"""The accessibility settings menu: every mod option plus the sound glossary, read aloud.

Open it by pressing your modifier button three times quickly (or the keyboard shortcut,
Equals by default). While it's open the game doesn't get your button presses, and the
mod's world sounds are quiet so you can hear the sound previews.

  D-pad up / down (arrow keys)          previous / next setting in this group
  Bumpers (Q / E)                       previous / next group
  D-pad left / right (arrow keys)       change the value (sound volumes play a preview)
  A (Enter or Space)                    toggle, press a button, or play the sound
  Y (Tab)                               describe the setting
  X (R)                                 reset to its default
  B, or the modifier button (Escape)    close; settings are saved

Sound glossary entries say what each sound means, and their volume goes from 0 to 300%.
"""

from __future__ import annotations

from typing import Any, Callable

from . import audio as snd
from .audio import audio
from .speech import speech

UP = {"XboxTypeS_DPad_Up", "Gamepad_LeftStick_Up", "Up", "W"}
DOWN = {"XboxTypeS_DPad_Down", "Gamepad_LeftStick_Down", "Down", "S"}
LEFT = {"XboxTypeS_DPad_Left", "Gamepad_LeftStick_Left", "Left", "A"}
RIGHT = {"XboxTypeS_DPad_Right", "Gamepad_LeftStick_Right", "Right", "D"}
NEXT_GROUP = {"XboxTypeS_RightShoulder", "E"}
PREV_GROUP = {"XboxTypeS_LeftShoulder", "Q"}
ACTIVATE = {"XboxTypeS_A", "Enter", "SpaceBar"}
DESCRIBE = {"XboxTypeS_Y", "Tab"}
RESET = {"XboxTypeS_X", "R"}
CLOSE = {"XboxTypeS_B", "Escape", "BackSpace", "XboxTypeS_Start"}


def kind(opt: Any) -> str:
    for cls in type(opt).__mro__:
        name = cls.__name__
        if name in ("BoolOption", "SliderOption", "DropdownOption", "SpinnerOption", "ButtonOption"):
            return name
    return ""


def name_of(opt: Any) -> str:
    return str(getattr(opt, "display_name", "") or getattr(opt, "identifier", "") or "Setting")


