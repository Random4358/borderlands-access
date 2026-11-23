"""Controller combos, keyboard fallbacks, menu tracking and menu navigation sounds.

Controller scheme: hold the *modifier* button (default: Back/View) and press another button.
While the modifier is held the other buttons are swallowed so the game doesn't also jump,
reload, etc. A quick tap of the modifier on its own is passed through to the game.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from . import audio as snd
from .audio import audio
from .features import features
from .speech import speech

# --------------------------------------------------------------------------------------
# Actions (shared by controller combos and keyboard keybinds)
# --------------------------------------------------------------------------------------


def _toggle(attr: str, label: str) -> Callable[[], None]:
    def fn() -> None:
        new = not getattr(features.s, attr)
        setattr(features.s, attr, new)
        on_toggle(attr, new)
        audio.play("ui", snd.ui("on" if new else "off", features.s.volume))
        speech.say(f"{label} {'on' if new else 'off'}")

    return fn


def _repeat() -> None:
    if menus.in_menu():
        from .menu_reader import reader
        from .panel_reader import HANDLED, panels

        movie = panels.focus_movie()
        from . import game

        if movie is not None and game.class_name(movie) not in HANDLED and panels.last_spoken:
            speech.say(panels.last_spoken)
            return
        reader.read_current()
    else:
        speech.repeat()


def _trace() -> None:
    from . import trace

    trace.toggle_menus()


_last_run: dict[str, float] = {}


def run_action(name: str) -> None:
    """Run an action once. Keyboard shortcuts can arrive through both the game's input route
    and a menu's own button route, so ignore a repeat of the same action within 0.25 s."""
    from .mod_menu import modmenu

    if modmenu.is_open and name not in ("settings", "stop"):
        return
    now = time.perf_counter()
    if now - _last_run.get(name, 0.0) < 0.25:
        return
    _last_run[name] = now
    try:
        ACTIONS[name][1]()
    except Exception as e:  # noqa: BLE001
        print(f"[Borderlands Access] action {name} failed: {e}")


# Set by __init__: maps a key name to the action whose keyboard shortcut is currently bound to it
# (follows rebinding in the mod menu). Menus bypass the normal keybind route, so menu_key uses it.
keyboard_action_for: Callable[[str], str | None] = lambda key: None

# Set by __init__ so toggles are written back to the saved mod options.
on_toggle: Callable[[str, bool], None] = lambda attr, value: None

ACTIONS: dict[str, tuple[str, Callable[[], None]]] = {
    "snap_aim": ("Aim at nearest enemy, press again to cycle", lambda: features.snap_aim()),
    "status": ("Health, shield and weapon", lambda: features.report_status()),
    "enemies": ("List nearby enemies", lambda: features.report_enemies()),
    "repeat": ("Repeat last speech, or re-read the highlighted menu entry", lambda: _repeat()),
    "poi_next": ("Next item in scanner category", lambda: features.cycle_poi(1)),
    "poi_prev": ("Previous item in scanner category", lambda: features.cycle_poi(-1)),
    "poi_rescan": ("Rescan and summarise nearby things", lambda: features.rescan_pois()),
    "mission": ("Current mission and objectives", lambda: features.current_mission()),
    "cat_next": ("Next scanner category", lambda: features.cycle_category(1)),
    "cat_prev": ("Previous scanner category", lambda: features.cycle_category(-1)),
    "beacon": ("Toggle beacon to selected point", lambda: features.toggle_beacon()),
    "heading": ("Heading and location", lambda: features.report_heading()),
    "face": ("Turn toward the objective (lock-on navigation)", lambda: features.face_objective()),
    "stick_r": ("Turn toward the objective when lock-on navigation is on, otherwise heading",
                lambda: features.face_objective() if features.s.lock_nav else features.report_heading()),
    "level": ("Level view to horizon", lambda: features.level_view()),
    "turn": ("Turn around", lambda: features.turn_around()),
    "radar": ("Toggle enemy radar", _toggle("radar", "Enemy radar")),
    "walls": ("Toggle wall sounds", _toggle("walls", "Wall sounds")),
    "targeting": ("Toggle targeting sounds", _toggle("targeting", "Targeting")),
    "help": ("Speak controls", lambda: speak_help()),
    "stop": ("Stop speech", lambda: speech.stop()),
    "trace": ("Start or stop the menu trace tool", lambda: _trace()),
    "settings": ("Open or close the accessibility settings", lambda: _settings()),
}

