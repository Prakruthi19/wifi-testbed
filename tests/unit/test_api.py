"""Web panel API over recorded runs. No lab needed."""

from __future__ import annotations

import json
import sys

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from testbed import api  # noqa: E402

NODE = "tests/test_failures.py::test_induced_failure[mac_blocked]"


@pytest.fixture
def lab(tmp_path):
    hist = tmp_path / "reports" / "history"
    hist.mkdir(parents=True)
    (hist / "20260927T164700Z.json").write_text(json.dumps({
        "finished": "2026-09-27T16:47:00+00:00",
        "results": [{"nodeid": NODE, "suite": "failures", "outcome": "failed", "duration_s": 3,
                     "message": "wrong stage", "properties": {}}]}))
    (hist / "20260928T030000Z.json").write_text(json.dumps({
        "finished": "2026-09-28T03:00:00+00:00",
        "results": [{"nodeid": NODE, "suite": "failures", "outcome": "passed", "duration_s": 2,
                     "message": "", "properties": {"stage": "network_selection"}}]}))
    art = tmp_path / "reports" / "artifacts" / api.dashboard.artifact_dir_name(NODE)
    art.mkdir(parents=True)
    (art / "capture.pcap").write_bytes(b"\xd4\xc3\xb2\xa1")
    (art / "classification.json").write_text(json.dumps({"classifier": {"stage": "network_selection"}}))
    inv = tmp_path / "inventory.yaml"
    inv.write_text("aps:\n  - {name: ap-wpa2-2g, ssid: lab-wpa2, channel: 6, passphrase: secret123}\n")
    return tmp_path


def client(lab, root=False):
    return TestClient(api.create_app(lab / "reports", lab / "inventory.yaml", is_root=lambda: root))


def test_summary_runs_and_tests(lab):
    c = client(lab)
    s = c.get("/api/summary").json()
    assert s["runs"] == 2 and s["tests"] == 1 and s["counts"]["passed"] == 1 and not s["can_start_runs"]
    runs = c.get("/api/runs").json()
    assert [r["id"] for r in runs] == ["20260928T030000Z", "20260927T164700Z"]  # newest first
    t = c.get("/api/tests").json()[0]
    assert t["history"] == ["failed", "passed"] and t["classifier_stage"] == "network_selection"
    assert "capture.pcap" in t["files"]
    detail = c.get("/api/runs/20260927T164700Z").json()
    assert detail["results"][0]["outcome"] == "failed"
    assert c.get("/api/runs/nope").status_code == 404


def test_lab_never_sends_passphrases(lab):
    body = client(lab).get("/api/lab").text
    assert "lab-wpa2" in body and "secret123" not in body and "passphrase" not in body


def test_artifacts_are_served_but_paths_cannot_escape(lab):
    c = client(lab)
    d = api.dashboard.artifact_dir_name(NODE)
    assert c.get(f"/api/artifacts/{d}/capture.pcap").content == b"\xd4\xc3\xb2\xa1"
    assert c.get(f"/api/artifacts/{d}/..%2F..%2Fhistory%2F20260927T164700Z.json").status_code == 404
    assert c.get("/api/artifacts/x/missing.log").status_code == 404


def test_starting_a_run_needs_root_and_a_known_suite(lab):
    assert client(lab).post("/api/jobs", json={"suite": "failures"}).status_code == 403
    assert client(lab, root=True).post("/api/jobs", json={"suite": "rm -rf"}).status_code == 400


def test_one_job_at_a_time_and_its_result(lab):
    jobs = api.Jobs(lab / "jobs")
    job = jobs.start("failures", cmd=[sys.executable, "-c", "import time; print('hello'); time.sleep(0.5)"])
    with pytest.raises(api.HTTPException) as busy:
        jobs.start("failures", cmd=[sys.executable, "-c", "pass"])
    assert busy.value.status_code == 409
    jobs.jobs[job["id"]]["_proc"].wait()
    for _ in range(50):  # the waiter thread sets the status just after the process exits
        if jobs.jobs[job["id"]]["status"] != "running":
            break
        __import__("time").sleep(0.05)
    view = jobs.view(jobs.jobs[job["id"]])
    assert view["status"] == "passed" and view["log_tail"] == ["hello"]
    assert view["started"] and view["finished"]
    assert jobs.current()["id"] == job["id"]  # a page opened later finds the last run


def test_current_job_is_empty_before_any_run(lab):
    assert client(lab).get("/api/jobs/current").json() == {"job": None}


def test_progress_is_read_from_pytest_output():
    lines = [
        "collected 318 items / 310 deselected / 8 selected",
        "",
        "tests/test_failures.py ..s.F",
    ]
    assert api._progress(lines) == {"done": 5, "total": 8}
    assert api._progress(["collected 3 items", "tests/test_a.py ...  [100%]"]) == {"done": 3, "total": 3}
    assert api._progress([]) == {"done": 0, "total": None}


