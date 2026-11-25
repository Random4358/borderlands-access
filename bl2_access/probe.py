"""Recording what's around a marker the mod can't lead you to, so the way there can be worked out.

When you're within about 12 m of a marker that's well above or below you, the mod writes, once
per marker, to logs/marker_probe.txt:

* a height map of the ground around the marker: a 13 by 13 grid, one metre apart, centred on
  the marker, each cell the highest floor there relative to the marker, in decimetres (so 0 is
  level with it, -25 is 2.5 m below), "##" where solid rock or a wall fills the space above, and
  ".." where there's no floor within 8 m below (a drop or a hole);
* walls: for each pair of neighbouring cells at about the same height, whether something blocks
  walking between them at knee or chest height;
* every actor within 6 m of the marker (its class, name and position relative to the marker), to
  catch ladders, lifts, jump pads and the object the marker is on;
* where you are, and the known paths (learned trails) near it.

Everything is measured with the mod's line tests, about 1,500 of them, done in one go (a few
hundredths of a second).
"""

from __future__ import annotations

import math
import os
import time
from typing import Any

from . import game

GRID = 6              # cells each side of the marker (13 x 13)
STEP = 100.0          # uu between cells (1 m)
ABOVE = 400.0         # search for floor from this far above the marker
BELOW = 800.0         # down to this far below it
NEAR_ACTORS = 600.0   # uu: actors this close to the marker are listed
PROBE_WITHIN = 1200.0  # uu across the floor: probe when you're this close to a raised marker

_done: set[str] = set()


def _floor(pawn: Any, x: float, y: float, top: float, bottom: float) -> float | str:
    """Highest floor at (x, y) between top and bottom; '##' if solid right at the top, '..' if
    no floor at all."""
    if game.fast_trace(pawn, (x, y, top + 40), (x, y, top)) is False:
        return "##"
    if game.fast_trace(pawn, (x, y, top), (x, y, bottom)) is not False:
        return ".."
    lo, hi = bottom, top
    while hi - lo > 10:
        mid = (lo + hi) / 2
        if game.fast_trace(pawn, (x, y, top), (x, y, mid)) is False:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _blocked(pawn: Any, a: tuple, b: tuple) -> str:
    """'' if you could walk from floor point a to b; else what's in the way."""
    for h, what in ((50.0, "knee"), (130.0, "chest")):
        if game.fast_trace(pawn, (a[0], a[1], a[2] + h), (b[0], b[1], b[2] + h)) is False:
            return what
    return ""


