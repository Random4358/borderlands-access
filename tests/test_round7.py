"""Tests for: character descriptions, silence in menus, scanner categories."""
import enum, sys, time, types
from types import SimpleNamespace as NS

sys.path.insert(0, sys.argv[1])

class EInputEvent(enum.IntEnum):
    IE_Pressed = 0; IE_Released = 1

class _Opt:
    def __init__(self, ident, value=None, *a, **k): self.value = value
mb = types.ModuleType("mods_base")
for n in ("BoolOption", "DropdownOption", "SliderOption", "ButtonOption"):
    setattr(mb, n, _Opt)
mb.GroupedOption = lambda ident, children, **k: NS(children=children)
mb.EInputEvent = EInputEvent
mb.keybind = lambda ident, key=None, callback=None, **k: NS(identifier=ident, key=key, callback=callback)
mb.build_mod = lambda **k: NS(save_settings=lambda: None, settings_file=None)
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



# ================================================================ round 7: status menu tabs, skills, items, quest waypoints
import json, os
from bl2_access.status_reader import status, TAB_FILE
if os.path.exists(TAB_FILE):
    os.remove(TAB_FILE)
status._load_tabs()

def cls(name, supers=()):
    chain = [NS(Name=name)] + [NS(Name=s) for s in supers]
    return NS(Name=name, _superfields=lambda: chain, _properties=lambda: [])

class Movie:
    Name = "StatusMenuExGFxMovie_0"
    def __init__(s): s.Class = cls("StatusMenuExGFxMovie", ["GFxMoviePlayer"]); s.tab = 1
    def GetCurrentTab(s): return s.tab
movie = Movie()
focus = NS(movie=movie)
class Tree:
    def GetSkillGrade(s, sk): return {"Ward": 3}.get(sk.Name, 0)
world.pc = NS(Pawn=None, GFxUIManager=NS(FindFocusMovie=lambda: focus.movie), WorldInfo=NS(Pauser=None),
              PlayerSkillTree=Tree())
m.controls.menus.opened(movie)

def tick():
    m.hooks._last_tick = 0; m.hooks.on_tick(None, None, None, None)

def run(path, kind, obj, ret=None, **args):
    a = NS(**args); a._type = NS(_properties=lambda: [NS(Name=k) for k in args])
    hooked[(path, kind)](obj, a, ret, None)

# --- tabs: learned from the tab's own input handler, then announced as soon as the tab number changes
said.clear()
tick()
assert not said, said                                     # tab 1 not known yet: nothing to say
run("WillowGame.StatusMenuExGFxMovie:HandleMapInputKey", Type.PRE, movie, ControllerId=0, ukey="XboxTypeS_DPad_Down", uevent=0)
print("tab:", said[-1]); assert said[-1][0] == "Map"
n = len(said)
run("WillowGame.StatusMenuExGFxMovie:HandleMapInputKey", Type.PRE, movie, ControllerId=0, ukey="XboxTypeS_DPad_Down", uevent=1)
assert len(said) == n                                      # same tab: not repeated
movie.tab = 2; tick()
assert len(said) == n                                      # unknown tab number: wait for its handler
run("WillowGame.StatusMenuExGFxMovie:HandleInventoryInputKey", Type.PRE, movie, ControllerId=0, ukey="XboxTypeS_DPad_Down", uevent=0)
assert said[-1][0] == "Inventory", said[-1]
movie.tab = 1; tick(); assert said[-1][0] == "Map", said[-1]          # known now: immediate
movie.tab = 2; tick(); assert said[-1][0] == "Inventory"
assert json.load(open(TAB_FILE)) == {"1": "Map", "2": "Inventory"}
assert ("WillowGame.StatusMenuExGFxMovie:HandleKeyDefaults", Type.PRE) not in hooked
print("tabs OK")

# --- items: highlighted item read, comparison (equipped) item skipped, repeats suppressed
def item(kind, name, level, path, equipped=False, value=0):
    return NS(Class=cls(kind), Name=path, _path_name=lambda: path, GetShortHumanReadableName=lambda: name,
              GetExpLevel=lambda: level, bEquipped=equipped, GetMonetaryValue=lambda: value)
