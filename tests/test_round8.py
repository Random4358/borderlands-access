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
FAKE["ItemCardGFxObject"] = [("SetItemCardEx", [("WPC", "WillowPlayerController"), ("InventoryItem", "WillowInventory"),
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



# ================================================================ round 8: continuous object sounds
from array import array
from bl2_access import audio as A
from bl2_access.audio import audio as eng
from bl2_access.object_sounds import objects as OS

def samples(b):
    a = array("h"); a.frombytes(b); return a
def energy(b):
    a = samples(b); l = sum(abs(a[i]) for i in range(0, len(a), 2)); r = sum(abs(a[i]) for i in range(1, len(a), 2)); return l, r

# --- the loops join without clicks: every segment starts and ends at (nearly) zero, for every kind
def max_step(a, ch):
    return max(abs(a[i + 2] - a[i]) for i in range(ch, len(a) - 2, 2))
for kind in A.LOOPS:
    n = A.loop_length(kind)
    for step in range(n):
        for behind in (False, True):
            # next segment also moves the sound a little, as it does while you turn
            a = samples(A.loop_segment(kind, step, 0.3, 0.8, behind))
            b = samples(A.loop_segment(kind, step + 1, 0.4, 0.7, behind))
            assert len(a) == 2 * A.SEG_N
            for ch in (0, 1):
                join = abs(b[ch] - a[-2 + ch])
                inside = max(max_step(a, ch), max_step(b, ch))
                assert join <= inside * 1.05 + 50, (kind, step, behind, ch, join, inside)
l, r = energy(A.loop_segment("weapon3", 0, 0.9, 0.8, False)); assert r > 3 * l          # panned right
l2, r2 = energy(A.loop_segment("weapon3", 0, -0.9, 0.8, False)); assert l2 > 3 * r2     # panned left
front = sum(energy(A.loop_segment("container", 0, 0, 0.8, False))); back = sum(energy(A.loop_segment("container", 0, 0, 0.8, True)))
assert back < front                                                                  # muffled behind you
fi = samples(A.loop_segment("ammo", 0, 0, 0.8, False, 1)); assert max(abs(x) for x in fi[:40]) < 300   # fade in
# each kind sounds different (different fundamentals / patterns)
sigs = {k: (A.LOOPS[k][0][0][0], len(A.LOOPS[k][0]), tuple(A.LOOPS[k][1])) for k in A.LOOPS}
assert len(set(sigs.values())) == len(sigs)
print("loop sounds OK")

# --- fake output streams (nothing plays on the test machine)
class FakeStream:
    def __init__(s): s.q = []; s.fed = []; s.stops = 0
    def ahead(s): return len(s.q) * A.SEG
    def feed(s, b): s.q.append(b); s.fed.append(b)
    def stop(s): s.q = []; s.stops += 1
    def play_out(s): s.q = s.q[1:]   # one segment finishes
eng.streams = [FakeStream() for _ in range(A.STREAMS)]; eng.ok = True

def cls(name, supers=()):
    chain = [NS(Name=name)] + [NS(Name=s) for s in supers]
    return NS(Name=name, _superfields=lambda: chain, _properties=lambda: [])
class Actor:
    def __init__(s, kind, name, loc, **kw):
        s.Class = cls(kind, ["Actor"]); s.Name = name; s.Location = NS(X=loc[0], Y=loc[1], Z=loc[2])
        s.bDeleteMe = False; s.bHidden = False; s._p = f"Glacial_P.TheWorld:PersistentLevel.{name}"
        for k, v in kw.items(): setattr(s, k, v)
    def _path_name(s): return s._p
def pickup(name, inv_cls, defname, loc):
    inv = NS(Class=cls(inv_cls), Name=name, GetShortHumanReadableName=lambda: name,
             DefinitionData=NS(ItemDefinition=NS(Name=defname)))
    return Actor("WillowPickup", name.replace(" ", ""), loc, Inventory=inv)
def thing(name, defname, loc, **kw):
    return Actor("WillowInteractiveObject", name, loc, InteractiveObjectDefinition=NS(Name=defname), **kw)

smg = pickup("Bandit SMG", "WillowWeapon", "SMG_Bandit", (300, 300, 0))       # front right, 4 m
shield = pickup("Absorbing Shield", "WillowShield", "Shield_Absorb", (700, 0, 0))
cash = pickup("Money", "WillowUsableItem", "Money_Pile", (200, -200, 0))      # front left, 3 m
echo = pickup("ECHO Recorder", "WillowMissionItem", "MissionItem_Echo", (1300, 0, 0))   # quest item, far-ish
far = pickup("Far Gun", "WillowWeapon", "AR_Far", (3000, 0, 0))               # beyond 15 m
chest = thing("Chest1", "IO_Chest_Red", (-400, 0, 0), bIsUsable=True)        # behind you
opened = thing("Chest2", "IO_Chest_Red", (100, 100, 0), bIsUsable=False)
door = thing("Door1", "IO_Door_Bunker", (600, -600, 0))
barrel = thing("Barrel", "IO_FireBarrel", (150, 0, 0))                        # "Other": no sound
objects.clear()
objects["WillowPickup"] = [smg, shield, cash, echo, far]
objects["WillowInteractiveObject"] = [chest, opened, door, barrel]

class Pawn:
    def __init__(s):
        s.Name = "me"; s.Location = NS(X=0, Y=0, Z=0); s.Class = cls("WillowPlayerPawn", ["Pawn"])
        s.BaseEyeHeight = 0; s.NextPawn = None; s.Velocity = NS(X=0, Y=0, Z=0); s.bDeleteMe = False; s.bHidden = False
        s.Controller = None; s.Weapon = None; s.CylinderComponent = NS(CollisionHeight=90)
    def GetHealth(s): return 100
    def GetMaxHealth(s): return 100
    def IsEnemy(s, o): return False
    def FastTrace(s, e, st): return True
me = Pawn()
focus = NS(movie=None)
class PC:
    def __init__(s):
        s.Pawn = me; s.Rotation = NS(Pitch=0, Yaw=0, Roll=0); s.PlayerInput = None
        s.WorldInfo = NS(PawnList=me, GetMapName=lambda b: "Glacial_P", Pauser=None, GRI=NS())
        s.GFxUIManager = NS(FindFocusMovie=lambda: focus.movie)
    def LineOfSightTo(s, p): return True
    def SetRotation(s, r): s.Rotation = r
world.pc = PC()
f = m.feats
# features that would otherwise make sounds/speech of their own
for o in ("opt_radar", "opt_npc_sounds", "opt_npc_talk", "opt_walls", "opt_ledges", "opt_jump", "opt_low_health", "opt_targeting"):
    getattr(m, o).value = False
m.opt_object_max.value = 4; m.opt_object_range.value = 15
for o in ("opt_loot_sounds", "opt_container_sounds", "opt_interactive_sounds", "opt_quest_item_sounds"):
    getattr(m, o).value = True
m.controls.menus.open.clear()

def tick():
    m.hooks._last_tick = 0; m.hooks.on_tick(None, None, None, None)

tick()
kinds = {src.key.split(".")[-1]: src.kind for src in OS.sources.values()}
print("playing:", kinds)
assert kinds == {"ECHORecorder": "quest", "Money": "money", "BanditSMG": "weapon1", "Chest1": "container"}, kinds
assert "Chest2" not in kinds and "Barrel" not in kinds and "FarGun" not in kinds
# every playing stream is queued ahead, starts with a fade in, and is panned to its object
for src in OS.sources.values():
    st = eng.streams[src.slot]
    assert st.ahead() >= 0.2 - 1e-9, st.ahead()
smg_st = eng.streams[OS.sources[smg._p].slot]; cash_st = eng.streams[OS.sources[cash._p].slot]
l, r = energy(smg_st.fed[-1]); assert r > l, (l, r)          # SMG is to the right
l, r = energy(cash_st.fed[-1]); assert l > r, (l, r)         # money to the left
assert OS.sources[chest._p].behind                           # chest behind: muffled
# continuous: as segments finish, new ones are queued without restarting (no fade in again)
n = len(smg_st.fed)
for _ in range(10):
    for st in eng.streams: st.play_out()
    tick()
assert len(smg_st.fed) >= n + 10 and smg_st.stops == 0
assert samples(smg_st.fed[-1])[:40].tolist() != [0] * 40
# turning around moves the sound: SMG ends up on the left
world.pc.Rotation = NS(Pitch=0, Yaw=32768, Roll=0)
for st in eng.streams: st.play_out(); st.play_out(); st.play_out()
tick()
l, r = energy(smg_st.fed[-1]); assert l > r, ("after turning", l, r)
world.pc.Rotation = NS(Pitch=0, Yaw=0, Roll=0)
print("directional + continuous OK")

# picking an item up: its sound fades out and the next nearest takes the free stream
before = dict(OS.sources)
objects["WillowPickup"].remove(cash); del cash.Location
for st in eng.streams: st.play_out()
tick()
assert cash._p not in OS.sources
last = samples(cash_st.fed[-1]); assert max(abs(x) for x in last[-40:]) < 300   # faded out, not cut
OS.next_scan = 0; tick()
kinds = {src.key.split(".")[-1]: src.kind for src in OS.sources.values()}
assert kinds.get("AbsorbingShield") == "item1" and len(kinds) == 4, kinds
# opening the chest: its sound stops at the next scan
chest.bIsUsable = False; OS.next_scan = 0; tick()
assert chest._p not in OS.sources
OS.next_scan = 0; tick()
kinds = {src.key.split(".")[-1]: src.kind for src in OS.sources.values()}
assert kinds.get("Door1") == "interactive", kinds
print("pickup / opened container OK")

# menus: every object sound fades out; nothing is fed while the menu is up
focus.movie = NS(Name="StatusMenuExGFxMovie_0", Class=cls("StatusMenuExGFxMovie", ["GFxMoviePlayer"]))
tick(); assert not OS.sources
counts = [len(st.fed) for st in eng.streams]
for _ in range(5):
    for st in eng.streams: st.play_out()
    tick()
assert [len(st.fed) for st in eng.streams] == counts
focus.movie = None; OS.next_scan = 0; tick(); assert OS.sources
# options: each type can be switched off; all off = silence
m.opt_loot_sounds.value = False; OS.next_scan = 0
for st in eng.streams: st.play_out(); st.play_out(); st.play_out()
tick()
assert all(src.kind.rstrip("0123456789") not in ("weapon", "item", "money", "ammo", "health", "loot") for src in OS.sources.values()), [s.kind for s in OS.sources.values()]
for o in ("opt_container_sounds", "opt_interactive_sounds", "opt_quest_item_sounds"):
    getattr(m, o).value = False
tick(); assert not OS.sources
m.opt_loot_sounds.value = True; m.opt_object_max.value = 2; OS.next_scan = 0; tick()
assert len(OS.sources) == 2
print("menus + options OK")
f.rescan_pois(); print("summary:", said[-1][0]); assert "Object sounds:" in said[-1][0]
m.on_disable()
assert not OS.sources
print("ALL ROUND 8 TESTS OK")
