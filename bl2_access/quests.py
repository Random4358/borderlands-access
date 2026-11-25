"""Active mission and objectives, for the scanner's "Quest objectives" category.

Confirmed names:
* ``pc.WorldInfo.GRI.MissionTracker`` with ``ActiveMission`` (a MissionDefinition) and
  ``MissionList`` (entries with ``MissionDef`` and ``Status``) - from the bl2-missionselector mod.
* MissionDefinition text fields ``MissionName``, ``MissionDescription``, ``MissionSummary``,
  ``TurnInDescription``, ``MissionGiver``, ``MissionTurnInLocation``; MissionObjectiveDefinition
  ``ProgressMessage`` - from the game's own localisation files.

Not confirmed (found by looking at the live objects instead of guessing one name): which property
holds a mission's list of objectives, the per-objective progress counts, and each objective's
required count. Everything here reads fresh each call and keeps no game objects between frames.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from . import game

# MissionTracker status values (bl2-missionselector's MissionStatus enum).
NOT_STARTED, ACTIVE, REQUIRED_DONE, READY_TO_TURN_IN, COMPLETE, FAILED = range(6)
STATUS_TEXT = {
    ACTIVE: "in progress",
    REQUIRED_DONE: "required objectives complete",
    READY_TO_TURN_IN: "ready to turn in",
    COMPLETE: "complete",
    FAILED: "failed",
}


@dataclass
class Objective:
    text: str
    progress: int | None = None
    needed: int | None = None

    @property
    def done(self) -> bool:
        return self.progress is not None and self.needed is not None and self.progress >= self.needed

    def spoken(self) -> str:
        if self.progress is not None and self.needed and self.needed > 1:
            return f"{self.text}, {self.progress} of {self.needed}"
        if self.done:
            return f"{self.text}, done"
        return self.text


@dataclass
class MissionInfo:
    name: str
    status: int | None = None
    summary: str = ""
    objectives: list[Objective] = field(default_factory=list)
    turn_in_to: str = ""
    turn_in_text: str = ""
    stage_known: bool = False        # objectives are just the current stage (objective set)
    stage_summary: str = ""          # what this stage is about, when the game has it
    marked: list[str] = field(default_factory=list)   # objectives the game has put a marker on

    @property
    def ready_to_turn_in(self) -> bool:
        return self.status == READY_TO_TURN_IN

    def spoken(self) -> str:
        parts = [f"Mission: {self.name}"]
        if self.status in STATUS_TEXT and self.status != ACTIVE:
            parts.append(STATUS_TEXT[self.status].capitalize())
        if self.ready_to_turn_in:
            who = f" to {self.turn_in_to}" if self.turn_in_to else ""
            parts.append(f"Turn it in{who}")
            if self.turn_in_to:
                # How, since it isn't obvious (a tester couldn't hand in My First Gun).
                parts.append(f"Find {self.turn_in_to} in the scanner's People category or the mission contact entry, "
                             f"go right up to them, and press Use when you hear Talk to {self.turn_in_to}")
        else:
            todo = [o for o in self.objectives if not o.done]
            if not self.stage_known:
                # Without the current stage, the mission's list includes later stages that
                # haven't started. The game's markers show what's live, so those come first.
                # A marker can keep the label of an objective you've already done (seen in
                # Blindsided: "Defend Claptrap" after it was done), so only unfinished ones count.
                marked = [o for o in todo if o.text in self.marked]
                now = bool(marked)
                todo = marked or todo
            else:
                now = True
            if todo:
                parts.append(("Now: " if now else "Objectives: ") + ". ".join(o.spoken() for o in todo))
            if self.stage_summary:
                parts.append(self.stage_summary)
            elif not todo and self.summary:
                parts.append(self.summary)
        return ". ".join(p.rstrip(". ") for p in parts if p)


def _text(obj: Any, name: str) -> str:
    try:
        v = getattr(obj, name)
    except Exception:
        return ""
    s = re.sub(r"<[^>]+>", "", str(v or ""))
    s = re.sub(r"\[/?-?[a-z_]+\]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def tracker(pc: Any) -> Any:
    try:
        return pc.WorldInfo.GRI.MissionTracker
    except Exception:
        return None


def _array_props(obj: Any) -> list[tuple[str, Any]]:
    """(name, value) of every array property on an object or struct, by reflection."""
    out = []
    try:
        props = list(obj.Class._properties()) if hasattr(obj, "Class") else list(obj._type._properties())
    except Exception:
        return out
    for p in props:
        try:
            if p.Class.Name != "ArrayProperty":
                continue
            out.append((str(p.Name), getattr(obj, p.Name)))
        except Exception:
            continue
    return out


def _objective_defs(mission: Any) -> list[Any]:
    """The mission's MissionObjectiveDefinitions. Tries the likely name first, then any array
    whose elements are objective definitions."""
    for name in ("MissionObjectives", "Objectives"):
        try:
            arr = list(getattr(mission, name))
            if arr and "Objective" in game.class_name(arr[0]):
                return arr
        except Exception:
            continue
    for _name, arr in _array_props(mission):
        try:
            items = list(arr)
        except Exception:
            continue
        if items and game.class_name(items[0]) == "MissionObjectiveDefinition":
            return items
    return []


def _entry_for(trk: Any, mission: Any) -> Any:
    try:
        for e in trk.MissionList:
            if e.MissionDef == mission:
                return e
    except Exception:
        pass
    return None


def _progress_counts(entry: Any, n: int) -> list[int] | None:
    """Per-objective progress from the MissionList entry: the int array as long as the objectives."""
    if entry is None or n == 0:
        return None
    for name in ("ObjectivesProgress", "ObjectiveProgress"):
        try:
            vals = [int(v) for v in getattr(entry, name)]
            if len(vals) >= n:
                return vals[:n]
        except Exception:
            continue
    for _name, arr in _array_props(entry):
        try:
            vals = list(arr)
        except Exception:
            continue
        if len(vals) >= n and all(isinstance(v, int) and not isinstance(v, bool) for v in vals):
            return [int(v) for v in vals[:n]]
    return None


_entry_logged = False


def _live_objective_text(trk: Any, mission: Any) -> str:
    """The first unfinished objective of the mission's live stage, or ''."""
    if trk is None or mission is None:
        return ""
    entry = _entry_for(trk, mission)
    stage = _active_set(entry)
    if stage is None:
        return ""
    try:
        stage_defs = list(stage.ObjectiveDefinitions)
    except Exception:
        return ""
    defs = _objective_defs(mission)
    counts = _progress_counts(entry, len(defs))
    for i, d in enumerate(defs):
        if not any(d == s for s in stage_defs):
            continue
        o = Objective(_text(d, "ProgressMessage") or _text(d, "Description"), counts[i] if counts else None, _needed(d))
        if o.text and not o.done:
            return o.text
    return ""


