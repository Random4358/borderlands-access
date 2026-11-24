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



# ================================================================ round 9: item card reader (replays the in-game trace)
from bl2_access.item_cards import cards, rarity_word, type_word

def cls(name, supers=()):
    chain = [NS(Name=name)] + [NS(Name=s) for s in supers]
    return NS(Name=name, _superfields=lambda: chain, _properties=lambda: [])
movie = NS(Name="StatusMenuExGFxMovie_6", Class=cls("StatusMenuExGFxMovie", ["GFxMoviePlayer"]), GetCurrentTab=lambda: 2)
movie._path_name = lambda: "StatusMenuExGFxMovie_6"
world.pc = NS(Pawn=None, GFxUIManager=NS(FindFocusMovie=lambda: movie), WorldInfo=NS(Pauser=None))
m.controls.menus.opened(movie)

def run(path, kind, obj, **args):
    a = NS(**args); a._type = NS(_properties=lambda: [NS(Name=k) for k in args])
    hooked[(path, kind)](obj, a, None, None)
C = "WillowGame.ItemCardGFxObject:"
card9, card10 = NS(Name="ItemCardGFxObject_9"), NS(Name="ItemCardGFxObject_10")
panel = NS(Name="StatusMenuInventoryPanelGFxObject_4")
def weapon(name, path, level):
    return NS(Class=cls("WillowWeapon"), Name=path, _path_name=lambda: path, GetShortHumanReadableName=lambda: name,
              DefinitionData=NS(ManufacturerGradeIndex=level))
repeater = weapon("Basic Repeater", "Inv.WillowWeapon_10", 5)
conv = weapon("Gearbox Projectile Convergence", "Inv.WillowWeapon_11", 6)

def select(thing):
    run("WillowGame.BaseTopLevelPanelGFxObject:OnItemSelected", Type.PRE, panel, Panel=None, Thing=thing)
def build(card, item, compare=None, stats=(), title=None, fun="", value=None, req=(False, True, "")):
    run(C + "SetItemCardEx", Type.PRE, card, WPC=None, InventoryItem=item, CompareAgainstInventoryItem=compare,
        CurrencyType=0, OverrideValue=-1)
    for i, (label, val, arrow) in enumerate(stats):
        run(C + "SetTopStat", Type.PRE, card, StatIndex=i, LabelText=label, ValueText=val, CompareArrow=arrow,
            AuxText="", IconName="x", NewLabelText="", NewValueText="", NewAuxText="")
    if title:
        maker, name, icon, readied, colour = title
        run(C + "SetTitle", Type.PRE, card, Manufacturer=maker, Title=name, Rarity=NS(), TypeIcon=icon,
            ElementalIcon="None", bIsReadied=readied)
        run(C + "__SetTitle", Type.PRE, card, Manufacturer=maker, Title=name, Rarity=colour, TypeIcon=icon,
            ElementalIcon="None", bIsReadied=readied)
    if fun:
        run(C + "SetFunStats", Type.PRE, card, FunStatsText=fun)
    if value is not None:
        run(C + "SetValue", Type.PRE, card, Amount=value)
    run(C + "SetLevelRequirement", Type.PRE, card, bHasRequirement=req[0], bMetRequirement=req[1],
        bAlreadyUsed=False, RequirementText=req[2])
    run(C + "SetItemCardEx", Type.POST, card)

# 1. empty equipped slot (trace 17:20:18: Thing=None, InventoryItem=None)
said.clear()
select(None); build(card9, None)
print("empty:", said); assert said[-1][0] == "Empty slot", said
select(None); build(card9, None)                       # same thing again straight away: not repeated
assert len(said) == 1

# 2. equipped pistol (trace 17:20:19)
REP_STATS = [("Damage", "11", 0), ("Accuracy", "89.3", 0), ("Fire Rate", "12.5", 0), ("Reload Speed", "1.5", 0),
             ("Magazine Size", "10", 0)]
FUN = "• <font color='#ffffff'><font color=\"#FFDEAD\"><i>Burst fire</i></font> while <font color=\"#FFDEAD\"><i>zoomed</i></font>."
select(repeater)
build(card9, repeater, stats=REP_STATS, title=("dahl", "Basic Repeater", "Pistol", True, 16777215), fun=FUN, value=20)
print("equipped:", said[-1][0])
assert said[-1][0] == ("Basic Repeater, Common Dahl pistol, level 5, equipped. Damage 11, Accuracy 89.3, Fire Rate 12.5, "
                       "Reload Speed 1.5, Magazine Size 10. Burst fire while zoomed. Worth 20 dollars."), said[-1]

