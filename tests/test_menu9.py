"""Offline test of the menu reader: fake lists, options focus, main-menu calibration, dialogs."""
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
mb.build_mod = lambda **k: NS(save_settings=lambda: None)
mb.get_pc = lambda: None          # main menu: no player pawn
sys.modules["mods_base"] = mb

hooked = {}
us = types.ModuleType("unrealsdk")
us.make_struct = lambda name, **f: NS(**f)
us.find_all = lambda *a, **k: []
def find_class(name):
    if name == "WillowGFxUIManager":
        raise ValueError("no class")
    owner = NS(Name=name, Outer=NS(Name="WillowGame"))
    return NS(_find=lambda fn: NS(Outer=owner))
us.find_class = find_class
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
from bl2_access.menu_reader import reader, clean, resolve
said = []
m.speaker.say = lambda t, interrupt=True: said.append(t)
m.audio_engine.play = lambda *a: None
m.on_enable()
print("menu hooks:", len(reader.registered), "(training skipped because class missing)")

def call(cls, fn, obj, kind=Type.POST, **args):
    a = NS(**args)
    props = [NS(Name=k) for k in args]
    a._type = NS(_properties=lambda: props)
    hooked[(f"WillowGame.{cls}:{fn}", kind)](obj, a, None, None)

class ListObj:
    def __init__(self, name):
        self.Name = name; self.Selection = 0; self.Scroll = 7
        self.Class = NS(Name="WillowScrollingList", _properties=lambda: [
            NS(Name="Selection", Class=NS(Name="IntProperty")), NS(Name="Scroll", Class=NS(Name="IntProperty"))])
        self.MyOwnerMovie = NS(ResolveDataStoreMarkup=lambda s: {"$WillowMenu.FrontEnd.Continue": "CONTINUE"}.get(s, s))
    def _path_name(self): return "Frontend.TheList_" + self.Name

# --- main menu: populate, auto-announce first entry, then calibrate on D-pad down
lst = ListObj("main")
for i, cap in enumerate(["$WillowMenu.FrontEnd.Continue", "NEW GAME", "OPTIONS", "<font color='#ff0'>QUIT</font>"]):
    call("WillowScrollingList", "AddListItem", lst, EventID=i, Caption=cap, bDisabled=False)
time.sleep(0.2); reader.tick()
print("first:", said[-1]); assert said[-1] == "CONTINUE, 1 of 4"
st = m.controls.state
def press(k): return m.hooks.on_input(None, NS(Key=k, Event=EInputEvent.IE_Pressed, ControllerId=0), None, None)
press("XboxTypeS_DPad_Down"); lst.Selection = 1; time.sleep(0.05); reader.tick()
print("after down:", said[-1]); assert said[-1] == "NEW GAME, 2 of 4"
assert reader.sel_prop["WillowScrollingList"] == "Selection"
press("Down"); lst.Selection = 3; lst.Scroll = 9; time.sleep(0.05); reader.tick()
print("after down x2:", said[-1]); assert said[-1] == "QUIT, 4 of 4"

# --- options menu: spinner + slider, focus via UpdateDescriptionText, value changes
time.sleep(0.35)
opts = ListObj("opts"); prov = NS(Name="prov", _path_name=lambda: "prov")
call("WillowScrollingList", "AddSpinnerListItem", opts, EventID=10, Caption="Subtitles", bDisabled=False, StartIndex=1, Choices=["Off", "On"])
call("WillowScrollingList", "AddSliderListItem", opts, EventID=11, Caption="Field of view", bDisabled=False, Value=90, Min=70, Max=110, Step=1)
call("WillowScrollingListDataProviderOptionsBase", "AddDescription", prov, EventID=11, Description="Wider view")
call("WillowScrollingListDataProviderOptionsBase", "UpdateDescriptionText", prov, Type.PRE, EventID=10, TheList=opts)
print("focus 1:", said[-1]); assert said[-1] == "Subtitles, On, choice, 1 of 2"
call("WillowScrollingListDataProviderOptionsBase", "UpdateDescriptionText", prov, Type.PRE, EventID=11, TheList=opts)
print("focus 2:", said[-1]); assert said[-1] == "Field of view, slider 90, range 70 to 110, 2 of 2. Wider view"
call("WillowScrollingListDataProviderOptionsBase", "HandleSliderChange", prov, Type.PRE, EventID=11, NewSliderValue=95)
call("WillowScrollingListDataProviderOptionsBase", "HandleSpinnerChange", prov, Type.PRE, EventID=10, NewChoiceIndex=0)
print("changes:", said[-2:]); assert said[-2:] == ["95", "Off"]

