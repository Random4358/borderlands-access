"""64-bit Prism speech bridge.

Borderlands 2 is a 32-bit game, and Prism only ships 64-bit Windows DLLs, so the mod can't load
Prism directly. The mod starts this script with your normal 64-bit Python instead; it loads
Prism (which talks to NVDA) and speaks whatever the mod sends over a localhost UDP socket.

    python prism_bridge.py <port> <parent_pid>

Messages (UTF-8):  "S1<text>" speak, interrupting   "S0<text>" speak, queued
                   "X" stop speech                    "Q" quit
The bridge exits by itself when the game process (parent_pid) goes away.
"""

from __future__ import annotations

import ctypes
import os
import socket
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DLL_DIR = os.path.join(HERE, "prism64")
PRISM_OK = 0
PRISM_ERROR_ALREADY_INITIALIZED = 15


def load_prism():
    os.add_dll_directory(DLL_DIR)
    lib = ctypes.CDLL(os.path.join(DLL_DIR, "prism.dll"))  # PRISM_CALL is __cdecl
    P = ctypes.c_void_p
    sig = {
        "prism_init": (P, [P]),
        "prism_shutdown": (None, [P]),
        "prism_registry_id": (ctypes.c_uint64, [P, ctypes.c_char_p]),
        "prism_registry_create": (P, [P, ctypes.c_uint64]),
        "prism_registry_create_best": (P, [P]),
        "prism_backend_initialize": (ctypes.c_int, [P]),
        "prism_backend_name": (ctypes.c_char_p, [P]),
        "prism_backend_speak": (ctypes.c_int, [P, ctypes.c_char_p, ctypes.c_bool]),
        "prism_backend_output": (ctypes.c_int, [P, ctypes.c_char_p, ctypes.c_bool]),
        "prism_backend_stop": (ctypes.c_int, [P]),
        "prism_backend_free": (None, [P]),
    }
    for name, (res, args) in sig.items():
        fn = getattr(lib, name)
        fn.restype = res
        fn.argtypes = args
    return lib


def make_backend(lib, ctx):
    """Prefer NVDA explicitly; otherwise whatever Prism thinks is best."""
    candidates = []
    nvda_id = lib.prism_registry_id(ctx, b"NVDA")
    if nvda_id:
        candidates.append(lambda: lib.prism_registry_create(ctx, nvda_id))
    candidates.append(lambda: lib.prism_registry_create_best(ctx))
    for make in candidates:
        b = make()
        if not b:
            continue
        err = lib.prism_backend_initialize(b)
        if err in (PRISM_OK, PRISM_ERROR_ALREADY_INITIALIZED):
            return b
        lib.prism_backend_free(b)
    return None


def parent_alive(pid: int) -> bool:
    if pid <= 0:
        return True
    k32 = ctypes.WinDLL("kernel32")
    k32.OpenProcess.restype = ctypes.c_void_p
    h = k32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if not h:
        return False
    try:
        return k32.WaitForSingleObject(ctypes.c_void_p(h), 0) == 0x102  # WAIT_TIMEOUT
    finally:
        k32.CloseHandle(ctypes.c_void_p(h))


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 47820
    parent = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    lib = load_prism()
    ctx = lib.prism_init(None)
    if not ctx:
        return 2
    backend = make_backend(lib, ctx)
    if not backend:
        lib.prism_shutdown(ctx)
        return 3

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", port))
    sock.settimeout(1.0)
    name = (lib.prism_backend_name(backend) or b"unknown").decode("utf-8", "replace")
    reply_to = None
    try:
        while True:
            try:
                data, addr = sock.recvfrom(65535)
            except socket.timeout:
                if not parent_alive(parent):
                    break
                continue
            if addr[0] != "127.0.0.1" or not data:
                continue
            kind = data[:1]
            if kind == b"H":  # hello -> reply with backend name
                reply_to = addr
                sock.sendto(b"N" + name.encode("utf-8"), reply_to)
            elif kind == b"S" and len(data) >= 2:
                text = data[2:]
                interrupt = data[1:2] == b"1"
                if lib.prism_backend_output(backend, text, interrupt) != PRISM_OK:
                    lib.prism_backend_speak(backend, text, interrupt)
            elif kind == b"X":
                lib.prism_backend_stop(backend)
            elif kind == b"Q":
                break
    finally:
        lib.prism_backend_free(backend)
        lib.prism_shutdown(ctx)
    return 0


if __name__ == "__main__":
    sys.exit(main())
