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
  3. The mod's own route planner (planner.py): a search over a grid of points about a metre
     apart, testing with line traces where you can walk, which finds the way round walls and
     through doorways.
  4. Local steering, used until the planner's first answer: when the straight line to the target is blocked, the
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
FAR = 3500.0           # uu: beyond this the planner uses a coarse grid (35 m)
PLAN_CELLS = 2500      # planner search limit, doubled (up to 4x) when a partial route stalls
PLAN_BUDGET = 120      # line traces the planner may use per frame
PROGRESS_SECONDS = 8.0 # moving without getting further along the route this long = re-plan
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
        self.planner = None                  # GridPlanner, made when first needed
        self.replan_at = 0.0
        self.plan_logged = ""
        self.path: list = []                 # the route being followed (kept while re-planning)
        self.path_kind = ""                  # "done" (reaches the target) or "partial"
        self.path_cell = 90.0
        self.noted: set[str] = set()

    def reset(self) -> None:
        self.node, self.source, self.next_update, self.target_key = None, "", 0.0, ""
        self.steer, self.next_steer, self.side, self.side_until, self.progress = None, 0.0, 0, 0.0, None
        self.stuck_since, self.forced_until = None, 0.0
        self.planner, self.replan_at, self.plan_logged = None, 0.0, ""
        self.path, self.path_kind, self.path_cell = [], "", 90.0

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
            self._note_target(key, eye, target_pos)
        if self.node is not None and _dist(eye, self.node) < NODE_REACHED:
            self.node, self.next_update = None, 0.0  # reached it: ask for the next one now
        if now >= self.next_update and (self.navmesh_ok is not False or self.nodes_ok is not False):
            self.node, self.source = self._ask(pc, eye, target_pos, target_actor)
            self.next_update = now + (ROUTE_EVERY if self.node is not None else 2.0)
        if self.node is not None and _dist(eye, self.node) <= _dist(eye, target_pos) + 200:
            return self.node
        if pawn is None:
            return target_pos
        planned = self._planned(pawn, target_pos, now)
        steer = self._steer(pawn, eye, target_pos, now)   # also watches for snags
        if planned is not None and now >= self.forced_until:
            return planned
        return steer

    def _note_target(self, key: str, eye: tuple, target_pos: tuple) -> None:
        from . import trace

        trace.note(f"route to '{key}': {_dist(eye, target_pos) / 100:.0f} m away, "
                   f"target at ({target_pos[0]:.0f}, {target_pos[1]:.0f}, {target_pos[2]:.0f}), "
                   f"you at ({eye[0]:.0f}, {eye[1]:.0f}, {eye[2]:.0f})")

    def _planned(self, pawn: Any, target_pos: tuple, now: float) -> tuple | None:
        """The next point on the planned route, planning and re-planning as needed.

        * Far from the target (over 35 m) the search uses a coarse 1.8 m grid, enough for open
          ground; within 35 m it uses the fine 0.9 m grid that finds doorways.
        * The route being followed is kept while a new one is worked out.
        * If a search can't reach the target, you're led as close as it got; when you get there
          and the next search gets no closer, the search area is doubled (up to 4 times).
        * If you keep walking without getting closer along the route for 8 s, it re-plans and
          says "Recalculating".
        """
        from .planner import GridPlanner, follow

        loc = game.location(pawn)
        feet = game.feet_z(pawn)
        if loc is None or feet is None or not game.FLOOR_SEEN:
            return None   # no working line test yet: a plan from wrong answers would mislead you
        here = (loc[0], loc[1], feet)
        if self.planner is None:
            self.planner = GridPlanner(lambda a, b: game.fast_trace(pawn, a, b))
            self.path, self.path_kind, self.limit, self.last_gap = [], "", PLAN_CELLS, None
            self.runs_seen, self.watch, self.announced = 0, None, False
        pl = self.planner
        far = math.dist(here[:2], target_pos[:2]) > FAR
        cell = 180.0 if far else 90.0
        path = self.path
        off_route = bool(path) and min(math.dist(here[:2], q[:2]) for q in path) > cell * 2.5
        at_end = bool(path) and self.path_kind == "partial" and math.dist(here[:2], path[-1][:2]) < cell * 1.2
        grain_changed = bool(path) and (cell != self.path_cell)
        if pl.state != "running" and (not path or now >= self.replan_at or off_route or at_end or grain_changed):
            # Start from the ground actually under you (measured), not an estimate from your height.
            ground = game.ground_z(pawn, loc[0], loc[1], loc[2])
            start = (loc[0], loc[1], ground if ground is not None else feet)
            self.start_note = (f"you at ({loc[0]:.0f}, {loc[1]:.0f}), body {loc[2]:.0f}, estimated feet {feet:.0f}, "
                               f"measured ground {'none' if ground is None else f'{ground:.0f}'}")
            pl.start(start, target_pos, cell=cell, max_cells=self.limit)
            self.replan_at = now + 8.0
        pl.step(PLAN_BUDGET)
        if pl.runs != self.runs_seen and pl.state in ("done", "partial", "failed"):
            self.runs_seen = pl.runs
            self._take_plan(pl, here, now)
        if not self.path:
            return None
        self._watch_progress(here, now)

        def visible(q: tuple) -> bool:
            return all(game.fast_trace(pawn, (here[0], here[1], here[2] + h), (q[0], q[1], q[2] + h)) is not False
                       for h in (50.0, 130.0))

        nxt = follow(self.path, here, visible)
        if nxt is None:
            return None
        if self.path_kind == "done" and nxt == self.path[-1]:
            return target_pos
        return (nxt[0], nxt[1], nxt[2] + 100)

    def _take_plan(self, pl: Any, here: tuple, now: float) -> None:
        from .speech import speech

        length = sum(math.dist(a[:2], b[:2]) for a, b in zip(pl.path, pl.path[1:])) / 100
        if pl.state == "failed":
            r = pl.rejects
            self._note(f"route planner: no walkable way found from here; steps refused: no floor {r['no floor']}, "
                       f"knee {r['knee']}, chest {r['chest']}; grid {pl.cell / 100:.1f} m; {getattr(self, 'start_note', '')}")
            if self.path_kind == "partial" and self.limit < PLAN_CELLS * 4:
                # Stuck at the end of a partial route (often pressed against a wall): look wider.
                self.limit *= 2
                self._note(f"route planner: searching a bigger area ({self.limit} points)")
            if not self.path:
                self.path_kind = ""
            return
        # A partial route that gets no closer than the last one: search a bigger area next time.
        if pl.state == "partial":
            if self.last_gap is not None and pl.best_gap >= self.last_gap - 100 and self.limit < PLAN_CELLS * 4:
                self.limit *= 2
                self._note(f"route planner: no closer, searching a bigger area ({self.limit} points)")
                self.replan_at = 0.0
            self.last_gap = pl.best_gap
        else:
            self.limit, self.last_gap = PLAN_CELLS, None
        self.path, self.path_kind, self.path_cell = list(pl.path), pl.state, pl.cell
        # distance left along the route from each point, for the progress check
        self.tail = [0.0] * len(self.path)
        for k in range(len(self.path) - 2, -1, -1):
            self.tail[k] = self.tail[k + 1] + math.dist(self.path[k][:2], self.path[k + 1][:2])
        self.watch = None
        self._note(f"route planner: {'path to the target' if pl.state == 'done' else 'partial path toward the target'}, "
                   f"{length:.0f} m, {pl.cells_searched} points searched, grid {pl.cell / 100:.1f} m")
        if not self.announced:
            self.announced = True
            if pl.state == "done":
                speech.say(f"Route found, {max(1, round(length))} metres", interrupt=False)
            else:
                speech.say("Heading toward it, searching for the way in", interrupt=False)

    def _watch_progress(self, here: tuple, now: float) -> None:
        """Re-plan if you keep moving but don't get any further along the route."""
        i = min(range(len(self.path)), key=lambda k: math.dist(here[:2], self.path[k][:2]))
        remaining = math.dist(here[:2], self.path[i][:2]) + self.tail[i]
        if self.watch is None:
            self.watch = (now, remaining)
            return
        t0, r0 = self.watch
        if remaining < r0 - 150:
            self.watch = (now, remaining)
        elif now - t0 >= PROGRESS_SECONDS:
            from .speech import speech

            self.watch = (now, remaining)
            self.replan_at = 0.0
            self._note("route planner: no progress along the route, recalculating")
            speech.say("Recalculating", interrupt=False)

    def route_direction(self) -> tuple | None:
        """Second point of the current planned path (where the route goes from here), if any."""
        if len(self.path) < 2:
            return None
        return self.path[1]

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
                self.replan_at = 0.0          # and plan again from here
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

        direct = clear(point(heading, ahead)) if game.FLOOR_SEEN else None
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
