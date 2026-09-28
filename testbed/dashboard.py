"""One-page summary of every lab run: reports/dashboard.html.

    .venv/bin/python -m testbed.dashboard    # rebuild by hand (pytest also rebuilds it every run)

Each pytest session appends its results to reports/history/<time>.json (see tests/conftest.py).
The dashboard shows, per suite, the latest outcome of every test, the facts it recorded (stage,
timings, throughput), the classifier's verdict, links to its pcap and logs, and the outcome of
earlier runs of the same test so flips stand out. Delete reports/history to start fresh.
"""

from __future__ import annotations

import argparse
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from testbed import REPORTS_DIR

HISTORY = "history"

# marker -> (title, what a pass shows). Order is the order on the page.
SUITES = {
    "failures": ("Failure diagnosis", "one failure induced at a time; the harness and the "
                 "classifier must name the stage it broke at"),
    "enterprise": ("Enterprise login (802.1X)", "username/password login; wrong password and "
                   "untrusted server fail at the eap stage"),
    "decrypt": ("WPA3 capture decryption", "capture decrypted with the session key; the "
                "password alone must not work"),
    "roam": ("Roaming", "client moves between two APs: full re-login vs 802.11r fast roaming"),
    "faults": ("Fault injection", "break the lab while connected; detect it and recover"),
    "smarthome": ("Smart-home behaviours", "router reboot, password change, 2.4 GHz-only device"),
    "perf": ("Performance (virtual network)", "iperf3 and ping over emulated radios: a software "
             "baseline, not Wi-Fi speed"),
    "matrix": ("Connectivity matrix", "security x PMF x channel x client, repeated joins"),
    "qualify": ("AP qualification", "baseline every inventory AP must pass"),
    "vlan": ("VLAN segmentation", "SSIDs on separate VLANs; isolation enforced"),
    "android": ("Android (ADB)", "phone behaviour driven over ADB"),
    "rf": ("Range vs rate", "attenuator sweep; real radios only"),
    "unit": ("Unit tests", "parsers and decision logic, no lab"),
}
OUTCOME_ORDER = {"failed": 0, "error": 1, "passed": 2, "skipped": 3}


