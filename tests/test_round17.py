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



# ================================================================ round 17: snagged on low obstacles
import math
import bl2_access.game as G
from bl2_access import navigation as NAV
from bl2_access import trace as T

notes = []
T.note = lambda text: notes.append(text)
G.TRACE_MODE = "fast"; G.FLOOR_SEEN = True

class Box:
    def __init__(s, x0, x1, y0, y1, z1): s.x0, s.x1, s.y0, s.y1, s.z1 = x0, x1, y0, y1, z1
    def hit(s, x, y, z): return s.x0 <= x <= s.x1 and s.y0 <= y <= s.y1 and z <= s.z1
class Pawn:
    """Location is the body centre; feet are 90 below (floor at z = -90)."""
    def __init__(s, boxes):
        s.Location = NS(X=0.0, Y=0.0, Z=0.0); s.Velocity = NS(X=0.0, Y=0.0, Z=0.0); s.Acceleration = NS(X=0.0, Y=0.0, Z=0.0)
        s.boxes = boxes; s.CylinderComponent = NS(CollisionHeight=90); s.BaseEyeHeight = 60
        s.Name = "me"; s.Class = NS(Name="WillowPlayerPawn"); s.NextPawn = None; s.bDeleteMe = False; s.bHidden = False
        s.Controller = None; s.Weapon = None
    def FastTrace(s, end, start):
        for i in range(61):
            t = i / 60
            x = start.X + (end.X - start.X) * t; y = start.Y + (end.Y - start.Y) * t; z = start.Z + (end.Z - start.Z) * t
            if z <= -90 or any(b.hit(x, y, z) for b in s.boxes):
                return False
        return True
    def GetHealth(s): return 100
    def GetMaxHealth(s): return 100
    def IsEnemy(s, o): return False

crate = Box(60, 160, -100, 100, -40)          # knee high (50 cm), right in front
assert G.blockage(Pawn([crate]), 0.0, 100)["jumpable"]
wall = Box(60, 80, -50, 2000, 400)            # tall, covers ahead and to the right; open to the left (-Y)
b = G.blockage(Pawn([wall]), 0.0, 100)
assert b["wall"] and b["left_open"] and not b["right_open"], b
assert G.move_intent(Pawn([])) is None
p = Pawn([]); p.Acceleration = NS(X=0, Y=500, Z=0); assert G.move_intent(p) == (0.0, 1.0)
print("blockage OK")

# --- in the game loop
me = Pawn([crate])
world.pc = NS(Pawn=me, Rotation=NS(Pitch=0, Yaw=0, Roll=0), PlayerInput=None, SetRotation=lambda r: None,
              WorldInfo=NS(PawnList=me, GetMapName=lambda b: "Glacial_P", Pauser=None, GRI=NS()),
              GFxUIManager=NS(FindFocusMovie=lambda: None), LineOfSightTo=lambda p: True)
for o in ("opt_radar", "opt_npc_sounds", "opt_npc_talk", "opt_walls", "opt_low_health", "opt_targeting",
          "opt_loot_sounds", "opt_container_sounds", "opt_interactive_sounds", "opt_quest_item_sounds", "opt_interact"):
    getattr(m, o).value = False
m.opt_jump.value = True; m.opt_ledges.value = True; m.opt_speak_blocked.value = True; m.opt_speak_jump.value = False
objects.clear(); m.controls.menus.open.clear()
f = m.feats
def tick():
    m.hooks._last_tick = 0; m.hooks.on_tick(None, None, None, None)
tick()                                   # spawn
def push_for(seconds):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < seconds:
        f.next_wall = 0; tick(); time.sleep(0.05)

# not pushing: silence
said.clear(); played.clear(); push_for(0.8)
assert not said, said
# pushing into the crate, not moving: "Low obstacle. Jump over", once
me.Acceleration = NS(X=800, Y=0, Z=0)
said.clear(); played.clear(); push_for(0.9)
print("crate:", said, played)
assert [s for s, _ in said] == ["Low obstacle. Jump over"] and "alert" in played
push_for(0.8); assert len(said) == 1               # once per snag
# let go and push again: told again
me.Acceleration = NS(X=0, Y=0, Z=0); push_for(0.3)
me.Acceleration = NS(X=800, Y=0, Z=0); push_for(0.9); assert len(said) == 2
# a tall wall, open to the left
me.boxes = [wall]; me.Acceleration = NS(X=0, Y=0, Z=0); push_for(0.3)
said.clear(); me.Acceleration = NS(X=800, Y=0, Z=0); push_for(0.9)
print("wall:", said)
assert said and said[-1][0] == "Blocked, open to the left", said
# walking normally (moving): nothing said
me.boxes = []; me.Velocity = NS(X=400, Y=0, Z=0); said.clear(); push_for(0.9)
assert not said, said
# the option turns it off (the jump cue sound still plays for jumpable things)
me.Velocity = NS(X=0, Y=0, Z=0); me.boxes = [wall]; m.opt_speak_blocked.value = False
me.Acceleration = NS(X=0, Y=0, Z=0); push_for(0.3); said.clear(); me.Acceleration = NS(X=800, Y=0, Z=0); push_for(0.9)
assert not said
m.opt_speak_blocked.value = True
print("blocked announcements OK")

# --- the beacon's route: a low obstacle the body-height test can't see, found by getting snagged
log_wall = Box(400, 450, -300, 300, -40)        # a fallen log across the way (50 cm high)
me = Pawn([log_wall]); target = (1500.0, 0.0, 0.0); r = NAV.Route(); now = 0.0
class PC: pass
stuck_steps = 0
for step in range(160):
    now += 0.2
    p = r.next_point(PC(), (me.Location.X, me.Location.Y, 60), target, None, "goal", now, me)
    here = (me.Location.X, me.Location.Y)
    d = math.dist(here, p[:2]) or 1
    nx, ny = here[0] + (p[0] - here[0]) / d * 60, here[1] + (p[1] - here[1]) / d * 60
    me.Acceleration = NS(X=(p[0] - here[0]) / d * 800, Y=(p[1] - here[1]) / d * 800, Z=0)
    if log_wall.hit(nx, ny, -60) or log_wall.hit((here[0] + nx) / 2, (here[1] + ny) / 2, -60):
        me.Velocity = NS(X=0, Y=0, Z=0); stuck_steps += 1         # snagged: doesn't move
    else:
        me.Location = NS(X=nx, Y=ny, Z=0.0); me.Velocity = NS(X=300, Y=0, Z=0)
    if math.dist((me.Location.X, me.Location.Y), target[:2]) < 150:
        break
print("log: arrived", math.dist((me.Location.X, me.Location.Y), target[:2]) < 150, "after", step + 1, "steps,", stuck_steps, "snagged")
assert math.dist((me.Location.X, me.Location.Y), target[:2]) < 150
assert stuck_steps <= 8, stuck_steps                            # found a way round quickly
assert any("snagged" in n for n in notes)
m.on_disable()
print("ALL ROUND 17 TESTS OK")
