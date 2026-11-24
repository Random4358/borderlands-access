"""Line tests straight from the engine's own code (an experimental option, on by default).

The game's line-test functions (FastTrace and friends) give fixed answers when the mod manager
calls them. They are "native" functions: their real work is C++ code inside Borderlands2.exe,
which the game's own scripts reach through an interpreter frame (FFrame) holding the
arguments as UnrealScript bytecode. This module calls that C++ code the same way the game's
scripts do, without going through the mod manager:

1. Find the code. The SDK gives the address of the Engine.Actor:FastTrace function object
   and its flags and parameter sizes. Those values are found in its memory, and the pointer
   just after them that points into the game's code section is the native code (checked
   against other native functions). Every read uses ReadProcessMemory, which reports a bad
   address instead of crashing.
2. Call it. A small machine-code thunk (x86, the game is 32-bit) calls it with an FFrame whose
   bytecode is: vector constant (end), vector constant (start), "optional argument left
   out" twice, end of arguments. The result is FastTrace's own answer: 1 = clear.
3. Crash guard. Before the very first call a marker file is written; it's removed once the
   call returns. If the game crashed during that call, the marker is still there next time,
   and the direct call is switched off for good (delete logs\\native_trace_attempt.txt to
   try again). Any failure along the way also switches it off, with the reason logged.

Everything is logged as "direct line test ...". Whether the answers make sense is checked by
the usual line test self-check (floor below you blocked, open air clear) before anything
relies on them.
"""

from __future__ import annotations

import os
import struct
from typing import Any, Callable

MOD_DIR = os.path.dirname(os.path.abspath(__file__))
MARKER = os.path.join(MOD_DIR, "logs", "native_trace_attempt.txt")
FUNC_NATIVE = 0x400

# UnrealScript bytecode tokens (Unreal Engine 3)
EX_VECTOR_CONST = 0x23
EX_EMPTY_PARM_VALUE = 0x4A
EX_END_FUNCTION_PARMS = 0x16

# cdecl thunk(fn, this, frame, result): mov ecx,this; push result; push frame; call fn (thiscall)
THUNK = bytes([
    0x55,                    # push ebp
    0x8B, 0xEC,              # mov ebp, esp
    0x8B, 0x4D, 0x0C,        # mov ecx, [ebp+12]   this
    0xFF, 0x75, 0x14,        # push [ebp+20]       result
    0xFF, 0x75, 0x10,        # push [ebp+16]       frame
    0xFF, 0x55, 0x08,        # call [ebp+8]        fn (callee pops its 2 arguments)
    0x5D,                    # pop ebp
    0xC3,                    # ret
])
RET8 = bytes([0xC2, 0x08, 0x00])   # ret 8: stands in for the frame's logging functions

# FFrame layout (32-bit UE3): FOutputDevice (vtable, 3 flags) then Node, Object, Code, Locals,
# PreviousFrame, OutParms.
FRAME_SIZE = 64
OFF_VTABLE, OFF_NODE, OFF_OBJECT, OFF_CODE, OFF_LOCALS, OFF_PREV, OFF_OUTPARMS = 0, 16, 20, 24, 28, 32, 36


def bytecode(end: tuple, start: tuple) -> bytes:
    """FastTrace(TraceEnd, TraceStart, [BoxExtent], [bTraceComplex]) as script bytecode."""
    return (bytes([EX_VECTOR_CONST]) + struct.pack("<3f", *end)
            + bytes([EX_VECTOR_CONST]) + struct.pack("<3f", *start)
            + bytes([EX_EMPTY_PARM_VALUE, EX_EMPTY_PARM_VALUE, EX_END_FUNCTION_PARMS]))


def frame_bytes(vtable: int, node: int, obj: int, code: int, locals_: int) -> bytes:
    b = bytearray(FRAME_SIZE)
    struct.pack_into("<I", b, OFF_VTABLE, vtable)
    for off, v in ((OFF_NODE, node), (OFF_OBJECT, obj), (OFF_CODE, code), (OFF_LOCALS, locals_)):
        struct.pack_into("<I", b, off, v)
    return bytes(b)


