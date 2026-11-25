"""Tests for: calling the engine's line test directly."""
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



# ================================================================ round 22: object sounds stay with their object; chests aren't wrongly "opened"


# ================================================================ round 24: the engine's own line test, called directly
import os, struct, math, tempfile
import bl2_access.native_trace as N
import bl2_access.game as G
from bl2_access import trace as T
notes = []
T.note = lambda text: notes.append(text)

# --- the arguments, as the game's scripts pass them
code = N.bytecode((1.0, 2.0, 3.0), (4.0, 5.0, 6.0))
assert code[0] == 0x23 and struct.unpack_from("<3f", code, 1) == (1.0, 2.0, 3.0)
assert code[13] == 0x23 and struct.unpack_from("<3f", code, 14) == (4.0, 5.0, 6.0)
assert code[26:] == bytes([0x4A, 0x4A, 0x16]) and len(code) == 29
fr = N.frame_bytes(0x1000, 0x2000, 0x3000, 0x4000, 0x5000)
assert len(fr) == N.FRAME_SIZE and struct.unpack_from("<I", fr, 0)[0] == 0x1000
assert struct.unpack_from("<4I", fr, 16) == (0x2000, 0x3000, 0x4000, 0x5000)
assert struct.unpack_from("<2I", fr, 32) == (0, 0)          # no previous frame, no out-parameters
# the thunk: this in ECX, frame and result pushed, call, return
assert N.THUNK[:3] == bytes([0x55, 0x8B, 0xEC]) and N.THUNK[-1] == 0xC3 and bytes([0x8B, 0x4D, 0x0C]) in N.THUNK
print("bytecode, frame and thunk OK")

# --- finding the native code pointer in a function object's memory
TEXT = (0x00401000, 0x01400000)
mem = {}
def put(addr, data):
    for i, b in enumerate(data):
        mem[addr + i] = b
def read(addr, n):
    if any(addr + i not in mem for i in range(n)):
        # unknown memory reads as zeros inside a "function object", None elsewhere (like ReadProcessMemory)
        if addr >= 0x20000000:
            return bytes(mem.get(addr + i, 0) for i in range(n))
        return None
    return bytes(mem[addr + i] for i in range(n))
FUNC = 0x20000000
blob = bytearray(0x200)
struct.pack_into("<I", blob, 0x10, 0x00401234)        # a vtable-like pointer before the flags: must not be taken
struct.pack_into("<I", blob, 0x84, 0x00020401)        # FunctionFlags (native, final...)
struct.pack_into("<HH", blob, 0x88, 0, 0)             # iNative, RepOffset
struct.pack_into("<HH", blob, 0x90, 0x1C, 0x18)       # ParamsSize, ReturnValueOffset
struct.pack_into("<I", blob, 0x94, 0x7FFF0000)        # padding / heap pointer: not code
struct.pack_into("<I", blob, 0x98, 0x00A1B2C0)        # Func: points into code
put(FUNC, blob)
found = N.find_native_pointer(read, FUNC, 0x00020401, 0x1C, 0x18, TEXT)
assert found == (0x98, 0x00A1B2C0), found
assert N.find_native_pointer(read, FUNC, 0x12345, 0x1C, 0x18, TEXT) is None   # wrong flags: nothing guessed
print("code pointer search OK")

# --- the code section, from the game's PE header
BASE = 0x00400000
pe = bytearray(0x400)
pe[0:2] = b"MZ"; struct.pack_into("<I", pe, 0x3C, 0x80)
pe[0x80:0x84] = b"PE\0\0"; struct.pack_into("<H", pe, 0x86, 2); struct.pack_into("<H", pe, 0x94, 0xE0)
sec = 0x80 + 0x18 + 0xE0
pe[sec:sec + 8] = b".text\0\0\0"; struct.pack_into("<II", pe, sec + 8, 0xFFF000, 0x1000)
pe[sec + 40:sec + 48] = b".data\0\0\0"; struct.pack_into("<II", pe, sec + 48, 0x100000, 0x1000000)
put(BASE, pe)
assert N.text_section(read, BASE) == (0x00401000, 0x01400000), N.text_section(read, BASE)
assert N.text_section(read, 0x00300000) is None
print("code section OK")

