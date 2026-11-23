"""Hook-discovery tools, used to add readers for menus we don't cover yet (inventory, vendors, ...).

Console commands (open the console with ~):
  bla_trace menus          trace every function of the menus open right now (+ list/dialog classes)
  bla_trace <Class> ...    trace every function of the named classes, e.g. bla_trace StatusMenuExGFxMovie
  bla_trace off            stop tracing
  bla_dump <Class>         write the class's functions and properties to logs/dump_<Class>.txt

While tracing, every call is appended to logs/trace.log with its arguments, so you can open a
menu, move the highlight a few times, and then see which function fired and what text it carried.
Keyboard F2 toggles "bla_trace menus" with spoken feedback.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any

import unrealsdk
from unrealsdk import hooks as uhooks
from unrealsdk.hooks import Type

from .speech import MOD_DIR, speech

LOG_DIR = os.path.join(MOD_DIR, "logs")
_ID = "bl2_access_trace"
SKIP_PACKAGES = {"Core", "Engine"}
# Per-frame functions, matched anywhere in the name. FilterAxisInput is polled every frame per
# stick axis; the menu reader logs real stick pushes to diagnostic.log instead.
NOISY = ("Tick", "Render", "Draw", "FilterAxisInput")
PER_FUNC_LIMIT = 25
EXTRA_CLASSES = [
    "WillowScrollingList",
    "WillowScrollingListDataProviderFrontEnd",
    "WillowScrollingListDataProviderPause",
    "FrontendGFxMovie",
    "WillowGFxDialogBox",
    "WillowGFxUIManager",
]

_hooked: list[str] = []
_counts: dict[str, int] = {}
_log = None

# Diagnostics: while the mod is still being fitted to the game, key presses and menu events are
# written to logs/diagnostic.log (capped) so problems can be diagnosed from the file afterwards.
DIAG_LIMIT = 2000
_diag = None
_diag_lines = 0


def diag_start() -> None:
    global _diag, _diag_lines
    diag_stop()
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        _diag = open(os.path.join(LOG_DIR, "diagnostic.log"), "w", encoding="utf-8")
        _diag_lines = 0
        note(f"==== diagnostics start {time.strftime('%Y-%m-%d %H:%M:%S')}")
    except Exception as e:  # noqa: BLE001
        print(f"[Borderlands Access] diagnostics unavailable: {e}")
        _diag = None


def diag_stop() -> None:
    global _diag
    if _diag is not None:
        try:
            _diag.close()
        except Exception:
            pass
    _diag = None


def note(text: str) -> None:
    """One line in logs/diagnostic.log (no-op when diagnostics are off)."""
    global _diag_lines
    if _diag is None or _diag_lines >= DIAG_LIMIT:
        return
    _diag_lines += 1
    try:
        _diag.write(f"{time.strftime('%H:%M:%S')} {text}\n")
        if _diag_lines == DIAG_LIMIT:
            _diag.write("... limit reached, further lines dropped\n")
        _diag.flush()
    except Exception:
        pass


QUIET = False  # automatic startup trace: log to file only, don't flood the console


def _out(line: str) -> None:
    if not QUIET:
        print(f"[trace] {line}")
    if _log is not None:
        _log.write(line + "\n")
        _log.flush()


def _render(v: Any) -> str:
    if v is None:
        return "None"
    if isinstance(v, (int, float, bool)):
        return str(v)
    if isinstance(v, str):
        return repr(v[:120])
    try:
        label = f"<{v.Class.Name} {v.Name}"
        # Items: include the name the player sees, so the trace shows which item is highlighted.
        if str(v.Class.Name).startswith("Willow") and hasattr(v, "GetShortHumanReadableName"):
            try:
                label += f" '{v.GetShortHumanReadableName()}'"
            except Exception:
                pass
        return label + ">"
    except Exception:
        pass
    try:
        return "[" + ", ".join(_render(x) for x in list(v)[:8]) + "]"
    except Exception:
        return type(v).__name__


def _args_text(args: Any) -> str:
    parts = []
    try:
        for prop in args._type._properties():
            try:
                parts.append(f"{prop.Name}={_render(getattr(args, prop.Name))}")
            except Exception:
                parts.append(f"{prop.Name}=?")
    except Exception:
        pass
    return ", ".join(parts)


def _functions(cls: Any):
    """(hook path, function name) for functions defined on cls and its non-engine parents."""
    for struct in cls._superfields():
        try:
            pkg = struct.Outer.Name
        except Exception:
            continue
        if str(pkg) in SKIP_PACKAGES:
            continue
        child = struct.Children
        while child is not None:
            try:
                if child.Class.Name == "Function":
                    yield f"{pkg}.{struct.Name}:{child.Name}", str(child.Name)
            except Exception:
                pass
            child = child.Next


def _make_cb(path: str):
    def cb(obj: Any, args: Any, _ret: Any, _func: Any) -> None:
        n = _counts.get(path, 0)
        if n >= PER_FUNC_LIMIT:
            return
        _counts[path] = n + 1
        who = ""
        try:
            who = str(obj.Name)
        except Exception:
            pass
        _out(f"{time.strftime('%H:%M:%S')} {path} [{who}] ({_args_text(args)})"
             + ("  ...further calls muted" if n + 1 == PER_FUNC_LIMIT else ""))
    return cb


def start(class_names: list[str]) -> int:
    global _log
    stop(quiet=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    _log = open(os.path.join(LOG_DIR, "trace.log"), "w" if QUIET else "a", encoding="utf-8")
    _out(f"==== trace start {time.strftime('%Y-%m-%d %H:%M:%S')}: {', '.join(class_names)}")
    seen: set[str] = set()
    for cn in class_names:
        try:
            cls = unrealsdk.find_class(cn)
        except Exception:
            _out(f"class not found: {cn}")
            continue
        for path, fname in _functions(cls):
            if path in seen or any(n in fname for n in NOISY):
                continue
            seen.add(path)
            try:
                uhooks.add_hook(path, Type.PRE, _ID, _make_cb(path))
                _hooked.append(path)
            except Exception:
                pass
    _out(f"hooked {len(_hooked)} functions")
    return len(_hooked)


def stop(quiet: bool = False) -> None:
    global _log
    for path in _hooked:
        try:
            uhooks.remove_hook(path, Type.PRE, _ID)
        except Exception:
            pass
    _hooked.clear()
    _counts.clear()
    if _log is not None:
        if not quiet:
            _out("==== trace stop")
        _log.close()
        _log = None


# Inventory, skills, missions, vendors etc. do their work in GFxObject "panel" classes rather
# than in the menu's main movie class, so the F2 trace also hooks those.
PANEL_WORDS = re.compile(r"(?i)statusmenu|inventory|itemcard|skill|vending|mission|challenge|badass"
                         r"|backpack|equip|bank|panel")


def panel_classes() -> list[str]:
    try:
        classes = unrealsdk.find_all("Class", exact=False)
    except Exception:
        return []
    out = []
    for c in classes:
        try:
            name = str(c.Name)
            if not PANEL_WORDS.search(name):
                continue
            if not any("GFx" in str(s.Name) for s in c._superfields()):
                continue
            out.append(name)
        except Exception:
            continue
    return sorted(set(out))


def open_menu_classes() -> list[str]:
    from .controls import menus

    names = set(menus.open.values()) | set(panel_classes())
    try:
        for m in unrealsdk.find_all("GFxMoviePlayer", exact=False):
            try:
                if "Default__" in m._path_name():
                    continue
                if getattr(m, "bMovieIsOpen", True):
                    names.add(str(m.Class.Name))
            except Exception:
                continue
    except Exception:
        pass
    return sorted(names) + EXTRA_CLASSES


def auto_start() -> None:
    """Quietly trace the menu/list/dialog classes from launch (diagnostics mode)."""
    global QUIET
    QUIET = True
    n = start(EXTRA_CLASSES)
    note(f"auto trace hooked {n} functions of {', '.join(EXTRA_CLASSES)}")


def toggle_menus() -> None:
    global QUIET
    QUIET = False
    if _hooked:
        stop()
        speech.say("Menu trace stopped. Log saved.")
        return
    classes = open_menu_classes()
    n = start(classes)
    speech.say(f"Menu trace started on {len(classes)} classes, {n} functions. Press F2 again to stop.")


def dump(class_name: str) -> str:
    cls = unrealsdk.find_class(class_name)
    os.makedirs(LOG_DIR, exist_ok=True)
    path = os.path.join(LOG_DIR, f"dump_{class_name}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"{class_name}\n\nFUNCTIONS\n")
        for hp, _ in _functions(cls):
            f.write(f"  {hp}\n")
        f.write("\nPROPERTIES\n")
        for prop in cls._properties():
            try:
                f.write(f"  {prop.Name}: {prop.Class.Name}\n")
            except Exception:
                continue
    return path


def _cmd_trace(line: str, cmd_len: int) -> None:
    rest = line[cmd_len:].split()
    if not rest or rest[0].lower() == "off":
        stop()
        print("[trace] stopped")
    elif rest[0].lower() == "menus":
        print(f"[trace] hooked {start(open_menu_classes())} functions")
    else:
        print(f"[trace] hooked {start(rest)} functions")


def _cmd_dump(line: str, cmd_len: int) -> None:
    rest = line[cmd_len:].split()
    for cn in rest:
        try:
            print(f"[trace] wrote {dump(cn)}")
        except Exception as e:  # noqa: BLE001
            print(f"[trace] {cn}: {e}")


def register_commands() -> None:
    try:
        from unrealsdk import commands
    except ImportError:
        print("[Borderlands Access] console commands unavailable")
        return

    for name, cb in (("bla_trace", _cmd_trace), ("bla_dump", _cmd_dump)):
        try:
            if not commands.has_command(name):
                commands.add_command(name, cb)
        except Exception as e:  # noqa: BLE001
            print(f"[Borderlands Access] command {name}: {e}")


def unregister_commands() -> None:
    stop(quiet=True)
    try:
        from unrealsdk import commands
    except ImportError:
        return
    for name in ("bla_trace", "bla_dump"):
        try:
            commands.remove_command(name)
        except Exception:
            pass
