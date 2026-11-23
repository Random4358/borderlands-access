"""Thin, defensive helpers over the Unreal objects we read.

Everything that touches a game property is wrapped so a missing property on one object
(or a future SDK change) degrades a single feature instead of throwing every frame.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Iterator

import unrealsdk
from mods_base import get_pc

try:
    from unrealsdk.unreal import WeakPointer
except ImportError:  # offline tests
    class WeakPointer:  # type: ignore[no-redef]
        def __init__(self, obj: Any = None) -> None:
            self._obj = obj

        def __call__(self) -> Any:
            return self._obj


def weak(obj: Any) -> Any:
    """Keep a game object between frames safely. The game deletes objects whenever a menu
    closes or a level loads; touching a deleted object through a plain reference crashes the
    game, but a WeakPointer just returns None."""
    return WeakPointer(obj)


def deref(ptr: Any) -> Any:
    try:
        return ptr() if ptr is not None else None
    except Exception:
        return None


UU_PER_TURN = 65536
RAD_PER_UU = 2 * math.pi / UU_PER_TURN
# Unreal units -> metres. BL2 is roughly 1 uu = 1 cm; tweak if distances feel wrong.
UU_PER_METRE = 100.0


def pc() -> Any:
    try:
        return get_pc()
    except Exception:
        return None


def player_pawn(controller: Any = None) -> Any:
    controller = controller or pc()
    try:
        return controller.Pawn if controller is not None else None
    except Exception:
        return None


def vec(x: float, y: float, z: float) -> Any:
    return unrealsdk.make_struct("Vector", X=x, Y=y, Z=z)


def rot(pitch: float, yaw: float, roll: float = 0) -> Any:
    return unrealsdk.make_struct("Rotator", Pitch=int(pitch) & 0xFFFF, Yaw=int(yaw) & 0xFFFF, Roll=int(roll))


def location(actor: Any) -> tuple[float, float, float] | None:
    try:
        l = actor.Location
        return (l.X, l.Y, l.Z)
    except Exception:
        return None


def signed_uu(v: int) -> int:
    v = int(v) & 0xFFFF
    return v - 65536 if v > 32767 else v


def view_angles(controller: Any) -> tuple[float, float]:
    """(yaw, pitch) in radians."""
    r = controller.Rotation
    return signed_uu(r.Yaw) * RAD_PER_UU, signed_uu(r.Pitch) * RAD_PER_UU


def eye_position(pawn: Any) -> tuple[float, float, float] | None:
    loc = location(pawn)
    if loc is None:
        return None
    try:
        h = float(pawn.BaseEyeHeight)
    except Exception:
        h = 60.0
    return (loc[0], loc[1], loc[2] + h)


def wrap_angle(a: float) -> float:
    while a > math.pi:
        a -= 2 * math.pi
    while a < -math.pi:
        a += 2 * math.pi
    return a


@dataclass
class Relative:
    dist: float          # unreal units
    rel_yaw: float       # radians, +right
    rel_pitch: float     # radians, +up (relative to where you look)
    elevation: float     # radians, +up (absolute, relative to horizon)
    aim_error: float     # radians between crosshair and target

    @property
    def pan(self) -> float:
        return math.sin(self.rel_yaw)

    @property
    def behind(self) -> bool:
        return math.cos(self.rel_yaw) < 0

    @property
    def metres(self) -> float:
        return self.dist / UU_PER_METRE


def relative(eye: tuple[float, float, float], yaw: float, pitch: float,
             target: tuple[float, float, float]) -> Relative:
    dx, dy, dz = target[0] - eye[0], target[1] - eye[1], target[2] - eye[2]
    horiz = math.hypot(dx, dy)
    dist = math.sqrt(horiz * horiz + dz * dz) or 1e-6
    t_yaw = math.atan2(dy, dx)
    t_pitch = math.atan2(dz, horiz)
    vx = math.cos(pitch) * math.cos(yaw)
    vy = math.cos(pitch) * math.sin(yaw)
    vz = math.sin(pitch)
    dot = (vx * dx + vy * dy + vz * dz) / dist
    return Relative(
        dist=dist,
        rel_yaw=wrap_angle(t_yaw - yaw),
        rel_pitch=t_pitch - pitch,
        elevation=t_pitch,
        aim_error=math.acos(max(-1.0, min(1.0, dot))),
    )


def aim_rotation(eye: tuple[float, float, float], target: tuple[float, float, float]) -> tuple[int, int]:
    """(pitch_uu, yaw_uu) that looks from eye at target."""
    dx, dy, dz = target[0] - eye[0], target[1] - eye[1], target[2] - eye[2]
    yaw = math.atan2(dy, dx)
    pitch = math.atan2(dz, math.hypot(dx, dy))
    return int(pitch / RAD_PER_UU), int(yaw / RAD_PER_UU)


def set_view(controller: Any, pitch_uu: int, yaw_uu: int) -> bool:
    r = rot(pitch_uu, yaw_uu, 0)
    for fn in ("SetRotation", "ClientSetRotation"):
        try:
            getattr(controller, fn)(r)
            return True
        except Exception:
            continue
    try:
        controller.Rotation = r
        return True
    except Exception:
        return False


def clock(rel_yaw: float) -> str:
    """Direction as a clock face: 12 is straight ahead, 3 is right."""
    hour = round(math.degrees(rel_yaw) / 30) % 12
    return f"{12 if hour == 0 else hour} o'clock"


def height_word(rel: Relative) -> str:
    deg = math.degrees(rel.elevation)
    if deg > 20:
        return ", above"
    if deg < -20:
        return ", below"
    return ""


def heading_degrees(yaw: float) -> int:
    return int(round(math.degrees(yaw))) % 360


def describe(rel: Relative) -> str:
    m = rel.metres
    dist = f"{m:.0f} metres" if m >= 2 else "right next to you"
    return f"{dist}, {clock(rel.rel_yaw)}{height_word(rel)}"


# --------------------------------------------------------------------------------------
# Pawns
# --------------------------------------------------------------------------------------

def iter_pawns(controller: Any) -> Iterator[Any]:
    try:
        p = controller.WorldInfo.PawnList
    except Exception:
        return
    guard = 0
    while p is not None and guard < 4000:
        yield p
        guard += 1
        try:
            p = p.NextPawn
        except Exception:
            return


def health(p: Any) -> tuple[float, float] | None:
    for cur, mx in (("GetHealth", "GetMaxHealth"),):
        try:
            return float(getattr(p, cur)()), float(getattr(p, mx)())
        except Exception:
            pass
    try:
        return float(p.Health), float(p.HealthMax)
    except Exception:
        return None


def is_alive(p: Any) -> bool:
    try:
        if p.bDeleteMe or p.bHidden:
            return False
    except Exception:
        pass
    h = health(p)
    return h is None or h[0] > 0


def class_name(obj: Any) -> str:
    try:
        return str(obj.Class.Name)
    except Exception:
        return ""


def is_player_pawn(p: Any) -> bool:
    try:
        c = p.Controller
        if c is not None and "PlayerController" in class_name(c):
            return True
    except Exception:
        pass
    return "PlayerPawn" in class_name(p)


_is_enemy_works: bool | None = None


def is_hostile(me: Any, p: Any, treat_all_ai_as_enemies: bool) -> bool:
    global _is_enemy_works
    if p is None or me is None or p == me or is_player_pawn(p):
        return False
    if _is_enemy_works is not False:
        try:
            result = bool(me.IsEnemy(p))
            _is_enemy_works = True
            return result
        except Exception:
            _is_enemy_works = False
    return treat_all_ai_as_enemies


def is_friendly_npc(me: Any, p: Any) -> bool:
    """A friendly, non-player character - only when the game can actually tell friend from foe.
    If IsEnemy isn't available we return False, so enemies never get the friendly chime."""
    global _is_enemy_works
    if p is None or me is None or p == me or is_player_pawn(p):
        return False
    if _is_enemy_works is False:
        return False
    try:
        result = not bool(me.IsEnemy(p))
        _is_enemy_works = True
        return result
    except Exception:
        _is_enemy_works = False
        return False


