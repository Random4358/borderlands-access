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

# --- 5b. someone has stood at the marker's height a few metres away (up a ramp): the known route
# leads there instead of to the spot right underneath it (the Find new gear marker)
g = W.WayGraph(); g.map = "Glacial_P"
t = 0.0
for k in range(12):                                          # along the ground, under the marker at x 600
    g.record(1, (k * 100.0, 0.0, 90.0), t); t += 0.25
for k in range(1, 10):                                       # then up a ramp to the side, to the marker's level
    g.record(1, (1100.0 - k * 60.0, k * 60.0, 90.0 + k * 34.0), t); t += 0.25
spot = g.height_spot((600.0, 0.0, 400.0))
assert spot is not None and 200 <= spot[2] and math.dist(spot[:2], (600.0, 0.0)) < 1500, spot
W.graph.__dict__.update(g.__dict__)
G_ = NAV.game
saved_floor = G_.FLOOR_SEEN; G_.FLOOR_SEEN = False
class Pw:
    def __init__(s, x, y, z): s.Location = NS(X=x, Y=y, Z=z); s.Velocity = NS(X=0.0, Y=0.0, Z=0.0); s.Acceleration = NS(X=0.0, Y=0.0, Z=0.0); s.CylinderComponent = NS(CollisionHeight=90); s.BaseEyeHeight = 60; s.Controller = None
r = NAV.Route(); said.clear(); notes.clear()
p = r.next_point(NS(), (0.0, 0.0, 150.0), (600.0, 0.0, 400.0), None, "Gear", 0.0, Pw(0.0, 0.0, 90.0))
print("raised marker, known route:", [n for n in notes if "height" in n])
assert r.known_done and r.known_spot is not None, (r.known_done, r.known_spot)
assert any("Known route up to its height" in s for s, _i in said), said
help_text = r.height_help((600.0, 0.0, 400.0))
assert "Learned paths reach its height" in help_text and "beacon leads there" in help_text, help_text
# --- 5c. no known way: the mod says it's searching, and later what it found
r = NAV.Route(); said.clear()
assert "can't search" in r.height_help((600.0, 0.0, 400.0)) and r.climb_wanted
G_.FLOOR_SEEN = True
r.climb_wanted = False
assert r.height_help((600.0, 0.0, 400.0)).startswith("Searching for a way up") and r.climb_wanted
pl = NS(state="done", path=[(0.0, 0.0, 0.0), (300.0, 0.0, 0.0), (390.0, 0.0, 100.0), (600.0, 0.0, 100.0)],
        moves=["walk", "walk", "jump", "walk"], cell=90.0, cells_searched=50, best_gap=0.0, rejects={})
r.limit, r.last_gap = NAV.PLAN_CELLS, None
r._take_plan(pl, (0.0, 0.0, 0.0), 1.0)
print("way up:", said[-1][0])
assert said[-1][0].startswith("Way up found. 6 metres, with 1 jump up") and not r.climb_wanted, said
assert r.height_help((600.0, 0.0, 400.0)).startswith("The beacon leads up: 6 metres")
assert r.height_help((600.0, 0.0, -400.0), up=False).startswith("The beacon leads down")
r.climb_wanted = True
r._take_plan(NS(state="failed", path=[], moves=[], cell=90.0, cells_searched=900, best_gap=0.0,
                rejects={"no floor": 1, "knee": 2, "chest": 3}), (0.0, 0.0, 0.0), 2.0)
assert said[-1][0].startswith("No way up found from here"), said[-1]
G_.FLOOR_SEEN = saved_floor
print("raised marker guidance OK")

# --- 5d. a search begun far away is started again once you're much closer
class Busy:
    def __init__(s): s.state = "running"; s.cell = 180.0; s.starts = []; s.runs = 0
    def start(s, *a, **k): s.starts.append(a); s.state = "running"
    def step(s, *a, **k): return s.state
r = NAV.Route(); G_.FLOOR_SEEN = True; notes.clear()
r.planner = Busy(); r.path, r.path_kind, r.limit, r.last_gap = [], "", NAV.PLAN_CELLS, None
r.runs_seen, r.watch, r.announced = 0, None, False
r.search_from = (0.0, 0.0, 7000.0)                           # begun 70 m from the target
orig_loc, orig_feet, orig_ground = G_.location, G_.feet_z, G_.ground_z
G_.location = lambda a: (a.Location.X, a.Location.Y, a.Location.Z)
G_.feet_z = lambda a: a.Location.Z - 90
G_.ground_z = lambda a, x, y, z: z - 90
r._planned(Pw(3000.0, 0.0, 90.0), (7000.0, 0.0, 300.0), 5.0)     # 40 m away now: keep going
assert not r.planner.starts
r._planned(Pw(6700.0, 0.0, 90.0), (7000.0, 0.0, 300.0), 6.0)     # 3 m away: search again from here
assert len(r.planner.starts) == 1 and any("searching again from here" in n for n in notes), notes
assert abs(r.search_from[2] - 300.0) < 1
G_.location, G_.feet_z, G_.ground_z, G_.FLOOR_SEEN = orig_loc, orig_feet, orig_ground, saved_floor
print("stale search restarted OK")

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

