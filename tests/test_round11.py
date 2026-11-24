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



# ================================================================ round 11: spoken settings menu, triple press, sound glossary
from bl2_access import audio as A
from bl2_access.mod_menu import modmenu
m.opt_menu_desc.value = False   # (help text after each entry is tested in round 23)
from unrealsdk.hooks import Block

replays = []
class PlayerInput:
    def InputKey(s, cid, key, ev, amount, gamepad): replays.append((key, ev))
class Pawn:
    def __init__(s):
        s.Name = "me"; s.Location = NS(X=0, Y=0, Z=0); s.Class = NS(Name="WillowPlayerPawn")
        s.BaseEyeHeight = 0; s.NextPawn = None; s.Velocity = NS(X=0, Y=0, Z=0); s.bDeleteMe = False; s.bHidden = False
        s.Controller = None; s.Weapon = None; s.CylinderComponent = NS(CollisionHeight=90)
    def GetHealth(s): return 100
    def GetMaxHealth(s): return 100
    def IsEnemy(s, o): return False
    def FastTrace(s, e, st): return True
me = Pawn()
world.pc = NS(Pawn=me, Rotation=NS(Pitch=0, Yaw=0, Roll=0), PlayerInput=PlayerInput(), SetRotation=lambda r: None,
              WorldInfo=NS(PawnList=me, GetMapName=lambda b: "Glacial_P", Pauser=None, GRI=NS()),
              GFxUIManager=NS(FindFocusMovie=lambda: None), LineOfSightTo=lambda p: True)
m.opt_modifier.value = "Back / View"
def tick():
    m.hooks._last_tick = 0; m.hooks.on_tick(None, None, None, None)
tick()
assert m.state.modifier == "XboxTypeS_Back"
ui = NS(Name="WillowUIInteraction_0")
def key(k, pressed=True):
    ev = EInputEvent.IE_Pressed if pressed else EInputEvent.IE_Released
    a = NS(ControllerId=0, Key=k, Event=ev); a._type = NS(_properties=lambda: [])
    return m.hooks.on_input(ui, a, None, None)
def tap(k):
    r1 = key(k, True); r2 = key(k, False); return r1, r2

# --- one tap of the modifier still reaches the game, just slightly later
replays.clear(); said.clear()
tap("XboxTypeS_Back")
tick(); assert replays == []                       # held back briefly
time.sleep(0.4); tick()
assert [r[0] for r in replays] == ["XboxTypeS_Back", "XboxTypeS_Back"] and not modmenu.is_open, replays
# two taps reach the game as two taps
replays.clear(); tap("XboxTypeS_Back"); time.sleep(0.1); tap("XboxTypeS_Back"); time.sleep(0.4); tick()
assert len(replays) == 4 and not modmenu.is_open
# a slow sequence isn't a triple press
replays.clear(); tap("XboxTypeS_Back"); time.sleep(0.4); tick(); tap("XboxTypeS_Back"); time.sleep(0.4); tick()
tap("XboxTypeS_Back"); time.sleep(0.4); tick()
assert not modmenu.is_open and len(replays) == 6
# holding the modifier for a shortcut isn't a tap
said.clear(); key("XboxTypeS_Back", True); key("XboxTypeS_Y", True); key("XboxTypeS_Y", False); key("XboxTypeS_Back", False)
time.sleep(0.4); tick(); assert not modmenu.is_open
print("single taps + shortcuts OK")

# --- triple press opens the settings; the game doesn't get those taps
replays.clear(); said.clear()
for _ in range(3):
    tap("XboxTypeS_Back"); time.sleep(0.05)
assert modmenu.is_open, said
time.sleep(0.4); tick(); assert replays == []
print("open:", said[-1][0][:160])
assert said[-1][0].startswith("Accessibility settings.") and "General group, 1 of" in said[-1][0]
assert m.controls.menus.world_sounds_paused()                # world quiet while the menu is up
group_names = [g[0] for g in modmenu.groups]
print("groups:", group_names)
assert group_names[0] == "General" and group_names[-1] == "Sound glossary and volumes"