def usable_target(controller: Any) -> Any:
    """What the game says the player can 'use' right now (the object behind the Use prompt),
    or None if this isn't exposed. Tries the likely property names."""
    for name in ("CurrentUsableObject", "CurrentInteractionIcon", "CurrentUseTarget", "UsableObject"):
        try:
            v = getattr(controller, name)
        except Exception:
            continue
        if v is not None and not isinstance(v, (int, float, str, bool)):
            return v
    return None


def pretty(raw: str) -> str:
    raw = re.sub(r"_\d+$", "", raw)
    raw = re.sub(r"^(Willow|Gd_|GD_|Pawn_|Char_|AIPawn_)", "", raw)
    raw = raw.replace("_", " ")
    raw = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", raw)
    return raw.strip() or "Unknown"


def display_name(obj: Any) -> str:
    for getter in (
        lambda o: o.AIClass.DefaultDisplayName,
        lambda o: o.GetShortHumanReadableName(),
        lambda o: o.Inventory.GetShortHumanReadableName(),
        lambda o: o.InteractiveObjectDefinition.Name,
        lambda o: o.PlayerReplicationInfo.PlayerName,
    ):
        try:
            v = getter(obj)
            if v:
                v = str(v)
                return pretty(v) if "_" in v else v
        except Exception:
            continue
    return pretty(class_name(obj))


