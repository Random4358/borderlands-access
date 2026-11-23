"""Guidance to a chosen place: the beacon, route finding, and the lock-on navigation turn.

Beacon: a steady tone (not separate pings) on its own stream, so its direction is always
current. It's panned to where you need to go, muffled when that's behind you, and switches to
a brighter "on course" tone when you face within a few degrees of the right way. It pulses
faster as you get closer. The pitch rises when the target is above you and falls when below.

Route: the beacon leads to the next point on a walkable route instead of straight through
walls. Three ways of finding it, best first:
  1. The level's navigation mesh, through the controller's NavigationHandle (what the game's
     own AI walks with).
  2. The older path-node network (Controller.FindPathToward / FindPathTo).
  3. Local steering, which always works: when the straight line to the target is blocked, the
     directions around you are tested with line traces, and the beacon leads you along the
     first clear one with floor under it, keeping to one side so it doesn't flip back and
     forth. If you're walking but not getting closer, it tries the other side.
The first two are only used if the game gives real route points; each is logged once to
logs\\diagnostic.log, so it's clear which one the level supports.

Lock-on navigation (an option): Modifier + right stick click, or the apostrophe key, turns you to
face the way to go, along the route when there is one.
"""

from __future__ import annotations

import math
import time
from typing import Any

from . import audio as snd
from . import game
from .audio import audio

ON_COURSE_DEG = 7.0     # facing this close to the way to go = "on course"
NODE_REACHED = 140.0    # uu: close enough to a route point to move on to the next one
ROUTE_EVERY = 0.5       # seconds between asking the game for a route
STEER_EVERY = 0.25      # seconds between local steering checks
STEER_REACH = 450.0     # uu: how far ahead each steering direction is tested (~4.5 m)
LOOK_AHEAD = 1500.0     # uu: how much of the straight line must be clear to head straight (~15 m)
STEER_ANGLES = (25, 45, 65, 90, 115, 140)  # degrees either side of the straight line
STUCK_SECONDS = 3.0     # walking this long without getting 0.4 m closer = try the other side
LEAD = 0.1              # seconds of beacon tone queued ahead
BEACON_BASE = 56        # 700 Hz at the same height as you


def beacon_cycles(elev_deg: float) -> int:
    x = max(-1.0, min(1.0, elev_deg / 30))
    return max(8, int(round(BEACON_BASE * 2 ** (x * 0.5))))  # up to half an octave each way


def _dist(a: tuple, b: tuple) -> float:
    return math.dist(a, b)


class _NoPath(Exception):
    """The navigation mesh answered, but found no path this time."""


def _first(r: Any) -> Any:
    """Return value of a call that may also hand back out-parameters as a tuple."""
    return r[0] if isinstance(r, tuple) else r


