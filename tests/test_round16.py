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



# ================================================================ round 16: line tests that work whichever trace function the game supports
import math
import bl2_access.game as G
from bl2_access import navigation as NAV
from bl2_access import trace as T

notes = []
T.note = lambda text: notes.append(text)
def reset():
    G.TRACE_MODE = None; G.FLOOR_SEEN = False; G._trace_notes.clear(); notes.clear()

def world_hit(start, end):
    """A floor at z=-90 and a crate 2 m ahead (x 150..250, up to 60 cm high)."""
    for i in range(41):
        t = i / 40
        x = start.X + (end.X - start.X) * t; z = start.Z + (end.Z - start.Z) * t
        if z <= -90 or (150 <= x <= 250 and z <= -30):
            return True
    return False

class BrokenFast:          # FastTrace errors out; Trace works
    def __init__(s): s.Location = NS(X=0.0, Y=0.0, Z=0.0)
    def FastTrace(s, end, start): raise TypeError("bad arguments")
    def Trace(s, hl, hn, end, start, actors): return (NS(Name="WorldInfo") if world_hit(start, end) else None, hl, hn, None)
class BlindFast(BrokenFast):  # FastTrace runs but never sees anything (wrong collision channel)
    def FastTrace(s, end, start): return True
class GoodFast(BrokenFast):
    def FastTrace(s, end, start): return not world_hit(start, end)
class Nothing:
    def __init__(s): s.Location = NS(X=0.0, Y=0.0, Z=0.0)

# FastTrace errors -> Trace used, and the error is logged
reset(); p = BrokenFast()
assert G.fast_trace(p, (0, 0, 0), (0, 0, -500)) is False and G.TRACE_MODE == "trace"
assert G.fast_trace(p, (0, 0, 0), (100, 0, 0)) is True
assert any("line test fast failed: TypeError" in n for n in notes)
# FastTrace blind -> the self-check notices it can't see the floor and switches to Trace
reset(); p = BlindFast()
G.fast_trace(p, (0, 0, 0), (100, 0, 0)); assert G.TRACE_MODE == "fast"     # first guess
print("self-check:", G.trace_self_test(p)); assert G.TRACE_MODE == "trace" and G.FLOOR_SEEN
assert G.fast_trace(p, (0, 0, -60), (300, 0, -60)) is False                    # now sees the crate
# a working FastTrace is kept
reset(); p = GoodFast(); assert G.trace_self_test(p) == "fast"
# nothing works: None (callers fall back), no crash
reset(); assert G.fast_trace(Nothing(), (0, 0, 0), (1, 0, 0)) is None
# in the air at spawn: no floor under you yet -> keep going, check again later
class Airborne(GoodFast):
    def FastTrace(s, end, start): return True
reset(); a = Airborne(); a.Trace = lambda hl, hn, e, st, ac: (None, hl, hn, None)
assert "will check again" in G.trace_self_test(a) and not G.FLOOR_SEEN
print("trace selection OK")

# --- in the features: the jump cue fires with a game where only Trace sees the world
reset()
class Pawn(BlindFast):
    def __init__(s):
        super().__init__(); s.Name = "me"; s.Class = NS(Name="WillowPlayerPawn"); s.BaseEyeHeight = 60
        s.CylinderComponent = NS(CollisionHeight=90); s.Velocity = NS(X=300, Y=0, Z=0); s.NextPawn = None
        s.bDeleteMe = False; s.bHidden = False; s.Controller = None; s.Weapon = None
    def GetHealth(s): return 100
    def GetMaxHealth(s): return 100
    def IsEnemy(s, o): return False
me = Pawn()
world.pc = NS(Pawn=me, Rotation=NS(Pitch=0, Yaw=0, Roll=0), PlayerInput=None, SetRotation=lambda r: None,
              WorldInfo=NS(PawnList=me, GetMapName=lambda b: "Glacial_P", Pauser=None, GRI=NS()),
              GFxUIManager=NS(FindFocusMovie=lambda: None), LineOfSightTo=lambda p: True)
for o in ("opt_radar", "opt_npc_sounds", "opt_npc_talk", "opt_walls", "opt_ledges", "opt_low_health", "opt_targeting",
          "opt_loot_sounds", "opt_container_sounds", "opt_interactive_sounds", "opt_quest_item_sounds", "opt_interact"):
    getattr(m, o).value = False
m.opt_jump.value = True; m.opt_speak_jump.value = True; m.opt_jump_height.value = 100
objects.clear(); m.controls.menus.open.clear()
f = m.feats; f.had_pawn = False; f.last_map = ""
def tick():
    m.hooks._last_tick = 0; m.hooks.on_tick(None, None, None, None)
said.clear(); played.clear(); tick()          # spawn: self-check picks Trace
assert G.TRACE_MODE == "trace", (G.TRACE_MODE, notes)
f.next_wall = 0; f.next_jump_ok = 0; tick()
print("jump:", played, [s for s, _ in said][-2:])
assert "alert" in played and said[-1][0] == "Jump over", (played, said)
print("jump cue with Trace OK")

# --- navigation mesh: "no path" doesn't switch it off; it's asked again 2 s later
asked = []
class Handle:
    def ClearConstraints(s): pass
    def SetFinalDestination(s, v): pass
    def FindPath(s): asked.append(1); return (len(asked) >= 2, None, 0)   # no path first, then a path
    def GetNextMoveLocation(s, v, arrive): return (True, NS(X=400.0, Y=100.0, Z=0.0))
class NavPC:
    NavigationHandle = Handle()
    def FindPathTo(s, v): return None
orig_find = us.find_class
us.find_class = lambda n: (NS(ClassDefaultObject=NS(TowardPoint=lambda h, g: True, AtLocation=lambda h, g, d, partial=False: True))
                           if n in ("NavMeshPath_Toward", "NavMeshGoal_At") else orig_find(n))
r = NAV.Route(); target = (2000.0, 0.0, 0.0)
p1 = r.next_point(NavPC(), (0, 0, 0), target, None, "g", 0.0, None)
p2 = r.next_point(NavPC(), (0, 0, 0), target, None, "g", 1.0, None)   # too soon: not asked again
p3 = r.next_point(NavPC(), (0, 0, 0), target, None, "g", 2.1, None)
us.find_class = orig_find
assert p1 == target and len(asked) == 2 and p3 == (400.0, 100.0, 0.0) and r.navmesh_ok is not False, (asked, p3, r.navmesh_ok)
assert any("will keep trying" in n for n in notes)
print("navigation mesh retry OK")
m.on_disable()
print("ALL ROUND 16 TESTS OK")
