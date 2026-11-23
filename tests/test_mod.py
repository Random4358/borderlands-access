"""Offline test: stub the SDK, import the mod, drive fake game state through tick/input."""
import enum, math, sys, types, time
from types import SimpleNamespace as NS

root = sys.argv[1]
sys.path.insert(0, root)

# ---- stubs
class EInputEvent(enum.IntEnum):
    IE_Pressed = 0; IE_Released = 1; IE_Repeat = 2

class _Opt:
    def __init__(self, ident, value=None, *a, **k): self.identifier = ident; self.value = value; self.k = k

mb = types.ModuleType("mods_base")
for n in ("BoolOption", "DropdownOption", "SliderOption", "ButtonOption"):
    setattr(mb, n, _Opt)
mb.GroupedOption = lambda ident, children, **k: NS(identifier=ident, children=children)
mb.EInputEvent = EInputEvent
binds = []
def keybind(ident, key=None, callback=None, **k):
    b = NS(identifier=ident, key=key, callback=callback); binds.append(b); return b
mb.keybind = keybind
built = {}
mb.build_mod = lambda **k: built.update(k) or NS(save_settings=lambda: None)
world = NS()
mb.get_pc = lambda: world.pc
sys.modules["mods_base"] = mb

us = types.ModuleType("unrealsdk")
us.make_struct = lambda name, **f: NS(**f)
us.find_all = lambda cn, exact=True: []
hk = types.ModuleType("unrealsdk.hooks")
class Type(enum.Enum): PRE = 0; POST = 1
hk.Type = Type; hk.Block = object()
added = []
hk.add_hook = lambda name, kind, ident, cb: added.append(name)
hk.remove_hook = lambda *a: None
us.hooks = hk
sys.modules["unrealsdk"] = us; sys.modules["unrealsdk.hooks"] = hk

# ---- fake world
class Pawn:
    def __init__(self, name, loc, hp=100, player=False):
        self.Name = name; self.Location = NS(X=loc[0], Y=loc[1], Z=loc[2]); self.hp = hp
        self.Class = NS(Name="WillowPlayerPawn" if player else "WillowAIPawn")
        self.BaseEyeHeight = 60; self.NextPawn = None; self.Velocity = NS(X=200, Y=0, Z=0)
        self.bDeleteMe = False; self.bHidden = False; self.Controller = None
        self.AIClass = NS(DefaultDisplayName=f"Bandit {name}"); self.Weapon = None
        self.CylinderComponent = NS(CollisionHeight=90)
    def GetHealth(self): return self.hp
    def GetMaxHealth(self): return 100
    def FastTrace(self, end, start): return not (end.X - start.X > 200)  # wall 2 m ahead (+X)

me = Pawn("me", (0, 0, 0), hp=20, player=True)
e1 = Pawn("e1", (1000, 0, 60))      # dead ahead at eye height
e2 = Pawn("e2", (0, 1500, 60))      # to the right (+Y)
e3 = Pawn("e3", (-800, 0, 60))      # behind
me.NextPawn = e1; e1.NextPawn = e2; e2.NextPawn = e3
class PC:
    def __init__(self):
        self.Pawn = me; self.Rotation = NS(Pitch=0, Yaw=0, Roll=0)
        self.WorldInfo = NS(PawnList=me, GetMapName=lambda b: "Glacial_P"); self.PlayerInput = None
    def LineOfSightTo(self, p): return p is not e3
    def SetRotation(self, r): self.Rotation = r
world.pc = PC()

import bl2_access as m
from bl2_access import game, controls, hooks
from bl2_access.audio import audio
played = []
audio.play = lambda group, data: played.append((group, len(data)))
said = []
m.speaker.say = lambda t, interrupt=True: said.append(t)

m.on_enable()
print("hooks:", len(added), "keybinds:", len(binds), "options groups:", len(built["options"]))
for _ in range(5):
    hooks._last_tick = 0
    hooks.on_tick(None, None, None, None)
    time.sleep(0.02)
f = m.feats
print("enemies:", [(e.key, round(e.rel.metres), round(e.rel.pan, 2), e.rel.behind, e.visible) for e in f.enemies])
print("locked:", f.locked_key)
print("said:", said)
print("played groups:", sorted({g for g, _ in played}))
assert f.enemies[0].key == "e3" and f.enemies[0].rel.behind
assert f.locked_key == "e1"
r2 = [e for e in f.enemies if e.key == "e2"][0]
assert r2.rel.pan > 0.99, r2.rel.pan
assert any(g == "nav" for g, _ in played), "wall click expected"
assert any("Windshear" in s for s in said) and "Low health" in said

# controller combo: hold Back + A -> snap aim to nearest visible (e1, since e3 hidden)
said.clear()
h = hooks.on_input
def press(k, ev): return h(None, NS(Key=k, Event=ev, ControllerId=0), None, None)
assert press("XboxTypeS_Back", EInputEvent.IE_Pressed) is not None
assert press("XboxTypeS_A", EInputEvent.IE_Pressed) is not None
assert press("XboxTypeS_A", EInputEvent.IE_Released) is not None
press("XboxTypeS_Back", EInputEvent.IE_Released)
print("after snap:", said, "yaw", world.pc.Rotation.Yaw)
# A pressed alone without modifier passes through
assert press("XboxTypeS_A", EInputEvent.IE_Pressed) is None
# Back + Start help
said.clear(); press("XboxTypeS_Back", EInputEvent.IE_Pressed); press("XboxTypeS_Start", EInputEvent.IE_Pressed)
print("help:", said[0][:120], "...")
# turn to face e2 then check snap uses aim rotation math
p, y = game.aim_rotation((0, 0, 60), (0, 1500, 60)); assert y == 16384 and p == 0, (p, y)
print("clock right:", game.clock(math.pi / 2), "| behind:", game.clock(math.pi))
f.report_status(); f.report_enemies(); print(said[-2:])
m.on_disable()
print("ALL OK")


