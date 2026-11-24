"""Tests for: calling the engine's line test directly."""
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


# ================================================================ round 24: the engine's own line test, called directly
import os, struct, math, tempfile
import bl2_access.native_trace as N
import bl2_access.game as G
from bl2_access import trace as T
notes = []
T.note = lambda text: notes.append(text)

# --- the arguments, as the game's scripts pass them
code = N.bytecode((1.0, 2.0, 3.0), (4.0, 5.0, 6.0))
assert code[0] == 0x23 and struct.unpack_from("<3f", code, 1) == (1.0, 2.0, 3.0)
assert code[13] == 0x23 and struct.unpack_from("<3f", code, 14) == (4.0, 5.0, 6.0)
assert code[26:] == bytes([0x4A, 0x4A, 0x16]) and len(code) == 29
fr = N.frame_bytes(0x1000, 0x2000, 0x3000, 0x4000, 0x5000)
assert len(fr) == N.FRAME_SIZE and struct.unpack_from("<I", fr, 0)[0] == 0x1000
assert struct.unpack_from("<4I", fr, 16) == (0x2000, 0x3000, 0x4000, 0x5000)
assert struct.unpack_from("<2I", fr, 32) == (0, 0)          # no previous frame, no out-parameters
# the thunk: this in ECX, frame and result pushed, call, return
assert N.THUNK[:3] == bytes([0x55, 0x8B, 0xEC]) and N.THUNK[-1] == 0xC3 and bytes([0x8B, 0x4D, 0x0C]) in N.THUNK
print("bytecode, frame and thunk OK")

# --- finding the native code pointer in a function object's memory
TEXT = (0x00401000, 0x01400000)
mem = {}
def put(addr, data):
    for i, b in enumerate(data):
        mem[addr + i] = b
def read(addr, n):
    if any(addr + i not in mem for i in range(n)):
        # unknown memory reads as zeros inside a "function object", None elsewhere (like ReadProcessMemory)
        if addr >= 0x20000000:
            return bytes(mem.get(addr + i, 0) for i in range(n))
        return None
    return bytes(mem[addr + i] for i in range(n))
FUNC = 0x20000000
blob = bytearray(0x200)
struct.pack_into("<I", blob, 0x10, 0x00401234)        # a vtable-like pointer before the flags: must not be taken
struct.pack_into("<I", blob, 0x84, 0x00020401)        # FunctionFlags (native, final...)
struct.pack_into("<HH", blob, 0x88, 0, 0)             # iNative, RepOffset
struct.pack_into("<HH", blob, 0x90, 0x1C, 0x18)       # ParamsSize, ReturnValueOffset
struct.pack_into("<I", blob, 0x94, 0x7FFF0000)        # padding / heap pointer: not code
struct.pack_into("<I", blob, 0x98, 0x00A1B2C0)        # Func: points into code
put(FUNC, blob)
found = N.find_native_pointer(read, FUNC, 0x00020401, 0x1C, 0x18, TEXT)
assert found == (0x98, 0x00A1B2C0), found
assert N.find_native_pointer(read, FUNC, 0x12345, 0x1C, 0x18, TEXT) is None   # wrong flags: nothing guessed
print("code pointer search OK")

# --- the code section, from the game's PE header
BASE = 0x00400000
pe = bytearray(0x400)
pe[0:2] = b"MZ"; struct.pack_into("<I", pe, 0x3C, 0x80)
pe[0x80:0x84] = b"PE\0\0"; struct.pack_into("<H", pe, 0x86, 2); struct.pack_into("<H", pe, 0x94, 0xE0)
sec = 0x80 + 0x18 + 0xE0
pe[sec:sec + 8] = b".text\0\0\0"; struct.pack_into("<II", pe, sec + 8, 0xFFF000, 0x1000)
pe[sec + 40:sec + 48] = b".data\0\0\0"; struct.pack_into("<II", pe, sec + 48, 0x100000, 0x1000000)
put(BASE, pe)
assert N.text_section(read, BASE) == (0x00401000, 0x01400000), N.text_section(read, BASE)
assert N.text_section(read, 0x00300000) is None
print("code section OK")

# --- crash guard and safety switches
d = N.DirectTrace()
N.MARKER = os.path.join(tempfile.mkdtemp(), "native_trace_attempt.txt")
open(N.MARKER, "w").write("x")
assert d.prepare() is False and d.state == "off" and "stopped during the first direct call" in d.reason
os.remove(N.MARKER)
d = N.DirectTrace(); d.enabled = False
assert d.prepare() is False and "switched off in the settings" in d.reason
d = N.DirectTrace()
assert d.prepare() is False and d.state == "off"          # this test runs in 64-bit Python (or without the game)
try:
    d.fast_trace(NS(_get_address=lambda: 1), (0, 0, 0), (0, 0, -100)); raise AssertionError("should refuse")
except RuntimeError as e:
    assert "off" in str(e)
assert any(n.startswith("direct line test: off") for n in notes)
print("crash guard OK")

# --- the self-check tries it first and uses it when its answers make sense
FLOOR = -90.0
def blocked(a, b):
    n = 40
    return any(a[2] + (b[2] - a[2]) * i / n <= FLOOR for i in range(n + 1))
class Pawn:
    def __init__(s):
        s.Location = NS(X=0.0, Y=0.0, Z=0.0); s.Controller = None; s.WorldInfo = None
        s.CylinderComponent = NS(CollisionHeight=90)
    def FastTrace(s, e, st): return False           # the SDK route: always "blocked", as in the game
    def Trace(s, *a, **k): return None
me = Pawn()
class Fake:
    state = "ready"
    def fast_trace(s, actor, start, end): return not blocked(start, end)
real = N.direct; N.direct = Fake()
G.FLOOR_SEEN = False; G.TRACE_MODE = None
verdict = G.trace_self_test(me)
print("self-check:", verdict)
assert G.FLOOR_SEEN and G.TRACE_METHOD == "direct engine call", (G.TRACE_METHOD, notes[-3:])
assert G.fast_trace(me, (0, 0, 0), (0, 0, -500)) is False and G.fast_trace(me, (0, 0, 0), (500, 0, 0)) is True
N.direct = real; G.FLOOR_SEEN = False; G.TRACE_METHOD = "FastTrace(end, start)"
print("self-check picks the direct call OK")
m.on_disable()
print("ALL ROUND 24 TESTS OK")
