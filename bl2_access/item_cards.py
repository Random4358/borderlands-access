"""Reads the item card: the panel the game shows for the highlighted item in the inventory,
at vendors, the bank and so on.

From the in-game trace (inventory screen), every highlight move runs:
  BaseTopLevelPanelGFxObject.OnItemSelected(Panel, Thing)      Thing = highlighted item, or None
  ItemCardGFxObject.SetItemCardEx(WPC, InventoryItem, CompareAgainstInventoryItem, CurrencyType, ...)
      SetTopStat(StatIndex, LabelText, ValueText, CompareArrow, ...)    once per stat line
      __SetTitle(Manufacturer, Title, Rarity (colour), TypeIcon, ElementalIcon, bIsReadied)
      SetFunStats(FunStatsText)                                         special effects text
      SetValue(Amount)
      SetLevelRequirement(bHasRequirement, bMetRequirement, bAlreadyUsed, RequirementText)
SetItemCardEx makes all those calls itself, so when it returns (POST hook) the card is complete
and is read straight away; nothing waits for the next frame.

CompareArrow, worked out from two guns' real stats: 0 no comparison, 1 better, 2 worse, 3 same.
"""

from __future__ import annotations

import re
import time
from typing import Any

from . import game

CARD = "WillowGame.ItemCardGFxObject"
ARROWS = {1: "better", 2: "worse", 3: "same"}
TYPE_WORDS = {
    "pistol": "pistol", "smg": "SMG", "sniper": "sniper rifle", "shotgun": "shotgun",
    "assault": "assault rifle", "assaultrifle": "assault rifle", "ar": "assault rifle",
    "launcher": "rocket launcher", "rocketlauncher": "rocket launcher", "rocket": "rocket launcher",
    "shield": "shield", "grenade": "grenade mod", "grenademod": "grenade mod", "classmod": "class mod",
    "relic": "relic", "artifact": "relic", "com": "class mod",
}
CURRENCY = {0: "dollars", 1: "eridium", 2: "seraph crystals", 3: "torgue tokens"}


def _clean(s: Any) -> str:
    t = re.sub(r"<[^>]+>", " ", str(s or ""))
    t = re.sub(r"\[/?-?[a-z_]+\]", "", t)
    t = t.replace("•", " ").replace("\\n", " ")
    t = re.sub(r"\s+", " ", t).strip()
    return re.sub(r"\s+([.,;:!?])", r"\1", t)


def rarity_word(colour: Any) -> str:
    """The game colours item names by rarity; the colour arrives as 0xRRGGBB."""
    try:
        c = int(colour)
    except Exception:
        return ""
    r, g, b = (c >> 16) & 255, (c >> 8) & 255, c & 255
    if min(r, g, b) > 200:
        return "common"
    if g > 150 and r < 120 and b < 120:
        return "uncommon"
    if b > 150 and r < 120 and g < 170:
        return "rare"
    if r > 120 and b > 150 and g < 120:
        return "epic"
    if r > 200 and 80 < g < 200 and b < 80:
        return "legendary"
    if b > 150 and g > 150 and r < 120:
        return "pearlescent"
    if r > 200 and g < 120 and b > 150:
        return "e-tech"
    return ""


def type_word(icon: Any) -> str:
    key = re.sub(r"[^a-z]", "", str(icon or "").lower())
    if not key or key == "none":
        return ""
    return TYPE_WORDS.get(key, key)


def item_level(item: Any) -> int | None:
    for getter in (lambda i: i.GetExpLevel(), lambda i: i.DefinitionData.ManufacturerGradeIndex,
                   lambda i: i.ExpLevel):
        try:
            v = int(getter(item))
            if v > 0:
                return v
        except Exception:
            continue
    return None


def _ident(obj: Any) -> str:
    if obj is None:
        return ""
    try:
        return obj._path_name()
    except Exception:
        return str(id(obj))


def _name(obj: Any) -> str:
    for g in ("GetShortHumanReadableName", "GetHumanReadableName"):
        try:
            v = _clean(getattr(obj, g)())
            if v:
                return v
        except Exception:
            continue
    return ""


