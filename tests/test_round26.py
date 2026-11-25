"""Tests for: cutscene descriptions."""
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

# ================================================================ round 26: cutscene descriptions
import json, os
from bl2_access import trace as T
from bl2_access import cutscenes as C
from bl2_access.cutscenes import cutscenes as cs, matinee_key
notes = []
T.note = lambda text: notes.append(text)

# --- every description file loads, is in time order, and has no empty lines
lib = cs.library()
print("descriptions:", sorted(lib))
assert {"megaintro", "tc_marcus", "tc_scooter", "tc_tannis", "tc_zed"} <= set(lib)
for k, d in lib.items():
    times = [t for t, _s in d["lines"]]
    assert times == sorted(times) and all(s.strip() for _t, s in d["lines"]), k
assert 35 <= len(lib["megaintro"]["lines"]) <= 60
# the intro's lines during the narration (first 108 s) are short, so they fit the gaps
assert all(len(s.split()) <= 8 for t, s in lib["megaintro"]["lines"] if t < 108), [s for t, s in lib["megaintro"]["lines"] if t < 108 and len(s.split()) > 8]
print("description files OK")

# --- hooks: which exist is logged
assert ("Engine.PlayerController:ClientPlayMovie", Type.PRE) in hooked
cs.register()
assert any(n.startswith("cutscene: watching") for n in notes), notes

# --- a video: named from its path, lines spoken on time, once each, and the end logged
clock = [1000.0]
C.time = NS(perf_counter=lambda: clock[0], strftime=time.strftime, sleep=lambda s: None)
cs._start_timer = lambda: None            # no background thread in the test
said.clear(); notes.clear()
hooked[("Engine.PlayerController:ClientPlayMovie", Type.PRE)](world.pc, NS(MovieName="..\Movies\MegaIntro.bik"), None, None)
assert cs.key == "MegaIntro" and cs.kind == "movie", cs.key
assert any("cutscene hook fired: Engine.PlayerController:ClientPlayMovie" in n for n in notes)
assert any("'MegaIntro' started" in n and "description lines" in n for n in notes), notes
cs.tick()
assert said and said[-1][0] == "Ink drawings on old paper: a planet." and said[-1][1] is False, said
n = len(said)
clock[0] += 5; cs.tick(); assert len(said) == n                      # nothing due yet
clock[0] += 6; cs.tick(); assert said[-1][0] == "The Vault symbol."
clock[0] += 0.1; cs.tick(); assert sum(s == "The Vault symbol." for s, _i in said) == 1
# skipped far ahead (a loading hitch): old lines aren't read out in a burst
clock[0] = 1000.0 + 200; k = len(said); cs.tick()
assert len(said) - k <= 1, said[k:]
hooked[("Engine.PlayerController:ClientStopMovie", Type.PRE)](world.pc, NS(), None, None)
assert cs.key == "" and any("'MegaIntro' ended (stopped)" in n for n in notes)
print("video descriptions OK")

# --- descriptions off: nothing spoken
m.opt_cutscene_desc.value = False; m.sync_settings()
said.clear()
hooked[("Engine.PlayerController:ClientPlayMovie", Type.PRE)](world.pc, NS(MovieName="TC_Zed"), None, None)
cs.tick(); assert not said
hooked[("Engine.PlayerController:ClientStopMovie", Type.PRE)](world.pc, NS(), None, None)
m.opt_cutscene_desc.value = True; m.sync_settings()
print("setting off OK")

# --- an in-engine scene: found when cinematic mode comes on, timed by its own position
class Interp:
    def __init__(s, path):
        s.Name = path.rsplit(".", 1)[1]; s.bIsPlaying = True; s.Position = 0.0; s.InterpData = NS(InterpLength=12.0); s.p = path
    def _path_name(s): return s.p
scene = Interp("Glacial_P.TheWorld:PersistentLevel.Main_Sequence.SeqAct_Interp_3")
assert matinee_key(scene) == "Glacial_P/Main_Sequence.SeqAct_Interp_3"
objects["SeqAct_Interp"] = [NS(Name="Default__SeqAct_Interp", bIsPlaying=True), scene]
cs.lib["glacial_p/main_sequence.seqact_interp_3"] = {"key": "Glacial_P/Main_Sequence.SeqAct_Interp_3",
                                                     "lines": [(1.0, "Claptrap digs you out."), (6.0, "He waves.")]}
world.pc = NS(bCinematicMode=False, ConsoleCommand=lambda c, w=False: shots.append(c))
shots = []
said.clear(); notes.clear()
cs.tick(); assert cs.key == ""
world.pc.bCinematicMode = True; clock[0] += 1; cs.tick()
assert cs.key == "Glacial_P/Main_Sequence.SeqAct_Interp_3" and cs.kind == "matinee", cs.key
assert any("cinematic mode on" in n for n in notes) and any("12 s long" in n for n in notes), notes
clock[0] += 30; cs.tick(); assert not said                           # wall time doesn't matter: position does
scene.Position = 1.2; cs.tick(); assert said[-1][0] == "Claptrap digs you out."
scene.Position = 6.5; cs.tick(); assert said[-1][0] == "He waves."
# capture mode: a screenshot a second, logged with the scene and time
m.opt_cutscene_capture.value = True; m.sync_settings()
cs.next_shot = 0.0; cs.tick(); clock[0] += 0.5; cs.tick(); clock[0] += 0.6; cs.tick()
assert shots == ["shot", "shot"], shots
cap = os.path.join(T.LOG_DIR, "cutscene_capture.txt")
assert os.path.exists(cap) and "SeqAct_Interp_3 at 6.50" in open(cap, encoding="utf-8").read()
m.opt_cutscene_capture.value = False; m.sync_settings()
# the scene ends when cinematic mode goes off
world.pc.bCinematicMode = False; cs.tick()
assert cs.key == "" and any("ended (cinematic mode off)" in n for n in notes), notes
# an unknown scene is logged as needing a description
scene2 = Interp("Glacial_P.TheWorld:PersistentLevel.Main_Sequence.SeqAct_Interp_9"); objects["SeqAct_Interp"] = [scene2]
world.pc.bCinematicMode = True; clock[0] += 1; cs.tick()
assert any("SeqAct_Interp_9' started" in n and "no description written yet" in n for n in notes), notes
world.pc.bCinematicMode = False; cs.tick()
print("in-engine scenes and capture OK")
m.on_disable()
assert not any(k[0].startswith("Engine.PlayerController:ClientPlayMovie") for k in hooked)
print("ALL ROUND 26 TESTS OK")