class Route:
    """Where to head now on the way to a target."""

    def __init__(self) -> None:
        self.node: tuple[float, float, float] | None = None
        self.source = ""                     # "navmesh", "path nodes", "steering" or ""
        self.next_update = 0.0
        self.navmesh_ok: bool | None = None  # learned on first use, logged once
        self.nodes_ok: bool | None = None
        self.target_key = ""
        # local steering
        self.steer: tuple[float, float, float] | None = None
        self.next_steer = 0.0
        self.side = 0                        # +1 right, -1 left, 0 not chosen
        self.side_until = 0.0
        self.progress: tuple[float, float] | None = None  # (time, distance) at last check
        self.stuck_since: float | None = None
        self.forced_until = 0.0              # keep steering round a snag even if the line looks clear
        self.noted: set[str] = set()

    def reset(self) -> None:
        self.node, self.source, self.next_update, self.target_key = None, "", 0.0, ""
        self.steer, self.next_steer, self.side, self.side_until, self.progress = None, 0.0, 0, 0.0, None
        self.stuck_since, self.forced_until = None, 0.0

    def _note(self, text: str) -> None:
        if text in self.noted:
            return
        self.noted.add(text)
        from . import trace

        trace.note(text)

    # ------------------------------------------------------------ the decision
    def next_point(self, pc: Any, eye: tuple, target_pos: tuple, target_actor: Any, key: str,
                   now: float, pawn: Any = None) -> tuple[float, float, float]:
        """Where to head now: the next route point, a way around an obstacle, or the target."""
        if key != self.target_key:
            self.reset()
            self.target_key = key
        if self.node is not None and _dist(eye, self.node) < NODE_REACHED:
            self.node, self.next_update = None, 0.0  # reached it: ask for the next one now
        if now >= self.next_update and (self.navmesh_ok is not False or self.nodes_ok is not False):
            self.node, self.source = self._ask(pc, eye, target_pos, target_actor)
            self.next_update = now + (ROUTE_EVERY if self.node is not None else 2.0)
        if self.node is not None and _dist(eye, self.node) <= _dist(eye, target_pos) + 200:
            return self.node
        if pawn is None:
            return target_pos
        return self._steer(pawn, eye, target_pos, now)

    # ------------------------------------------------------------ 1 and 2: the game's routes
    def _ask(self, pc: Any, eye: tuple, target_pos: tuple, target_actor: Any) -> tuple[Any, str]:
        if self.navmesh_ok is not False:
            pos = self._navmesh(pc, eye, target_pos)
            if pos is not None:
                return pos, "navmesh"
        if self.nodes_ok is not False:
            pos = self._path_nodes(pc, eye, target_pos, target_actor)
            if pos is not None:
                return pos, "path nodes"
        return None, ""

    def _navmesh(self, pc: Any, eye: tuple, target_pos: tuple) -> tuple | None:
        try:
            import unrealsdk

            handle = getattr(pc, "NavigationHandle", None)
            if handle is None:
                try:
                    pc.InitNavigationHandle()
                except Exception:
                    pass
                handle = getattr(pc, "NavigationHandle", None)
            if handle is None:
                raise RuntimeError("no NavigationHandle")
            goal = game.vec(*target_pos)
            toward = unrealsdk.find_class("NavMeshPath_Toward").ClassDefaultObject
            at = unrealsdk.find_class("NavMeshGoal_At").ClassDefaultObject
            handle.ClearConstraints()
            try:
                handle.SetFinalDestination(goal)
            except Exception:
                pass
            toward.TowardPoint(handle, goal)
            try:
                at.AtLocation(handle, goal, 150.0, True)   # keep a partial path if the goal isn't on the mesh
            except Exception:
                at.AtLocation(handle, goal, 150.0)
            if not _first(handle.FindPath()):
                raise _NoPath("FindPath found no path")
            try:
                handle.SetFinalDestination(goal)
            except Exception:
                pass
            r = handle.GetNextMoveLocation(game.vec(*eye), 80.0)
            ok, dest = (r[0], r[1]) if isinstance(r, tuple) else (r, None)
            pos = (float(dest.X), float(dest.Y), float(dest.Z)) if ok and dest is not None else None
            if pos is None or _dist(eye, pos) < 40:
                raise RuntimeError("no next move location")
        except _NoPath as e:
            # The mesh works but had no path from here; try again later (it may from elsewhere).
            self._note(f"route finding: navigation mesh had no path ({e}); will keep trying")
            return None
        except Exception as e:  # noqa: BLE001
            if self.navmesh_ok is None:
                self.navmesh_ok = False
                self._note(f"route finding: navigation mesh not usable ({type(e).__name__}: {e})")
            return None
        if not self.navmesh_ok:
            self.navmesh_ok = True
            self._note("route finding: using the navigation mesh")
        return pos

    def _path_nodes(self, pc: Any, eye: tuple, target_pos: tuple, target_actor: Any) -> tuple | None:
        calls = []
        if target_actor is not None:
            calls.append(lambda: pc.FindPathToward(target_actor))
        calls.append(lambda: pc.FindPathTo(game.vec(*target_pos)))
        tried = False
        for call in calls:
            try:
                node = call()
                tried = True
            except Exception:
                continue
            pos = game.location(node) if node is not None else None
            if pos is not None and _dist(eye, pos) > 40 and _dist(pos, target_pos) > 60:
                if not self.nodes_ok:
                    self.nodes_ok = True
                    self._note("route finding: using path nodes")
                return pos
        if self.nodes_ok is None:
            # Available but empty counts as unusable for this level; steering takes over.
            self.nodes_ok = False
            self._note(f"route finding: path nodes {'gave no route' if tried else 'not available'}")
        return None

    # ------------------------------------------------------------ 3: local steering
    def _steer(self, pawn: Any, eye: tuple, target_pos: tuple, now: float) -> tuple:
        base = game.location(pawn) or eye  # trace at body height: below head-high clutter
        start = (base[0], base[1], base[2] + 20)
        dist = math.hypot(target_pos[0] - start[0], target_pos[1] - start[1])
        # Pushing but not moving = snagged on something (often too low for the body-height line
        # test to see): pick a way around straight away; if that doesn't work, the other side.
        trying = game.move_intent(pawn) is not None
        if trying and game.speed(pawn) < 40:
            if self.stuck_since is None:
                self.stuck_since = now
            elif now - self.stuck_since >= 0.8:
                self.stuck_since = now + 1.2   # next re-plan after 2 s more of being stuck
                self.side = -self.side if self.side else self._open_side(pawn, start, target_pos)
                self.side_until = now + 3.0
                self.forced_until = now + 2.5
                self.steer, self.next_steer = None, 0.0
                self._note("route finding: snagged on something, finding a way around")
        else:
            self.stuck_since = None
        moving = trying or game.speed(pawn) > 50
        if self.progress is None or not moving:
            self.progress = (now, dist)
        elif now - self.progress[0] >= STUCK_SECONDS:
            if self.progress[1] - dist < 40 and self.side:
                self.side = -self.side
                self.side_until = now + 3.0
                self.steer, self.next_steer = None, 0.0
                self._note("route finding: stuck, trying the other side")
            self.progress = (now, dist)
        if now < self.next_steer and self.steer is not None:
            return self.steer
        self.next_steer = now + STEER_EVERY
        self.steer = self._choose(pawn, start, target_pos, dist, now)
        return self.steer

    def _open_side(self, pawn: Any, start: tuple, target_pos: tuple) -> int:
        """Which side (+1 right, -1 left) is open when you're snagged, toward the target."""
        heading = math.atan2(target_pos[1] - start[1], target_pos[0] - start[0])
        b = game.blockage(pawn, heading, 100.0)
        if b.get("right_open") and not b.get("left_open"):
            return 1
        if b.get("left_open") and not b.get("right_open"):
            return -1
        return 1

    def _choose(self, pawn: Any, start: tuple, target_pos: tuple, dist: float, now: float) -> tuple:
        ahead = min(LOOK_AHEAD, max(dist, 1.0))
        heading = math.atan2(target_pos[1] - start[1], target_pos[0] - start[0])

        def point(angle: float, r: float) -> tuple:
            return (start[0] + math.cos(angle) * r, start[1] + math.sin(angle) * r, start[2])

        def clear(p: tuple) -> bool | None:
            return game.fast_trace(pawn, start, p)

        feet = game.feet_z(pawn)
        knee_z = (feet + 45) if feet is not None else start[2] - 60

        def clear_low(p: tuple) -> bool:
            """Also clear at knee height, so low obstacles don't count as a way through."""
            return game.fast_trace(pawn, (start[0], start[1], knee_z), (p[0], p[1], knee_z)) is not False

        def floor(p: tuple) -> bool:
            return game.fast_trace(pawn, (p[0], p[1], p[2]), (p[0], p[1], p[2] - 300)) is False

        direct = clear(point(heading, ahead))
        if direct is None:          # tracing not available: nothing better than straight
            self._note("route finding: can't steer, line tests unavailable (see the line test lines)")
            return target_pos
        if direct and now >= self.forced_until:
            if now >= self.side_until:
                self.side = 0
            return target_pos
        sides = [self.side] if self.side else [1, -1]
        if self.side:
            sides.append(-self.side)
        for need_low in (True, False):   # prefer ways clear at knee height too
            for off in STEER_ANGLES:
                for s in sides:
                    p = point(heading + s * math.radians(off), STEER_REACH)
                    if clear(p) and floor(p) and (not need_low or clear_low(p)):
                        if s != self.side:
                            self.side = s
                            self.side_until = now + 2.0
                        self._note("route finding: steering around obstacles (no game route here)")
                        return p
        return target_pos  # boxed in: point at the target and let the wall cues help