class CardReader:
    def __init__(self) -> None:
        self.cards: dict[str, dict] = {}            # card object name -> card being built
        self.selected: tuple[float, str] | None = None  # (when, item identity or "" for empty)
        self.last_text = ""
        self.last_time = 0.0
        self.spoke_at = 0.0
        self.say = None  # set by the status reader: say(text)

    # -------------------------------------------------------------- hook callbacks
    def on_selected(self, thing: Any) -> None:
        self.selected = (time.perf_counter(), _ident(thing))

    def on_card_start(self, card: Any, args: Any) -> None:
        item = getattr(args, "InventoryItem", None)
        compare = getattr(args, "CompareAgainstInventoryItem", None)
        try:
            currency = int(getattr(args, "CurrencyType", 0))
        except Exception:
            currency = 0
        self.cards[str(card.Name)] = {
            "ident": _ident(item), "fallback": _name(item) if item is not None else "",
            "level": item_level(item) if item is not None else None,
            "compare": _name(compare) if compare is not None else "",
            "currency": currency, "stats": {}, "title": None, "fun": "", "value": None, "req": "",
        }

    def _card(self, card: Any) -> dict | None:
        try:
            return self.cards.get(str(card.Name))
        except Exception:
            return None

    def on_title(self, card: Any, args: Any) -> None:
        rec = self._card(card)
        if rec is None:
            return
        rarity = getattr(args, "Rarity", None)
        old = rec["title"] or {}
        rec["title"] = {
            "name": _clean(getattr(args, "Title", "")) or old.get("name", ""),
            "maker": _clean(getattr(args, "Manufacturer", "")).capitalize() or old.get("maker", ""),
            "type": type_word(getattr(args, "TypeIcon", "")) or old.get("type", ""),
            "element": "" if str(getattr(args, "ElementalIcon", "None")).lower() in ("", "none")
                       else _clean(getattr(args, "ElementalIcon", "")).lower(),
            "rarity": rarity_word(rarity) or old.get("rarity", ""),
            "readied": bool(getattr(args, "bIsReadied", False)),
        }

    def on_stat(self, card: Any, args: Any) -> None:
        rec = self._card(card)
        if rec is None:
            return
        label = _clean(getattr(args, "LabelText", ""))
        value = _clean(getattr(args, "ValueText", ""))
        if not label and not value:
            return
        try:
            arrow = ARROWS.get(int(getattr(args, "CompareArrow", 0)), "")
        except Exception:
            arrow = ""
        aux = _clean(getattr(args, "AuxText", ""))
        try:
            idx = int(getattr(args, "StatIndex", len(rec["stats"])))
        except Exception:
            idx = len(rec["stats"])
        rec["stats"][idx] = " ".join(p for p in (label, value, aux, arrow) if p)

    def on_fun(self, card: Any, args: Any) -> None:
        rec = self._card(card)
        if rec is not None:
            rec["fun"] = _clean(getattr(args, "FunStatsText", ""))

    def on_value(self, card: Any, args: Any) -> None:
        rec = self._card(card)
        if rec is None:
            return
        try:
            rec["value"] = int(getattr(args, "Amount"))
        except Exception:
            pass

    def on_requirement(self, card: Any, args: Any) -> None:
        rec = self._card(card)
        if rec is None:
            return
        text = _clean(getattr(args, "RequirementText", ""))
        if bool(getattr(args, "bHasRequirement", False)) and not bool(getattr(args, "bMetRequirement", True)):
            text = (text + ". You can't use this yet") if text else "You can't use this yet"
        rec["req"] = text

    def on_card_done(self, card: Any) -> None:
        try:
            rec = self.cards.pop(str(card.Name), None)
        except Exception:
            rec = None
        if rec is None:
            return
        now = time.perf_counter()
        recent = self.selected is not None and now - self.selected[0] < 1.0
        if recent:
            want = self.selected[1]
            if want != rec["ident"]:
                return            # this card shows something else (e.g. the comparison card)
            text = self.compose(rec) if want else "Empty slot"
        else:
            if not rec["ident"]:
                return            # no selection info (vendors...): only read cards with an item
            text = self.compose(rec)
        if not text:
            return
        if text == self.last_text and now - self.last_time < 1.0:
            return                # the game often builds the same card twice in a row
        self.last_text, self.last_time, self.spoke_at = text, now, now
        from . import trace

        trace.note(f"item card: {text[:120]}")
        if self.say is not None:
            self.say(text)

    # -------------------------------------------------------------- text
    @staticmethod
    def compose(rec: dict) -> str:
        t = rec["title"] or {}
        name = t.get("name") or rec["fallback"] or "Item"
        kind = " ".join(p for p in (t.get("rarity", ""), t.get("element", ""), t.get("maker", ""),
                                    t.get("type", "")) if p)
        head = [name]
        if kind:
            head.append(kind[0].upper() + kind[1:])
        if rec["level"]:
            head.append(f"level {rec['level']}")
        if t.get("readied"):
            head.append("equipped")
        parts = [", ".join(head)]
        stats = [rec["stats"][k] for k in sorted(rec["stats"])]
        if stats:
            lead = f"Compared with {rec['compare']}: " if rec["compare"] else ""
            parts.append(lead + ", ".join(stats))
        if rec["fun"]:
            parts.append(rec["fun"].rstrip(". "))
        if rec["value"] is not None and rec["value"] > 0:
            parts.append(f"Worth {rec['value']} {CURRENCY.get(rec['currency'], 'dollars')}")
        if rec["req"]:
            parts.append(rec["req"].rstrip(". "))
        return ". ".join(p for p in parts if p) + "."

    # -------------------------------------------------------------- hooks
    def plan(self, Type: Any) -> list[tuple[str, Any, Any]]:
        def wrap(fn, with_args=True):
            def cb(obj: Any, args: Any, _r: Any, _f: Any) -> None:
                try:
                    fn(obj, args) if with_args else fn(obj)
                except Exception:
                    pass
            return cb

        def selected(obj: Any, args: Any) -> None:
            self.on_selected(getattr(args, "Thing", None))

        return [
            ("WillowGame.BaseTopLevelPanelGFxObject:OnItemSelected", Type.PRE, wrap(selected)),
            (f"{CARD}:SetItemCardEx", Type.PRE, wrap(self.on_card_start)),
            (f"{CARD}:__SetTitle", Type.PRE, wrap(self.on_title)),
            (f"{CARD}:SetTitle", Type.PRE, wrap(self.on_title)),
            (f"{CARD}:SetTopStat", Type.PRE, wrap(self.on_stat)),
            (f"{CARD}:SetFunStats", Type.PRE, wrap(self.on_fun)),
            (f"{CARD}:SetValue", Type.PRE, wrap(self.on_value)),
            (f"{CARD}:SetLevelRequirement", Type.PRE, wrap(self.on_requirement)),
            (f"{CARD}:SetItemCardEx", Type.POST, wrap(self.on_card_done, with_args=False)),
        ]


cards = CardReader()