# Controller combos: modifier + key -> action.
COMBOS: dict[str, str] = {
    "XboxTypeS_A": "snap_aim",
    "XboxTypeS_X": "status",
    "XboxTypeS_Y": "enemies",
    "XboxTypeS_B": "repeat",
    # Scanner: left/right picks a category, up/down moves through it, left trigger = beacon.
    "XboxTypeS_DPad_Up": "poi_prev",
    "XboxTypeS_DPad_Down": "poi_next",
    "XboxTypeS_DPad_Right": "cat_next",
    "XboxTypeS_DPad_Left": "cat_prev",
    "XboxTypeS_LeftTrigger": "beacon",
    "XboxTypeS_RightTrigger": "poi_rescan",
    "XboxTypeS_LeftThumbStick": "level",
    "XboxTypeS_RightThumbStick": "stick_r",
    "XboxTypeS_RightShoulder": "radar",
    "XboxTypeS_LeftShoulder": "walls",
    "XboxTypeS_Start": "help",
}

PAD_NAMES = {
    "XboxTypeS_A": "A", "XboxTypeS_B": "B", "XboxTypeS_X": "X", "XboxTypeS_Y": "Y",
    "XboxTypeS_DPad_Up": "D-pad up", "XboxTypeS_DPad_Down": "D-pad down",
    "XboxTypeS_DPad_Left": "D-pad left", "XboxTypeS_DPad_Right": "D-pad right",
    "XboxTypeS_LeftThumbStick": "left stick click", "XboxTypeS_RightThumbStick": "right stick click",
    "XboxTypeS_LeftShoulder": "left bumper", "XboxTypeS_RightShoulder": "right bumper",
    "XboxTypeS_LeftTrigger": "left trigger", "XboxTypeS_RightTrigger": "right trigger",
    "XboxTypeS_Start": "Start", "XboxTypeS_Back": "Back",
}

MODIFIER_CHOICES = {
    "Back / View": "XboxTypeS_Back",
    "Left stick click": "XboxTypeS_LeftThumbStick",
    "Right stick click": "XboxTypeS_RightThumbStick",
    "D-pad left": "XboxTypeS_DPad_Left",
}

ADS_KEYS = {"XboxTypeS_LeftTrigger", "RightMouseButton"}
MENU_MOVE = {"XboxTypeS_DPad_Up", "XboxTypeS_DPad_Down", "XboxTypeS_DPad_Left", "XboxTypeS_DPad_Right",
             "Up", "Down", "Left", "Right", "W", "S", "A", "D", "Gamepad_LeftStick_Up",
             "Gamepad_LeftStick_Down", "Gamepad_LeftStick_Left", "Gamepad_LeftStick_Right",
             "XboxTypeS_LeftShoulder", "XboxTypeS_RightShoulder", "Q", "E"}
MENU_SELECT = {"XboxTypeS_A", "Enter", "SpaceBar"}
MENU_BACK = {"XboxTypeS_B", "Escape", "BackSpace"}


def _settings() -> None:
    from .mod_menu import modmenu

    modmenu.toggle()


def speak_help() -> None:
    mod = PAD_NAMES.get(state.modifier, state.modifier)
    lines = [f"Press {mod} three times quickly for the accessibility settings", f"Hold {mod} and press"]
    for key, action in COMBOS.items():
        if key == state.modifier:
            continue
        lines.append(f"{PAD_NAMES.get(key, key)}: {ACTIONS[action][0]}")
    speech.say(". ".join(lines))


# --------------------------------------------------------------------------------------
# Input state machine
# --------------------------------------------------------------------------------------