# Which line test works in this game: "fast" (Actor.FastTrace), "trace" (Actor.Trace), or None
# until the first test. Chosen by trace_self_test() and by errors; logged once.
TRACE_MODE: str | None = None
_trace_notes: set[str] = set()


def _trace_note(text: str) -> None:
    if text in _trace_notes:
        return
    _trace_notes.add(text)
    try:
        from . import trace

        trace.note(text)
    except Exception:
        pass


def _fast(actor: Any, start: tuple, end: tuple) -> bool:
    return bool(actor.FastTrace(vec(*end), vec(*start)))


def _full(actor: Any, start: tuple, end: tuple) -> bool:
    """Actor.Trace: returns the actor hit (the world itself counts), with the hit location and
    normal as out-parameters. Clear = nothing hit."""
    r = actor.Trace(vec(0, 0, 0), vec(0, 0, 0), vec(*end), vec(*start), False)
    hit = r[0] if isinstance(r, tuple) else r
    return hit is None


def fast_trace(actor: Any, start: tuple[float, float, float], end: tuple[float, float, float]) -> bool | None:
    """True if the line is clear of world geometry, False if something's in the way, None if no
    way of tracing works. Uses whichever of the game's two trace functions works here."""
    global TRACE_MODE
    order = [TRACE_MODE] if TRACE_MODE in ("fast", "trace") else ["fast", "trace"]
    if TRACE_MODE in ("fast", "trace"):
        order.append("trace" if TRACE_MODE == "fast" else "fast")
    for mode in order:
        try:
            result = _fast(actor, start, end) if mode == "fast" else _full(actor, start, end)
        except Exception as e:  # noqa: BLE001
            _trace_note(f"line test {mode} failed: {type(e).__name__}: {e}")
            continue
        if TRACE_MODE is None:
            TRACE_MODE = mode
        return result
    return None


FLOOR_SEEN = False  # a self-test has confirmed a method that sees the floor


def trace_self_test(pawn: Any) -> str:
    """Check the line test can see the floor under you (a straight-down trace must hit
    something), and pick the method that can. If neither does (you might be in the air), the
    current choice is kept and the caller tries again later. Returns the result for the log."""
    global TRACE_MODE, FLOOR_SEEN
    loc = location(pawn)
    if loc is None:
        return "no position"
    start, end = loc, (loc[0], loc[1], loc[2] - 3000)
    results = {}
    for mode, fn in (("fast", _fast), ("trace", _full)):
        try:
            results[mode] = fn(pawn, start, end)
        except Exception as e:  # noqa: BLE001
            results[mode] = f"error {type(e).__name__}: {e}"
    if results.get("fast") is False:
        TRACE_MODE, FLOOR_SEEN = "fast", True
    elif results.get("trace") is False:
        TRACE_MODE, FLOOR_SEEN = "trace", True
    verdict = TRACE_MODE if FLOOR_SEEN else "no floor seen yet, will check again"
    _trace_note(f"line test self-check: FastTrace sees floor={results.get('fast') is False} ({results.get('fast')}), "
                f"Trace sees floor={results.get('trace') is False} ({results.get('trace')}) -> {verdict}")
    return verdict


def move_intent(pawn: Any, controller: Any = None) -> tuple[float, float] | None:
    """Unit (x, y) direction you're pushing the stick or movement keys, or None if you aren't.
    This is what you're trying to do, which still works when something stops you moving."""
    try:
        a = pawn.Acceleration
        m = math.hypot(a.X, a.Y)
        if m > 1:
            return (a.X / m, a.Y / m)
    except Exception:
        pass
    try:
        pi = controller.PlayerInput
        fwd, strafe = float(pi.aForward), float(pi.aStrafe)
        if abs(fwd) + abs(strafe) > 0.01:
            yaw = view_angles(controller)[0]
            x = fwd * math.cos(yaw) - strafe * math.sin(yaw)
            y = fwd * math.sin(yaw) + strafe * math.cos(yaw)
            m = math.hypot(x, y)
            return (x / m, y / m) if m else None
    except Exception:
        pass
    return None


