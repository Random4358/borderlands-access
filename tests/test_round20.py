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



# ================================================================ round 20: hills, wrong height estimates, and why a plan failed
import math
import bl2_access.game as G
import bl2_access.navigation as NAV
import bl2_access.planner as P
from bl2_access import trace as T

notes = []
T.note = lambda text: notes.append(text)
G.TRACE_MODE = "fast"; G.FLOOR_SEEN = True

class World:
    def __init__(s, ground, walls=()):
        s.ground, s.walls, s.count = ground, list(walls), 0
    def solid(s, x, y, z):
        if any(x0 <= x <= x1 and y0 <= y <= y1 and z <= z1 for x0, x1, y0, y1, z1 in s.walls):
            return True
        return z <= s.ground(x, y)
    def trace(s, a, b):
        s.count += 1
        n = max(2, int(math.dist(a, b) / 10))
        return not any(s.solid(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n, a[2] + (b[2] - a[2]) * i / n)
                       for i in range(n + 1))
class Pawn:
    """`centre` is how high the body's Location sits above the ground (the game's real value
    may differ from the 90 the mod assumes)."""
    def __init__(s, world, at, centre=90.0):
        s.world, s.centre = world, centre
        s.Location = NS(X=at[0], Y=at[1], Z=world.ground(at[0], at[1]) + centre)
        s.Velocity = NS(X=0.0, Y=0.0, Z=0.0); s.Acceleration = NS(X=0.0, Y=0.0, Z=0.0)
        s.CylinderComponent = NS(CollisionHeight=90)
    def FastTrace(s, end, start): return s.world.trace((start.X, start.Y, start.Z), (end.X, end.Y, end.Z))
class PC: pass

def walk(world, me, target, frames=4000, speed=30.0):
    r = NAV.Route(); now = 0.0
    for f in range(frames):
        now += 1 / 30
        here = (me.Location.X, me.Location.Y)
        p = r.next_point(PC(), (here[0], here[1], me.Location.Z + 60), target, None, "Cabinet", now, me)
        d = math.dist(here, p[:2]) or 1
        nx, ny = here[0] + (p[0] - here[0]) / d * speed, here[1] + (p[1] - here[1]) / d * speed
        ex, ey = nx + (p[0] - here[0]) / d * 35, ny + (p[1] - here[1]) / d * 35
        g0, g1 = world.ground(*here), world.ground(nx, ny)
        blocked = not world.trace((here[0], here[1], g0 + 50), (ex, ey, world.ground(ex, ey) + 50)) or g1 > g0 + 70
        me.Acceleration = NS(X=(p[0] - here[0]) / d * 800, Y=(p[1] - here[1]) / d * 800, Z=0)
        if blocked:
            me.Velocity = NS(X=0.0, Y=0.0, Z=0.0)
        else:
            me.Location = NS(X=nx, Y=ny, Z=g1 + me.centre); me.Velocity = NS(X=900.0, Y=0.0, Z=0.0)
        if math.dist((me.Location.X, me.Location.Y), target[:2]) < 150:
            return True, f + 1, r
    return False, frames, r

# --- a 27 degree hillside, the target 50 m away up it, behind a wall with a gap
hill = lambda x, y: -90.0 + 0.5 * max(0.0, x)          # rises 50 cm per metre
wall = [(3000, 3020, -2000, 600, 5000), (3000, 3020, 800, 2000, 5000)]   # gap at y 600..800
w = World(hill, wall)
target = (5000.0, 0.0, hill(5000, 0))
notes.clear()
old_up, old_down = P.STEP_UP, P.DROP
ok, frames, r = walk(w, Pawn(w, (0.0, 0.0)), target)
print(f"hillside: arrived={ok} in {frames} frames | {[n for n in notes if 'planner' in n][:2]}")
assert ok and not any("no walkable way" in n for n in notes)
assert any("grid 1.8 m" in n for n in notes)            # the far-away coarse grid works on the slope
print("coarse planning on a slope OK")

# --- the body sits higher or lower than the mod assumes: the measured ground fixes it
for centre in (40.0, 150.0):
    w = World(lambda x, y: -90.0, [(1000, 1020, -1000, 300, 2000)])
    notes.clear()
    ok, frames, r = walk(w, Pawn(w, (0.0, 0.0), centre=centre), (2000.0, 0.0, -90.0))
    print(f"body centre {centre}: arrived={ok} in {frames} frames")
    assert ok and not any("no walkable way" in n for n in notes), notes
print("measured ground OK")

# --- when it does fail, the log says why
pillar = lambda x, y: -90.0 if math.hypot(x, y) < 60 else -5000.0      # standing on a pillar, a drop all round
w = World(pillar)
notes.clear()
r = NAV.Route(); me = Pawn(w, (0.0, 0.0)); now = 0.0
for _ in range(30):
    now += 1 / 30; r.next_point(PC(), (0.0, 0.0, 60.0), (2000.0, 0.0, -90.0), None, "x", now, me)
fail = [n for n in notes if "no walkable way" in n]
print("failure note:", fail[:1])
assert fail and "no floor 8" in fail[0] and "measured ground -90" in fail[0], fail
print("failure reasons logged OK")

# --- the same place under two names keeps its route
f = m.feats
from bl2_access.features import POI
me = Pawn(World(lambda x, y: -90.0), (0.0, 0.0))
world.pc = NS(Pawn=me, Rotation=NS(Pitch=0, Yaw=0, Roll=0), PlayerInput=None, SetRotation=lambda r: None,
              WorldInfo=NS(PawnList=me, GetMapName=lambda b: "Glacial_P", Pauser=None, GRI=NS()),
              GFxUIManager=NS(FindFocusMovie=lambda: None), LineOfSightTo=lambda p: True)
me.Name = "me"; me.Class = NS(Name="WillowPlayerPawn"); me.BaseEyeHeight = 60; me.NextPawn = None
me.bDeleteMe = False; me.bHidden = False; me.Controller = None; me.Weapon = None
me.GetHealth = lambda: 100; me.GetMaxHealth = lambda: 100; me.IsEnemy = lambda o: False
for o in ("opt_radar", "opt_npc_sounds", "opt_npc_talk", "opt_walls", "opt_ledges", "opt_jump", "opt_low_health",
          "opt_targeting", "opt_loot_sounds", "opt_container_sounds", "opt_interactive_sounds", "opt_quest_item_sounds",
          "opt_interact"):
    getattr(m, o).value = False
objects.clear(); m.controls.menus.open.clear()
def tick():
    m.hooks._last_tick = 0; m.hooks.on_tick(None, None, None, None)
tick()
f.pois = [POI("My First Gun", None, "Quest objectives", pos=(3000.0, 0.0, -90.0)),
          POI("Open cabinet", None, "Quest objectives", pos=(3010.0, 5.0, -90.0))]
f.category = "Quest objectives"; f.poi_index = 0; f.beacon = True
notes.clear(); tick(); tick()
f.poi_index = 1; tick(); tick(); f.poi_index = 0; tick()
routes = [n for n in notes if n.startswith("route to")]
assert len(routes) == 1, routes
print("same place keeps its route OK")
m.on_disable()
print("ALL ROUND 20 TESTS OK")
