"""Reader for the status menu (Back button: missions, map, inventory, skills, badass rank) and the
other item screens (vendors, bank, trading).

* Tabs: each tab has its own input handler on StatusMenuExGFxMovie (HandleMapInputKey,
  HandleSkillsInputKey, ...), so the handler that fires tells us which tab you're on. The tab
  number from GetCurrentTab is matched to those names as you use the menu and remembered in
  tab_names.json, so later tab switches are announced straight away.
* Skills: SkillTreeGFxObject.GetSkillDescriptionForGrade runs each time the highlight moves,
  with the highlighted skill; its result is the description the game shows.
* Items: rather than relying on unconfirmed function names, every function of the inventory
  panel / item card classes that takes an inventory item is hooked. When the highlight moves,
  the item those functions receive is the one you're on. The item that's only being shown for
  comparison (your equipped one) is skipped when a different item arrives at the same time.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from . import game
from .speech import MOD_DIR, speech

_ID = "bl2_access_status"
STATUS_MOVIE = "StatusMenuExGFxMovie"
TAB_FILE = os.path.join(MOD_DIR, "tab_names.json")
TAB_WORDS = {
    "map": "Map", "skills": "Skills", "skill": "Skills", "inventory": "Inventory", "inv": "Inventory",
    "missions": "Mission log", "mission": "Mission log", "missionlog": "Mission log",
    "badass": "Badass rank", "badassrank": "Badass rank", "challenges": "Challenges",
    "challenge": "Challenges", "logs": "Echo logs", "log": "Echo logs", "echo": "Echo logs",
    "character": "Character",
}
ITEM_CLASSES = [  # the item card itself is read by item_cards.py
    "InventoryCardGFx", "StatusMenuInventoryPanelGFxObject",
    "StatusMenuEquippedPanelGFxObject", "InventoryListPanelGFxObject", "BaseInventoryPanelGFxObject",
    "InventoryDataProviderGFxObject", "InventoryDataProviderElement", "TwoPanelInterfaceGFxObject",
    "TwoPanelInterfaceGFxMovie", "VendingMachineExGFxMovie", "TradingPanelGFxObject",
    "TradingOffersPanelGFxObject", "BankGFxMovie", "ItemOfTheDayPanelGFxObject",
    "WillowInventoryGFxMovie", STATUS_MOVIE,
]
SKIP_PACKAGES = {"Core", "Engine", "GFxUI", "GearboxFramework"}
NOISY = ("Tick", "Render", "Draw", "Axis", "Timer")
ITEM_PARAM_CLASS = re.compile(r"(?i)inventory|weapon|item|equip|artifact|shield|grenade|classmod")
NOT_ITEM_CLASS = re.compile(r"(?i)definition|gfx|card|panel|provider|manager|pickup|balance|pool")
COMPARE_PARAM = re.compile(r"(?i)compar|equipped|current(ly)?equip|old")
CPF_PARM = 0x80
BATCH = 0.08  # seconds to collect the item calls that one highlight move triggers


def _clean(s: Any) -> str:
    t = re.sub(r"<[^>]+>", " ", str(s or ""))
    t = re.sub(r"\[/?-?[a-z_]+\]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return re.sub(r"\s+([.,;:!?])", r"\1", t)


def tab_label(word: str) -> str:
    key = word.lower()
    return TAB_WORDS.get(key) or game.pretty(word)


def is_equipped(item: Any) -> bool:
    for getter in ("IsEquipped", "IsReadied"):
        try:
            v = getattr(item, getter)
            if callable(v) and v():
                return True
        except Exception:
            continue
    try:
        if bool(item.bEquipped):
            return True
    except Exception:
        pass
    try:
        return int(item.QuickSelectSlot) > 0
    except Exception:
        return False


def describe_item(item: Any) -> str:
    from .panel_reader import describe

    text = describe(item)
    if not text:
        return ""
    if is_equipped(item) and "equipped" not in text:
        text += ", equipped"
    try:
        value = int(item.GetMonetaryValue())
        if value > 0:
            text += f", worth {value} dollars"
    except Exception:
        pass
    return text


def _ident(obj: Any) -> str:
    try:
        return obj._path_name()
    except Exception:
        return str(id(obj))


class StatusReader:
    def __init__(self) -> None:
        self.tab_word = ""          # handler name of the tab you're on, e.g. "Skills"
        self.tab_num: int | None = None
        self.tab_names: dict[str, str] = {}
        self.pending_items: list[tuple[str, str, Any]] = []  # (path, param, item)
        self.batch_start = 0.0
        self.last_item = ""
        self.last_skill = ""
        self.last_skill_time = 0.0
        self.last_spoke = 0.0
        self.item_paths_seen: set[str] = set()
        self.tick_noted = False
        self._hooked: list[tuple[str, Any]] = []
        self._item_params: dict[str, list[str]] = {}
        self._load_tabs()

    # ------------------------------------------------------------ tabs
    def _load_tabs(self) -> None:
        try:
            with open(TAB_FILE, encoding="utf-8") as f:
                self.tab_names = {str(k): str(v) for k, v in json.load(f).items()}
        except Exception:
            self.tab_names = {}

    def _save_tabs(self) -> None:
        try:
            with open(TAB_FILE, "w", encoding="utf-8") as f:
                json.dump(self.tab_names, f)
        except Exception:
            pass

    def _say(self, text: str, interrupt: bool = True) -> None:
        from .panel_reader import panels

        panels.last_spoken = text
        self.last_spoke = time.perf_counter()
        speech.say(text, interrupt)

    def on_tab_input(self, movie: Any, word: str) -> None:
        """A tab's own input handler ran: that's the tab you're on."""
        num = self._current_tab(movie)
        if num is not None and self.tab_names.get(str(num)) != word:
            self.tab_names[str(num)] = word
            self._save_tabs()
            from . import trace

            trace.note(f"status menu: tab {num} is {word}")
        if word != self.tab_word:
            self.tab_word = word
            self.last_item = ""
            self._say(tab_label(word))
        if num is not None:
            self.tab_num = num

    @staticmethod
    def _current_tab(movie: Any) -> int | None:
        try:
            return int(movie.GetCurrentTab())
        except Exception:
            return None

    def _poll_tab(self) -> None:
        from .panel_reader import panels

        movie = panels.focus_movie()
        if movie is None or game.class_name(movie) != STATUS_MOVIE:
            if self.tab_word or self.tab_num is not None:
                self.tab_word, self.tab_num, self.last_item = "", None, ""
            return
        num = self._current_tab(movie)
        if num is None or num == self.tab_num:
            return
        self.tab_num = num
        word = self.tab_names.get(str(num))
        if word and word != self.tab_word:
            self.tab_word = word
            self.last_item = ""
            self._say(tab_label(word))

    # ------------------------------------------------------------ skills
    def on_skill(self, skill: Any, desc: Any) -> None:
        if skill is None:
            return
        name = _clean(getattr(skill, "SkillName", "")) or game.pretty(str(getattr(skill, "Name", "Skill")))
        now = time.perf_counter()
        ident = _ident(skill)
        if ident == self.last_skill and now - self.last_skill_time < 0.4:
            return
        self.last_skill, self.last_skill_time = ident, now
        parts = [name]
        grade = self._skill_grade(skill)
        try:
            top = int(skill.MaxGrade)
        except Exception:
            top = 0
        if grade is not None and top > 0:
            parts.append(f"{grade} of {top} points")
        elif top > 0:
            parts.append(f"up to {top} points")
        text = _clean(desc) or _clean(getattr(skill, "SkillDescription", ""))
        spoken = ", ".join(parts) + (f". {text}" if text else "")
        self._say(spoken)

    @staticmethod
    def _skill_grade(skill: Any) -> int | None:
        pc = game.pc()
        if pc is None:
            return None
        for holder in ("PlayerSkillTree", "SkillTree"):
            try:
                tree = getattr(pc, holder)
                return int(tree.GetSkillGrade(skill))
            except Exception:
                continue
        return None

    # ------------------------------------------------------------ items
    def on_item_call(self, path: str, obj: Any, args: Any) -> None:
        from . import controls

        if not controls.menus.world_sounds_paused():  # only while a menu is up
            return
        now = time.perf_counter()
        for param in self._item_params.get(path, ()):
            try:
                v = getattr(args, param)
            except Exception:
                continue
            if v is None:
                continue
            from .panel_reader import kind_of

            if kind_of(v) != "item":
                continue
            if not self.pending_items:
                self.batch_start = now
            self.pending_items.append((path, param, v))

    def _flush_items(self) -> None:
        from .item_cards import cards

        batch, self.pending_items = self.pending_items, []
        if not batch or cards.spoke_at >= self.batch_start - 0.5:
            return  # the item card reader already read this highlight
        # The highlighted item, not the one shown alongside it for comparison.
        main = [b for b in batch if not COMPARE_PARAM.search(b[1])] or batch
        loose = [b for b in main if not is_equipped(b[2])]
        path, param, item = (loose or main)[0]
        ident = _ident(item)
        if ident == self.last_item:
            return
        text = describe_item(item)
        if not text:
            return
        self.last_item = ident
        key = f"{path}.{param}"
        if key not in self.item_paths_seen:
            self.item_paths_seen.add(key)
            from . import trace

            trace.note(f"item reader: {key} gave {game.class_name(item)}")
        self._say(text)

    # ------------------------------------------------------------ tick / hooks
    def tick(self) -> None:
        if not self.tick_noted and self.tab_word:
            self.tick_noted = True
            from . import trace

            trace.note("status reader: frame updates keep running while the status menu is open")
        self._poll_tab()
        if self.pending_items and time.perf_counter() - self.batch_start >= BATCH:
            self._flush_items()

    def register(self) -> int:
        import unrealsdk
        from unrealsdk import hooks as uhooks
        from unrealsdk.hooks import Type

        self.unregister()
        from .item_cards import cards

        cards.say = self._say
        plan: list[tuple[str, Any, Any]] = list(cards.plan(Type))
        taken = {path for path, _k, _cb in plan}

        # Tab handlers: HandleMapInputKey, HandleSkillsInputKey, ...
        for path, fname, _func in _functions(STATUS_MOVIE):
            m = re.fullmatch(r"Handle(\w+?)InputKey", fname)
            if m and m.group(1) not in ("", "Key"):
                word = m.group(1)

                def tab_cb(obj: Any, args: Any, _r: Any, _f: Any, word: str = word) -> None:
                    try:
                        self.on_tab_input(obj, word)
                    except Exception:
                        pass

                plan.append((path, Type.PRE, tab_cb))

        def skill_cb(obj: Any, args: Any, ret: Any, _f: Any) -> None:
            try:
                self.on_skill(getattr(args, "SkillDef", None), ret)
            except Exception:
                pass

        plan.append(("WillowGame.SkillTreeGFxObject:GetSkillDescriptionForGrade", Type.POST, skill_cb))

        seen: set[str] = set()
        for cls in ITEM_CLASSES:
            for path, fname, func in _functions(cls):
                if path in seen or path in taken or any(n in fname for n in NOISY):
                    continue
                seen.add(path)
                params = _item_params(func)
                if not params:
                    continue
                self._item_params[path] = params

                def item_cb(obj: Any, args: Any, _r: Any, _f: Any, path: str = path) -> None:
                    try:
                        self.on_item_call(path, obj, args)
                    except Exception:
                        pass

                plan.append((path, Type.PRE, item_cb))

        for path, kind, cb in plan:
            try:
                uhooks.add_hook(path, kind, _ID, cb)
                self._hooked.append((path, kind))
            except Exception:
                continue
        from . import trace

        missing = [p for p, _k, _cb in cards.plan(Type) if (p, _k) not in self._hooked]
        if missing:
            trace.note("item card reader could not hook: " + ", ".join(sorted(set(missing))))
        trace.note(f"status reader hooked {len(self._hooked)} functions "
                   f"({len(self._item_params)} take an item)")
        return len(self._hooked)

    def unregister(self) -> None:
        try:
            from unrealsdk import hooks as uhooks
        except Exception:
            return
        for path, kind in self._hooked:
            try:
                uhooks.remove_hook(path, kind, _ID)
            except Exception:
                pass
        self._hooked.clear()
        self._item_params.clear()


def _functions(class_name: str):
    """(hook path, function name, function object) for the class and its game-side parents."""
    import unrealsdk

    try:
        cls = unrealsdk.find_class(class_name)
    except Exception:
        return
    for struct in cls._superfields():
        try:
            pkg = str(struct.Outer.Name)
        except Exception:
            continue
        if pkg in SKIP_PACKAGES:
            continue
        child = struct.Children
        while child is not None:
            try:
                if child.Class.Name == "Function":
                    yield f"{pkg}.{struct.Name}:{child.Name}", str(child.Name), child
            except Exception:
                pass
            child = child.Next


def _item_params(func: Any) -> list[str]:
    """Names of the function's parameters that hold an inventory item."""
    out = []
    child = getattr(func, "Children", None)
    while child is not None:
        try:
            if child.Class.Name == "ObjectProperty":
                flags = getattr(child, "PropertyFlags", CPF_PARM)
                pclass = str(child.PropertyClass.Name)
                if (int(flags) & CPF_PARM and ITEM_PARAM_CLASS.search(pclass)
                        and not NOT_ITEM_CLASS.search(pclass)):
                    out.append(str(child.Name))
        except Exception:
            pass
        child = getattr(child, "Next", None)
    return out


status = StatusReader()
