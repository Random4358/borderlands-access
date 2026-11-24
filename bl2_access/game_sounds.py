"""The game's own loot sounds, replayed on repeat (an option: "Loot sound style").

When loot drops, the game plays a sound for it (a Wwise "AkEvent", or an older SoundCue).
This module watches for those: a sound played by a pickup, or right where one lies, whose
name says it's a drop / landing sound, is remembered for that item and for its kind and
rarity ("weapon3", "health"...). Remembered sounds are saved in game_sounds.json, so once a
blue gun's drop sound has been heard, every blue gun can use it, also after a restart.

In this style each nearby item replays its drop sound every couple of seconds, played on the
item itself, so the game's own 3D sound places it. Items whose sound hasn't been learned yet
get a short burst of the mod's tone at the same pace instead. Everything is logged
("game loot sound ...") so it's clear what was found.
"""

from __future__ import annotations

import json
import math
import os
from typing import Any

from . import game

MOD_DIR = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(MOD_DIR, "game_sounds.json")
SOUND_HOOKS = ["Engine.Actor:PlayAkEvent", "Engine.Actor:PlaySound"]
DROP_WORDS = ("drop", "land", "impact", "bounce", "spawn", "loot", "rarity", "legendary")
NEAR = 150.0   # uu: a sound played this close to an item counts as the item's

_ID = "bl2_access_game_sounds"


def _name(obj: Any) -> str:
    try:
        return str(obj.Name)
    except Exception:
        return ""


def _path(obj: Any) -> str:
    try:
        return str(obj._path_name())
    except Exception:
        return ""


class GameSounds:
    def __init__(self) -> None:
        self.by_item: dict[str, Any] = {}      # pickup path -> sound object
        self.by_kind: dict[str, Any] = {}      # "weapon3" -> sound object
        self.saved: dict[str, list[str]] = {}  # kind -> [class name, path], from game_sounds.json
        self.items: dict[str, tuple[tuple, str]] = {}  # pickup path -> (position, kind), from object sounds
        self.logged: set[str] = set()
        self.replaying = False
        self.registered = False
        self.load()

    # ------------------------------------------------------------ learning
    def register(self) -> None:
        if self.registered:
            return
        from unrealsdk import hooks as uhooks
        from unrealsdk.hooks import Type

        for name in SOUND_HOOKS:
            try:
                uhooks.add_hook(name, Type.PRE, _ID, self.on_sound)
            except Exception as e:  # noqa: BLE001
                self._note(f"game loot sound: couldn't watch {name}: {e}")
        self.registered = True

    def unregister(self) -> None:
        if not self.registered:
            return
        from unrealsdk import hooks as uhooks
        from unrealsdk.hooks import Type

        for name in SOUND_HOOKS:
            try:
                uhooks.remove_hook(name, Type.PRE, _ID)
            except Exception:
                pass
        self.registered = False

    def on_sound(self, obj: Any, args: Any, ret: Any, func: Any) -> None:
        if self.replaying:
            return
        try:
            self.heard(obj, self._sound_arg(args))
        except Exception:
            pass

    @staticmethod
    def _sound_arg(args: Any) -> Any:
        for n in ("InEvent", "AkEvent", "Event", "InSoundCue", "Sound", "SoundCue"):
            try:
                v = getattr(args, n)
            except Exception:
                continue
            if v is not None:
                return v
        try:
            for prop in args._type._properties():
                v = getattr(args, prop.Name)
                if v is not None and any(w in game.class_name(v) for w in ("AkEvent", "SoundCue")):
                    return v
        except Exception:
            pass
        return None

    def heard(self, source: Any, sound: Any) -> None:
        """A sound was played by `source`. If it's an item's drop sound, remember it."""
        if sound is None:
            return
        sname = _name(sound)
        key = None
        if "Pickup" in game.class_name(source):
            key = _path(source)
        else:
            pos = game.location(source)
            if pos is not None:
                best = None
                for k, (q, _kind) in self.items.items():
                    d = math.dist(pos, q)
                    if d < NEAR and (best is None or d < best[0]):
                        best = (d, k)
                key = best[1] if best else None
        if key is None or key not in self.items:
            return
        kind = self.items[key][1]
        dropish = any(w in sname.lower() for w in DROP_WORDS)
        tag = f"{kind}:{sname}"
        if tag not in self.logged:
            self.logged.add(tag)
            self._note(f"game loot sound heard: {game.class_name(sound)} {sname} for {kind}"
                       f"{'' if dropish else ' (not used: the name does not look like a drop sound)'}")
        if not dropish:
            return
        self.by_item[key] = sound
        if kind not in self.by_kind:
            self.by_kind[kind] = sound
            self.saved[kind] = [game.class_name(sound), _path(sound)]
            self.save()
            self._note(f"game loot sound learned for {kind}: {sname}")

    # ------------------------------------------------------------ playing
    def note_item(self, key: str, pos: tuple, kind: str) -> None:
        self.items[key] = (pos, kind)

    def forget_items(self, keep: set[str]) -> None:
        for k in [k for k in self.items if k not in keep]:
            del self.items[k]
            self.by_item.pop(k, None)

    def sound_for(self, key: str, kind: str) -> Any:
        s = self.by_item.get(key) or self.by_kind.get(kind)
        if s is None and kind in self.saved:
            s = self._find(*self.saved[kind])
            if s is not None:
                self.by_kind[kind] = s
        return s

    def play(self, actor: Any, sound: Any) -> bool:
        """Play the sound on the item (so the game places it). True if the game took it."""
        self.replaying = True
        try:
            calls = ([lambda: actor.PlayAkEvent(sound)] if "AkEvent" in game.class_name(sound) else []) + [
                lambda: actor.PlaySound(sound)]
            for call in calls:
                try:
                    call()
                    return True
                except Exception as e:  # noqa: BLE001
                    tag = f"play error {type(e).__name__}"
                    if tag not in self.logged:
                        self.logged.add(tag)
                        self._note(f"game loot sound: playing {_name(sound)} failed: {type(e).__name__}: {e}")
            return False
        finally:
            self.replaying = False

    # ------------------------------------------------------------ saving
    def _find(self, cls: str, path: str) -> Any:
        try:
            import unrealsdk

            return unrealsdk.find_object(cls, path)
        except Exception:
            return None

    def load(self) -> None:
        try:
            with open(STORE, encoding="utf-8") as f:
                data = json.load(f)
            self.saved = {str(k): [str(v[0]), str(v[1])] for k, v in data.items()}
        except Exception:
            self.saved = {}

    def save(self) -> None:
        try:
            with open(STORE, "w", encoding="utf-8") as f:
                json.dump(self.saved, f, indent=1)
        except Exception:
            pass

    def _note(self, text: str) -> None:
        try:
            from . import trace

            trace.note(text)
        except Exception:
            pass


sounds = GameSounds()