def _active_set(entry: Any) -> Any:
    """The current objective set from a mission's progress entry: whichever field holds a
    MissionObjectiveSetDefinition (the likely names first)."""
    if entry is None:
        return None
    for name in ("ActiveObjectiveSet", "CurrentObjectiveSet", "ObjectiveSet"):
        try:
            v = getattr(entry, name)
        except Exception:
            continue
        if v is not None and "ObjectiveSet" in game.class_name(v):
            return v
    for _n, v in _fields(entry):
        if _is_obj(v) and game.class_name(v) == "MissionObjectiveSetDefinition":
            return v
    return None


def _needed(obj_def: Any) -> int | None:
    for name in ("ObjectiveCount", "Count", "NumRequired", "RequiredCount"):
        try:
            v = getattr(obj_def, name)
            if isinstance(v, int) and not isinstance(v, bool):
                return v
        except Exception:
            continue
    return None


def active_mission(pc: Any) -> MissionInfo | None:
    from . import trace

    trk = tracker(pc)
    if trk is None:
        return None
    try:
        mission = trk.ActiveMission
    except Exception:
        mission = None
    if mission is None:
        return None
    name = _text(mission, "MissionName") or game.pretty(str(getattr(mission, "Name", "Mission")))
    entry = _entry_for(trk, mission)
    status = None
    try:
        status = int(entry.Status) if entry is not None else None
    except Exception:
        pass
    defs = _objective_defs(mission)
    counts = _progress_counts(entry, len(defs))
    # The current stage: the mission's progress entry points at its active objective set.
    stage = _active_set(entry)
    stage_defs = None
    if stage is not None:
        try:
            stage_defs = list(stage.ObjectiveDefinitions)
        except Exception:
            stage_defs = None
    objectives = []
    for i, d in enumerate(defs):
        if stage_defs is not None and not any(d == s for s in stage_defs):
            continue
        text = _text(d, "ProgressMessage") or _text(d, "Description")
        if not text:
            continue
        objectives.append(Objective(text, counts[i] if counts else None, _needed(d)))
    info = MissionInfo(
        name=name,
        status=status,
        summary=_text(mission, "MissionSummary") or _text(mission, "MissionDescription"),
        objectives=objectives,
        turn_in_to=_text(mission, "MissionTurnInLocation"),
        turn_in_text=_text(mission, "TurnInDescription"),
        stage_known=stage_defs is not None,
        stage_summary=(_text(stage, "MissionSummaryOverride") or _text(stage, "MissionDescriptionOverride"))
        if stage is not None else "",
        marked=[w.label for w in waypoints(pc) if w.active and w.label != "Objective waypoint"],
    )
    global _entry_logged
    if not _entry_logged and entry is not None:
        _entry_logged = True
        trace.note("mission entry fields: " + ", ".join(
            f"{n}={game.class_name(v) or type(v).__name__}" for n, v in _fields(entry)))
    trace.note(f"mission '{name}' status={status} objectives={len(defs)} "
               f"progress={'yes' if counts else 'no'} turn_in='{info.turn_in_to}' "
               f"stage={'none' if stage is None else getattr(stage, 'Name', '?')} "
               f"now={[o.text for o in objectives if not o.done]} marked={info.marked}")
    return info


