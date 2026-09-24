"""Matrix view for the HTML report: rows = AP configs, columns = clients."""

from __future__ import annotations

import html
from collections import OrderedDict

CELL_STYLE = {
    "ok": "background:#d7f5dd",
    "bug": "background:#f8d0d0",
    "flaky": "background:#fbe8b6",
    "noncompliant": "background:#e3e0f5",
}


def cell_state(result: dict) -> str:
    exp, rate = result["expected"], result["pass_rate"]
    if exp == "noncompliant":
        return "noncompliant"
    if 0 < rate < 1:
        return "flaky"
    if (exp == "pass") == (rate == 1):
        return "ok"
    return "bug"


def matrix_html(results: list[dict]) -> str:
    """`results` items: row, col, pass_rate, median_join_ms, expected, failed_stages."""
    if not results:
        return ""
    cols = list(OrderedDict.fromkeys(r["col"] for r in results))
    grid: dict[str, dict[str, dict]] = OrderedDict()
    for r in results:
        grid.setdefault(r["row"], {})[r["col"]] = r

    out = ['<table class="matrix" style="border-collapse:collapse;font-size:13px">',
           "<tr><th style='text-align:left;padding:4px 8px'>AP config</th>"]
    out += [f"<th style='padding:4px 8px'>{html.escape(c)}</th>" for c in cols]
    out.append("</tr>")
    for row, cells in grid.items():
        out.append(f"<tr><td style='padding:4px 8px'>{html.escape(row)}</td>")
        for c in cols:
            r = cells.get(c)
            if not r:
                out.append("<td></td>")
                continue
            state = cell_state(r)
            median = f"{r['median_join_ms']:.0f} ms" if r.get("median_join_ms") else "&ndash;"
            detail = f"expected {r['expected']}"
            if r.get("failed_stages"):
                detail += f"; failed at {', '.join(r['failed_stages'])}"
            out.append(
                f"<td title='{html.escape(detail)}' style='{CELL_STYLE[state]};padding:4px 8px;"
                f"text-align:center;border:1px solid #ccc'>{r['pass_rate']:.0%}<br>"
                f"<small>{median}</small></td>")
        out.append("</tr>")
    out.append("</table>")
    legend = " ".join(f"<span style='{s};padding:2px 6px'>{k}</span>" for k, s in CELL_STYLE.items())
    out.append(f"<p style='font-size:12px'>Cell = pass rate / median join time. {legend}</p>")
    return "\n".join(out)
