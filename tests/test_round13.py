"""Tests for: character descriptions, silence in menus, scanner categories."""
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



# ================================================================ round 13: clean character select text
from bl2_access.menu_reader import clean
cases = [
    ("Uses [skill]Deception[-skill] to sneak.", "Uses Deception to sneak."),
    ("Zer0", "Zero"), ("Decepti0n", "Deception"), ("B0re", "Bore"),
    ("Level 10, 10x zoom, AR10, 2.0 seconds", "Level 10, 10x zoom, AR10, 2.0 seconds"),
    ("Phaselock enemies.\nThen shoot them.", "Phaselock enemies. Then shoot them."),
    ("Line one<br>Line two<BR/>Three", "Line one. Line two. Three"),
    ("Maya&#39;s &quot;Phaselock&quot; &amp; more&nbsp;power", "Maya's \"Phaselock\" & more power"),
    ("\u2022 Burst fire \u2022 Big guns", "Burst fire Big guns"),
    ("Can\u2019t stop", "Can\u2019t stop"),
    ("Don\u00e2\u20ac\u2122t stop", "Don\u2019t stop"),               # mojibake repaired
    ("Press \ue001 to use", "Press to use"),                         # button glyph removed
    ("<font color='#ffffff'>Sal</font>|Gunzerking", "Sal Gunzerking"),
    ("Wait. . . then go", "Wait. then go"),
    ("[place]Sanctuary[-place]", "Sanctuary"),
    ("Long range sniping or slitting throats.", "Long range sniping or slitting throats."),
    (None, ""),
]
for raw, want in cases:
    got = clean(raw)
    assert got == want, (raw, got, want)
print("clean OK")

# the character select reader uses it and logs the raw text once
from bl2_access.menu_reader import reader
d = NS(_path_name=lambda: "GD_Assassin.NameId_Assassin", LocalizedCharacterName="Zer0",
       LocalizedCharacterDescription="A [skill]deadly[-skill] assassin.\nStrikes from the shadows.",
       LocalizedActionSkillDescription="Decepti0n", LocalizedPreferredWeaponDescription="Long range sniping or slitting throats.")
objects.clear(); objects["PlayerNameIdentifierDefinition"] = [d]
reader.char_details.clear()
text = reader._character_details("Profile_Assassin")
print("details:", text)
assert text == ("A deadly assassin. Strikes from the shadows. Action skill: Deception. "
                "Preferred weapons: Long range sniping or slitting throats"), text
m.on_disable()
print("ALL ROUND 13 TESTS OK")