class InputState:
    TAP_SECONDS = 0.35

    def __init__(self) -> None:
        self.modifier = "XboxTypeS_Back"
        self.mod_down = False
        self.mod_down_at = 0.0
        self.combo_used = False
        self.swallowed: set[str] = set()
        self.replaying = False
        self.menu_sounds = True
        self._last_menu_key = ""
        self._last_menu_key_at = 0.0
        self.last_device = "pad"         # "pad" or "keyboard": which button names prompts use
        self.taps: list[float] = []      # recent quick taps of the modifier
        self.pending_tap: tuple[float, Any, int, str, int] | None = None  # due, weak obj, cid, key, count

    MULTI_TAP_WINDOW = 0.35  # a tap is passed to the game only once no further tap follows in this time

    def tick(self) -> None:
        """Pass held-back modifier taps to the game once it's clear they weren't a triple press."""
        if self.pending_tap is None or time.perf_counter() < self.pending_tap[0]:
            return
        _due, ptr, cid, key, count = self.pending_tap
        self.pending_tap = None
        self.taps = []
        from .game import deref

        obj = deref(ptr)
        for _ in range(count):
            self.replay(obj, cid, key)

    def handle(self, obj: Any, controller_id: int, key: str, pressed: bool, released: bool) -> bool:
        """Return True to swallow the input."""
        if self.replaying:
            return False
        if pressed:
            self.last_device = "pad" if key.startswith(("XboxTypeS_", "Gamepad_")) else "keyboard"
            from . import trace

            trace.note(f"input {key} (in menu: {menus.in_menu()})")

        from .mod_menu import modmenu

        if modmenu.is_open:  # the accessibility settings get every button while open
            if pressed:
                self.swallowed.add(key)  # its release may arrive after the menu has closed
                if key == self.modifier:
                    modmenu.close()
                else:
                    modmenu.key(key)
            if key in ADS_KEYS:
                features.ads_held = False
            self.mod_down = False
            return True

        if released and key in self.swallowed:  # release of a press something else consumed
            self.swallowed.discard(key)
            if key == self.modifier:
                self.mod_down = False
            return True

        if key in ADS_KEYS and not self.mod_down:
            if pressed:
                features.ads_held = True
            elif released:
                features.ads_held = False

        if key == self.modifier:
            if pressed:
                self.mod_down = True
                self.mod_down_at = time.perf_counter()
                self.combo_used = False
                audio.play("ui", snd.ui("modifier", features.s.volume))
                return True
            if released:
                self.mod_down = False
                now = time.perf_counter()
                quick = now - self.mod_down_at < self.TAP_SECONDS
                if quick and not self.combo_used:
                    self.taps = [t for t in self.taps if now - t < 1.0] + [now]
                    if len(self.taps) >= 3:  # triple press: accessibility settings
                        self.taps = []
                        self.pending_tap = None
                        from .mod_menu import modmenu

                        modmenu.open()
                        return True
                    from .game import weak

                    # Hold the tap back briefly in case it's the start of a triple press.
                    self.pending_tap = (now + self.MULTI_TAP_WINDOW, weak(obj), controller_id, key, len(self.taps))
                else:
                    self.taps = []
                return True
            return True  # swallow repeats

        if self.mod_down and key in COMBOS:
            if pressed:
                self.combo_used = True
                self.swallowed.add(key)
                name = COMBOS[key]
                try:
                    ACTIONS[name][1]()
                except Exception as e:  # noqa: BLE001
                    print(f"[Borderlands Access] action {name} failed: {e}")
            elif released:
                self.swallowed.discard(key)
            return True

        # Swallow the release of a key whose press we consumed, even if modifier was let go.
        if key in self.swallowed:
            if released:
                self.swallowed.discard(key)
            return True

        if pressed and menus.in_menu():
            self.menu_key(key, "ui")
        return False

    def menu_key(self, key: str, source: str) -> None:
        """A key pressed while a menu is open. Menus can report the same press through more
        than one hook (the UI interaction and the menu's own key handler), so de-duplicate."""
        now = time.perf_counter()
        if key == self._last_menu_key and now - self._last_menu_key_at < 0.02:
            return
        self._last_menu_key, self._last_menu_key_at = key, now
        from . import trace
        from .menu_reader import reader

        trace.note(f"menu key {key} via {source}")
        action = keyboard_action_for(key)
        if action is not None:
            run_action(action)
            return
        # Cinematics and loading screens also count as "no character", but have no options:
        # stay quiet there.
        sounds = self.menu_sounds and menus.has_options()
        if key in MENU_MOVE:
            reader.before_nav(key)
            from .panel_reader import panels

            panels.before_nav()
            if sounds:
                audio.play("ui", snd.ui("move", features.s.volume))
        elif key in MENU_SELECT and sounds:
            audio.play("ui", snd.ui("select", features.s.volume))
        elif key in MENU_BACK and sounds:
            audio.play("ui", snd.ui("back", features.s.volume))

    def replay(self, obj: Any, controller_id: int, key: str) -> None:
        """Send a lone tap of the modifier through to the game."""
        from .hooks import EV_PRESSED, EV_RELEASED

        self.replaying = True
        try:
            targets = []
            try:
                from . import game

                pc = game.pc()
                if pc is not None and pc.PlayerInput is not None:
                    targets.append(pc.PlayerInput)
            except Exception:
                pass
            targets.append(obj)
            for t in targets:
                try:
                    t.InputKey(controller_id, key, EV_PRESSED, 1.0, True)
                    t.InputKey(controller_id, key, EV_RELEASED, 0.0, True)
                    break
                except Exception:
                    continue
        finally:
            self.replaying = False


state = InputState()


# --------------------------------------------------------------------------------------
# Menus
# --------------------------------------------------------------------------------------