def artifact_dir_name(nodeid: str) -> str:
    """Same naming as the `artifacts` fixture in tests/conftest.py."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", nodeid.split("::", 1)[-1])[:120]


def suite_of(keywords, nodeid: str) -> str:
    for marker in SUITES:
        if marker in keywords:
            return marker
    return "unit" if "/unit/" in nodeid else "other"


def _message(report) -> str:
    """Why a test failed or skipped, in one line."""
    if report.skipped and isinstance(report.longrepr, tuple):
        return str(report.longrepr[2]).removeprefix("Skipped: ")
    text = getattr(report, "longreprtext", "") or ""
    lines = [ln[2:].strip() for ln in text.splitlines() if ln.startswith("E ")]
    return " ".join(lines)[:400] if lines else text.strip().splitlines()[-1][:400] if text else ""


def record(report) -> dict | None:
    """A history entry for one pytest TestReport, or None if this phase is not the verdict."""
    if report.when == "call" or (report.when == "setup" and not report.passed):
        outcome = report.outcome
        if report.when == "setup" and report.failed:
            outcome = "error"
        return {
            "nodeid": report.nodeid,
            "suite": suite_of(report.keywords, report.nodeid),
            "outcome": outcome,
            "duration_s": round(report.duration, 2),
            "message": "" if report.passed else _message(report),
            "properties": {k: _jsonable(v) for k, v in report.user_properties},
        }
    return None


def _jsonable(value):
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def save_run(results: list[dict], reports_dir: Path = REPORTS_DIR) -> Path | None:
    if not results:
        return None
    d = reports_dir / HISTORY
    d.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    path = d / f"{started:%Y%m%dT%H%M%S%fZ}.json"
    path.write_text(json.dumps({"finished": started.isoformat(timespec="seconds"),
                                "results": results}, indent=1))
    return path


def load_runs(reports_dir: Path = REPORTS_DIR) -> list[dict]:
    runs = []
    for p in sorted((reports_dir / HISTORY).glob("*.json")):
        try:
            runs.append(json.loads(p.read_text()))
        except (OSError, json.JSONDecodeError):
            continue
    return runs


def latest(runs: list[dict]) -> dict[str, dict]:
    """nodeid -> latest result, with `history` (oldest first) and `when` added."""
    out: dict[str, dict] = {}
    for run in runs:
        for r in run["results"]:
            prev = out.get(r["nodeid"])
            hist = (prev["history"] if prev else []) + [r["outcome"]]
            out[r["nodeid"]] = {**r, "history": hist, "when": run["finished"]}
    return out


# -- rendering -------------------------------------------------------------------------------

CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1b;--muted:#6b6b66;--line:#e3e2dc;
--pass:#1f7a3f;--pass-bg:#e3f4e8;--fail:#b3261e;--fail-bg:#fbe4e2;--skip:#7a6a1f;--skip-bg:#f6efd6}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--card:#1f1f1d;--ink:#ecebe6;--muted:#a3a29b;
--line:#34332f;--pass:#7fd49a;--pass-bg:#1c3324;--fail:#ff8f86;--fail-bg:#3a1f1d;--skip:#e0cc7a;
--skip-bg:#332d17}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:0}
.sub{color:var(--muted);margin:0 0 20px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:24px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.tile b{display:block;font-size:26px;font-variant-numeric:tabular-nums}.tile span{color:var(--muted)}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;margin-bottom:16px;overflow:hidden}
section>header{padding:14px 16px;border-bottom:1px solid var(--line);display:flex;gap:12px;
align-items:baseline;flex-wrap:wrap}section>header p{margin:0;color:var(--muted);flex:1 1 300px}
.count{font-variant-numeric:tabular-nums;color:var(--muted)}
.row{display:grid;grid-template-columns:72px minmax(0,1fr);gap:12px;padding:12px 16px;border-top:1px solid var(--line)}
.row:first-of-type{border-top:0}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;font-weight:600;text-align:center}
.passed{color:var(--pass);background:var(--pass-bg)}.failed,.error{color:var(--fail);background:var(--fail-bg)}
.skipped{color:var(--skip);background:var(--skip-bg)}
.name{font-weight:600;overflow-wrap:anywhere}.facts span,.msg,.links a{overflow-wrap:anywhere}.msg{margin:4px 0 0;color:var(--fail)}
.skipmsg{margin:4px 0 0;color:var(--muted)}
.facts{display:flex;flex-wrap:wrap;gap:4px 14px;margin-top:6px;color:var(--muted);font-size:13px}
.facts b{color:var(--ink);font-weight:500}
.links{margin-top:6px;font-size:13px;display:flex;flex-wrap:wrap;gap:4px 12px}
a{color:inherit}.dots{display:inline-flex;gap:3px;vertical-align:middle;margin-left:8px}
.dot{width:8px;height:8px;border-radius:50%}.dot.passed{background:var(--pass)}
.dot.failed,.dot.error{background:var(--fail)}.dot.skipped{background:var(--skip)}
.note{font-size:13px;color:var(--muted);margin-top:24px}
details summary{cursor:pointer;padding:12px 16px;color:var(--muted)}
"""

SHOWN_FILES = (".pcap", ".log", ".json", ".txt", ".html", ".png", ".zip")


def _fmt(value) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, (dict, list, tuple)):
        text = json.dumps(value, separators=(", ", ": "))
        return text if len(text) <= 90 else text[:87] + "..."
    return str(value)


def _test_name(nodeid: str) -> str:
    return nodeid.split("::", 1)[-1].replace("test_", "", 1)


def _row(r: dict, reports_dir: Path) -> str:
    e = html.escape
    parts = [f'<div class="row"><div><span class="badge {r["outcome"]}">{r["outcome"]}</span></div><div>']
    dots = "".join(f'<span class="dot {o}" title="{o}"></span>' for o in r["history"][-10:])
    hist = f'<span class="dots" title="last runs, oldest first">{dots}</span>' if len(r["history"]) > 1 else ""
    parts.append(f'<div class="name">{e(_test_name(r["nodeid"]))}{hist}</div>')
    if r["message"]:
        cls = "skipmsg" if r["outcome"] == "skipped" else "msg"
        parts.append(f'<p class="{cls}">{e(r["message"])}</p>')

    facts = dict(r["properties"])
    art = reports_dir / "artifacts" / artifact_dir_name(r["nodeid"])
    verdict = art / "classification.json"
    if verdict.exists():
        try:
            c = json.loads(verdict.read_text())
            c = c.get("classifier", c)
            if "stage" in c:
                facts.setdefault("classifier_stage", c["stage"])
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
    facts["time"] = f'{r["duration_s"]:g} s'
    parts.append('<div class="facts">' + "".join(
        f"<span>{e(k)} <b>{e(_fmt(v))}</b></span>" for k, v in facts.items()) + "</div>")

    if art.is_dir():
        files = sorted(p for p in art.iterdir() if p.suffix in SHOWN_FILES)
        if files:
            parts.append('<div class="links">' + "".join(
                f'<a href="{e(p.relative_to(reports_dir).as_posix())}">{e(p.name)}</a>'
                for p in files) + "</div>")
    parts.append("</div></div>")
    return "".join(parts)


