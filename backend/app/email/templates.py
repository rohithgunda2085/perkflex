"""The words of each email. Plain text and a small HTML copy. No model is involved and nothing is invented here:
the body is the notice the app already showed the traveller."""

import html

SUBJECTS = {
    "CONFIRM": "Confirm your email for PerkFlex",
    "BOOKED": "PerkFlex: your trip is booked",
    "RELEASE": "PerkFlex: points pending from your release",
    "PURCHASE": "PerkFlex: your purchase is confirmed",
    "COMPLETE": "PerkFlex: your trip is complete",
}
FOOTER = (
    "PerkFlex is a concept demo with synthetic data. It is not affiliated with Southwest Airlines.\n"
    "To stop these emails, turn off Email notifications in your PerkFlex wallet."
)
EMAIL_SHAPE = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


def subject_for(kind: str) -> str:
    return SUBJECTS[kind]


def body_text(kind: str, notice: str = "", link: str = "") -> str:
    if kind == "CONFIRM":
        core = f"Please confirm this address so PerkFlex can email you about your trips.\n\nConfirm: {link}\n\nIf you did not ask for this, ignore this email and nothing will be sent."
    else:
        core = notice.strip() or "Your PerkFlex activity was updated."
    return f"{core}\n\n--\n{FOOTER}\n"


def body_html(text: str) -> str:
    paragraphs = "".join(f"<p>{html.escape(p).replace(chr(10), '<br>')}</p>" for p in text.split("\n\n") if p.strip())
    return f"<html><body style=\"font-family:Arial,sans-serif;line-height:1.5\">{paragraphs}</body></html>"
