"""Reads Borderlands 2 menus aloud.

What is covered, and how:

* Scrolling-list menus (main menu, pause menu, options, mod menu). We record every entry as the
  game adds it (``WillowScrollingList:AddListItem`` / ``AddSpinnerListItem`` / ``AddSliderListItem``),
  so we know each entry's caption, spinner choices and slider range.
  - Options menus call ``UpdateDescriptionText(EventID, TheList)`` whenever the highlight moves,
    which tells us exactly which entry is focused, so we read it with its value and description.
  - Spinner/slider changes (``HandleSpinnerChange`` / ``HandleSliderChange``) speak the new value.
  - Main/pause menus have no such callback, so after each navigation key we compare the list's
    integer properties before and after; the one that moved is the selection index. The result
    is remembered per list class, so this self-calibration only happens once.
* Dialog boxes (``WillowGFxDialogBox``): title, message, then the highlighted button.
* Training/tutorial pop-ups (``ShowTrainingDialog``): title and message.

Hook names are checked against the live game classes before registering, and anything missing
is skipped. Inventory, vendors and other non-list menus still need their hooks found with
the trace tool (see trace.py).
"""

from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass, field
from typing import Any

import unrealsdk
from unrealsdk import hooks as uhooks
from unrealsdk.hooks import Type

from . import audio as snd
from .audio import audio
from .features import features
from .speech import speech

_ID = "bl2_access_menu"


# ------------------------------------------------------------------------------ helpers

