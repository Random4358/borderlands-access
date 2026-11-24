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



# ================================================================ round 12: quiet menu sounds in cinematics, interaction prompts
from bl2_access import audio as A
from bl2_access.audio import audio as eng

def cls(name, supers=()):
    chain = [NS(Name=name)] + [NS(Name=s) for s in supers]
    return NS(Name=name, _superfields=lambda: chain, _properties=lambda: [])
focus = NS(movie=None)
world.pc = NS(Pawn=None, Rotation=NS(Pitch=0, Yaw=0, Roll=0), PlayerInput=None, SetRotation=lambda r: None,
              WorldInfo=NS(PawnList=None, GetMapName=lambda b: "Glacial_P", Pauser=None, GRI=NS()),
              GFxUIManager=NS(FindFocusMovie=lambda: focus.movie), LineOfSightTo=lambda p: True)
m.controls.menus.open.clear()
ui = NS(Name="WillowUIInteraction_0")
def key(k, pressed=True):
    ev = EInputEvent.IE_Pressed if pressed else EInputEvent.IE_Released
    a = NS(ControllerId=0, Key=k, Event=ev); a._type = NS(_properties=lambda: [])
    return m.hooks.on_input(ui, a, None, None)
def gfx(k, movie):
    a = NS(ControllerId=0, ButtonName=k, InputEvent=EInputEvent.IE_Pressed); a._type = NS(_properties=lambda: [])
    m.reader.on_button_input(movie, a)
def tick():
    m.hooks._last_tick = 0; m.hooks.on_tick(None, None, None, None)
m.opt_menu_sounds.value = True; tick()

# --- cinematic / loading screen: no character, nothing to choose -> silent
for screen in (None, NS(Name="WillowGFxMovieCinematic_0", Class=cls("WillowGFxMovieCinematic")),
               NS(Name="LoadingMovie_0", Class=cls("WillowLoadingMovie"))):
    focus.movie = screen
    played.clear(); time.sleep(0.03)
    key("XboxTypeS_DPad_Down"); key("XboxTypeS_DPad_Down", False); time.sleep(0.03)
    key("XboxTypeS_A"); key("XboxTypeS_A", False); time.sleep(0.03)
    if screen is not None:
        gfx("XboxTypeS_DPad_Up", screen); time.sleep(0.03)
    assert "ui" not in played, (screen and screen.Name, played)
print("silent in cinematics and loading screens OK")
# --- real menus still click: a menu we know, or a menu-type screen with focus
main = NS(Name="FrontendGFxMovie_0", Class=cls("FrontendGFxMovie", ["GFxMoviePlayer"])); main._path_name = lambda: "FrontendGFxMovie_0"
m.controls.menus.opened(main); focus.movie = main
played.clear(); time.sleep(0.03); gfx("XboxTypeS_DPad_Down", main)
assert "ui" in played, played
m.controls.menus.closed(main)
pause = NS(Name="PauseGFxMovie_0", Class=cls("SomePauseMenuGFxMovie")); focus.movie = pause
played.clear(); time.sleep(0.03); gfx("XboxTypeS_DPad_Down", pause); assert "ui" in played
m.opt_menu_sounds.value = False; tick(); played.clear(); time.sleep(0.03); gfx("XboxTypeS_DPad_Up", pause)
assert "ui" not in played                                    # the option still turns them off
m.opt_menu_sounds.value = True; tick(); focus.movie = None
print("menu sounds in real menus OK")

# --- interaction prompts
class Pawn:
    def __init__(s, name, loc, player=False):
        s.Name = name; s.Location = NS(X=loc[0], Y=loc[1], Z=loc[2]); s.player = player
        s.Class = cls("WillowPlayerPawn" if player else "WillowAIPawn", ["Pawn"]); s.AIClass = NS(DefaultDisplayName=name)
        s.BaseEyeHeight = 0; s.NextPawn = None; s.Velocity = NS(X=0, Y=0, Z=0); s.bDeleteMe = False; s.bHidden = False
        s.Controller = None; s.Weapon = None; s.CylinderComponent = NS(CollisionHeight=90)
    def GetHealth(s): return 100
    def GetMaxHealth(s): return 100
    def IsEnemy(s, o): return False
    def FastTrace(s, e, st): return True
