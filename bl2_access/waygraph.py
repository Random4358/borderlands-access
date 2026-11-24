"""Known walkable ways around each level, built without the game's line tests.

The engine's own route and line-test functions don't run through the SDK (they return fixed
answers), so routes are built from things the mod *can* read:

1. Navigation points. If the level has path nodes, each one's PathList holds the level
   designer's links (ReachSpecs) to its neighbours. Read once per level; logged either way.
2. Learned trails. While you play, the positions of every walking character, yours and the
   game's (enemies and NPCs walk the game's real navigation mesh), are sampled a few times a
   second. Two samples of the same character a short way apart are a step someone actually
   took, so they're linked. The result is saved per level in the mod's "maps" folder, so it
   grows every time you or anyone else plays the level and is there after a restart.

A route is an A* search over these links from the point nearest you to the one nearest the
target. If no known way reaches the target, it leads to the known point closest to it.
"""

from __future__ import annotations

import heapq
import json
import math
import os
import time
from typing import Any

from . import game

MOD_DIR = os.path.dirname(os.path.abspath(__file__))
MAP_DIR = os.path.join(MOD_DIR, "maps")

CELL = 120.0          # uu: trail points are merged on a grid this size (~1.2 m)
SAMPLE_EVERY = 0.25   # seconds between position samples
MAX_STEP = 450.0      # uu: further than this between two samples = not one step (teleport, fast travel)
MAX_GAP = 1.5         # seconds: samples further apart than this aren't linked
FLAT = 100.0          # uu of height change still walkable both ways; more = only the way it was taken
MAX_NODES = 80000
SAVE_EVERY = 30.0
NEAR_START = 600.0    # uu: the route starts at a known point at most this far from you
GOAL_NEAR = 300.0     # uu: a known point this close to the target counts as reaching it
LINK_NAV = 200.0      # uu: navigation points this close to a trail point are joined to it
SEARCH_LIMIT = 20000  # nodes expanded per search at most


def _vec(v: Any) -> tuple[float, float, float] | None:
    try:
        return (float(v.X), float(v.Y), float(v.Z))
    except Exception:
        return None


def _walking(p: Any) -> bool:
    """On the ground (not falling, flying or swimming)."""
    try:
        ph = p.Physics
    except Exception:
        return True
    name = getattr(ph, "name", None)
    if isinstance(name, str):
        return "Walking" in name
    try:
        return int(ph) == 1   # PHYS_Walking
    except Exception:
        return "Walking" in str(ph)


def raw_map(pc: Any) -> str:
    try:
        return str(pc.WorldInfo.GetMapName(True)) or ""
    except Exception:
        try:
            return str(pc.WorldInfo.GetMapName(False)) or ""
        except Exception:
            return ""


