"""Stereo-positioned cue sounds, synthesised at runtime and played through winmm waveOut.

Each "channel" is its own waveOut device handle; Windows mixes them for us, so we can play
radar pings, target ticks and wall clicks at the same time without a mixing thread.
"""

from __future__ import annotations

import ctypes
import math
import random
import time
from array import array
from ctypes import wintypes
from functools import lru_cache

RATE = 22050
MAX_GAIN = 3.0  # per-sound volume goes up to 300%

# The sound glossary: every sound the mod makes, in the order the settings menu lists them.
# (key, name, what it means). Each has its own volume, 0 to 300%.
SOUNDS: list[tuple[str, str, str]] = [
    ("enemy", "Enemy tone, off target", "Steady tone for each nearby enemy. Panned to where it is compared with your aim, higher when it's above your crosshair, lower when below, louder when closer."),
    ("enemy_near", "Enemy tone, nearly on target", "The enemy tone turns brighter and gently pulses when your aim is within about 10 degrees of the enemy."),
    ("enemy_locked", "Enemy tone, on target", "A buzzy, fast-pulsing high tone: your crosshair is on the enemy. Fire."),
    ("radar", "Enemy radar beep", "Repeating beep for each nearby enemy, used when the enemy sound style is set to radar beeps."),
    ("ui_lock", "Target lock", "A rising two-note click when your crosshair lands on an enemy, or lock-on picks one."),
    ("ui_on_target", "On-target tick", "Ticks while your crosshair stays on an enemy, in radar beep style only."),
    ("ui_lost", "Target lost", "A falling tone when your crosshair leaves an enemy, in radar beep style only."),
    ("ui_heartbeat", "Low health heartbeat", "A heartbeat when your health is low. Faster when it's very low."),
    ("npc", "Friendly character chime", "A soft two-note chime for friendly characters nearby."),
    ("beacon", "Beacon", "A steady pulsing tone that leads you to the item or objective you picked, panned the way to go. It pulses faster as you get closer and is muffled when the way to go is behind you."),
    ("beacon_on", "Beacon, on course", "The beacon turns brighter when you're facing the way to go. Walk forward."),
    ("wall", "Wall click", "A soft click when there's a wall close in front of or beside you."),
    ("ledge", "Ledge warning", "A falling tone when there's a drop ahead of you."),
    ("ui_jump", "Jump cue", "A rising boing when there's something you can jump over, or a gap you can jump across."),
    ("gear", "Weapons and gear on the ground", "A bright two-note shimmer for guns, shields, grenade mods, class mods and relics lying nearby."),
    ("ammo", "Ammo and health on the ground", "A low, soft hum that gently swells."),
    ("money", "Money and eridium on the ground", "A high sparkle."),
    ("loot", "Other loot on the ground", "A plain, steady high tone."),
    ("container", "Chests and containers", "A woody low buzz for chests, lockers and crates you haven't opened."),
    ("interactive", "Doors, switches, vendors and travel", "A low warble for doors, switches, vending machines and fast travel stations."),
    ("quest", "Quest items", "A pulsing high two-tone chord for quest items and mission objects."),
    ("ui_move", "Menu move", "A short tick when you move the highlight in a menu."),
    ("ui_select", "Menu select", "Two rising notes when you pick something in a menu."),
    ("ui_back", "Menu back", "Two falling notes when you go back in a menu."),
    ("ui_open", "Menu opened", "Three rising notes when a menu opens."),
    ("ui_close", "Menu closed", "Three falling notes when a menu closes."),
    ("ui_on", "Switched on", "Two rising notes when something is switched on, such as the beacon or radar."),
    ("ui_off", "Switched off", "Two falling notes when something is switched off."),
    ("ui_prompt", "Interaction prompt", "A soft double tick when you're close enough to use something, just before it's named with the button to press."),
    ("ui_modifier", "Modifier button", "A tiny click when you hold the modifier button for a shortcut."),
    ("ui_error", "Error", "A low buzz when an action can't be done."),
]
GAINS: dict[str, float] = {key: 1.0 for key, _n, _d in SOUNDS}


def gain(key: str) -> float:
    return GAINS.get(key, 1.0)
WAVE_MAPPER = 0xFFFFFFFF
WHDR_DONE = 0x00000001


