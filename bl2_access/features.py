"""In-world accessibility features: enemy radar, targeting, aim assist, wall/ledge probes,
points of interest, and status readouts. Everything runs from ``Features.tick``."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

from . import audio as snd
from . import game
from .audio import audio
from .speech import speech


@dataclass
class Settings:
    """Plain values copied from the mod options each tick (keeps this module SDK-free)."""

    volume: float = 0.8
    radar: bool = True
    radar_range: float = 4000.0
    radar_max: int = 3
    radar_hidden: bool = True
    treat_all_ai_as_enemies: bool = True
    targeting: bool = True
    speak_target: bool = True
    aim_assist: float = 0.4
    aim_mode: str = "assist"         # while aiming down sights: "assist", "lock" or "off"
    enemy_tones: bool = True         # steady enemy tones (True) or the older radar beeps (False)
    enemy_volume: float = 0.7
    walls: bool = True
    wall_distance: float = 250.0
    ledges: bool = True
    npc_sounds: bool = True
    npc_range: float = 2500.0    # unreal units
    npc_max: int = 2
    npc_talk: bool = True
    interact_prompts: bool = True    # "Chest. Press X to open" when you can use something
    nav_assist: bool = False         # Modifier + right stick click turns you toward the objective
    jump: bool = True
    jump_height: float = 100.0   # unreal units the player clears with a jump
    speak_jump: bool = False
    low_health: bool = True
    low_health_pct: float = 30.0
    loot_sounds: bool = True         # continuous sounds for loot on the ground, by type
    container_sounds: bool = True    # chests, lockers, crates...
    interactive_sounds: bool = True  # doors, switches, vendors, fast travel
    quest_item_sounds: bool = True
    object_range: float = 1500.0     # unreal units
    object_max: int = 4
    object_volume: float = 0.7


@dataclass
class Snapshot:
    pc: Any
    pawn: Any
    eye: tuple[float, float, float]
    yaw: float
    pitch: float


@dataclass
class Enemy:
    ptr: Any  # WeakPointer: enemies die and levels unload between frames
    key: str
    pos: tuple[float, float, float]
    rel: game.Relative
    visible: bool

    @property
    def actor(self) -> Any:
        return game.deref(self.ptr)


@dataclass
class POI:
    name: str
    ptr: Any  # WeakPointer (None for text-only entries such as the mission summary)
    category: str = "Other"
    text: str = ""  # text-only entries: what to say instead of a distance and direction
    pos: tuple[float, float, float] | None = None  # fixed map position (quest waypoints)

    @property
    def actor(self) -> Any:
        return game.deref(self.ptr)

    def position(self) -> tuple[float, float, float] | None:
        if self.ptr is not None:
            p = game.location(self.actor)
            if p is not None:
                return p
        return self.pos

    @property
    def locatable(self) -> bool:
        return self.ptr is not None or self.pos is not None


# ------------------------------------------------------------------------- scanner categories
QUEST = "Quest objectives"
CATEGORY_ORDER = [
    QUEST, "People", "Weapons and gear", "Ammo and health", "Money", "Containers",
    "Vendors", "Travel", "Doors and switches", "Other",
]

# Checked in order against the object's class + definition name (lower-case). First match wins.
OBJECT_RULES = [
    (QUEST, ("mission", "quest", "objective", "echo", "audiolog", "datalog")),
    ("Vendors", ("vending", "vendor", "blackmarket", "bank", "slotmachine", "slot_machine", "goldenchest", "golden")),
    ("Travel", ("fasttravel", "fast_travel", "teleport", "vehiclespawn", "catcharide", "catch_a_ride",
                "newu", "new_u", "resurrect", "respawn", "savestation", "save_station")),
    ("Containers", ("chest", "locker", "crate", "box", "safe", "container", "dumpster", "cabinet",
                    "toilet", "cooler", "fridge", "lootpile", "pile", "bag", "stash", "loot")),
    ("Doors and switches", ("door", "switch", "button", "lever", "valve", "elevator", "gate", "lift",
                            "console", "terminal", "panel")),
]
PICKUP_RULES = [
    (QUEST, ("mission", "quest")),
    ("Money", ("money", "cash", "currency", "eridium", "dollar", "moonstone")),
    ("Ammo and health", ("ammo", "health", "insta", "healing", "medkit")),
]
GEAR_CLASSES = ("WillowWeapon", "WillowShield", "WillowGrenadeMod", "WillowClassMod",
                "WillowArtifact", "WillowEquipAbleItem")
NAME_PREFIXES = r"^(InteractiveObj(ect)?s?_|IO_|Obj_|ObjDef_|Def_|GD_|Willow)"


def _clean_def_name(raw: str) -> str:
    import re

    raw = re.sub(NAME_PREFIXES, "", raw, flags=re.I)
    raw = re.sub(r"_?\d+$", "", raw)
    raw = raw.replace("_", " ")
    raw = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", raw)
    return re.sub(r"\s+", " ", raw).strip()


def _definition_name(obj: Any) -> str:
    for getter in (lambda o: o.InteractiveObjectDefinition.Name, lambda o: o.DefinitionData.ItemDefinition.Name):
        try:
            v = getter(obj)
            if v:
                return str(v)
        except Exception:
            continue
    return ""


# What the Use button does for each scanner category (None: no prompt). Money and ammo are
# picked up just by walking over them, so they don't get one.
USE_VERBS = {
    "Containers": "open", "Vendors": "shop", "Travel": "use", "Doors and switches": "use",
    "Quest objectives": "use", "Weapons and gear": "pick up", "Other loot": "pick up",
}


def use_button() -> str:
    from .controls import state

    return "E" if getattr(state, "last_device", "pad") == "keyboard" else "X"


def prompt_text(name: str, verb: str) -> str:
    b = use_button()
    if verb == "pick up":
        return f"{name}. Press {b} to pick up, hold {b} to equip"
    return f"{name}. Press {b} to {verb}"


def nearby_usables(snap: "Snapshot", radius: float) -> list:
    """(weak pointer, key, verb, name) for things within radius you could use."""
    from .object_sounds import _still_usable

    out = []

    def add(actor: Any, cat: str | None, name: str, pickup: bool) -> None:
        if pickup and cat == "Other":
            cat = "Other loot"
        verb = USE_VERBS.get(cat or "")
        if verb is None:
            return
        if pickup and cat == "Quest objectives":
            verb = "pick up"
        pos = game.location(actor)
        if pos is None or game.relative(snap.eye, snap.yaw, snap.pitch, pos).dist > radius:
            return
        if cat == "Containers" and not _still_usable(actor):
            return
        try:
            key = actor._path_name()
        except Exception:
            key = str(id(actor))
        out.append((game.weak(actor), key, verb, name or "Object"))

    for a in game.world_actors(["WillowInteractiveObject", "WillowVendingMachineBase"]):
        cat, name = categorize_object(a)
        add(a, cat, name, False)
    for a in game.world_actors(["WillowPickup"]):
        cat, name = categorize_pickup(a)
        add(a, cat, name, True)
    return out


_seen_kinds: set[str] = set()


def _first_sighting(key: str) -> bool:
    """Log each kind of object once, so the diagnostic log isn't filled by the scanner."""
    if key in _seen_kinds:
        return False
    _seen_kinds.add(key)
    return True


