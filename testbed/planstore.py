"""Saved Wi-Fi plans from the network builder, in SQLite (reports/plans.db).

Unlike runs.db, which is an index rebuilt from the JSON history files, this database IS the source of
truth for saved plans: deleting it deletes them.

Built for more than one client from the start, even though the app has one today:

    clients  1 ──< plans          a client (a customer, a team) owns many plans ("maps")

    clients(id, slug, name, created)            slug is the stable name used in URLs, e.g. "default"
    plans(id, client_id, name, name_key, home, body, created, updated)
        UNIQUE (client_id, name_key)            names are unique per client, ignoring case
        body                                    the plan in the same JSON format as a downloaded file

Every query filters by client_id, so adding clients later is adding rows and a way to pick the client
(a login), not a schema change. The API uses the "default" client until then.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
  id INTEGER PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plans (
  id INTEGER PRIMARY KEY,
  client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  name_key TEXT NOT NULL,          -- lower-cased name, so "Home" and "home" count as the same plan
  home TEXT NOT NULL,              -- the floor-plan template, kept out of body so lists need no JSON parsing
  aps INTEGER NOT NULL,            -- number of access points, for the same reason
  body TEXT NOT NULL,              -- the plan, in the downloadable file format
  created TEXT NOT NULL,
  updated TEXT NOT NULL,
  UNIQUE (client_id, name_key)
);
CREATE INDEX IF NOT EXISTS plans_by_client ON plans (client_id, updated DESC);
"""
DEFAULT_CLIENT = "default"


class NameTaken(Exception):
    """A plan with this name already exists for the client; the caller decides whether to replace it."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PlanStore:
    _lock = threading.Lock()

    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(SCHEMA)
            db.execute("INSERT OR IGNORE INTO clients (slug, name, created) VALUES (?, ?, ?)",
                       (DEFAULT_CLIENT, "Default client", _now()))

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    def client_id(self, slug: str) -> int | None:
        with self._connect() as db:
            row = db.execute("SELECT id FROM clients WHERE slug = ?", (slug,)).fetchone()
        return row["id"] if row else None

    @staticmethod
    def _summary(r: sqlite3.Row) -> dict:
        return {"id": r["id"], "name": r["name"], "home": r["home"], "aps": r["aps"],
                "created": r["created"], "updated": r["updated"]}

    def list(self, client_id: int) -> list[dict]:
        """Newest change first. Only the summary columns: no plan bodies are read."""
        with self._connect() as db:
            rows = db.execute("SELECT id, name, home, aps, created, updated FROM plans WHERE client_id = ? "
                              "ORDER BY updated DESC, id DESC", (client_id,)).fetchall()
        return [self._summary(r) for r in rows]

    def get(self, client_id: int, plan_id: int) -> dict | None:
        with self._connect() as db:
            r = db.execute("SELECT * FROM plans WHERE client_id = ? AND id = ?", (client_id, plan_id)).fetchone()
        return r and {**self._summary(r), "plan": json.loads(r["body"])}

    def save(self, client_id: int, name: str, plan: dict, replace: bool = False) -> tuple[dict, bool]:
        """Save under `name`. Returns (summary, created). An existing name raises NameTaken unless replace."""
        name = name.strip()
        key, body, now = name.lower(), json.dumps(plan), _now()
        with self._lock, self._connect() as db:
            old = db.execute("SELECT id FROM plans WHERE client_id = ? AND name_key = ?", (client_id, key)).fetchone()
            if old and not replace:
                raise NameTaken(name)
            if old:
                db.execute("UPDATE plans SET name = ?, home = ?, aps = ?, body = ?, updated = ? WHERE id = ?",
                           (name, plan["home"], len(plan["accessPoints"]), body, now, old["id"]))
                plan_id = old["id"]
            else:
                plan_id = db.execute(
                    "INSERT INTO plans (client_id, name, name_key, home, aps, body, created, updated) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (client_id, name, key, plan["home"], len(plan["accessPoints"]), body, now, now)).lastrowid
            row = db.execute("SELECT id, name, home, aps, created, updated FROM plans WHERE id = ?", (plan_id,)).fetchone()
        return self._summary(row), old is None

    def delete(self, client_id: int, plan_id: int) -> bool:
        with self._lock, self._connect() as db:
            return db.execute("DELETE FROM plans WHERE client_id = ? AND id = ?", (client_id, plan_id)).rowcount > 0
