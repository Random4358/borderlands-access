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



# ================================================================ round 14: steady beacon, route finding, navigation assist
import math
from array import array
from bl2_access import audio as A
from bl2_access.audio import audio as eng
from bl2_access import navigation as NAV
from bl2_access.features import POI, QUEST

def samples(b):
    a = array("h"); a.frombytes(b); return a
def energy(b):
    a = samples(b); return sum(abs(a[i]) for i in range(0, len(a), 2)), sum(abs(a[i]) for i in range(1, len(a), 2))
class FakeStream:
    def __init__(s): s.q = []; s.fed = []; s.stops = 0
    def ahead(s): return len(s.q) * A.SEG
    def feed(s, b): s.q.append(b); s.fed.append(b)
    def stop(s): s.q = []; s.stops += 1
eng.streams = []; eng.combat_streams = []; eng.nav_stream = FakeStream(); eng.ok = True
nav = eng.nav_stream

def cls(name, supers=()):
    chain = [NS(Name=name)] + [NS(Name=s) for s in supers]
    return NS(Name=name, _superfields=lambda: chain, _properties=lambda: [])
class Pawn:
    def __init__(s):
        s.Name = "me"; s.Location = NS(X=0, Y=0, Z=0); s.Class = cls("WillowPlayerPawn", ["Pawn"]); s.player = True
        s.BaseEyeHeight = 0; s.NextPawn = None; s.Velocity = NS(X=0, Y=0, Z=0); s.bDeleteMe = False; s.bHidden = False
        s.Controller = None; s.Weapon = None; s.CylinderComponent = NS(CollisionHeight=90)
    def GetHealth(s): return 100
    def GetMaxHealth(s): return 100
    def IsEnemy(s, o): return False
    def FastTrace(s, e, st): return True
me = Pawn()
route_calls = []
class PC:
    def __init__(s):
        s.Pawn = me; s.Rotation = NS(Pitch=0, Yaw=0, Roll=0); s.PlayerInput = None; s.route = []
        s.WorldInfo = NS(PawnList=me, GetMapName=lambda b: "Glacial_P", Pauser=None, GRI=NS())
        s.GFxUIManager = NS(FindFocusMovie=lambda: None)
    def LineOfSightTo(s, p): return True
    def SetRotation(s, r): s.Rotation = r
    def FindPathToward(s, actor):
        route_calls.append("toward")
        # the next route point you haven't reached yet
        for n in s.route:
            if math.dist((me.Location.X, me.Location.Y), (n.Location.X, n.Location.Y)) > 140:
                return n
        return None
world.pc = PC()
objects.clear()
f = m.feats
for o in ("opt_radar", "opt_npc_sounds", "opt_npc_talk", "opt_walls", "opt_ledges", "opt_jump", "opt_low_health",
          "opt_targeting", "opt_loot_sounds", "opt_container_sounds", "opt_interactive_sounds", "opt_quest_item_sounds",
          "opt_interact"):
    getattr(m, o).value = False
m.controls.menus.open.clear()
def tick():
    m.hooks._last_tick = 0; m.hooks.on_tick(None, None, None, None)
def drain(): nav.q = []

tick()  # first frame in the map (resets the scanner)
goal = NS(Name="Chest", Class=cls("WillowInteractiveObject", ["Actor"]), Location=NS(X=2000, Y=0, Z=0))
f.pois = [POI("Red chest", NS(), "Containers")]
import bl2_access.game as G
f.pois[0].ptr = G.weak(goal)
f.category = "Containers"; f.poi_index = 0; f.beacon = True

# --- straight line (no route): steady tone, on course when facing it
said.clear(); tick()
assert nav.ahead() >= 0.1 - 1e-9 and NAV.beacon.last[0] == "beacon_on", NAV.beacon.last   # facing it
world.pc.Rotation = NS(Pitch=0, Yaw=-8192, Roll=0)     # turned 45 degrees left: the goal is to the right
drain(); tick()
kind, cyc, pan, vol, behind = NAV.beacon.last
assert kind == "beacon" and pan > 0.5 and not behind, NAV.beacon.last
l, r = energy(nav.fed[-1]); assert r > l
world.pc.Rotation = NS(Pitch=0, Yaw=32768, Roll=0)     # facing away
drain(); tick(); assert NAV.beacon.last[4] is True       # muffled: it's behind you
world.pc.Rotation = NS(Pitch=0, Yaw=900, Roll=0)       # ~5 degrees off: still on course
drain(); tick(); assert NAV.beacon.last[0] == "beacon_on"
# no stops/restarts while it plays: one continuous stream
assert nav.stops == 0
# pulses faster when closer
def pulses():
    nav.fed.clear(); NAV.beacon.step = 0
    for _ in range(20):
        drain(); tick()
    return sum(1 for b in nav.fed if max(abs(x) for x in samples(b)) > 0.8 * max(max(abs(x) for x in samples(c)) for c in nav.fed))
