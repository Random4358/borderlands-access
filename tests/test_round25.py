"""Tests for: reaching objectives above or below you."""
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





# ================================================================ round 25: objectives above or below you: climbing, ramps, drops
import math
from bl2_access import planner as P
from bl2_access import navigation as NAV
from bl2_access import waygraph as W
from bl2_access import trace as T
notes = []
T.note = lambda text: notes.append(text)

def world(floor):
    def solid(x, y, z): return z <= floor(x, y)
    def trace(a, b):
        n = max(2, int(math.dist(a, b) / 8))
        return not any(solid(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n, a[2] + (b[2] - a[2]) * i / n)
                       for i in range(n + 1))
    return trace

def plan(trace, start, goal, cells=3000):
    pl = P.GridPlanner(trace)
    pl.start(start, goal, cell=90.0, max_cells=cells)
    for _ in range(20000):
        if pl.step(400) != "running":
            break
    return pl

def on_platform(x, y): return 400 <= x <= 800 and -200 <= y <= 200

# --- 1. a crate-height ledge (1 m) with the marker floating above it: jump up onto it
low = world(lambda x, y: 100.0 if on_platform(x, y) else 0.0)
pl = plan(low, (0.0, 0.0, 0.0), (600.0, 0.0, 250.0))
print("ledge:", pl.state, "moves", [m for m in pl.moves if m != "walk"], "end", tuple(round(c) for c in pl.path[-1]))
assert pl.state == "done" and "jump" in pl.moves and abs(pl.path[-1][2] - 100) < 15, (pl.state, pl.path[-3:])

# --- 2. a 2.5 m platform, too high to jump, with a ramp round the side: the route takes the ramp
def ramp_floor(x, y):
    if on_platform(x, y):
        return 250.0
    if 400 <= x <= 800 and -700 <= y < -200:
        return 250.0 * (y + 700) / 500        # rises from the ground at y -700 to the top at y -200
    return 0.0
ramp = world(ramp_floor)
pl = plan(ramp, (0.0, 0.0, 0.0), (600.0, 0.0, 400.0))
print("ramp:", pl.state, "moves", [m for m in pl.moves if m != "walk"], "lowest y on the way", round(min(p[1] for p in pl.path)))
assert pl.state == "done" and abs(pl.path[-1][2] - 250) < 15
assert min(p[1] for p in pl.path) < -250, "went round by the ramp"
assert "jump" not in pl.moves

# --- 3. the same platform with no way up: never "reached" from underneath
cliff = world(lambda x, y: 250.0 if on_platform(x, y) else 0.0)
pl = plan(cliff, (0.0, 0.0, 0.0), (600.0, 0.0, 400.0), cells=1500)
print("no way up:", pl.state)
assert pl.state != "done", pl.path[-2:]

# --- 4. a target below: drop off the edge
pl = plan(cliff, (600.0, 0.0, 250.0), (1300.0, 0.0, 100.0))
print("drop:", pl.state, [m for m in pl.moves if m != "walk"])
assert pl.state == "done" and "drop" in pl.moves and abs(pl.path[-1][2]) < 15

# --- 5. known paths that only ever went underneath a raised marker don't count as reaching it
g = W.WayGraph(); g.map = "T"
for k in range(12):
    g.record(1, (k * 100.0, 0.0, 90.0), k * 0.25)          # walked along the ground (body ~90 up)
path, done = g.route((0.0, 0.0, 90.0), (600.0, 0.0, 400.0))   # marker 4 m up
assert not done, path[-1]
path, done = g.route((0.0, 0.0, 90.0), (600.0, 0.0, 150.0))   # marker at about head height: there
assert done
print("known paths and height OK")

# --- 6. on the route, the spot where you need to jump is announced once
r = NAV.Route()
r.path = [(0.0, 0.0, 0.0), (90.0, 0.0, 0.0), (180.0, 0.0, 100.0), (270.0, 0.0, 100.0)]
r.path_moves = ["walk", "walk", "jump", "walk"]
said.clear()
r._climb_cue((-100.0, 0.0, 0.0))
assert not said                                              # not there yet
r._climb_cue((85.0, 0.0, 0.0))
assert said and said[-1][0] == "Jump up here", said
r._climb_cue((88.0, 0.0, 0.0)); assert len(said) == 1        # once
r.path_moves = ["walk", "walk", "drop", "walk"]; r.climb_told = set()
r._climb_cue((85.0, 0.0, 0.0)); assert said[-1][0] == "Drop down here"
print("climb cues OK")
m.on_disable()
print("ALL ROUND 25 TESTS OK")
