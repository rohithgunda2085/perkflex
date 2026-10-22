"""Password hashing with scrypt, in the same stored format the Node API used, so existing hashes keep working:

    scrypt$N$r$p$<salt base64>$<hash base64>
"""

import base64
import hashlib
import hmac
import secrets

N, R, P, KEY_LENGTH = 16384, 8, 1, 64
_MAXMEM = 128 * 1024 * 1024  # scrypt at N=16384, r=8 needs ~16 MB; allow headroom for larger stored parameters


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=KEY_LENGTH, maxmem=_MAXMEM)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    key = _derive(password, salt, N, R, P)
    return f"scrypt${N}${R}${P}${base64.b64encode(salt).decode()}${base64.b64encode(key).decode()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check. Returns False (never raises) for malformed or placeholder hashes."""
    parts = stored.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return False
    try:
        n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
        # Refuse absurd parameters from a corrupted row rather than burning CPU or memory on them.
        if not (2 <= n <= 2**20 and 1 <= r <= 32 and 1 <= p <= 16):
            return False
        expected = base64.b64decode(parts[5], validate=True)
        actual = _derive(password, base64.b64decode(parts[4], validate=True), n, r, p)
    except (ValueError, TypeError):
        return False
    return len(actual) == len(expected) and hmac.compare_digest(actual, expected)


_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no look-alike characters


def generate_demo_password() -> str:
    """A readable one-time demo password such as PF-7KQ3-M9XD."""

    def pick(count: int) -> str:
        return "".join(secrets.choice(_ALPHABET) for _ in range(count))

    return f"PF-{pick(4)}-{pick(4)}"
