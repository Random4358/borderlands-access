"""Route finding of our own, for levels where the game gives the player no route.

An A* search over a grid of points about a metre apart, centred on where you stand. Each point
also has a height, so a floor and a ledge above it are different places. Three kinds of move:

* walk: line traces find nothing at knee or chest height between the two points, and there's
  floor at the neighbour no more than a step up or a short drop down (stairs, slopes);
* jump up: onto a ledge, crate or step up to about a jump's height, with headroom to jump;
* drop down: off an edge onto floor up to a few metres below.

Jumps and drops cost more than walking, so the route uses them only when they help, for
example to reach a marker on a ledge. A target counts as reached only at about its height:
standing under a marker on a ledge isn't there yet. Each point of the route says how it's
reached (`moves`), so the beacon can say "Jump up here" or "Drop down here".

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
import time
from typing import Callable, Iterator

Point = tuple[float, float, float]

CELL = 90.0          # uu between grid points (doorways are 120 or more wide)
KNEE = 50.0          # trace heights above the floor
CHEST = 130.0
STEP_UP = 70.0       # highest floor rise between neighbours that still counts as walkable (stairs)
DROP = 80.0          # deepest floor drop between neighbours that still counts as walkable
MAX_CELLS = 1600     # search limit (about a 40 m wide area)
JUMP_UP = 110.0      # highest ledge you can jump onto (uu)
MAX_DROP = 450.0     # deepest drop the route will take you down
JUMP_COST = 3.0      # a jump or a drop counts as this many cells of walking
ABOVE = 230.0        # a target up to this far above the floor counts as reached (markers float)
BELOW = 80.0         # and this far below it
NEIGHBOURS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]


class GridPlanner:
    def __init__(self, trace: Callable[[Point, Point], bool | None]) -> None:
        self.trace = trace
        self.state = "idle"        # idle, running, done (reached the target), partial, failed
        self.path: list[Point] = []
        self.moves: list[str] = []     # how each point of the path is reached: walk, jump or drop
        self.goal: Point | None = None
        self._job: Iterator[None] | None = None
        self._spent = 0
        self.cells_searched = 0
        self.cell = CELL
        self.max_cells = MAX_CELLS
        self.best_gap = 0.0       # how far the end of the path is from the target (uu)
        self.runs = 0             # increases each time a search finishes
        self.rejects = {"no floor": 0, "knee": 0, "chest": 0}   # why steps were refused (for the log)

    # ------------------------------------------------------------ public
    def start(self, feet: Point, goal: Point, cell: float = CELL, max_cells: int | None = None) -> None:
        """Begin a search. `cell` is the grid spacing (coarser for long walks outdoors);
        `max_cells` the search limit (larger when an earlier search couldn't get close)."""
        self.goal = goal
        self.state = "running"
        self.path = []
        self.cells_searched = 0
        self.cell = cell
        self.max_cells = max_cells or MAX_CELLS
        # A bigger grid step crosses more ground, so it may rise or fall more (about 40 degrees).
        self.up = max(STEP_UP, cell * 0.85)
        self.down = max(DROP, cell * 0.95)
        self.rejects = {"no floor": 0, "knee": 0, "chest": 0}
        self._job = self._search(feet, goal)

    def step(self, budget: int = 120, seconds: float | None = None, minimum: int = 120) -> str:
        """Do up to `budget` line traces of searching, or with `seconds`, at least `minimum` and
        then as many more as fit in that time (still at most `budget`). Returns the state."""
        if self.state != "running" or self._job is None:
            return self.state
        self._spent = 0
        deadline = time.perf_counter() + seconds if seconds else None
        try:
            if deadline is None:
                self._budget = budget
                while self._spent < budget:
                    next(self._job)
            else:
                while self._spent < budget and (self._spent < minimum or time.perf_counter() < deadline):
                    self._budget = min(budget, self._spent + 30)
                    next(self._job)
        except StopIteration:
            self._job = None
        return self.state

    # ------------------------------------------------------------ tracing with a budget
    def _t(self, a: Point, b: Point) -> bool | None:
        self._spent += 1
        return self.trace(a, b)

    def _floor(self, x: float, y: float, z: float) -> float | None:
        """Floor height at (x, y), searching from a step above z to a drop below it, to within
        about 10 uu."""
        up, down = getattr(self, "up", STEP_UP), getattr(self, "down", DROP)
        return self._floor_between(x, y, z + up, z - down)

    def _floor_between(self, x: float, y: float, hi: float, lo: float) -> float | None:
        """The highest floor at (x, y) between heights lo and hi, or None."""
        if self._t((x, y, hi + 40), (x, y, hi)) is False:
            return None  # solid already at the top of the range: the surface is higher than that
        if self._t((x, y, hi), (x, y, lo)) is not False:
            return None  # no floor in reach: a drop, a gap or a hole
        while hi - lo > 20:
            mid = (lo + hi) / 2
            if self._t((x, y, hi), (x, y, mid)) is False:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    def _clear(self, a: Point, b: Point, nz: float, cz: float) -> bool:
        """Nothing at knee or chest height between two floor points."""
        return (self._t((a[0], a[1], cz + KNEE), (b[0], b[1], nz + KNEE)) is True
                and self._t((a[0], a[1], cz + CHEST), (b[0], b[1], nz + CHEST)) is True)

    # ------------------------------------------------------------ the search (a generator: yields to share time)
    def _search(self, feet: Point, goal: Point) -> Iterator[None]:
        ox, oy, oz = feet
        CELL = self.cell
        gz = goal[2]

        def centre(c: tuple) -> tuple[float, float]:
            return ox + c[0] * CELL, oy + c[1] * CELL

        def key(ix: int, iy: int, z: float) -> tuple:
            return (ix, iy, int(round(z / 100.0)))

        def h(c: tuple, zc: float) -> float:
            x, y = centre(c)
            flat = math.hypot(goal[0] - x, goal[1] - y)
            # how far the floor is from the target's height band (0 inside it)
            vert = max(0.0, (gz - ABOVE) - zc) + max(0.0, zc - (gz + BELOW))
            return math.hypot(flat, vert)

        def at_goal(c: tuple, zc: float) -> bool:
            x, y = centre(c)
            flat = math.hypot(goal[0] - x, goal[1] - y)
            right_height = -BELOW <= gz - zc <= ABOVE
            # On the target, or right beside it (the target itself is often inside furniture or
            # a wall, so the last metre can't be walked); either way at about its height.
            return right_height and flat <= CELL * 1.5

        start = key(0, 0, oz)
        z = {start: oz}
        g = {start: 0.0}
        how: dict[tuple, str] = {start: "walk"}
        parent: dict[tuple, tuple | None] = {start: None}
        open_heap = [(h(start, oz), 0.0, start)]
        closed: set[tuple] = set()
        best, best_h = start, h(start, oz)

        def offer(nb: tuple, nz: float, cost: float, move: str, cur: tuple) -> None:
            if cost < g.get(nb, 1e18):
                g[nb] = cost
                z[nb] = nz
                how[nb] = move
                parent[nb] = cur
                heapq.heappush(open_heap, (cost + h(nb, nz), cost, nb))

        while open_heap:
            _f, gc, cur = heapq.heappop(open_heap)
            if cur in closed:
                continue
            closed.add(cur)
            self.cells_searched = len(closed)
            cz = z[cur]
            hc = h(cur, cz)
            if hc < best_h:
                best, best_h = cur, hc
            if at_goal(cur, cz):
                self._finish(cur, parent, z, how, centre, reached=True, gap=0.0)
                return
            if len(closed) >= self.max_cells:
                break
            cx, cy = centre(cur)
            target_above = gz - cz > ABOVE
            for dx, dy in NEIGHBOURS:
                ix, iy = cur[0] + dx, cur[1] + dy
                nx, ny = centre((ix, iy))
                step = CELL * (1.414 if dx and dy else 1.0)
                walked = False
                # walk: floor at the other end (at most a stair step up or a small drop), and
                # nothing in the way at knee or chest height
                nz = self._floor(nx, ny, cz)
                if nz is None:
                    self.rejects["no floor"] += 1
                elif self._clear((cx, cy), (nx, ny), nz, cz):
                    walked = True
                    nb = key(ix, iy, nz)
                    if nb not in closed:
                        offer(nb, nz, gc + step, "walk", cur)
                else:
                    self.rejects["knee"] += 1
                yield from self._pause()
                # jump up: a ledge higher than a step but within a jump, with room to jump
                # (one cheap check first: open space above the obstacle at jump height, which a
                # wall fails at once)
                if (not walked or target_above) and self._t(
                        (cx, cy, cz + JUMP_UP + KNEE), (nx, ny, cz + JUMP_UP + KNEE)) is True:
                    jz = self._floor_between(nx, ny, cz + JUMP_UP, cz + self.up + 1)
                    if (jz is not None
                            and self._t((cx, cy, cz + CHEST), (cx, cy, cz + JUMP_UP + CHEST)) is True
                            and self._clear((cx, cy), (nx, ny), jz, jz)):
                        nb = key(ix, iy, jz)
                        if nb not in closed:
                            offer(nb, jz, gc + step + CELL * JUMP_COST, "jump", cur)
                    yield from self._pause()
                # drop down: off an edge onto floor further below
                if nz is None:
                    dz_ = self._floor_between(nx, ny, cz - self.down, cz - MAX_DROP)
                    if dz_ is not None and self._t((cx, cy, cz + KNEE), (nx, ny, cz + KNEE)) is True:
                        nb = key(ix, iy, dz_)
                        if nb not in closed:
                            offer(nb, dz_, gc + step + CELL * JUMP_COST, "drop", cur)
                    yield from self._pause()
        self._finish(best, parent, z, how, centre, reached=False, gap=best_h)

    def _pause(self) -> Iterator[None]:
        if self._spent >= self._budget:
            yield None

    def _finish(self, end, parent, z, how, centre, reached: bool, gap: float = 0.0) -> None:
        self.best_gap = gap
        self.runs += 1
        cells = []
        c = end
        while c is not None:
            cells.append(c)
            c = parent[c]
        cells.reverse()
        self.path = [(*centre(c), z[c]) for c in cells]
        self.moves = [how.get(c, "walk") for c in cells]
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
