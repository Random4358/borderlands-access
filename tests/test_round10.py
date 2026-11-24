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



# ================================================================ round 10: steady enemy tones + lock-on aim
import math
from array import array
from bl2_access import audio as A
from bl2_access.audio import audio as eng
from bl2_access.combat_sounds import tones, aim_state

def samples(b):
    a = array("h"); a.frombytes(b); return a
def energy(b):
    a = samples(b); return sum(abs(a[i]) for i in range(0, len(a), 2)), sum(abs(a[i]) for i in range(1, len(a), 2))
def max_step(a, ch):
    return max(abs(a[i + 2] - a[i]) for i in range(ch, len(a) - 2, 2))

# --- tones join cleanly, including when the voice or pitch changes between segments
for k1, c1, k2, c2 in [("enemy", 32, "enemy", 34), ("enemy", 30, "enemy_near", 33), ("enemy_near", 40, "enemy_locked", 80),
                       ("enemy_locked", 80, "enemy", 28)]:
    for step in range(4):
        a = samples(A.tone_segment(k1, c1, step, 0.2, 0.7, False)); b = samples(A.tone_segment(k2, c2, step + 1, 0.25, 0.7, False))
        for ch in (0, 1):
            assert abs(b[ch] - a[-2 + ch]) <= max(max_step(a, ch), max_step(b, ch)) * 1.05 + 50, (k1, k2, step)
assert A.enemy_cycles(0) == 32 and A.enemy_cycles(30) == 64 and A.enemy_cycles(-30) == 16 and A.enemy_cycles(90) == 64
assert A.enemy_cycles(10) > 32 > A.enemy_cycles(-10)
assert sum(energy(A.tone_segment("enemy", 32, 0, 0, 0.7, True))) < sum(energy(A.tone_segment("enemy", 32, 0, 0, 0.7, False)))
print("tone synthesis OK")

class FakeStream:
    def __init__(s): s.q = []; s.fed = []
    def ahead(s): return len(s.q) * A.SEG
    def feed(s, b): s.q.append(b); s.fed.append(b)
    def stop(s): s.q = []
    def play_out(s): s.q = s.q[1:]
eng.streams = [FakeStream() for _ in range(A.STREAMS)]
eng.combat_streams = [FakeStream() for _ in range(A.COMBAT_STREAMS)]; eng.ok = True

def cls(name, supers=()):
    chain = [NS(Name=name)] + [NS(Name=s) for s in supers]
    return NS(Name=name, _superfields=lambda: chain, _properties=lambda: [])
class Pawn:
    def __init__(s, name, loc, player=False):
        s.Name = name; s.Location = NS(X=loc[0], Y=loc[1], Z=loc[2]); s.seen = True
        s.Class = cls("WillowPlayerPawn" if player else "WillowAIPawn", ["Pawn"]); s.player = player
        s.BaseEyeHeight = 0; s.NextPawn = None; s.Velocity = NS(X=0, Y=0, Z=0); s.bDeleteMe = False; s.bHidden = False
        s.Controller = None; s.Weapon = None; s.CylinderComponent = NS(CollisionHeight=90); s.AIClass = NS(DefaultDisplayName=name)
    def GetHealth(s): return 100
    def GetMaxHealth(s): return 100
    def IsEnemy(s, o): return not getattr(o, "player", False) if s.player else True
    def FastTrace(s, e, st): return True
    @property
    def LastRenderTime(s): return 100.0 if getattr(s, "seen", True) else 40.0   # the game skips drawing hidden things
me = Pawn("me", (0, 0, 0), player=True)
ahead_e = Pawn("Bandit", (1000, 0, 0))          # dead centre: on target
near_e = Pawn("Psycho", (1000, 90, 0))          # ~5 degrees right: nearly
side_e = Pawn("Goliath", (0, 1200, 0))          # 90 degrees right
high_e = Pawn("Nomad", (900, -300, 500))        # up and to the left
hid_e = Pawn("Marauder", (700, 400, 0)); hid_e.seen = False
chain = [me, ahead_e, near_e, side_e, high_e, hid_e]
for a, b in zip(chain, chain[1:]): a.NextPawn = b
objects.clear()
class PC:
    def __init__(s):
        s.Pawn = me; s.Rotation = NS(Pitch=0, Yaw=0, Roll=0); s.PlayerInput = None
        s.WorldInfo = NS(PawnList=me, GetMapName=lambda b: "Glacial_P", Pauser=None, GRI=NS(), TimeSeconds=100.1)
        s.GFxUIManager = NS(FindFocusMovie=lambda: focus.movie)
    def LineOfSightTo(s, p): return False   # like in the game: never works through the SDK
    def SetRotation(s, r): s.Rotation = r
focus = NS(movie=None)
world.pc = PC()
f = m.feats
for o in ("opt_npc_sounds", "opt_npc_talk", "opt_walls", "opt_ledges", "opt_jump", "opt_low_health",
          "opt_loot_sounds", "opt_container_sounds", "opt_interactive_sounds", "opt_quest_item_sounds"):
    getattr(m, o).value = False
m.opt_radar.value = True; m.opt_targeting.value = True; m.opt_enemy_sound.value = "Steady tones"
m.opt_radar_max.value = 4; m.opt_radar_hidden.value = True; m.opt_radar_range.value = 40
m.opt_aim_mode.value = "Aim assist"; m.opt_speak_target.value = True
m.controls.menus.open.clear()
def tick():
    m.hooks._last_tick = 0; m.hooks.on_tick(None, None, None, None)
def drain():
    for st in eng.combat_streams: st.q = []