# --- dialog
dlg = NS(Name="dlg", CurrentSelection=0, _path_name=lambda: "dlg")
call("WillowGFxDialogBox", "SetText", dlg, Title="Quit game?", Message="Unsaved progress will be lost.")
call("WillowGFxDialogBox", "AppendButton", dlg, Tag="yes", Caption="Yes", Tip="")
call("WillowGFxDialogBox", "AppendButton", dlg, Tag="no", Caption="No", Tip="Return to the game")
call("WillowGFxDialogBox", "ApplyLayout", dlg)
print("dialog:", said[-1]); assert said[-1] == "Quit game?. Unsaved progress will be lost.. Yes button, 1 of 2"
dlg.CurrentSelection = 1
call("WillowGFxDialogBox", "HandleInputKey", dlg, ukey="Down", uevent=0)
print("dialog move:", said[-1]); assert said[-1] == "No button, 2 of 2. Return to the game"

assert clean("<p>[skill]Gunzerking[/skill] &amp; more</p>") == "Gunzerking & more"
assert resolve("$WillowMenu.Pause.ExitToMainMenu") == "Exit To Main Menu"

# ---- regression: what the real game log showed
said.clear(); time.sleep(0.35)
fl = ListObj("frontend2"); fl.MyOwnerMovie = None    # owner movie not set yet while populating
caps = ["$WillowMenu.WillowScrollingListDataProviderFrontEnd.Play_NewGame", "OPTIONS", "EXTRAS", "QUIT"]
for _rebuild in range(3):                               # game rebuilds the main list 3x in a row
    for i, cap in enumerate(caps):
        call("WillowScrollingList", "AddListItem", fl, EventID=i, Caption=cap, bDisabled=(cap == "EXTRAS"))
fl.MyOwnerMovie = NS(ResolveDataStoreMarkup=lambda s: s)  # attached, but can't resolve this key
time.sleep(0.2); reader.tick()
print("regression first:", said[-1]); assert said[-1] == "Play New Game, 1 of 4", said[-1]
reader.sel_prop.clear()
class Frozen(ListObj):                                   # selection lives in Flash: no int prop moves
    pass
fl.Class = NS(Name="FrontendList", _properties=lambda: [])
press("XboxTypeS_DPad_Down"); time.sleep(0.05); reader.tick()
print("estimate down:", said[-1]); assert said[-1] == "OPTIONS, 2 of 4"
press("Down"); time.sleep(0.05); reader.tick()
print("estimate skips disabled:", said[-1]); assert said[-1] == "QUIT, 4 of 4"
press("Down"); time.sleep(0.05); reader.tick()
print("estimate wraps:", said[-1]); assert said[-1] == "Play New Game, 1 of 4"
press("XboxTypeS_DPad_Up"); time.sleep(0.05); reader.tick()
print("estimate up wraps:", said[-1]); assert said[-1] == "QUIT, 4 of 4"
print("ALL REGRESSION TESTS OK")
# ---- regression 2: keys only reach the menu's own handler (FrontendGFxMovie:SharedHandleInputKey)
said.clear()
movie = NS(Name="FrontendGFxMovie_0")
def movie_key(k, ev=EInputEvent.IE_Pressed):
    call("FrontendGFxMovie", "SharedHandleInputKey", movie, Type.PRE, ControllerId=0, ukey=k, uevent=ev)