# --- crash guard and safety switches
d = N.DirectTrace()
N.MARKER = os.path.join(tempfile.mkdtemp(), "native_trace_attempt.txt")
open(N.MARKER, "w").write("x")
assert d.prepare() is False and d.state == "off" and "stopped during the first direct call" in d.reason
os.remove(N.MARKER)
d = N.DirectTrace(); d.enabled = False
assert d.prepare() is False and "switched off in the settings" in d.reason
d = N.DirectTrace()
assert d.prepare() is False and d.state == "off"          # this test runs in 64-bit Python (or without the game)
try:
    d.fast_trace(NS(_get_address=lambda: 1), (0, 0, 0), (0, 0, -100)); raise AssertionError("should refuse")
except RuntimeError as e:
    assert "off" in str(e)
assert any(n.startswith("direct line test: off") for n in notes)
print("crash guard OK")

# --- the self-check tries it first and uses it when its answers make sense
FLOOR = -90.0
def blocked(a, b):
    n = 40
    return any(a[2] + (b[2] - a[2]) * i / n <= FLOOR for i in range(n + 1))
class Pawn:
    def __init__(s):
        s.Location = NS(X=0.0, Y=0.0, Z=0.0); s.Controller = None; s.WorldInfo = None
        s.CylinderComponent = NS(CollisionHeight=90)
    def FastTrace(s, e, st): return False           # the SDK route: always "blocked", as in the game
    def Trace(s, *a, **k): return None
me = Pawn()
class Fake:
    state = "ready"
    def fast_trace(s, actor, start, end): return not blocked(start, end)
real = N.direct; N.direct = Fake()
G.FLOOR_SEEN = False; G.TRACE_MODE = None
verdict = G.trace_self_test(me)
print("self-check:", verdict)
assert G.FLOOR_SEEN and G.TRACE_METHOD == "direct engine call", (G.TRACE_METHOD, notes[-3:])
assert G.fast_trace(me, (0, 0, 0), (0, 0, -500)) is False and G.fast_trace(me, (0, 0, 0), (500, 0, 0)) is True
N.direct = real; G.FLOOR_SEEN = False; G.TRACE_METHOD = "FastTrace(end, start)"
print("self-check picks the direct call OK")

# --- turning the view: the game's SetRotation does nothing (seen in game), so the value is written
class GamePC:
    def __init__(s): s.Rotation = NS(Pitch=3158, Yaw=55802, Roll=0); s.calls = []
    def SetRotation(s, r): s.calls.append("SetRotation")          # accepted, does nothing
    def ClientSetRotation(s, r): s.calls.append("ClientSetRotation")
pc = GamePC()
assert G.set_view(pc, 4998, -12985) is True
assert pc.Rotation.Pitch == 4998 and pc.Rotation.Yaw == (-12985) & 0xFFFF and pc.calls == []
assert G.VIEW_METHOD == "Rotation value"
class Frozen:
    """Nothing turns it: set_view must say so instead of claiming success."""
    def __init__(s): object.__setattr__(s, "_r", NS(Pitch=0, Yaw=0, Roll=0))
    @property
    def Rotation(s): return s._r
    @Rotation.setter
    def Rotation(s, v): pass
    def SetRotation(s, r): pass
    def ClientSetRotation(s, r): pass
assert G.set_view(Frozen(), 1000, 2000) is False
assert any("couldn't turn the view" in n for n in notes)
# wrap-around: 65535 and -1 are the same direction
pc.Rotation = NS(Pitch=0, Yaw=65535, Roll=0); assert G._rotation_is(pc, 0, -1)
print("turning the view OK")

# --- skill tree: "Skills" once (not on every button press), points to spend, points per skill
from bl2_access.status_reader import status as SR
from bl2_access import controls as C
ward = NS(Class=NS(Name="SkillDefinition"), Name="Ward", _path_name=lambda: "S.Ward", SkillName="Ward", MaxGrade=5,
          SkillDescription="Your shield holds more.")