# 3. backpack SMG compared with the equipped pistol, then the comparison card is cleared (trace 17:20:27)
CONV_STATS = [("Damage", "11", 3), ("Accuracy", "92.3", 1), ("Fire Rate", "10.4", 2), ("Reload Speed", "2.7", 2),
              ("Magazine Size", "20", 1)]
n = len(said)
select(conv)
build(card9, conv, compare=repeater, stats=CONV_STATS, title=("hyperion", "Gearbox Projectile Convergence", "SMG", False, 16777215), value=33)
build(card10, None)
build(card9, conv, compare=repeater, stats=CONV_STATS, title=("hyperion", "Gearbox Projectile Convergence", "SMG", False, 16777215), value=33)
print("compare:", said[-1][0])
assert len(said) == n + 1, said[n:]
assert said[-1][0] == ("Gearbox Projectile Convergence, Common Hyperion SMG, level 6. Compared with Basic Repeater: "
                       "Damage 11 same, Accuracy 92.3 better, Fire Rate 10.4 worse, Reload Speed 2.7 worse, "
                       "Magazine Size 20 better. Worth 33 dollars."), said[-1]
m.controls._repeat(); assert said[-1][0].startswith("Gearbox Projectile Convergence"), said[-1]

# 4. moving back onto the pistol later reads it again
cards.last_time -= 2
select(repeater)
build(card9, repeater, stats=REP_STATS, title=("dahl", "Basic Repeater", "Pistol", True, 16777215), fun=FUN, value=20)
assert said[-1][0].startswith("Basic Repeater, Common Dahl pistol"), said[-1]

# 5. a level requirement you don't meet; a legendary
relic = NS(Class=cls("WillowArtifact"), Name="R", _path_name=lambda: "Inv.R", GetShortHumanReadableName=lambda: "Vitality Relic")
select(relic)
build(card9, relic, stats=[("Max Health", "+12%", 0)], title=("eridian", "Vitality Relic", "artifact", False, 0xFF9600),
      req=(True, False, "Requires level 12"))
print("relic:", said[-1][0])
assert said[-1][0] == ("Vitality Relic, Legendary Eridian relic. Max Health +12%. Requires level 12. You can't use this yet."), said[-1]

# 6. vendors: no selection call; the card with an item is read, the empty one isn't
cards.selected = None; cards.last_time -= 2
n = len(said)
build(card9, conv, compare=repeater, stats=CONV_STATS[:1], title=("hyperion", "Gearbox Projectile Convergence", "SMG", False, 16777215), value=150)
build(card10, None)
assert len(said) == n + 1 and "Worth 150 dollars" in said[-1][0], said[n:]

# 7. the general item hooks stay quiet right after the card reader spoke (no double reading)
n = len(said)
run("WillowGame.StatusMenuInventoryPanelGFxObject:OnHighlight", Type.PRE, panel, Thing=conv)
time.sleep(0.1); m.hooks._last_tick = 0; m.hooks.on_tick(None, None, None, None)
assert len(said) == n, said[n:]

# 8. helpers
assert rarity_word(16777215) == "common" and rarity_word(0x00FF00) == "uncommon" and rarity_word(0x3C8CFF) == "rare"
assert rarity_word(0xA050FF) == "epic" and rarity_word(0xFF9600) == "legendary" and rarity_word("x") == ""
assert type_word("sniper") == "sniper rifle" and type_word("None") == "" and type_word("Shotgun") == "shotgun"
# card calls for a card that was never started don't crash
run(C + "SetTopStat", Type.PRE, NS(Name="ItemCardGFxObject_99"), StatIndex=0, LabelText="x", ValueText="1", CompareArrow=0,
    AuxText="", IconName="", NewLabelText="", NewValueText="", NewAuxText="")
run(C + "SetItemCardEx", Type.POST, NS(Name="ItemCardGFxObject_99"))
m.controls.menus.closed(movie)
m.on_disable()
assert (C + "SetItemCardEx", Type.POST) not in hooked
print("ALL ROUND 9 TESTS OK")
