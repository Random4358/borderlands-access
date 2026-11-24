"""Unreal function hooks. Registered by hand (not with @hook) so that a function name that
doesn't exist in this game build is simply skipped instead of breaking the mod."""

from __future__ import annotations

import time
import traceback
from typing import Any

from mods_base import EInputEvent
from unrealsdk import hooks as uhooks
from unrealsdk.hooks import Block, Type

from .controls import menus, state
from .features import features

EV_PRESSED = EInputEvent.IE_Pressed
EV_RELEASED = EInputEvent.IE_Released
_ID = "bl2_access"
TICK_INTERVAL = 1 / 30

# Input: WillowUIInteraction sees keyboard + controller input before the player does.
INPUT_HOOKS = ["WillowGame.WillowUIInteraction:InputKey"]
# Per-frame: whichever of these the game actually calls drives our update loop.
TICK_HOOKS = ["WillowGame.WillowGameViewportClient:Tick", "Engine.GameViewportClient:Tick"]
MENU_OPEN_HOOKS = [
    "GFxUI.GFxMoviePlayer:Start",
    "WillowGame.WillowGFxMovie:Start",
    "WillowGame.FrontendGFxMovie:Start",
    "WillowGame.StatusMenuExGFxMovie:Start",
    "WillowGame.VendingMachineExGFxMovie:Start",
    "WillowGame.QuestAcceptGFxMovie:Start",
    "WillowGame.FastTravelStationGFxMovie:Start",
    "WillowGame.VehicleSpawnStationGFxMovie:Start",
    "WillowGame.CustomizationGFxMovie:Start",
    "WillowGame.LatentRewardGFxMovie:Start",
    "WillowGame.TrainingDialogGFxMovie:Start",
]
MENU_CLOSE_HOOKS = ["GFxUI.GFxMoviePlayer:Close", "WillowGame.WillowGFxMovie:OnClose"]

_last_tick = 0.0
PRE_TICK: Any = None  # set by __init__ to copy option values into features.s
_errors: dict[str, int] = {}
_registered: list[tuple[str, Any, str]] = []


def _report(where: str) -> None:
    n = _errors.get(where, 0)
    _errors[where] = n + 1
    if n < 3:  # don't flood the console every frame
        print(f"[Borderlands Access] error in {where}:\n{traceback.format_exc()}")


def _arg(args: Any, *names: str) -> Any:
    for n in names:
        try:
            return getattr(args, n)
        except Exception:
            continue
    return None


def on_input(obj: Any, args: Any, ret: Any, func: Any) -> Any:
    try:
        key = str(_arg(args, "Key"))
        ev = _arg(args, "Event", "EventType")
        cid = _arg(args, "ControllerId") or 0
        pressed = ev == EV_PRESSED
        released = ev == EV_RELEASED
        if state.handle(obj, cid, key, pressed, released):
            return Block, True
    except Exception:
        _report("input")
    return None


def on_tick(obj: Any, args: Any, ret: Any, func: Any) -> None:
    global _last_tick
    now = time.perf_counter()
    if now - _last_tick < TICK_INTERVAL:
        return
    _last_tick = now
    try:
        if PRE_TICK is not None:
            PRE_TICK()
        try:
            state.tick()
        except Exception:
            _report("input tick")
        try:
            from .menu_reader import reader

            reader.tick()
        except Exception:
            _report("menu tick")
        try:
            from .panel_reader import panels

            panels.tick()
        except Exception:
            _report("panel tick")
        try:
            from .status_reader import status

            status.tick()
        except Exception:
            _report("status tick")
        try:
            from .screen_text import screen_text

            screen_text.tick()
        except Exception:
            _report("screen text tick")
        features.tick()
    except Exception:
        _report("tick")


def on_menu_open(obj: Any, args: Any, ret: Any, func: Any) -> None:
    try:
        menus.opened(obj)
    except Exception:
        _report("menu open")


def on_menu_close(obj: Any, args: Any, ret: Any, func: Any) -> None:
    try:
        menus.closed(obj)
    except Exception:
        _report("menu close")


def register() -> None:
    unregister()
    plan = (
        [(n, Type.PRE, on_input) for n in INPUT_HOOKS]
        + [(n, Type.POST, on_tick) for n in TICK_HOOKS]
        + [(n, Type.POST, on_menu_open) for n in MENU_OPEN_HOOKS]
        + [(n, Type.PRE, on_menu_close) for n in MENU_CLOSE_HOOKS]
    )
    for name, kind, cb in plan:
        try:
            uhooks.add_hook(name, kind, _ID, cb)
            _registered.append((name, kind, _ID))
        except Exception as e:  # noqa: BLE001
            print(f"[Borderlands Access] skipped hook {name}: {e}")


def unregister() -> None:
    for name, kind, ident in _registered:
        try:
            uhooks.remove_hook(name, kind, ident)
        except Exception:
            pass
    _registered.clear()