tree = NS(Skills=[NS(Definition=NS(Name="Other", _path_name=lambda: "S.Other"), Grade=1),
                  NS(Definition=NS(Name="Ward", _path_name=lambda: "S.Ward"), Grade=2)])
status_movie = NS(Name="StatusMenuExGFxMovie_1", Class=NS(Name="StatusMenuExGFxMovie"), GetCurrentTab=lambda: 4,
                  _path_name=lambda: "StatusMenuExGFxMovie_1")
skill_movie = NS(Name="SkillTreeGFxObject_0", Class=NS(Name="SkillTreeGFxObject"), _path_name=lambda: "SkillTree")
focus = {"m": status_movie}
world.pc = NS(Pawn=None, PlayerSkillTree=tree, PlayerReplicationInfo=NS(GeneralSkillPoints=3),
              GFxUIManager=NS(FindFocusMovie=lambda: focus["m"]), WorldInfo=NS(Pauser=None), Rotation=NS(Pitch=0, Yaw=0, Roll=0))
C.menus.opened(status_movie)
SR.tab_word, SR.tab_num = "", None
said.clear()
SR.on_tab_input(status_movie, "Skills")
assert said and said[-1][0] == "Skills. 3 skill points to spend", said
focus["m"] = skill_movie                        # inside the tree, something else has the focus
for _ in range(5):
    SR._poll_tab()
    SR.on_tab_input(status_movie, "Skills")     # every button press runs the tab's handler
assert [s for s, _i in said].count("Skills. 3 skill points to spend") == 1, said
said.clear(); SR.last_skill = ""
SR.on_skill(ward, "Shield Capacity: +5%")
print("skill:", said[-1][0])
assert said[-1][0] == "Ward, 2 of 5 points. Your shield holds more. Shield Capacity: +5%.", said[-1]
one = NS(Class=NS(Name="SkillDefinition"), Name="Deathtrap", _path_name=lambda: "S.DT", SkillName="Summon Deathtrap",
         MaxGrade=1, SkillDescription="")
SR.last_skill = ""; SR.on_skill(one, "Cooldown: 60 seconds")
assert said[-1][0] == "Summon Deathtrap, 1 point maximum. Cooldown: 60 seconds.", said[-1]
C.menus.closed(status_movie); focus["m"] = None
print("skill tree reading OK")

# --- drop sounds: only what the item itself plays, never a creature's sound
from bl2_access import game_sounds as GS
GS.STORE = os.path.join(tempfile.mkdtemp(), "gs.json")
gs = GS.GameSounds()
gs.note_item("Map.TheWorld:PersistentLevel.WillowPickup_1", (0.0, 0.0, 0.0), "ammo")
pick = NS(Class=NS(Name="WillowPickup"), _path_name=lambda: "Map.TheWorld:PersistentLevel.WillowPickup_1")
rock = NS(Class=NS(Name="AkEvent"), Name="Ak_Play_Mon_BMong_Rock_Impact", _path_name=lambda: "Ake.Rock")
bully = NS(Class=NS(Name="WillowAIPawn"), Location=NS(X=10.0, Y=0.0, Z=0.0))
gs.heard(bully, rock); gs.heard(pick, rock)
assert not gs.by_kind, gs.by_kind
drop = NS(Class=NS(Name="AkEvent"), Name="Ak_Play_Item_Ammo_Drop", _path_name=lambda: "Ake.Drop")
gs.heard(pick, drop); assert gs.by_kind.get("ammo") is drop
open(GS.STORE, "w").write('{"ammo": ["AkEvent", "Ake_Mon_Bullymong.Ak_Play_Mon_BMong_Rock_Impact"]}')
gs2 = GS.GameSounds(); assert "ammo" not in gs2.saved        # the wrong one learned before is dropped
print("drop sound learning OK")

# --- the current objective: only the live stage of the mission (as in Blindsided), with markers as a fallback
from bl2_access import quests as Q
def odef(text, n=1): return NS(Class=NS(Name="MissionObjectiveDefinition"), ProgressMessage=text, ObjectiveCount=n)
names = ["Retrieve Claptrap's eye", "Defend Claptrap", "Dig out Claptrap", "Defeat Knuckle Dragger",
         "Defeat minions", "Find Sir Hammerlock", "Find new gear", "Loot gear", "Return to Claptrap"]
