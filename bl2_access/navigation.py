"""Guidance to a chosen place: the beacon, route finding, and the navigation assist turn.

Beacon: a steady tone (not separate pings) on its own stream, so its direction is always
current. It's panned to where you need to go, muffled when that's behind you, and switches to
a brighter "on course" tone when you face within a few degrees of the right way. It pulses
faster as you get closer. The pitch rises when the target is above you and falls when below.

Route: where the level has a navigation network, the game's own path finding
(Controller.FindPathToward / FindPathTo) gives the next point on a walkable route. The beacon
leads to that point instead of straight through walls, moving on as you reach each one. Where
the game gives no route, the beacon points straight at the target.

Navigation assist (an option): Modifier + right stick click, or the apostrophe key, turns you to
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
ROUTE_EVERY = 0.5       # seconds between route updates
LEAD = 0.1              # seconds of beacon tone queued ahead
BEACON_BASE = 56        # 700 Hz at the same height as you


def beacon_cycles(elev_deg: float) -> int:
    x = max(-1.0, min(1.0, elev_deg / 30))
    return max(8, int(round(BEACON_BASE * 2 ** (x * 0.5))))  # up to half an octave each way


class Route:
    """Next point on the game's walkable route to a target, when the game provides one."""

    def __init__(self) -> None:
        self.node: tuple[float, float, float] | None = None
        self.next_update = 0.0
        self.supported: bool | None = None   # learned on first try; logged once
        self.target_key = ""

    def reset(self) -> None:
        self.node, self.next_update, self.target_key = None, 0.0, ""

    def next_point(self, pc: Any, eye: tuple, target_pos: tuple, target_actor: Any, key: str,
                   now: float) -> tuple[float, float, float]:
        """Where to head now: the next route point, or the target itself."""
        if key != self.target_key:
            self.reset()
            self.target_key = key
        if self.node is not None and _dist(eye, self.node) < NODE_REACHED:
            self.node, self.next_update = None, 0.0  # reached it: ask for the next one now
        if now >= self.next_update and self.supported is not False:
            self.next_update = now + ROUTE_EVERY
            self.node = self._ask(pc, eye, target_pos, target_actor)
        if self.node is None:
            return target_pos
        # Ignore a route point that's further away than the target itself (a bad route).
        if _dist(eye, self.node) > _dist(eye, target_pos) + 200:
            return target_pos
        return self.node

    def _ask(self, pc: Any, eye: tuple, target_pos: tuple, target_actor: Any) -> tuple | None:
        from . import trace

        found = None
        tried = False
        calls = []
        if target_actor is not None:
            calls.append(("FindPathToward", lambda: pc.FindPathToward(target_actor)))
        calls.append(("FindPathTo", lambda: pc.FindPathTo(game.vec(*target_pos))))
        for name, call in calls:
            try:
                node = call()
                tried = True
            except Exception:
                continue
            pos = game.location(node) if node is not None else None
            if pos is not None and _dist(eye, pos) > 40 and _dist(pos, target_pos) > 60:
                found = pos
                break
        if self.supported is None:
            self.supported = tried
            trace.note(f"route finding: {'available' if tried else 'not available'}"
                       f"{', first route point found' if found else ''}")
        return found


def _dist(a: tuple, b: tuple) -> float:
    return math.dist(a, b)


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
        point = self.route.next_point(snap.pc, snap.eye, target_pos, target_actor, key, now)
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
    point = beacon.route.next_point(snap.pc, snap.eye, target_pos, target_actor, key, time.perf_counter())
    _pitch, yaw = game.aim_rotation(snap.eye, point)
    game.set_view(snap.pc, 0, yaw)
    return _dist(snap.eye, target_pos), point != target_pos
