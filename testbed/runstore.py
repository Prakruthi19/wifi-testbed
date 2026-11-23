"""An indexed SQLite copy of reports/history/*.json, so the API answers from one query instead of
opening every run file.

The JSON files stay the source of truth (pytest writes them, see dashboard.save_run). This database
is an index built from them: delete reports/runs.db and it is rebuilt on the next request.

    write path: pytest -> history/<id>.json -> RunStore.add()           (at the end of each run)
    read path:  API -> RunStore.sync() (stat only) -> SELECT ... LIMIT   (per request)

sync() only stats the files; a file is parsed again only if its size or modified time changed, so
runs copied in by hand are picked up too. Every change bumps `version`, which the API uses as the
HTTP ETag: when nothing changed, the browser gets "304 Not Modified" and no body.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections import Counter
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,          -- the history file name, a sortable UTC timestamp
  finished TEXT NOT NULL,
  passed INTEGER NOT NULL, failed INTEGER NOT NULL, error INTEGER NOT NULL, skipped INTEGER NOT NULL,
  suites TEXT NOT NULL,         -- JSON list
  mtime_ns INTEGER NOT NULL, size INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS results (
  run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  pos INTEGER NOT NULL,         -- order within the run, as pytest ran them
  nodeid TEXT NOT NULL, suite TEXT NOT NULL, outcome TEXT NOT NULL,
  duration_s REAL, message TEXT, properties TEXT,
  PRIMARY KEY (run_id, pos)
);
CREATE INDEX IF NOT EXISTS results_by_test ON results (nodeid, run_id);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value INTEGER NOT NULL);
INSERT OR IGNORE INTO meta VALUES ('version', 0);
"""


def _counts(results: list[dict]) -> dict[str, int]:
    c = Counter(r["outcome"] for r in results)
    return {k: c.get(k, 0) for k in ("passed", "failed", "error", "skipped")}


class RunStore:
    _lock = threading.Lock()  # one writer at a time inside this process

    def __init__(self, db_path: Path, history_dir: Path):
        self.db_path = db_path
        self.history_dir = history_dir
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    # -- writing ---------------------------------------------------------------------------------
    def add(self, path: Path) -> bool:
        """Index one history file. Returns False if it is unreadable."""
        try:
            st = path.stat()
            run = json.loads(path.read_text())
            results = run["results"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            return False
        c = _counts(results)
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM runs WHERE id = ?", (path.stem,))
            db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?)",
                       (path.stem, run["finished"], c["passed"], c["failed"], c["error"], c["skipped"],
                        json.dumps(sorted({r["suite"] for r in results})), st.st_mtime_ns, st.st_size))
            db.executemany("INSERT INTO results VALUES (?,?,?,?,?,?,?,?)", [
                (path.stem, i, r["nodeid"], r["suite"], r["outcome"], r.get("duration_s"),
                 r.get("message", ""), json.dumps(r.get("properties", {})))
                for i, r in enumerate(results)])
            db.execute("UPDATE meta SET value = value + 1 WHERE key = 'version'")
        return True

    def sync(self) -> None:
        """Bring the index in line with the folder: add new or changed files, drop deleted ones."""
        on_disk = {}
        for p in self.history_dir.glob("*.json"):
            try:
                st = p.stat()
            except OSError:
                continue
            on_disk[p.stem] = (p, st.st_mtime_ns, st.st_size)
        with self._connect() as db:
            known = {r["id"]: (r["mtime_ns"], r["size"]) for r in db.execute("SELECT id, mtime_ns, size FROM runs")}
        for run_id, (p, mtime, size) in on_disk.items():
            if known.get(run_id) != (mtime, size):
                self.add(p)
        gone = [k for k in known if k not in on_disk]
        if gone:
            with self._lock, self._connect() as db:
                db.executemany("DELETE FROM runs WHERE id = ?", [(k,) for k in gone])
                db.execute("UPDATE meta SET value = value + 1 WHERE key = 'version'")

    # -- reading ---------------------------------------------------------------------------------
    def version(self) -> int:
        with self._connect() as db:
            return db.execute("SELECT value FROM meta WHERE key = 'version'").fetchone()[0]

    def list(self, limit: int = 1000, before: str | None = None) -> list[dict]:
        """Newest first. `before` is the id of the last run on the previous page (keyset pagination)."""
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM runs WHERE (? IS NULL OR id < ?) ORDER BY id DESC LIMIT ?",
                (before, before, limit)).fetchall()
        return [{"id": r["id"], "finished": r["finished"],
                 "counts": {k: r[k] for k in ("passed", "failed", "error", "skipped")},
                 "suites": json.loads(r["suites"])} for r in rows]

    def get(self, run_id: str) -> dict | None:
        with self._connect() as db:
            run = db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if run is None:
                return None
            results = db.execute("SELECT * FROM results WHERE run_id = ? ORDER BY pos", (run_id,)).fetchall()
        return {"id": run["id"], "finished": run["finished"],
                "counts": {k: run[k] for k in ("passed", "failed", "error", "skipped")},
                "results": [{"nodeid": r["nodeid"], "suite": r["suite"], "outcome": r["outcome"],
                             "duration_s": r["duration_s"], "message": r["message"],
                             "properties": json.loads(r["properties"] or "{}")} for r in results]}
