from dataclasses import dataclass

import psycopg

from ..security.passwords import hash_password, verify_password


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    role: str  # PASSENGER | AIRLINE_ADMIN
    login_id: str
    passenger_id: str | None
    name: str

    @property
    def profile_id(self) -> str | None:
        """The traveller id the frontend uses; the login id for travellers, nothing for the airline admin."""
        return self.login_id if self.passenger_id else None

    def to_public(self) -> dict:
        return {
            "userId": self.user_id,
            "role": self.role,
            "profileId": self.profile_id,
            "passengerId": self.passenger_id,
            "name": self.name,
        }


# Checked against when the login id does not exist, so response time does not reveal valid usernames.
_DUMMY_HASH = hash_password("not-a-real-account")


def authenticate(conn: psycopg.Connection, login_id: str, password: str) -> AuthenticatedUser | None:
    """The user when the credentials are valid, otherwise None. Never says which part was wrong."""
    row = conn.execute(
        """SELECT u.user_id, u.user_role, u.login_id, u.passenger_id, u.password_hash, u.is_active_flag,
                  p.passenger_name
             FROM dim_user_account u LEFT JOIN dim_passenger p USING (passenger_id)
            WHERE u.login_id = %s""",
        (login_id.strip().lower(),),
    ).fetchone()
    ok = verify_password(password, row["password_hash"] if row else _DUMMY_HASH)
    if not row or not ok or not row["is_active_flag"]:
        return None
    conn.execute("UPDATE dim_user_account SET last_login_time_utc = now() WHERE user_id = %s", (row["user_id"],))
    return AuthenticatedUser(
        user_id=row["user_id"],
        role=row["user_role"],
        login_id=row["login_id"],
        passenger_id=row["passenger_id"],
        name=row["passenger_name"] or "Airline admin",
    )


def user_by_login(conn: psycopg.Connection, login_id: str) -> AuthenticatedUser | None:
    """Looks up an active user without a password (used by the demo traveller switch)."""
    row = conn.execute(
        """SELECT u.user_id, u.user_role, u.login_id, u.passenger_id, p.passenger_name
             FROM dim_user_account u LEFT JOIN dim_passenger p USING (passenger_id)
            WHERE u.login_id = %s AND u.is_active_flag""",
        (login_id.strip().lower(),),
    ).fetchone()
    if not row:
        return None
    return AuthenticatedUser(
        user_id=row["user_id"],
        role=row["user_role"],
        login_id=row["login_id"],
        passenger_id=row["passenger_id"],
        name=row["passenger_name"] or "Airline admin",
    )