far = pulses()
me.Location = NS(X=1700, Y=0, Z=0); near = pulses()
assert near > far, (far, near)
# arriving
me.Location = NS(X=1900, Y=0, Z=0); drain(); tick()
assert not f.beacon and said[-1][0] == "Arrived at Red chest", said[-1]
print("steady beacon OK")

# --- route finding: the beacon leads to each route point in turn, not through the wall
me.Location = NS(X=0, Y=0, Z=0); world.pc.Rotation = NS(Pitch=0, Yaw=0, Roll=0)
world.pc.route = [NS(Name="N1", Location=NS(X=0, Y=800, Z=0)), NS(Name="N2", Location=NS(X=1500, Y=800, Z=0))]
NAV.beacon.route.supported = None; route_calls.clear()
f.beacon = True; drain(); tick()
assert route_calls and NAV.beacon.last[2] > 0.9, NAV.beacon.last      # first point is hard right, not straight ahead
me.Location = NS(X=0, Y=700, Z=0); NAV.beacon.route.next_update = 0; drain(); tick()   # reached N1
world.pc.Rotation = NS(Pitch=0, Yaw=0, Roll=0); drain(); tick()
kind, cyc, pan, vol, behind = NAV.beacon.last
assert abs(pan) < 0.2 and kind == "beacon_on", NAV.beacon.last         # now N2: straight ahead
me.Location = NS(X=1450, Y=800, Z=0); NAV.beacon.route.next_update = 0; drain(); tick()  # route used up
assert NAV.beacon.last[2] < -0.2, NAV.beacon.last                        # heading to the goal itself (to the right of +X? no: -Y)
f.beacon = False; tick(); assert nav.q[-1:] and NAV.beacon.started is False
# a controller with no route finding: straight line, and it stops asking
del PC.FindPathToward
NAV.beacon.route.supported = None; me.Location = NS(X=0, Y=0, Z=0); f.beacon = True; drain(); tick()
assert NAV.beacon.route.supported is False and abs(NAV.beacon.last[2]) < 0.1
f.beacon = False; tick()
print("route finding OK")

# --- navigation assist: one press turns you toward the way to go
world.pc.Rotation = NS(Pitch=3000, Yaw=16384, Roll=0)
m.opt_nav_assist.value = False; tick(); said.clear()
f.face_objective(); assert said[-1][0].startswith("Navigation assist is off"), said
assert world.pc.Rotation.Yaw == 16384
m.opt_nav_assist.value = True; tick()
f.face_objective()
y = ((world.pc.Rotation.Yaw + 32768) % 65536 - 32768) * 360 / 65536
assert abs(y) < 1 and world.pc.Rotation.Pitch == 0, world.pc.Rotation   # facing the chest, view level
assert said[-1][0] == "Facing Red chest, 20 metres", said[-1]
# with a route: faces the first route point
def ftoward(s, a): return NS(Name="N1", Location=NS(X=0, Y=800, Z=0))
PC.FindPathToward = ftoward; NAV.beacon.route.supported = None; NAV.beacon.route.reset()
f.face_objective(); y = ((world.pc.Rotation.Yaw + 32768) % 65536 - 32768) * 360 / 65536
assert abs(y - 90) < 1 and said[-1][0].endswith("following the path"), (y, said[-1])
del PC.FindPathToward
# nothing picked: the tracked mission's nearest marker
f.pois = []; f.poi_index = -1
marker = NS(Name="Boom", Class=cls("WillowAIPawn", ["Pawn", "Actor"]), Location=NS(X=0, Y=-3000, Z=0))
obj = NS(Class=NS(Name="MissionObjectiveDefinition"), ProgressMessage="Kill Boom", ObjectiveCount=1)
mission = NS(Name="M1", Class=NS(Name="MissionDefinition"), MissionName="Berg", MissionObjectives=[obj])
def rec(**kw):
    r = NS(**kw); r._type = NS(_properties=lambda: [NS(Name=k) for k in kw]); return r
world.pc.WorldInfo.GRI = NS(MissionTracker=NS(ActiveMission=mission, MissionList=[],
                                              MissionWaypoints=[rec(Mission=mission, Objective=obj, WaypointActor=marker)]))
NAV.beacon.route.reset(); f.face_objective()
y = ((world.pc.Rotation.Yaw + 32768) % 65536 - 32768) * 360 / 65536
assert abs(y + 90) < 1 and said[-1][0] == "Facing Kill Boom, 30 metres", (y, said[-1])
world.pc.WorldInfo.GRI = NS()
f.face_objective(); assert said[-1][0].startswith("No objective marked")
# buttons: modifier + right stick click, and the apostrophe key
assert m.controls.COMBOS["XboxTypeS_RightThumbStick"] == "stick_r"
assert any(b.key == "Quote" for b in m.KEYBINDS)
m.opt_nav_assist.value = False; tick(); m.controls.ACTIONS["stick_r"][1](); assert said[-1][0].startswith("Heading")
# glossary has both beacon sounds, each with a preview
assert {"beacon", "beacon_on"} <= {k for k, _n, _d in A.SOUNDS} and A.preview("beacon") and A.preview("beacon_on")
m.on_disable()
print("ALL ROUND 14 TESTS OK")