def categorize_object(obj: Any) -> tuple[str | None, str]:
    """(category, spoken name) for an interactive object, or (None, '') to skip it."""
    from . import trace

    cls = game.class_name(obj)
    defn = _definition_name(obj)
    hay = f"{cls} {defn}".lower().replace(" ", "")
    if _first_sighting(f"o {cls} {defn}"):
        trace.note(f"scan object class={cls} def={defn}")
    cat = "Vendors" if "vending" in cls.lower() else None
    if cat is None:
        for name, words in OBJECT_RULES:
            if any(w in hay for w in words):
                cat = name
                break
    name = _clean_def_name(defn) if defn else ""
    if not name or name.lower() in ("interactive object", "object"):
        name = game.display_name(obj)
    return cat or "Other", name or "Object"


def categorize_pickup(obj: Any) -> tuple[str | None, str]:
    """(category, spoken name) for an item lying on the ground."""
    from . import trace

    try:
        inv = obj.Inventory
    except Exception:
        return None, ""
    if inv is None:
        return None, ""
    inv_cls = game.class_name(inv)
    defn = _definition_name(inv)
    name = game.display_name(inv) or _clean_def_name(defn)
    if _first_sighting(f"p {inv_cls} {defn}"):
        trace.note(f"scan pickup inv={inv_cls} def={defn} name={name}")
    hay = f"{inv_cls} {defn} {name}".lower().replace(" ", "")
    for cat, words in PICKUP_RULES:
        if any(w in hay for w in words):
            return cat, name
    if any(inv_cls.startswith(g) for g in GEAR_CLASSES):
        return "Weapons and gear", name
    return "Other", name