smg = item("WillowWeapon", "Bandit SMG", 5, "Inv.W1", value=120)
pistol = item("WillowWeapon", "Jakobs Pistol", 4, "Inv.W2", equipped=True)
shield = item("WillowShield", "Absorbing Shield", 6, "Inv.S1")
card = NS(Name="ItemCardGFxObject_0")
said.clear()
run("WillowGame.InventoryCardGFx:SetItemCardEx", Type.PRE, card, WPC=None, InventoryItem=smg, ComparisonItem=pistol)
run("WillowGame.InventoryCardGFx:SetItemCardEx", Type.PRE, card, WPC=None, InventoryItem=pistol, ComparisonItem=None)  # 2nd card
time.sleep(0.1); tick()
print("item:", said); assert said[-1][0] == "Bandit SMG, level 5, worth 120 dollars", said
n = len(said)
run("WillowGame.InventoryCardGFx:SetFocusItem", Type.PRE, card, Item=smg); time.sleep(0.1); tick()
assert len(said) == n                                      # same item again: silent
run("WillowGame.StatusMenuInventoryPanelGFxObject:OnHighlight", Type.PRE, card, Thing=shield); time.sleep(0.1); tick()
assert said[-1][0] == "Absorbing Shield, level 6", said[-1]
run("WillowGame.InventoryCardGFx:SetItemCardEx", Type.PRE, card, WPC=None, InventoryItem=pistol, ComparisonItem=None)
time.sleep(0.1); tick()
assert said[-1][0] == "Jakobs Pistol, level 4, equipped", said[-1]   # highlighting the equipped gun itself
assert ("WillowGame.InventoryCardGFx:SetDef", Type.PRE) not in hooked   # definitions aren't items
m.controls._repeat(); assert said[-1][0] == "Jakobs Pistol, level 4, equipped", said[-1]
# outside menus the item hooks stay quiet
m.controls.menus.closed(movie); focus.movie = None
n = len(said)
run("WillowGame.InventoryCardGFx:SetItemCardEx", Type.PRE, card, WPC=None, InventoryItem=smg, ComparisonItem=None)
time.sleep(0.1); tick(); assert len(said) == n, (said[n:], m.controls.menus.open)
focus.movie = movie; m.controls.menus.opened(movie)
print("items OK")

# --- skills: name, points, the description the game generated
ward = NS(Class=cls("SkillDefinition"), Name="Ward", _path_name=lambda: "S.Ward", SkillName="Ward", MaxGrade=5,
          SkillDescription="fallback")
accel = NS(Class=cls("SkillDefinition"), Name="Accelerate", _path_name=lambda: "S.Acc", SkillName="Accelerate",
           MaxGrade=5, SkillDescription="Increases [skill]gun damage[-skill].")
run("WillowGame.SkillTreeGFxObject:GetSkillDescriptionForGrade", Type.POST, None,
    ret="Increases your <font color='#ff0'>shield capacity</font>.", SkillDef=ward, Grade=1)
print("skill:", said[-1][0]); assert said[-1][0] == "Ward, 3 of 5 points. Increases your shield capacity."
n = len(said)
run("WillowGame.SkillTreeGFxObject:GetSkillDescriptionForGrade", Type.POST, None, ret="x", SkillDef=ward, Grade=2)
assert len(said) == n                                      # same skill, same moment: once
run("WillowGame.SkillTreeGFxObject:GetSkillDescriptionForGrade", Type.POST, None, ret="", SkillDef=accel, Grade=1)
assert said[-1][0] == "Accelerate, 0 of 5 points. Increases gun damage.", said[-1]
m.controls.menus.closed(movie); focus.movie = None
print("skills OK")

# --- quest waypoints: the tracker's waypoint list gives the scanner real positions
class Pawn:
    def __init__(s, name, loc):
        s.Name = name; s.Location = NS(X=loc[0], Y=loc[1], Z=loc[2]); s.Class = cls("WillowPlayerPawn", ["Pawn", "Actor"])
        s.BaseEyeHeight = 60; s.NextPawn = None; s.Velocity = NS(X=0, Y=0, Z=0); s.bDeleteMe = False; s.bHidden = False
        s.Controller = None; s.Weapon = None; s.CylinderComponent = NS(CollisionHeight=90)
    def GetHealth(s): return 100
    def GetMaxHealth(s): return 100
    def IsEnemy(s, o): return False
    def FastTrace(s, e, st): return True
