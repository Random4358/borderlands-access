"""General reader for menus that aren't scrolling lists: inventory, skill tree, missions, vendors...

These menus keep their highlighted thing in Flash and in UnrealScript "panel" objects whose
names differ per menu. Rather than guessing those names, we compare the menu's object
references just before and just after a navigation press: whatever now points at an item,
skill or mission that it didn't point at before is what you just highlighted.

Only object *references* are read (never stored between frames), from the menu that has
input focus and from GFx panel objects it holds, two levels deep, with a cap on how many
properties are read per press.
"""

from __future__ import annotations

import re
import time
from typing import Any

from . import game
from .speech import speech

MAX_PROPS = 600          # properties read per snapshot
SETTLE = 0.05            # seconds after the press before looking (lets the game update)

# Menus that already have a dedicated reader.
HANDLED = ("FrontendGFxMovie", "OptionsGFxMovie", "WillowGFxDialogBox",
           "CharacterSelectionReduxGFxMovie", "WillowGFxMoviePressStart", "OnlineMessageGFxMovie")


def _clean(s: Any) -> str:
    t = re.sub(r"<[^>]+>", " ", str(s or ""))
    t = re.sub(r"\[/?-?[a-z_]+\]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return re.sub(r"\s+([.,;:!?])", r"\1", t)


def _call_str(obj: Any, *names: str) -> str:
    for n in names:
        try:
            v = getattr(obj, n)
            v = v() if callable(v) else v
        except Exception:
            continue
        v = _clean(v)
        if v and not v.startswith("$"):
            return v
    return ""


def kind_of(obj: Any) -> str | None:
    """What sort of selectable thing this is, or None if it's not one we read."""
    cls = game.class_name(obj)
    if not cls:
        return None
    if cls in ("WillowWeapon", "WillowShield", "WillowGrenadeMod", "WillowClassMod", "WillowArtifact",
               "WillowUsableItem", "WillowMissionItem", "WillowEquipAbleItem") or cls.startswith("WillowInventory"):
        return "item"
    if cls.endswith("SkillDefinition") or cls == "SkillDefinition":
        return "skill"
    if cls == "MissionDefinition":
        return "mission"
    if cls in ("ChallengeDefinition", "WillowChallengeDefinition"):
        return "challenge"
    return None


def describe(obj: Any) -> str:
    k = kind_of(obj)
    if k == "item":
        name = _call_str(obj, "GetShortHumanReadableName", "GetHumanReadableName") or game.display_name(obj)
        parts = [name]
        for label, getters in (("level", ("GetExpLevel", "ExpLevel")),):
            for g in getters:
                try:
                    v = getattr(obj, g)
                    v = v() if callable(v) else v
                    if isinstance(v, int) and v > 0:
                        parts.append(f"{label} {v}")
                        break
                except Exception:
                    continue
        try:
            if bool(obj.GetMark() == 2):  # favourite mark, if exposed
                parts.append("favourite")
        except Exception:
            pass
        return ", ".join(parts)
    if k == "skill":
        name = _call_str(obj, "SkillName") or game.pretty(str(getattr(obj, "Name", "Skill")))
        desc = _call_str(obj, "SkillDescription")
        return f"{name}. {desc}" if desc else name
    if k == "mission":
        name = _call_str(obj, "MissionName") or game.pretty(str(getattr(obj, "Name", "Mission")))
        summ = _call_str(obj, "MissionSummary", "MissionDescription")
        return f"{name}. {summ}" if summ else name
    if k == "challenge":
        name = _call_str(obj, "ChallengeName") or game.pretty(str(getattr(obj, "Name", "Challenge")))
        desc = _call_str(obj, "Description")
        return f"{name}. {desc}" if desc else name
    return ""


def _object_props(obj: Any) -> list[tuple[str, Any]]:
    out = []
    try:
        props = list(obj.Class._properties())
    except Exception:
        return out
    for p in props:
        try:
            if p.Class.Name not in ("ObjectProperty", "ComponentProperty"):
                continue
            out.append((str(p.Name), getattr(obj, p.Name)))
        except Exception:
            continue
    return out


def snapshot(movie: Any) -> dict[str, tuple[str, Any]]:
    """path -> (identity, object) for selectable things reachable from the menu, 2 levels deep.
    Objects are only used within this frame."""
    result: dict[str, tuple[str, Any]] = {}
    budget = [MAX_PROPS]

    def walk(obj: Any, prefix: str, depth: int) -> None:
        for name, val in _object_props(obj):
            if budget[0] <= 0:
                return
            budget[0] -= 1
            if val is None:
                result[prefix + name] = ("", None)
                continue
            if kind_of(val):
                try:
                    ident = val._path_name()
                except Exception:
                    ident = str(id(val))
                result[prefix + name] = (ident, val)
            elif depth > 0 and "GFxObject" in _class_chain(val):
                walk(val, prefix + name + ".", depth - 1)

    walk(movie, "", 2)
    return result


def _class_chain(obj: Any) -> str:
    try:
        return " ".join(str(s.Name) for s in obj.Class._superfields())
    except Exception:
        return game.class_name(obj)


class PanelReader:
    def __init__(self) -> None:
        self.pending: tuple[float, str, dict[str, tuple[str, Any]]] | None = None
        self.last_spoken = ""
        self.found_paths: dict[str, str] = {}  # movie class -> property path that tracked selection

    @staticmethod
    def focus_movie() -> Any:
        pc = game.pc()
        try:
            return pc.GFxUIManager.FindFocusMovie() if pc is not None else None
        except Exception:
            return None

    def before_nav(self) -> None:
        movie = self.focus_movie()
        cls = game.class_name(movie) if movie is not None else ""
        if not cls or cls in HANDLED:
            return
        snap = snapshot(movie)
        # Keep only identities: the objects themselves must not outlive this frame.
        self.pending = (time.perf_counter(), cls, {k: (v[0], None) for k, v in snap.items()})

    def tick(self) -> None:
        if self.pending is None or time.perf_counter() - self.pending[0] < SETTLE:
            return
        started, cls, before = self.pending
        self.pending = None
        from .status_reader import status

        if status.last_spoke >= started:  # the status menu reader already read this move
            return
        movie = self.focus_movie()
        if movie is None or game.class_name(movie) != cls:
            return
        after = snapshot(movie)
        changed = [(path, obj) for path, (ident, obj) in after.items()
                   if obj is not None and before.get(path, ("", None))[0] != ident]
        if not changed:
            return
        # Prefer the path that worked before in this menu, then names that sound like a selection.
        known = self.found_paths.get(cls)
        changed.sort(key=lambda pc: (pc[0] != known,
                                     not re.search(r"(?i)select|highlight|focus|current|hover|card", pc[0]),
                                     pc[0].count(".")))
        path, obj = changed[0]
        text = describe(obj)
        if not text:
            return
        from . import trace

        if self.found_paths.get(cls) != path:
            self.found_paths[cls] = path
            trace.note(f"panel reader: {cls} selection via {path} ({game.class_name(obj)})")
        self.last_spoken = text
        speech.say(text)


panels = PanelReader()