objs = [odef(n) for n in names]
progress = [1, 0, 0, 1, 1, 0, 0, 0, 0]          # earlier stages done; Defend Claptrap live; later ones not started
stage = NS(Name="Set_DefendClaptrap", Class=NS(Name="MissionObjectiveSetDefinition"), ObjectiveDefinitions=[objs[1]],
           MissionSummaryOverride="Keep the bullymongs off Claptrap while he digs through the snow.")
blind = NS(Name="Ep2", Class=NS(Name="MissionDefinition"), MissionName="Blindsided", MissionSummary="",
           MissionObjectives=objs)
def rec2(**f):
    r = NS(**f); r._type = NS(_properties=lambda: [NS(Name=k) for k in f]); return r
_chain = [NS(Name=n) for n in ("WillowAIPawn", "Pawn", "Actor")]
claptrap = NS(Name="Claptrap", Class=NS(Name="WillowAIPawn", _superfields=lambda: _chain, _properties=lambda: []), Location=NS(X=1500.0, Y=0.0, Z=0.0))
entry = rec2(MissionDef=blind, Status=1, ObjectivesProgress=progress, ActiveObjectiveSet=stage)
trk = NS(ActiveMission=blind, MissionList=[entry], MissionWaypoints=[rec2(Mission=blind, Objective=objs[1], WaypointActor=claptrap)])
qpc = NS(WorldInfo=NS(GRI=NS(MissionTracker=trk)))
info = Q.active_mission(qpc)
print("mission:", info.spoken())
assert info.spoken() == ("Mission: Blindsided. Now: Defend Claptrap. "
                         "Keep the bullymongs off Claptrap while he digs through the snow"), info.spoken()
# no stage in the entry: the game's marker decides, not the later objectives that haven't started
entry2 = rec2(MissionDef=blind, Status=1, ObjectivesProgress=progress)
trk.MissionList = [entry2]
info = Q.active_mission(qpc)
print("mission (markers):", info.spoken())
assert info.spoken() == "Mission: Blindsided. Now: Defend Claptrap", info.spoken()
assert "Find Sir Hammerlock" not in info.spoken()
assert any(n.startswith("mission entry fields:") for n in notes)
# later, as in the game: everything up to the eye done, the marker still labelled "Defend Claptrap"
progress[:] = [1, 1, 1, 1, 1, 0, 0, 0, 0]
info = Q.active_mission(qpc)
print("mission (stale marker):", info.spoken())
assert info.spoken() == ("Mission: Blindsided. Objectives: Find Sir Hammerlock. Find new gear. Loot gear. "
                         "Return to Claptrap"), info.spoken()
print("current objective OK")

# --- opened containers drop off: the ones you open, then any showing the game's learned "opened" value
import bl2_access.opened as OP
from bl2_access.object_sounds import _still_usable
OP.STORE = os.path.join(tempfile.mkdtemp(), "opened_flag.json")
op = OP.Opened(); OP.opened = op
class Chest:
    def __init__(s, name, state="Closed"):
        s.Name = name; s.State = NS(name=state); s.bIsUsable = True; s.LastRenderTime = 1.0; s.Loot = 3
        props = [NS(Name=n) for n in ("State", "bIsUsable", "LastRenderTime", "Loot")]
        s.Class = NS(Name="WillowInteractiveObject", _properties=lambda: props)
    def _path_name(s): return "Glacial_P.TheWorld:PersistentLevel." + s.Name
