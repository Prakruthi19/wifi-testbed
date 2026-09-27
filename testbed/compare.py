"""Regression report: compare two pytest junit.xml files and list what changed.

    .venv/bin/python -m testbed.compare reports/baseline/junit.xml reports/junit.xml

Keep a copy of a good run's junit.xml as the baseline (e.g. cp -r reports reports/baseline).
Exit code 1 when anything that passed before fails now.
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("before", type=Path)
    ap.add_argument("after", type=Path)
    args = ap.parse_args(argv)
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