def matches_person(person_name: str, wanted: str) -> bool:
    a, b = person_name.lower().strip(), wanted.lower().strip()
    return bool(a and b) and (a == b or a in b or b in a)


# ------------------------------------------------------------------ objective waypoints
@dataclass
class Waypoint:
    label: str
    ptr: Any                                   # WeakPointer to the marked actor, or None
    pos: tuple[float, float, float] | None     # where it is (fixed points have no actor)
    active: bool                               # belongs to the tracked mission


_logged_layout = False


def _fields(v: Any) -> list[tuple[str, Any]]:
    try:
        props = list(v._type._properties())
    except Exception:
        return []
    out = []
    for p in props:
        try:
            out.append((str(p.Name), getattr(v, p.Name)))
        except Exception:
            continue
    return out


def _is_obj(v: Any) -> bool:
    return v is not None and hasattr(v, "Class") and not isinstance(v, (str, bytes))


def _as_vector(v: Any) -> tuple[float, float, float] | None:
    try:
        x, y, z = v.X, v.Y, v.Z
        if all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in (x, y, z)):
            return (float(x), float(y), float(z))
    except Exception:
        pass
    return None


def _placed(actor: Any) -> bool:
    """Has a real position (Info actors such as the mission tracker sit at 0,0,0)."""
    loc = game.location(actor)
    return loc is not None and any(abs(c) > 1 for c in loc)


def _dig(v: Any, found: dict, depth: int) -> None:
    """Collect the mission, objective, marked actor and position from a waypoint record of
    unknown layout: objects by class, structs and arrays by walking their fields."""
    if v is None or depth < 0 or isinstance(v, (str, bytes, int, float, bool)):
        return
    if _is_obj(v):
        cls = game.class_name(v)
        chain = ""
        try:
            chain = " ".join(str(s.Name) for s in v.Class._superfields())
        except Exception:
            chain = cls
        if cls == "MissionDefinition":
            found.setdefault("mission", v)
        elif cls == "MissionObjectiveDefinition":
            found.setdefault("objective", v)
        elif "ActorComponent" in chain or cls.endswith("Component"):
            try:
                owner = v.Owner
            except Exception:
                owner = None
            if owner is not None and _placed(owner):
                found.setdefault("actor", owner)
            for name, sub in _fields_of_obj(v):
                _dig(sub, found, depth - 1)
        elif " Actor" in f" {chain}" and _placed(v):
            found.setdefault("actor", v)
        return
    vec = _as_vector(v)
    if vec is not None:
        if any(abs(c) > 1 for c in vec):
            found.setdefault("pos", vec)
        return
    fields = _fields(v)
    if fields:
        for name, sub in fields:
            _dig(sub, found, depth - 1)
        return
    try:
        items = list(v)[:16]
    except Exception:
        return
    for sub in items:
        _dig(sub, found, depth - 1)