class Actor:
    def __init__(s, kind, name, loc, **kw):
        s.Class = cls(kind, ["Actor"]); s.Name = name; s.Location = NS(X=loc[0], Y=loc[1], Z=loc[2])
        s.bDeleteMe = False; s.bHidden = False; s._p = f"Glacial_P.TheWorld:PersistentLevel.{name}"; s.seen = True
        for k, v in kw.items(): setattr(s, k, v)
    def _path_name(s): return s._p
def pickup(name, inv_cls, defname, loc):
    inv = NS(Class=cls(inv_cls), Name=name, GetShortHumanReadableName=lambda: name,
             DefinitionData=NS(ItemDefinition=NS(Name=defname)))
    return Actor("WillowPickup", name.replace(" ", ""), loc, Inventory=inv)
def thing(name, defname, loc, **kw):
    return Actor("WillowInteractiveObject", name, loc, InteractiveObjectDefinition=NS(Name=defname), **kw)
me = Pawn("me", (0, 0, 0), player=True)
chest = thing("Chest1", "IO_Chest_Red", (150, 0, 0), bIsUsable=True)
cash = pickup("Money", "WillowUsableItem", "Money_Pile", (100, 20, 0))
gun = pickup("Bandit SMG", "WillowWeapon", "SMG_Bandit", (2000, 0, 0))
door = thing("Door1", "IO_Door_Bunker", (0, -2000, 0))
objects.clear()
objects["WillowInteractiveObject"] = [chest, door]
objects["WillowPickup"] = [cash, gun]
world.pc = NS(Pawn=me, Rotation=NS(Pitch=0, Yaw=0, Roll=0), PlayerInput=None,
              WorldInfo=NS(PawnList=me, GetMapName=lambda b: "Glacial_P", Pauser=None, GRI=NS()),
              GFxUIManager=NS(FindFocusMovie=lambda: focus.movie), LineOfSightTo=lambda p: getattr(p, "seen", True))
world.pc.SetRotation = lambda r: setattr(world.pc, "Rotation", r)
f = m.feats
for o in ("opt_radar", "opt_npc_sounds", "opt_walls", "opt_ledges", "opt_jump", "opt_low_health", "opt_targeting",
          "opt_loot_sounds", "opt_container_sounds", "opt_interactive_sounds", "opt_quest_item_sounds"):
    getattr(m, o).value = False
m.opt_interact.value = True; m.opt_npc_talk.value = True
eng.streams = []; eng.combat_streams = []
def step(): f.next_use_scan = 0; tick()

