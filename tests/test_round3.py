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
m.opt_enemy_sound.value = "Radar beeps"  # these checks are for the beep radar

def call(cls, fn, obj, kind=Type.PRE, **args):
    a = NS(**args); props = [NS(Name=k) for k in args]
    a._type = NS(_properties=lambda: props)
    hooked[(f"WillowGame.{cls}:{fn}", kind)](obj, a, None, None)

# ---------------------------------------------------------------- 1. character descriptions
def namedef(path, **fields):
    return NS(_path_name=lambda: path, **fields)
objects["PlayerNameIdentifierDefinition"] = [
    namedef("Default__PlayerNameIdentifierDefinition"),
    namedef("GD_Siren_Streaming.NameId_Siren", LocalizedCharacterName="Maya",
            LocalizedCharacterDescription="A siren with phase powers.",
            LocalizedActionSkillDescription="Phaselock", LocalizedPreferredWeaponDescription="SMGs and elemental guns."),
    namedef("GD_Lilac_PlayerClass.NameId_Lilac", LocalizedCharacterDescription="A raging psycho.",
            LocalizedPreferredWeaponDescription="Melee and buzz axes."),
]
csm = NS(Name="CharacterSelectionReduxGFxMovie_0")
def standin(p): call("CharacterSelectionReduxGFxMovie", "UpdatePlayerStandIn", csm, PlayerIndex=0, WPC=None, SaveGame=NS(Name=p))
def select(i): call("CharacterSelectionReduxGFxMovie", "SetSelectedCharacterIndex", csm, PlayerIndex=0, NewSelectedIndex=i)
select(2); standin("Profile_Siren")
print("siren:", said[-2:])
assert said[-2] == ("Maya, the Siren", True)
assert said[-1] == ("A siren with phase powers. Action skill: Phaselock. Preferred weapons: SMGs and elemental guns", False)
select(5); standin("Profile_LilacPlayerClass")
assert said[-2][0] == "Krieg, the Psycho" and said[-1][0].startswith("A raging psycho.") and said[-1][1] is False
n = len(said); select(2)          # revisit: instant name + cached details, both again
assert [s for s, _ in said[n:]] == ["Maya, the Siren", said[-1][0]] and said[-1][0].startswith("A siren")
select(3); standin("Profile_Mercenary")   # no definition loaded for this class: name only, no crash
assert said[-1] == ("Salvador, the Gunzerker", True)
reader.read_descriptions = False
n = len(said); select(5); assert said[n:] == [("Krieg, the Psycho", True)]
reader.read_descriptions = True
print("1. character descriptions OK")

# ---------------------------------------------------------------- 2. silence while a menu is open
class Pawn:
    def __init__(s, name, loc, player=False, hostile=True, hp=100):
        s.Name = name; s.Location = NS(X=loc[0], Y=loc[1], Z=loc[2]); s.hp = hp
        s.Class = NS(Name="WillowPlayerPawn" if player else "WillowAIPawn"); s.hostile = hostile
        s.BaseEyeHeight = 60; s.NextPawn = None; s.Velocity = NS(X=0, Y=0, Z=0); s.bDeleteMe = False; s.bHidden = False
        s.Controller = None; s.AIClass = NS(DefaultDisplayName=name); s.Weapon = None
        s.CylinderComponent = NS(CollisionHeight=90)
    def GetHealth(s): return s.hp
    def GetMaxHealth(s): return 100
    def FastTrace(s, end, start): return True
    def IsEnemy(s, other): return getattr(other, "hostile", True)
me = Pawn("me", (0, 0, 0), player=True, hp=10)
bandit = Pawn("Bandit", (800, 0, 60))
claptrap = Pawn("Claptrap", (300, 200, 60), hostile=False)
me.NextPawn = bandit; bandit.NextPawn = claptrap
focus = NS(movie=None)
class PC:
    def __init__(s):
        s.Pawn = me; s.Rotation = NS(Pitch=0, Yaw=0, Roll=0); s.PlayerInput = None
        s.WorldInfo = NS(PawnList=me, GetMapName=lambda b: "Glacial_P", Pauser=None)
        s.GFxUIManager = NS(FindFocusMovie=lambda: focus.movie)
    def LineOfSightTo(s, p): return True
    def SetRotation(s, r): s.Rotation = r
world.pc = PC()
f = m.feats
def tick():
    m.hooks._last_tick = 0
    m.hooks.on_tick(None, None, None, None)