def _fields_of_obj(obj: Any) -> list[tuple[str, Any]]:
    """Struct/object fields of a component that may hold the waypoint data (e.g. WaypointInfo)."""
    out = []
    try:
        props = list(obj.Class._properties())
    except Exception:
        return out
    for p in props:
        try:
            if p.Class.Name in ("StructProperty", "ObjectProperty") and "Waypoint" in str(p.Name) \
                    or str(p.Name) in ("MissionObjective", "LinkedMission", "AssociatedMissionObjective"):
                out.append((str(p.Name), getattr(obj, p.Name)))
        except Exception:
            continue
    return out


def waypoints(pc: Any) -> list[Waypoint]:
    """Objective markers the game is showing (MissionTracker.MissionWaypoints)."""
    global _logged_layout
    from . import trace

    trk = tracker(pc)
    if trk is None:
        return []
    try:
        records = list(trk.MissionWaypoints)
    except Exception:
        return []
    try:
        active = trk.ActiveMission
    except Exception:
        active = None
    if records and not _logged_layout:
        _logged_layout = True
        trace.note("waypoint record fields: " + ", ".join(
            f"{n}={game.class_name(v) or type(v).__name__}" for n, v in _fields(records[0])))
    live = _live_objective_text(trk, active)
    out: list[Waypoint] = []
    seen: set = set()
    for rec in records:
        found: dict = {}
        _dig(rec, found, 4)
        actor, pos = found.get("actor"), found.get("pos")
        if actor is None and pos is None:
            continue
        if actor is not None:
            pos = game.location(actor) or pos
            if _marker_only(actor):
                # A marker actor of its own (WillowWaypoint), not a thing: where it floats is
                # all there is to it, so treat it as a fixed point (and put it on the ground).
                actor = None
        if actor is None and pos is not None:
            pos = grounded(pc, pos)
        key = tuple(round(c / 50) for c in pos) if pos else id(actor)
        if key in seen:
            continue
        seen.add(key)
        mission, objective = found.get("mission"), found.get("objective")
        is_active = mission is None or active is None or mission == active
        text = (_text(objective, "ProgressMessage") if objective is not None else "") or "Objective waypoint"
        if is_active and live:
            text = live   # a marker can keep the label of a finished objective (Blindsided)
        if not is_active and mission is not None:
            text = f"{_text(mission, 'MissionName') or 'Other mission'}: {text}"
        out.append(Waypoint(text, game.weak(actor) if actor is not None else None, pos, is_active))
    return out


def _marker_only(actor: Any) -> bool:
    """A pure marker actor (nothing to use or pick up), as opposed to the thing a marker is on."""
    return "waypoint" in game.class_name(actor).lower()


_ground: dict[tuple, tuple] = {}


def grounded(pc: Any, pos: tuple) -> tuple:
    """A marker with nothing at it can float well above the ground (Find new gear is 3.5 m up,
    over flat open ground): the place to go is the floor right below it. A marker on a ledge or a
    floor has that floor just below it, so it stays where it is. Measured once per marker."""
    key = tuple(round(c / 50) for c in pos)
    if key in _ground:
        return _ground[key]
    if not game.FLOOR_SEEN:
        return pos
    pawn = game.player_pawn(pc)
    if pawn is None:
        return pos
    floor = game.ground_z(pawn, pos[0], pos[1], pos[2] + 20, depth=900)
    if floor is None:
        return pos            # nothing below (or tracing failed): try again next time
    out = pos
    if pos[2] - floor > 150:
        out = (pos[0], pos[1], floor + 60)
        from . import trace

        trace.note(f"marker at ({pos[0]:.0f}, {pos[1]:.0f}, {pos[2]:.0f}) floats {(pos[2] - floor) / 100:.1f} m "
                   f"above the ground; using the ground below it")
    _ground[key] = out
    return out


# ------------------------------------------------------------------ what an objective needs (for the log)
_objectives_recorded: set[str] = set()


