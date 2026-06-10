"""
Reads results.json and renders dashboard.html.
Run after checks.py has produced results.json.
"""

import json
import sys
from pathlib import Path

RESULTS_FILE = Path("results.json")
OUTPUT_FILE = Path("index.html")


def status_badge(status):
    if status == "green":
        return '<span class="badge green">PASS</span>'
    elif status == "red":
        return '<span class="badge red">FAIL</span>'
    elif status == "amber":
        return '<span class="badge amber">WARN</span>'
    elif status == "manual":
        return '<span class="badge manual">MANUAL</span>'
    elif status == "pending":
        return '<span class="badge pending">PENDING</span>'
    elif status == "error":
        return '<span class="badge error">ERROR</span>'
    return '<span class="badge">UNKNOWN</span>'


def render_flags(flags):
    if not flags:
        return ""
    items = "".join(f"<li>{f}</li>" for f in flags)
    return f'<ul class="flags">{items}</ul>'


def render_kv(d, indent=0):
    if not d:
        return ""
    rows = []
    for k, v in d.items():
        if isinstance(v, list):
            sub = render_list_of_dicts(v) if v and isinstance(v[0], dict) else f"<code>{v}</code>"
            rows.append(f"<tr><td class='key'>{k}</td><td>{sub}</td></tr>")
        elif isinstance(v, dict):
            rows.append(f"<tr><td class='key'>{k}</td><td>{render_kv(v)}</td></tr>")
        else:
            display = f"{v:,}" if isinstance(v, (int, float)) and v is not None else v
            rows.append(f"<tr><td class='key'>{k}</td><td><strong>{display}</strong></td></tr>")
    return f"<table class='kv'>{''.join(rows)}</table>"


def render_list_of_dicts(items):
    if not items:
        return ""
    cols = list(items[0].keys())
    header = "".join(f"<th>{c}</th>" for c in cols)
    body_rows = []
    for item in items:
        row_status = item.get("status", "")
        cls = f"row-{row_status}" if row_status else ""
        cells = []
        for c in cols:
            val = item[c]
            if c == "status":
                cells.append(f"<td>{status_badge(val)}</td>")
            elif c == "flags":
                cells.append(f"<td>{render_flags(val)}</td>")
            elif isinstance(val, (int, float)) and val is not None:
                cells.append(f"<td>{val:,}</td>")
            else:
                cells.append(f"<td>{val}</td>")
        body_rows.append(f"<tr class='{cls}'>{''.join(cells)}</tr>")
    return f"<table class='detail'><thead><tr>{header}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def render_check_card(check):
    name = check.get("check", "Unknown")
    status = check.get("status", "unknown")
    flags = check.get("flags", [])
    values = check.get("values", {})
    note = check.get("note", "")
    error = check.get("error", "")

    body = ""
    if note:
        body += f'<p class="note">{note}</p>'
    if error:
        body += f'<p class="error-msg">Error: {error}</p>'
    if values:
        body += render_kv(values)
    body += render_flags(flags)

    return f"""
    <div class="card {status}">
        <div class="card-header">
            {status_badge(status)}
            <span class="card-title">{name}</span>
        </div>
        <div class="card-body">{body}</div>
    </div>
    """


def build_html(data):
    run_date = data.get("run_date", "unknown")
    run_time = data.get("run_time", "unknown")
    automated = data.get("automated", [])
    pending = data.get("pending", [])
    manual = data.get("manual", [])
    errors = data.get("errors", [])

    total = len(automated) + len(errors)
    fails = sum(1 for c in automated if c.get("status") == "red") + len(errors)
    warns = sum(1 for c in automated if c.get("status") == "amber")
    passes = sum(1 for c in automated if c.get("status") == "green")

    overall = "green" if fails == 0 and warns == 0 else ("amber" if fails == 0 else "red")
    overall_label = "ALL CLEAR" if fails == 0 and warns == 0 else ("WARNINGS" if fails == 0 else "FAILURES DETECTED")

    auto_cards = "".join(render_check_card(c) for c in automated)
    error_cards = "".join(render_check_card({**c, "status": "error"}) for c in errors)
    pending_cards = "".join(render_check_card(c) for c in pending)
    manual_cards = "".join(render_check_card(c) for c in manual)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DDA Daily BI Checks — {run_date}</title>
