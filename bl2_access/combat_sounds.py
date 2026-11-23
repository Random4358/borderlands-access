"""Steady enemy tones that tell you where you're aiming.

Each of the nearest enemies plays a continuous tone (no beeping on and off):
* Left / right: panned by where the enemy is compared with your crosshair. Centred = in line.
* Up / down: the pitch rises when the enemy is above your crosshair and falls when it's below
  (up to an octave at 30 degrees). Level with your aim = the middle pitch.
* How close your aim is: a soft mellow tone when you're off to the side, a brighter, gently
  pulsing tone within about 10 degrees, and a buzzy, fast-pulsing high tone when your crosshair
  is on the enemy. That last one means fire.
* Distance: louder when closer. Behind you or behind cover: muffled.

Each enemy gets its own stream (audio.combat_streams), fed every frame with its latest position.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from . import audio as snd
from .audio import audio

LEAD = 0.1          # seconds queued ahead: short, so the sound follows your aim quickly
NEAR_DEG = 10.0     # "nearly on target" cone


def lock_cone_deg(dist: float) -> float:
    """Roughly a body width (~60 uu) either side; never tighter than 1.5 degrees."""
    return max(1.5, math.degrees(math.atan2(60, max(1.0, dist))))


def aim_state(enemy: Any) -> str:
    err = math.degrees(enemy.rel.aim_error)
    if enemy.visible and err <= lock_cone_deg(enemy.rel.dist):
        return "enemy_locked"
    if err <= NEAR_DEG:
        return "enemy_near"
    return "enemy"


@dataclass
class _Voice:
    slot: int
    step: int = 0
    started: bool = False
    kind: str = "enemy"
    cycles: int = snd.ENEMY_BASE
    pan: float = 0.0
    vol: float = 0.0
    muffled: bool = False


class EnemyTones:
    def __init__(self) -> None:
        self.voices: dict[str, _Voice] = {}

    def tick(self, enemies: list[Any], s: Any) -> None:
        streams = audio.combat_streams
        if not audio.ok or not streams:
            return
        shown = [e for e in enemies if e.visible or s.radar_hidden][: max(1, min(int(s.radar_max), len(streams)))]
        keep = {e.key for e in shown}
        for key in [k for k in self.voices if k not in keep]:
            self._release(self.voices.pop(key))
        used = {v.slot for v in self.voices.values()}
        free = sorted((i for i in range(len(streams)) if i not in used), key=lambda i: streams[i].ahead())
        for e in shown:
            if e.key not in self.voices:
                if not free:
                    continue
                slot = free.pop(0)
                if streams[slot].ahead() > 0:
                    streams[slot].stop()
                self.voices[e.key] = _Voice(slot)
            self._feed(self.voices[e.key], e, s)

    def _feed(self, v: _Voice, e: Any, s: Any) -> None:
        stream = audio.combat_streams[v.slot]
        try:
            if stream.ahead() >= LEAD:
                return
            kind = aim_state(e)
            cycles = snd.LOCKED_CYCLES if kind == "enemy_locked" else snd.enemy_cycles(math.degrees(e.rel.rel_pitch))
            closeness = 1.0 - min(1.0, e.rel.dist / max(1.0, s.radar_range))
            vol = (0.25 + 0.75 * closeness) * s.volume * s.enemy_volume
            if not e.visible:
                vol *= 0.7
            muffled = bool(e.rel.behind or not e.visible)
            v.kind, v.cycles, v.pan, v.vol, v.muffled = kind, cycles, e.rel.pan, vol, muffled
            while stream.ahead() < LEAD:
                stream.feed(snd.tone_segment(kind, cycles, v.step, e.rel.pan, vol, muffled, 0 if v.started else 1))
                v.started = True
                v.step += 1
        except Exception:
            pass

    def _release(self, v: _Voice) -> None:
        if not v.started:
            return
        try:
            audio.combat_streams[v.slot].feed(
                snd.tone_segment(v.kind, v.cycles, v.step, v.pan, v.vol, v.muffled, -1))
        except Exception:
            pass

    def stop(self, fade: bool = True) -> None:
        for v in self.voices.values():
            if fade:
                self._release(v)
            else:
                try:
                    audio.combat_streams[v.slot].stop()
                except Exception:
                    pass
        self.voices.clear()


tones = EnemyTones()