# --- starter paths that come with the mod: a new install uses them; what's learned here merges in
import os, tempfile, json, time as _time
real_starter, real_maps = W.STARTER_DIR, W.MAP_DIR
W.STARTER_DIR, W.MAP_DIR = tempfile.mkdtemp(), tempfile.mkdtemp()
json.dump({"version": 1, "cell": 120.0, "nodes": [[0, 0, 90, 5], [120, 0, 90, 5], [240, 0, 90, 5]],
           "edges": [[0, 1], [1, 0], [1, 2], [2, 1]]}, open(os.path.join(W.STARTER_DIR, "Lvl_P.json"), "w"))
g = W.WayGraph(); g.map = "Lvl_P"; notes.clear(); g.load()
assert len(g.pos) == 3 and any("starter paths" in n and "nothing learned here yet" in n for n in notes), notes
# learned here: one point the same as the starter's, one new beyond it
json.dump({"version": 1, "cell": 120.0, "nodes": [[240, 0, 90, 2], [360, 0, 90, 1]], "edges": [[0, 1], [1, 0]]},
          open(os.path.join(W.MAP_DIR, "Lvl_P.json"), "w"))
g = W.WayGraph(); g.map = "Lvl_P"; g.load()
assert len(g.pos) == 4, len(g.pos)                      # the shared point isn't doubled
path, done = g.route((0.0, 0.0, 90.0), (360.0, 0.0, 90.0))
a_ = g.keys[(2, 0, 1)]; b_ = g.keys[(3, 0, 1)]
assert b_ in g.edges[a_] and a_ in g.edges[b_]           # starter and learned paths join up
g.save(); saved = json.load(open(os.path.join(W.MAP_DIR, "Lvl_P.json")))
assert len(saved["nodes"]) == 4                         # and from now on they're kept together
W.STARTER_DIR, W.MAP_DIR = real_starter, real_maps
print("starter paths OK")

# --- the bundled Windshear Waste paths load and give real routes quickly
g = W.WayGraph(); g.map = "Glacial_P"
W.MAP_DIR = tempfile.mkdtemp()                          # as on a new install: nothing learned yet
g.load(); W.MAP_DIR = real_maps
print("bundled Glacial_P:", len(g.pos), "points")
assert len(g.pos) > 1000
# the largest connected group, and the point in it furthest from its first point
start = max(range(len(g.pos)), key=lambda i: len(g.edges[i]))
group, todo = {start}, [start]
while todo:
    u = todo.pop()
    for v in g.edges[u]:
        if v not in group: group.add(v); todo.append(v)
far = max(group, key=lambda i: math.dist(g.pos[start][:2], g.pos[i][:2]))
t0 = _time.perf_counter(); path, done = g.route(tuple(g.pos[start][:3]), tuple(g.pos[far][:3])); took = _time.perf_counter() - t0
print(f"route across it: {len(path)} points, reached={done}, {took * 1000:.0f} ms, "
      f"{math.dist(g.pos[start][:2], g.pos[far][:2]) / 100:.0f} m apart, group of {len(group)}")
assert done and len(path) > 20 and took < 0.5
print("bundled paths OK")

# --- screens without a reader of their own (licence, privacy policy): their text is read, and how to leave
import bl2_access.status_reader as SRm
from bl2_access.screen_text import screen_text, is_unknown
assert is_unknown("WillowGFxMovieLegal") and is_unknown("OnlineMessageGFxMovie")
assert not is_unknown("WillowHUDGFxMovie") and not is_unknown("FrontendGFxMovie")
param = NS(Class=NS(Name="StrProperty"), Name="BodyText", PropertyFlags=0x80, Next=None)
fn = NS(Name="SetBodyText", Children=param)
orig_fns = SRm._functions
SRm._functions = lambda cls: iter([(f"WillowGame.{cls}:SetBodyText", "SetBodyText", fn)])
legal = NS(Name="WillowGFxMovieLegal_0", Class=NS(Name="WillowGFxMovieLegal"), _path_name=lambda: "legal")
said.clear(); notes.clear()
m.controls.menus.opened(legal)
SRm._functions = orig_fns
print("legal screen:", said[-1][0])
assert said[-1][0].startswith("Legal screen. Press A or Enter to accept or continue, B or Escape to go back"), said
assert any(n.startswith("screen text: WillowGFxMovieLegal: reading text from 1 functions: SetBodyText(BodyText)") for n in notes), notes
cb = hooked[("WillowGame.WillowGFxMovieLegal:SetBodyText", Type.PRE)]
cb(legal, NS(BodyText="<p>By playing you agree to the <b>Terms of Service</b>.</p>"), None, None)
cb(legal, NS(BodyText="By playing you agree to the Terms of Service."), None, None)   # same text again: once
screen_text.last_add -= 1; screen_text.tick()
assert said[-1][0] == "By playing you agree to the Terms of Service", said[-1]
assert sum("Terms of Service" in s for s, _i in said) == 1
print("unknown screens OK")
m.on_disable()
print("ALL ROUND 25 TESTS OK")