played.clear(); tick(); time.sleep(0.05); tick()
assert "radar" in played and "alert" in played, played        # in the world: radar + heartbeat
# a) a known menu is open
inv = NS(Class=NS(Name="StatusMenuExGFxMovie"), Name="StatusMenuExGFxMovie_0", _path_name=lambda: "inv")
m.controls.menus.opened(inv)
played.clear(); f.next_ping.clear(); f.next_heartbeat = 0; tick()
assert not [g for g in played if g in ("radar", "alert", "nav", "target", "beacon")], played
m.controls.menus.closed(inv)
# b) menu was deleted without a close call -> pruned, sounds resume
m.controls.menus.opened(inv); m.controls.menus.ptrs["inv"] = lambda: None
played.clear(); f.next_ping.clear(); f.next_heartbeat = 0; tick()
assert "radar" in played, played
# c) the game is paused
world.pc.WorldInfo.Pauser = NS(Name="pauser")
played.clear(); f.next_ping.clear(); f.next_heartbeat = 0; tick()
assert not [g for g in played if g in ("radar", "alert")], played
world.pc.WorldInfo.Pauser = None
# d) an unknown menu holds input focus; the HUD does not count
focus.movie = NS(Class=NS(Name="SomeNewMenuGFxMovie"))
played.clear(); f.next_ping.clear(); f.next_heartbeat = 0; tick()
assert not [g for g in played if g in ("radar", "alert")], played
focus.movie = NS(Class=NS(Name="WillowHUDGFxMovie"))
played.clear(); f.next_ping.clear(); f.next_heartbeat = 0; tick()
assert "radar" in played, played
focus.movie = None
print("2. silence in menus OK")

# ---------------------------------------------------------------- 3. scanner categories
def actor(cls, loc, defn=None, inv=None, path=None):
    a = NS(Class=NS(Name=cls), Location=NS(X=loc[0], Y=loc[1], Z=loc[2]), bDeleteMe=False)
    if defn is not None:
        a.InteractiveObjectDefinition = NS(Name=defn)
    if inv is not None:
        a.Inventory = inv
    p = path or f"Glacial_P.TheWorld:PersistentLevel.{cls}_{id(a)}"
    a._path_name = lambda: p
    return a
def item(cls, defn, name):
    return NS(Class=NS(Name=cls), DefinitionData=NS(ItemDefinition=NS(Name=defn)), GetShortHumanReadableName=lambda: name)
objects["WillowInteractiveObject"] = [
    actor("WillowInteractiveObject", (500, 0, 0), "InteractiveObj_LootChest_Red"),
    actor("WillowInteractiveObject", (200, 0, 0), "IO_AmmoCrate_01"),
    actor("WillowInteractiveObject", (900, 900, 0), "InteractiveObj_FastTravelStation"),
    actor("WillowInteractiveObject", (100, -300, 0), "InteractiveObj_Door_Industrial"),
    actor("WillowInteractiveObject", (50, 50, 0), "IO_MissionEcho_Claptrap"),
    actor("WillowInteractiveObject", (0, 0, 0), "InteractiveObj_LootChest_Red", path="Default__WillowInteractiveObject"),
]
objects["WillowVendingMachineBase"] = [actor("WillowVendingMachine", (700, 0, 0), "VendingMachine_Guns")]
objects["WillowPickup"] = [
    actor("WillowPickup", (150, 0, 0), inv=item("WillowWeapon", "WT_Bandit_SMG", "Bandit SMG")),
    actor("WillowPickup", (160, 0, 0), inv=item("WillowUsableItem", "AmmoDrop_Pistol", "Pistol Ammo")),
    actor("WillowPickup", (170, 0, 0), inv=item("WillowUsableItem", "Money_Pile", "$15")),
    actor("WillowPickup", (180, 0, 0), inv=item("WillowShield", "Shield_Absorb", "Absorbing Shield")),
    actor("WillowPickup", (190, 0, 0), inv=None),
]
said.clear()
f.cycle_category(1)
print("first category:", said[-1][0])
assert said[-1][0].startswith("Quest objectives, 1 item. Nearest: Mission Echo Claptrap"), said[-1]
f.cycle_category(1); assert said[-1][0].startswith("People, 1 item. Nearest: Claptrap"), said[-1]
f.cycle_category(1); assert said[-1][0].startswith("Weapons and gear, 2 items. Nearest: Bandit SMG"), said[-1]
f.cycle_poi(1); assert said[-1][0].startswith("Absorbing Shield,") and said[-1][0].endswith("2 of 2"), said[-1]
f.cycle_poi(1); assert said[-1][0].startswith("Bandit SMG,") and said[-1][0].endswith("1 of 2"), said[-1]
for expect in ("Ammo and health", "Money", "Containers", "Vendors", "Travel", "Doors and switches"):
    f.cycle_category(1); assert said[-1][0].startswith(expect + ","), (expect, said[-1])
cont = f.categories["Containers"]
assert [p.name for p in cont] == ["Ammo Crate", "Loot Chest Red"], [p.name for p in cont]
f.cycle_category(1); assert said[-1][0].startswith("Quest objectives,")        # wraps around
f.cycle_category(-1); assert said[-1][0].startswith("Doors and switches,")
f.rescan_pois(); print("summary:", said[-1][0])
assert said[-1][0].startswith("Nearby: 1 quest objectives, 1 people, 2 weapons and gear")
# beacon works on the selected category item
f.cycle_category(1); f.cycle_poi(1); f.toggle_beacon(); assert f.beacon
# controller combos map to the new actions
assert m.controls.COMBOS["XboxTypeS_DPad_Right"] == "cat_next" and m.controls.COMBOS["XboxTypeS_LeftTrigger"] == "beacon"
print("3. scanner categories OK")
m.on_disable()
print("ALL ROUND 3 TESTS OK")


