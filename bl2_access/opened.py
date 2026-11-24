"""Which containers have been opened, so they drop off the scanner and stop making a sound.

The game's own "can this be used" values that the mod guessed at don't change when a chest is
opened in Borderlands 2, so two things are used instead:

1. What you opened. When you press Use while the interaction prompt has just named a
   container in reach, that container counts as opened for the rest of this visit to the level.
2. What the game changes. At that moment the container's plain values (true/false, numbers,
   names) are noted, and again a second and a half later. A value that changes the same way
   on two different containers is the game's own "opened" marker: it's saved in
   opened_flag.json and from then on any container showing it counts as opened, also ones
   opened before you arrived or by someone else. Each change is logged ("container opened:").
"""

from __future__ import annotations

import json
import os
from typing import Any

from . import game

MOD_DIR = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(MOD_DIR, "opened_flag.json")
CHECK_AFTER = 1.5        # seconds after Use to look at what changed
VOTES_NEEDED = 2         # containers that must agree before a value is trusted
SKIP = ("time", "render", "tick", "location", "rotation", "velocity", "count", "seed")


def _plain(v: Any) -> Any:
    """A comparable form of simple values; None for anything else."""
    if isinstance(v, bool) or isinstance(v, int) or isinstance(v, str):
        return v
    name = getattr(v, "name", None)   # enums
    if isinstance(name, str):
        return name
    return None


def snapshot(actor: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        props = list(actor.Class._properties())
    except Exception:
        return out
    for p in props:
        try:
            name = str(p.Name)
        except Exception:
            continue
        if any(w in name.lower() for w in SKIP):
            continue
        try:
            v = _plain(getattr(actor, name))
        except Exception:
            continue
        if v is not None:
            out[name] = v
    return out


def _path(actor: Any) -> str:
    try:
        return str(actor._path_name())
    except Exception:
        return str(id(actor))


class Opened:
    def __init__(self) -> None:
        self.map = ""
        self.used: set[str] = set()                   # containers you opened, this visit
        self.pending: list[tuple[float, Any, str, dict]] = []
        self.votes: dict[str, set[str]] = {}          # "name=value" -> containers that showed it
        self.flag: tuple[str, Any] | None = None      # the learned (property, opened value)
        self.load()

    # ------------------------------------------------------------ asking
    def is_opened(self, actor: Any) -> bool:
        if _path(actor) in self.used:
            return True
        if self.flag is not None:
            name, value = self.flag
            try:
                return _plain(getattr(actor, name)) == value
            except Exception:
                return False
        return False

    # ------------------------------------------------------------ learning
    def note_use(self, actor: Any, now: float) -> None:
        path = _path(actor)
        if path in self.used:
            return
        self.used.add(path)
        self.pending.append((now + CHECK_AFTER, game.weak(actor), path, snapshot(actor)))

    def tick(self, pc: Any, now: float) -> None:
        try:
            name = str(pc.WorldInfo.GetMapName(True))
        except Exception:
            name = self.map
        if name != self.map:
            self.map, self.used, self.pending = name, set(), []
        due = [p for p in self.pending if now >= p[0]]
        if not due:
            return
        self.pending = [p for p in self.pending if now < p[0]]
        for _t, ptr, path, before in due:
            actor = game.deref(ptr)
            after = snapshot(actor) if actor is not None else {}
            changed = {k: (before[k], after[k]) for k in before if k in after and after[k] != before[k]}
            self._note(f"container opened: {path.split('.')[-1]}: "
                       + (", ".join(f"{k} {a!r} -> {b!r}" for k, (a, b) in changed.items()) or "no plain value changed"))
            for k, (_a, b) in changed.items():
                key = f"{k}={json.dumps(b)}"
                self.votes.setdefault(key, set()).add(path)
                if self.flag is None and len(self.votes[key]) >= VOTES_NEEDED:
                    self.flag = (k, b)
                    self.save()
                    self._note(f"container opened: the game marks opened containers with {k} = {b!r}; using that now")

    # ------------------------------------------------------------ saving
    def load(self) -> None:
        try:
            with open(STORE, encoding="utf-8") as f:
                d = json.load(f)
            self.flag = (str(d["property"]), d["value"])
        except Exception:
            self.flag = None

    def save(self) -> None:
        if self.flag is None:
            return
        try:
            with open(STORE, "w", encoding="utf-8") as f:
                json.dump({"property": self.flag[0], "value": self.flag[1]}, f)
        except Exception:
            pass

    def _note(self, text: str) -> None:
        try:
            from . import trace

            trace.note(text)
        except Exception:
            pass


opened = Opened()