def probe(pawn: Any, name: str, target: tuple, why: str = "") -> str | None:
    """Write the surroundings of one marker to logs/marker_probe.txt. Returns the file path."""
    if not game.FLOOR_SEEN or pawn is None:
        return None
    from .trace import LOG_DIR

    tx, ty, tz = target
    t0 = time.perf_counter()
    rows: list[list[float | str]] = []
    for j in range(GRID, -GRID - 1, -1):             # north (+y) at the top
        row = []
        for i in range(-GRID, GRID + 1):
            row.append(_floor(pawn, tx + i * STEP, ty + j * STEP, tz + ABOVE, tz - BELOW))
        rows.append(row)

    def cell(i: int, j: int) -> float | str:
        return rows[GRID - j][i + GRID]

    lines = [f"\n==== {time.strftime('%Y-%m-%d %H:%M:%S')} {name} at ({tx:.0f}, {ty:.0f}, {tz:.0f}){f' ({why})' if why else ''}"]
    loc = game.location(pawn)
    feet = game.feet_z(pawn)
    if loc is not None:
        lines.append(f"you: ({loc[0]:.0f}, {loc[1]:.0f}), feet {feet:.0f} = {(feet - tz) / 10:+.0f} dm from the marker, "
                     f"{math.hypot(loc[0] - tx, loc[1] - ty) / 100:.1f} m away across the floor")
    lines.append("floor heights around the marker, in decimetres relative to it (north up, east right, 1 m apart; "
                 "## solid above, .. no floor within 8 m; [ ] is the marker's cell):")
    lines.append("      " + " ".join(f"{i:>4}" for i in range(-GRID, GRID + 1)))
    for j in range(GRID, -GRID - 1, -1):
        out = []
        for i in range(-GRID, GRID + 1):
            v = cell(i, j)
            s = v if isinstance(v, str) else f"{(v - tz) / 10:+.0f}"
            out.append(f"[{s:>3}]" if i == 0 and j == 0 else f"{s:>4}")
        lines.append(f"{j:>4}  " + " ".join(out))
    # walls between neighbouring cells at about the same height (within a stair step)
    walls = []
    for j in range(-GRID, GRID + 1):
        for i in range(-GRID, GRID + 1):
            a = cell(i, j)
            if isinstance(a, str):
                continue
            for di, dj in ((1, 0), (0, 1)):
                if not (-GRID <= i + di <= GRID and -GRID <= j + dj <= GRID):
                    continue
                b = cell(i + di, j + dj)
                if isinstance(b, str) or abs(a - b) > 70:
                    continue
                what = _blocked(pawn, (tx + i * STEP, ty + j * STEP, a), (tx + (i + di) * STEP, ty + (j + dj) * STEP, b))
                if what:
                    walls.append(f"({i},{j})-({i + di},{j + dj}) {what}")
    lines.append(f"blocked between level neighbours ({len(walls)}): " + ("; ".join(walls[:80]) if walls else "none"))
    # actors near the marker
    near = []
    try:
        import unrealsdk

        for a in unrealsdk.find_all("Actor", exact=False):
            try:
                path = a._path_name()
                if "Default__" in path or ".TheWorld:" not in path:
                    continue
                q = game.location(a)
                if q is None or math.dist(q, target) > NEAR_ACTORS:
                    continue
                near.append((math.dist(q, target), f"{a.Class.Name} {a.Name} at ({(q[0] - tx) / 100:+.1f}, "
                                                    f"{(q[1] - ty) / 100:+.1f}) m, {(q[2] - tz) / 10:+.0f} dm"))
            except Exception:
                continue
    except Exception as e:  # noqa: BLE001
        near.append((0.0, f"(couldn't list actors: {e})"))
    near.sort()
    lines.append(f"actors within {NEAR_ACTORS / 100:.0f} m of the marker ({len(near)}):")
    lines += [f"  {t}" for _d, t in near[:60]]
    # learned trail points near it
    try:
        from .waygraph import graph

        pts = sorted((math.hypot(q[0] - tx, q[1] - ty), q) for q in graph.pos
                     if math.hypot(q[0] - tx, q[1] - ty) < GRID * STEP)
        lines.append(f"known path points within {GRID} m ({len(pts)}; body height, about 9 dm above the feet):")
        lines += [f"  ({(q[0] - tx) / 100:+.1f}, {(q[1] - ty) / 100:+.1f}) m, {(q[2] - tz) / 10:+.0f} dm" for _d, q in pts[:40]]
    except Exception:
        pass
    lines.append(f"(probe took {(time.perf_counter() - t0) * 1000:.0f} ms)")
    path = os.path.join(LOG_DIR, "marker_probe.txt")
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:
        return None
    return path


def maybe_probe(pawn: Any, key: str, name: str, target: tuple) -> None:
    """Probe a raised or lowered marker once, when you're close to it."""
    if key in _done or not game.FLOOR_SEEN:
        return
    loc = game.location(pawn)
    feet = game.feet_z(pawn)
    if loc is None or feet is None:
        return
    if math.hypot(loc[0] - target[0], loc[1] - target[1]) > PROBE_WITHIN:
        return
    rise = target[2] - feet
    if -150 <= rise <= 200:
        return
    _done.add(key)
    written = probe(pawn, name, target, why=f"{'above' if rise > 0 else 'below'} you by {abs(rise) / 100:.1f} m")
    if written:
        from . import trace

        trace.note(f"marker probe: wrote the surroundings of '{name}' to {written}")
