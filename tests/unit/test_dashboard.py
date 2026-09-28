"""Results dashboard built from recorded runs. No lab needed."""

from __future__ import annotations

import json
from types import SimpleNamespace

from testbed import dashboard


def fake_report(nodeid, when="call", outcome="passed", keywords=("lab", "failures"), props=(),
                longrepr=None, text=""):
    return SimpleNamespace(nodeid=nodeid, when=when, outcome=outcome, passed=outcome == "passed",
                           failed=outcome == "failed", skipped=outcome == "skipped",
                           keywords={k: 1 for k in keywords}, duration=1.234,
                           user_properties=list(props), longrepr=longrepr, longreprtext=text)


def test_record_only_the_verdict_phase():
    assert dashboard.record(fake_report("t::a", when="setup")) is None
    assert dashboard.record(fake_report("t::a", when="teardown")) is None
    r = dashboard.record(fake_report("t::a", props=[("roam_ms_log", 41.2)]))
    assert r["suite"] == "failures" and r["outcome"] == "passed" and r["properties"] == {"roam_ms_log": 41.2}
    err = dashboard.record(fake_report("t::b", when="setup", outcome="failed", text="E   boom"))
    assert err["outcome"] == "error" and err["message"] == "boom"
    skip = dashboard.record(fake_report("t::c", when="setup", outcome="skipped",
                                        longrepr=("f.py", 1, "Skipped: ap1 missing")))
    assert skip["outcome"] == "skipped" and skip["message"] == "ap1 missing"


def test_suite_of():
    assert dashboard.suite_of({"lab": 1, "roam": 1}, "tests/test_roaming.py::x") == "roam"
    assert dashboard.suite_of({}, "tests/unit/test_x.py::y") == "unit"


def test_latest_keeps_history_and_page_renders(tmp_path):
    node = "tests/test_failures.py::test_induced_failure[mac_blocked]"
    runs = [{"finished": "2026-09-27T16:47:00+00:00",
             "results": [{"nodeid": node, "suite": "failures", "outcome": "failed", "duration_s": 3,
                          "message": "assert 'network_selection' in ('authentication',)",
                          "properties": {}}]},
            {"finished": "2026-09-28T01:00:00+00:00",
             "results": [{"nodeid": node, "suite": "failures", "outcome": "passed", "duration_s": 3,
                          "message": "", "properties": {"harness_stage": "network_selection"}}]}]
    tests = dashboard.latest(runs)
    assert tests[node]["outcome"] == "passed" and tests[node]["history"] == ["failed", "passed"]

    art = tmp_path / "artifacts" / dashboard.artifact_dir_name(node)
    art.mkdir(parents=True)
    (art / "capture.pcap").write_bytes(b"")
    (art / "classification.json").write_text(json.dumps({"classifier": {"stage": "network_selection"}}))
    page = dashboard.render(runs, tmp_path)
    assert "Failure diagnosis" in page and "1/1 passed" in page
    assert f'href="artifacts/{art.name}/capture.pcap"' in page
    assert "classifier_stage <b>network_selection</b>" in page
    assert "changed outcome between runs" in page


def test_save_and_write(tmp_path):
    assert dashboard.save_run([], tmp_path) is None
    dashboard.save_run([{"nodeid": "t::a", "suite": "roam", "outcome": "skipped", "duration_s": 0,
                         "message": "ap1 missing", "properties": {}}], tmp_path)
    page = dashboard.write(tmp_path)
    assert "Roaming" in page.read_text() and "ap1 missing" in page.read_text()
