"""Reading screens the mod has no dedicated reader for (licence, privacy policy, online
messages and the like).

When such a screen opens, the mod says its name and how to leave it ("A to accept or
continue, B to go back"), and hooks every function of that screen's class that takes text:
whatever text the game puts on the screen through them is read out, once each. The screen's
name and those functions are logged ("screen text:"), so proper support can be added later.
"""

from __future__ import annotations

import re
import time
from typing import Any

from . import game

CPF_PARM = 0x80
# Always-on overlays and screens with their own reader: never treated as unknown screens.
SKIP_WORDS = ("hud", "scope", "echo", "transition", "loading", "cinematic", "crosshair", "subtitle", "compass",
              "marker", "textchat", "notification", "pressstart", "statusmenu", "vending", "characterselection",
              "frontend", "pause", "dialogbox", "training", "questaccept", "fasttravel", "bank", "latentreward",
              "customization", "vehiclespawn", "lobby")
ALWAYS = ("OnlineMessageGFxMovie",)   # known, but its text isn't read anywhere else
MAX_TEXTS = 25
_ID = "bl2_access_screen_text"


def _str_params(func: Any) -> list[str]:
    out = []
    child = getattr(func, "Children", None)
    while child is not None:
        try:
            if child.Class.Name == "StrProperty" and int(getattr(child, "PropertyFlags", CPF_PARM)) & CPF_PARM:
                out.append(str(child.Name))
        except Exception:
            pass
        child = getattr(child, "Next", None)
    return out


def is_unknown(cls: str) -> bool:
    low = cls.lower()
    return cls in ALWAYS or ("movie" in low and not any(w in low for w in SKIP_WORDS))


class ScreenText:
    def __init__(self) -> None:
        self.hooked: dict[str, list[str]] = {}    # class -> hooked function paths
        self.spoken: set[str] = set()
        self.queue: list[str] = []
        self.count = 0
        self.last_add = 0.0
        self.registered: list[tuple[str, Any]] = []

    def opened(self, movie: Any, announce: bool) -> None:
        cls = game.class_name(movie)
        if not cls or not is_unknown(cls):
            return
        self.spoken, self.queue, self.count = set(), [], 0
        if cls not in self.hooked:
            self._hook(cls)
        if announce and cls not in ALWAYS:
            from .speech import speech

            name = re.sub(r"(?i)(willow)?gfx(movie)?", "", cls) or cls
            speech.say(f"{game.pretty(name)} screen. Press A or Enter to accept or continue, B or Escape to go back",
                       interrupt=False)

    def _hook(self, cls: str) -> None:
        from unrealsdk import hooks as uhooks
        from unrealsdk.hooks import Type

        from .status_reader import _functions

        paths = []
        for path, fname, func in _functions(cls):
            params = _str_params(func)
            if not params:
                continue

            def cb(obj: Any, args: Any, _r: Any, _f: Any, params: list = params) -> None:
                try:
                    for p in params:
                        self.add(getattr(args, p, ""))
                except Exception:
                    pass

            try:
                uhooks.add_hook(path, Type.PRE, _ID, cb)
                self.registered.append((path, Type.PRE))
                paths.append(f"{fname}({', '.join(params)})")
            except Exception:
                continue
        self.hooked[cls] = paths
        from . import trace

        trace.note(f"screen text: {cls}: reading text from {len(paths)} functions: {', '.join(paths[:15])}")

    def add(self, raw: Any) -> None:
        from .menu_reader import clean

        text = clean(raw)
        if len(text) < 2 or text in self.spoken or self.count >= MAX_TEXTS:
            return
        self.spoken.add(text)
        self.count += 1
        self.queue.append(text)
        self.last_add = time.perf_counter()

    def tick(self) -> None:
        """Read what's been put on the screen, once it has settled (texts come in bursts)."""
        if not self.queue or time.perf_counter() - self.last_add < 0.2:
            return
        from .speech import speech

        text = ". ".join(t.rstrip(". ") for t in self.queue)
        self.queue = []
        speech.say(text, interrupt=False)

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
        self.hooked.clear()


screen_text = ScreenText()
