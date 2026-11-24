"""Screen reader output.

Order of preference:
  1. Prism (ethindp/prism) -> prism.dll, which picks NVDA when NVDA is running.
  2. NVDA Controller Client directly -> nvdaControllerClient32.dll / nvdaControllerClient.dll.
  3. Console log only (so the mod never crashes because speech is missing).

All DLLs must be 32-bit (x86) because Borderlands 2 is a 32-bit game.
Put them in this mod's ``lib`` folder.
"""

from __future__ import annotations

import ctypes
import os
import struct

MOD_DIR = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.join(MOD_DIR, "lib")
IS_32_BIT = struct.calcsize("P") == 4


def _log(msg: str) -> None:
    print(f"[Borderlands Access] {msg}")


def _candidate_dirs() -> list[str]:
    dirs = [LIB_DIR, MOD_DIR]
    try:
        import sys

        dirs.append(os.path.dirname(sys.executable))
    except Exception:
        pass
    return [d for d in dirs if os.path.isdir(d)]


def _find(names: list[str]) -> str | None:
    for d in _candidate_dirs():
        for n in names:
            p = os.path.join(d, n)
            if os.path.isfile(p):
                return p
    return None


class _Backend:
    name = "none"

    def speak(self, text: str, interrupt: bool) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def stop(self) -> None:
        pass

    def close(self) -> None:
        pass


class PrismBackend(_Backend):
    """ctypes wrapper over the Prism C API (prism_init / prism_registry_* / prism_backend_*)."""

    def __init__(self, dll_path: str, stdcall: bool = False) -> None:
        if hasattr(os, "add_dll_directory"):
            self._dll_dir = os.add_dll_directory(os.path.dirname(dll_path))
        loader = ctypes.WinDLL if stdcall else ctypes.CDLL
        lib = loader(dll_path)
        self.lib = lib

        lib.prism_init.restype = ctypes.c_void_p
        lib.prism_init.argtypes = [ctypes.c_void_p]
        lib.prism_shutdown.restype = None
        lib.prism_shutdown.argtypes = [ctypes.c_void_p]
        lib.prism_registry_create_best.restype = ctypes.c_void_p
        lib.prism_registry_create_best.argtypes = [ctypes.c_void_p]
        lib.prism_backend_speak.restype = ctypes.c_int
        lib.prism_backend_speak.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_bool]
        lib.prism_backend_free.restype = None
        lib.prism_backend_free.argtypes = [ctypes.c_void_p]

        self._output = getattr(lib, "prism_backend_output", None)
        if self._output is not None:
            self._output.restype = ctypes.c_int
            self._output.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_bool]
        self._stop = getattr(lib, "prism_backend_stop", None)
        if self._stop is not None:
            self._stop.restype = ctypes.c_int
            self._stop.argtypes = [ctypes.c_void_p]

        self.ctx = lib.prism_init(None)
        if not self.ctx:
            raise OSError("prism_init returned NULL")

        init = lib.prism_backend_initialize
        init.restype = ctypes.c_int
        init.argtypes = [ctypes.c_void_p]
        self.backend = None
        for make in (self._create_nvda, lambda: lib.prism_registry_create_best(self.ctx)):
            b = make()
            if b and init(b) in (0, 15):  # PRISM_OK / ALREADY_INITIALIZED
                self.backend = b
                break
            if b:
                lib.prism_backend_free(b)
        if not self.backend:
            lib.prism_shutdown(self.ctx)
            raise OSError("Prism found no usable speech backend")

        self.name = "Prism"
        name_fn = getattr(lib, "prism_backend_name", None)
        if name_fn is not None:
            name_fn.restype = ctypes.c_char_p
            name_fn.argtypes = [ctypes.c_void_p]
            try:
                raw = name_fn(self.backend)
                if raw:
                    self.name = f"Prism ({raw.decode('utf-8', 'replace')})"
            except Exception:
                pass

    def _create_nvda(self):
        """Ask Prism for NVDA explicitly; fall back to create_best if anything is missing."""
        lib = self.lib
        reg_id = getattr(lib, "prism_registry_id", None)
        create = getattr(lib, "prism_registry_create", None)
        if reg_id is None or create is None:
            return None
        try:
            reg_id.restype = ctypes.c_uint64
            reg_id.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
            create.restype = ctypes.c_void_p
            create.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
            bid = reg_id(self.ctx, b"NVDA")
            if not bid:
                return None
            return create(self.ctx, bid) or None
        except Exception:
            return None

    def speak(self, text: str, interrupt: bool) -> bool:
        data = text.encode("utf-8")
        fn = self._output or self.lib.prism_backend_speak
        err = fn(self.backend, data, interrupt)
        if err != 0 and fn is self._output:
            err = self.lib.prism_backend_speak(self.backend, data, interrupt)
        return err == 0

    def stop(self) -> None:
        if self._stop is not None:
            self._stop(self.backend)

    def close(self) -> None:
        try:
            self.lib.prism_backend_free(self.backend)
            self.lib.prism_shutdown(self.ctx)
        except Exception:
            pass


