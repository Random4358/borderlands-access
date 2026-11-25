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



# ================================================================ round 19: always leading you into buildings
import math
import bl2_access.game as G
import bl2_access.navigation as NAV
import bl2_access.planner as P
from bl2_access import trace as T

notes = []
T.note = lambda text: notes.append(text)
G.TRACE_MODE = "fast"; G.FLOOR_SEEN = True
FLOOR = -90.0

class World:
    def __init__(s, walls=(), floor=None):
        s.walls, s.count = list(walls), 0
        s.floor = floor or (lambda x, y: FLOOR)
    def solid(s, x, y, z):
        if any(x0 <= x <= x1 and y0 <= y <= y1 and z <= z1 for x0, x1, y0, y1, z1 in s.walls):
            return True
        return z <= s.floor(x, y)
    def trace(s, a, b):
        s.count += 1
        n = max(2, int(math.dist(a, b) / 10))
        return not any(s.solid(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n, a[2] + (b[2] - a[2]) * i / n)
                       for i in range(n + 1))
class Pawn:
    def __init__(s, world, at):
        s.world = world; s.Location = NS(X=at[0], Y=at[1], Z=world.floor(at[0], at[1]) + 90)
        s.Velocity = NS(X=0.0, Y=0.0, Z=0.0); s.Acceleration = NS(X=0.0, Y=0.0, Z=0.0)
        s.CylinderComponent = NS(CollisionHeight=90)
    def FastTrace(s, end, start): return s.world.trace((start.X, start.Y, start.Z), (end.X, end.Y, end.Z))
class PC: pass

def walk(world, me, target, key, frames=3000, speed=30.0, arrive=150):
    """Follow the beacon like a player: walk toward whatever it points at. Fails if you'd walk
    through a wall. Returns (arrived, frames used, most traces used in one frame)."""
    r = NAV.Route(); now = 0.0; worst = 0
    for f in range(frames):
        now += 1 / 30
        here = (me.Location.X, me.Location.Y)
        eye = (here[0], here[1], me.Location.Z + 60)
        before = world.count
        p = r.next_point(PC(), eye, target, None, key, now, me)
        worst = max(worst, world.count - before)
        d = math.dist(here, p[:2]) or 1
        nx, ny = here[0] + (p[0] - here[0]) / d * speed, here[1] + (p[1] - here[1]) / d * speed
        feet = world.floor(nx, ny)
        cur = me.Location.Z - 90
        # a body is ~35 uu round: the way ahead must be clear that far beyond the step
        ex, ey = nx + (p[0] - here[0]) / d * 35, ny + (p[1] - here[1]) / d * 35
        blocked = (not world.trace((here[0], here[1], cur + 50), (ex, ey, max(cur, feet) + 50))) or feet > cur + 70
        me.Acceleration = NS(X=(p[0] - here[0]) / d * 800, Y=(p[1] - here[1]) / d * 800, Z=0)
        if blocked:
            me.Velocity = NS(X=0.0, Y=0.0, Z=0.0)
        else:
            me.Location = NS(X=nx, Y=ny, Z=feet + 90); me.Velocity = NS(X=speed * 30, Y=0.0, Z=0.0)
        if math.dist((me.Location.X, me.Location.Y), target[:2]) < arrive and abs(me.Location.Z - 90 - target[2]) < 200:
            return True, f + 1, worst, r
    return False, frames, worst, r

# --- a building 60 m away; its only door is on the far side; the target is inside
H = 400
building = [(5800, 5820, -800, 800, H),                       # west wall (facing you), solid
            (5800, 7000, -820, -800, H), (5800, 7000, 800, 820, H),
            (6980, 7000, -800, 300, H), (6980, 7000, 430, 800, H)]   # east wall, door at y 300..430
w = World(building)
target = (6200.0, 0.0, FLOOR)
said.clear(); notes.clear()
ok, frames, worst, r = walk(w, Pawn(w, (0.0, 0.0)), target, "Cabinet")
print(f"building: arrived={ok} in {frames} frames ({frames / 30:.0f} s), most traces in a frame: {worst}")
assert ok, (frames, notes[-6:])
# coarse far off, then fine close up (or, once you're much closer than the coarse search began, a fresh
# fine search from where you are)
assert (any("grid 1.8 m" in n for n in notes) or any("searching again from here" in n for n in notes)) \
    and any("grid 0.9 m" in n for n in notes), notes
assert frames < 1200, frames   # 56 s before the stale-search restart, 26 s with it
assert said and said[0][0].startswith(("Route found", "Heading toward it")), said
assert worst <= NAV.PLAN_BUDGET + 120, worst              # planner budget plus following/steering checks
print("into a building from far away OK")

# --- upstairs: stairs up to a mezzanine, target on it
def stairs(x, y):
    if 600 <= x < 1200 and -150 <= y <= 150:
        return FLOOR + (int((x - 600) / 50) + 1) * 25        # 12 steps of 25 cm
    if x >= 1200 and -400 <= y <= 400:
        return FLOOR + 300                                     # the upper floor
    return FLOOR
w = World([(1200, 2000, 150, 170, FLOOR + 290)], floor=stairs)   # the upper floor's edge isn't walkable from below except by the stairs
pl = P.GridPlanner(w.trace); pl.start((0.0, 0.0, FLOOR), (1600.0, 0.0, FLOOR + 300))
while pl.state == "running":
    pl.step(120)
print("stairs:", pl.state, "end height", round(pl.path[-1][2]))
assert pl.state == "done" and pl.path[-1][2] > FLOOR + 250
print("up the stairs OK")

# --- a search area that's too small grows until the way in is found
keep = NAV.PLAN_CELLS
NAV.PLAN_CELLS = 400
big = [(1000, 1020, -1500, 1500, H), (1000, 1800, -1520, -1500, H), (1000, 1800, 1500, 1520, H),
       (1780, 1800, -1500, 1300, H), (1780, 1800, 1420, 1500, H)]     # door at the far end, top corner
w = World(big)
notes.clear()
ok, frames, worst, r = walk(w, Pawn(w, (0.0, 0.0)), (1400.0, 0.0, FLOOR), "Locker", frames=6000)
NAV.PLAN_CELLS = keep
print(f"small search: arrived={ok} in {frames} frames; grew: {[n for n in notes if 'bigger area' in n][:2]}")
assert ok and any("bigger area" in n for n in notes)
print("search area grows OK")

# --- while a new route is worked out, you're still led along the old one (not straight at the wall)
w = World(building); me = Pawn(w, (5000.0, 0.0)); r = NAV.Route(); now = 0.0
for _ in range(900):
    now += 1 / 30; r.next_point(PC(), (5000.0, 0.0, 60.0), target, None, "Cabinet", now, me)
    if r.path and r.planner.state in ("done", "partial"):
        break
assert r.path and r.planner.state in ("done", "partial"), (r.planner.state, notes[-3:])
r.replan_at = 0.0
p = r.next_point(PC(), (5000.0, 0.0, 60.0), target, None, "Cabinet", now + 0.1, me)
assert r.planner.state == "running" and abs(p[1]) > 300, (r.planner.state, p)   # still the detour, not straight east
print("keeps the old route while re-planning OK")

# --- not getting anywhere for 8 s: "Recalculating"
said.clear()
r.watch = (now, 0.0)   # no closer than when the check started
r._watch_progress((5000.0, 0.0, FLOOR), now + 9)
assert said and said[-1][0] == "Recalculating" and r.replan_at == 0.0
print("ALL ROUND 19 TESTS OK")