def find_native_pointer(read: Callable[[int, int], bytes | None], func_addr: int, flags: int,
                        params_size: int, ret_offset: int, text: tuple[int, int]) -> tuple[int, int] | None:
    """(offset, code address) of a native function object's code pointer, or None.

    Looks in the function object's memory for its FunctionFlags value, then its ParamsSize and
    ReturnValueOffset (two 16-bit values) shortly after, and takes the first 4-byte value after
    those that points into the game's code section."""
    blob = read(func_addr, 0x200)
    if not blob:
        return None
    lo, hi = text
    for f_off in range(0, len(blob) - 4, 4):
        if struct.unpack_from("<I", blob, f_off)[0] != flags:
            continue
        sizes = struct.pack("<HH", params_size, ret_offset)
        s_off = blob.find(sizes, f_off + 4, f_off + 0x20)
        if s_off < 0:
            continue
        start = (s_off + 4 + 3) // 4 * 4
        for p_off in range(start, min(len(blob) - 4, start + 0x20), 4):
            v = struct.unpack_from("<I", blob, p_off)[0]
            if lo <= v < hi:
                return p_off, v
    return None


def text_section(read: Callable[[int, int], bytes | None], base: int) -> tuple[int, int] | None:
    """Address range of the game's code (.text) from its PE header."""
    dos = read(base, 0x40)
    if not dos or dos[:2] != b"MZ":
        return None
    nt = struct.unpack_from("<I", dos, 0x3C)[0]
    hdr = read(base + nt, 0x18)
    if not hdr or hdr[:4] != b"PE\0\0":
        return None
    n_sections = struct.unpack_from("<H", hdr, 6)[0]
    opt_size = struct.unpack_from("<H", hdr, 20)[0]
    table = read(base + nt + 0x18 + opt_size, 40 * n_sections)
    if not table:
        return None
    for i in range(n_sections):
        name = table[40 * i:40 * i + 8].rstrip(b"\0")
        vsize, vaddr = struct.unpack_from("<II", table, 40 * i + 8)
        if name == b".text":
            return base + vaddr, base + vaddr + vsize
    return None