def _value_text(v: Any) -> str:
    try:
        if v is None or isinstance(v, (bool, int, float, str)):
            return repr(v)
        name = getattr(v, "Name", None)
        if name is not None:
            return f"<{game.class_name(v)} {name}>"
        try:
            items = list(v)
            return "[" + ", ".join(_value_text(x) for x in items[:8]) + (", ..." if len(items) > 8 else "") + "]"
        except Exception:
            pass
        return str(v)[:120]
    except Exception as e:  # noqa: BLE001
        return f"(unreadable: {type(e).__name__})"


def _properties(obj: Any) -> list[tuple[str, str]]:
    out = []
    try:
        props = list(obj.Class._properties())
    except Exception:
        try:
            props = list(obj._type._properties())
        except Exception:
            return out
    for p in props:
        try:
            out.append((str(p.Name), _value_text(getattr(obj, str(p.Name)))))
        except Exception:
            continue
    return out


def record_objective(pc: Any, label: str, marker: tuple | None) -> str | None:
    """Once per objective: the tracked mission's live objectives (every field of their
    definitions) and everything usable within 40 m of the marker, to logs/objectives.txt. To
    find out what an objective needs that standing at its marker doesn't do."""
    if label in _objectives_recorded or marker is None:
        return None
    _objectives_recorded.add(label)
    import math
    import os
    import time

    from .trace import LOG_DIR

    trk = tracker(pc)
    lines = [f"\n==== {time.strftime('%Y-%m-%d %H:%M:%S')} objective '{label}', marker at "
             f"({marker[0]:.0f}, {marker[1]:.0f}, {marker[2]:.0f})"]
    try:
        mission = trk.ActiveMission if trk is not None else None
        entry = _entry_for(trk, mission) if mission is not None else None
        stage = _active_set(entry)
        lines.append(f"mission {getattr(mission, 'Name', None)}, stage {getattr(stage, 'Name', None)}")
        for d in (list(stage.ObjectiveDefinitions) if stage is not None else _objective_defs(mission)):
            lines.append(f"objective definition {getattr(d, 'Name', '?')}:")
            lines += [f"  {n} = {v}" for n, v in _properties(d)]
    except Exception as e:  # noqa: BLE001
        lines.append(f"(couldn't read the objective: {type(e).__name__}: {e})")
    near = []
    for a in game.world_actors(["WillowInteractiveObject", "WillowPickup", "WillowVendingMachineBase",
                                "WillowAIPawn", "WillowInventory"]):
        q = game.location(a)
        if q is None:
            continue
        d = math.dist(q[:2], marker[:2])
        if d > 4000:
            continue
        info = []
        for field in ("InteractiveObjectDefinition", "Inventory", "DefinitionData", "AIClass", "MissionDirector",
                      "SimpleAnimState", "bCanBeUsed", "UsabilityType"):
            try:
                v = getattr(a, field)
            except Exception:
                continue
            info.append(f"{field}={_value_text(v)}")
        near.append((d, f"{game.class_name(a)} {getattr(a, 'Name', '?')} '{game.display_name(a)}' at "
                        f"({(q[0] - marker[0]) / 100:+.1f}, {(q[1] - marker[1]) / 100:+.1f}) m, "
                        f"{(q[2] - marker[2]) / 10:+.0f} dm; " + ", ".join(info)))
    near.sort()
    lines.append(f"usable things, pickups and characters within 40 m of the marker ({len(near)}):")
    lines += [f"  {d / 100:5.1f} m  {t}" for d, t in near[:80]]
    path = os.path.join(LOG_DIR, "objectives.txt")
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:
        return None
    return path


# ------------------------------------------------------------------ one-time class inventory
CLASS_WORDS = re.compile(r"(?i)mission|objective|waypoint|marker|compass|quest")


def write_class_inventory() -> str | None:
    """Write the game's mission/objective/waypoint classes (with their properties and functions)
    to logs/mission_classes.txt, once. Class objects are permanent, so this is safe to read."""
    import os

    import unrealsdk

    from .trace import LOG_DIR

    path = os.path.join(LOG_DIR, "mission_classes.txt")
    if os.path.exists(path):
        return None
    try:
        classes = [c for c in unrealsdk.find_all("Class", exact=False) if CLASS_WORDS.search(str(c.Name))]
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
    return path