class WayGraph:
    def __init__(self) -> None:
        self.map = ""
        self.clear()

    def clear(self) -> None:
        self.pos: list[list[float]] = []          # [x, y, z, samples]
        self.keys: dict[tuple, int] = {}          # grid key -> node id (trail points)
        self.edges: dict[int, set[int]] = {}
        self.buckets: dict[tuple, list[int]] = {}  # 5 m buckets, for "nearest" lookups
        self.last: dict[int, tuple[float, int]] = {}  # character id -> (time, node) of last sample
        self.next_sample = 0.0
        self.next_save = 0.0
        self.dirty = False
        self.nav_count = 0
        self.nav_links = 0
        self.nav_read = False
        self.nav_due = 0.0
        self.version = 0     # bumped when the graph changes meaningfully (for re-routing)
        self.added = 0

    # ------------------------------------------------------------ building
    def _bucket(self, x: float, y: float) -> tuple:
        return (int(x // 500), int(y // 500))

    def _new_node(self, p: tuple, key: tuple | None = None) -> int:
        i = len(self.pos)
        self.pos.append([p[0], p[1], p[2], 1])
        if key is not None:
            self.keys[key] = i
        self.edges[i] = set()
        self.buckets.setdefault(self._bucket(p[0], p[1]), []).append(i)
        return i

    def node_at(self, p: tuple) -> int | None:
        key = (round(p[0] / CELL), round(p[1] / CELL), round(p[2] / CELL))
        i = self.keys.get(key)
        if i is not None:
            n = self.pos[i]
            if n[3] < 50:   # settle the point at the average of where people stood
                n[0] += (p[0] - n[0]) / (n[3] + 1)
                n[1] += (p[1] - n[1]) / (n[3] + 1)
                n[2] += (p[2] - n[2]) / (n[3] + 1)
                n[3] += 1
            return i
        if len(self.pos) >= MAX_NODES:
            return None
        self.dirty = True
        self.added += 1
        return self._new_node(p, key)

    def link(self, a: int, b: int) -> None:
        if a == b:
            return
        if b not in self.edges[a]:
            self.edges[a].add(b)
            self.dirty = True
            self.added += 1
        dz = self.pos[b][2] - self.pos[a][2]
        if abs(dz) <= FLAT and a not in self.edges[b]:
            self.edges[b].add(a)

    def record(self, who: int, p: tuple, now: float) -> None:
        """One position sample of a walking character."""
        i = self.node_at(p)
        if i is None:
            return
        prev = self.last.get(who)
        if prev is not None:
            t, j = prev
            if now - t <= MAX_GAP and j < len(self.pos) and math.dist(self.pos[j][:3], self.pos[i][:3]) <= MAX_STEP:
                self.link(j, i)
        self.last[who] = (now, i)
        if self.added >= 20:
            self.added = 0
            self.version += 1

    def tick(self, pc: Any, me: Any, now: float) -> None:
        """Sample every walking character (call every frame; samples a few times a second)."""
        name = raw_map(pc)
        if name and name != self.map:
            self.switch(name, pc)
        if not self.map:
            return
        if not self.nav_read and now >= self.nav_due:
            self.read_nav_points()   # a few seconds in, once the level's parts have streamed in
        if now < self.next_sample:
            return
        self.next_sample = now + SAMPLE_EVERY
        seen = set()
        for p in game.iter_pawns(pc):
            try:
                if p.bDeleteMe or p.bHidden:
                    continue
                if "Vehicle" in game.class_name(p):
                    continue
                h = game.health(p)
                if h is not None and h[0] <= 0:
                    continue
                loc = _vec(p.Location)
            except Exception:
                continue
            if loc is None:
                continue
            try:
                who = 0 if p == me else hash(p._path_name())
            except Exception:
                who = id(p)
            seen.add(who)
            if not _walking(p):
                continue   # keep its last ground point, so a jump or drop still links up
            self.record(who, loc, now)
        for who in [w for w in self.last if w not in seen]:
            del self.last[who]
        if self.dirty and now >= self.next_save:
            self.save()

    # ------------------------------------------------------------ levels and files
    def _file(self, name: str) -> str:
        safe = "".join(c for c in name if c.isalnum() or c in "_-") or "unknown"
        return os.path.join(MAP_DIR, f"{safe}.json")

    def switch(self, name: str, pc: Any = None) -> None:
        if self.map and self.dirty:
            self.save()
        self.clear()
        self.map = name
        self.load()
        self.nav_due = time.perf_counter() + 8.0
        self.next_save = time.perf_counter() + SAVE_EVERY

    def load(self) -> None:
        path = self._file(self.map)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            self._note(f"level layout: no saved paths for {self.map} yet; learning as you and others walk")
            return
        except Exception as e:  # noqa: BLE001
            self._note(f"level layout: couldn't read saved paths ({e}); starting fresh")
            return
        for x, y, z, n in data.get("nodes", []):
            key = (round(x / CELL), round(y / CELL), round(z / CELL))
            i = self._new_node((x, y, z), key)
            self.pos[i][3] = n
        for a, b in data.get("edges", []):
            if 0 <= a < len(self.pos) and 0 <= b < len(self.pos):
                self.edges[a].add(b)
        self.version += 1
        self._note(f"level layout: loaded {len(self.pos)} known points and "
                   f"{sum(len(e) for e in self.edges.values())} links for {self.map}")

    def save(self) -> None:
        self.next_save = time.perf_counter() + SAVE_EVERY
        if not self.map:
            return
        # Navigation points are re-read from the level each time, so only trail points are kept.
        trail = sorted(self.keys.values())
        index = {old: new for new, old in enumerate(trail)}
        data = {
            "version": 1, "cell": CELL,
            "nodes": [[round(self.pos[i][0], 1), round(self.pos[i][1], 1), round(self.pos[i][2], 1),
                       int(self.pos[i][3])] for i in trail],
            "edges": [[index[a], index[b]] for a in trail for b in self.edges[a] if b in index],
        }
        try:
            os.makedirs(MAP_DIR, exist_ok=True)
            tmp = self._file(self.map) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, separators=(",", ":"))
            os.replace(tmp, self._file(self.map))
            self.dirty = False
        except Exception as e:  # noqa: BLE001
            self._note(f"level layout: couldn't save paths ({e})")

    def _note(self, text: str) -> None:
        try:
            from . import trace

            trace.note(text)
        except Exception:
            pass

    # ------------------------------------------------------------ navigation points
    def read_nav_points(self) -> None:
        """Add the level's path nodes and their links, if it has any. Logged either way."""
        self.nav_read = True
        try:
            points = game.world_actors(["NavigationPoint"])
        except Exception as e:  # noqa: BLE001
            self._note(f"level layout: couldn't list navigation points ({e})")
            return
        ids: dict[int, int] = {}
        kinds: dict[str, int] = {}
        for np_ in points:
            loc = _vec(getattr(np_, "Location", None))
            if loc is None:
                continue
            ids[id(np_)] = self._new_node(loc)
            try:
                ids[hash(np_._path_name())] = ids[id(np_)]
            except Exception:
                pass
            kinds[game.class_name(np_)] = kinds.get(game.class_name(np_), 0) + 1
        links, sample = 0, ""
        for np_ in points:
            a = ids.get(id(np_))
            if a is None:
                continue
            try:
                specs = list(np_.PathList)
            except Exception:
                continue
            for spec in specs:
                try:
                    end = spec.End
                    end = getattr(end, "Actor", end)
                    b = ids.get(id(end))
                    if b is None:
                        try:
                            b = ids.get(hash(end._path_name()))
                        except Exception:
                            b = None
                    if b is None:
                        continue
                    self.edges[a].add(b)
                    links += 1
                    if not sample:
                        sample = (f"{game.class_name(spec)} from {game.class_name(np_)} to {game.class_name(end)}, "
                                  f"{getattr(spec, 'Distance', '?')} uu")
                except Exception:
                    continue
        self.nav_count, self.nav_links = len(set(ids.values())), links
        # join navigation points to trail points right beside them
        joined = 0
        trail = set(self.keys.values())
        for i in set(ids.values()):
            j = self.nearest(self.pos[i][:3], LINK_NAV, only=trail)
            if j is not None and abs(self.pos[j][2] - self.pos[i][2]) < 80:
                self.edges[i].add(j)
                self.edges[j].add(i)
                joined += 1
        top = ", ".join(f"{k} {v}" for k, v in sorted(kinds.items(), key=lambda kv: -kv[1])[:6])
        self._note(f"level layout: {self.nav_count} navigation points ({top or 'none'}), {links} links"
                   f"{'; e.g. ' + sample if sample else ''}; {joined} joined to learned paths")
        if self.nav_count:
            self.version += 1

    # ------------------------------------------------------------ searching
    def nearest(self, p: tuple, within: float, only: set | None = None) -> int | None:
        bx, by = self._bucket(p[0], p[1])
        r = int(within // 500) + 1
        best, best_d = None, within
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                for i in self.buckets.get((bx + dx, by + dy), ()):
                    if only is not None and i not in only:
                        continue
                    q = self.pos[i]
                    d = math.hypot(q[0] - p[0], q[1] - p[1]) + abs(q[2] - p[2]) * 1.5
                    if d < best_d:
                        best, best_d = i, d
        return best

    def route(self, start: tuple, goal: tuple) -> tuple[list[tuple], bool] | None:
        """Known walkable points from near `start` toward `goal`, and whether they reach it.
        None if you're not near any known point yet."""
        s = self.nearest(start, NEAR_START)
        if s is None:
            return None
        P = self.pos

        def h(i: int) -> float:
            q = P[i]
            return math.dist((q[0], q[1], q[2]), goal)

        came: dict[int, int] = {s: -1}
        cost = {s: 0.0}
        heap = [(h(s), 0.0, s)]
        best, best_h = s, h(s)
        reached = None
        expanded = 0
        while heap and expanded < SEARCH_LIMIT:
            _f, g, i = heapq.heappop(heap)
            if g > cost.get(i, math.inf):
                continue
            expanded += 1
            hi = h(i)
            if hi < best_h:
                best, best_h = i, hi
            if hi <= GOAL_NEAR:
                reached = i
                break
            qi = P[i]
            for j in self.edges.get(i, ()):
                qj = P[j]
                ng = g + math.dist((qi[0], qi[1], qi[2]), (qj[0], qj[1], qj[2]))
                if ng < cost.get(j, math.inf):
                    cost[j] = ng
                    came[j] = i
                    heapq.heappush(heap, (ng + h(j), ng, j))
        end = reached if reached is not None else best
        path = []
        while end != -1:
            q = P[end]
            path.append((q[0], q[1], q[2]))
            end = came[end]
        path.reverse()
        return path, reached is not None


graph = WayGraph()
