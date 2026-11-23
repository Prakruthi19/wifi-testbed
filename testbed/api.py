"""HTTP API for the web control panel in web/. It serves what the lab already saves and can start a suite.

    .venv/bin/uvicorn testbed.api:app --port 8000            # results and inventory (no root needed)
    sudo -E .venv/bin/uvicorn testbed.api:app --port 8000    # also lets the panel start lab runs
    .venv/bin/python -m testbed.api --export web/public/demo # freeze the current results as demo data

Data comes from reports/history/*.json (written by every pytest run, see testbed/dashboard.py),
reports/artifacts/<test>/ and lab/inventory.yaml. Passphrases are never sent to the browser.
Run lists and details are served from an SQLite index of the history files (reports/runs.db, see
testbed/runstore.py), and JSON answers carry an ETag so an unchanged answer costs a 304 and no body.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from testbed import LAB_DIR, REPO_ROOT, REPORTS_DIR
from testbed import dashboard
from testbed.runstore import RunStore

# Suites the panel may start. android needs a phone on the host, rf needs real radios, unit is CI's job.
STARTABLE = [s for s in dashboard.SUITES if s not in ("android", "rf", "unit")] + ["home"]
SECRET_KEYS = {"passphrase", "password", "wpa_passphrase"}


def _strip_secrets(value):
    if isinstance(value, dict):
        return {k: _strip_secrets(v) for k, v in value.items() if k not in SECRET_KEYS}
    if isinstance(value, list):
        return [_strip_secrets(v) for v in value]
    return value


def _run_id(run: dict) -> str:
    return run["_file"]


def _counts(results: list[dict]) -> dict[str, int]:
    c = Counter(r["outcome"] for r in results)
    return {k: c.get(k, 0) for k in ("passed", "failed", "error", "skipped")}


def _artifacts(nodeid: str, reports_dir: Path) -> tuple[list[str], str | None]:
    """Files saved for one test, and the classifier's stage if it left a verdict."""
    art = reports_dir / "artifacts" / dashboard.artifact_dir_name(nodeid)
    if not art.is_dir():
        return [], None
    files = sorted(p.name for p in art.iterdir() if p.is_file() and p.suffix in dashboard.SHOWN_FILES)
    stage = None
    try:
        c = json.loads((art / "classification.json").read_text())
        stage = c.get("classifier", c).get("stage")
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    return files, stage


# Parsed history files, keyed by path. A file is parsed again only if its size or modified time changed,
# so a request reads the disk once per new run instead of re-parsing every run every time.
_HISTORY_CACHE: dict[Path, tuple[tuple[int, int], dict]] = {}
_HISTORY_LOCK = threading.Lock()


def _load_history(p: Path) -> dict | None:
    try:
        st = p.stat()
        key = (st.st_mtime_ns, st.st_size)
        with _HISTORY_LOCK:
            hit = _HISTORY_CACHE.get(p)
        if hit and hit[0] == key:
            return hit[1]
        run = {**json.loads(p.read_text()), "_file": p.stem}
    except (OSError, json.JSONDecodeError):
        return None
    with _HISTORY_LOCK:
        _HISTORY_CACHE[p] = (key, run)
    return run


RECENT_RUNS = 20  # how many runs the Test runs page needs in full (sentences and test history)


def _with_artifacts(results: list[dict], reports_dir: Path) -> list[dict]:
    out = []
    for x in results:
        files, stage = _artifacts(x["nodeid"], reports_dir)
        out.append({**x, "artifact_dir": dashboard.artifact_dir_name(x["nodeid"]),
                    "files": files, "classifier_stage": stage})
    return out


