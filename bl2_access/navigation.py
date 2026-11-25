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
KNOWN_REACHED = 90.0    # uu: the same along known paths (closer, so corners aren't cut)
KNOWN_AHEAD = 1000.0    # uu along a known path the beacon may aim ahead (~10 m), while it runs straight
KNOWN_WIDTH = 60.0      # uu: a walked trail (smoothed) this close to a straight line counts as straight (trails wobble)
ROUTE_EVERY = 0.5       # seconds between asking the game for a route
STEER_EVERY = 0.25      # seconds between local steering checks
STEER_REACH = 450.0     # uu: how far ahead each steering direction is tested (~4.5 m)
LOOK_AHEAD = 1500.0     # uu: how much of the straight line must be clear to head straight (~15 m)
STEER_ANGLES = (25, 45, 65, 90, 115, 140)  # degrees either side of the straight line
STUCK_SECONDS = 3.0     # walking this long without getting 0.4 m closer = try the other side
LEAD = 0.1              # seconds of beacon tone queued ahead
BODY = 35.0             # uu: half your width, for "can you walk straight there" checks
FAR = 3500.0           # uu: beyond this the planner uses a coarse grid (35 m)
PLAN_CELLS = 2500      # planner search limit, doubled (up to 4x) when a partial route stalls
PLAN_BUDGET = 2000     # line traces the planner may use per frame at most
PLAN_SECONDS = 0.004   # and the time it may take per frame (a search from far off needs many)
STALE_SECONDS = 15.0   # a search running this long, begun much further away than you are now, starts over
PROGRESS_SECONDS = 8.0 # moving without getting further along the route this long = re-plan
BEACON_BASE = 56        # 700 Hz at the same height as you


def beacon_cycles(elev_deg: float) -> int:
    x = max(-1.0, min(1.0, elev_deg / 30))
    return max(8, int(round(BEACON_BASE * 2 ** (x * 0.5))))  # up to half an octave each way


def _dist(a: tuple, b: tuple) -> float:
    return math.dist(a, b)


def _smoothed(path: list, a: int, b: int) -> list:
    """path[a:b] with each point averaged with its neighbours (takes out the grid's zig-zag)."""
    out = []
    for k in range(a, b):
        nb = path[max(0, k - 1):k + 2]
        out.append((sum(q[0] for q in nb) / len(nb), sum(q[1] for q in nb) / len(nb)))
    return out


class _NoPath(Exception):
    """The navigation mesh answered, but found no path this time."""


def _first(r: Any) -> Any:
    """Return value of a call that may also hand back out-parameters as a tuple."""
    return r[0] if isinstance(r, tuple) else r