movie_key("XboxTypeS_DPad_Down"); time.sleep(0.05); reader.tick()
print("movie down:", said[-1]); assert said[-1] == "Play New Game, 1 of 4"   # wrapped from QUIT
movie_key("XboxTypeS_DPad_Down", EInputEvent.IE_Released); time.sleep(0.05); reader.tick()
assert said[-1] == "Play New Game, 1 of 4"            # release does nothing
time.sleep(0.1)
press("Down"); movie_key("Down"); time.sleep(0.05); reader.tick()   # same press seen by both hooks
print("dedupe:", said[-1]); assert said[-1] == "OPTIONS, 2 of 4" and said.count("OPTIONS, 2 of 4") == 1
print("ALL MOVIE INPUT TESTS OK")
# ---- regression 3: replay of the real trace (selection comes from HandleSelectionChange)
said.clear(); time.sleep(0.35)
real = ListObj("real"); real.MyOwnerMovie = NS(ResolveDataStoreMarkup=lambda s: s)
prov = NS(Name="WillowScrollingListDataProviderFrontEnd_1", _path_name=lambda: "provFE")
# Real game order: EventIDs are not 0..n, first entry has EventID 6
real_items = [(6, "$WillowMenu.WillowScrollingListDataProviderFrontEnd.Play_NewGame"), (0, "OPTIONS"),
              (3, "$WillowMenu.WillowScrollingListDataProviderFrontEnd.Extras"), (9, "QUIT")]
for eid, cap in real_items:
    call("WillowScrollingList", "AddListItem", real, EventID=eid, Caption=cap, bDisabled=False, bNew=False)
call("WillowScrollingListDataProviderBase", "HandleSelectionChange", prov, Type.PRE, EventID=6, TheList=real)
print("real first:", said[-1]); assert said[-1] == "Play New Game, 1 of 4"
time.sleep(0.2); reader.tick(); assert said.count("Play New Game, 1 of 4") == 1   # tick must not repeat it
# A D-pad press arriving via FilterButtonInput must NOT trigger the key-press estimate any more
gfx = NS(Name="FrontendGFxMovie_0")
call("GFxMoviePlayer", "FilterButtonInput", gfx, Type.PRE, ControllerId=0, ButtonName="XboxTypeS_DPad_Down", InputEvent=EInputEvent.IE_Pressed)
time.sleep(0.05); reader.tick()
assert said[-1] == "Play New Game, 1 of 4", said[-1]
# ...the game then reports the real move
call("WillowScrollingListDataProviderBase", "HandleSelectionChange", prov, Type.PRE, EventID=3, TheList=real)
print("real move:", said[-1]); assert said[-1] == "Extras, 3 of 4"
call("WillowScrollingListDataProviderBase", "HandleSelectionChange", prov, Type.PRE, EventID=3, TheList=real)
assert said.count("Extras, 3 of 4") == 1           # same entry twice is spoken once
# stick logging: only edges are noted, no exception on per-frame polling
for d in (0.0, 0.1, -0.9, -0.95, 0.0):
    call("GFxMoviePlayer", "FilterAxisInput", gfx, Type.PRE, ControllerId=0, Key="XboxTypeS_LeftY", Delta=d, DeltaTime=0.016)
# online pop-up is announced on open
m.controls.menus.opened(NS(Class=NS(Name="OnlineMessageGFxMovie"), Name="OnlineMessageGFxMovie_0", _path_name=lambda: "olm"))
print("popup:", said[-1]); assert said[-1].startswith("Message from the game. Press A or Enter to accept or continue, B or Escape to go back")
print("ALL REAL-TRACE TESTS OK")
# ---- regression 4: option help text given as '$Key' references (real game: MusicVolumeDesc)
said.clear(); time.sleep(0.35)
ol = ListObj("audio"); ol.MyOwnerMovie = NS(ResolveDataStoreMarkup=lambda s: s)
lookup = {"$WillowMenu.MenuOptionDisplayNames.SFXVolumeDesc": "Changes the volume of sound effects."}
oprov = NS(Name="provAudio", _path_name=lambda: "provAudio",
           MyOptionsMovie=NS(ResolveDataStoreMarkup=lambda s: lookup.get(s, s)))