class Data:
    """Reads the lab's saved files. One instance per request, so new runs show up without a restart;
    the files themselves come from a cache that only re-reads files that changed."""

    def __init__(self, reports_dir: Path = REPORTS_DIR, inventory: Path = LAB_DIR / "inventory.yaml"):
        self.reports_dir = reports_dir
        self.inventory = inventory
        self.runs = []
        for p in sorted((reports_dir / dashboard.HISTORY).glob("*.json")):
            run = _load_history(p)
            if run is not None:
                self.runs.append(run)

    def summary(self) -> dict:
        tests = dashboard.latest(self.runs)
        return {"sample": False, "runs": len(self.runs),
                "last_finished": self.runs[-1]["finished"] if self.runs else None,
                "tests": len(tests), "counts": _counts(list(tests.values()))}

    def lab(self) -> dict:
        inv = yaml.safe_load(self.inventory.read_text()) if self.inventory.exists() else {}
        return _strip_secrets(inv or {})

    def run_list(self) -> list[dict]:
        return [{"id": _run_id(r), "finished": r["finished"], "counts": _counts(r["results"]),
                 "suites": sorted({x["suite"] for x in r["results"]})} for r in reversed(self.runs)]

    def run(self, run_id: str) -> dict | None:
        for r in self.runs:
            if _run_id(r) == run_id:
                return {"id": run_id, "finished": r["finished"], "counts": _counts(r["results"]),
                        "results": _with_artifacts(r["results"], self.reports_dir)}
        return None

    def recent(self, n: int = RECENT_RUNS) -> list[dict]:
        """The newest n runs in full, newest first: one request instead of one per run."""
        return [self.run(r["id"]) for r in self.run_list()[:max(0, n)]]

    def tests(self) -> list[dict]:
        out = []
        for t in dashboard.latest(self.runs).values():
            files, stage = _artifacts(t["nodeid"], self.reports_dir)
            out.append({**t, "artifact_dir": dashboard.artifact_dir_name(t["nodeid"]),
                        "files": files, "classifier_stage": stage})
        return sorted(out, key=lambda t: (dashboard.OUTCOME_ORDER.get(t["outcome"], 9), t["nodeid"]))


# -- starting runs -----------------------------------------------------------------------------

class Jobs:
    """At most one lab run at a time; lab tests share the radios, so two would break each other."""

    def __init__(self, log_dir: Path):
        self.log_dir = log_dir
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()

    def busy(self) -> bool:
        return any(j["status"] == "running" for j in self.jobs.values())

    def start(self, suite: str, cmd: list[str] | None = None) -> dict:
        with self.lock:
            if self.busy():
                raise HTTPException(409, "a run is already in progress")
            job_id = uuid.uuid4().hex[:8]
            self.log_dir.mkdir(parents=True, exist_ok=True)
            log = self.log_dir / f"{job_id}.log"
            cmd = cmd or [sys.executable, "-m", "pytest", "-m", suite, "-ra"]
            proc = subprocess.Popen(cmd, cwd=REPO_ROOT, stdout=log.open("w"), stderr=subprocess.STDOUT)
            job = {"id": job_id, "suite": suite, "status": "running", "returncode": None,
                   "started": _now(), "finished": None, "_proc": proc, "_log": log}
            self.jobs[job_id] = job
        threading.Thread(target=self._wait, args=(job,), daemon=True).start()
        return self.view(job)

    def _wait(self, job: dict) -> None:
        rc = job["_proc"].wait()
        job["returncode"] = rc
        job["finished"] = _now()
        job["status"] = "passed" if rc == 0 else "failed"

    def current(self) -> dict | None:
        """The running job, else the most recent one, so a page opened later can pick it up again."""
        if not self.jobs:
            return None
        running = [j for j in self.jobs.values() if j["status"] == "running"]
        return running[0] if running else max(self.jobs.values(), key=lambda j: j["started"])

    def view(self, job: dict) -> dict:
        try:
            lines = job["_log"].read_text(errors="replace").splitlines()
        except OSError:
            lines = []
        return {k: v for k, v in job.items() if not k.startswith("_")} | {"log_tail": lines[-40:],
                                                                          "progress": _progress(lines)}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _progress(lines: list[str]) -> dict:
    """Tests finished out of tests selected, read from pytest's own output (one character per test)."""
    total = None
    done = 0
    for line in lines:
        m = re.search(r"collected (\d+) items?(?: / (\d+) deselected)?(?: / (\d+) selected)?", line)
        if m:
            total = int(m.group(3) or m.group(1))
        m = re.match(r"\S+\.py ([.sFExX]+)", line)
        if m:
            done += len(m.group(1))
    return {"done": done, "total": total}


class StartRun(BaseModel):
    suite: str


