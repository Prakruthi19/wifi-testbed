"""Turn one failed test's artifacts into a bug report draft (Markdown) for GitHub Issues or Jira.

    python -m testbed.bug_draft reports/artifacts/test_induced_failure_mac_blocked_

It reads what the harness already saved (classification.json, iperf.json, logs, pcap) and fills
the fields a lab bug needs: title, repro, expected vs actual, evidence, attachments, environment.
Severity and triage stay a human call; the draft only proposes a label.
"""

from __future__ import annotations

import argparse
import json
import platform
from pathlib import Path

from testbed import inventory as inv


def _test_name(artifact_dir: Path) -> str:
    """The artifact folder is the test id with [] and other symbols turned into _ (conftest._safe)."""
    return artifact_dir.name.strip("_")


def _software() -> dict:
    try:
        return {k: v for k, v in inv.load().raw.get("software", {}).items() if v}
    except Exception:  # inventory is optional for a draft
        return {}


def draft(artifact_dir: Path) -> str:
    artifact_dir = Path(artifact_dir)
    test = _test_name(artifact_dir)
    lines: list[str] = []
    title = f"{test}: failed"
    expected = actual = "see attached logs"
    evidence: list[str] = []

    cls = artifact_dir / "classification.json"
    if cls.exists():
        data = json.loads(cls.read_text())
        c, join = data["classifier"], data["join"]
        expected = f"join stops at `{' or '.join(data['expected'])}`"
        actual = (f"classifier: `{c['stage']}` ({c['summary']}); "
                  f"harness: `{join.get('failed_stage') or 'success'}`")
        test = data["case"]
        title = f"{data['case']}: classifier says {c['stage']}, expected {'/'.join(data['expected'])}"
        evidence = [f"- frame #{f['no']} {f['kind']} {f['src']} -> {f['dst']}"
                    + (f" status={f['status']}" if f.get("status") is not None else "")
                    + (f" reason={f['reason']}" if f.get("reason") is not None else "")
                    for f in c.get("evidence", [])]
    perf = artifact_dir / "iperf.json"
    if perf.exists():
        data = json.loads(perf.read_text())
        r = data["iperf"]
        title = f"{test}: {r['direction']} {r['mbps']} Mbps" + (f" ({r['error']})" if r["error"] else "")
        actual = f"{r['mbps']} Mbps, retransmits {r['retransmits']}, error {r['error']}"

    files = sorted(p.relative_to(artifact_dir).as_posix() for p in artifact_dir.rglob("*") if p.is_file())
    env = {"host": platform.node(), "kernel": platform.release(), **_software()}

    lines += [f"# {title}", "",
              "**Labels (proposed):** `new`, `sev:3` (triage decides)", "",
              "## Steps to reproduce",
              "1. `sudo lab/setup_lab.sh`",
              f"2. `sudo -E .venv/bin/pytest -m lab -k \"{test}\" -v`", "",
              "## Expected", expected, "",
              "## Actual", actual, ""]
    if evidence:
        lines += ["## Evidence (last frames the classifier used)", *evidence, ""]
    lines += ["## Attachments", *[f"- `{artifact_dir.as_posix()}/{f}`" for f in files], "",
              "## Environment", *[f"- {k}: {v}" for k, v in env.items()], "",
              "## Isolation notes", "- Stage located by: classifier (air) vs harness (client log).",
              "- Is it the product, the lab, or the test's expectation? Say which and why.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("artifact_dir", type=Path)
    ap.add_argument("-o", "--out", type=Path, help="write the draft here instead of stdout")
    args = ap.parse_args(argv)
    text = draft(args.artifact_dir)
    if args.out:
        args.out.write_text(text)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