def speed(pawn: Any) -> float:
    """Horizontal speed in uu per second (0 if unknown)."""
    try:
        v = pawn.Velocity
        return math.hypot(v.X, v.Y)
    except Exception:
        return 0.0


def feet_z(pawn: Any) -> float | None:
    loc = location(pawn)
    if loc is None:
        return None
    try:
        return loc[2] - float(pawn.CylinderComponent.CollisionHeight)
    except Exception:
        return loc[2] - 90


def blockage(pawn: Any, angle: float, jump_height: float, reach: float = 120.0) -> dict:
    """What's in the way in direction `angle` (radians): a low obstacle you could jump, a wall,
    and whether the ways 60 degrees to each side are open. Uses line tests at knee, jump and
    chest height."""
    loc = location(pawn)
    feet = feet_z(pawn)
    if loc is None or feet is None:
        return {}
    x, y = loc[0], loc[1]

    def line(a: float, height: float, r: float) -> bool | None:
        return fast_trace(pawn, (x, y, feet + height), (x + math.cos(a) * r, y + math.sin(a) * r, feet + height))

    def floor_at(a: float, r: float) -> bool:
        px, py = x + math.cos(a) * r, y + math.sin(a) * r
        return fast_trace(pawn, (px, py, feet + 30), (px, py, feet - 300)) is False

    knee = line(angle, 40, reach)
    if knee is None:
        return {}
    top = line(angle, jump_height, reach)
    chest = line(angle, 130, reach)

    def open_side(sign: int) -> bool:
        a = angle + sign * math.radians(60)
        return bool(line(a, 40, 200)) and bool(line(a, 130, 200)) and floor_at(a, 150)

    return {
        "knee_blocked": knee is False,
        "jumpable": knee is False and top is True and chest is True,
        "wall": knee is False and (top is False or chest is False),
        "left_open": open_side(-1),
        "right_open": open_side(1),
    }


def openings(pawn: Any, reach: float = 250.0, step_deg: int = 30) -> list[float]:
    """Directions (radians) all the way round you that are clear at knee and chest height for
    `reach` and have floor, i.e. ways you could walk."""
    loc = location(pawn)
    feet = feet_z(pawn)
    if loc is None or feet is None:
        return []
    x, y = loc[0], loc[1]
    out = []
    for k in range(0, 360, step_deg):
        a = math.radians(k)
        ex, ey = x + math.cos(a) * reach, y + math.sin(a) * reach
        if (fast_trace(pawn, (x, y, feet + 45), (ex, ey, feet + 45)) is True
                and fast_trace(pawn, (x, y, feet + 130), (ex, ey, feet + 130)) is True
                and fast_trace(pawn, (ex, ey, feet + 30), (ex, ey, feet - 300)) is False):
            out.append(a)
    return out


def line_of_sight(controller: Any, target: Any) -> bool:
    try:
        return bool(controller.LineOfSightTo(target))
    except Exception:
        return True


def world_actors(class_names: list[str]) -> list[Any]:
    """Live actors of the given classes in the current map (skips templates/defaults)."""
    out = []
    for cn in class_names:
        try:
            objs = unrealsdk.find_all(cn, exact=False)
        except Exception:
            continue
        for o in objs:
            try:
                path = o._path_name()
                if "Default__" in path or ".TheWorld:" not in path:
                    continue
                if o.bDeleteMe:
                    continue
                out.append(o)
            except Exception:
                continue
    return out


_MAP_NAMES = {
    "Glacial_P": "Windshear Waste",
    "SouthernShelf_P": "Southern Shelf",
    "Sanctuary_P": "Sanctuary",
    "Sanctuary_Hole_P": "Sanctuary",
    "Ice_P": "Three Horns Divide",
}


def map_name(controller: Any) -> str:
    try:
        raw = str(controller.WorldInfo.GetMapName(False))
    except Exception:
        return ""
    return _MAP_NAMES.get(raw, pretty(re.sub(r"_P$", "", raw)))
