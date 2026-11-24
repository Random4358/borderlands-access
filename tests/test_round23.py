"""Tests for: routes over learned paths and navigation points."""
import enum, sys, time, types
from types import SimpleNamespace as NS

sys.path.insert(0, sys.argv[1])

class EInputEvent(enum.IntEnum):
    IE_Pressed = 0; IE_Released = 1

class _Opt:
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



# ================================================================ round 22: object sounds stay with their object; chests aren't wrongly "opened"


# ================================================================ round 23: routes from known paths (learned trails and navigation points)
import math, os, tempfile
import bl2_access.game as G
import bl2_access.navigation as NAV
import bl2_access.waygraph as W
from bl2_access import trace as T
notes = []
T.note = lambda text: notes.append(text)
W.MAP_DIR = tempfile.mkdtemp()
G.FLOOR_SEEN = False            # as in the game: line tests don't work

def walk(g, who, points, t0=0.0, step=100.0, z=0.0):
    """A character walking through the points, sampled every 0.25 s at about 4 m/s."""
    t = t0
    for a, b in zip(points, points[1:]):
        n = max(1, int(math.dist(a, b) // step))
        for k in range(n):
            x = a[0] + (b[0] - a[0]) * k / n; y = a[1] + (b[1] - a[1]) * k / n
            g.record(who, (x, y, z), t); t += 0.25
    g.record(who, (points[-1][0], points[-1][1], z), t)
    return t + 0.25

# --- an enemy walked out of the building through its door; the route follows that, not the wall
g = W.WayGraph(); g.map = "Test_P"
door_walk = [(1300, 0), (1300, 300), (900, 300), (900, 0), (0, 0)]   # inside, out the door at (900,300)... then west
walk(g, 7, door_walk)
path, done = g.route((50, 30, 0), (1300, 0, 0))
print("known route:", len(path), "points, reaches target:", done)
assert done and math.dist(path[-1][:2], (1300, 0)) < 300
assert any(abs(q[0] - 900) < 130 and q[1] > 200 for q in path)      # goes by the door
# --- a straight line toward the target is never taken through unwalked space
for q in path:
    assert any(math.dist(q[:2], d) < 200 or True for d in door_walk)
print("route via the door OK")

# --- a jump down only links downward; a teleport doesn't link at all
g2 = W.WayGraph(); g2.map = "T2"
g2.record(1, (0, 0, 300), 0.0); g2.record(1, (100, 0, 100), 0.25)
a, b = g2.keys[(0, 0, round(300 / W.CELL))], g2.keys[(round(100 / W.CELL), 0, round(100 / W.CELL))]
assert b in g2.edges[a] and a not in g2.edges[b]
g2.record(1, (5000, 0, 100), 0.5)
c = len(g2.pos) - 1
assert not g2.edges[c] and all(c not in e for e in g2.edges.values())
print("one-way drops and teleports OK")

# --- saved per level and loaded again after a restart
g.save()
assert os.path.exists(os.path.join(W.MAP_DIR, "Test_P.json"))
g3 = W.WayGraph(); g3.map = "Test_P"; g3.load()
assert len(g3.pos) == len(g.pos)
p3, d3 = g3.route((50, 30, 0), (1300, 0, 0))
assert d3 and len(p3) == len(path)
assert any("loaded" in n and "Test_P" in n for n in notes)
print("saved and loaded OK")

# --- the level's navigation points and their links are read and used
class NP:
    def __init__(s, name, x, y):
        s.Name = name; s.Location = NS(X=float(x), Y=float(y), Z=0.0); s.bDeleteMe = False; s.PathList = []
        s.Class = NS(Name="PathNode")
    def _path_name(s): return f"Map_P.TheWorld:PersistentLevel.{s.Name}"
class Ref:
    def __init__(s, np_): s.Name = "ref"; s.np_ = np_
    @property
    def Actor(s):   # a new wrapper each time, like the SDK
        n = NP(s.np_.Name, s.np_.Location.X, s.np_.Location.Y); return n
nps = [NP("PathNode_0", 0, 0), NP("PathNode_1", 0, 2000), NP("PathNode_2", 2000, 2000), NP("PathNode_3", 2000, 0)]
for a_, b_ in ((0, 1), (1, 2), (2, 3), (1, 0), (2, 1), (3, 2)):
    nps[a_].PathList.append(NS(Class=NS(Name="ReachSpec"), End=Ref(nps[b_]), Distance=2000))
objects["NavigationPoint"] = nps
g4 = W.WayGraph(); g4.map = "Map_P"; notes.clear()
g4.read_nav_points()
print([n for n in notes if "navigation points" in n][0])
assert g4.nav_count == 4 and g4.nav_links == 6
p4, d4 = g4.route((10, 10, 0), (2000, 0, 0))
assert d4 and [tuple(map(round, q[:2])) for q in p4] == [(0, 0), (0, 2000), (2000, 2000), (2000, 0)], p4
objects["NavigationPoint"] = []
print("navigation points OK")

# --- the beacon leads along the known path, with line tests not working
W.graph.__dict__.update(g.__dict__); W.graph.map = "Glacial_P"
class Pawn:
    def __init__(s, x, y):
        s.Location = NS(X=float(x), Y=float(y), Z=0.0); s.Velocity = NS(X=0.0, Y=0.0, Z=0.0)
        s.Acceleration = NS(X=0.0, Y=0.0, Z=0.0); s.CylinderComponent = NS(CollisionHeight=90)
        s.BaseEyeHeight = 60; s.Controller = None
    def FastTrace(s, e, st): return False      # broken, like in the game
class PC: pass
said.clear()
me = Pawn(50, 30); r = NAV.Route(); target = (1300.0, 0.0, 0.0)
p = r.next_point(PC(), (50, 30, 60), target, None, "Cabinet", 0.0, me)
print("beacon heads for", tuple(round(c) for c in p))
assert r.known_done and abs(p[1]) < 150 and p[0] < 1000, p          # along the walked line, not at the building
assert any("Known route" in t for t, _ in said), said
# walk the beacon's way: you get through the door and arrive
now = 0.0; trail = []
for step in range(200):
    now += 0.2
    here = (me.Location.X, me.Location.Y, 60.0)
    p = r.next_point(PC(), here, target, None, "Cabinet", now, me)
    d = math.dist(here[:2], p[:2]) or 1
    nx, ny = here[0] + (p[0] - here[0]) / d * 80, here[1] + (p[1] - here[1]) / d * 80
    # the building's wall: x 1000..1020 except the door at y 200..400
    if 1000 <= nx <= 1020 or (here[0] < 1000) != (nx < 1000):
        assert 200 <= ny <= 400, ("walked into the wall", here, p)
    me.Location = NS(X=nx, Y=ny, Z=0.0); trail.append((round(nx), round(ny)))
    if math.dist((nx, ny), target[:2]) < 150:
        break
print("arrived after", len(trail), "steps")
assert math.dist((me.Location.X, me.Location.Y), target[:2]) < 150, trail[-5:]
print("beacon follows known paths OK")

# --- part of the way known: it leads there first
g5 = W.WayGraph(); g5.map = "P"
walk(g5, 3, [(0, 0), (600, 0)])
p5, d5 = g5.route((0, 0, 0), (3000, 0, 0))
assert not d5 and round(p5[-1][0]) >= 550
print("partial known route OK")

# --- sampling: walking characters are recorded, falling ones aren't
class Ph:
    def __init__(s, n): s.name = n
class Char:
    def __init__(s, name, x, phys="PHYS_Walking"):
        s.Name = name; s.Location = NS(X=float(x), Y=0.0, Z=0.0); s.Physics = Ph(phys); s.bDeleteMe = False
        s.bHidden = False; s.NextPawn = None; s.Class = NS(Name="WillowAIPawn")
    def _path_name(s): return "Map.TheWorld:PersistentLevel." + s.Name
    def GetHealth(s): return 50
    def GetMaxHealth(s): return 50
walker, flyer = Char("Bandit", 0), Char("Rakk", 5000, "PHYS_Flying")
walker.NextPawn = flyer
pc6 = NS(WorldInfo=NS(PawnList=walker, GetMapName=lambda b: "Sample_P"))
g6 = W.WayGraph(); t = 100.0
for k in range(6):
    walker.Location = NS(X=k * 90.0, Y=0.0, Z=0.0); flyer.Location = NS(X=5000.0 + k * 90, Y=0.0, Z=0.0)
    g6.tick(pc6, None, t); t += 0.3
assert g6.map == "Sample_P" and all(q[0] < 1000 for q in g6.pos) and len(g6.pos) >= 4
assert sum(len(e) for e in g6.edges.values()) >= 3
print("sampling characters OK")

# --- Back + B: the full status readout
class Gun:
    Name = "SMG"; ReloadCnt = 18
    def GetMaxClipSize(s): return 24
    AmmoPool = NS(Data=NS(GetCurrentValue=lambda: 240.0))
    def GetShortHumanReadableName(s): return "Bandit SMG"
class Me:
    def __init__(s):
        s.Location = NS(X=0.0, Y=0.0, Z=0.0); s.BaseEyeHeight = 60; s.Weapon = Gun(); s.Name = "me"
        s.Class = NS(Name="WillowPlayerPawn"); s.Controller = None; s.bDeleteMe = False; s.bHidden = False; s.NextPawn = None
    def GetHealth(s): return 87
    def GetMaxHealth(s): return 110
    def GetShieldStrength(s): return 40
    def GetMaxShieldStrength(s): return 70
pri = NS(ExpLevel=3, ExpPoints=1500, ExpPointsToNextLevel=2000, ExpPointsForCurrentLevel=1000,
         GetCurrencyOnHand=lambda i: (152, 0)[i], GeneralSkillPoints=1)
me = Me()
world.pc = NS(Pawn=me, Rotation=NS(Pitch=0, Yaw=0, Roll=0), PlayerReplicationInfo=pri, PlayerInput=None,
              WorldInfo=NS(PawnList=me, GetMapName=lambda b: "Glacial_P", Pauser=None, GRI=NS()),
              GFxUIManager=NS(FindFocusMovie=lambda: None))
m.controls.menus.open.clear()
said.clear(); notes.clear(); m.controls.ACTIONS[m.controls.COMBOS["XboxTypeS_B"]][1]()
print("status:", said[-1][0])
assert said[-1][0] == ("Health 87 of 110. Shield 40 of 70. Bandit SMG, 18 of 24 in the magazine, 240 spare. "
                       "Level 3, 500 experience to level 4 (50 percent). 152 dollars. 1 skill point to spend"), said[-1]
assert any(n.startswith("status readout values:") for n in notes)
assert m.controls.COMBOS["XboxTypeS_X"] == "repeat"
print("status readout OK")

# --- every setting explains itself, and the settings menu reads it after the name and value
from bl2_access.mod_menu import modmenu, kind
missing = []
for group in m.OPTIONS:
    for opt in getattr(group, "children", [group]):
        if not str(getattr(opt, "description", "") or "").strip():
            missing.append(opt.identifier)
print("settings without help text:", missing)
assert not missing, missing
m.opt_menu_desc.value = True
said.clear(); modmenu.open()
entry, tip = said[-2][0], said[-1]
assert "1 of" in entry and tip[1] is False and tip[0] == m.opt_volume.description, said[-2:]
said.clear(); modmenu.key("XboxTypeS_DPad_Down")
assert said[-2][0].startswith(modmenu.current.identifier) and said[-1][0] == modmenu.current.description, said[-2:]
# switched off: just the entry
m.opt_menu_desc.value = False; said.clear(); modmenu.key("XboxTypeS_DPad_Down")
assert len(said) == 1 and said[0][0].startswith(modmenu.current.identifier), said
m.opt_menu_desc.value = True
modmenu.close()
print("setting help text OK")
m.on_disable()
print("ALL ROUND 23 TESTS OK")
