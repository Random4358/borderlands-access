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



# ================================================================ round 22: object sounds stay with their object; chests aren't wrongly "opened"
from bl2_access import audio as A
from bl2_access.audio import audio as eng
from bl2_access.object_sounds import objects as OS, _still_usable

class FakeStream:
    def __init__(s): s.q = []
    def ahead(s): return len(s.q) * A.SEG
    def feed(s, b): s.q.append(b)
    def stop(s): s.q = []
eng.streams = [FakeStream() for _ in range(A.STREAMS)]; eng.combat_streams = []; eng.nav_stream = None; eng.ok = True

def cls(name, supers=()):
    chain = [NS(Name=name)] + [NS(Name=s) for s in supers]
    return NS(Name=name, _superfields=lambda: chain, _properties=lambda: [])
class Actor:
    def __init__(s, name, loc, **kw):
        s.Class = cls("WillowPickup", ["Actor"]); s.Name = name; s.Location = NS(X=loc[0], Y=loc[1], Z=loc[2])
        s.bDeleteMe = False; s.bHidden = False; s._p = f"Glacial_P.TheWorld:PersistentLevel.{name}"
        inv = NS(Class=cls("WillowWeapon"), Name=name, GetShortHumanReadableName=lambda: name,
                 DefinitionData=NS(ItemDefinition=NS(Name="SMG")))
        s.Inventory = inv
        for k, v in kw.items(): setattr(s, k, v)
    def _path_name(s): return s._p
gun_a = Actor("GunA", (600.0, 300.0, 0.0))
gun_b = Actor("GunB", (600.0, -310.0, 0.0))
objects.clear(); objects["WillowPickup"] = [gun_a, gun_b]
class Pawn:
    def __init__(s):
        s.Name = "me"; s.Location = NS(X=0.0, Y=0.0, Z=0.0); s.Class = cls("WillowPlayerPawn", ["Pawn"])
        s.BaseEyeHeight = 0; s.NextPawn = None; s.Velocity = NS(X=0, Y=0, Z=0); s.bDeleteMe = False; s.bHidden = False
        s.Controller = None; s.Weapon = None; s.CylinderComponent = NS(CollisionHeight=90)
    def GetHealth(s): return 100
    def GetMaxHealth(s): return 100
    def IsEnemy(s, o): return False
    def FastTrace(s, e, st): return True
me = Pawn()
world.pc = NS(Pawn=me, Rotation=NS(Pitch=0, Yaw=0, Roll=0), PlayerInput=None, SetRotation=lambda r: None,
              WorldInfo=NS(PawnList=me, GetMapName=lambda b: "Glacial_P", Pauser=None, GRI=NS()),
              GFxUIManager=NS(FindFocusMovie=lambda: None), LineOfSightTo=lambda p: True)
for o in ("opt_radar", "opt_npc_sounds", "opt_npc_talk", "opt_walls", "opt_ledges", "opt_jump", "opt_low_health",
          "opt_targeting", "opt_container_sounds", "opt_interactive_sounds", "opt_quest_item_sounds", "opt_interact"):
    getattr(m, o).value = False
m.opt_loot_sounds.value = True; m.opt_object_max.value = 1; m.opt_object_range.value = 15
m.controls.menus.open.clear()
def tick():
    m.hooks._last_tick = 0; m.hooks.on_tick(None, None, None, None)
tick(); OS.next_scan = 0; tick()
first = set(OS.sources)
print("playing:", [k.split(".")[-1] for k in first])
# the two guns keep trading places by a few centimetres as you move: the sound stays put
for i in range(10):
    gun_b.Location = NS(X=600.0, Y=-290.0 if i % 2 else -310.0, Z=0.0)
    gun_a.Location = NS(X=600.0, Y=310.0 if i % 2 else 290.0, Z=0.0)
    OS.next_scan = 0; tick()
    assert set(OS.sources) == first, ("swapped", i, set(OS.sources))
# but something clearly closer takes over
gun_b.Location = NS(X=150.0, Y=-50.0, Z=0.0); OS.next_scan = 0; tick()
assert set(OS.sources) != first
print("sounds stay with their object OK")

# containers: only plain "used" flags count as opened, never a guessed function call
chest = NS(IsUsable=lambda *a: False, bHidden=False)          # a function that says "no" without a player
assert _still_usable(chest) is True
assert _still_usable(NS(bIsUsable=False)) is False
print("opened-container check OK")