def _find_python64() -> str | None:
    """A 64-bit Python on this PC to run the Prism bridge (the game's own Python is 32-bit)."""
    override = os.path.join(MOD_DIR, "helper", "python_path.txt")
    if os.path.isfile(override):
        with open(override, encoding="utf-8") as f:
            p = f.read().strip().strip('"')
        if os.path.isfile(p):
            return p
    import glob

    roots = [os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Python"),
             os.environ.get("ProgramW6432", r"C:\Program Files"), "C:\\"]
    found: list[str] = []
    for r in roots:
        found += glob.glob(os.path.join(r, "Python3*", "pythonw.exe"))
    # Newest version first; skip 32-bit installs (folder names end in -32).
    found = [p for p in found if not os.path.basename(os.path.dirname(p)).endswith("-32")]

    def ver(p: str) -> int:
        digits = "".join(ch for ch in os.path.basename(os.path.dirname(p)) if ch.isdigit())
        return int(digits or 0)

    found.sort(key=ver, reverse=True)
    return found[0] if found else None


class PrismBridgeBackend(_Backend):
    """Prism running in a separate 64-bit Python process (see helper/prism_bridge.py)."""

    def __init__(self) -> None:
        import socket
        import subprocess

        script = os.path.join(MOD_DIR, "helper", "prism_bridge.py")
        dll = os.path.join(MOD_DIR, "helper", "prism64", "prism.dll")
        if not (os.path.isfile(script) and os.path.isfile(dll)):
            raise OSError("helper/prism64/prism.dll missing")
        python = _find_python64()
        if python is None:
            raise OSError("no 64-bit Python found for the Prism bridge (see helper/python_path.txt)")

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.bind(("127.0.0.1", 0))
        self.port = probe.getsockname()[1]
        probe.close()

        self.proc = subprocess.Popen(
            [python, "-I", script, str(self.port), str(os.getpid())],
            cwd=os.path.dirname(script),
            creationflags=0x08000000,  # CREATE_NO_WINDOW
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:  # stop Windows reporting "port unreachable" as instant recv errors
            self.sock.ioctl(socket.SIO_UDP_CONNRESET, False)
        except Exception:
            pass
        self.sock.settimeout(0.25)
        backend_name = None
        import time

        deadline = time.monotonic() + 8.0  # time for Python + Prism to start
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise OSError(f"Prism bridge exited with code {self.proc.returncode}")
            self.sock.sendto(b"H", ("127.0.0.1", self.port))
            try:
                data, _addr = self.sock.recvfrom(1024)
                if data[:1] == b"N":
                    backend_name = data[1:].decode("utf-8", "replace")
                    break
            except socket.timeout:
                continue
            except OSError:
                time.sleep(0.25)
        if backend_name is None:
            self.close()
            raise OSError("Prism bridge did not respond")
        self.name = f"Prism ({backend_name})"

    def _send(self, data: bytes) -> None:
        self.sock.sendto(data, ("127.0.0.1", self.port))

    def speak(self, text: str, interrupt: bool) -> bool:
        self._send(b"S" + (b"1" if interrupt else b"0") + text.encode("utf-8")[:60000])
        return True

    def stop(self) -> None:
        self._send(b"X")

    def close(self) -> None:
        try:
            self._send(b"Q")
        except Exception:
            pass
        try:
            self.proc.wait(timeout=2)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        try:
            self.sock.close()
        except Exception:
            pass


class NvdaBackend(_Backend):
    name = "NVDA (controller client)"

    def __init__(self, dll_path: str) -> None:
        lib = ctypes.WinDLL(dll_path)
        lib.nvdaController_testIfRunning.restype = ctypes.c_ulong
        lib.nvdaController_speakText.argtypes = [ctypes.c_wchar_p]
        lib.nvdaController_speakText.restype = ctypes.c_ulong
        lib.nvdaController_cancelSpeech.restype = ctypes.c_ulong
        if lib.nvdaController_testIfRunning() != 0:
            raise OSError("NVDA is not running")
        self.lib = lib
        self._braille = getattr(lib, "nvdaController_brailleMessage", None)
        if self._braille is not None:
            self._braille.argtypes = [ctypes.c_wchar_p]

    def speak(self, text: str, interrupt: bool) -> bool:
        if interrupt:
            self.lib.nvdaController_cancelSpeech()
        ok = self.lib.nvdaController_speakText(text) == 0
        if self._braille is not None:
            try:
                self._braille(text)
            except Exception:
                pass
        return ok

    def stop(self) -> None:
        self.lib.nvdaController_cancelSpeech()


class Speech:
    def __init__(self) -> None:
        self.backend: _Backend | None = None
        self.last_text = ""
        self.enabled = True

    def start(self, prefer: str = "prism", prism_stdcall: bool = False) -> str:
        self.close()
        order = ["prism", "nvda"] if prefer == "prism" else ["nvda", "prism"]
        errors = []
        for kind in order:
            try:
                if kind == "prism":
                    # A 32-bit prism.dll in lib/ loads in-process; otherwise use the 64-bit bridge.
                    path = _find(["prism.dll"])
                    if path:
                        try:
                            self.backend = PrismBackend(path, stdcall=prism_stdcall)
                        except Exception as e:  # noqa: BLE001 - e.g. wrong bitness
                            errors.append(f"in-process prism: {e}")
                    if self.backend is None:
                        self.backend = PrismBridgeBackend()
                else:
                    path = _find(["nvdaControllerClient32.dll", "nvdaControllerClient.dll"])
                    if path:
                        self.backend = NvdaBackend(path)
                    else:
                        errors.append("nvdaControllerClient DLL not found in lib folder")
            except Exception as e:  # noqa: BLE001 - any loader failure falls through
                errors.append(f"{kind}: {e}")
            if self.backend is not None:
                break
        if self.backend is None:
            _log("No screen reader output available. " + "; ".join(errors))
            if not IS_32_BIT:
                _log("Note: this Python is 64-bit; the game needs 32-bit DLLs.")
            return "console only"
        _log(f"Speech backend: {self.backend.name}")
        return self.backend.name

    def say(self, text: str, interrupt: bool = True) -> None:
        if not text:
            return
        self.last_text = text
        self.said_count = getattr(self, "said_count", 0) + 1   # lets the menu move sound wait for a real move
        _log(f"SAY: {text}")
        if not self.enabled or self.backend is None:
            return
        try:
            self.backend.speak(text, interrupt)
        except Exception as e:  # noqa: BLE001
            _log(f"Speech failed: {e}")

    def repeat(self) -> None:
        if self.last_text:
            self.say(self.last_text)

    def stop(self) -> None:
        if self.backend is not None:
            try:
                self.backend.stop()
            except Exception:
                pass

    def close(self) -> None:
        if self.backend is not None:
            self.backend.close()
        self.backend = None


speech = Speech()