def create_app(reports_dir: Path = REPORTS_DIR, inventory: Path = LAB_DIR / "inventory.yaml",
               is_root=lambda: os.geteuid() == 0) -> FastAPI:
    app = FastAPI(title="wifi-testbed API")
    jobs = Jobs(reports_dir / "jobs")
    data = lambda: Data(reports_dir, inventory)

    store = RunStore(reports_dir / "runs.db", reports_dir / dashboard.HISTORY)

    def cached(request: Request, make, *salt) -> Response:
        """HTTP caching: the ETag is the index version (bumped by every new or changed run) plus
        the URL. If the browser already holds that version it gets 304 and no body, and nothing is
        computed. Cache-Control: no-cache means "keep it, but ask me before using it"."""
        store.sync()
        key = hashlib.sha1(repr((str(request.url), *salt)).encode()).hexdigest()[:12]
        tag = f'W/"{store.version()}-{key}"'
        headers = {"ETag": tag, "Cache-Control": "no-cache"}
        if request.headers.get("if-none-match") == tag:
            return Response(status_code=304, headers=headers)
        return JSONResponse(make(), headers=headers)

    @app.get("/api/summary")
    def summary(request: Request):
        root = is_root()
        return cached(request, lambda: data().summary() | {"can_start_runs": root, "startable_suites": STARTABLE}, root)

    @app.get("/api/lab")
    def lab():
        return data().lab()

    @app.get("/api/runs")
    def runs(request: Request, limit: int = 1000, before: str | None = None):
        return cached(request, lambda: store.list(max(1, min(limit, 1000)), before))

    def detail(run_id: str) -> dict | None:
        r = store.get(run_id)
        return r and {**r, "results": _with_artifacts(r["results"], reports_dir)}

    @app.get("/api/runs/recent")  # declared before /api/runs/{run_id} so "recent" is not read as an id
    def recent_runs(request: Request, n: int = RECENT_RUNS):
        return cached(request, lambda: [detail(r["id"]) for r in store.list(max(0, min(n, 100)))])

    @app.get("/api/runs/{run_id}")
    def run(request: Request, run_id: str):
        store.sync()
        if store.get(run_id) is None:
            raise HTTPException(404, "no such run")
        return cached(request, lambda: detail(run_id))

    @app.get("/api/tests")
    def tests(request: Request):
        return cached(request, lambda: data().tests())

    @app.get("/api/artifacts/{test_dir}/{name}")
    def artifact(test_dir: str, name: str):
        base = (reports_dir / "artifacts").resolve()
        path = (base / test_dir / name).resolve()
        if base not in path.parents or not path.is_file():
            raise HTTPException(404, "no such file")
        return FileResponse(path)

    @app.post("/api/jobs", status_code=201)
    def start(body: StartRun):
        if body.suite not in STARTABLE:
            raise HTTPException(400, f"unknown suite; choose one of {STARTABLE}")
        if not is_root():
            raise HTTPException(403, "lab runs need root: start the API with sudo -E")
        return jobs.start(body.suite)

    @app.get("/api/jobs/current")
    def current_job():
        j = jobs.current()
        return {"job": jobs.view(j) if j else None}

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str):
        if job_id not in jobs.jobs:
            raise HTTPException(404, "no such job")
        return jobs.view(jobs.jobs[job_id])

    app.state.jobs = jobs
    return app


app = create_app()


# -- demo export -------------------------------------------------------------------------------

def export(out: Path, reports_dir: Path = REPORTS_DIR, inventory: Path = LAB_DIR / "inventory.yaml") -> int:
    """Write the same JSON the API serves as static files, for the GitHub Pages demo build."""
    d = Data(reports_dir, inventory)
    (out / "runs").mkdir(parents=True, exist_ok=True)
    write = lambda name, obj: (out / name).write_text(json.dumps(obj, indent=1))
    write("summary.json", d.summary() | {"can_start_runs": False, "startable_suites": STARTABLE})
    write("lab.json", d.lab())
    write("runs.json", d.run_list())
    write("tests.json", d.tests())
    for r in d.run_list():
        write(f"runs/{r['id']}.json", d.run(r["id"]))
    write("runs/recent.json", d.recent())
    return len(d.runs)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export", type=Path, required=True, metavar="DIR")
    n = export(ap.parse_args().export)
    print(f"exported {n} runs")
