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



# ================================================================ round 15: getting around obstacles
import bl2_access.game as _G; _G.FLOOR_SEEN = True; _G.TRACE_MODE = "fast"   # line tests work in this simulated world
import math
from bl2_access import navigation as NAV
from bl2_access import trace as T

notes = []
T.note = lambda text: notes.append(text)

class Box:
    def __init__(s, x0, x1, y0, y1): s.x0, s.x1, s.y0, s.y1 = x0, x1, y0, y1
    def hits(s, a, b):
        for i in range(81):
            t = i / 80
            x = a[0] + (b[0] - a[0]) * t; y = a[1] + (b[1] - a[1]) * t
            if s.x0 <= x <= s.x1 and s.y0 <= y <= s.y1:
                return True
        return False
class Pawn:
    def __init__(s, walls, pits=()):
        s.Location = NS(X=0.0, Y=0.0, Z=0.0); s.Velocity = NS(X=0, Y=0, Z=0); s.walls = walls; s.pits = pits
    def FastTrace(s, end, start):
        a, b = (start.X, start.Y), (end.X, end.Y)
        if a == b:   # straight down: floor unless over a pit
            return any(p.hits(a, a) for p in s.pits)
        return not any(w.hits(a, b) for w in s.walls)
def pos(p): return (p.Location.X, p.Location.Y, p.Location.Z)
class PC: pass   # no navigation mesh, no path nodes

# --- a wall between you and the target: the beacon leads around it, then on to the target
wall = Box(500, 600, -400, 400)
me = Pawn([wall]); pc = PC(); target = (2000.0, 0.0, 0.0)
r = NAV.Route(); now = 0.0
p = r.next_point(pc, pos(me), target, None, "goal", now, me)
print("first steer point:", tuple(round(c) for c in p))
assert p != target and abs(p[1]) > 100, p                          # not straight into the wall
assert me.FastTrace(NS(X=p[0], Y=p[1], Z=0), NS(X=0, Y=0, Z=0))      # and the way to it is clear
assert any("steering around obstacles" in n for n in notes)
assert any("navigation mesh not usable" in n for n in notes) and any("path nodes not available" in n for n in notes)
# walk toward whatever the beacon points at; you get past the wall and arrive
path = []
for step in range(120):
    now += 0.3
    p = r.next_point(pc, pos(me), target, None, "goal", now, me)
    here = pos(me)
    d = math.dist(here[:2], p[:2]) or 1
    nx, ny = here[0] + (p[0] - here[0]) / d * 100, here[1] + (p[1] - here[1]) / d * 100
    assert not wall.hits(here, (nx, ny)), ("walked into the wall", here, p)
    me.Location = NS(X=nx, Y=ny, Z=0.0); me.Velocity = NS(X=300, Y=0, Z=0)
    path.append((round(nx), round(ny)))
    if math.dist((nx, ny), target[:2]) < 150:
        break
print("arrived after", len(path), "steps; widest point", max(abs(y) for _x, y in path))
assert math.dist(pos(me)[:2], target[:2]) < 150, path[-5:]
# no game route asked for again once it's known not to work
calls = []
class PC2:
    def FindPathTo(s, v): calls.append(1); return None
r2 = NAV.Route(); r2.next_point(PC2(), (0, 0, 0), target, None, "k", 0.0, Pawn([]))
r2.next_point(PC2(), (0, 0, 0), target, None, "k", 1.0, Pawn([])); r2.next_point(PC2(), (0, 0, 0), target, None, "k", 2.0, Pawn([]))
assert len(calls) == 1, calls
print("around the wall OK")

# --- no floor beyond the wall on one side (a drop): it picks the side with floor
pit = Box(0, 800, 100, 2000)                    # everything to the right of the line is a drop
me = Pawn([wall], pits=[pit]); r = NAV.Route()
p = r.next_point(PC(), pos(me), target, None, "goal", 0.0, me)
assert p[1] < 0, p                               # goes left, where there's floor
print("avoids drops OK")

# --- stuck: walking but not getting closer for 3 seconds -> tries the other side
me = Pawn([wall]); r = NAV.Route()
p1 = r.next_point(PC(), pos(me), target, None, "goal", 0.0, me)
side1 = r.side
me.Velocity = NS(X=200, Y=0, Z=0)               # pressing forward, but not moving (snagged)
for t in (0.5, 1.5, 2.5, 3.2, 3.5):
    p2 = r.next_point(PC(), pos(me), target, None, "goal", t, me)
assert r.side == -side1 and (p2[1] > 0) != (p1[1] > 0), (side1, r.side, p1, p2)
assert any("stuck" in n for n in notes)
# standing still isn't "stuck"
me2 = Pawn([wall]); r = NAV.Route(); r.next_point(PC(), pos(me2), target, None, "g", 0.0, me2); s0 = r.side
for t in (1, 2, 3, 4, 5):
    r.next_point(PC(), pos(me2), target, None, "g", t, me2)
assert r.side == s0
print("stuck detection OK")

# --- a working navigation mesh is used first
moves = []
class Handle:
    def ClearConstraints(s): pass
    def FindPath(s): return (True, None, 0)
    def SetFinalDestination(s, v): pass
    def GetNextMoveLocation(s, v, arrive): moves.append(1); return (True, NS(X=300.0, Y=-250.0, Z=0.0))
class NavPC:
    NavigationHandle = Handle()
orig_find = us.find_class
us.find_class = lambda n: (NS(ClassDefaultObject=NS(TowardPoint=lambda h, g: True, AtLocation=lambda h, g, d: True))
                           if n in ("NavMeshPath_Toward", "NavMeshGoal_At") else orig_find(n))
notes.clear(); r = NAV.Route()
p = r.next_point(NavPC(), (0, 0, 0), target, None, "goal", 0.0, Pawn([wall]))
us.find_class = orig_find
assert p == (300.0, -250.0, 0.0) and r.source == "navmesh" and moves, (p, r.source)
assert any("using the navigation mesh" in n for n in notes)
print("navigation mesh OK")
print("ALL ROUND 15 TESTS OK")
