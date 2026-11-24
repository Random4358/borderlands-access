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
def find_class(name):
    owner = NS(Name=name, Outer=NS(Name="WillowGame"))
    return NS(_find=lambda fn: NS(Outer=owner))
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

import bl2_access as m
from bl2_access.menu_reader import reader
from bl2_access import features as F
said = []
m.speaker.say = lambda t, interrupt=True: said.append((t, interrupt))
played = []
m.audio_engine.play = lambda group, data: played.append(group)
m.on_enable()
m.opt_enemy_sound.value = "Radar beeps"  # these checks are for the beep radar

def call(cls, fn, obj, kind=Type.PRE, **args):
    a = NS(**args); props = [NS(Name=k) for k in args]
    a._type = NS(_properties=lambda: props)
    hooked[(f"WillowGame.{cls}:{fn}", kind)](obj, a, None, None)


# ================================================================ round 5: NPC sounds + talk prompt
class Pawn:
    def __init__(s, name, loc, player=False, hostile=True):
        s.Name = name; s.Location = NS(X=loc[0], Y=loc[1], Z=loc[2])
        s.Class = NS(Name="WillowPlayerPawn" if player else "WillowAIPawn"); s.hostile = hostile
        s.BaseEyeHeight = 60; s.NextPawn = None; s.Velocity = NS(X=0, Y=0, Z=0); s.bDeleteMe = False; s.bHidden = False
        s.Controller = None; s.AIClass = NS(DefaultDisplayName=name); s.Weapon = None
        s.CylinderComponent = NS(CollisionHeight=90)
    def GetHealth(s): return 100
    def GetMaxHealth(s): return 100
    def FastTrace(s, end, start): return True
    def IsEnemy(s, other):
        if NO_ISENEMY[0]:
            raise AttributeError("IsEnemy")
        return getattr(other, "hostile", True)
NO_ISENEMY = [False]
def move(p, x, y): p.Location = NS(X=x, Y=y, Z=0)

me = Pawn("me", (0, 0, 0), player=True)
clap = Pawn("Claptrap", (1000, 0, 0), hostile=False)
bandit = Pawn("Bandit", (1500, 300, 0))
me.NextPawn = clap; clap.NextPawn = bandit

class PC:
    def __init__(s):
        s.Pawn = me; s.Rotation = NS(Pitch=0, Yaw=0, Roll=0); s.PlayerInput = None
        s.WorldInfo = NS(PawnList=me, GetMapName=lambda b: "Glacial_P", Pauser=None, GRI=NS())
        s.GFxUIManager = NS(FindFocusMovie=lambda: None)
    def LineOfSightTo(s, p): return True
    def SetRotation(s, r): s.Rotation = r
world.pc = PC()
objects.clear()
f = m.feats
from bl2_access import game
game._is_enemy_works = None
f.s.walls = f.s.ledges = f.s.jump = False; f.s.low_health = False

def tick():
    m.hooks._last_tick = 0
    m.hooks.on_tick(None, None, None, None)
def fresh():
    played.clear(); f.npc_next.clear(); f.next_ping.clear()

# 1) friendly 10 m ahead gets the NPC chime; the bandit gets the radar, never the chime
said.clear(); fresh(); tick()
assert [n.key for n in f.npcs] == ["Claptrap"], [n.key for n in f.npcs]
assert [e.key for e in f.enemies] == ["Bandit"], [e.key for e in f.enemies]
assert played.count("npc") == 1 and "radar" in played, played
assert not [s for s, _ in said if s.startswith("Talk to")]           # 10 m: too far to talk
print("chime + radar:", played)

# 2) walk up to Claptrap (2 m, in front): "Talk to Claptrap", exactly once
move(clap, 200, 0); said.clear(); tick(); tick(); tick()
talks = [s for s, _ in said if s.startswith("Talk to")]
print("talk:", talks); assert talks == ["Talk to Claptrap. Press X"]
# 3) step back to 3 m (still within reset distance): no repeat; walk away 6 m then back: announced again
move(clap, 300, 0); tick(); assert len([s for s, _ in said if s.startswith("Talk to")]) == 1
move(clap, 600, 0); tick(); move(clap, 200, 0); tick()
assert len([s for s, _ in said if s.startswith("Talk to")]) == 2
# 4) right next to you but behind: no announcement (you're not facing them)
move(clap, 1000, 0); tick(); said.clear(); move(clap, -200, 0); tick()
assert not [s for s, _ in said if s.startswith("Talk to")], said
# 5) the game exposes its Use target: only announce when it's this person
move(clap, 1000, 0); tick(); said.clear()
other = NS(Name="Chest")
world.pc.CurrentUsableObject = other
move(clap, 200, 0); tick(); assert not [s for s, _ in said if s.startswith("Talk to")], said
world.pc.CurrentUsableObject = clap
tick(); assert [s for s, _ in said if s.startswith("Talk to")] == ["Talk to Claptrap. Press X"], said
del world.pc.CurrentUsableObject
# 6) options off
m.opt_npc_sounds.value = False; m.opt_npc_talk.value = False
move(clap, 1000, 0); fresh(); said.clear(); tick(); move(clap, 200, 0); tick()
assert "npc" not in played and not [s for s, _ in said if s.startswith("Talk to")], (played, said)
m.opt_npc_sounds.value = True; m.opt_npc_talk.value = True
# 7) game can't tell friend from foe: no NPC chime at all (never chime at enemies)
NO_ISENEMY[0] = True; game._is_enemy_works = None
move(clap, 1000, 0); fresh(); tick()
assert not f.npcs and "npc" not in played, (f.npcs, played)
NO_ISENEMY[0] = False; game._is_enemy_works = None
# 8) inside a menu: silent
inv = NS(Class=NS(Name="StatusMenuExGFxMovie"), Name="inv", _path_name=lambda: "inv")
m.controls.menus.opened(inv); fresh(); tick()
assert "npc" not in played, played
m.controls.menus.closed(inv)
m.on_disable()
print("ALL ROUND 5 TESTS OK")


