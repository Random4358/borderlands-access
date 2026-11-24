"""Tests for: character descriptions, silence in menus, scanner categories."""
import enum, sys, time, types
from types import SimpleNamespace as NS

sys.path.insert(0, sys.argv[1])

class EInputEvent(enum.IntEnum):
    IE_Pressed = 0; IE_Released = 1

class _Opt:
    __hash__ = None   # like the real mod manager's options (dataclasses): can't be dict keys
    def __init__(self, ident, value=None, *a, description="", display_name=None, **k):
        self.identifier = ident; self.display_name = display_name or ident; self.description = description
        self.value = value; self.default_value = value; self.is_hidden = False
class BoolOption(_Opt): pass
class SliderOption(_Opt):
    def __init__(self, ident, value, min_value=0, max_value=100, step=1, is_integer=True, **k):
        super().__init__(ident, value, **k); self.min_value = min_value; self.max_value = max_value
        self.step = step; self.is_integer = is_integer
class DropdownOption(_Opt):
    def __init__(self, ident, value, choices=(), **k):
        super().__init__(ident, value, **k); self.choices = list(choices)
class ButtonOption(_Opt):
    def __init__(self, ident, on_press=None, **k):
        super().__init__(ident, None, **k); self.on_press = on_press
mb = types.ModuleType("mods_base")
for c in (BoolOption, DropdownOption, SliderOption, ButtonOption):
    setattr(mb, c.__name__, c)
mb.GroupedOption = lambda ident, children, **k: NS(children=children, display_name=ident, identifier=ident, is_hidden=False)
mb.EInputEvent = EInputEvent
mb.keybind = lambda ident, key=None, callback=None, **k: NS(identifier=ident, key=key, callback=callback)
saves = []
mb.build_mod = lambda **k: NS(save_settings=lambda: saves.append(1), settings_file=None)
world = NS(pc=None)
mb.get_pc = lambda: world.pc
sys.modules["mods_base"] = mb

objects = {}  # class name -> list of objects for find_all
us = types.ModuleType("unrealsdk")
us.make_struct = lambda name, **f: NS(**f)
us.find_all = lambda cls, exact=True: list(objects.get(cls, []))
FAKE = {}  # class name -> [(function, [(param, param class)])]
def _chain(items):
    first = None
    for it in reversed(items):
        it.Next = first; first = it
    return first
def find_class(name):
    owner = NS(Name=name, Outer=NS(Name="WillowGame"))
    funcs = []
    for fn, params in FAKE.get(name, []):
        ps = [NS(Class=NS(Name="ObjectProperty"), Name=p, PropertyFlags=0x80, PropertyClass=NS(Name=c)) for p, c in params]
        funcs.append(NS(Class=NS(Name="Function"), Name=fn, Children=_chain(ps)))
    owner.Children = _chain(funcs)
    return NS(_find=lambda fn: NS(Outer=owner), _superfields=lambda: [owner])
us.find_class = find_class
hooked = {}
hk = types.ModuleType("unrealsdk.hooks")
class Type(enum.Enum): PRE = 0; POST = 1
hk.Type = Type; hk.Block = object()
hk.add_hook = lambda name, kind, ident, cb: hooked.__setitem__((name, kind), cb)
hk.remove_hook = lambda name, kind, ident: hooked.pop((name, kind), None)
us.hooks = hk
cmds = types.ModuleType("unrealsdk.commands")
cmds.has_command = lambda n: False; cmds.add_command = lambda n, cb: True; cmds.remove_command = lambda n: True
us.commands = cmds
sys.modules.update({"unrealsdk": us, "unrealsdk.hooks": hk, "unrealsdk.commands": cmds})

FAKE["StatusMenuExGFxMovie"] = [("HandleInputKey", []), ("HandleMapInputKey", []), ("HandleSkillsInputKey", []),
                                 ("HandleInventoryInputKey", []), ("HandleKeyDefaults", [])]
FAKE["InventoryCardGFx"] = [("SetItemCardEx", [("WPC", "WillowPlayerController"), ("InventoryItem", "WillowInventory"),
                                                ("ComparisonItem", "WillowInventory")]),
                             ("SetFocusItem", [("Item", "WillowInventory")]),
                             ("SetDef", [("Def", "WillowInventoryDefinition")])]
FAKE["StatusMenuInventoryPanelGFxObject"] = [("OnHighlight", [("Thing", "WillowInventory")])]
import bl2_access as m
from bl2_access.menu_reader import reader
from bl2_access import features as F
said = []
m.speaker.say = lambda t, interrupt=True: said.append((t, interrupt))
played = []
m.audio_engine.play = lambda group, data: played.append(group)
m.on_enable()

def call(cls, fn, obj, kind=Type.PRE, **args):
    a = NS(**args); props = [NS(Name=k) for k in args]
    a._type = NS(_properties=lambda: props)
    hooked[(f"WillowGame.{cls}:{fn}", kind)](obj, a, None, None)



# ================================================================ round 18: the route planner (round walls, through doorways)
import math
import bl2_access.game as G
from bl2_access import navigation as NAV
from bl2_access.planner import GridPlanner, follow
from bl2_access import trace as T

notes = []
T.note = lambda text: notes.append(text)
G.TRACE_MODE = "fast"; G.FLOOR_SEEN = True
FLOOR = -90.0