class DirectTrace:
    def __init__(self) -> None:
        self.state = "unknown"      # "unknown", "ready" or "off"
        self.reason = ""
        self.enabled = True         # the option
        self.fn = 0
        self.func_obj = 0
        self._keep: list = []       # buffers that must stay alive
        self._call: Any = None
        self.first_done = False

    def _note(self, text: str) -> None:
        try:
            from . import trace

            trace.note("direct line test: " + text)
        except Exception:
            pass

    def _off(self, why: str) -> None:
        self.state, self.reason = "off", why
        self._note(f"off: {why}")

    # ------------------------------------------------------------ setting up
    def prepare(self) -> bool:
        if self.state != "unknown":
            return self.state == "ready"
        if not self.enabled:
            self._off("switched off in the settings")
            return False
        if os.path.exists(MARKER):
            self._off("the game stopped during the first direct call last time, so it stays off "
                      "(delete logs\\native_trace_attempt.txt to try again)")
            return False
        try:
            import ctypes
            from ctypes import wintypes
        except Exception as e:  # noqa: BLE001
            self._off(f"no ctypes ({e})")
            return False
        if ctypes.sizeof(ctypes.c_void_p) != 4:
            self._off("not the 32-bit game")
            return False
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                          ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        k32.GetModuleHandleW.restype = ctypes.c_void_p
        k32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
        k32.VirtualAlloc.restype = ctypes.c_void_p
        k32.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
        proc = k32.GetCurrentProcess()

        def read(addr: int, n: int) -> bytes | None:
            buf = ctypes.create_string_buffer(n)
            got = ctypes.c_size_t(0)
            if not k32.ReadProcessMemory(proc, ctypes.c_void_p(addr), buf, n, ctypes.byref(got)) or got.value != n:
                return None
            return buf.raw

        try:
            import unrealsdk

            func = unrealsdk.find_object("Function", "Engine.Actor:FastTrace")
            self.func_obj = int(func._get_address())
            flags, psize, roff = int(func.FunctionFlags), int(func.ParamsSize), int(func.ReturnValueOffset)
        except Exception as e:  # noqa: BLE001
            self._off(f"couldn't find Engine.Actor:FastTrace ({type(e).__name__}: {e})")
            return False
        if not flags & FUNC_NATIVE:
            self._off(f"FastTrace isn't marked native (flags {flags:#x})")
            return False
        base = k32.GetModuleHandleW(None) or 0
        text = text_section(read, base)
        if text is None:
            self._off("couldn't read the game's code section")
            return False
        found = find_native_pointer(read, self.func_obj, flags, psize, roff, text)
        if found is None:
            self._off(f"couldn't find FastTrace's code pointer (flags {flags:#x}, params {psize}, return at {roff})")
            return False
        off, self.fn = found
        # Check the same field in another native function points to different code.
        try:
            other = unrealsdk.find_object("Function", "Engine.Actor:Trace")
            blob = read(int(other._get_address()) + off, 4)
            other_fn = struct.unpack("<I", blob)[0] if blob else 0
        except Exception:
            other_fn = 0
        if not (text[0] <= other_fn < text[1]) or other_fn == self.fn:
            self._off(f"code pointer check failed (offset {off:#x}: FastTrace {self.fn:#x}, Trace {other_fn:#x})")
            return False
        # machine code: the thunk and a do-nothing logging function, in executable memory
        mem = k32.VirtualAlloc(None, 0x1000, 0x3000, 0x40)   # MEM_COMMIT|MEM_RESERVE, PAGE_EXECUTE_READWRITE
        if not mem:
            self._off("couldn't allocate memory for the call")
            return False
        ctypes.memmove(mem, THUNK, len(THUNK))
        ctypes.memmove(mem + 0x40, RET8, len(RET8))
        vtable = (ctypes.c_uint32 * 16)(*([mem + 0x40] * 16))
        self._keep = [vtable]
        self.vtable = ctypes.addressof(vtable)
        proto = ctypes.CFUNCTYPE(None, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32)
        self._call = proto(mem)
        self._ctypes = ctypes
        self.state = "ready"
        self._note(f"found FastTrace's code at {self.fn:#x} (field offset {off:#x}, code section "
                   f"{text[0]:#x}-{text[1]:#x}); Trace's is at {other_fn:#x}")
        return True

    # ------------------------------------------------------------ calling
    def fast_trace(self, actor: Any, start: tuple, end: tuple) -> bool:
        """True = clear, False = blocked. Raises if the direct call isn't available."""
        if not self.prepare():
            raise RuntimeError(f"direct line test off: {self.reason}")
        ctypes = self._ctypes
        try:
            obj = int(actor._get_address())
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"no address for {actor!r}: {e}") from e
        code = ctypes.create_string_buffer(bytecode(end, start))
        locals_ = ctypes.create_string_buffer(256)
        frame = ctypes.create_string_buffer(frame_bytes(self.vtable, self.func_obj, obj,
                                                        ctypes.addressof(code), ctypes.addressof(locals_)))
        result = ctypes.c_uint32(0xDEAD)
        if not self.first_done:
            try:
                os.makedirs(os.path.dirname(MARKER), exist_ok=True)
                with open(MARKER, "w", encoding="utf-8") as f:
                    f.write("The mod is calling the engine's line test directly for the first time.\n")
                    f.flush()
                    os.fsync(f.fileno())
            except Exception:
                pass
        try:
            self._call(self.fn, obj, ctypes.addressof(frame), ctypes.addressof(result))
        except OSError as e:   # Windows turns a bad memory access inside the call into this
            try:
                os.remove(MARKER)
            except Exception:
                pass
            self._off(f"the call failed inside the game: {e}")
            raise RuntimeError(str(e)) from e
        if not self.first_done:
            self.first_done = True
            try:
                os.remove(MARKER)
            except Exception:
                pass
            self._note(f"first call returned {result.value:#x}")
        if result.value == 0xDEAD:
            self._off("the call didn't write a result")
            raise RuntimeError("no result")
        return result.value != 0


direct = DirectTrace()