# --- moving and changing
assert key("XboxTypeS_DPad_Down") == (Block, True)           # swallowed: the game doesn't see it
assert said[-1][0].startswith("Speech output,") and said[-1][0].endswith("2 of 7"), said[-1]
key("XboxTypeS_DPad_Up"); assert said[-1][0].startswith("Cue volume, 80 percent"), said[-1]
key("XboxTypeS_DPad_Right"); assert said[-1][0] == "81 percent" and m.opt_volume.value == 81
key("XboxTypeS_DPad_Left"); assert m.opt_volume.value == 80
key("XboxTypeS_DPad_Up"); assert said[-1][0].startswith("Diagnostic") or said[-1][0].startswith("Trace"), said[-1]  # wraps to the end
# dropdowns cycle; Y describes
key("XboxTypeS_RightShoulder")                               # Controller and menus
assert said[-1][0].startswith("Controller and menus group, 2 of"), said[-1]
assert said[-1][0].endswith("Controller modifier button, Back / View. 1 of 5")
key("XboxTypeS_Y"); assert "Hold this button" in said[-1][0] and "Choices:" in said[-1][0]
# bools toggle with A or left/right
key("XboxTypeS_DPad_Down"); before = m.opt_menu_sounds.value
key("XboxTypeS_A"); assert m.opt_menu_sounds.value == (not before) and said[-1][0] in ("on", "off")
key("XboxTypeS_DPad_Right"); assert m.opt_menu_sounds.value == before
# sliders stop at their limits
key("XboxTypeS_RightShoulder")                               # Enemy radar
while not modmenu.current.display_name.startswith("Radar max"):
    key("XboxTypeS_DPad_Down")
for _ in range(10):
    key("XboxTypeS_DPad_Right")
assert m.opt_radar_max.value == 6 and said[-1][0].startswith("Maximum"), said[-1]
key("XboxTypeS_X"); assert m.opt_radar_max.value == 3 and said[-1][0] == "Reset to 3"
# keyboard shortcuts for other actions do nothing while the menu is open
n = len(said); m.controls.run_action("enemies"); assert len(said) == n
print("navigation + values OK")

# --- sound glossary: every sound listed with what it means; volume 0..300% with a preview
key("XboxTypeS_LeftShoulder"); key("XboxTypeS_LeftShoulder"); key("XboxTypeS_LeftShoulder")   # wraps back
while modmenu.groups[modmenu.gi][0] != "Sound glossary and volumes":
    key("XboxTypeS_RightShoulder")
items = modmenu.groups[modmenu.gi][1]
assert len(items) == len(A.SOUNDS) == 33
assert said[-1][0].endswith("Enemy tone, off target volume, 100 percent. 1 of 33"), said[-1]
played.clear()
key("XboxTypeS_DPad_Right"); assert said[-1][0] == "110 percent" and A.GAINS["enemy"] == 1.1 and "ui" in played
key("XboxTypeS_Y"); assert said[-1][0].startswith("Steady tone for each nearby enemy") and "0 to 300" in said[-1][0]
for _ in range(25):
    key("XboxTypeS_DPad_Right")
assert m.SOUND_OPTS["enemy"].value == 300 and A.GAINS["enemy"] == 3.0
for _ in range(33):
    key("XboxTypeS_DPad_Left")
assert m.SOUND_OPTS["enemy"].value == 0 and said[-1][0].startswith("Minimum")
played.clear(); key("XboxTypeS_A"); assert "ui" in played                # A plays the sound (silent at 0%)
key("XboxTypeS_X"); assert m.SOUND_OPTS["enemy"].value == 100
# moving onto a sound plays it so you hear what it is
played.clear(); key("XboxTypeS_DPad_Down"); assert "ui" in played and said[-1][0].startswith("Enemy tone, nearly on target")
# volumes reach the sounds through the options each tick
m.SOUND_OPTS["ui_select"].value = 250; tick(); assert A.GAINS["ui_select"] == 2.5
m.SOUND_OPTS["ui_select"].value = 100; tick()
print("sound glossary OK")

# --- closing: B, or the modifier; settings saved
saves.clear(); key("XboxTypeS_B")
assert not modmenu.is_open and saves and said[-1][0] == "Settings saved and closed"
for _ in range(3):
    tap("XboxTypeS_Back"); time.sleep(0.05)
assert modmenu.is_open
saves.clear(); key("XboxTypeS_Back"); key("XboxTypeS_Back", False)
assert not modmenu.is_open and saves
time.sleep(0.4); replays.clear(); tick(); assert replays == []       # the closing press isn't passed on
# keyboard: Equals opens and closes; arrow keys work inside
bind = [b for b in m.KEYBINDS if b.key == "Equals"][0]
bind.callback(); assert modmenu.is_open
pos = modmenu.ii; key("Down"); assert modmenu.ii == (pos + 1) % 33 and said[-1][0].endswith(f"{modmenu.ii + 1} of 33"), said[-1]  # reopens where you left off
time.sleep(0.3); bind.callback(); assert not modmenu.is_open
# a different modifier (left stick click) works the same way
m.opt_modifier.value = "Left stick click"; tick()
for _ in range(3):
    tap(m.state.modifier); time.sleep(0.05)
assert modmenu.is_open; key("XboxTypeS_B")
m.on_disable(); assert not modmenu.is_open
print("ALL ROUND 11 TESTS OK")