class WAVEFORMATEX(ctypes.Structure):
    _fields_ = [
        ("wFormatTag", wintypes.WORD),
        ("nChannels", wintypes.WORD),
        ("nSamplesPerSec", wintypes.DWORD),
        ("nAvgBytesPerSec", wintypes.DWORD),
        ("nBlockAlign", wintypes.WORD),
        ("wBitsPerSample", wintypes.WORD),
        ("cbSize", wintypes.WORD),
    ]


class WAVEHDR(ctypes.Structure):
    pass


WAVEHDR._fields_ = [
    ("lpData", ctypes.c_void_p),
    ("dwBufferLength", wintypes.DWORD),
    ("dwBytesRecorded", wintypes.DWORD),
    ("dwUser", ctypes.c_size_t),
    ("dwFlags", wintypes.DWORD),
    ("dwLoops", wintypes.DWORD),
    ("lpNext", ctypes.POINTER(WAVEHDR)),
    ("reserved", ctypes.c_size_t),
]

_winmm = ctypes.WinDLL("winmm")
_winmm.waveOutOpen.argtypes = [
    ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint, ctypes.POINTER(WAVEFORMATEX),
    ctypes.c_size_t, ctypes.c_size_t, wintypes.DWORD,
]
for _fn in ("waveOutPrepareHeader", "waveOutUnprepareHeader", "waveOutWrite"):
    getattr(_winmm, _fn).argtypes = [ctypes.c_void_p, ctypes.POINTER(WAVEHDR), ctypes.c_uint]
_winmm.waveOutReset.argtypes = [ctypes.c_void_p]
_winmm.waveOutClose.argtypes = [ctypes.c_void_p]


def _fmt() -> WAVEFORMATEX:
    f = WAVEFORMATEX()
    f.wFormatTag = 1  # PCM
    f.nChannels = 2
    f.nSamplesPerSec = RATE
    f.wBitsPerSample = 16
    f.nBlockAlign = 4
    f.nAvgBytesPerSec = RATE * 4
    f.cbSize = 0
    return f


class _Channel:
    def __init__(self, fmt: WAVEFORMATEX) -> None:
        self.h = ctypes.c_void_p()
        res = _winmm.waveOutOpen(ctypes.byref(self.h), WAVE_MAPPER, ctypes.byref(fmt), 0, 0, 0)
        if res != 0:
            raise OSError(f"waveOutOpen failed ({res})")
        self.hdr: WAVEHDR | None = None
        self.buf = None
        self.started = 0.0

    def busy(self) -> bool:
        return self.hdr is not None and not (self.hdr.dwFlags & WHDR_DONE)

    def _release(self) -> None:
        if self.hdr is not None:
            if self.busy():
                _winmm.waveOutReset(self.h)
            _winmm.waveOutUnprepareHeader(self.h, ctypes.byref(self.hdr), ctypes.sizeof(WAVEHDR))
            self.hdr = None
            self.buf = None

    def play(self, data: bytes) -> None:
        self._release()
        self.buf = ctypes.create_string_buffer(data, len(data))
        hdr = WAVEHDR()
        hdr.lpData = ctypes.cast(self.buf, ctypes.c_void_p)
        hdr.dwBufferLength = len(data)
        _winmm.waveOutPrepareHeader(self.h, ctypes.byref(hdr), ctypes.sizeof(WAVEHDR))
        _winmm.waveOutWrite(self.h, ctypes.byref(hdr), ctypes.sizeof(WAVEHDR))
        self.hdr = hdr
        self.started = time.perf_counter()

    def close(self) -> None:
        self._release()
        _winmm.waveOutClose(self.h)