call("WillowScrollingList", "AddSliderListItem", ol, EventID=20, Caption="Music Volume", bDisabled=False, Value=10, Min=0, Max=10, Step=1)
call("WillowScrollingList", "AddSliderListItem", ol, EventID=21, Caption="SFXVolume", bDisabled=False, Value=10, Min=0, Max=10, Step=1)
call("WillowScrollingListDataProviderOptionsBase", "AddDescription", oprov, EventID=20, Description="$WillowMenu.MenuOptionDisplayNames.MusicVolumeDesc")
call("WillowScrollingListDataProviderOptionsBase", "AddDescription", oprov, EventID=21, Description="$WillowMenu.MenuOptionDisplayNames.SFXVolumeDesc")
call("WillowScrollingListDataProviderBase", "HandleSelectionChange", oprov, Type.PRE, EventID=20, TheList=ol)
print("unresolvable desc:", said[-1]); assert said[-1] == "Music Volume, slider 10, range 0 to 10, 1 of 2"
call("WillowScrollingListDataProviderBase", "HandleSelectionChange", oprov, Type.PRE, EventID=21, TheList=ol)
print("resolved desc:", said[-1]); assert said[-1] == "SFXVolume, slider 10, range 0 to 10, 2 of 2. Changes the volume of sound effects."
print("ALL DESCRIPTION TESTS OK")
# ---- regression 5: dialogs whose text comes from WillowMenu.int (real file from the game install)
import bl2_access.menu_reader as mr
mr._loc_dir = lambda: r"C:\Program Files (x86)\Steam\steamapps\common\Borderlands 2\WillowGame\Localization\INT"
said.clear()
d2 = NS(Name="WillowGFxDialogBox_0", CurrentSelection=0, _path_name=lambda: "dlg2")
call("WillowGFxDialogBox", "AutoLocEnable", d2, File="WillowMenu", Section="dlgGettingSavegameList")
call("WillowGFxDialogBox", "ApplyLayout", d2)
print("save list dialog:", said[-1]); assert said[-1] == "Getting Save List. Retrieving available saved games. Please wait."
call("WillowGFxDialogBox", "AutoLocEnable", d2, File="WillowMenu", Section="dlgNoPreviousGameSavesFound")
call("WillowGFxDialogBox", "ApplyLayout", d2)
print("not found dialog:", said[-1][:90], "..."); assert said[-1].startswith("Not Found. No save data from the original Borderlands was found.")
call("WillowGFxDialogBox", "AutoLocEnable", d2, File="WillowMenu", Section="dlgDeleteSaveGameConfirm_DoesNotExist")
call("WillowGFxDialogBox", "ApplyLayout", d2)
assert said[-1] == "Dialog"                         # unknown section falls back safely
print("ALL LOCALISATION DIALOG TESTS OK")
# ---- regression 6: the game deletes the menu (level load after pressing OK). The crash dumps
# showed null reads inside pyunrealsdk, so after deletion the mod must not touch the object at all.
class Exploding:
    """Stands in for a deleted UObject: any attribute access is the crash we must avoid."""
    def __getattr__(self, name):
        raise AssertionError(f"touched deleted object .{name}")
dead = ListObj("dying"); dead.MyOwnerMovie = NS(ResolveDataStoreMarkup=lambda s: s)
time.sleep(0.35)
call("WillowScrollingList", "AddListItem", dead, EventID=1, Caption="CONTINUE", bDisabled=False)
time.sleep(0.2); reader.tick()
st_dead = reader.current
st_dead.ptr = lambda: None                 # WeakPointer now reports the object is gone
m.controls.menus.last_movie_ptr = lambda: None
reader.before_nav("XboxTypeS_DPad_Down")    # must not touch it
reader.tick()                               # must not touch it, and must forget it
assert reader.current is None and all(s.obj is not None for s in reader.lists.values())
assert m.controls.menus.last_movie is None
# enemies/POIs are dropped on the loading screen and never dereferenced afterwards
from bl2_access.features import Enemy, POI
e = Enemy(lambda: None, "k", (0, 0, 0), None, True); assert e.actor is None
p = POI("Chest", lambda: None); assert p.actor is None
print("ALL DELETED-OBJECT TESTS OK")
# ---- regression 7: F-key shortcuts pressed inside a menu (real log: F2 on the character screen)
said.clear()
m.controls.menus.open["cs"] = "CharacterSelectionReduxGFxMovie"; m.controls.menus.ptrs["cs"] = (lambda o=object(): o)
cs = NS(Name="CharacterSelectionReduxGFxMovie_0")
toggled = []
import bl2_access.trace as tr
tr.toggle_menus = lambda: toggled.append(1)
def gfx_btn(k):
    call("GFxMoviePlayer", "FilterButtonInput", cs, Type.PRE, ControllerId=0, ButtonName=k, InputEvent=EInputEvent.IE_Pressed)
    call("WillowGFxMovie3D", "FilterButtonInput", cs, Type.PRE, ControllerId=0, ButtonName=k, InputEvent=EInputEvent.IE_Pressed)
