"""Continuous, directional sounds for things in the world: loot on the ground (by type),
chests and other containers, doors / switches / vendors / fast travel, and quest items.

Each of the nearest few objects gets its own stream (see audio._Stream) that plays its loop
without a break. Every frame the next segment is made with the object's current direction
and distance, so the sound moves as you turn and walk. Sounds fade out when the object is
picked up, opened, out of range, or when a menu is up.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any

from . import audio as snd
from . import game
from .audio import audio

RESCAN = 0.5      # seconds between looking for objects (positions update every frame)
LEAD = 0.2        # seconds of sound kept queued ahead on each stream

PICKUP_KIND = {
    "Weapons and gear": "gear",
    "Ammo and health": "ammo",
    "Money": "money",
    "Quest objectives": "quest",
    "Other": "loot",
}
OBJECT_KIND = {
    "Containers": "container",
    "Quest objectives": "quest",
    "Vendors": "interactive",
    "Travel": "interactive",
    "Doors and switches": "interactive",
}
KIND_NAMES = {
    "weapon": "weapons", "item": "shields, grenade mods, class mods and relics", "ammo": "ammo",
    "health": "health", "money": "money", "quest": "quest items", "gear": "gear",
    "container": "containers", "interactive": "doors, switches, vendors and travel", "loot": "other loot",
}
HEALTH_WORDS = ("health", "insta", "healing", "medkit")
_rarity_logged: set = set()


def _base(kind: str) -> str:
    return kind.rstrip("0123456789")


def rarity_of(inv: Any) -> int:
    """1 common .. 5 legendary, 6 pearlescent / seraph / effervescent and above. 1 if unknown.
    The raw value is logged once per value seen, so the mapping can be checked."""
    raw = None
    for get in (lambda: inv.GetRarityLevel(), lambda: inv.RarityLevel, lambda: inv.DefinitionData.RarityLevel):
        try:
            v = get()
            v = v[0] if isinstance(v, tuple) else v
            raw = int(v)
            break
        except Exception:
            continue
    if raw not in _rarity_logged:
        _rarity_logged.add(raw)
        try:
            from . import trace

            trace.note(f"loot rarity: {game.class_name(inv)} {game.display_name(inv)} rarity value {raw}")
        except Exception:
            pass
    if raw is None or raw < 1:
        return 1
    if raw >= 6:   # BL2 uses large numbers (500 and up) for pearlescent, seraph and the like
        return 6
    return raw


@dataclass
class Source:
    key: str
    ptr: Any
    kind: str
    slot: int = -1
    step: int = 0
    started: bool = False
    pan: float = 0.0
    vol: float = 0.0
    behind: bool = False


def _still_usable(obj: Any) -> bool:
    """False for containers that have been opened, where the game says so plainly. (Calling the
    game's usability functions without a player isn't reliable, so they aren't used.)"""
    for prop in ("bIsUsable", "bCanBeUsed", "bUsable"):
        try:
            return bool(getattr(obj, prop))
        except Exception:
            continue
    try:
        return not bool(obj.bHidden)
    except Exception:
        return True


SAME_SPOT = 200.0  # uu: things of the same kind this close together get one sound (a pile of ammo)
BEACON_DUCK = 0.55  # object sounds while the beacon is on, so it stands out
COMBAT_DUCK = 0.5   # and while enemy tones are playing


class ObjectSounds:
    def __init__(self) -> None:
        self.focus_key: str | None = None   # the beacon's target: its own loop is left out
        self.duck = 1.0                     # set each frame by features.tick
        self.sources: dict[str, Source] = {}
        self.next_scan = 0.0
        self.kinds: dict[str, tuple[str, str]] = {}  # actor path -> (kind or "", name), per map
        self.map_key = ""

    # ------------------------------------------------------------ which objects
    def _classify(self, actor: Any, is_pickup: bool) -> str:
        from .features import categorize_object, categorize_pickup

        try:
            key = actor._path_name()
        except Exception:
            key = str(id(actor))
        hit = self.kinds.get(key)
        if hit is None:
            cat, name = categorize_pickup(actor) if is_pickup else categorize_object(actor)
            table = PICKUP_KIND if is_pickup else OBJECT_KIND
            kind = table.get(cat or "", "")
            if is_pickup and kind in ("gear", "ammo"):
                kind = self._refine(actor, kind, name)
            hit = (kind, name)
            self.kinds[key] = hit
        return hit[0]

    def _refine(self, actor: Any, kind: str, name: str) -> str:
        """gear -> weapon<rarity> or item<rarity>; ammo -> ammo or health."""
        from .features import _definition_name

        try:
            inv = actor.Inventory
        except Exception:
            inv = None
        if kind == "ammo":
            hay = f"{game.class_name(inv)} {_definition_name(inv) if inv is not None else ''} {name}".lower()
            return "health" if any(w in hay for w in HEALTH_WORDS) else "ammo"
        if inv is None:
            return "item1"
        family = "weapon" if game.class_name(inv).startswith("WillowWeapon") else "item"
        return f"{family}{rarity_of(inv)}"

    def _wanted(self, s: Any, snap: Any) -> list[tuple[float, str, Any, str]]:
        enabled = {
            "weapon": s.loot_sounds, "item": s.loot_sounds, "ammo": s.loot_sounds, "health": s.loot_sounds,
            "money": s.loot_sounds, "loot": s.loot_sounds,
            "quest": s.quest_item_sounds, "container": s.container_sounds, "interactive": s.interactive_sounds,
        }
        found: list[tuple[float, str, Any, str]] = []

        def consider(actor: Any, is_pickup: bool) -> None:
            kind = self._classify(actor, is_pickup)
            if not kind or not enabled.get(_base(kind)):
                return
            pos = game.location(actor)
            if pos is None:
                return
            d = game.relative(snap.eye, snap.yaw, snap.pitch, pos).dist
            if d > s.object_range:
                return
            if kind == "container" and not _still_usable(actor):
                return
            try:
                key = actor._path_name()
            except Exception:
                key = str(id(actor))
            if key == self.focus_key:
                return   # the beacon is leading you to it: two sounds in one place would clash
            found.append((d, key, actor, kind, pos))

        if s.loot_sounds or s.quest_item_sounds:
            for a in game.world_actors(["WillowPickup"]):
                consider(a, True)
        if s.container_sounds or s.interactive_sounds or s.quest_item_sounds:
            for a in game.world_actors(["WillowInteractiveObject", "WillowVendingMachineBase"]):
                consider(a, False)
        # Quest items first, then nearest. A sound already playing gets a 3 m head start, so two
        # things at about the same distance don't keep swapping (which made the sound seem to
        # jump between objects).
        playing = set(self.sources)
        found.sort(key=lambda f: (f[3] != "quest", f[0] - (300.0 if f[1] in playing else 0.0)))
        # Several things of the same kind side by side (a pile of ammo, a row of lockers) play as
        # one sound: the same loop from almost the same place only muddies it.
        picked: list = []
        for f in found:
            if any(g[3] == f[3] and math.dist(g[4][:2], f[4][:2]) < SAME_SPOT for g in picked):
                continue
            picked.append(f)
        return [f[:4] for f in picked[: max(1, min(int(s.object_max), snd.STREAMS))]]

    # ------------------------------------------------------------ per frame
    def tick(self, s: Any, snap: Any, now: float) -> None:
        if not audio.ok or not audio.streams:
            return
        if not (s.loot_sounds or s.container_sounds or s.interactive_sounds or s.quest_item_sounds):
            self.stop()
            return
        map_key = game.map_name(snap.pc) or ""
        if map_key != self.map_key:
            self.map_key = map_key
            self.kinds.clear()
            self.stop(fade=False)
        if now >= self.next_scan:
            self.next_scan = now + RESCAN
            self._assign(self._wanted(s, snap))
        for src in list(self.sources.values()):
            self._feed(src, s, snap)

    def _assign(self, wanted: list[tuple[float, str, Any, str]]) -> None:
        keep = {key for _d, key, _a, _k in wanted}
        for key in [k for k in self.sources if k not in keep]:
            self._release(self.sources.pop(key))
        used = {src.slot for src in self.sources.values()}
        free = [i for i in range(len(audio.streams)) if i not in used]
        free.sort(key=lambda i: audio.streams[i].ahead())  # silent ones first: let fades finish
        for _d, key, actor, kind in wanted:
            if key in self.sources or not free:
                continue
            slot = free.pop(0)
            if audio.streams[slot].ahead() > 0:
                audio.streams[slot].stop()  # a released sound is still fading here
            self.sources[key] = Source(key, game.weak(actor), kind, slot)

    def _feed(self, src: Source, s: Any, snap: Any) -> None:
        actor = game.deref(src.ptr)
        pos = game.location(actor) if actor is not None else None
        if pos is None:  # picked up / destroyed
            self._release(self.sources.pop(src.key))
            return
        stream = audio.streams[src.slot]
        try:
            if stream.ahead() >= LEAD:
                return
            rel = game.relative(snap.eye, snap.yaw, snap.pitch, pos)
            closeness = 1.0 - min(1.0, rel.dist / max(1.0, s.object_range))
            # Quieter than the beacon and enemy tones (those tell you where to go and what's
            # shooting you), and quieter still while they're playing.
            vol = (0.05 + 0.45 * closeness ** 1.5) * s.volume * s.object_volume * self.duck
            while stream.ahead() < LEAD:
                fade = 0 if src.started else 1
                stream.feed(snd.loop_segment(src.kind, src.step, rel.pan, vol, rel.behind, fade))
                src.pan, src.vol, src.behind = rel.pan, vol, rel.behind
                src.started = True
                src.step += 1
        except Exception:
            self.sources.pop(src.key, None)

    def _release(self, src: Source) -> None:
        """Let the sound fade out instead of cutting it off mid-wave."""
        if src.slot < 0 or src.slot >= len(audio.streams) or not src.started:
            return
        try:
            stream = audio.streams[src.slot]
            stream.feed(snd.loop_segment(src.kind, src.step, src.pan, src.vol, src.behind, -1))
        except Exception:
            pass

    def stop(self, fade: bool = True) -> None:
        for src in list(self.sources.values()):
            if fade:
                self._release(src)
            elif 0 <= src.slot < len(audio.streams):
                try:
                    audio.streams[src.slot].stop()
                except Exception:
                    pass
        self.sources.clear()
        self.next_scan = 0.0

    def summary(self) -> str:
        if not self.sources:
            return "No object sounds playing"
        counts: dict[str, int] = {}
        for src in self.sources.values():
            counts[_base(src.kind)] = counts.get(_base(src.kind), 0) + 1
        return "Object sounds: " + ", ".join(f"{n} {KIND_NAMES[k]}" for k, n in counts.items())


objects = ObjectSounds()