class _Stream:
    """A waveOut handle fed back-to-back segments, for sounds that play continuously and
    follow an object as it moves. Queued segments play gaplessly; each new one carries the
    latest pan and volume."""

    def __init__(self, fmt: WAVEFORMATEX) -> None:
        self.h = ctypes.c_void_p()
        res = _winmm.waveOutOpen(ctypes.byref(self.h), WAVE_MAPPER, ctypes.byref(fmt), 0, 0, 0)
        if res != 0:
            raise OSError(f"waveOutOpen failed ({res})")
        self.queue: list[tuple[WAVEHDR, object, float]] = []  # header, buffer, seconds

    def _reap(self) -> None:
        while self.queue and self.queue[0][0].dwFlags & WHDR_DONE:
            hdr, _buf, _d = self.queue.pop(0)
            _winmm.waveOutUnprepareHeader(self.h, ctypes.byref(hdr), ctypes.sizeof(WAVEHDR))

    def ahead(self) -> float:
        """Seconds of sound still queued (including the segment playing now)."""
        self._reap()
        return sum(d for _h, _b, d in self.queue)

    def feed(self, data: bytes) -> None:
        self._reap()
        buf = ctypes.create_string_buffer(data, len(data))
        hdr = WAVEHDR()
        hdr.lpData = ctypes.cast(buf, ctypes.c_void_p)
        hdr.dwBufferLength = len(data)
        _winmm.waveOutPrepareHeader(self.h, ctypes.byref(hdr), ctypes.sizeof(WAVEHDR))
        _winmm.waveOutWrite(self.h, ctypes.byref(hdr), ctypes.sizeof(WAVEHDR))
        self.queue.append((hdr, buf, len(data) / (RATE * 4)))

    def stop(self) -> None:
        if self.queue:
            _winmm.waveOutReset(self.h)
            for hdr, _b, _d in self.queue:
                _winmm.waveOutUnprepareHeader(self.h, ctypes.byref(hdr), ctypes.sizeof(WAVEHDR))
            self.queue = []

    def close(self) -> None:
        self.stop()
        _winmm.waveOutClose(self.h)


STREAMS = 6  # continuous object sounds playing at once
COMBAT_STREAMS = 4  # continuous enemy tones playing at once

# How many simultaneous voices each kind of cue gets.
GROUPS = {"radar": 4, "target": 1, "nav": 3, "ui": 2, "alert": 1, "beacon": 1, "npc": 2}


class AudioEngine:
    def __init__(self) -> None:
        self.groups: dict[str, list[_Channel]] = {}
        self.streams: list[_Stream] = []
        self.combat_streams: list[_Stream] = []
        self.nav_stream: _Stream | None = None
        self.master = 0.8
        self.ok = False

    def start(self) -> bool:
        self.close()
        fmt = _fmt()
        try:
            for name, count in GROUPS.items():
                self.groups[name] = [_Channel(fmt) for _ in range(count)]
            self.streams = [_Stream(fmt) for _ in range(STREAMS)]
            self.combat_streams = [_Stream(fmt) for _ in range(COMBAT_STREAMS)]
            self.nav_stream = _Stream(fmt)
            self.ok = True
        except OSError as e:
            print(f"[Borderlands Access] Audio unavailable: {e}")
            self.close()
        return self.ok

    def play(self, group: str, data: bytes) -> None:
        chans = self.groups.get(group)
        if not chans or not data:
            return
        free = [c for c in chans if not c.busy()]
        chan = free[0] if free else min(chans, key=lambda c: c.started)
        try:
            chan.play(data)
        except Exception as e:  # noqa: BLE001
            print(f"[Borderlands Access] play failed: {e}")

    def close(self) -> None:
        for chans in self.groups.values():
            for c in chans:
                try:
                    c.close()
                except Exception:
                    pass
        self.groups = {}
        for st in self.streams + self.combat_streams + ([self.nav_stream] if self.nav_stream else []):
            try:
                st.close()
            except Exception:
                pass
        self.streams = []
        self.combat_streams = []
        self.nav_stream = None
        self.ok = False


# --------------------------------------------------------------------------------------
# Synthesis
# --------------------------------------------------------------------------------------

def _wave(kind: str, phase: float) -> float:
    if kind == "sine":
        return math.sin(phase)
    if kind == "square":
        return 0.6 if math.sin(phase) >= 0 else -0.6
    if kind == "triangle":
        x = (phase / (2 * math.pi)) % 1.0
        return 4 * x - 1 if x < 0.5 else 3 - 4 * x
    if kind == "noise":
        return random.uniform(-1, 1)
    return 0.0


