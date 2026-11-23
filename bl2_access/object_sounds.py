"""Continuous, directional sounds for things in the world: loot on the ground (by type),
chests and other containers, doors / switches / vendors / fast travel, and quest items.

Each of the nearest few objects gets its own stream (see audio._Stream) that plays its loop
without a break. Every frame the next segment is made with the object's current direction
and distance, so the sound moves as you turn and walk. Sounds fade out when the object is
picked up, opened, out of range, or when a menu is up.
"""

from __future__ import annotations

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
    "gear": "weapons and gear", "ammo": "ammo and health", "money": "money", "quest": "quest items",
    "container": "containers", "interactive": "doors, switches, vendors and travel", "loot": "other loot",
}


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
    """False for containers that have been opened, where the game says so."""
    for getter in ("IsUsable", "CanBeUsed"):
        try:
            fn = getattr(obj, getter)
        except Exception:
            continue
        try:
            return bool(fn(None)) if callable(fn) else bool(fn)
        except TypeError:
            try:
                return bool(fn())
            except Exception:
                continue
        except Exception:
            continue
    for prop in ("bIsUsable", "bCanBeUsed", "bUsable"):
        try:
            return bool(getattr(obj, prop))
        except Exception:
            continue
    try:
        return not bool(obj.bHidden)
    except Exception:
        return True


class ObjectSounds:
    def __init__(self) -> None:
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
            hit = (table.get(cat or "", ""), name)
            self.kinds[key] = hit
        return hit[0]

    def _wanted(self, s: Any, snap: Any) -> list[tuple[float, str, Any, str]]:
        enabled = {
            "gear": s.loot_sounds, "ammo": s.loot_sounds, "money": s.loot_sounds, "loot": s.loot_sounds,
            "quest": s.quest_item_sounds, "container": s.container_sounds, "interactive": s.interactive_sounds,
        }
        found: list[tuple[float, str, Any, str]] = []

        def consider(actor: Any, is_pickup: bool) -> None:
            kind = self._classify(actor, is_pickup)
            if not kind or not enabled.get(kind):
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
            found.append((d, key, actor, kind))

        if s.loot_sounds or s.quest_item_sounds:
            for a in game.world_actors(["WillowPickup"]):
                consider(a, True)
        if s.container_sounds or s.interactive_sounds or s.quest_item_sounds:
            for a in game.world_actors(["WillowInteractiveObject", "WillowVendingMachineBase"]):
                consider(a, False)
        # Quest items first, then nearest.
        found.sort(key=lambda f: (f[3] != "quest", f[0]))
        return found[: max(1, min(int(s.object_max), snd.STREAMS))]

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
            vol = (0.08 + 0.6 * closeness ** 1.5) * s.volume * s.object_volume
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
            counts[src.kind] = counts.get(src.kind, 0) + 1
        return "Object sounds: " + ", ".join(f"{n} {KIND_NAMES[k]}" for k, n in counts.items())


objects = ObjectSounds()