gfx_btn("F2")
print("F2 in menu ran trace toggle:", len(toggled)); assert toggled == [1]     # once, despite two hooks
time.sleep(0.3); gfx_btn("F2"); assert toggled == [1, 1]
gfx_btn("F4"); print("F4 help:", said[-1][:40]); assert said[-1].startswith("Press Back three times quickly") and "Hold Back and press" in said[-1]
# the game's own keybind route + the menu route for the same press -> still once
said.clear(); time.sleep(0.3)
m.KEYBINDS[[a for a, _ in m._BIND_ACTIONS].index("help")].callback(); gfx_btn("F4")
assert len([s for s in said if s.startswith("Press Back three times")]) == 1
# rebinding is respected
m._BIND_ACTIONS[[a for a, _ in m._BIND_ACTIONS].index("trace")][1].key = "F12"
time.sleep(0.3); gfx_btn("F2"); assert toggled == [1, 1]; gfx_btn("F12"); assert toggled == [1, 1, 1]
m.controls.menus.open.pop("cs", None); m.controls.menus.ptrs.pop("cs", None)
print("ALL MENU SHORTCUT TESTS OK")
# ---- regression 8: replay of the real character-screen trace
said.clear()
csm = NS(Name="CharacterSelectionReduxGFxMovie_0")
def save(name): return NS(Name=name)
def standin(profile):
    call("CharacterSelectionReduxGFxMovie", "UpdatePlayerStandIn", csm, Type.PRE, PlayerIndex=0, WPC=None, SaveGame=save(profile))
def select(i):
    call("CharacterSelectionReduxGFxMovie", "SetSelectedCharacterIndex", csm, Type.PRE, PlayerIndex=0, NewSelectedIndex=i)
standin("Profile_Soldier")                     # screen opens on the starting character
print("opening:", said[-2:]); assert said[-2] == "Axton, the Commando" and said[-1].startswith("Move left or right") and "Press A or Enter to choose" in said[-1]
# real sequence from the trace: 2 Siren, 3 Mercenary, 2, 3, 2, 5 Lilac, 4 Mechromancer
for idx, prof in [(2, "Profile_Siren"), (3, "Profile_Mercenary")]:
    select(idx); standin(prof)
print("first visits:", said[-2:]); assert said[-2:] == ["Maya, the Siren", "Salvador, the Gunzerker"]
n = len(said); select(2); assert said[-1] == "Maya, the Siren" and len(said) == n + 1   # instant on revisit
standin("Profile_Siren"); assert len(said) == n + 1                                     # preview doesn't repeat it
select(5); standin("Profile_LilacPlayerClass"); assert said[-1] == "Krieg, the Psycho"
select(4); standin("Profile_Mechromancer"); assert said[-1] == "Gaige, the Mechromancer"
select(1); standin("Profile_SomeNewClass"); assert said[-1] == "Some New Class"           # unknown class: readable fallback
call("CharacterSelectionReduxGFxMovie", "SetSelectedCharacterIndex", csm, Type.PRE, PlayerIndex=1, NewSelectedIndex=3)
assert said[-1] == "Some New Class"                                                     # player 2 ignored
print("ALL CHARACTER SCREEN TESTS OK")
m.on_disable(); assert not reader.registered
print("ALL MENU TESTS OK")