def synth(freq: float, dur: float, pan: float = 0.0, vol: float = 0.5, wave: str = "sine",
          freq_end: float | None = None, lowpass: float = 0.0, attack: float = 0.004,
          release: float = 0.03) -> array:
    """Return interleaved stereo int16 samples. pan: -1 left .. +1 right. lowpass: 0..0.95."""
    n = max(1, int(RATE * dur))
    pan = max(-1.0, min(1.0, pan))
    ang = (pan + 1) * math.pi / 4
    lg, rg = math.cos(ang) * 1.41, math.sin(ang) * 1.41
    lg, rg = min(lg, 1.0), min(rg, 1.0)
    out = array("h", bytes(4 * n))
    phase = 0.0
    prev = 0.0
    a_n = max(1, int(RATE * attack))
    r_n = max(1, int(RATE * release))
    amp = 32000 * max(0.0, min(MAX_GAIN, vol))
    f_end = freq if freq_end is None else freq_end
    two_pi_over_rate = 2 * math.pi / RATE
    for i in range(n):
        f = freq + (f_end - freq) * (i / n)
        phase += f * two_pi_over_rate
        s = _wave(wave, phase)
        if lowpass:
            s = prev = prev + (s - prev) * (1 - lowpass)
        env = 1.0
        if i < a_n:
            env = i / a_n
        elif i > n - r_n:
            env = max(0.0, (n - i) / r_n)
        v = s * env * amp
        out[2 * i] = _clip(v * lg)
        out[2 * i + 1] = _clip(v * rg)
    return out


def _clip(v: float) -> int:
    return 32767 if v > 32767 else (-32767 if v < -32767 else int(v))


def silence(dur: float) -> array:
    return array("h", bytes(4 * max(1, int(RATE * dur))))


def join(*parts: array) -> bytes:
    out = array("h")
    for p in parts:
        out.extend(p)
    return out.tobytes()


def _q(x: float, step: float) -> float:
    return round(x / step) * step


# Each cue below is cached on quantised inputs so we only synthesise a handful of variants.

@lru_cache(maxsize=1024)
def _enemy(pan: float, vol: float, pitch: float, behind: bool, visible: bool) -> bytes:
    base = (700 if visible else 520) * pitch
    if behind:
        return join(synth(base * 0.75, 0.07, pan, vol, "triangle", lowpass=0.6))
    return join(synth(base, 0.06, pan, vol, "square" if visible else "sine"))


def enemy_ping(pan: float, vol: float, pitch: float, behind: bool, visible: bool) -> bytes:
    return _enemy(_q(pan, 0.1), _q(vol * gain("radar"), 0.1), _q(pitch, 0.05), behind, visible)


@lru_cache(maxsize=64)
def _beacon(pan: float, vol: float, behind: bool) -> bytes:
    f = 950 if not behind else 700
    return join(synth(f, 0.09, pan, vol, "triangle", lowpass=0.5 if behind else 0.0, release=0.07))


def beacon_ping(pan: float, vol: float, behind: bool) -> bytes:
    return _beacon(_q(pan, 0.1), _q(vol * gain("beacon"), 0.1), behind)


@lru_cache(maxsize=128)
def _npc(pan: float, vol: float, behind: bool) -> bytes:
    # Soft rising two-note bell: friendly, and nothing like the square-wave enemy beeps.
    lp = 0.55 if behind else 0.0
    lo, hi = (440, 554) if behind else (587, 740)
    return join(synth(lo, 0.07, pan, vol, "sine", lowpass=lp, release=0.05),
                synth(hi, 0.11, pan, vol * 0.9, "sine", lowpass=lp, release=0.09))


def npc_chime(pan: float, vol: float, behind: bool) -> bytes:
    return _npc(_q(pan, 0.1), _q(vol * gain("npc"), 0.1), behind)


@lru_cache(maxsize=64)
def _wall(pan: float, vol: float) -> bytes:
    return join(synth(180, 0.035, pan, vol, "noise", lowpass=0.85, release=0.02))


def wall_click(pan: float, vol: float) -> bytes:
    return _wall(_q(pan, 0.25), _q(vol * gain("wall"), 0.1))


@lru_cache(maxsize=16)
def _ledge(pan: float, vol: float) -> bytes:
    return join(synth(700, 0.18, pan, vol, "triangle", freq_end=220))


def ledge_warning(pan: float, vol: float) -> bytes:
    return _ledge(_q(pan, 0.5), _q(vol * gain("ledge"), 0.1))