def render(runs: list[dict], reports_dir: Path = REPORTS_DIR) -> str:
    e = html.escape
    tests = latest(runs)
    counts = {o: sum(r["outcome"] == o for r in tests.values()) for o in ("passed", "failed", "error", "skipped")}
    flips = sum(len(set(r["history"]) - {"skipped"}) > 1 for r in tests.values())
    last = runs[-1]["finished"][:16].replace("T", " ") + " UTC" if runs else "never"
    out = ["<!doctype html><html lang='en'><meta charset='utf-8'>",
           "<meta name='viewport' content='width=device-width,initial-scale=1'>",
           f"<title>Wi-Fi test bed results</title><style>{CSS}</style><main>",
           "<h1>Wi-Fi test bed results</h1>",
           f"<p class='sub'>{len(runs)} run(s), latest {e(last)}. Emulated lab "
           "(mac80211_hwsim, hostapd, wpa_supplicant) unless a suite says otherwise.</p>",
           "<div class='tiles'>",
           f"<div class='tile'><b>{len(tests)}</b><span>tests</span></div>",
           f"<div class='tile'><b style='color:var(--pass)'>{counts['passed']}</b><span>passed</span></div>",
           f"<div class='tile'><b style='color:var(--fail)'>{counts['failed'] + counts['error']}</b>"
           "<span>failed or errored</span></div>",
           f"<div class='tile'><b>{counts['skipped']}</b><span>skipped</span></div>",
           f"<div class='tile'><b>{flips}</b><span>changed outcome between runs</span></div>",
           "</div>"]
    extra = [(n, t) for n, t in (("matrix.html", "connectivity matrix"), ("report.html", "latest pytest report"))
             if (reports_dir / n).exists()]
    extra += [(p.name, p.stem) for p in sorted(reports_dir.glob("demo-*.html"))]
    if extra:
        out.append("<p class='sub'>Also: " + ", ".join(f"<a href='{e(n)}'>{e(t)}</a>" for n, t in extra) + "</p>")

    by_suite: dict[str, list[dict]] = {}
    for r in tests.values():
        by_suite.setdefault(r["suite"], []).append(r)
    for suite in [s for s in SUITES if s in by_suite] + sorted(set(by_suite) - set(SUITES)):
        rows = sorted(by_suite[suite], key=lambda r: (OUTCOME_ORDER.get(r["outcome"], 9), r["nodeid"]))
        title, blurb = SUITES.get(suite, (suite, ""))
        ok = sum(r["outcome"] == "passed" for r in rows)
        ran = sum(r["outcome"] != "skipped" for r in rows)
        head = (f"<header><h2>{e(title)}</h2><span class='count'>{ok}/{ran} passed"
                f"{f', {len(rows) - ran} skipped' if len(rows) > ran else ''}</span>"
                f"<p>{e(blurb)}</p></header>")
        body = "".join(_row(r, reports_dir) for r in rows)
        if suite == "unit":
            body = f"<details><summary>show {len(rows)} unit tests</summary>{body}</details>"
        out.append(f"<section>{head}{body}</section>")
    if not tests:
        out.append("<p>No runs recorded yet. Run any pytest suite; this page is rebuilt after each run.</p>")
    out.append("<p class='note'>Latest result per test across all recorded runs; dots show earlier "
               "runs, oldest first. Performance figures are virtual-network measurements. "
               "Delete reports/history to start fresh.</p></main></html>")
    return "".join(out)


def write(reports_dir: Path = REPORTS_DIR) -> Path:
    path = reports_dir / "dashboard.html"
    path.write_text(render(load_runs(reports_dir), reports_dir))
    return path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--reports", type=Path, default=REPORTS_DIR)
    args = p.parse_args(argv)
    print(write(args.reports))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