class Beacon:
    def __init__(self) -> None:
        self.route = Route()
        self.step = 0
        self.started = False
        self.last = ("beacon", BEACON_BASE, 0.0, 0.0, False)

    def stream(self) -> Any:
        return getattr(audio, "nav_stream", None)

    def tick(self, s: Any, snap: Any, target_pos: tuple, target_actor: Any, key: str, now: float) -> float:
        """Feed the beacon tone for one frame. Returns the distance to the target itself."""
        point = self.route.next_point(snap.pc, snap.eye, target_pos, target_actor, key, now, snap.pawn)
        dist_target = _dist(snap.eye, target_pos)
        st = self.stream()
        if st is None or not audio.ok:
            return dist_target
        try:
            if st.ahead() >= LEAD:
                return dist_target
            rel = game.relative(snap.eye, snap.yaw, snap.pitch, point)
            on_course = abs(math.degrees(rel.rel_yaw)) <= ON_COURSE_DEG
            kind = "beacon_on" if on_course else "beacon"
            closeness = 1.0 - min(1.0, dist_target / 6000)
            vol = (0.35 + 0.65 * closeness) * s.volume
            period = max(2, int(round(10 - 8 * closeness)))   # pulse every 0.8 s far .. 0.16 s close
            cycles = beacon_cycles(math.degrees(rel.elevation))
            while st.ahead() < LEAD:
                pulse = 1.0 if self.step % period == 0 else 0.3
                st.feed(snd.tone_segment(kind, cycles, self.step, rel.pan, vol * pulse, rel.behind,
                                         0 if self.started else 1))
                self.last = (kind, cycles, rel.pan, vol * pulse, rel.behind)
                self.started = True
                self.step += 1
        except Exception:
            pass
        return dist_target

    def stop(self, fade: bool = True) -> None:
        st = self.stream()
        if st is not None and self.started:
            try:
                if fade:
                    kind, cycles, pan, vol, behind = self.last
                    st.feed(snd.tone_segment(kind, cycles, self.step, pan, vol, behind, -1))
                else:
                    st.stop()
            except Exception:
                pass
        self.started = False
        self.route.reset()


beacon = Beacon()


def face(snap: Any, target_pos: tuple, target_actor: Any, key: str) -> tuple[float, bool]:
    """Turn to face the way to go (the next route point if there is one), view level.
    Returns (distance to the target, whether a route point was used)."""
    point = beacon.route.next_point(snap.pc, snap.eye, target_pos, target_actor, key, time.perf_counter(), snap.pawn)
    _pitch, yaw = game.aim_rotation(snap.eye, point)
    game.set_view(snap.pc, 0, yaw)
    return _dist(snap.eye, target_pos), point != target_pos