@lru_cache(maxsize=32)
def _ui(name: str, vol: float) -> bytes:
    if name == "lock":
        return join(synth(900, 0.05, 0, vol, "sine"), synth(1350, 0.07, 0, vol, "sine"))
    if name == "on_target":
        return join(synth(1600, 0.025, 0, vol * 0.7, "sine", release=0.01))
    if name == "lost":
        return join(synth(900, 0.06, 0, vol * 0.6, "sine", freq_end=600))
    if name == "move":
        return join(synth(1200, 0.02, 0, vol * 0.6, "sine", release=0.01))
    if name == "select":
        return join(synth(800, 0.04, 0, vol, "sine"), synth(1200, 0.06, 0, vol, "sine"))
    if name == "back":
        return join(synth(1000, 0.04, 0, vol, "sine"), synth(650, 0.06, 0, vol, "sine"))
    if name == "open":
        return join(synth(600, 0.05, 0, vol, "triangle"), synth(900, 0.05, 0, vol, "triangle"),
                    synth(1200, 0.08, 0, vol, "triangle"))
    if name == "close":
        return join(synth(1200, 0.05, 0, vol, "triangle"), synth(900, 0.05, 0, vol, "triangle"),
                    synth(600, 0.08, 0, vol, "triangle"))
    if name == "on":
        return join(synth(700, 0.05, 0, vol), synth(1050, 0.08, 0, vol))
    if name == "off":
        return join(synth(1050, 0.05, 0, vol), synth(700, 0.08, 0, vol))
    if name == "heartbeat":
        return join(synth(70, 0.09, 0, vol, "sine"), silence(0.08), synth(60, 0.11, 0, vol * 0.8, "sine"))
    if name == "jump":  # quick upward "boing": two rising sweeps, distinct from the falling ledge tone
        return join(synth(420, 0.07, 0, vol, "triangle", freq_end=760),
                    synth(760, 0.09, 0, vol, "triangle", freq_end=1250))
    if name == "modifier":
        return join(synth(500, 0.03, 0, vol * 0.5, "sine"))
    if name == "prompt":  # soft double tick: something you can use is right here
        return join(synth(1500, 0.025, 0, vol * 0.5, "sine", release=0.01), silence(0.05),
                    synth(1500, 0.025, 0, vol * 0.5, "sine", release=0.01))
    if name == "error":
        return join(synth(300, 0.12, 0, vol, "square"))
    return b""


def ui(name: str, vol: float = 0.5) -> bytes:
    return _ui(name, _q(vol * gain("ui_" + name), 0.1))


audio = AudioEngine()


# --------------------------------------------------------------------------------------
# Continuous object sounds ("loops"). Each sound is a short pattern of segments. Every
# frequency is a whole number of cycles per segment, so each segment starts and ends at a
# zero crossing: segments join without clicks even when the pan or volume changes between
# them, and the sound never stops and restarts.
# --------------------------------------------------------------------------------------
SEG = 0.08                      # seconds per segment
SEG_N = int(RATE * SEG)         # 1764 samples
CYCLE = 1 / SEG                 # 12.5 Hz: frequencies are multiples of this

# kind -> list of segments, each (cycles per segment of the fundamental, amplitude);
# plus the harmonic recipe [(harmonic, weight)].
#
# Each kind has its own part of the pitch range, and the middle (about 450 to 1000 Hz) is
# kept clear for the beacon (700 Hz, rising and falling with height), so nothing sounds like
# it or blurs into it:
#   container 200 Hz, ammo 300, doors and switches 375-425    | beacon 500-1000 |
#   quest 1100 + 1650, other loot 1300, gear 1750-2125, money 2500-3000
LOOPS: dict[str, tuple[list[tuple[int, float]], list[tuple[int, float]]]] = {
    # weapons, shields, grenades, relics...: bright two-note shimmer
    "gear": ([(140, 1.0), (140, 1.0), (170, 1.0), (170, 1.0)], [(1, 1.0), (3, 0.08)]),
    # ammo and health: low, soft hum that swells
    "ammo": ([(24, 1.0), (24, 0.85), (24, 0.7), (24, 0.85)], [(1, 1.0), (2, 0.1)]),
    # money and eridium: high sparkle
    "money": ([(200, 0.6), (224, 0.6), (240, 0.6), (224, 0.6)], [(1, 1.0)]),
    # quest items: an open fifth that pulses (two tones at once)
    "quest": ([(88, 1.0), (88, 1.0), (88, 0.55), (88, 0.55)], [(1, 1.0), (1.5, 0.8)]),
    # chests, lockers, crates: woody low buzz
    "container": ([(16, 1.0), (16, 0.65)], [(1, 1.0), (2, 0.3), (3, 0.08)]),
    # doors, switches, vendors, fast travel: mid warble
    "interactive": ([(30, 0.9), (30, 0.9), (34, 0.9), (34, 0.9)], [(1, 1.0), (2, 0.1)]),
    # anything else lying on the ground
    "loot": ([(104, 0.8)], [(1, 1.0)]),
}