me = Pawn("me", (0, 0, 0))
obj1 = NS(Class=NS(Name="MissionObjectiveDefinition"), ProgressMessage="Kill [skill]Boom[-skill]", ObjectiveCount=1)
obj2 = NS(Class=NS(Name="MissionObjectiveDefinition"), ProgressMessage="Open the gate", ObjectiveCount=1)
mission = NS(Name="M1", Class=NS(Name="MissionDefinition"), MissionName="Cleaning Up the Berg", MissionSummary="",
             MissionObjectives=[obj1, obj2])
side = NS(Name="M2", Class=NS(Name="MissionDefinition"), MissionName="Shielded Favors", MissionObjectives=[])
target = NS(Name="Boom", Class=cls("WillowAIPawn", ["Pawn", "Actor"]), Location=NS(X=3000, Y=0, Z=0))
gate = NS(Name="Gate", Class=cls("WillowInteractiveObject", ["Actor"]), Location=NS(X=0, Y=800, Z=0))
comp = NS(Name="WP", Class=cls("MissionObjectiveWaypointComponent", ["WaypointComponent", "ActorComponent"]), Owner=gate)
def rec(**f):
    r = NS(**f); r._type = NS(_properties=lambda: [NS(Name=k) for k in f]); return r
tracker = NS(ActiveMission=mission, MissionList=[NS(MissionDef=mission, Status=1, ObjectivesProgress=[0, 0])],
             MissionWaypoints=[
                 rec(Mission=mission, Objective=obj1, WaypointActor=target),
                 rec(Mission=mission, Objective=obj2, Waypoint=comp),
                 rec(Mission=side, Info=rec(Location=NS(X=-500, Y=0, Z=0))),   # a fixed point, other mission
                 rec(Mission=mission, Objective=obj2, Waypoint=comp),           # duplicate
                 rec(Nothing=None),                                              # no position: ignored
             ])
class PC:
    def __init__(s):
        s.Pawn = me; s.Rotation = NS(Pitch=0, Yaw=0, Roll=0); s.PlayerInput = None
        s.WorldInfo = NS(PawnList=me, GetMapName=lambda b: "Glacial_P", Pauser=None, GRI=NS(MissionTracker=tracker))
        s.GFxUIManager = NS(FindFocusMovie=lambda: None)
    def LineOfSightTo(s, p): return True
    def SetRotation(s, r): s.Rotation = r
world.pc = PC(); objects.clear()
from bl2_access import quests
pts = quests.waypoints(world.pc)
print("waypoints:", [(w.label, w.pos, w.active) for w in pts])
assert [w.label for w in pts] == ["Kill Boom", "Open the gate", "Shielded Favors: Objective waypoint"]
f = m.feats
said.clear(); f.categories = {}; f.category = ""
f.cycle_category(1)
print("quest category:", said[-1][0])
assert said[-1][0].startswith("Quest objectives, 4 entries. Mission: Cleaning Up the Berg.") and "Objective" in said[-1][0]
f.toggle_beacon(); assert f.beacon, said[-1]                       # summary entry: leads to the nearest objective
assert f.pois[0].position() == (0.0, 800.0, 0.0)                    # the gate is nearer than Boom
f.toggle_beacon()
f.cycle_poi(1); print("entry 2:", said[-1][0]); assert said[-1][0].startswith("Open the gate,") and said[-1][0].endswith("2 of 4")
f.cycle_poi(1); assert said[-1][0].startswith("Kill Boom,"), said[-1]
f.cycle_poi(1); assert said[-1][0].startswith("Shielded Favors: Objective waypoint,"), said[-1]
f.toggle_beacon(); assert f.beacon                                  # fixed point: beacon works
snap = f.snapshot(); f.next_beacon = 0; played.clear(); f.beacon_tick(snap, time.perf_counter())
from bl2_access import navigation as NAV
assert NAV.beacon.started and f.beacon, NAV.beacon.last           # the steady beacon tone is playing
f.toggle_beacon()
tracker.MissionWaypoints = []                                       # no markers yet
f.categories = {}; f.category = ""; f.cycle_category(1); f.toggle_beacon()
assert not f.beacon and "marked a location" in said[-1][0], said[-1]
del tracker.MissionWaypoints                                        # property missing: no crash
assert quests.waypoints(world.pc) == []
print("waypoints OK")
m.on_disable()
assert not any(k[0].startswith("WillowGame.InventoryCardGFx") for k in hooked)
os.remove(TAB_FILE)
print("ALL ROUND 7 TESTS OK")
