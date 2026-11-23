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


# ================================================================ round 6: inventory / skill tree panel reader
from bl2_access.panel_reader import panels, describe, snapshot

def cls(name, supers=()):
    chain = [NS(Name=name)] + [NS(Name=s) for s in supers]
    return NS(Name=name, _superfields=lambda: chain, _properties=lambda: [])

def obj_class(name, prop_names, supers=()):
    c = cls(name, supers)
    c._properties = lambda: [NS(Name=p, Class=NS(Name="ObjectProperty")) for p in prop_names]
    return c

def item(kind, name, level, path):
    return NS(Class=cls(kind), Name=path, _path_name=lambda: path,
              GetShortHumanReadableName=lambda: name, GetExpLevel=lambda: level)

smg = item("WillowWeapon", "Bandit SMG", 5, "Inv.WillowWeapon_1")
shield = item("WillowShield", "Absorbing Shield", 6, "Inv.WillowShield_2")
relic = item("WillowArtifact", "Vitality Relic", 7, "Inv.WillowArtifact_3")
skill1 = NS(Class=cls("SkillDefinition"), Name="Ward", _path_name=lambda: "Skills.Ward",
            SkillName="Ward", SkillDescription="Increases your [skill]shield capacity[-skill].")
skill2 = NS(Class=cls("SkillDefinition"), Name="Accelerate", _path_name=lambda: "Skills.Accelerate",
            SkillName="Accelerate", SkillDescription="Increases gun damage.")

# Inventory panel object (a GFxObject) holds the highlighted item; the menu movie holds the panel.
panel = NS(Name="StatusMenuInventoryPanelGFxObject_0", SelectedThing=smg, WeaponOwner=None,
           Class=obj_class("StatusMenuInventoryPanelGFxObject", ["SelectedThing", "WeaponOwner"], ["GFxObject"]))
skills = NS(Name="SkillTreeGFxObject_0", HighlightedSkill=skill1,
            Class=obj_class("SkillTreeGFxObject", ["HighlightedSkill"], ["GFxObject"]))
movie = NS(Name="StatusMenuExGFxMovie_0", InventoryPanel=panel, SkillTree=skills, OwnerPC=None,
           Class=obj_class("StatusMenuExGFxMovie", ["InventoryPanel", "SkillTree", "OwnerPC"], ["GFxMoviePlayer"]))
_path = {"InventoryPanel": panel}
movie._path_name = lambda: "StatusMenuExGFxMovie_0"

focus = NS(movie=movie)
world.pc = NS(Pawn=None, GFxUIManager=NS(FindFocusMovie=lambda: focus.movie), WorldInfo=NS(Pauser=None))
m.controls.menus.opened(movie)

def press(key):
    call("GFxMoviePlayer", "FilterButtonInput", NS(Name="StatusMenuExGFxMovie_0"), Type.PRE,
         ControllerId=0, ButtonName=key, InputEvent=EInputEvent.IE_Pressed)

# describe() for each kind
assert describe(smg) == "Bandit SMG, level 5"
assert describe(skill1) == "Ward. Increases your shield capacity."
print("describe OK")

# moving the highlight in the inventory: the panel's SelectedThing changes -> it's read
said.clear()
press("XboxTypeS_DPad_Down"); panel.SelectedThing = shield
time.sleep(0.06); m.hooks._last_tick = 0; m.hooks.on_tick(None, None, None, None)
print("inventory move:", said[-1]); assert said[-1][0] == "Absorbing Shield, level 6"
time.sleep(0.03)
press("XboxTypeS_DPad_Down"); panel.SelectedThing = relic
time.sleep(0.06); m.hooks._last_tick = 0; m.hooks.on_tick(None, None, None, None)
assert said[-1][0] == "Vitality Relic, level 7", said[-1]
# no change -> silence (no repeats)
n = len(said); time.sleep(0.03)
press("XboxTypeS_DPad_Down")
time.sleep(0.06); m.hooks._last_tick = 0; m.hooks.on_tick(None, None, None, None)
assert len(said) == n, said[n:]
# re-read with F8 / Back+B path
m.controls._repeat(); assert said[-1][0] == "Vitality Relic, level 7"
# skill tree: a different panel's highlighted skill changes
time.sleep(0.03)
press("XboxTypeS_DPad_Right"); skills.HighlightedSkill = skill2
time.sleep(0.06); m.hooks._last_tick = 0; m.hooks.on_tick(None, None, None, None)
print("skill move:", said[-1]); assert said[-1][0] == "Accelerate. Increases gun damage."
# menus with a dedicated reader are left alone
focus.movie = NS(Name="FrontendGFxMovie_0", Class=obj_class("FrontendGFxMovie", ["Thing"], ["GFxMoviePlayer"]), Thing=smg)
n = len(said); time.sleep(0.03)
press("XboxTypeS_DPad_Down"); time.sleep(0.06); m.hooks._last_tick = 0; m.hooks.on_tick(None, None, None, None)
assert len(said) == n
# menu closed mid-press: no crash, no speech
focus.movie = movie; time.sleep(0.03)
press("XboxTypeS_DPad_Down"); focus.movie = None
time.sleep(0.06); m.hooks._last_tick = 0; m.hooks.on_tick(None, None, None, None)
assert len(said) == n
# snapshot budget: a huge menu doesn't read unbounded properties
big = NS(Name="big", Class=obj_class("BigGFxMovie", [f"P{i}" for i in range(2000)], ["GFxMoviePlayer"]))
for i in range(2000):
    setattr(big, f"P{i}", None)
assert len(snapshot(big)) <= 600
m.controls.menus.closed(movie)
m.on_disable()
print("ALL ROUND 6 TESTS OK")

