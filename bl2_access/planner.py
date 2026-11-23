"""Route finding of our own, for levels where the game gives the player no route.

An A* search over a grid of points about a metre apart, centred on where you stand. A step from
one point to a neighbour counts as walkable when line traces find nothing at knee height or
chest height between them, and there's floor at the neighbour no more than a step up or a short
drop down. That lets the route go round walls, through doorways and gaps, and up gentle
slopes, and keeps it off ledges.

The search does a limited number of traces each frame (`step(budget)`), so it never causes a
stutter. A typical detour is found in well under a second. If the target can't be reached
within the search limit, the route goes as far as it can toward it.

The planner knows nothing about the game: it gets a `trace(start, end)` function that returns
True when the line is clear, False when something's in the way, or None if tracing is
unavailable.
"""

from __future__ import annotations

import heapq
import math
from typing import Callable, Iterator

Point = tuple[float, float, float]

CELL = 90.0          # uu between grid points (doorways are 120 or more wide)
KNEE = 50.0          # trace heights above the floor
CHEST = 130.0
STEP_UP = 60.0       # highest floor rise between neighbours that still counts as walkable
DROP = 80.0          # deepest floor drop between neighbours that still counts as walkable
MAX_CELLS = 1600     # search limit (about a 40 m wide area)
NEIGHBOURS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]


class GridPlanner:
    def __init__(self, trace: Callable[[Point, Point], bool | None]) -> None:
        self.trace = trace
        self.state = "idle"        # idle, running, done (reached the target), partial, failed
        self.path: list[Point] = []
        self.goal: Point | None = None
        self._job: Iterator[None] | None = None
        self._spent = 0
        self.cells_searched = 0

    # ------------------------------------------------------------ public
    def start(self, feet: Point, goal: Point) -> None:
        self.goal = goal
        self.state = "running"
        self.path = []
        self.cells_searched = 0
        self._job = self._search(feet, goal)

    def step(self, budget: int = 120) -> str:
        """Do up to `budget` line traces of searching. Returns the state."""
        if self.state != "running" or self._job is None:
            return self.state
        self._spent = 0
        self._budget = budget
        try:
            while self._spent < budget:
                next(self._job)
        except StopIteration:
            self._job = None
        return self.state

    # ------------------------------------------------------------ tracing with a budget
    def _t(self, a: Point, b: Point) -> bool | None:
        self._spent += 1
        return self.trace(a, b)

    def _floor(self, x: float, y: float, z: float) -> float | None:
        """Floor height at (x, y), searching from a step above z to a short drop below it."""
        if self._t((x, y, z + STEP_UP), (x, y, z - DROP)) is not False:
            return None  # no floor in reach: a drop, a gap or a hole
        if self._t((x, y, z + STEP_UP), (x, y, z)) is False:
            lo, hi = z, z + STEP_UP          # floor is above where we stand
        else:
            lo, hi = z - DROP, z
        mid = (lo + hi) / 2
        if self._t((x, y, hi), (x, y, mid)) is False:
            return (mid + hi) / 2
        return (lo + mid) / 2

    # ------------------------------------------------------------ the search (a generator: yields to share time)
    def _search(self, feet: Point, goal: Point) -> Iterator[None]:
        ox, oy, oz = feet

        def centre(c: tuple[int, int]) -> tuple[float, float]:
            return ox + c[0] * CELL, oy + c[1] * CELL

        def h(c: tuple[int, int]) -> float:
            x, y = centre(c)
            return math.hypot(goal[0] - x, goal[1] - y)

        start = (0, 0)
        z = {start: oz}
        g = {start: 0.0}
        parent: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
        open_heap = [(h(start), 0.0, start)]
        closed: set[tuple[int, int]] = set()
        best, best_h = start, h(start)

        while open_heap:
            _f, gc, cur = heapq.heappop(open_heap)
            if cur in closed:
                continue
            closed.add(cur)
            self.cells_searched = len(closed)
            hc = h(cur)
            if hc < best_h:
                best, best_h = cur, hc
            if hc <= CELL * 0.75 or (hc <= CELL * 1.5 and abs(goal[2] - z[cur]) < 250):
                best = cur
                self._finish(best, parent, z, centre, reached=True)
                return
            if len(closed) >= MAX_CELLS:
                break
            cx, cy = centre(cur)
            cz = z[cur]
            for dx, dy in NEIGHBOURS:
                nb = (cur[0] + dx, cur[1] + dy)
                if nb in closed:
                    continue
                nx, ny = centre(nb)
                # Walkable step: nothing in the way at knee or chest height, floor at the other end.
                if self._t((cx, cy, cz + KNEE), (nx, ny, cz + KNEE)) is not True:
                    yield from self._pause()
                    continue
                if self._t((cx, cy, cz + CHEST), (nx, ny, cz + CHEST)) is not True:
                    yield from self._pause()
                    continue
                nz = self._floor(nx, ny, cz)
                yield from self._pause()
                if nz is None:
                    continue
                cost = gc + (CELL * (1.414 if dx and dy else 1.0))
                if cost < g.get(nb, 1e18):
                    g[nb] = cost
                    z[nb] = nz
                    parent[nb] = cur
                    heapq.heappush(open_heap, (cost + h(nb), cost, nb))
        self._finish(best, parent, z, centre, reached=False)

    def _pause(self) -> Iterator[None]:
        if self._spent >= self._budget:
            yield None

    def _finish(self, end, parent, z, centre, reached: bool) -> None:
        cells = []
        c = end
        while c is not None:
            cells.append(c)
            c = parent[c]
        cells.reverse()
        self.path = [(*centre(c), z[c]) for c in cells]
        if reached:
            self.state = "done"
        elif len(self.path) > 1:
            self.state = "partial"
        else:
            self.state = "failed"


def follow(path: list[Point], here: Point, visible: Callable[[Point], bool], reach: float = 700.0) -> Point | None:
    """The point to head for on a route: the furthest point you can walk straight to (within
    `reach`), so the beacon doesn't zigzag through every grid point."""
    if not path:
        return None
    # Where on the path you are: the nearest point.
    i = min(range(len(path)), key=lambda k: math.dist(path[k][:2], here[:2]))
    best = path[min(i + 1, len(path) - 1)]
    for k in range(i + 1, len(path)):
        if math.dist(path[k][:2], here[:2]) > reach:
            break
        if visible(path[k]):
            best = path[k]
    return best