def _straight(a: tuple, b: tuple, between: list, width: float = KNOWN_WIDTH) -> bool:
    """All the points walked between a and b lie within `width` of the line a-b."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy)
    if n < 1:
        return True
    return all(abs((q[0] - a[0]) * dy - (q[1] - a[1]) * dx) / n <= width for q in between)


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
        self._reset_known()

    def _reset_known(self) -> None:
        self.known: list = []                # route over learned paths / navigation points
        self.known_done = False
        self.known_idx = 0
        self.known_at = 0.0
        self.known_version = -1
        self.known_said = False
        self.known_aim = 0
        self.known_spot: tuple | None = None  # a spot at the target's height the known route leads to                   # the point the beacon aims at: only ever moves forward

    def reset(self) -> None:
        self.node, self.source, self.next_update, self.target_key = None, "", 0.0, ""
        self.steer, self.next_steer, self.side, self.side_until, self.progress = None, 0.0, 0, 0.0, None
        self.stuck_since, self.forced_until = None, 0.0
        self.planner, self.replan_at, self.plan_logged = None, 0.0, ""
        self.path, self.path_kind, self.path_cell = [], "", 90.0
        self.path_moves, self.climb_told = [], set()
        self.climb_wanted = False    # someone's waiting to hear whether there's a way up
        self.search_from: tuple | None = None
        self._reset_known()

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
        known = self._known(pawn, eye, target_pos, now)
        if known is not None and self.known_done:
            return known                    # a way someone has actually walked, all the way there
        planned = self._planned(pawn, target_pos, now)
        steer = self._steer(pawn, eye, target_pos, now)   # also watches for snags
        if planned is not None and now >= self.forced_until:
            return planned
        if known is not None:
            return known                    # known paths as far as they go toward it
        return steer

    # ------------------------------------------------------------ known paths (waygraph.py)
    def _known(self, pawn: Any, eye: tuple, target_pos: tuple, now: float) -> tuple | None:
        """Next point along the learned paths / navigation points toward the target."""
        from .waygraph import graph

        here = (game.location(pawn) if pawn is not None else None) or eye
        path = self.known
        off = bool(path) and min(math.dist(here[:2], q[:2]) for q in path[self.known_idx:self.known_idx + 20] or path) > 500
        # Re-plan when off the path, or every few seconds if the known paths have grown since (a
        # search can take a moment on a big level, so not every frame).
        stale = now >= self.known_at + 3.0 and not self.known_done and graph.version != self.known_version
        if now >= self.known_at and (not path or off or stale):
            self.known_at = now + 1.0
            self.known_version = graph.version
            r = graph.route(here, target_pos)
            self.known_spot = None
            if r is not None and not r[1] and target_pos[2] - here[2] > 200:
                # Known paths don't reach a raised target itself; but if someone has stood at its
                # height close by (on the ledge or floor it's on), lead there first.
                spot = graph.height_spot(target_pos)
                r2 = graph.route(here, spot) if spot is not None else None
                if r2 is not None and r2[1] and len(r2[0]) >= 2:
                    r, self.known_spot = r2, spot
                    self._note(f"known paths: reach the target's height {math.dist(spot[:2], target_pos[:2]) / 100:.0f} m "
                               f"from it, at ({spot[0]:.0f}, {spot[1]:.0f}, {spot[2]:.0f}); leading there")
            if r is None or len(r[0]) < 2:
                self.known, self.known_done = [], False
            else:
                self.known, self.known_done = r
                self.known_idx = self.known_aim = 0
                length = sum(math.dist(a, b) for a, b in zip(self.known, self.known[1:])) / 100
                self._note(f"known paths: {'route to the target' if self.known_done else 'part of the way'}, "
                           f"{length:.0f} m over {len(self.known)} points")
                if not self.known_said:
                    self.known_said = True
                    from .speech import speech

                    if self.known_spot is not None:
                        speech.say(f"Known route up to its height, {max(1, round(length))} metres", interrupt=False)
                    elif self.known_done:
                        speech.say(f"Known route, {max(1, round(length))} metres", interrupt=False)
                    else:
                        speech.say("Known paths lead part of the way", interrupt=False)
            path = self.known
        if not path:
            return None
        # how far along you are: the nearest of the next few points
        window = range(self.known_idx, min(len(path), self.known_idx + 20))
        if window:
            self.known_idx = min(window, key=lambda k: math.dist(here[:2], path[k][:2]))
        while self.known_idx < len(path) and math.dist(here[:2], path[self.known_idx][:2]) < KNOWN_REACHED:
            self.known_idx += 1
        if self.known_idx >= len(path):
            return target_pos if self.known_done else None
        # Aim well ahead along the path while it runs straight (up to ~10 m), never at the point
        # nearest you: walking a metre to one side of the trail, that point is beside you, and the
        # tone would swing left and right as you pass each one. Corners people walked around are
        # never cut. The aim only moves forward, so small steps don't make it jump back and forth.
        j, run = self.known_idx, 0.0
        start = max(0, self.known_idx - 1)
        smooth = _smoothed(path, start, min(len(path), start + 40))
        while j + 1 < len(path):
            run += math.dist(path[j][:2], path[j + 1][:2])
            # The path itself must run straight (its zig-zag from the 1.2 m grid smoothed out), from
            # the stretch you're on (the point before the next one) to the aim. Not the line from
            # you: you may be a metre or two off to the side, and you're led back onto it.
            if run > KNOWN_AHEAD or j + 1 - start >= len(smooth) or                     not _straight(smooth[0], smooth[j + 1 - start], smooth[:j + 1 - start]):
                break
            j += 1
        if game.FLOOR_SEEN and pawn is not None:
            # line tests work: what you can actually walk straight to decides, not the trail's shape
            j = max(self.known_idx, self._known_visible(pawn, here, path, now))
        j = max(j, self.known_aim)
        if j >= len(path):
            j = len(path) - 1
        self.known_aim = j
        q = path[j]
        # the target itself once you're at the end of the path (not before: it may be round a corner)
        if self.known_done and j == len(path) - 1 and math.dist(q[:2], target_pos[:2]) < 300 \
                and math.dist(here[:2], q[:2]) < 200:
            return target_pos
        return (q[0], q[1], q[2] + 60)

    def _known_visible(self, pawn: Any, here: tuple, path: list, now: float) -> int:
        """With working line tests: the furthest point along the known path (up to ~10 m on) that
        you can walk straight to, checked down both sides of your body. Checked 4 times a second."""
        if not game.FLOOR_SEEN or pawn is None:
            return 0
        if now < getattr(self, "known_vis_at", 0.0) and getattr(self, "known_vis_path", None) is path:
            return self.known_vis
        self.known_vis_at, self.known_vis_path, self.known_vis = now + 0.25, path, 0
        feet = game.feet_z(pawn)
        base = feet if feet is not None else here[2] - 100
        run = 0.0
        for k in range(self.known_idx, len(path)):
            if k > self.known_idx:
                run += math.dist(path[k - 1][:2], path[k][:2])
            if run > KNOWN_AHEAD:
                break
            q = path[k]
            dx, dy = q[0] - here[0], q[1] - here[1]
            n = math.hypot(dx, dy) or 1.0
            sx, sy = -dy / n * BODY, dx / n * BODY
            ok = True
            for ox, oy in ((0.0, 0.0), (sx, sy), (-sx, -sy)):
                if game.fast_trace(pawn, (here[0] + ox, here[1] + oy, base + 50),
                                   (q[0] + ox, q[1] + oy, q[2] + 50)) is False:
                    ok = False
                    break
            if ok:
                self.known_vis = k
        return self.known_vis

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
        from .planner import GridPlanner, follow, progress

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
        # coarse grid far away; a margin either side so hovering near 35 m doesn't re-plan over and over
        gap = math.dist(here[:2], target_pos[:2])
        far = gap > (FAR - 300 if getattr(self, "path_cell", 90.0) == 180.0 and self.path else FAR + 300)
        cell = 180.0 if far else 90.0
        path = self.path
        off_route = bool(path) and min(math.dist(here[:2], q[:2]) for q in path) > cell * 2.5
        at_end = bool(path) and self.path_kind == "partial" and math.dist(here[:2], path[-1][:2]) < cell * 1.2
        grain_changed = bool(path) and (cell != self.path_cell)
        # A route that reaches the target is kept while you follow it; re-planned only when you leave
        # it, stop getting further along it, or get snagged (those set replan_at to 0).
        due = now >= self.replan_at and (self.path_kind != "done" or self.replan_at == 0.0)
        # A search still running from much further away than you are now is out of date: start
        # again from here. (A tester stood 3 m from a raised marker while the search
        # begun 70 m back was still going.)
        stale = (pl.state == "running" and self.search_from is not None
                 and now - getattr(self, "search_began", now) > STALE_SECONDS
                 and self.search_from[2] - gap > max(1500.0, 0.6 * self.search_from[2]))
        if stale:
            self._note("route planner: you've moved on since the search began; searching again from here")
        if stale or (pl.state != "running" and (not path or due or off_route or at_end or grain_changed)):
            # Start from the ground actually under you (measured), not an estimate from your height.
            ground = game.ground_z(pawn, loc[0], loc[1], loc[2])
            start = (loc[0], loc[1], ground if ground is not None else feet)
            self.start_note = (f"you at ({loc[0]:.0f}, {loc[1]:.0f}), body {loc[2]:.0f}, estimated feet {feet:.0f}, "
                               f"measured ground {'none' if ground is None else f'{ground:.0f}'}")
            pl.start(start, target_pos, cell=cell, max_cells=self.limit)
            self.search_from = (here[0], here[1], gap)
            self.search_began = now
            self.replan_at = now + 8.0
        pl.step(PLAN_BUDGET, PLAN_SECONDS)
        if pl.runs != self.runs_seen and pl.state in ("done", "partial", "failed"):
            self.runs_seen = pl.runs
            self._take_plan(pl, here, now)
        if not self.path:
            return None
        self._watch_progress(here, now)

        def visible(q: tuple) -> bool:
            """Can you walk straight there? Checked along both sides of your body as well as the
            middle, so a line that only just clears a corner doesn't leave you snagged on it."""
            dx, dy = q[0] - here[0], q[1] - here[1]
            n = math.hypot(dx, dy) or 1.0
            sx, sy = -dy / n * BODY, dx / n * BODY
            for ox, oy, hts in ((0.0, 0.0, (50.0, 130.0)), (sx, sy, (50.0,)), (-sx, -sy, (50.0,))):
                for h in hts:
                    if game.fast_trace(pawn, (here[0] + ox, here[1] + oy, here[2] + h),
                                       (q[0] + ox, q[1] + oy, q[2] + h)) is False:
                        return False
            return True

        self.path_at = progress(self.path, here, getattr(self, "path_at", 0))
        nxt = follow(self.path, here, visible, at=self.path_at)
        if nxt is None:
            return None
        # Don't slip back along the route just because a far point flickers out of sight for a
        # step; but only keep the earlier aim while you can still walk straight to it (keeping it
        # regardless led round corners into walls).
        k = self.path.index(nxt)
        aim = getattr(self, "follow_k", 0)
        if k < aim < len(self.path) and visible(self.path[aim]):
            nxt = self.path[aim]
        else:
            self.follow_k = k
        self._climb_cue(here)
        if self.path_kind == "done" and nxt == self.path[-1]:
            return target_pos
        return (nxt[0], nxt[1], nxt[2] + 100)

    def _climb_cue(self, here: tuple) -> None:
        """Say "Jump up here" / "Drop down here" when you reach a spot on the route where it
        goes up onto a ledge or down off one (once each)."""
        moves = getattr(self, "path_moves", [])
        if len(moves) != len(self.path) or len(self.path) < 2:
            return
        i = min(range(len(self.path)), key=lambda k: math.dist(here[:2], self.path[k][:2]))
        told = getattr(self, "climb_told", set())
        self.climb_told = told
        for j in range(i + 1, min(len(self.path), i + 3)):
            move = moves[j]
            if move not in ("jump", "drop"):
                continue
            edge = self.path[j - 1]
            spot = (round(edge[0] / 50), round(edge[1] / 50), move)
            if spot in told or math.dist(here[:2], edge[:2]) > 140:
                continue
            told.add(spot)
            from .speech import speech

            if move == "jump":
                try:
                    audio.play("ui", snd.ui("jump", 0.8))
                except Exception:
                    pass
                speech.say("Jump up here", interrupt=True)
            else:
                speech.say("Drop down here", interrupt=True)
            return

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
            self._climb_news(found=False)
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
        self.follow_k = self.path_at = 0
        self.path_moves = list(getattr(pl, "moves", [])) or ["walk"] * len(self.path)
        n_jump, n_drop = self.path_moves.count("jump"), self.path_moves.count("drop")
        if n_jump or n_drop:
            self._note(f"route planner: the route has {n_jump} jump{'s' if n_jump != 1 else ''} up and "
                       f"{n_drop} drop{'s' if n_drop != 1 else ''} down")
        # distance left along the route from each point, for the progress check
        self.tail = [0.0] * len(self.path)
        for k in range(len(self.path) - 2, -1, -1):
            self.tail[k] = self.tail[k + 1] + math.dist(self.path[k][:2], self.path[k + 1][:2])
        self.watch = None
        self._note(f"route planner: {'path to the target' if pl.state == 'done' else 'partial path toward the target'}, "
                   f"{length:.0f} m, {pl.cells_searched} points searched, grid {pl.cell / 100:.1f} m")
        if self.climb_wanted:
            self._climb_news(found=pl.state == "done")
        elif not self.announced:
            self.announced = True
            if pl.state == "done":
                speech.say(f"Route found, {max(1, round(length))} metres", interrupt=False)
            else:
                speech.say("Heading toward it, searching for the way in", interrupt=False)

    def _climb_news(self, found: bool) -> None:
        """Tell whoever is waiting below a raised target whether a way up was found."""
        if not self.climb_wanted:
            return
        from .speech import speech

        self.climb_wanted = False
        if found:
            speech.say("Way up found. " + self.climb_summary(), interrupt=False)
        else:
            speech.say("No way up found from here. " + self.no_way_hint(), interrupt=False)

    def climb_summary(self) -> str:
        """How the planned route gets up there: its length and jumps."""
        length = sum(math.dist(a[:2], b[:2]) for a, b in zip(self.path, self.path[1:])) / 100
        jumps = list(getattr(self, "path_moves", [])).count("jump")
        how = (f", with {jumps} jump{'s' if jumps != 1 else ''} up. You'll hear Jump up here at each" if jumps
               else ", up a slope or stairs")
        return f"{max(1, round(length))} metres{how}. Follow the beacon"

    def no_way_hint(self) -> str:
        if not game.FLOOR_SEEN:
            return "The mod's line tests aren't working yet, so it can't search. Try again in a moment"
        return ("It may be reached from further away, by a ladder or lift, or from another side. "
                "The search starts again as you move")

    def height_help(self, target_pos: tuple, up: bool = True) -> str:
        """For a raised (or lowered) target you're right under: what the mod knows about the way
        there, instead of leaving you to find it."""
        if self.known_spot is not None and self.known_done:
            d = math.dist(self.known_spot[:2], target_pos[:2]) / 100
            return f"Learned paths reach its height {max(1, round(d))} metres from it. The beacon leads there"
        if self.path_kind == "done" and self.path:
            return f"The beacon leads {'up' if up else 'down'}: " + self.climb_summary()
        self.climb_wanted = True
        if not game.FLOOR_SEEN:
            return f"The mod can't search for a way {'up' if up else 'down'} until its line tests work. You'll hear when it can"
        pl = self.planner
        if pl is None or pl.state != "running":
            self.replan_at = 0.0        # search again from right here
        return f"Searching for a way {'up' if up else 'down'}. You'll hear when one is found"

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
        self.duck = 1.0   # set by features.tick: quieter while enemy tones play

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
            # The loudest sound the mod makes, except in a fight, when it steps back so the enemy
            # tones (which share its pitch range) are clear.
            vol = (0.75 + 0.25 * closeness) * s.volume * self.duck
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
    pitch, yaw = game.aim_rotation(snap.eye, point)
    near = math.hypot(target_pos[0] - snap.eye[0], target_pos[1] - snap.eye[1]) < 400
    if point == target_pos and near:
        # Close to the thing itself: look at it (a little above its base), not level over the
        # top of it, so the game's crosshair-based Use finds it.
        pitch, _yaw = game.aim_rotation(snap.eye, (target_pos[0], target_pos[1], target_pos[2] + 60))
    else:
        pitch = 0   # travelling: keep the view level
    game.set_view(snap.pc, pitch, yaw)
    return _dist(snap.eye, target_pos), point != target_pos
