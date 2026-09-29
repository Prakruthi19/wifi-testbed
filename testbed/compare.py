"""Regression report: compare two pytest junit.xml files and list what changed.

    .venv/bin/python -m testbed.compare reports/baseline/junit.xml reports/junit.xml

Keep a copy of a good run's junit.xml as the baseline (e.g. cp -r reports reports/baseline).
Exit code 1 when anything that passed before fails now.

    .venv/bin/python -m testbed.compare --consistency reports/runs/run-*.xml

lists tests whose outcome changes between repeated runs (see lab/repeat.sh).
"""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path


def outcomes(junit: Path) -> dict[str, str]:
    """{test id: "passed" | "failed" | "error" | "skipped"} from a junit.xml."""
    out = {}
    for case in ET.parse(junit).getroot().iter("testcase"):
        name = f"{case.get('classname')}::{case.get('name')}"
        if case.find("failure") is not None:
            out[name] = "failed"
        elif case.find("error") is not None:
            out[name] = "error"
        elif case.find("skipped") is not None:
            out[name] = "skipped"
        else:
            out[name] = "passed"
    return out


def compare(before: dict[str, str], after: dict[str, str]) -> dict[str, list]:
    bad = ("failed", "error")
    changes = {"regressed": [], "fixed": [], "new": [], "removed": [], "other": []}
    for name in sorted(set(before) | set(after)):
        b, a = before.get(name), after.get(name)
        if b is None:
            changes["new"].append((name, a))
        elif a is None:
            changes["removed"].append((name, b))
        elif b == "passed" and a in bad:
            changes["regressed"].append((name, f"{b} -> {a}"))
        elif b in bad and a == "passed":
            changes["fixed"].append((name, f"{b} -> {a}"))
        elif a != b:
            changes["other"].append((name, f"{b} -> {a}"))
    return changes


def consistency(runs: list[dict[str, str]]) -> dict[str, list[str]]:
    """Tests whose outcome differs between repeated runs of the same suite (flaky candidates)."""
    names = sorted(set().union(*runs)) if runs else []
    return {n: [r.get(n, "missing") for r in runs] for n in names
            if len({r.get(n, "missing") for r in runs}) > 1}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("before", type=Path)
    ap.add_argument("after", type=Path, nargs="+",
                    help="one junit.xml to compare against, or several with --consistency")
    ap.add_argument("--consistency", action="store_true",
                    help="treat all files as repeats of one suite and list tests that flip")
    args = ap.parse_args(argv)
    if args.consistency:
        runs = [outcomes(p) for p in [args.before, *args.after]]
        flips = consistency(runs)
        total = len(set().union(*runs))
        print(f"{len(runs)} runs, {total} tests, {len(flips)} inconsistent")
        for name, seq in flips.items():
            print(f"  {name}  {' '.join(seq)}")
        return 1 if flips else 0
    args.after = args.after[0]
    before, after = outcomes(args.before), outcomes(args.after)
    changes = compare(before, after)
    print(f"before: {sum(v == 'passed' for v in before.values())}/{len(before)} passed   "
          f"after: {sum(v == 'passed' for v in after.values())}/{len(after)} passed")
    for section, rows in changes.items():
        if rows:
            print(f"\n{section.upper()} ({len(rows)})")
            for name, what in rows:
                print(f"  {name}  {what}")
    return 1 if changes["regressed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
