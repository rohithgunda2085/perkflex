"""Reads the traveller's free-text message for plain preferences. Rules only: no model, no network.

An intent can only NARROW the advice: it can drop a release the traveller does not want, change which offer is
preferred, or ask for an offer that already exists. It never creates an offer, raises a price or changes a number.
"""

import re
from dataclasses import dataclass


def _has(text: str, *patterns: str) -> bool:
    return any(re.search(p, text) for p in patterns)


@dataclass(frozen=True)
class Intent:
    keep_bag: bool = False  # does not want to release a bag
    keep_seat: bool = False  # does not want to give up the seat
    prefers_bag_release: bool = False  # travels light
    wants_extra_seat: bool = False
    wants_front_seat: bool = False
    wants_boarding: bool = False
    wants_drink: bool = False
    wants_standby: bool = False
    heavy_bag: bool = False
    saving: bool = False  # would rather keep points than spend them
    wants_points: bool = False  # asks for points or how to earn them ("add me 15000 points")
    points_target: int = 0  # the number they named, if any

    @property
    def any(self) -> bool:
        return any(getattr(self, f) for f in self.__dataclass_fields__)


_NUMBER = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(k\b)?")


def points_asked_for(text: str) -> int:
    """The points amount a message names ("15000", "15,000", "15k"), or 0. Used only to describe how far away it is."""
    for m in _NUMBER.finditer(text):
        raw = m.group(1).replace(",", "")
        try:
            value = float(raw) * (1000 if m.group(2) else 1)
        except ValueError:
            continue
        if value >= 1:
            return int(value)
    return 0


def asks_for_points(text: str) -> bool:
    """True for "add me 15000 points", "give me free points", "how can I earn more points". Plain patterns only."""
    return _has(
        text,
        r"\b(?:add|give|credit|send|top ?up|grant|get)\b[^.?!]{0,40}\bpoints?\b",
        r"\bhow (?:do|can|could|to|would) (?:i |we )?(?:earn|get|collect|gain|win)\b[^.?!]{0,40}\bpoints?\b",
        r"\b(?:more|free|extra|bonus) points\b",
        r"\bearn\b[^.?!]{0,30}\bpoints?\b",
    )


def parse_intent(message: str) -> Intent:
    t = (message or "").lower()
    if not t.strip():
        return Intent()
    light = _has(t, r"backpack", r"carry[- ]?on only", r"\bno (?:bags?|luggage|checked)", r"travel(?:ling)? light", r"without (?:a )?bag")
    keep_bag = _has(t, r"(?:keep|need|using|bringing|checking)\W+(?:my |a |the |both |two |all )?(?:checked )?(?:bags?|luggage|suitcase)", r"don'?t (?:want to )?(?:release|give up) (?:my |the )?bag")
    tall = _has(t, r"\btall\b", r"leg ?room", r"extra legroom", r"stretch")
    keep_seat = _has(t, r"(?:keep|need|like|love) (?:my |the )?seat", r"don'?t (?:want to )?(?:change|swap|give up|release) (?:my |the )?seat") or tall
    wants_points = asks_for_points(t)
    return Intent(
        wants_points=wants_points,
        points_target=points_asked_for(t) if wants_points else 0,
        keep_bag=keep_bag and not light,
        keep_seat=keep_seat,
        prefers_bag_release=light,
        wants_extra_seat=tall,
        wants_front_seat=_has(t, r"front of the (?:plane|cabin)", r"near the front", r"front seat", r"\bfront row"),
        wants_boarding=_has(t, r"board(?:ing)? early", r"early boarding", r"priority boarding", r"first on", r"overhead"),
        wants_drink=_has(t, r"\bdrink", r"\bcocktail", r"\bbeer\b", r"\bwine\b"),
        wants_standby=_has(t, r"standby", r"earlier flight", r"change (?:my )?flight", r"flexib", r"may need to change"),
        heavy_bag=_has(t, r"overweight", r"\bheavy\b", r"\b(?:over|more than) 50 ?(?:lb|pounds)"),
        saving=_has(t, r"\bsav(?:e|ing) (?:my )?points", r"don'?t (?:want to )?spend", r"keep (?:my )?points", r"not spend"),
    )
