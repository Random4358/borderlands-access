"""Steady enemy tones that tell you where you're aiming.

Each of the nearest enemies plays a continuous tone (no beeping on and off):
* Left / right: panned by where the enemy is compared with your crosshair. Dead centre only
  when your crosshair is within the enemy's width; even a little off, it's clearly to one side
  (a third of the way over at once), so the last few degrees are easy to hear.
* Up / down: the pitch rises when the enemy is above your crosshair and falls when it's below
  (up to an octave at 30 degrees). Level with your aim = exactly the middle note; a little off
  jumps a semitone at once.
* How close your aim is: a soft mellow tone when you're off to the side, a slow pulse within
  about 15 degrees, a quicker, brighter pulse within about 6, and a buzzy, fast-pulsing high
  tone when your crosshair is on the enemy. That last one means fire.
* Quick to follow your aim: sound is fed in 40 ms halves of the 80 ms segments, so only about
  40 to 80 ms is ever queued ahead.
* Distance: louder when closer. Behind you or behind cover: muffled.

Each enemy gets its own stream (audio.combat_streams), fed every frame with its latest position.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from . import audio as snd
from .audio import audio

LEAD = 0.06         # seconds queued ahead (two 40 ms halves): short, so the sound follows your aim quickly
NEAR_DEG = 15.0     # "nearly on target": slow pulse
CLOSE_DEG = 6.0     # "very nearly": quicker pulse
PAN_START = 0.35    # how far over the tone is the moment your aim leaves the enemy's width
PAN_FULL_DEG = 25.0  # degrees beyond that to be fully to one side


def lock_cone_deg(dist: float) -> float:
    """Roughly a body width (~60 uu) either side; never tighter than 1.5 degrees."""
    return max(1.5, math.degrees(math.atan2(60, max(1.0, dist))))


def aim_state(enemy: Any) -> str:
    err = math.degrees(enemy.rel.aim_error)
    if enemy.visible and err <= lock_cone_deg(enemy.rel.dist):
        return "enemy_locked"
    if err <= CLOSE_DEG:
        return "enemy_near2"
    if err <= NEAR_DEG:
        return "enemy_near"
    return "enemy"


def aim_pan(enemy: Any) -> float:
    """Centred only within the enemy's width; outside it, clearly to one side straight away."""
    h = math.degrees(enemy.rel.rel_yaw)
    off = abs(h) - lock_cone_deg(enemy.rel.dist)
    if off <= 0:
        return 0.0
    return math.copysign(min(1.0, PAN_START + (1 - PAN_START) * off / PAN_FULL_DEG), h)


@dataclass
class _Voice:
    slot: int
    step: int = 0
    half: int = 0       # which 40 ms half of the segment goes next
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
            cone = lock_cone_deg(e.rel.dist)
            cycles = (snd.LOCKED_CYCLES if kind == "enemy_locked"
                      else snd.enemy_cycles(math.degrees(e.rel.rel_pitch), cone))
            pan = aim_pan(e)
            closeness = 1.0 - min(1.0, e.rel.dist / max(1.0, s.radar_range))
            vol = (0.25 + 0.75 * closeness) * s.volume * s.enemy_volume
            if not e.visible:
                vol *= 0.7
            muffled = bool(e.rel.behind or not e.visible)
            v.kind, v.cycles, v.pan, v.vol, v.muffled = kind, cycles, pan, vol, muffled
            while stream.ahead() < LEAD:
                # Half a segment at a time (each half starts and ends where the wave is at zero,
                # so halves of different segments join cleanly): the latest aim is heard sooner.
                seg = snd.tone_segment(kind, cycles, v.step, pan, vol, muffled, 1 if v.step == 0 else 0)
                mid = len(seg) // 2
                stream.feed(seg[:mid] if v.half == 0 else seg[mid:])
                v.started = True
                v.half ^= 1
                if v.half == 0:
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
