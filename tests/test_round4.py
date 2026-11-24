"""Tests for: character descriptions, silence in menus, scanner categories."""
import enum, sys, time, types
from types import SimpleNamespace as NS

sys.path.insert(0, sys.argv[1])

class EInputEvent(enum.IntEnum):
    IE_Pressed = 0; IE_Released = 1

class _Opt:
    __hash__ = None   # like the real mod manager's options (dataclasses): can't be dict keys
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
def find_class(name):
    owner = NS(Name=name, Outer=NS(Name="WillowGame"))
    return NS(_find=lambda fn: NS(Outer=owner))
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


# ================================================================ round 4: missions + jump cues
import bl2_access.game as _G; _G.FLOOR_SEEN = True; _G.TRACE_MODE = "fast"   # line tests work in this simulated world
class Pawn:
    def __init__(s, name, loc, player=False, hostile=True):
        s.Name = name; s.Location = NS(X=loc[0], Y=loc[1], Z=loc[2])
        s.Class = NS(Name="WillowPlayerPawn" if player else "WillowAIPawn"); s.hostile = hostile
        s.BaseEyeHeight = 60; s.NextPawn = None; s.Velocity = NS(X=300, Y=0, Z=0); s.bDeleteMe = False; s.bHidden = False
        s.Controller = None; s.AIClass = NS(DefaultDisplayName=name); s.Weapon = None
        s.CylinderComponent = NS(CollisionHeight=90)
        s.geometry = []  # list of (xmin, xmax, zmin, zmax) solid boxes; floor is z <= floor_z unless in a gap
        s.floor_gaps = []  # list of (xmin, xmax) with no floor
    def GetHealth(s): return 100
    def GetMaxHealth(s): return 100
    def IsEnemy(s, other): return getattr(other, "hostile", True)
    def FastTrace(s, end, start):
        """True = clear. Samples the segment against boxes and the floor (floor top at z=-90)."""
        for i in range(41):
            t = i / 40
            px = start.X + (end.X - start.X) * t; pz = start.Z + (end.Z - start.Z) * t
            for (x0, x1, z0, z1) in s.geometry:
                if x0 <= px <= x1 and z0 <= pz <= z1:
                    return False
            in_gap = any(g0 <= px <= g1 for g0, g1 in s.floor_gaps)
            if not in_gap and pz <= -90:
                return False
        return True

me = Pawn("me", (0, 0, 0), player=True)
doc = Pawn("Doc Mercy", (600, 300, 0), hostile=False)
me.NextPawn = doc

# --- mission data, shaped like the real game (names confirmed from the .int files / missionselector)
obj1 = NS(Class=NS(Name="MissionObjectiveDefinition"), ProgressMessage="Kill bandits", ObjectiveCount=5)
obj2 = NS(Class=NS(Name="MissionObjectiveDefinition"), ProgressMessage="Find the [skill]ECHO[-skill] recorder", ObjectiveCount=1)
def props(*names):
    return lambda: [NS(Name=n, Class=NS(Name="ArrayProperty")) for n in names]
mission = NS(Name="M_Ep2_Example", MissionName="Example Mission", MissionSummary="Help the doctor.",
             MissionTurnInLocation="Doc Mercy", TurnInDescription="Talk to Doc Mercy.",
             MissionObjectives=[obj1, obj2])
entry = NS(MissionDef=mission, Status=1, ObjectivesProgress=[3, 0])
tracker = NS(ActiveMission=mission, MissionList=[entry])

class PC:
    def __init__(s):
        s.Pawn = me; s.Rotation = NS(Pitch=0, Yaw=0, Roll=0); s.PlayerInput = None
        s.WorldInfo = NS(PawnList=me, GetMapName=lambda b: "Glacial_P", Pauser=None, GRI=NS(MissionTracker=tracker))
        s.GFxUIManager = NS(FindFocusMovie=lambda: None)
    def LineOfSightTo(s, p): return True
    def SetRotation(s, r): s.Rotation = r