def loop_length(kind: str) -> int:
    return len(LOOPS.get(kind, LOOPS["loot"])[0])


@lru_cache(maxsize=256)
def _loop_base(kind: str, step: int, behind: bool) -> tuple:
    """Mono samples (-1..1) for one segment of a loop."""
    pattern, harmonics = LOOPS.get(kind, LOOPS["loot"])
    cycles, amp = pattern[step % len(pattern)]
    if behind:  # muffled: fundamental only, a little quieter
        harmonics = [h for h in harmonics if h[0] == 1] or harmonics[:1]
        amp *= 0.6
    parts = []
    for h, w in harmonics:
        k = round(cycles * h)  # whole cycles per segment keeps the joins clean
        parts.append((2 * math.pi * k / SEG_N, w))
    norm = sum(w for _f, w in parts) or 1.0
    return tuple(amp * sum(w * math.sin(f * i) for f, w in parts) / norm for i in range(SEG_N))


@lru_cache(maxsize=1500)
def _loop_seg(kind: str, step: int, pan_q: int, vol_q: int, behind: bool, fade: int) -> bytes:
    base = _loop_base(kind, step, behind)
    pan = pan_q / 10
    ang = (pan + 1) * math.pi / 4
    lg, rg = min(math.cos(ang) * 1.41, 1.0), min(math.sin(ang) * 1.41, 1.0)
    amp = 30000 * vol_q / 40
    out = array("h", bytes(4 * SEG_N))
    for i, v in enumerate(base):
        e = 1.0
        if fade > 0:      # fading in
            e = i / SEG_N
        elif fade < 0:    # fading out
            e = 1 - i / SEG_N
        v *= amp * e
        out[2 * i] = _clip(v * lg)
        out[2 * i + 1] = _clip(v * rg)
    return out.tobytes()


def loop_segment(kind: str, step: int, pan: float, vol: float, behind: bool, fade: int = 0) -> bytes:
    """One segment of a continuous object sound. fade: 1 fade in, -1 fade out, 0 steady.
    Pan and volume are rounded so segments are reused from the cache."""
    pan_q = int(round(max(-1.0, min(1.0, pan)) * 10))
    vol_q = int(round(max(0.0, min(MAX_GAIN, vol * gain(kind))) * 40))
    return _loop_seg(kind, step % loop_length(kind), pan_q, vol_q, bool(behind), fade)


# --------------------------------------------------------------------------------------
# Continuous enemy tones. Same seamless-segment method as the object loops, but the pitch
# varies (it tells you whether the enemy is above or below your crosshair), so the number of
# cycles per segment is a parameter. Three voices tell you how close your aim is:
#   enemy        a soft, mellow tone: the enemy is off to the side
#   enemy_near   brighter and gently pulsing: within about 10 degrees of your crosshair
#   enemy_locked a buzzy, fast-pulsing tone at a fixed high pitch: you're aimed at it, fire
# --------------------------------------------------------------------------------------
ENEMY_TONES: dict[str, tuple[list[float], list[tuple[int, float]]]] = {
    "enemy": ([1.0], [(1, 1.0), (3, 0.11)]),
    "enemy_near": ([1.0, 1.0, 0.7, 0.7], [(1, 1.0), (2, 0.45), (3, 0.25)]),
    "enemy_locked": ([1.0, 0.25], [(1, 1.0), (3, 0.33), (5, 0.2), (7, 0.14)]),
    # the beacon: mellow when you're not facing the way to go, bright when you are
    "beacon": ([1.0], [(1, 1.0), (2, 0.2)]),
    "beacon_on": ([1.0], [(1, 1.0), (2, 0.5), (3, 0.3), (4, 0.2)]),
}
ENEMY_BASE = 32      # 400 Hz: an enemy level with your crosshair
LOCKED_CYCLES = 80   # 1000 Hz