class ModMenu:
    def __init__(self) -> None:
        self.is_open = False
        self.groups: list[tuple[str, list[Any]]] = []
        self.gi = 0
        self.ii = 0
        self.sound_keys: dict[int, str] = {}       # id(option) -> glossary key
        self.sound_notes: dict[int, str] = {}      # id(option) -> what the sound means
        self.options: list[Any] = []                # top-level options (GroupedOptions), set by __init__
        self.save: Callable[[], None] | None = None
        self.volume: Callable[[], float] = lambda: 0.8

    # ------------------------------------------------------------ setup
    def configure(self, options: list[Any], sound_options: dict[str, Any],
                  save: Callable[[], None], volume: Callable[[], float]) -> None:
        self.options = options
        self.save = save
        self.volume = volume
        notes = {k: d for k, _n, d in snd.SOUNDS}
        self.sound_keys = {id(o): k for k, o in sound_options.items()}
        self.sound_notes = {id(o): notes.get(k, "") for k, o in sound_options.items()}

    def _build(self) -> None:
        self.groups = []
        loose = []
        for opt in self.options:
            children = getattr(opt, "children", None)
            if children is not None:
                items = [c for c in children if not getattr(c, "is_hidden", False) and kind(c)]
                if items:
                    self.groups.append((name_of(opt), items))
            elif kind(opt) and not getattr(opt, "is_hidden", False):
                loose.append(opt)
        if loose:
            self.groups.insert(0, ("General", loose))

    # ------------------------------------------------------------ open / close
    def toggle(self) -> None:
        self.close() if self.is_open else self.open()

    def open(self) -> None:
        self._build()
        if not self.groups:
            speech.say("No settings found")
            return
        self.is_open = True
        self.gi = min(self.gi, len(self.groups) - 1)
        self.ii = min(self.ii, len(self.groups[self.gi][1]) - 1)
        audio.play("ui", snd.ui("open", self.volume()))
        speech.say(f"Accessibility settings. {len(self.groups)} groups. "
                   f"Up and down to move, left and right to change, bumpers for groups, B to close. "
                   + self._group_text() + ". " + self._item_text())

    def close(self) -> None:
        if not self.is_open:
            return
        self.is_open = False
        if self.save is not None:
            try:
                self.save()
            except Exception as e:  # noqa: BLE001
                print(f"[Borderlands Access] saving settings failed: {e}")
        audio.play("ui", snd.ui("close", self.volume()))
        speech.say("Settings saved and closed")

    # ------------------------------------------------------------ reading
    @property
    def current(self) -> Any:
        return self.groups[self.gi][1][self.ii]

    def _group_text(self) -> str:
        name, items = self.groups[self.gi]
        return f"{name} group, {self.gi + 1} of {len(self.groups)}, {len(items)} settings"

    def value_text(self, opt: Any) -> str:
        k = kind(opt)
        v = getattr(opt, "value", None)
        if k == "BoolOption":
            return "on" if v else "off"
        if k == "SliderOption":
            num = int(v) if float(v).is_integer() else round(float(v), 2)
            unit = " percent" if id(opt) in self.sound_keys or "volume" in name_of(opt).lower() else ""
            return f"{num}{unit}"
        if k in ("DropdownOption", "SpinnerOption"):
            return str(v)
        if k == "ButtonOption":
            return "button, press A"
        return str(v)

    def _item_text(self) -> str:
        opt = self.current
        n = len(self.groups[self.gi][1])
        return f"{name_of(opt)}, {self.value_text(opt)}. {self.ii + 1} of {n}"

    def describe(self) -> None:
        opt = self.current
        note = self.sound_notes.get(id(opt)) or str(getattr(opt, "description", "") or "")
        extra = ""
        k = kind(opt)
        if k == "SliderOption":
            extra = f" Range {getattr(opt, 'min_value', 0):g} to {getattr(opt, 'max_value', 100):g}."
        elif k in ("DropdownOption", "SpinnerOption"):
            extra = " Choices: " + ", ".join(str(c) for c in getattr(opt, "choices", [])) + "."
        speech.say((note or "No description.") + extra)

    # ------------------------------------------------------------ changing
    def _set(self, opt: Any, value: Any) -> None:
        opt.value = value

    def change(self, step: int) -> None:
        opt = self.current
        k = kind(opt)
        if k == "BoolOption":
            self._set(opt, not opt.value)
        elif k == "SliderOption":
            lo, hi = float(getattr(opt, "min_value", 0)), float(getattr(opt, "max_value", 100))
            inc = float(getattr(opt, "step", 1) or 1)
            v = max(lo, min(hi, float(opt.value) + inc * step))
            if getattr(opt, "is_integer", True):
                v = int(round(v))
            if v == opt.value:
                audio.play("ui", snd.ui("error", self.volume()))
                speech.say(f"{'Maximum' if step > 0 else 'Minimum'}, {self.value_text(opt)}")
                return
            self._set(opt, v)
        elif k in ("DropdownOption", "SpinnerOption"):
            choices = list(getattr(opt, "choices", []))
            if not choices:
                return
            i = choices.index(opt.value) if opt.value in choices else 0
            self._set(opt, choices[(i + step) % len(choices)])
        else:
            speech.say("Press A to use this")
            return
        audio.play("ui", snd.ui("move", self.volume()))
        speech.say(self.value_text(opt))
        self._preview(opt)

    def _preview(self, opt: Any) -> None:
        key = self.sound_keys.get(id(opt))
        if key is None:
            return
        snd.GAINS[key] = float(opt.value) / 100  # hear the new volume straight away
        data = snd.preview(key, 0.6 * self.volume())
        if data:
            audio.play("ui", data)

    def activate(self) -> None:
        opt = self.current
        k = kind(opt)
        if id(opt) in self.sound_keys:
            self._preview(opt)
            return
        if k == "BoolOption":
            self.change(1)
        elif k in ("DropdownOption", "SpinnerOption"):
            self.change(1)
        elif k == "ButtonOption":
            fn = getattr(opt, "on_press", None)
            if fn is not None:
                fn(opt)
        else:
            speech.say("Use left and right to change this")

    def reset(self) -> None:
        opt = self.current
        if not hasattr(opt, "default_value"):
            return
        self._set(opt, opt.default_value)
        speech.say(f"Reset to {self.value_text(opt)}")
        self._preview(opt)

    # ------------------------------------------------------------ navigation
    def move(self, step: int) -> None:
        n = len(self.groups[self.gi][1])
        self.ii = (self.ii + step) % n
        audio.play("ui", snd.ui("move", self.volume()))
        speech.say(self._item_text())
        if id(self.current) in self.sound_keys:
            self._preview(self.current)

    def move_group(self, step: int) -> None:
        self.gi = (self.gi + step) % len(self.groups)
        self.ii = 0
        audio.play("ui", snd.ui("move", self.volume()))
        speech.say(self._group_text() + ". " + self._item_text())

    def key(self, key: str) -> None:
        """A key pressed while the menu is open."""
        if not self.is_open or not self.groups:
            return
        if key in UP:
            self.move(-1)
        elif key in DOWN:
            self.move(1)
        elif key in LEFT:
            self.change(-1)
        elif key in RIGHT:
            self.change(1)
        elif key in NEXT_GROUP:
            self.move_group(1)
        elif key in PREV_GROUP:
            self.move_group(-1)
        elif key in ACTIVATE:
            self.activate()
        elif key in DESCRIBE:
            self.describe()
        elif key in RESET:
            self.reset()
        elif key in CLOSE:
            self.close()


modmenu = ModMenu()