@dataclass
class Features:
    s: Settings = field(default_factory=Settings)
    ads_held: bool = False
    enemies: list[Enemy] = field(default_factory=list)
    next_ping: dict[str, float] = field(default_factory=dict)
    locked_key: str | None = None
    lock_on_key: str | None = None   # enemy the lock-on aim is following
    next_target_tick: float = 0.0
    next_wall: float = 0.0
    next_ledge_ok: float = 0.0
    next_jump_ok: float = 0.0
    npcs: list[Enemy] = field(default_factory=list)          # friendly characters in range
    npc_next: dict[str, float] = field(default_factory=dict)
    talk_key: str | None = None
    use_key: str | None = None       # object the interaction prompt last announced
    use_candidates: list = field(default_factory=list)
    next_use_scan: float = 0.0
    next_heartbeat: float = 0.0
    low_health_spoken: bool = False
    pois: list[POI] = field(default_factory=list)   # items in the current category
    categories: dict[str, list[POI]] = field(default_factory=dict)
    category: str = ""
    poi_index: int = -1
    beacon: bool = False
    next_beacon: float = 0.0
    snap_cycle: int = 0
    last_snap: float = 0.0
    last_tick: float = 0.0
    last_map: str = ""
    had_pawn: bool = False

    # ---------------------------------------------------------------- snapshot
    def snapshot(self) -> Snapshot | None:
        pc = game.pc()
        pawn = game.player_pawn(pc)
        if pc is None or pawn is None:
            return None
        eye = game.eye_position(pawn)
        if eye is None:
            return None
        try:
            yaw, pitch = game.view_angles(pc)
        except Exception:
            return None
        return Snapshot(pc, pawn, eye, yaw, pitch)

    # ---------------------------------------------------------------- main tick
    def tick(self) -> None:
        now = time.perf_counter()
        dt = min(0.1, now - self.last_tick) if self.last_tick else 0.0
        self.last_tick = now
        snap = self.snapshot()
        from .object_sounds import objects

        from .combat_sounds import tones

        from .navigation import beacon as nav_beacon

        if snap is None:  # menu or loading screen: drop anything that belongs to the old level
            objects.stop(fade=False)
            tones.stop(fade=False)
            nav_beacon.stop(fade=False)
            self.lock_on_key = None
            self.had_pawn = False
            self.enemies = []
            self.npcs = []
            self.talk_key = None
            self.locked_key = None
            return
        if not self.had_pawn:
            self.had_pawn = True
            self.on_spawn(snap)

        from .controls import menus

        if menus.world_sounds_paused():  # inventory, pause menu, vendor... keep the world quiet
            self.locked_key = None
            objects.stop()
            tones.stop()
            nav_beacon.stop()
            return

        objects.tick(self.s, snap, now)

        self.scan_enemies(snap)
        if self.s.radar and self.s.enemy_tones:
            tones.tick(self.enemies, self.s)
        else:
            tones.stop()
            if self.s.radar:
                self.radar(now)
        if self.s.npc_sounds or self.s.npc_talk:
            self.npc_cues(snap, now)
        if self.s.interact_prompts:
            self.interact_prompt(snap, now)
        if self.s.targeting:
            self.targeting(snap, now, dt)
        if self.s.walls or self.s.ledges or self.s.jump:
            self.probes(snap, now)
        if self.beacon:
            self.beacon_tick(snap, now)
        else:
            nav_beacon.stop()
        if self.s.low_health:
            self.health_alert(snap, now)

    def on_spawn(self, snap: Snapshot) -> None:
        name = game.map_name(snap.pc)
        if name and name != self.last_map:
            self.last_map = name
            self.pois = []
            self.categories = {}
            self.category = ""
            self.poi_index = -1
            self.beacon = False
            speech.say(f"Entered {name}")

    # ---------------------------------------------------------------- enemies
    def scan_enemies(self, snap: Snapshot) -> None:
        """One pass over every character: enemies for the radar, friendly NPCs for the chime."""
        found: list[Enemy] = []
        friends: list[Enemy] = []
        npc_range = self.s.npc_range
        for p in game.iter_pawns(snap.pc):
            if p == snap.pawn or not game.is_alive(p):
                continue
            friendly = game.is_friendly_npc(snap.pawn, p)
            if not friendly and not game.is_hostile(snap.pawn, p, self.s.treat_all_ai_as_enemies):
                continue
            pos = game.location(p)
            if pos is None:
                continue
            rel = game.relative(snap.eye, snap.yaw, snap.pitch, pos)
            if rel.dist > (npc_range if friendly else self.s.radar_range):
                continue
            try:
                key = str(p.Name)
            except Exception:
                key = str(id(p))
            entry = Enemy(game.weak(p), key, pos, rel, game.line_of_sight(snap.pc, p))
            (friends if friendly else found).append(entry)
        found.sort(key=lambda e: e.rel.dist)
        friends.sort(key=lambda e: e.rel.dist)
        self.enemies = found
        self.npcs = friends

    def npc_cues(self, snap: Snapshot, now: float) -> None:
        """Panned chime for the nearest friendly characters; 'Talk to <name>' when you're next to one."""
        shown = self.npcs[: self.s.npc_max] if self.s.npc_sounds else []
        keys = {n.key for n in shown}
        for k in list(self.npc_next):
            if k not in keys:
                del self.npc_next[k]
        for n in shown:
            if now < self.npc_next.get(n.key, 0.0):
                continue
            closeness = 1.0 - min(1.0, n.rel.dist / self.s.npc_range)
            vol = (0.2 + 0.6 * closeness) * self.s.volume * (1.0 if n.visible else 0.6)
            audio.play("npc", snd.npc_chime(n.rel.pan, vol, n.rel.behind))
            self.npc_next[n.key] = now + (2.0 - 1.4 * closeness)   # 2 s far away .. 0.6 s close

        if self.s.npc_talk:
            self.talk_prompt(snap)

    TALK_RANGE = 250.0    # ~2.5 m: close enough for the game's Use/Talk prompt
    TALK_RESET = 400.0    # walk this far away before the same person is announced again

    def talk_prompt(self, snap: Snapshot) -> None:
        if self.talk_key is not None:
            still_near = any(n.key == self.talk_key and n.rel.dist < self.TALK_RESET for n in self.npcs)
            if still_near:
                return
            self.talk_key = None
        usable = game.usable_target(snap.pc)
        for n in self.npcs:
            if n.rel.dist > self.TALK_RANGE:
                break
            if not n.visible or abs(n.rel.rel_yaw) > math.radians(60):
                continue
            actor = n.actor
            if actor is None:
                continue
            # If the game exposes what the Use prompt points at, only speak for that person.
            if usable is not None and usable != actor:
                continue
            self.talk_key = n.key
            audio.play("npc", snd.ui("select", self.s.volume * 0.6))
            speech.say(f"Talk to {game.display_name(actor)}. Press {use_button()}")
            return

    USE_RANGE = 220.0     # ~2 m: about where the game shows its Use prompt
    USE_KEEP = 330.0      # the same object isn't announced again until you've moved this far away
    USE_ANGLE = 50.0      # degrees either side of where you're looking

    def interact_prompt(self, snap: Snapshot, now: float) -> None:
        """When something usable is right in front of you, say what it is and which button uses
        it: "Red chest. Press X to open". Each object is announced once until you walk away."""
        if now >= self.next_use_scan:
            self.next_use_scan = now + 0.5
            self.use_candidates = nearby_usables(snap, 900.0)
        best = None
        for ptr, key, verb, name in self.use_candidates:
            actor = game.deref(ptr)
            pos = game.location(actor) if actor is not None else None
            if pos is None:
                continue
            rel = game.relative(snap.eye, snap.yaw, snap.pitch, pos)
            if key == self.use_key:
                if rel.dist > self.USE_KEEP or abs(math.degrees(rel.rel_yaw)) > self.USE_ANGLE + 25:
                    self.use_key = None  # walked away: it can be announced again
            if rel.dist > self.USE_RANGE or abs(math.degrees(rel.rel_yaw)) > self.USE_ANGLE:
                continue
            if not game.line_of_sight(snap.pc, actor):
                continue
            if best is None or rel.dist < best[0]:
                best = (rel.dist, key, verb, name)
        if best is None or best[1] == self.use_key:
            return
        _d, key, verb, name = best
        self.use_key = key
        audio.play("ui", snd.ui("prompt", self.s.volume))
        speech.say(prompt_text(name, verb), interrupt=False)

    def radar(self, now: float) -> None:
        shown = [e for e in self.enemies if e.visible or self.s.radar_hidden][: self.s.radar_max]
        keys = {e.key for e in shown}
        for k in list(self.next_ping):
            if k not in keys:
                del self.next_ping[k]
        for e in shown:
            due = self.next_ping.get(e.key, 0.0)
            if now < due:
                continue
            closeness = 1.0 - min(1.0, e.rel.dist / self.s.radar_range)
            interval = 1.2 - 0.95 * closeness            # 1.2 s far away .. 0.25 s up close
            vol = (0.25 + 0.75 * closeness) * self.s.volume * (1.0 if e.visible else 0.6)
            pitch = 2 ** max(-1.0, min(1.0, math.degrees(e.rel.elevation) / 45))
            audio.play("radar", snd.enemy_ping(e.rel.pan, vol, pitch, e.rel.behind, e.visible))
            self.next_ping[e.key] = now + interval

    def best_target(self, max_error_deg: float) -> Enemy | None:
        best = None
        for e in self.enemies:
            if not e.visible:
                continue
            if math.degrees(e.rel.aim_error) > max_error_deg:
                continue
            if best is None or e.rel.aim_error < best.rel.aim_error:
                best = e
        return best

    def targeting(self, snap: Snapshot, now: float, dt: float) -> None:
        target = self.best_target(15.0)
        locked = None
        if target is not None:
            # Lock cone shrinks with distance: roughly a body width (~60 uu) either side.
            lock_deg = max(1.5, math.degrees(math.atan2(60, target.rel.dist)))
            if math.degrees(target.rel.aim_error) <= lock_deg:
                locked = target

        # With steady enemy tones the tone itself changes when you're on target, so only the
        # moment of locking on gets a click (and the name); the ticking is for the beep mode.
        tones_on = self.s.radar and self.s.enemy_tones
        if locked is not None and locked.key != self.locked_key:
            audio.play("target", snd.ui("lock", self.s.volume * (0.6 if tones_on else 1.0)))
            if self.s.speak_target and locked.key != self.lock_on_key:
                speech.say(game.display_name(locked.actor), interrupt=True)
            self.next_target_tick = now + 0.2
        elif locked is None and self.locked_key is not None and not tones_on:
            audio.play("target", snd.ui("lost", self.s.volume * 0.6))
        elif locked is not None and now >= self.next_target_tick and not tones_on:
            audio.play("target", snd.ui("on_target", self.s.volume))
            self.next_target_tick = now + 0.15
        self.locked_key = locked.key if locked else None

        if not self.ads_held:
            self.lock_on_key = None
            return
        if self.s.aim_mode == "lock":
            self.lock_on(snap)
            return
        # Aim assist while aiming down sights: ease the view toward the best target.
        if self.s.aim_mode == "assist" and self.s.aim_assist > 0 and target is not None and dt > 0:
            want_pitch, want_yaw = game.aim_rotation(snap.eye, target.pos)
            cur_yaw = snap.yaw / game.RAD_PER_UU
            cur_pitch = snap.pitch / game.RAD_PER_UU
            dyaw = game.signed_uu(int(want_yaw - cur_yaw))
            dpitch = game.signed_uu(int(want_pitch - cur_pitch))
            k = min(1.0, self.s.aim_assist * 8 * dt)
            game.set_view(snap.pc, int(cur_pitch + dpitch * k), int(cur_yaw + dyaw * k))

    def lock_on(self, snap: Snapshot) -> None:
        """Lock-on aim: while you aim down sights, the view follows one enemy. It stays on the
        same enemy while you can see it; Back + A switches to the next one."""
        visible = [e for e in self.enemies if e.visible]
        if not visible:
            self.lock_on_key = None
            return
        target = next((e for e in visible if e.key == self.lock_on_key), None)
        if target is None:
            target = min(visible, key=lambda e: e.rel.aim_error)  # the one nearest your crosshair
            self.lock_on_key = target.key
            audio.play("target", snd.ui("lock", self.s.volume))
            if self.s.speak_target:
                speech.say(f"Locked on {game.display_name(target.actor)}", interrupt=True)
        pitch, yaw = game.aim_rotation(snap.eye, target.pos)
        game.set_view(snap.pc, pitch, yaw)

    # ---------------------------------------------------------------- probes
    def probes(self, snap: Snapshot, now: float) -> None:
        if now < self.next_wall:
            return
        self.next_wall = now + 0.3
        x, y, z = snap.eye
        z -= 20  # chest height so low cover counts as a wall
        if self.s.walls:
            for offset, pan in ((0.0, 0.0), (-math.pi / 2, -1.0), (math.pi / 2, 1.0)):
                a = snap.yaw + offset
                for frac, vol in ((0.5, 1.0), (1.0, 0.5)):
                    d = self.s.wall_distance * frac
                    end = (x + math.cos(a) * d, y + math.sin(a) * d, z)
                    clear = game.fast_trace(snap.pawn, (x, y, z), end)
                    if clear is False:
                        audio.play("nav", snd.wall_click(pan, vol * self.s.volume * 0.7))
                        break
        moving = self.moving(snap.pawn)
        if not moving or not (self.s.ledges or self.s.jump):
            return
        try:
            feet = snap.eye[2] - float(snap.pawn.BaseEyeHeight) - float(snap.pawn.CylinderComponent.CollisionHeight)
        except Exception:
            feet = snap.eye[2] - 150
        cx, cy = math.cos(snap.yaw), math.sin(snap.yaw)

        def ground_at(d: float) -> bool:
            """Is there floor at distance d ahead, no more than a step down?"""
            px, py = x + cx * d, y + cy * d
            return game.fast_trace(snap.pawn, (px, py, feet + 30), (px, py, feet - 300)) is False

        # Jump cue 1: an obstacle you can hop over - blocked at knee height, clear at jump height.
        if self.s.jump and now >= self.next_jump_ok:
            knee = feet + 40
            top = feet + self.s.jump_height
            reach = 160
            knee_blocked = game.fast_trace(snap.pawn, (x, y, knee), (x + cx * reach, y + cy * reach, knee)) is False
            top_clear = game.fast_trace(snap.pawn, (x, y, top), (x + cx * reach, y + cy * reach, top)) is True
            if knee_blocked and top_clear:
                self.jump_cue(now, "Jump over")
                return

        # Drop ahead: a gap you can jump across gets the jump cue; anything else is a ledge.
        if game.fast_trace(snap.pawn, (x + cx * 120, y + cy * 120, feet + 30),
                           (x + cx * 120, y + cy * 120, feet - 300)) is True:
            if self.s.jump and now >= self.next_jump_ok and any(ground_at(d) for d in (260, 360, 460)):
                self.jump_cue(now, "Jump the gap")
            elif self.s.ledges and now >= self.next_ledge_ok:
                audio.play("alert", snd.ledge_warning(0.0, self.s.volume))
                self.next_ledge_ok = now + 1.5

    def jump_cue(self, now: float, words: str) -> None:
        audio.play("alert", snd.ui("jump", self.s.volume))
        if self.s.speak_jump:
            speech.say(words, interrupt=False)
        self.next_jump_ok = now + 1.2
        self.next_ledge_ok = now + 1.2

    @staticmethod
    def moving(pawn: Any) -> bool:
        try:
            v = pawn.Velocity
            return math.hypot(v.X, v.Y) > 60
        except Exception:
            return True

    # ---------------------------------------------------------------- health
    def health_alert(self, snap: Snapshot, now: float) -> None:
        h = game.health(snap.pawn)
        if not h or h[1] <= 0:
            return
        pct = 100 * h[0] / h[1]
        if 0 < pct < self.s.low_health_pct:
            if not self.low_health_spoken:
                speech.say("Low health", interrupt=False)
                self.low_health_spoken = True
            if now >= self.next_heartbeat:
                audio.play("alert", snd.ui("heartbeat", self.s.volume))
                self.next_heartbeat = now + (0.6 if pct < 15 else 1.0)
        elif pct >= self.s.low_health_pct + 5:
            self.low_health_spoken = False

    # ---------------------------------------------------------------- points of interest
    def scan_pois(self, snap: Snapshot) -> None:
        """Find everything nearby and sort it into categories (see categorize())."""
        from . import trace

        found: list[POI] = []
        for p in game.iter_pawns(snap.pc):
            if p == snap.pawn or not game.is_alive(p):
                continue
            if game.is_player_pawn(p):
                found.append(POI(game.display_name(p), game.weak(p), "People"))
            elif not game.is_hostile(snap.pawn, p, False):
                found.append(POI(game.display_name(p), game.weak(p), "People"))
        for a in game.world_actors(["WillowInteractiveObject", "WillowVendingMachineBase"]):
            cat, name = categorize_object(a)
            if cat:
                found.append(POI(name, game.weak(a), cat))
        for a in game.world_actors(["WillowPickup"]):
            cat, name = categorize_pickup(a)
            if cat:
                found.append(POI(name, game.weak(a), cat))

        def dist(poi: POI) -> float:
            pos = poi.position()
            if pos is None:
                return 1e12
            return game.relative(snap.eye, snap.yaw, snap.pitch, pos).dist

        found = [p for p in found if dist(p) < 6000]
        found.sort(key=dist)
        self.categories = {}
        for p in found:
            self.categories.setdefault(p.category, []).append(p)
        self._add_mission_entries(snap)
        trace.note("scan: " + ", ".join(f"{c} {len(v)}" for c, v in self.categories.items()))

    def _add_mission_entries(self, snap: Snapshot) -> None:
        """Quest objectives: the active mission summary first (it carries the nearest objective
        waypoint, so the beacon works on it), then each objective waypoint, then the turn-in
        person if they're nearby, then quest items found by the scan."""
        from . import quests

        info = quests.active_mission(snap.pc)
        entries: list[POI] = []
        points = quests.waypoints(snap.pc)

        def dist(w: Any) -> float:
            if w.pos is None:
                return 1e12
            return game.relative(snap.eye, snap.yaw, snap.pitch, w.pos).dist

        points.sort(key=lambda w: (not w.active, dist(w)))
        if info is not None:
            first = points[0] if points else None
            entries.append(POI(info.name, first.ptr if first else None, QUEST, text=info.spoken(),
                               pos=first.pos if first else None))
        for w in points:
            entries.append(POI(w.label, w.ptr, QUEST, pos=w.pos))
        if info is not None and info.turn_in_to:
            for person in self.categories.get("People", []):
                if quests.matches_person(person.name, info.turn_in_to):
                    label = "Turn in to" if info.ready_to_turn_in else "Mission contact"
                    entries.append(POI(f"{label} {person.name}", person.ptr, QUEST))
                    break
        quest_items = self.categories.get(QUEST, [])
        if entries or quest_items:
            self.categories[QUEST] = entries + quest_items

    def current_mission(self) -> None:
        """Speak the active mission and its objectives (also the first Quest objectives entry)."""
        from . import quests

        snap = self.snapshot()
        if snap is None:
            speech.say("Not in game")
            return
        info = quests.active_mission(snap.pc)
        speech.say(info.spoken() if info else "No active mission")

    def _cat_names(self) -> list[str]:
        return [c for c in CATEGORY_ORDER if self.categories.get(c)]

    def _select_category(self, name: str) -> None:
        self.category = name
        self.pois = self.categories.get(name, [])
        self.poi_index = -1
        self.beacon = False

    def cycle_category(self, step: int) -> None:
        """Back + D-pad left/right: switch category. Rescans so the list is always fresh."""
        snap = self.snapshot()
        if snap is None:
            speech.say("Not in game")
            return
        self.scan_pois(snap)
        cats = self._cat_names()
        if not cats:
            self.pois, self.category = [], ""
            speech.say("Nothing nearby")
            return
        i = cats.index(self.category) if self.category in cats else (-1 if step > 0 else 0)
        self._select_category(cats[(i + step) % len(cats)])
        nearest = self.pois[0]
        n = len(self.pois)
        if nearest.text:  # Quest objectives starts with the mission summary
            pos = nearest.position()
            where = f". Objective {game.describe(game.relative(snap.eye, snap.yaw, snap.pitch, pos))}" if pos else ""
            speech.say(f"{self.category}, {n} {'entry' if n == 1 else 'entries'}. {nearest.text}{where}")
        else:
            pos = nearest.position()
            where = f". Nearest: {nearest.name}, {game.describe(game.relative(snap.eye, snap.yaw, snap.pitch, pos))}" if pos else ""
            speech.say(f"{self.category}, {n} {'item' if n == 1 else 'items'}{where}")
        self.poi_index = 0

    def cycle_poi(self, step: int) -> None:
        """Back + D-pad up/down: previous/next item in the current category."""
        snap = self.snapshot()
        if snap is None:
            speech.say("Not in game")
            return
        if not self.category or not self.pois:
            self.cycle_category(1)
            return
        # Refresh the current category, keeping our place by name where possible.
        current = self.pois[self.poi_index].name if 0 <= self.poi_index < len(self.pois) else None
        self.scan_pois(snap)
        self.pois = self.categories.get(self.category, [])
        if not self.pois:
            speech.say(f"No {self.category.lower()} nearby any more")
            self.category = ""
            return
        names = [p.name for p in self.pois]
        base = names.index(current) if current in names else (-1 if step > 0 else 0)
        self.poi_index = (base + step) % len(self.pois)
        self.announce_poi(snap)

    def rescan_pois(self) -> None:
        snap = self.snapshot()
        if snap is None:
            return
        self.scan_pois(snap)
        cats = self._cat_names()
        if not cats:
            speech.say("Nothing nearby")
            return
        from .object_sounds import objects

        sounding = objects.summary() if objects.sources else ""
        speech.say("Nearby: " + ", ".join(f"{len(self.categories[c])} {c.lower()}" for c in cats)
                   + (f". {sounding}" if sounding else ""))
        if self.category not in cats:
            self._select_category(cats[0])

    def announce_poi(self, snap: Snapshot) -> None:
        poi = self.pois[self.poi_index]
        pos = poi.position()
        if poi.text:
            where = f" Objective {game.describe(game.relative(snap.eye, snap.yaw, snap.pitch, pos))}." if pos else ""
            speech.say(f"{poi.text}.{where} {self.poi_index + 1} of {len(self.pois)}")
            return
        if pos is None:
            speech.say(f"{poi.name}, gone")
            return
        rel = game.relative(snap.eye, snap.yaw, snap.pitch, pos)
        speech.say(f"{poi.name}, {game.describe(rel)}. {self.poi_index + 1} of {len(self.pois)}")

    def toggle_beacon(self) -> None:
        if self.poi_index < 0 or not self.pois:
            speech.say("Select a point of interest first")
            return
        if not self.beacon and not self.pois[self.poi_index].locatable:
            speech.say("The game hasn't marked a location for this mission yet")
            return
        self.beacon = not self.beacon
        audio.play("ui", snd.ui("on" if self.beacon else "off", self.s.volume))
        speech.say(f"Beacon {'on' if self.beacon else 'off'}")

    def beacon_tick(self, snap: Snapshot, now: float) -> None:
        """Steady beacon tone toward the selected entry, along the game's route when it has one."""
        from .navigation import beacon as nav_beacon

        if self.poi_index < 0 or self.poi_index >= len(self.pois):
            self.beacon = False
            nav_beacon.stop()
            return
        poi = self.pois[self.poi_index]
        pos = poi.position()
        if pos is None:
            self.beacon = False
            nav_beacon.stop()
            speech.say(f"{poi.name} is gone. Beacon off")
            return
        dist = nav_beacon.tick(self.s, snap, pos, poi.actor, f"{self.category}:{poi.name}", now)
        # Objective markers with no object at them are areas, so "arrived" a little earlier.
        arrive = 150 if poi.ptr is not None else 300
        if dist < arrive:
            self.beacon = False
            nav_beacon.stop()
            audio.play("ui", snd.ui("select", self.s.volume))
            speech.say(f"Arrived at {poi.name}")

    def nav_target(self, snap: Snapshot) -> tuple[str, Any, Any] | None:
        """(name, position, actor) to guide to: the beacon's entry if one is picked, else the
        nearest marker of the tracked mission."""
        if 0 <= self.poi_index < len(self.pois):
            poi = self.pois[self.poi_index]
            pos = poi.position()
            if pos is not None:
                return poi.name, pos, poi.actor
        from . import quests

        points = [w for w in quests.waypoints(snap.pc) if w.pos is not None]
        if not points:
            return None
        points.sort(key=lambda w: (not w.active, game.relative(snap.eye, snap.yaw, snap.pitch, w.pos).dist))
        w = points[0]
        return w.label, (game.location(game.deref(w.ptr)) if w.ptr is not None else None) or w.pos, game.deref(w.ptr)

    def face_objective(self) -> None:
        """Navigation assist: turn to face the way to the objective (or the beacon's target)."""
        from . import navigation

        if not self.s.nav_assist:
            speech.say("Navigation assist is off. Turn it on in the accessibility settings, Navigation group")
            return
        snap = self.snapshot()
        if snap is None:
            speech.say("Not in game")
            return
        target = self.nav_target(snap)
        if target is None:
            audio.play("ui", snd.ui("error", self.s.volume))
            speech.say("No objective marked. Pick something in the scanner first")
            return
        name, pos, actor = target
        dist, routed = navigation.face(snap, pos, actor, f"face:{name}")
        audio.play("ui", snd.ui("move", self.s.volume))
        via = ", following the path" if routed else ""
        speech.say(f"Facing {name}, {dist / 100:.0f} metres{via}")

    # ---------------------------------------------------------------- actions
    def snap_aim(self) -> None:
        snap = self.snapshot()
        if snap is None:
            return
        visible = [e for e in self.enemies if e.visible] or self.enemies
        if not visible:
            audio.play("ui", snd.ui("error", self.s.volume))
            speech.say("No enemies in range")
            return
        now = time.perf_counter()
        self.snap_cycle = self.snap_cycle + 1 if now - self.last_snap < 2.0 else 0
        self.last_snap = now
        e = visible[self.snap_cycle % len(visible)]
        if self.s.aim_mode == "lock":
            seen = [x for x in self.enemies if x.visible]
            keys = [x.key for x in seen]
            if self.lock_on_key in keys:  # switch to the next enemy after the one you're locked on
                e = seen[(keys.index(self.lock_on_key) + 1) % len(seen)]
            if e.visible:
                self.lock_on_key = e.key  # lock-on follows the enemy you switched to
        pitch, yaw = game.aim_rotation(snap.eye, e.pos)
        game.set_view(snap.pc, pitch, yaw)
        hidden = "" if e.visible else ", behind cover"
        speech.say(f"{game.display_name(e.actor)}, {e.rel.metres:.0f} metres{hidden}")

    def report_enemies(self) -> None:
        if not self.enemies:
            speech.say("No enemies nearby")
            return
        parts = [f"{len(self.enemies)} {'enemy' if len(self.enemies) == 1 else 'enemies'}"]
        for e in self.enemies[:4]:
            parts.append(f"{game.display_name(e.actor)}, {game.describe(e.rel)}")
        speech.say(". ".join(parts))

    def report_status(self) -> None:
        snap = self.snapshot()
        if snap is None:
            speech.say("Not in game")
            return
        parts = []
        h = game.health(snap.pawn)
        if h:
            parts.append(f"Health {h[0]:.0f} of {h[1]:.0f}")
        for cur, mx in (("GetShieldStrength", "GetMaxShieldStrength"),):
            try:
                parts.append(f"Shield {getattr(snap.pawn, cur)():.0f} of {getattr(snap.pawn, mx)():.0f}")
            except Exception:
                pass
        weapon = None
        try:
            weapon = snap.pawn.Weapon
        except Exception:
            pass
        if weapon is not None:
            parts.append(game.display_name(weapon))
            for getter in (lambda w: w.ReloadCnt, lambda w: w.GetAmmoCount()):
                try:
                    parts.append(f"{int(getter(weapon))} in magazine")
                    break
                except Exception:
                    continue
        speech.say(". ".join(parts) or "Status unavailable")

    def report_heading(self) -> None:
        snap = self.snapshot()
        if snap is None:
            return
        deg = game.heading_degrees(snap.yaw)
        pitch = math.degrees(snap.pitch)
        look = " looking up" if pitch > 20 else " looking down" if pitch < -20 else ""
        speech.say(f"Heading {deg} degrees{look}. {game.map_name(snap.pc)}")

    def level_view(self) -> None:
        """Reset pitch to the horizon: very useful when you can't see where you're looking."""
        snap = self.snapshot()
        if snap is None:
            return
        game.set_view(snap.pc, 0, int(snap.yaw / game.RAD_PER_UU))
        audio.play("ui", snd.ui("move", self.s.volume))
        speech.say("View levelled")

    def turn_around(self) -> None:
        snap = self.snapshot()
        if snap is None:
            return
        game.set_view(snap.pc, int(snap.pitch / game.RAD_PER_UU), int(snap.yaw / game.RAD_PER_UU) + 32768)
        speech.say("Turned around")


features = Features()
