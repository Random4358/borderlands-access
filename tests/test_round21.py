"""Tests for: character descriptions, silence in menus, scanner categories."""
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



# ================================================================ round 21: the character's own trace hits its own body (as seen in game)
import math
import bl2_access.game as G
import bl2_access.navigation as NAV
from bl2_access import trace as T

notes = []
T.note = lambda text: notes.append(text)
def reset():
    G.TRACE_MODE = None; G.FLOOR_SEEN = False; G._trace_notes.clear(); notes.clear()
    G.TRACE_VIA = None; G.TRACE_VIA_NAME = "character"
FLOOR = -90.0
walls = [(1000, 1020, -400, 150, 2000), (1000, 1020, 280, 400, 2000),
         (1000, 1600, -420, -400, 2000), (1000, 1600, 400, 420, 2000), (1580, 1600, -420, 420, 2000)]
crate = (300, 360, -2000, -1800, FLOOR + 50)

def world_blocked(a, b):
    n = max(2, int(math.dist(a, b) / 10))
    for i in range(n + 1):
        x = a[0] + (b[0] - a[0]) * i / n; y = a[1] + (b[1] - a[1]) * i / n; z = a[2] + (b[2] - a[2]) * i / n
        if z <= FLOOR or any(x0 <= x <= x1 and y0 <= y <= y1 and z <= z1 for x0, x1, y0, y1, z1 in walls + [crate]):
            return True
    return False

class World:
    """The level's WorldInfo: traces only the world."""
    def FastTrace(s, end, start): return not world_blocked((start.X, start.Y, start.Z), (end.X, end.Y, end.Z))
class Pawn:
    """A character whose own FastTrace also hits its own capsule (radius 35, feet to 180 up)."""
    def __init__(s, at):
        s.Location = NS(X=at[0], Y=at[1], Z=FLOOR + 90); s.CylinderComponent = NS(CollisionHeight=90)
        s.Velocity = NS(X=0.0, Y=0.0, Z=0.0); s.Acceleration = NS(X=0.0, Y=0.0, Z=0.0)
        s.WorldInfo = World(); s.Controller = None
        s.Name = "me"; s.Class = NS(Name="WillowPlayerPawn"); s.BaseEyeHeight = 60; s.NextPawn = None
        s.bDeleteMe = False; s.bHidden = False; s.Weapon = None
    def in_body(s, x, y, z):
        return math.hypot(x - s.Location.X, y - s.Location.Y) <= 35 and FLOOR <= z <= FLOOR + 180
    def FastTrace(s, end, start):
        if s.in_body(start.X, start.Y, start.Z):
            return False                     # starts inside you: "blocked" at once
        return not world_blocked((start.X, start.Y, start.Z), (end.X, end.Y, end.Z))
    def GetHealth(s): return 100
    def GetMaxHealth(s): return 100
    def IsEnemy(s, o): return False

# --- before the fix the character's trace was used: everything looked blocked
reset(); me = Pawn((0.0, 0.0))
G.TRACE_MODE = "fast"
assert G.ground_z(me, 0, 0, me.Location.Z) > FLOOR + 80              # "ground" at your body, like the log
assert G.openings(me) == []                                           # every way "blocked"
# --- the self-check notices and switches to the world object
reset(); print("self-check:", G.trace_self_test(me))
assert G.TRACE_VIA_NAME == "world", notes
tracer = [n for n in notes if n.startswith("line test tracer")][0]
print(tracer)
assert "character: floor seen, 0 of 8 directions clear" in tracer and "world: floor seen, 8 of 8" in tracer
assert abs(G.ground_z(me, 0, 0, me.Location.Z) - FLOOR) < 3          # real ground now
assert len(G.openings(me)) == 12                                      # open all round
print("tracer choice OK")

# --- the route planner now finds the way into the room
class PC: pass
target = (1300.0, 0.0, FLOOR)
r = NAV.Route(); now = 0.0
me.Location = NS(X=700.0, Y=-200.0, Z=FLOOR + 90)
for _ in range(90):
    now += 1 / 30
    p = r.next_point(PC(), (700.0, -200.0, FLOOR + 150), target, None, "Cabinet", now, me)
print("beacon heads for", tuple(round(c) for c in p), "|", [n for n in notes if "planner" in n][:1])
assert r.path_kind == "done" and p[1] > 100, (r.path_kind, p)
assert not any("no walkable way" in n for n in notes)
print("route through the doorway OK")

# --- the jump cue and "blocked" messages work again
me.Location = NS(X=250.0, Y=-1900.0, Z=FLOOR + 90); me.Acceleration = NS(X=800.0, Y=0.0, Z=0.0)
b = G.blockage(me, 0.0, 100)
assert b["jumpable"], b
print("jump check OK")
print("ALL ROUND 21 TESTS OK")

# --- last resort: every object's trace hits your body -> lines start just outside it
reset()
class BodyWorld(World):
    def __init__(s, pawn): s.pawn = pawn
    def FastTrace(s, end, start):
        if s.pawn.in_body(start.X, start.Y, start.Z):
            return False
        return World.FastTrace(s, end, start)
me = Pawn((0.0, 0.0)); me.WorldInfo = BodyWorld(me)
print("self-check:", G.trace_self_test(me))
tracer = [n for n in notes if n.startswith("line test tracer")][0]
print(tracer)
assert "starting lines just outside your body (4 of 4" in tracer, tracer
assert abs(G.ground_z(me, 0, 0, me.Location.Z) - FLOOR) < 3
assert len(G.openings(me)) == 12
me.Location = NS(X=250.0, Y=-1900.0, Z=FLOOR + 90)
assert G.blockage(me, 0.0, 100)["jumpable"]
G.BODY_PTR = None
print("starting outside the body OK")
print("ALL ROUND 21 TESTS OK (with fallback)")