<style>
  :root {{
    --green: #22c55e; --green-bg: #f0fdf4; --green-border: #bbf7d0;
    --red: #ef4444; --red-bg: #fef2f2; --red-border: #fecaca;
    --amber: #f59e0b; --amber-bg: #fffbeb; --amber-border: #fde68a;
    --manual: #6366f1; --manual-bg: #eef2ff; --manual-border: #c7d2fe;
    --pending: #d97706; --pending-bg: #fffbeb; --pending-border: #fde68a;
    --error: #dc2626; --error-bg: #fff1f2; --error-border: #fecdd3;
    --gray: #6b7280; --gray-bg: #f9fafb; --card-radius: 10px;
    --font: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: var(--font); background: #f1f5f9; color: #1e293b; padding: 24px; }}
  header {{ background: #1e293b; color: white; border-radius: var(--card-radius); padding: 24px 32px; margin-bottom: 24px; }}
  header h1 {{ font-size: 1.6rem; font-weight: 700; }}
  header .meta {{ font-size: 0.85rem; color: #94a3b8; margin-top: 4px; }}
  .overall {{ display: inline-flex; align-items: center; gap: 10px; margin-top: 16px;
    padding: 10px 20px; border-radius: 8px; font-weight: 700; font-size: 1rem; }}
  .overall.green {{ background: var(--green-bg); color: #15803d; border: 1.5px solid var(--green-border); }}
  .overall.red {{ background: var(--red-bg); color: #b91c1c; border: 1.5px solid var(--red-border); }}
  .overall.amber {{ background: var(--amber-bg); color: #92400e; border: 1.5px solid var(--amber-border); }}
  .summary-bar {{ display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }}
  .summary-pill {{ padding: 8px 18px; border-radius: 999px; font-size: 0.85rem; font-weight: 600; }}
  .summary-pill.green {{ background: var(--green-bg); color: #15803d; border: 1px solid var(--green-border); }}
  .summary-pill.red {{ background: var(--red-bg); color: #b91c1c; border: 1px solid var(--red-border); }}
  .summary-pill.amber {{ background: var(--amber-bg); color: #92400e; border: 1px solid var(--amber-border); }}
  .summary-pill.gray {{ background: var(--gray-bg); color: #374151; border: 1px solid #e5e7eb; }}
  .summary-pill.pending {{ background: var(--pending-bg); color: #92400e; border: 1px solid var(--pending-border); }}
  h2 {{ font-size: 1rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;
    color: #64748b; margin: 28px 0 12px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(420px, 1fr)); gap: 16px; }}
  .card {{ border-radius: var(--card-radius); border: 1.5px solid #e2e8f0; background: white;
    overflow: hidden; transition: box-shadow 0.15s; }}
  .card:hover {{ box-shadow: 0 4px 16px rgba(0,0,0,0.08); }}
  .card.red {{ border-color: var(--red-border); background: var(--red-bg); }}
  .card.amber {{ border-color: var(--amber-border); background: var(--amber-bg); }}
  .card.green {{ border-color: var(--green-border); background: var(--green-bg); }}
  .card.manual {{ border-color: var(--manual-border); background: var(--manual-bg); }}
  .card.pending {{ border-color: var(--pending-border); background: var(--pending-bg); }}
  .card.error {{ border-color: var(--error-border); background: var(--error-bg); }}
  .card-header {{ display: flex; align-items: center; gap: 10px; padding: 14px 16px;
    border-bottom: 1px solid rgba(0,0,0,0.06); }}
  .card-title {{ font-weight: 600; font-size: 0.95rem; }}
  .card-body {{ padding: 14px 16px; font-size: 0.85rem; }}
  .badge {{ padding: 3px 10px; border-radius: 999px; font-size: 0.72rem; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.05em; flex-shrink: 0; }}
  .badge.green {{ background: var(--green); color: white; }}
  .badge.red {{ background: var(--red); color: white; }}
  .badge.amber {{ background: var(--amber); color: white; }}
  .badge.manual {{ background: var(--manual); color: white; }}
  .badge.pending {{ background: var(--pending); color: white; }}
  .badge.error {{ background: var(--error); color: white; }}
  table.kv {{ width: 100%; border-collapse: collapse; margin-top: 8px; }}
  table.kv td {{ padding: 4px 6px; vertical-align: top; }}
  table.kv td.key {{ color: var(--gray); white-space: nowrap; padding-right: 12px; font-size: 0.8rem; }}
  table.detail {{ width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 0.8rem; }}
  table.detail th {{ background: #f1f5f9; padding: 5px 8px; text-align: left; font-weight: 600; }}
  table.detail td {{ padding: 5px 8px; border-top: 1px solid #f1f5f9; }}
  table.detail tr.row-red td {{ background: #fff5f5; }}
  ul.flags {{ list-style: none; margin-top: 10px; display: flex; flex-direction: column; gap: 5px; }}
  ul.flags li {{ background: rgba(239,68,68,0.08); border-left: 3px solid var(--red);
    padding: 6px 10px; border-radius: 4px; color: #7f1d1d; font-size: 0.82rem; }}
  .note {{ color: var(--manual); font-style: italic; margin-bottom: 6px; }}
  .error-msg {{ color: var(--error); font-weight: 600; margin-bottom: 6px; }}
  footer {{ margin-top: 40px; text-align: center; font-size: 0.78rem; color: #94a3b8; }}
  @media (max-width: 600px) {{ .grid {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>

<header>
  <h1>DDA Daily BI Checks</h1>
  <div class="meta">Run: {run_time} &nbsp;|&nbsp; Date: {run_date} &nbsp;|&nbsp; Auto-generated by GitHub Actions</div>
  <div class="overall {overall}">
    {'✓' if overall == 'green' else '✗'} &nbsp; {overall_label}
  </div>
</header>

<div class="summary-bar">
  <span class="summary-pill green">{passes} Passed</span>
  <span class="summary-pill red">{fails} Failed</span>
  <span class="summary-pill amber">{warns} Warnings</span>
  <span class="summary-pill gray">{len(manual)} Manual checks</span>
  <span class="summary-pill pending">{len(pending)} Pending MCP access</span>
</div>

<h2>Automated Checks (Snowflake)</h2>
<div class="grid">
  {auto_cards}
  {error_cards}
</div>

<h2>Pending MCP Access</h2>
<div class="grid">
  {pending_cards}
</div>

<h2>Manual Checks (Telco / Dashboards)</h2>
<div class="grid">
  {manual_cards}
</div>

<footer>
  Uconnect DDA Dashboard &mdash; refreshed daily via GitHub Actions &mdash;
  Data source: Snowflake UCONNECT_DW
</footer>

</body>
</html>"""


def main():
    if not RESULTS_FILE.exists():
        print("results.json not found — run checks.py first", file=sys.stderr)
        sys.exit(1)
    data = json.loads(RESULTS_FILE.read_text())
    html = build_html(data)
    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"Dashboard written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