qpc2 = NS(WorldInfo=NS(GetMapName=lambda b: "Glacial_P"))
c1, c2, c3, c4 = Chest("Chest_1"), Chest("Chest_2"), Chest("Chest_3", "Opened"), Chest("Chest_4")
assert _still_usable(c1)
op.tick(qpc2, 0.0)
op.note_use(c1, 1.0)
assert not _still_usable(c1)                         # the one you opened is gone at once
c1.State = NS(name="Opened"); c1.LastRenderTime = 9.0; c1.Loot = 0
op.tick(qpc2, 3.0)
assert any("container opened: Chest_1" in n and "State" in n for n in notes), notes[-2:]
assert op.flag is None                                 # one container isn't proof
op.note_use(c2, 4.0); c2.State = NS(name="Opened"); op.tick(qpc2, 6.0)
assert op.flag == ("State", "Opened"), op.flag
assert not _still_usable(c3) and _still_usable(c4)    # opened before you came: gone; closed: stays
assert os.path.exists(OP.STORE) and OP.Opened().flag == ("State", "Opened")   # remembered next time
# a new level: what you opened is forgotten (the game refills chests), the learned value stays
op.tick(NS(WorldInfo=NS(GetMapName=lambda b: "Sanctuary_P")), 7.0)
assert not op.used and op.flag
print("opened containers OK")

# --- the marker is named by the live objective (not the finished one the game left on it)
blind_stage = NS(Name="FindGearSet", Class=NS(Name="MissionObjectiveSetDefinition"), ObjectiveDefinitions=[objs[6]])
progress[:] = [1, 1, 1, 1, 1, 1, 0, 0, 0]
trk.MissionList = [rec2(MissionDef=blind, Status=1, ObjectivesProgress=progress, ActiveObjectiveSet=blind_stage)]
wps = Q.waypoints(qpc)
assert wps and wps[0].label == "Find new gear", [w.label for w in wps]
print("marker label OK")

# --- arriving at a marker on a ledge: not "arrived" while it's 3 m up; what's near it is said
from bl2_access import features as FE
F_ = m.feats
class Me2:
    def __init__(s, z): s.Location = NS(X=0.0, Y=0.0, Z=z); s.CylinderComponent = NS(CollisionHeight=90); s.BaseEyeHeight = 60
me2 = Me2(6464.0)
chest = NS(Name="Chest_9", Class=NS(Name="WillowInteractiveObject"), Location=NS(X=150.0, Y=0.0, Z=6600.0), bIsUsable=True,
           bDeleteMe=False, _path_name=lambda: "Glacial_P.TheWorld:PersistentLevel.Chest_9",
           InteractiveObjectDefinition=NS(Name="IO_Chest_Red"))
objects["WillowInteractiveObject"] = [chest]
world.pc = NS(Pawn=me2, Rotation=NS(Pitch=0, Yaw=0, Roll=0), PlayerInput=None, FOVAngle=90.0,
              WorldInfo=NS(PawnList=None, GetMapName=lambda b: "Glacial_P", Pauser=None, GRI=NS(MissionTracker=trk), TimeSeconds=0.0),
              GFxUIManager=NS(FindFocusMovie=lambda: None))
snap = FE.Snapshot(world.pc, me2, (0.0, 0.0, 6524.0), 0.0, 0.0)
F_.pois = [FE.POI("Find new gear", None, "Quest objectives", pos=(100.0, 0.0, 6631.0))]
F_.poi_index = 0; F_.beacon = True; said.clear()
F_.beacon_tick(snap, 1.0)
print("ledge:", said[-1][0])
assert F_.beacon and (said[-1][0].startswith("Find new gear is about 3 metres above you. ") and "way up" in said[-1][0] and "Look for" not in said[-1][0]), said
assert "Chest" in said[-1][0], said[-1]
n = len(said); F_.beacon_tick(snap, 1.1); assert len(said) == n      # said once
# up on the ledge: arrived, and told what's there
me2.Location = NS(X=0.0, Y=0.0, Z=6640.0); snap = FE.Snapshot(world.pc, me2, (0.0, 0.0, 6700.0), 0.0, 0.0)
F_.beacon_tick(snap, 2.0)
print("arrived:", said[-1][0])
assert not F_.beacon and said[-1][0].startswith("Arrived at Find new gear. Here: Chest"), said[-1]
objects["WillowInteractiveObject"] = []
print("arriving at raised markers OK")
m.on_disable()
print("ALL ROUND 24 TESTS OK")