def test_export_writes_the_same_json_as_the_api(lab, tmp_path):
    out = tmp_path / "demo"
    assert api.export(out, lab / "reports", lab / "inventory.yaml") == 2
    assert json.loads((out / "runs.json").read_text())[0]["id"] == "20260928T030000Z"
    assert (out / "runs" / "20260927T164700Z.json").exists()
    assert [r["id"] for r in json.loads((out / "runs" / "recent.json").read_text())] == ["20260928T030000Z", "20260927T164700Z"]
    assert "secret123" not in (out / "lab.json").read_text()


def test_recent_runs_in_one_request_newest_first(lab):
    c = client(lab)
    recent = c.get("/api/runs/recent").json()
    assert [r["id"] for r in recent] == ["20260928T030000Z", "20260927T164700Z"]
    assert recent[1]["results"][0]["outcome"] == "failed"
    assert [r["id"] for r in c.get("/api/runs/recent?n=1").json()] == ["20260928T030000Z"]


def test_history_files_are_parsed_once_until_they_change(lab, monkeypatch):
    c = client(lab)
    c.get("/api/runs")
    reads = []
    real = api.Path.read_text
    monkeypatch.setattr(api.Path, "read_text", lambda self, *a, **k: (reads.append(self.name), real(self, *a, **k))[1])
    c.get("/api/runs")
    assert reads == []  # nothing changed, nothing re-read
    hist = lab / "reports" / "history"
    (hist / "20260929T010000Z.json").write_text(json.dumps({
        "finished": "2026-09-29T01:00:00+00:00",
        "results": [{"nodeid": NODE, "suite": "failures", "outcome": "passed", "duration_s": 1,
                     "message": "", "properties": {}}]}))
    assert c.get("/api/runs").json()[0]["id"] == "20260929T010000Z"  # a new run shows up without a restart
    assert reads == ["20260929T010000Z.json"]  # and only the new file was read


def test_unchanged_data_returns_304_and_a_new_run_changes_the_etag(lab):
    c = client(lab)
    first = c.get("/api/runs")
    tag = first.headers["etag"]
    assert first.headers["cache-control"] == "no-cache"
    again = c.get("/api/runs", headers={"If-None-Match": tag})
    assert again.status_code == 304 and again.content == b""
    (lab / "reports" / "history" / "20260929T010000Z.json").write_text(json.dumps({
        "finished": "2026-09-29T01:00:00+00:00",
        "results": [{"nodeid": NODE, "suite": "failures", "outcome": "passed", "duration_s": 1,
                     "message": "", "properties": {}}]}))
    fresh = c.get("/api/runs", headers={"If-None-Match": tag})
    assert fresh.status_code == 200 and fresh.json()[0]["id"] == "20260929T010000Z"
    assert fresh.headers["etag"] != tag


def test_runs_are_paged_newest_first(lab):
    c = client(lab)
    page1 = c.get("/api/runs?limit=1").json()
    assert [r["id"] for r in page1] == ["20260928T030000Z"]
    page2 = c.get(f"/api/runs?limit=1&before={page1[-1]['id']}").json()
    assert [r["id"] for r in page2] == ["20260927T164700Z"]
    assert c.get("/api/runs?limit=1&before=20260927T164700Z").json() == []


def test_the_index_rebuilds_itself_and_drops_deleted_runs(lab):
    c = client(lab)
    assert len(c.get("/api/runs").json()) == 2
    (lab / "reports" / "runs.db").unlink()
    assert len(client(lab).get("/api/runs").json()) == 2  # rebuilt from the JSON files
    (lab / "reports" / "history" / "20260927T164700Z.json").unlink()
    assert [r["id"] for r in client(lab).get("/api/runs").json()] == ["20260928T030000Z"]


def test_job_events_push_progress_and_end_with_the_final_state(lab):
    app = api.create_app(lab / "reports", lab / "inventory.yaml", is_root=lambda: True)
    job = app.state.jobs.start("failures", cmd=[sys.executable, "-c",
                                                "import time\nfor i in range(3): print('line', i, flush=True); time.sleep(0.3)"])
    c = TestClient(app)
    assert c.get("/api/jobs/nope/events").status_code == 404
    events = []
    with c.stream("GET", f"/api/jobs/{job['id']}/events") as res:
        assert res.headers["content-type"].startswith("text/event-stream")
        for line in res.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    assert len(events) >= 2  # pushed as the log grew, not only at the end
    assert events[-1]["status"] == "passed" and events[-1]["log_tail"][-1] == "line 2"
    assert all(e["status"] == "running" for e in events[:-1])
