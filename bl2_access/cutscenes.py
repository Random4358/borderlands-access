"""Audio descriptions for cutscenes.

Descriptions are written ahead of time (descriptions/*.json, one file per cutscene) and spoken
at set times while the cutscene plays, between the lines of dialogue where possible:

    {"key": "MegaIntro", "title": "Opening intro", "lines": [[0.2, "Ink drawings ..."], ...]}

Two kinds of cutscene:
* Pre-rendered videos (WillowGame/Movies/*.bik), named by their file name ("MegaIntro"). Timed
  from when the game starts the video.
* Scenes the engine plays live (a Matinee), named "<map>/<scene object>", e.g.
  "Glacial_P/Main_Sequence.SeqAct_Interp_3". Timed by the scene's own playback position, so
  pausing doesn't put the descriptions out of step.

How the game starts each kind is found at run time: every candidate hook is tried, and what
fires is logged ("cutscene:" lines in diagnostic.log).

Capture mode (off by default, for writing new descriptions): while a cutscene plays, the game's
own screenshot command runs once a second, and logs/cutscene_capture.txt records the cutscene's
name and time for each, so the pictures can be matched up and described.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any

from . import game

MOD_DIR = os.path.dirname(os.path.abspath(__file__))
DESC_DIR = os.path.join(MOD_DIR, "descriptions")
LATE = 4.0            # seconds: a line this far behind (skipped ahead, loading hitch) isn't spoken
CAPTURE_EVERY = 1.0   # seconds between screenshots in capture mode
_ID = "bl2_access_cutscenes"

# (hook, kind): "movie" carries a movie name; "stop" ends a movie; "texture" is a movie playing
# on an in-world screen; "cinematic" turns the engine's cinematic mode on or off.
MOVIE_HOOKS = [
    ("Engine.PlayerController:ClientPlayMovie", "movie"),
    ("WillowGame.WillowPlayerController:ClientPlayMovie", "movie"),
    ("Engine.PlayerController:ClientStopMovie", "stop"),
    ("WillowGame.WillowPlayerController:ClientStopMovie", "stop"),
    ("Engine.TextureMovie:Play", "texture"),
    ("Engine.TextureMovie:Stop", "texture_stop"),
    ("Engine.PlayerController:SetCinematicMode", "cinematic"),
    ("Engine.PlayerController:ClientSetCinematicMode", "cinematic"),
    ("WillowGame.WillowPlayerController:SetCinematicMode", "cinematic"),
    ("WillowGame.WillowPlayerController:ClientSetCinematicMode", "cinematic"),
]
CLASS_WORDS = re.compile(r"(?i)(movie|cinematic|matinee|interp|bink)")


def _arg(args: Any, *names: str) -> Any:
    for n in names:
        try:
            return getattr(args, n)
        except Exception:
            continue
    return None


def matinee_key(interp: Any) -> str:
    """'<map>/<scene object>' for a SeqAct_Interp, e.g. 'Glacial_P/Main_Sequence.SeqAct_Interp_3'."""
    try:
        path = str(interp._path_name())
    except Exception:
        return ""
    m = re.match(r"([^.:]+)\.TheWorld:PersistentLevel\.(.+)", path)
    return f"{m.group(1)}/{m.group(2)}" if m else path


class Cutscenes:
    def __init__(self) -> None:
        self.enabled = True
        self.capture = False
        self.lib: dict[str, dict] | None = None
        self.key = ""                 # cutscene playing now ("" = none)
        self.kind = ""                # "movie" or "matinee"
        self.started = 0.0
        self.interp: Any = None
        self.idx = 0
        self.lines: list = []
        self.cinematic = False
        self.next_check = 0.0
        self.next_shot = 0.0
        self.shots = 0
        self.registered: list[tuple[str, Any]] = []
        self.seen: set[str] = set()
        self.lock = threading.Lock()
        self.last_tick = 0.0
        self.timer: threading.Thread | None = None

    # ------------------------------------------------------------ descriptions
    def library(self) -> dict[str, dict]:
        if self.lib is None:
            self.lib = {}
            try:
                names = sorted(os.listdir(DESC_DIR))
            except OSError:
                names = []
            for name in names:
                if not name.endswith(".json"):
                    continue
                try:
                    with open(os.path.join(DESC_DIR, name), encoding="utf-8") as f:
                        d = json.load(f)
                    d["lines"] = sorted((float(t), str(s)) for t, s in d.get("lines", []))
                    self.lib[str(d.get("key") or name[:-5]).lower()] = d
                except Exception as e:  # noqa: BLE001
                    self._note(f"cutscene: couldn't read {name}: {e}")
        return self.lib

    def _note(self, text: str) -> None:
        from . import trace

        trace.note(text)

    # ------------------------------------------------------------ starting and stopping
    def begin(self, key: str, kind: str, interp: Any = None, via: str = "") -> None:
        if not key or key == self.key:
            return
        d = self.library().get(key.lower())
        self.key, self.kind, self.interp = key, kind, interp
        self.started, self.idx = time.perf_counter(), 0
        self.lines = d["lines"] if d else []
        self.next_shot = 0.0
        self._note(f"cutscene: {kind} '{key}' started{f' via {via}' if via else ''}; "
                   f"{f'{len(self.lines)} description lines' if d else 'no description written yet'}")
        if self.capture:
            self._capture_line(f"start {kind} {key}")
        if kind == "movie" and self.lines:
            self._start_timer()

    def end(self, why: str = "") -> None:
        if not self.key:
            return
        self._note(f"cutscene: '{self.key}' ended{f' ({why})' if why else ''} after {self.position():.1f} s")
        if self.capture:
            self._capture_line(f"end {self.key}")
        self.key, self.kind, self.interp, self.lines, self.idx = "", "", None, [], 0

    def position(self) -> float:
        """Seconds into the cutscene playing now."""
        if self.kind == "matinee" and self.interp is not None:
            try:
                return float(self.interp.Position)
            except Exception:
                pass
        return time.perf_counter() - self.started

    # ------------------------------------------------------------ hooks
    def on_hook(self, kind: str, path: str, obj: Any, args: Any) -> None:
        if kind not in self.seen:   # what fires, once each, so support can be completed from the log
            self.seen.add(kind)
            self._note(f"cutscene hook fired: {path}")
        if kind == "movie":
            name = str(_arg(args, "MovieName") or "")
            self.begin(os.path.splitext(os.path.basename(name.replace("\\", "/")))[0], "movie", via=path)
        elif kind == "stop":
            if self.kind == "movie":
                self.end("stopped")
        elif kind == "texture":
            name = str(getattr(obj, "Name", "") or "")
            self._note(f"cutscene: in-world screen video '{name}' started")
            if not self.key and name.lower() in self.library():
                self.begin(name, "movie", via=path)
        elif kind == "texture_stop":
            name = str(getattr(obj, "Name", "") or "")
            if self.key and name.lower() == self.key.lower():
                self.end("screen video stopped")
        elif kind == "cinematic":
            on = bool(_arg(args, "bInCinematicMode"))
            self.set_cinematic(on)

    def set_cinematic(self, on: bool) -> None:
        if on == self.cinematic:
            return
        self.cinematic = on
        self._note(f"cutscene: cinematic mode {'on' if on else 'off'}")
        self.next_check = 0.0
        if not on and self.kind == "matinee":
            self.end("cinematic mode off")

    def register(self) -> None:
        from unrealsdk import hooks as uhooks
        from unrealsdk.hooks import Type

        self.unregister()
        for path, kind in MOVIE_HOOKS:
            def cb(obj: Any, args: Any, _r: Any, _f: Any, kind: str = kind, path: str = path) -> None:
                try:
                    self.on_hook(kind, path, obj, args)
                except Exception:
                    pass

            try:
                uhooks.add_hook(path, Type.PRE, _ID, cb)
                self.registered.append((path, Type.PRE))
            except Exception:
                continue
        self._note(f"cutscene: watching {len(self.registered)} of {len(MOVIE_HOOKS)} hooks: "
                   + ", ".join(p.split(".", 1)[1] for p, _k in self.registered))

    def unregister(self) -> None:
        try:
            from unrealsdk import hooks as uhooks
        except Exception:
            return
        for path, kind in self.registered:
            try:
                uhooks.remove_hook(path, kind, _ID)
            except Exception:
                pass
        self.registered.clear()

    # ------------------------------------------------------------ every frame
    def _playing_matinee(self) -> Any:
        try:
            import unrealsdk

            for m in unrealsdk.find_all("SeqAct_Interp", exact=False):
                try:
                    if bool(m.bIsPlaying) and "Default__" not in str(m.Name):
                        return m
                except Exception:
                    continue
        except Exception:
            pass
        return None

    def tick(self) -> None:
        now = time.perf_counter()
        pc = game.pc()
        # Cinematic mode, read directly as well as from the hooks (whichever works).
        try:
            if pc is not None and hasattr(pc, "bCinematicMode"):
                self.set_cinematic(bool(pc.bCinematicMode))
        except Exception:
            pass
        # In a cinematic: which scene is playing (checked twice a second)?
        if self.cinematic and self.kind != "movie" and now >= self.next_check:
            self.next_check = now + 0.5
            m = self._playing_matinee()
            if m is not None:
                key = matinee_key(m)
                if key != self.key:
                    try:
                        length = float(m.InterpData.InterpLength)
                        extra = f", {length:.0f} s long"
                    except Exception:
                        extra = ""
                    self.begin(key, "matinee", interp=m, via=f"scene object{extra}")
            elif self.kind == "matinee":
                self.end("scene finished")
        if not self.key:
            return
        self.last_tick = now
        self.speak_due()
        # Capture mode: a screenshot a second.
        if self.capture and pc is not None and now >= self.next_shot:
            self.next_shot = now + CAPTURE_EVERY
            try:
                pc.ConsoleCommand("shot", False)
            except Exception:
                try:
                    pc.ConsoleCommand("shot")
                except Exception:
                    pass
            self.shots += 1
            self._capture_line(f"shot {self.shots} {self.key} at {self.position():.2f}")

    def speak_due(self) -> None:
        """Speak the description lines whose time has come."""
        if not self.enabled:
            return
        with self.lock:
            if not self.lines:
                return
            t = self.position()
            due = []
            while self.idx < len(self.lines) and self.lines[self.idx][0] <= t:
                at, text = self.lines[self.idx]
                self.idx += 1
                if t - at <= LATE:
                    due.append(text)
        if due:
            from .speech import speech

            for text in due:
                speech.say(text, interrupt=False)

    def _start_timer(self) -> None:
        """A full-screen video may stop the game's frame updates; then this keeps the lines
        coming (it does nothing while frames are running)."""
        if self.timer is not None and self.timer.is_alive():
            return
        key = self.key

        def run() -> None:
            while self.key == key and self.kind == "movie":
                time.sleep(0.2)
                if time.perf_counter() - self.last_tick > 0.5:
                    try:
                        self.speak_due()
                    except Exception:
                        pass
                if self.idx >= len(self.lines):
                    break

        self.timer = threading.Thread(target=run, name="bl2_access cutscene lines", daemon=True)
        self.timer.start()

    def _capture_line(self, text: str) -> None:
        from .trace import LOG_DIR

        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            with open(os.path.join(LOG_DIR, "cutscene_capture.txt"), "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}\n")
        except Exception:
            pass

    def write_class_inventory(self) -> str | None:
        """Once: the game's movie / cinematic / matinee classes and their functions, to
        logs/cutscene_classes.txt, so how videos are started can be pinned down."""
        import unrealsdk

        from .trace import LOG_DIR

        path = os.path.join(LOG_DIR, "cutscene_classes.txt")
        if os.path.exists(path):
            return None
        try:
            classes = [c for c in unrealsdk.find_all("Class", exact=False)
                       if CLASS_WORDS.search(str(c.Name)) and "gfx" not in str(c.Name).lower()]
        except Exception:
            return None
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for cls in sorted(classes, key=lambda c: str(c.Name)):
                try:
                    f.write(f"\n[{cls._path_name()}]\n")
                    child = cls.Children
                    while child is not None:
                        try:
                            f.write(f"  {child.Class.Name}: {child.Name}\n")
                        except Exception:
                            pass
                        child = child.Next
                except Exception:
                    continue
            # PlayerController functions mentioning movies or cinematics
            try:
                for fn in unrealsdk.find_all("Function", exact=False):
                    n = str(fn.Name)
                    if CLASS_WORDS.search(n) and "gfx" not in n.lower():
                        f.write(f"function {fn._path_name()}\n")
            except Exception:
                pass
        return path


cutscenes = Cutscenes()