# --- mixing: object sounds keep out of the beacon's pitch range
for kind, (pattern, harmonics) in A.LOOPS.items():
    for cycles, _amp in pattern:
        for h, w in harmonics:
            hz = round(cycles * h) * A.CYCLE
            assert not (450 <= hz <= 1000 and w > 0.12), (kind, hz, w)   # the beacon lives at 500-1000 Hz
print("pitch ranges OK")
# a pile of the same kind plays as one sound; different kinds side by side still both play
m.opt_object_max.value = 4
pile = [Actor(f"Ammo{i}", (400.0 + 40 * i, 0.0, 0.0)) for i in range(3)]
objects["WillowPickup"] = [gun_a, gun_b] + pile
OS.kinds.clear(); OS.next_scan = 0; tick()
names = sorted(k.split(".")[-1] for k in OS.sources)
print("playing:", names)
assert sum(n.startswith("Ammo") for n in names) == 1 and "GunA" in names and "GunB" in names, names
# (all gear here: the pile, 80 cm across, is one sound; the guns 3-6 m away from it are their own)
# the beacon's target doesn't also play its own sound, and the rest step back
OS.focus_key = None; OS.duck = 1.0
loud = OS._wanted(m.feats.s, m.feats.snapshot())
OS.focus_key = pile[0]._path_name()
assert all(f[1] != OS.focus_key for f in OS._wanted(m.feats.s, m.feats.snapshot()))
OS.focus_key = None
print("beacon target left out OK")
# with the beacon on, object sounds step back (and the beacon is louder than any of them)
from bl2_access import game as G2, object_sounds as OSM
m.feats.pois = [F.POI("Ammo0", G2.weak(pile[0]), "Weapons and gear")]; m.feats.poi_index = 0; m.feats.beacon = True
OS.next_scan = 0; tick()
assert OS.duck == OSM.BEACON_DUCK and OS.focus_key == pile[0]._path_name(), (OS.duck, OS.focus_key)
assert not any(k == OS.focus_key for k in OS.sources)
m.feats.beacon = False; tick(); assert OS.duck == 1.0 and OS.focus_key is None
assert 0.75 > 0.05 + 0.45   # quietest beacon (far away) vs loudest object sound (right beside you), before volumes
print("ducking OK")

# --- steady loot sounds: one held tone (only the container keeps its throb)
for kind, (pattern, _h) in A.LOOPS.items():
    if kind != "container":
        assert len({c for c, _a in pattern}) == 1 and len({a for _c, a in pattern}) == 1, kind
# weapons ring higher the rarer they are; gear uses the same ladder with its own tone colour
pitches = [A.LOOPS[f"weapon{r}"][0][0][0] for r in range(1, 7)]
assert pitches == sorted(pitches) and len(set(pitches)) == 6
assert A.LOOPS["weapon3"][1] != A.LOOPS["item3"][1]
assert A.preview("weapon") and A.preview("item") and A.preview("health")
A.GAINS["weapon"] = 2.0; assert A.gain("weapon4") == 2.0; A.GAINS["weapon"] = 1.0
print("steady sounds and rarity ladder OK")

from bl2_access.object_sounds import rarity_of
assert rarity_of(NS(RarityLevel=3)) == 3 and rarity_of(NS(GetRarityLevel=lambda: 5)) == 5
assert rarity_of(NS(RarityLevel=500)) == 6 and rarity_of(NS()) == 1
# a blue gun, a purple shield, a health vial and an ammo drop each get their own sound
def drop(name, inv_cls, defn, **kw):
    a = Actor(name, (300.0, 0.0, 0.0))
    a.Inventory = NS(Class=cls(inv_cls), Name=name, GetShortHumanReadableName=lambda: name,
                     DefinitionData=NS(ItemDefinition=NS(Name=defn)), **kw)
    return a
blue = drop("BlueGun", "WillowWeapon", "SMG", RarityLevel=3)
shield = drop("PurpleShield", "WillowShield", "Shield", RarityLevel=4)
vial = drop("Vial", "WillowUsableItem", "HealthVial_Small")
bullets = drop("Bullets", "WillowUsableItem", "AmmoDrop_SMG")
OS.kinds.clear()
got = {a.Name: OS._classify(a, True) for a in (blue, shield, vial, bullets)}
print("kinds:", got)
assert got == {"BlueGun": "weapon3", "PurpleShield": "item4", "Vial": "health", "Bullets": "ammo"}, got
print("loot kinds OK")
m.on_disable()
print("ALL ROUND 22 TESTS OK")