class World:
    """Flat floor at z=-90, solid walls (boxes, full height), and pits with no floor."""
    def __init__(s, walls=(), pits=()):
        s.walls, s.pits, s.count = list(walls), list(pits), 0
    def solid(s, x, y, z):
        if any(x0 <= x <= x1 and y0 <= y <= y1 for x0, x1, y0, y1 in s.walls):
            return True
        if any(x0 <= x <= x1 and y0 <= y <= y1 for x0, x1, y0, y1 in s.pits):
            return z <= FLOOR - 2000
        return z <= FLOOR
    def trace(s, a, b):
        s.count += 1
        n = max(2, int(math.dist(a, b) / 10))
        for i in range(n + 1):
            t = i / n
            if s.solid(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t):
                return False
        return True

def plan(world, start, goal, budget=120, limit=400):
    pl = GridPlanner(world.trace); pl.start(start, goal); steps = 0
    while pl.state == "running" and steps < limit:
        pl.step(budget); steps += 1
    return pl, steps

# --- a room you can only enter through a doorway on its west side, near its north corner
room = [(1000, 1020, -400, 150), (1000, 1020, 280, 400),      # west wall with a gap (y 150..280)
        (1000, 1600, -420, -400), (1000, 1600, 400, 420), (1580, 1600, -420, 420)]
w = World(room)
target = (1300.0, 0.0, -30.0)
pl, steps = plan(w, (0.0, 0.0, FLOOR), target)
print(f"room: {pl.state}, {len(pl.path)} points, {pl.cells_searched} searched, {w.count} traces, {steps} frames")
assert pl.state == "done", pl.state
through = [p for p in pl.path if 990 <= p[0] <= 1030]
assert through and all(150 < p[1] < 280 for p in through), through          # goes through the doorway
assert steps <= 60, steps                                                     # found within ~2 s at 30 fps
assert all(abs(p[2] - FLOOR) < 25 for p in pl.path)                           # floor heights estimated
# walking it: always heading for the furthest point you can see; never through a wall
here = (0.0, 0.0, FLOOR)
for _ in range(200):
    nxt = follow(pl.path, here, lambda q: w.trace((here[0], here[1], here[2] + 50), (q[0], q[1], q[2] + 50)))
    if math.dist(here[:2], pl.path[-1][:2]) < 60:
        break
    d = math.dist(here[:2], nxt[:2]) or 1
    step_to = (here[0] + (nxt[0] - here[0]) / d * 40, here[1] + (nxt[1] - here[1]) / d * 40, FLOOR)
    assert w.trace((here[0], here[1], -40), (step_to[0], step_to[1], -40)), ("walked into a wall", here, nxt)
    here = step_to
assert math.dist(here[:2], target[:2]) < 150, here
print("through the doorway OK")

# --- a drop in the way: the route goes round it, not over it
w = World(pits=[(300, 600, -800, 500)])
pl, _ = plan(w, (0.0, 0.0, FLOOR), (900.0, 0.0, FLOOR))
assert pl.state == "done" and not any(300 <= p[0] <= 600 and -800 <= p[1] <= 500 for p in pl.path), pl.path
assert any(p[1] > 500 for p in pl.path)                                        # around the north end
print("round the drop OK")

# --- a gentle slope up: still walkable, heights follow it
class Slope(World):
    def solid(s, x, y, z):
        return z <= FLOOR + max(0.0, x - 200) * 0.25   # rises 25 cm per metre after x=200
w = Slope()
pl, _ = plan(w, (0.0, 0.0, FLOOR), (900.0, 0.0, FLOOR + 175))
assert pl.state == "done" and pl.path[-1][2] > FLOOR + 120, pl.path[-1]
print("up a slope OK")

# --- a sealed room: no way in, but you get as close as possible and it says so
sealed = [(1000, 1020, -400, 400), (1000, 1600, -420, -400), (1000, 1600, 400, 420), (1580, 1600, -420, 420)]
w = World(sealed)
import bl2_access.planner as P
P.MAX_CELLS, keep = 500, P.MAX_CELLS
pl, steps = plan(w, (0.0, 0.0, FLOOR), (1300.0, 0.0, FLOOR), limit=2000)
P.MAX_CELLS = keep
assert pl.state == "partial" and pl.path[-1][0] < 1000 and pl.path[-1][0] > 850, (pl.state, pl.path[-1])
print("sealed room: partial OK")

# --- in the beacon's route: points toward the doorway, not at the wall between
class Pawn:
    def __init__(s, world):
        s.world = world; s.Location = NS(X=0.0, Y=0.0, Z=0.0); s.Velocity = NS(X=0.0, Y=0.0, Z=0.0)
        s.Acceleration = NS(X=0.0, Y=0.0, Z=0.0); s.CylinderComponent = NS(CollisionHeight=90)
    def FastTrace(s, end, start): return s.world.trace((start.X, start.Y, start.Z), (end.X, end.Y, end.Z))
w = World(room); me = Pawn(w)
class PC: pass
r = NAV.Route(); now = 0.0
me.Location = NS(X=700.0, Y=-200.0, Z=0.0)                    # just outside, the wall straight ahead of the target
for _ in range(60):
    now += 1 / 30
    p = r.next_point(PC(), (700.0, -200.0, 60.0), target, None, "Cabinet", now, me)
print("beacon heads for:", tuple(round(c) for c in p), "| planner:", r.planner.state)
assert r.planner.state == "done"
assert p[1] > 100, p                                          # toward the doorway (north), not east into the wall
assert any("route planner: path to the target" in n for n in notes) and any("route to 'Cabinet'" in n for n in notes)
print("beacon follows the planned route OK")

# --- "Blocked": looks all the way round, says where the way through is
assert G.openings(Pawn(World([(60, 80, -2000, 2000)]))) and all(
    abs(G.wrap_angle(a)) > math.radians(60) for a in G.openings(Pawn(World([(60, 80, -2000, 2000)]))))
print("ALL ROUND 18 TESTS OK")
