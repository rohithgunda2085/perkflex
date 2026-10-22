"""The frontend's display constants must match the Python rules they are generated from."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "generate_frontend_data.py"


def _generator():
    spec = importlib.util.spec_from_file_location("generate_frontend_data", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frontend_constants_are_up_to_date():
    generator = _generator()
    assert generator.OUTPUT.read_text(encoding="utf-8") == generator.render(), (
        "frontend/src/rules/data.ts is out of date. Run: "
        "cd backend && ../../.venv/bin/python scripts/generate_frontend_data.py"
    )


def test_the_generated_constants_cover_what_the_screens_use():
    text = _generator().render()
    for name in ("FARES", "FLIGHTS", "AIRPORTS", "RULES", "SEAT_NAMES", "SEAT_ORDER", "fareById", "flightById", "money", "fmt"):
        assert f"export const {name}" in text
    assert '"Choice Extra"' in text and '"DAL"' in text and '"bag1": 3000' in text