MENU_NAMES = {
    "FrontendGFxMovie": "Main menu",
    "StatusMenuExGFxMovie": "Inventory and status menu",
    "VendingMachineExGFxMovie": "Vending machine",
    "QuestAcceptGFxMovie": "Mission",
    "FastTravelStationGFxMovie": "Fast travel",
    "VehicleSpawnStationGFxMovie": "Catch a ride",
    "CustomizationGFxMovie": "Customization",
    "PauseGFxMovie": "Pause menu",
    "BankGFxMovie": "Bank",
    "LatentRewardGFxMovie": "Reward",
    "TrainingDialogGFxMovie": "Tutorial message",
    "WillowGFxMoviePressStart": "Title screen. Press A or Enter to start",
    "OnlineMessageGFxMovie": "Online status message from the game. Press A or Enter to continue",
    "CharacterSelectionReduxGFxMovie": "Character selection",
    "WillowGFxLobbyLoadCharacter": "Load character",
}


# Words in the class names of screens that have options to move between.
MENU_WORDS = ("menu", "dialog", "frontend", "options", "lobby", "selection", "vending", "bank", "fasttravel",
              "customization", "questaccept", "latentreward", "pressstart", "onlinemessage", "trading", "station")

# Flash movies that are always on screen during play; they never mean "a menu is open".
OVERLAY_WORDS = ("hud", "scope", "crosshair", "reticle", "subtitle", "compass", "marker", "hint",
                 "textchat", "notification", "pressstart", "onlinemessage")


class Menus:
    def __init__(self) -> None:
        self.open: dict[str, str] = {}
        self.ptrs: dict[str, Any] = {}  # path -> WeakPointer, so closed-but-missed menus get pruned
        self.announce = True
        self.last_movie_ptr: Any = None  # WeakPointer; used to resolve '$Localisation.Keys'
        self._last_focus = ""

    def _prune(self) -> None:
        from .game import deref

        for k in [k for k in self.open if deref(self.ptrs.get(k)) is None]:
            self.open.pop(k, None)
            self.ptrs.pop(k, None)

    def world_sounds_paused(self) -> bool:
        """True while in-world cues (radar, walls, beacon...) should be silent: a menu is open,
        the game is paused, or a menu has input focus."""
        from . import game, trace
        from .mod_menu import modmenu

        if modmenu.is_open:  # quiet, so sound previews can be heard
            return True
        self._prune()
        if self.open:
            return True
        pc = game.pc()
        if pc is None:
            return True
        try:
            if pc.WorldInfo.Pauser is not None:
                return True
        except Exception:
            pass
        try:
            fm = pc.GFxUIManager.FindFocusMovie()
        except Exception:
            fm = None
        cls = game.class_name(fm) if fm is not None else ""
        if cls != self._last_focus:
            self._last_focus = cls
            trace.note(f"focus movie: {cls or 'none'}")
        return bool(cls) and not any(w in cls.lower() for w in OVERLAY_WORDS)

    @property
    def last_movie(self) -> Any:
        from .game import deref

        return deref(self.last_movie_ptr)

    def opened(self, movie: Any) -> None:
        from . import game

        from . import trace

        self.last_movie_ptr = game.weak(movie)
        cls = game.class_name(movie)
        trace.note(f"movie opened: {cls}")
        if cls not in MENU_NAMES:
            return
        try:
            key = movie._path_name()
        except Exception:
            key = cls
        if key in self.open:
            return
        self.open[key] = cls
        self.ptrs[key] = game.weak(movie)
        if self.announce:
            audio.play("ui", snd.ui("open", features.s.volume))
            speech.say(MENU_NAMES[cls])

    def closed(self, movie: Any) -> None:
        from . import game

        try:
            key = movie._path_name()
        except Exception:
            key = game.class_name(movie)  # same fallback as opened()
        cls = self.open.pop(key, None)
        self.ptrs.pop(key, None)
        if cls and self.announce:
            audio.play("ui", snd.ui("close", features.s.volume))

    def has_options(self) -> bool:
        """True when a screen with options to move between is up: a menu we know, a live menu
        list, or a menu-type screen with input focus. Not cinematics or loading screens, which
        also leave you without a character but have nothing to choose."""
        from . import game
        from .menu_reader import reader

        self._prune()
        if self.open:
            return True
        st = reader.current
        try:
            if st is not None and st.obj is not None and st.items:
                return True
        except Exception:
            pass
        pc = game.pc()
        try:
            fm = pc.GFxUIManager.FindFocusMovie() if pc is not None else None
        except Exception:
            fm = None
        cls = game.class_name(fm).lower() if fm is not None else ""
        return bool(cls) and any(w in cls for w in MENU_WORDS) and not any(
            w in cls for w in OVERLAY_WORDS if w not in ("pressstart", "onlinemessage"))

    def in_menu(self) -> bool:
        self._prune()
        if self.open:
            return True
        from . import game

        return game.player_pawn() is None


menus = Menus()