played.clear(); said.clear()
tick()
by_name = {e.key: e for e in f.enemies}
print("states:", {k: aim_state(e) for k, e in by_name.items()})
assert aim_state(by_name["Bandit"]) == "enemy_locked"
assert aim_state(by_name["Psycho"]) == "enemy_near"
assert aim_state(by_name["Goliath"]) == "enemy"
assert set(tones.voices) == {"Bandit", "Psycho", "Nomad", "Marauder"}, set(tones.voices)   # nearest 4
v = tones.voices
assert v["Bandit"].kind == "enemy_locked" and v["Bandit"].cycles == A.LOCKED_CYCLES
assert v["Psycho"].kind == "enemy_near" and v["Psycho"].pan > 0
assert v["Nomad"].cycles > A.ENEMY_BASE and v["Nomad"].pan < 0          # above you: higher; left
assert v["Marauder"].muffled and not v["Bandit"].muffled                  # behind cover: muffled
# off screen the game draws nothing, whatever is in the way: not called "behind cover"
side_e.seen = False; tick(); assert {e.key: e.visible for e in f.enemies}["Goliath"] is True; side_e.seen = True; tick()
for st in eng.combat_streams:
    assert st.ahead() >= 0.1 - 1e-9
assert played.count("target") == 1 and said[-1][0] == "Bandit"          # one lock click + name, no ticking
# the tone keeps going (no restart) and follows the aim: turn so the Goliath is ahead
n = played.count("target")
for _ in range(5):
    drain(); tick()
assert played.count("target") == n                                       # tones mode: no repeated ticks
m.opt_radar_max.value = 4; hid_e.seen = True
world.pc.Rotation = NS(Pitch=0, Yaw=16384, Roll=0)                        # face +Y
drain(); tick()
assert aim_state({e.key: e for e in f.enemies}["Goliath"]) == "enemy_locked"
print("tones follow aim OK")

# radar beep mode: tones fade out, beeps return
world.pc.Rotation = NS(Pitch=0, Yaw=0, Roll=0)
m.opt_enemy_sound.value = "Radar beeps"; played.clear(); f.next_ping.clear()
drain(); tick()
assert not tones.voices and "radar" in played, played
m.opt_enemy_sound.value = "Steady tones"; drain(); tick(); assert tones.voices
# menus: silent
focus.movie = NS(Name="StatusMenuExGFxMovie_0", Class=cls("StatusMenuExGFxMovie", ["GFxMoviePlayer"]))
tick(); assert not tones.voices
focus.movie = None; drain(); tick(); assert tones.voices
print("modes + menus OK")

# --- lock-on: holding aim follows one enemy; it stays on it; Back+A switches; letting go releases
m.opt_aim_mode.value = "Lock-on"
world.pc.Rotation = NS(Pitch=0, Yaw=3000, Roll=0)    # looking ~16 degrees right: Psycho is nearest the crosshair
said.clear(); f.ads_held = True
drain(); tick()
assert f.lock_on_key == "Psycho", f.lock_on_key
assert said[-1][0] == "Locked on Psycho", said
def yaw_deg(): return game_deg(world.pc.Rotation.Yaw)
def game_deg(uu): return ((uu + 32768) % 65536 - 32768) * 360 / 65536
assert abs(yaw_deg() - math.degrees(math.atan2(90, 1000))) < 0.5, yaw_deg()   # view now on the Psycho
# the Bandit is now 5 degrees off; lock-on stays on the Psycho
for _ in range(3):
    drain(); tick()
assert f.lock_on_key == "Psycho" and abs(yaw_deg() - 5.14) < 0.5
# Psycho moves; the view follows
near_e.Location = NS(X=1000, Y=300, Z=0); drain(); tick()
assert abs(yaw_deg() - math.degrees(math.atan2(300, 1000))) < 0.5, yaw_deg()
# Psycho goes behind cover: lock-on picks the enemy nearest the crosshair instead
near_e.seen = False; drain(); tick()
assert f.lock_on_key != "Psycho" and said[-1][0].startswith("Locked on"), (f.lock_on_key, said[-1])
near_e.seen = True
# Back + A switches target in lock-on mode
before = f.lock_on_key; f.snap_aim(); assert f.lock_on_key and f.lock_on_key != before, (before, f.lock_on_key)
switched = f.lock_on_key; drain(); tick(); assert f.lock_on_key == switched     # and the lock stays on it
f.snap_aim(); assert f.lock_on_key not in (switched, None)
# releasing aim stops following
f.ads_held = False; drain(); tick(); assert f.lock_on_key is None
r = world.pc.Rotation.Yaw; near_e.Location = NS(X=1000, Y=-500, Z=0); drain(); tick()
assert world.pc.Rotation.Yaw == r                                          # no longer moved by the mod
print("lock-on OK")

# --- aim assist still eases toward the target; Off does nothing
m.opt_aim_mode.value = "Aim assist"; m.opt_aim_assist.value = 40
world.pc.Rotation = NS(Pitch=0, Yaw=600, Roll=0)   # ~3.3 degrees right of the Bandit
f.ads_held = True; drain(); tick()
y = game_deg(world.pc.Rotation.Yaw); assert 0 < y < 3.3, y
m.opt_aim_mode.value = "Off"; world.pc.Rotation = NS(Pitch=0, Yaw=600, Roll=0); drain(); tick()
assert world.pc.Rotation.Yaw == 600
f.ads_held = False
print("aim assist / off OK")
m.on_disable(); assert not tones.voices
print("ALL ROUND 10 TESTS OK")