world.pc = PC()
objects.clear()
f = m.feats
from bl2_access import quests

info = quests.active_mission(world.pc)
print("mission:", info.spoken())
assert info.spoken() == "Mission: Example Mission. Objectives: Kill bandits, 3 of 5. Find the ECHO recorder"
said.clear(); f.categories = {}; f.category = ""
f.cycle_category(1)
print("quest category:", said[-1][0])
assert said[-1][0] == "Quest objectives, 2 entries. Mission: Example Mission. Objectives: Kill bandits, 3 of 5. Find the ECHO recorder"
f.cycle_poi(1); print("contact:", said[-1][0])
assert said[-1][0].startswith("Mission contact Doc Mercy,") and said[-1][0].endswith("2 of 2")
f.toggle_beacon(); assert f.beacon, "beacon on the contact"
f.toggle_beacon()
f.cycle_poi(1); assert said[-1][0].endswith("1 of 2")         # back to the mission summary
f.toggle_beacon(); assert not f.beacon and "marked a location" in said[-1][0]
# ready to turn in
entry.Status = 3; entry.ObjectivesProgress = [5, 1]
f.current_mission(); print("turn in:", said[-1][0])
assert said[-1][0] == "Mission: Example Mission. Ready to turn in. Turn it in to Doc Mercy"
f.cycle_category(1); f.cycle_category(-1)                  # round trip back to Quest objectives
f.cycle_poi(1); assert said[-1][0].startswith("Turn in to Doc Mercy,"), said[-1]
# unknown objective layout: falls back to any array of objective definitions + any int array
mission2 = NS(Name="M_Other", MissionName="Other Mission", Things=[obj1],
              Class=NS(Name="MissionDefinition", _properties=props("Things")))
entry2 = NS(MissionDef=mission2, Status=1, Counts=[2], _type=NS(_properties=props("Counts")))
tracker.ActiveMission = mission2; tracker.MissionList = [entry2]
assert quests.active_mission(world.pc).spoken() == "Mission: Other Mission. Objectives: Kill bandits, 2 of 5"
tracker.ActiveMission = None
f.current_mission(); assert said[-1][0] == "No active mission"
world.pc.WorldInfo.GRI = NS()                                # no tracker at all: no crash
assert quests.active_mission(world.pc) is None
print("4a. quest objectives OK")

# --- jump cues
played.clear(); said.clear()
f.s.speak_jump = True
def probe():
    f.next_wall = 0; f.next_jump_ok = 0; f.next_ledge_ok = 0
    played.clear(); n = len(said)
    snap = f.snapshot(); f.probes(snap, time.perf_counter())
    return played[:], [s for s, _ in said[n:]]
# flat open ground: nothing
me.geometry = []; me.floor_gaps = []
p, s = probe(); assert "alert" not in p and not s, (p, s)
# knee-high crate 1 m ahead: jump over
me.geometry = [(100, 160, -90, -40)]
p, s = probe(); print("crate:", p, s); assert "alert" in p and s == ["Jump over"]
# tall wall: no jump cue (wall clicks handle it)
me.geometry = [(100, 160, -90, 300)]
p, s = probe(); assert not s, s
# gap with ground beyond (jumpable)
me.geometry = []; me.floor_gaps = [(80, 220)]
p, s = probe(); print("gap:", p, s); assert s == ["Jump the gap"]
# cliff: no ground within reach -> ledge warning, not jump
me.floor_gaps = [(80, 2000)]
p, s = probe(); assert "alert" in p and not s, (p, s)
# standing still: no cues
me.Velocity = NS(X=0, Y=0, Z=0); me.floor_gaps = [(80, 220)]
p, s = probe(); assert not p and not s, (p, s)
# jump cues off
me.Velocity = NS(X=300, Y=0, Z=0); f.s.jump = False
me.geometry = [(100, 160, -90, -40)]; me.floor_gaps = []
p, s = probe(); assert not s, s
f.s.jump = True
print("4b. jump cues OK")
m.on_disable()
print("ALL ROUND 4 TESTS OK")

