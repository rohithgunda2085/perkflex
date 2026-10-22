"""Translating between database values (BASIC, EXTRA_LEGROOM, CHECKED_IN...) and the app's vocabulary."""

FARE_FROM_DB = {"BASIC": "basic", "CHOICE": "choice", "CHOICE_PREFERRED": "preferred", "CHOICE_EXTRA": "extra"}
FARE_TO_DB = {v: k for k, v in FARE_FROM_DB.items()}
SEAT_FROM_DB = {"STANDARD": "standard", "PREFERRED": "preferred", "EXTRA_LEGROOM": "extra"}
SEAT_TO_DB = {v: k for k, v in SEAT_FROM_DB.items()}
SEAT_BENEFIT = {"preferred": "SEAT_PREF", "extra": "SEAT_XL"}  # no benefit row for Standard
TIER_FROM_DB = {"NONE": "Member", "SILVER": "Silver", "GOLD": "Gold", "PLATINUM": "Platinum"}
CARD_FROM_DB = {"NONE": "None", "PLUS": "Plus", "PREMIER": "Premier", "PRIORITY": "Priority"}
STATUS_FROM_DB = {"BOOKED": "booked", "CHECKED_IN": "checked-in", "FLOWN": "flown"}
PREF_SEAT_FROM_DB = {"ANY": "any", "FRONT": "front", "EXTRA": "extra"}
PREF_SEAT_TO_DB = {v: k for k, v in PREF_SEAT_FROM_DB.items()}

_FIXED_COLORS = ["blue", "peach", "purple", "mint", "pink"]


def initials(name: str) -> str:
    """First letter of the first and last words: 'Dee Ann Carlin' -> 'DC'; a single name uses two letters."""
    words = name.split()
    if len(words) >= 2:
        return (words[0][0] + words[-1][0]).upper()
    return name[:2].upper()


def avatar_color(login_id: str, tier: str) -> str:
    if tier == "Gold":
        return "gold"
    if tier in ("Silver", "Platinum"):
        return "silver"
    return _FIXED_COLORS[sum(map(ord, login_id)) % len(_FIXED_COLORS)]


def flight_code(flight_number: str) -> str:
    """The id the frontend and the pricing rules use for a flight: '2418' -> 'WN2418'."""
    return f"WN{flight_number}"


def flight_number(flight_code_: str) -> str:
    return flight_code_.removeprefix("WN")