# Symbols the game uses for layout that a screen reader would read out by name.
_LAYOUT_SYMBOLS = re.compile("[\u2022\u00b7\u25cf\u25aa\u25a0\u2023\u2043|~^*#_\\\\]+")
# Private-use glyphs (button icons in the game's fonts), the replacement character and
# other invisible characters.
_JUNK = re.compile("[\ue000-\uf8ff\ufffd\u200b-\u200f\u2028\u2029\ufeff\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _fix_mojibake(s: str) -> str:
    """Text that was UTF-8 but got read as Windows-1252 (e.g. "donâ€™t"): undo it."""
    if not any(m in s for m in ("\u00e2\u20ac", "\u00c3", "\u00c2")):
        return s
    try:
        return s.encode("cp1252").decode("utf-8")
    except Exception:
        return s


def clean(text: Any) -> str:
    s = "" if text is None else str(text)
    s = _fix_mojibake(s)
    s = re.sub(r"<br\s*/?>", ". ", s, flags=re.I)  # line breaks in Flash HTML
    s = re.sub(r"<[^>]+>", " ", s)            # other Flash HTML (<font>, <i>, ...)
    s = re.sub(r"\[/?-?[a-z_]+\]", "", s)     # [skill] ... [-skill] markup
    s = re.sub(r"\\[nrt]", " ", s)            # escaped line breaks written out as \n
    s = html.unescape(s)                       # &amp; &nbsp; &#39; ...
    s = s.replace("\u00a0", " ")
    s = _JUNK.sub("", s)
    s = _LAYOUT_SYMBOLS.sub(" ", s)
    s = re.sub(r"(?<=[A-Za-z])0(?=[A-Za-z]|\b)", "o", s)  # Zer0, Decepti0n -> Zero, Deception
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+([.,;:!?])", r"\1", s)
    return re.sub(r"([.!?])(\s*[.!?])+", r"\1", s)  # ". ." left by removed line breaks


def _resolvers(list_obj: Any, movie: Any = None):
    """Movies that can turn '$Package.Section.Key' markup into text, best first."""
    if movie is not None:
        yield movie
    if list_obj is not None:
        try:
            if list_obj.MyOwnerMovie is not None:
                yield list_obj.MyOwnerMovie
        except Exception:
            pass
    from .controls import menus

    last = menus.last_movie  # None if the game already deleted it
    if last is not None:
        yield last
    for cls in ("FrontendGFxMovie", "WillowGFxMovie", "GFxMoviePlayer"):
        try:
            for m in unrealsdk.find_all(cls, exact=False):
                if "Default__" not in m._path_name():
                    yield m
                    break
        except Exception:
            continue


def resolve_strict(text: str, list_obj: Any = None, movie: Any = None) -> str | None:
    """Like resolve(), but returns None when a '$Key' reference can't be looked up."""
    if not text.startswith("$"):
        return clean(text) or None
    for m in _resolvers(list_obj, movie):
        try:
            out = m.ResolveDataStoreMarkup(text)
        except Exception:
            continue
        if out and not str(out).startswith("$"):
            return clean(out) or None
    return None


def resolve(caption: str, list_obj: Any = None) -> str:
    """Turn '$WillowMenu.Foo.Bar' localisation keys into real text, then strip markup."""
    if caption.startswith("$"):
        for movie in _resolvers(list_obj):
            try:
                out = movie.ResolveDataStoreMarkup(caption)
            except Exception:
                continue
            if out and not str(out).startswith("$"):
                caption = str(out)
                break
    text = clean(caption)
    if text.startswith("$"):  # unresolved key: speak its last part, e.g. Play_NewGame -> Play New Game
        last = text.rsplit(".", 1)[-1].replace("_", " ")
        text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", last).strip()
    return text


def key_of(obj: Any) -> str:
    try:
        return obj._path_name()
    except Exception:
        return str(id(obj))


def positional(args: Any) -> list[Any]:
    """All parameters of a hooked call, in declaration order."""
    out = []
    try:
        for prop in args._type._properties():
            try:
                out.append(getattr(args, prop.Name))
            except Exception:
                out.append(None)
    except Exception:
        pass
    return out


def arg(args: Any, names: tuple[str, ...], index: int) -> Any:
    for n in names:
        try:
            return getattr(args, n)
        except Exception:
            continue
    vals = positional(args)
    return vals[index] if index < len(vals) else None


def pretty_name(raw: str) -> str:
    raw = re.sub(r"PlayerClass$", "", raw).replace("_", " ")
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", raw).strip() or "Unknown character"


def strings(args: Any) -> list[str]:
    return [clean(v) for v in positional(args) if isinstance(v, str) and clean(v)]


# ------------------------------------------------------------------------------ localisation files
# Many game dialogs get their text via WillowGFxDialogBox:AutoLocEnable(File, Section), which
# looks up Caption/Prompt in WillowGame\Localization\INT\<File>.int. We read the same file.

_LOC_CACHE: dict[str, dict[str, dict[str, str]]] = {}


def _loc_dir() -> str:
    import os

    from .speech import MOD_DIR

    game_root = os.path.dirname(os.path.dirname(MOD_DIR))  # sdk_mods\bl2_access -> game folder
    return os.path.join(game_root, "WillowGame", "Localization", "INT")


def parse_int(data: bytes) -> dict[str, dict[str, str]]:
    """Parse an Unreal .int localisation file (usually UTF-16 with BOM)."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = data.decode("utf-16", "replace")
    else:
        text = data.decode("utf-8-sig", "replace")
    sections: dict[str, dict[str, str]] = {}
    cur: dict[str, str] | None = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            cur = sections.setdefault(line[1:-1].lower(), {})
        elif cur is not None and "=" in line:
            k, v = line.split("=", 1)
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] == '"':
                v = v[1:-1]
            cur[k.strip().lower()] = v.replace("\\n", " ")
    return sections


def loc_section(file: str, section: str) -> dict[str, str]:
    import os

    key = file.lower()
    if key not in _LOC_CACHE:
        try:
            with open(os.path.join(_loc_dir(), f"{file}.int"), "rb") as f:
                _LOC_CACHE[key] = parse_int(f.read())
        except OSError:
            _LOC_CACHE[key] = {}
    return _LOC_CACHE[key].get(section.lower(), {})


def loc_dialog_text(file: str, section: str) -> str:
    entry = loc_section(file, section)
    parts = [clean(entry.get(k, "")) for k in ("caption", "prompt")]
    # Placeholders such as %CHARACTER% are filled in by the game; just drop the markers.
    return ". ".join(re.sub(r"%([A-Z_]+)%", r"\1", p).strip() for p in parts if p)


def hook_path(class_name: str, func: str) -> str | None:
    """'Package.OwningClass:Func' if the class (or a parent) really has that function."""
    try:
        cls = unrealsdk.find_class(class_name)
        f = cls._find(func)
        owner = f.Outer
        return f"{owner.Outer.Name}.{owner.Name}:{func}"
    except Exception:
        return None


# ------------------------------------------------------------------------------ lists

@dataclass
class Item:
    event_id: int
    caption: str
    kind: str = "item"            # item | spinner | slider
    choices: list[str] = field(default_factory=list)
    value: float = 0
    vmin: float = 0
    vmax: float = 0
    disabled: bool = False

    def value_text(self) -> str:
        if self.kind == "spinner" and self.choices:
            i = int(self.value)
            return self.choices[i] if 0 <= i < len(self.choices) else ""
        if self.kind == "slider":
            v = int(self.value) if float(self.value).is_integer() else round(self.value, 2)
            return f"{v}, range {int(self.vmin)} to {int(self.vmax)}"
        return ""

    def speak_text(self, index: int | None = None, total: int | None = None) -> str:
        parts = [self.caption or "blank"]
        if self.kind == "spinner":
            parts.append(f"{self.value_text()}, choice")
        elif self.kind == "slider":
            parts.append(f"slider {self.value_text()}")
        if self.disabled:
            parts.append("unavailable")
        if index is not None and total:
            parts.append(f"{index + 1} of {total}")
        return ", ".join(p for p in parts if p)


@dataclass
class ListState:
    ptr: Any  # WeakPointer to the WillowScrollingList: the game deletes lists when menus close
    items: list[Item] = field(default_factory=list)
    last_add: float = 0.0
    announced: bool = False
    last_index: int | None = None

    @property
    def obj(self) -> Any:
        """The live list, or None once the game has deleted it."""
        from .game import deref

        return deref(self.ptr)

    def by_event(self, event_id: int) -> tuple[int, Item] | None:
        for i, it in enumerate(self.items):
            if it.event_id == event_id:
                return i, it
        return None


class MenuReader:
    REPOPULATE_GAP = 0.3   # an add this long after the previous one starts a fresh list

    def __init__(self) -> None:
        self.lists: dict[str, ListState] = {}
        self.descriptions: dict[tuple[str, int], str] = {}
        self.current: ListState | None = None
        self.read_descriptions = True
        self.enabled = True
        # selection-index auto-calibration
        self.sel_prop: dict[str, str] = {}
        self.pending_nav: tuple[float, dict[str, int], int] | None = None
        self.selection_events = False  # True once HandleSelectionChange has been seen
        self.char_index: int | None = None
        self.char_spoken: int | None = None
        self.char_names: dict[int, str] = {}
        self.char_first_spoken: str | None = None
        self.char_profiles: dict[int, str] = {}
        self.char_details: dict[str, str] = {}
        self._axis_state: dict[str, int] = {}
        # dialogs
        self.dialog_buttons: dict[str, list[tuple[str, str]]] = {}
        self.dialog_sel: dict[str, int] = {}
        self.last_dialog_text = ""
        self.registered: list[tuple[str, Type]] = []

    # ---------------------------------------------------------------- recording
    def _list(self, obj: Any, event_id: int | None = None) -> ListState:
        k = key_of(obj)
        st = self.lists.get(k)
        now = time.perf_counter()
        # A repeated EventID means the game is rebuilding the list (it does this several times
        # in a row on the main menu), so start fresh instead of appending duplicates.
        rebuilt = st is not None and event_id is not None and st.by_event(event_id) is not None
        if st is None or rebuilt or now - st.last_add > self.REPOPULATE_GAP:
            from .game import weak

            st = ListState(weak(obj))
            self.lists[k] = st
        st.last_add = now
        self.current = st
        return st

    def on_add_item(self, obj: Any, args: Any, *_: Any) -> None:
        eid = int(arg(args, ("EventID",), 0) or 0)
        st = self._list(obj, eid)
        cap = resolve(str(arg(args, ("Caption",), 1) or ""), obj)
        dis = bool(arg(args, ("bDisabled", "Disabled"), 2) or False)
        st.items.append(Item(eid, cap, disabled=dis))

    def on_add_spinner(self, obj: Any, args: Any, *_: Any) -> None:
        vals = positional(args)
        eid = int(arg(args, ("EventID",), 0) or 0)
        st = self._list(obj, eid)
        cap = resolve(str(arg(args, ("Caption",), 1) or ""), obj)
        idx = vals[3] if len(vals) > 3 and isinstance(vals[3], int) else 0
        choices_raw = vals[4] if len(vals) > 4 else []
        try:
            choices = [resolve(str(c), obj) for c in choices_raw]
        except Exception:
            choices = []
        st.items.append(Item(eid, cap, "spinner", choices, idx))

    def on_add_slider(self, obj: Any, args: Any, *_: Any) -> None:
        vals = positional(args)
        eid = int(arg(args, ("EventID",), 0) or 0)
        st = self._list(obj, eid)
        cap = resolve(str(arg(args, ("Caption",), 1) or ""), obj)
        nums = [v for v in vals[3:] if isinstance(v, (int, float)) and not isinstance(v, bool)]
        value, vmin, vmax = (nums + [0, 0, 0])[:3]
        st.items.append(Item(eid, cap, "slider", value=value, vmin=vmin, vmax=vmax))

    def on_add_description(self, obj: Any, args: Any, *_: Any) -> None:
        eid = int(arg(args, ("EventID",), 0) or 0)
        raw = str(arg(args, ("Description", "Desc"), 1) or "")
        # Help text is usually a '$Package.Section.Key' reference. Look it up for real; if the
        # lookup fails, store nothing rather than reading the internal key name aloud.
        movie = None
        try:
            movie = obj.MyOptionsMovie
        except Exception:
            pass
        text = resolve_strict(raw, movie=movie)
        if text:
            self.descriptions[(key_of(obj), eid)] = text

    # ---------------------------------------------------------------- focus
    def on_selection_change(self, obj: Any, args: Any, *_: Any) -> None:
        """WillowScrollingListDataProviderBase:HandleSelectionChange(EventID, TheList): the game's
        own "highlight moved" callback, used by every scrolling-list menu (main, pause, options).
        Once we've seen it, we trust it and stop estimating from key presses."""
        self.selection_events = True
        self.on_update_description(obj, args)

    def on_update_description(self, obj: Any, args: Any, *_: Any) -> None:
        """Options menus: the highlight moved to EventID."""
        eid = int(arg(args, ("EventID",), 0) or 0)
        lst = arg(args, ("TheList",), 1)
        st = self.lists.get(key_of(lst)) if lst is not None else self.current
        if st is None:
            return
        found = st.by_event(eid)
        if found is None:
            return
        i, item = found
        if st.last_index == i and st.announced:
            return
        st.last_index, st.announced = i, True
        self.current = st
        self.pending_nav = None  # this menu tells us directly; no need to calibrate
        text = item.speak_text(i, len(st.items))
        desc = self.descriptions.get((key_of(obj), eid))
        if desc and self.read_descriptions and desc != item.caption:
            text += f". {desc}"
        speech.say(text)

    def on_spinner_change(self, obj: Any, args: Any, *_: Any) -> None:
        eid = int(arg(args, ("EventID",), 0) or 0)
        idx = int(arg(args, ("NewChoiceIndex",), 1) or 0)
        item = self._find_item(eid)
        if item is not None:
            item.value = idx
            speech.say(item.value_text() or str(idx))

    def on_slider_change(self, obj: Any, args: Any, *_: Any) -> None:
        eid = int(arg(args, ("EventID",), 0) or 0)
        val = arg(args, ("NewSliderValue",), 1) or 0
        item = self._find_item(eid)
        if item is not None:
            item.value = val
        speech.say(str(int(val) if float(val).is_integer() else round(val, 2)))

    def _find_item(self, eid: int) -> Item | None:
        if self.current is not None:
            f = self.current.by_event(eid)
            if f:
                return f[1]
        for st in self.lists.values():
            f = st.by_event(eid)
            if f:
                return f[1]
        return None

    # ---------------------------------------------------------------- main/pause menu selection
    @staticmethod
    def _int_props(obj: Any) -> dict[str, int]:
        out: dict[str, int] = {}
        try:
            for prop in obj.Class._properties():
                if prop.Class.Name not in ("IntProperty", "ByteProperty"):
                    continue
                try:
                    v = getattr(obj, prop.Name)
                    if isinstance(v, int):
                        out[prop.Name] = v
                except Exception:
                    continue
        except Exception:
            pass
        return out

    def _live_list(self) -> ListState | None:
        st = self.current
        if st is None or not st.items:
            return None
        obj = st.obj
        if obj is None:  # the game deleted this list (menu closed / level loading)
            self.forget_dead_lists()
            return None
        try:
            if obj.MyOwnerMovie is None:
                return None
        except Exception:
            return None
        return st

    def forget_dead_lists(self) -> None:
        for k in [k for k, st in self.lists.items() if st.obj is None]:
            del self.lists[k]
        if self.current is not None and self.current.obj is None:
            self.current = None
        self.pending_nav = None

    UP_KEYS = {"XboxTypeS_DPad_Up", "Up", "W", "Gamepad_LeftStick_Up"}
    DOWN_KEYS = {"XboxTypeS_DPad_Down", "Down", "S", "Gamepad_LeftStick_Down"}

    def before_nav(self, key: str = "") -> None:
        """Called from the input hook *before* the game handles a menu navigation key."""
        st = self._live_list()
        if st is None or self.selection_events:  # the game tells us the highlight directly
            return
        step = -1 if key in self.UP_KEYS else 1 if key in self.DOWN_KEYS else 0
        self.pending_nav = (time.perf_counter(), self._int_props(st.obj), step)

    def _estimate(self, st: ListState, step: int) -> int | None:
        """Fallback when the game doesn't expose the highlight: follow up/down presses ourselves,
        wrapping at the ends and skipping greyed-out entries."""
        n = len(st.items)
        if step == 0 or n == 0:
            return None
        idx = st.last_index or 0
        for _ in range(n):
            idx = (idx + step) % n
            if not st.items[idx].disabled:
                return idx
        return None

    def tick(self) -> None:
        st = self._live_list()
        if st is None:
            return
        cls = ""
        try:
            cls = str(st.obj.Class.Name)
        except Exception:
            pass
        now = time.perf_counter()

        # Fresh list finished populating: announce the highlighted (or first) entry.
        if not st.announced and now - st.last_add > 0.15:
            st.announced = True
            idx = self._selected(st, cls)
            if idx is None:
                idx = 0
            st.last_index = idx
            if 0 <= idx < len(st.items):
                speech.say(st.items[idx].speak_text(idx, len(st.items)), interrupt=False)
            return

        if self.pending_nav is None or now - self.pending_nav[0] < 0.03:
            return
        _, before, step = self.pending_nav
        self.pending_nav = None
        after = self._int_props(st.obj)
        if cls not in self.sel_prop:
            n = len(st.items)
            moved = [k for k, v in after.items() if k in before and v != before[k] and 0 <= v < n + 2]
            # Prefer names that look like a selection index.
            moved.sort(key=lambda k: (not re.search(r"(?i)select|highlight|focus|current|index", k), k))
            if moved:
                self.sel_prop[cls] = moved[0]
                print(f"[Borderlands Access] menu selection property for {cls}: {moved[0]}")
        idx = self._selected(st, cls)
        if idx is None:
            idx = self._estimate(st, step)
        if idx is None or idx == st.last_index:
            return
        st.last_index = idx
        if 0 <= idx < len(st.items):
            speech.say(st.items[idx].speak_text(idx, len(st.items)))

    def _selected(self, st: ListState, cls: str) -> int | None:
        prop = self.sel_prop.get(cls)
        if not prop:
            return None
        try:
            return int(getattr(st.obj, prop))
        except Exception:
            return None

    def read_current(self) -> None:
        """Re-read the focused entry (bound to Repeat while in menus)."""
        st = self._live_list()
        if st is None or st.last_index is None or not (0 <= st.last_index < len(st.items)):
            speech.repeat()
            return
        speech.say(st.items[st.last_index].speak_text(st.last_index, len(st.items)))

    def on_button_input(self, obj: Any, args: Any, *_: Any) -> None:
        """GFxMoviePlayer:FilterButtonInput(ControllerId, ButtonName, InputEvent): every button a
        menu receives, including ones the menu's Flash code handles itself."""
        from mods_base import EInputEvent

        from . import trace
        from .controls import state

        from .controls import menus

        key = str(arg(args, ("ButtonName",), 1) or "")
        ev = arg(args, ("InputEvent",), 2)
        # The HUD is also a Flash movie, so only treat this as menu input while a menu is open.
        if ev == EInputEvent.IE_Pressed and key and menus.in_menu():
            trace.note(f"menu button {key} [{getattr(obj, 'Name', '?')}]")
            state.menu_key(key, "gfx")

    def on_axis_input(self, obj: Any, args: Any, *_: Any) -> None:
        """GFxMoviePlayer:FilterAxisInput: called every frame per stick axis. Only log stick
        pushes (for diagnostics); BL2's Flash menus turn them into moves themselves."""
        key = str(arg(args, ("Key",), 1) or "")
        try:
            delta = float(arg(args, ("Delta",), 2) or 0.0)
        except Exception:
            return
        zone = 1 if delta > 0.6 else -1 if delta < -0.6 else 0
        if self._axis_state.get(key, 0) == zone:
            return
        self._axis_state[key] = zone
        if zone:
            from . import trace

            trace.note(f"stick {key} {'+' if zone > 0 else '-'} [{getattr(obj, 'Name', '?')}]")

    def on_movie_input(self, obj: Any, args: Any, *_: Any) -> None:
        """FrontendGFxMovie:SharedHandleInputKey(ControllerId, ukey, uevent): menu keys arrive here
        even when the general UI input hook doesn't see them. The pause menu inherits it."""
        from mods_base import EInputEvent

        from . import trace
        from .controls import state

        key = str(arg(args, ("ukey", "Key"), 1) or "")
        ev = arg(args, ("uevent", "Event"), 2)
        trace.note(f"movie input {key} {ev}")
        if ev == EInputEvent.IE_Pressed and key:
            state.menu_key(key, "movie")

    # ---------------------------------------------------------------- character selection
    # CharacterSelectionReduxGFxMovie (found with the F2 trace): each move calls
    # SetSelectedCharacterIndex(PlayerIndex, NewSelectedIndex); ~0.5 s later the 3D preview loads
    # via UpdatePlayerStandIn(PlayerIndex, WPC, SaveGame=<PlayerSaveGame Profile_Siren>), whose
    # name tells us the class. We remember index -> character so repeat visits are instant.
    CLASS_PROFILES = {
        "soldier": "Axton, the Commando",
        "commando": "Axton, the Commando",
        "siren": "Maya, the Siren",
        "mercenary": "Salvador, the Gunzerker",
        "gunzerker": "Salvador, the Gunzerker",
        "assassin": "Zero, the Assassin",
        "mechromancer": "Gaige, the Mechromancer",
        "tulipplayerclass": "Gaige, the Mechromancer",
        "lilacplayerclass": "Krieg, the Psycho",
        "psycho": "Krieg, the Psycho",
    }

    def _character_name(self, profile: str) -> str:
        raw = re.sub(r"^Profile_", "", profile)
        return self.CLASS_PROFILES.get(raw.lower(), pretty_name(raw))

    # Words that identify each class's PlayerNameIdentifierDefinition object (the game data the
    # select screen shows: description, action skill, preferred weapons).
    CLASS_TOKENS = {
        "soldier": ("soldier", "commando"),
        "siren": ("siren",),
        "mercenary": ("mercenary", "gunzerker"),
        "assassin": ("assassin",),
        "mechromancer": ("mechromancer", "tulip"),
        "tulipplayerclass": ("mechromancer", "tulip"),
        "lilacplayerclass": ("lilac", "psycho"),
    }
    DETAIL_FIELDS = (
        ("LocalizedCharacterDescription", ""),
        ("LocalizedActionSkillDescription", "Action skill: "),
        ("LocalizedPreferredWeaponDescription", "Preferred weapons: "),
    )

    def _character_details(self, profile: str) -> str:
        """Description text for a class, read fresh from the loaded game definitions. Only the
        resulting strings are cached, never the objects (they can be unloaded)."""
        key = re.sub(r"^Profile_", "", profile).lower()
        if key in self.char_details:
            return self.char_details[key]
        tokens = self.CLASS_TOKENS.get(key, (key.replace("playerclass", ""),))
        text = ""
        try:
            defs = list(unrealsdk.find_all("PlayerNameIdentifierDefinition", exact=False))
        except Exception:
            defs = []
        for d in defs:
            try:
                path = d._path_name().lower()
            except Exception:
                continue
            if "default__" in path or not any(t in path for t in tokens):
                continue
            parts = []
            for field_name, label in self.DETAIL_FIELDS:
                try:
                    raw = getattr(d, field_name)
                    v = clean(raw).rstrip(". ")
                    from . import trace

                    trace.note(f"character text {key}.{field_name}: {str(raw)[:300]!r}")
                except Exception:
                    v = ""
                if v:
                    parts.append(label + v)
            if parts:
                text = ". ".join(parts)
                break
        from . import trace

        trace.note(f"character details for {key}: {'found' if text else 'none'}")
        self.char_details[key] = text
        return text

    def _speak_character(self, profile: str | None, name: str) -> None:
        speech.say(name)
        if profile and self.read_descriptions:
            details = self._character_details(profile)
            if details:
                speech.say(details, interrupt=False)  # moving again interrupts it

    def on_char_index(self, obj: Any, args: Any, *_: Any) -> None:
        if int(arg(args, ("PlayerIndex",), 0) or 0) != 0:
            return
        idx = int(arg(args, ("NewSelectedIndex",), 1) or 0)
        self.char_index = idx
        name = self.char_names.get(idx)
        if name:
            self._speak_character(self.char_profiles.get(idx), name)
            self.char_spoken = idx
        else:
            self.char_spoken = None  # wait for the preview to tell us who this is

    def on_char_standin(self, obj: Any, args: Any, *_: Any) -> None:
        if int(arg(args, ("PlayerIndex",), 0) or 0) != 0:
            return
        save = arg(args, ("SaveGame",), 2)
        try:
            profile = str(save.Name) if save is not None else ""
        except Exception:
            return
        if not profile:
            return
        name = self._character_name(profile)
        if self.char_index is None:  # screen just opened: the starting character, position unknown
            if name != self.char_first_spoken:
                self.char_first_spoken = name
                speech.say(name, interrupt=False)
                if self.read_descriptions:
                    details = self._character_details(profile)
                    if details:
                        speech.say(details, interrupt=False)
            return
        self.char_names[self.char_index] = name
        self.char_profiles[self.char_index] = profile
        if self.char_spoken != self.char_index:
            self.char_spoken = self.char_index
            self._speak_character(profile, name)

    # ---------------------------------------------------------------- dialogs
    def on_dialog_text(self, obj: Any, args: Any, *_: Any) -> None:
        from . import trace

        trace.note(f"dialog SetText {positional(args)!r}")
        texts = strings(args)
        self.dialog_buttons[key_of(obj)] = []
        self.dialog_sel.pop(key_of(obj), None)
        if texts:
            self.last_dialog_text = ". ".join(texts)

    def on_dialog_autoloc(self, obj: Any, args: Any, *_: Any) -> None:
        """WillowGFxDialogBox:AutoLocEnable(File, Section): the dialog's text lives in a game
        localisation file (e.g. WillowMenu.int [dlgGettingSavegameList])."""
        file = str(arg(args, ("File",), 0) or "")
        section = str(arg(args, ("Section",), 1) or "")
        from . import trace

        trace.note(f"dialog AutoLocEnable {file} [{section}]")
        text = loc_dialog_text(file, section) if file and section else ""
        if text:
            self.dialog_buttons[key_of(obj)] = []
            self.dialog_sel.pop(key_of(obj), None)
            self.last_dialog_text = text

    def on_dialog_button(self, obj: Any, args: Any, *_: Any) -> None:
        vals = [clean(v) for v in positional(args) if isinstance(v, str)]
        caption = vals[1] if len(vals) > 1 else (vals[0] if vals else "")
        tip = vals[2] if len(vals) > 2 else ""
        self.dialog_buttons.setdefault(key_of(obj), []).append((caption, tip))

    def on_dialog_layout(self, obj: Any, *_: Any) -> None:
        audio.play("ui", snd.ui("open", features.s.volume))
        msg = self.last_dialog_text or "Dialog"
        btn = self._dialog_button_text(obj)
        speech.say(f"{msg}. {btn}" if btn else msg)
        self.last_dialog_text = ""

    def on_dialog_input(self, obj: Any, *_: Any) -> None:
        k = key_of(obj)
        try:
            sel = int(obj.CurrentSelection)
        except Exception:
            return
        if self.dialog_sel.get(k) == sel:
            return
        self.dialog_sel[k] = sel
        btn = self._dialog_button_text(obj)
        if btn:
            speech.say(btn)

    def _dialog_button_text(self, obj: Any) -> str:
        buttons = self.dialog_buttons.get(key_of(obj)) or []
        try:
            sel = int(obj.CurrentSelection)
        except Exception:
            sel = 0
        self.dialog_sel[key_of(obj)] = sel
        if not (0 <= sel < len(buttons)):
            return ""
        cap, tip = buttons[sel]
        out = f"{cap} button, {sel + 1} of {len(buttons)}"
        return f"{out}. {tip}" if tip and tip != cap else out

    def on_training(self, obj: Any, args: Any, *_: Any) -> None:
        texts = strings(args)
        if not texts:
            return
        # ShowTrainingDialog(message, title, ...) -> say the title first.
        msg, title = texts[0], (texts[1] if len(texts) > 1 else "")
        audio.play("ui", snd.ui("open", features.s.volume))
        speech.say(f"{title}. {msg}" if title else msg)

    # ---------------------------------------------------------------- registration
    def register(self) -> None:
        self.unregister()

        def safe(cb):
            def wrapper(*a: Any) -> None:
                if not self.enabled:
                    return
                try:
                    cb(*a)
                except Exception as e:  # noqa: BLE001
                    print(f"[Borderlands Access] menu reader {cb.__name__}: {e}")
            return wrapper

        plan = [
            ("WillowScrollingList", "AddListItem", Type.POST, self.on_add_item),
            ("WillowScrollingList", "AddSpinnerListItem", Type.POST, self.on_add_spinner),
            ("WillowScrollingList", "AddSliderListItem", Type.POST, self.on_add_slider),
            ("WillowScrollingListDataProviderOptionsBase", "AddDescription", Type.POST, self.on_add_description),
            ("WillowScrollingListDataProviderOptionsBase", "UpdateDescriptionText", Type.PRE, self.on_update_description),
            ("WillowScrollingListDataProviderKeyboardMouseOptions", "UpdateDescriptionText", Type.PRE, self.on_update_description),
            ("WillowScrollingListDataProviderOptionsBase", "HandleSpinnerChange", Type.PRE, self.on_spinner_change),
            ("WillowScrollingListDataProviderOptionsBase", "HandleSliderChange", Type.PRE, self.on_slider_change),
            ("WillowGFxDialogBox", "SetText", Type.POST, self.on_dialog_text),
            ("WillowGFxDialogBox", "AutoLocEnable", Type.POST, self.on_dialog_autoloc),
            ("WillowGFxDialogBox", "AppendButton", Type.POST, self.on_dialog_button),
            ("WillowGFxDialogBox", "ApplyLayout", Type.POST, self.on_dialog_layout),
            ("WillowGFxDialogBox", "HandleInputKey", Type.POST, self.on_dialog_input),
            ("WillowGFxUIManager", "ShowTrainingDialog", Type.POST, self.on_training),
            ("FrontendGFxMovie", "SharedHandleInputKey", Type.PRE, self.on_movie_input),
            ("WillowScrollingListDataProviderBase", "HandleSelectionChange", Type.PRE, self.on_selection_change),
            ("GFxMoviePlayer", "FilterButtonInput", Type.PRE, self.on_button_input),
            ("WillowGFxMovie3D", "FilterButtonInput", Type.PRE, self.on_button_input),
            ("GFxMoviePlayer", "FilterAxisInput", Type.PRE, self.on_axis_input),
            ("CharacterSelectionReduxGFxMovie", "SetSelectedCharacterIndex", Type.PRE, self.on_char_index),
            ("CharacterSelectionReduxGFxMovie", "UpdatePlayerStandIn", Type.PRE, self.on_char_standin),
        ]
        seen = set()
        for cls, fn, kind, cb in plan:
            path = hook_path(cls, fn)
            if path is None:
                print(f"[Borderlands Access] menu reader: {cls}.{fn} not found, skipped")
                continue
            if (path, kind) in seen:
                continue
            seen.add((path, kind))
            try:
                uhooks.add_hook(path, kind, _ID, safe(cb))
                self.registered.append((path, kind))
                from . import trace

                trace.note(f"menu reader hooked {path}")
            except Exception as e:  # noqa: BLE001
                print(f"[Borderlands Access] menu reader: could not hook {path}: {e}")

    def unregister(self) -> None:
        for path, kind in self.registered:
            try:
                uhooks.remove_hook(path, kind, _ID)
            except Exception:
                pass
        self.registered.clear()


reader = MenuReader()