m.state.last_device = "pad"
said.clear(); played.clear(); step()
print("chest:", said)
assert said and said[-1][0].startswith("Chest Red. Press X to open") and said[-1][1] is False, said
assert "ui" in played                                       # the soft double tick
assert not any("Money" in s[0] for s in said)               # money is picked up by walking over it
n = len(said); step(); step(); assert len(said) == n        # once, not every frame
# walk away and come back: announced again
me.Location = NS(X=-400, Y=0, Z=0); step(); assert len(said) == n
me.Location = NS(X=0, Y=0, Z=0); step(); assert len(said) == n + 1
# an opened chest has nothing to offer
chest.bIsUsable = False; me.Location = NS(X=-400, Y=0, Z=0); step(); me.Location = NS(X=0, Y=0, Z=0); step()
assert len(said) == n + 1
chest.bIsUsable = True
# gear: pick up / equip; keyboard names
me.Location = NS(X=1850, Y=0, Z=0); m.state.last_device = "keyboard"; step()
print("gun:", said[-1][0]); assert said[-1][0] == "Bandit SMG. Press E to pick up, hold E to equip", said[-1]
# behind you: no "press" prompt, but you're told where it is so you can turn to it (once)
me.Location = NS(X=0, Y=-1820, Z=0); world.pc.Rotation = NS(Pitch=0, Yaw=16384, Roll=0)    # facing away from the door (it is toward -Y)
n = len(said); step()
assert len(said) == n + 1 and said[-1][0] == "Door Bunker within reach, 6 o'clock. Turn to it", said[-1:]
step(); assert len(said) == n + 1
# the game's sight check doesn't work through the SDK, so it no longer hides prompts
world.pc.Rotation = NS(Pitch=0, Yaw=-16384, Roll=0); door.seen = False; step()
assert said[-1][0] == "Door Bunker. Press E to use", said[-1]
door.seen = True
# right next to it, the sight check failing (objects often block it with their own shape) doesn't stop the prompt
me.Location = NS(X=0, Y=-1500, Z=0); step(); door.seen = False; me.Location = NS(X=0, Y=-1880, Z=0); step()
assert said[-1][0] == "Door Bunker. Press E to use", said[-1]
door.seen = True
# key names follow the last device used
m.state.last_device = "pad"; me.Location = NS(X=0, Y=0, Z=0); world.pc.Rotation = NS(Pitch=0, Yaw=0, Roll=0); step()
assert said[-1][0].startswith("Chest Red. Press X"), said[-1]
key("Q"); key("Q", False); assert m.state.last_device == "keyboard"
key("XboxTypeS_DPad_Up"); key("XboxTypeS_DPad_Up", False); assert m.state.last_device == "pad"
# the weapon locker case from the game: its position is at its base, 2.2 m below your eyes,
# and you're 0.8 m in front of it; the prompt must still come
me.Location = NS(X=-400, Y=0, Z=0); step()
me.Location = NS(X=70, Y=0, Z=157); me.BaseEyeHeight = 64; world.pc.Rotation = NS(Pitch=0, Yaw=0, Roll=0)
n = len(said); step()
assert len(said) == n + 1 and said[-1][0].startswith("Chest Red. Press X"), said[-1:]
# use assist: X (which the game calls "XboxTypes_X") uses the announced locker for you,
# and the press is kept from the game so it isn't used twice
used = []
chest.UsedBy = lambda user: used.append(user) or True
r = key("XboxTypes_X"); key("XboxTypes_X", False)
assert used == [me] and r is not None and r is not False, (used, r)
assert m.controls.state.last_device == "pad"                 # still a controller, so "Press X"
m.opt_use_assist.value = False
m.features.features.s.use_assist = False
used.clear(); r = key("XboxTypes_X"); key("XboxTypes_X", False)
assert used == [], used                                     # switched off: the game handles it
m.features.features.s.use_assist = True; m.opt_use_assist.value = True
del chest.UsedBy
me.Location = NS(X=0, Y=0, Z=0); me.BaseEyeHeight = 0
# switched off: no prompts
m.opt_interact.value = False; me.Location = NS(X=-400, Y=0, Z=0); step(); me.Location = NS(X=0, Y=0, Z=0)
n = len(said); step(); assert len(said) == n
m.opt_interact.value = True
# NPCs: "Talk to <name>. Press X"
doc = Pawn("Doc Mercy", (150, 0, 0)); me.NextPawn = doc; objects["WillowInteractiveObject"] = []
m.feats.s.treat_all_ai_as_enemies = False
m.opt_all_ai.value = False
world.pc.CurrentUsableObject = None
doc.IsEnemy = lambda o: False
import bl2_access.game as G
orig = G.is_friendly_npc; G.is_friendly_npc = lambda me_, p: p is doc
step()
G.is_friendly_npc = orig
print("npc:", said[-1][0]); assert said[-1][0] == "Talk to Doc Mercy. Press X", said[-1]
# the glossary lists the new prompt sound
assert any(k == "ui_prompt" for k, _n, _d in A.SOUNDS) and A.preview("ui_prompt")
m.on_disable()
print("ALL ROUND 12 TESTS OK")
