"""Log in with an email and password; stay logged in with a session cookie.

Lives in the same SQLite file as the saved plans (reports/plans.db), because a user belongs to a client:

    clients  1 ──< users  1 ──< sessions
    users(id, client_id, email, password_hash, created)       email is unique, stored lower-cased
    sessions(token_hash, user_id, created, last_seen)          one row per logged-in browser

How the pieces stop the common attacks:
- Passwords are stored as a salted scrypt hash, never as text, so a leaked file gives no passwords.
- The session token is 32 random bytes. The database keeps only its SHA-256, so a leaked file gives
  no working tokens either. The browser keeps the token in an HttpOnly, SameSite=Lax cookie (set in api.py).
- A session ends after 30 minutes without use, or 8 hours after login, whichever comes first.
- Every login makes a new token; logout deletes it.
- Five wrong logins for one email in 5 minutes lock that email for the rest of the 5 minutes.
- A wrong email and a wrong password get the same answer, and take the same time.

There is no sign-up page: an admin adds users from the command line (see the end of this file).
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import secrets
import sqlite3
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,     -- scrypt$<salt hex>$<hash hex>
  created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,     -- SHA-256 of the cookie value; the value itself is never stored
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created REAL NOT NULL,           -- unix seconds
  last_seen REAL NOT NULL
);
"""
IDLE_S = 30 * 60
MAX_AGE_S = 8 * 60 * 60
MAX_FAILS, FAIL_WINDOW_S = 5, 5 * 60
MIN_PASSWORD = 8
# scrypt is slow and memory-hungry on purpose, so guessing passwords offline is expensive.
SCRYPT = dict(n=2**14, r=8, p=1, dklen=32)


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    return f"scrypt${salt.hex()}${hashlib.scrypt(password.encode(), salt=salt, **SCRYPT).hex()}"


def check_password(password: str, stored: str) -> bool:
    _, salt, _ = stored.split("$")
    return hmac.compare_digest(hash_password(password, bytes.fromhex(salt)), stored)  # constant-time compare


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# Checked against when the email is unknown, so that answer takes as long as a wrong password.
_DUMMY = hash_password("not a real password")


class TooManyTries(Exception):
    """Too many wrong logins for this email; try again after `wait` seconds."""
    def __init__(self, wait: int):
        self.wait = wait


class Auth:
    _lock = threading.Lock()

    def __init__(self, db_path: Path, now=time.time):
        self.db_path, self.now = db_path, now
        self._fails: dict[str, list[float]] = {}
        with self._connect() as db:
            db.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    def add_user(self, email: str, password: str, client_id: int) -> int:
        if len(password) < MIN_PASSWORD:
            raise ValueError(f"the password needs at least {MIN_PASSWORD} characters")
        with self._connect() as db:
            return db.execute("INSERT INTO users (client_id, email, password_hash, created) VALUES (?, ?, ?, ?)",
                              (client_id, email.strip().lower(), hash_password(password),
                               datetime.now(timezone.utc).isoformat(timespec="seconds"))).lastrowid

    def login(self, email: str, password: str) -> str | None:
        """A new session token, or None for a wrong email or password. Raises TooManyTries."""
        email, now = email.strip().lower(), self.now()
        with self._lock:
            fails = [t for t in self._fails.get(email, []) if now - t < FAIL_WINDOW_S]
            self._fails[email] = fails
            if len(fails) >= MAX_FAILS:
                raise TooManyTries(int(FAIL_WINDOW_S - (now - fails[0])) + 1)
        with self._connect() as db:
            user = db.execute("SELECT id, password_hash FROM users WHERE email = ?", (email,)).fetchone()
        ok = check_password(password, user["password_hash"] if user else _DUMMY) and user is not None
        if not ok:
            with self._lock:
                self._fails.setdefault(email, []).append(now)
            return None
        self._fails.pop(email, None)
        token = secrets.token_urlsafe(32)
        with self._connect() as db:
            db.execute("DELETE FROM sessions WHERE last_seen < ? OR created < ?", (now - IDLE_S, now - MAX_AGE_S))
            db.execute("INSERT INTO sessions VALUES (?, ?, ?, ?)", (_token_hash(token), user["id"], now, now))
        return token

    def user(self, token: str | None) -> dict | None:
        """Who this cookie belongs to, or None if it is missing, unknown or expired. Using it keeps it alive."""
        if not token:
            return None
        now, th = self.now(), _token_hash(token)
        with self._connect() as db:
            r = db.execute("SELECT s.created, s.last_seen, u.id, u.email, u.client_id, c.slug FROM sessions s "
                           "JOIN users u ON u.id = s.user_id JOIN clients c ON c.id = u.client_id "
                           "WHERE s.token_hash = ?", (th,)).fetchone()
            if r is None:
                return None
            if now - r["last_seen"] > IDLE_S or now - r["created"] > MAX_AGE_S:
                db.execute("DELETE FROM sessions WHERE token_hash = ?", (th,))
                return None
            db.execute("UPDATE sessions SET last_seen = ? WHERE token_hash = ?", (now, th))
        return {"id": r["id"], "email": r["email"], "client_id": r["client_id"], "client": r["slug"]}

    def logout(self, token: str | None) -> None:
        if token:
            with self._connect() as db:
                db.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


def main(argv: list[str] | None = None) -> int:
    """python -m testbed.auth add-user you@example.com [--client default] : asks for the password twice."""
    from testbed import REPORTS_DIR
    from testbed.planstore import DEFAULT_CLIENT, PlanStore

    ap = argparse.ArgumentParser(description="Manage logins for the web panel.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add-user", help="add a user who can log in")
    add.add_argument("email")
    add.add_argument("--client", default=DEFAULT_CLIENT, help="the client the user belongs to (default: %(default)s)")
    add.add_argument("--db", type=Path, default=REPORTS_DIR / "plans.db")
    args = ap.parse_args(argv)

    plans = PlanStore(args.db)
    cid = plans.client_id(args.client)
    if cid is None:
        print(f"no client named {args.client!r}", file=sys.stderr)
        return 1
    pw = getpass.getpass("Password: ")
    if pw != getpass.getpass("Same password again: "):
        print("the passwords differ", file=sys.stderr)
        return 1
    try:
        Auth(args.db).add_user(args.email, pw, cid)
    except (ValueError, sqlite3.IntegrityError) as e:
        print(f"not added: {'that email already has a login' if isinstance(e, sqlite3.IntegrityError) else e}", file=sys.stderr)
        return 1
    print(f"added {args.email.strip().lower()} to client {args.client!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