def enemy_cycles(rel_pitch_deg: float) -> int:
    """Cycles per segment for an enemy this many degrees above (+) or below (-) your aim:
    up to an octave higher or lower at 30 degrees."""
    x = max(-1.0, min(1.0, rel_pitch_deg / 30))
    return max(8, int(round(ENEMY_BASE * 2 ** x)))


@lru_cache(maxsize=512)
def _tone_base(kind: str, cycles: int, step: int, muffled: bool) -> tuple:
    amps, harmonics = ENEMY_TONES.get(kind, ENEMY_TONES["enemy"])
    amp = amps[step % len(amps)]
    if muffled:  # behind you or behind cover: fundamental only, quieter
        harmonics = harmonics[:1]
        amp *= 0.7
    parts = [(2 * math.pi * cycles * h / SEG_N, w) for h, w in harmonics]
    norm = sum(w for _f, w in parts) or 1.0
    return tuple(amp * sum(w * math.sin(f * i) for f, w in parts) / norm for i in range(SEG_N))


@lru_cache(maxsize=2000)
def _tone_seg(kind: str, cycles: int, step: int, pan_q: int, vol_q: int, muffled: bool, fade: int) -> bytes:
    base = _tone_base(kind, cycles, step, muffled)
    ang = (pan_q / 10 + 1) * math.pi / 4
    lg, rg = min(math.cos(ang) * 1.41, 1.0), min(math.sin(ang) * 1.41, 1.0)
    amp = 30000 * vol_q / 40
    out = array("h", bytes(4 * SEG_N))
    for i, v in enumerate(base):
        e = i / SEG_N if fade > 0 else (1 - i / SEG_N if fade < 0 else 1.0)
        v *= amp * e
        out[2 * i] = _clip(v * lg)
        out[2 * i + 1] = _clip(v * rg)
    return out.tobytes()


def tone_segment(kind: str, cycles: int, step: int, pan: float, vol: float, muffled: bool, fade: int = 0) -> bytes:
    amps = ENEMY_TONES.get(kind, ENEMY_TONES["enemy"])[0]
    pan_q = int(round(max(-1.0, min(1.0, pan)) * 10))
    vol_q = int(round(max(0.0, min(MAX_GAIN, vol * gain(kind))) * 40))
    return _tone_seg(kind, int(cycles), step % len(amps), pan_q, vol_q, bool(muffled), fade)


def preview(key: str, vol: float = 0.6) -> bytes:
    """A short sample of one glossary sound at its current volume, for the settings menu."""
    if key.startswith("ui_"):
        return ui(key[3:], vol)
    if key == "radar":
        return join(*[array("h", enemy_ping(0, vol, 1.0, False, True)) + silence(0.12) for _ in range(3)])
    if key in ("beacon", "beacon_on"):
        cyc = 56
        segs = [tone_segment(key, cyc, i, 0, vol * (1.0 if i % 4 == 0 else 0.3), False,
                             1 if i == 0 else (-1 if i == 11 else 0)) for i in range(12)]
        return b"".join(segs)
    if key == "npc":
        return npc_chime(0, vol, False)
    if key == "wall":
        return join(*[array("h", wall_click(0, vol)) + silence(0.1) for _ in range(3)])
    if key == "ledge":
        return ledge_warning(0, vol)
    n = 8
    if key in LOOPS:
        segs = [loop_segment(key, i, 0, vol, False, 1 if i == 0 else (-1 if i == n - 1 else 0)) for i in range(n)]
    elif key in ENEMY_TONES:
        cycles = LOCKED_CYCLES if key == "enemy_locked" else ENEMY_BASE
        segs = [tone_segment(key, cycles, i, 0, vol, False, 1 if i == 0 else (-1 if i == n - 1 else 0)) for i in range(n)]
    else:
        return b""
    return b"".join(segs)
