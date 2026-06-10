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
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Helvetica+Neue:wght@400;500;700&display=swap" rel="stylesheet">
<style>
  /* ── Spot CI 2025 — THERMOLINE ── */
  :root {{
    --inkcore:    #0e0e0e;
    --zero-white: #ffffff;
    --hypermint:  #13f460;
    --sonic-blue: #2d40e9;
    --ultraviolet:#52bec0;
    --highvolt:   #f44610;

    /* semantic mappings */
    --pass:       var(--hypermint);
    --pass-text:  #0a3d1f;
    --fail:       var(--highvolt);
    --fail-text:  #fff;
    --warn:       #f5c400;
    --warn-text:  #3d2f00;
    --pending:    var(--ultraviolet);
    --pending-text: #0c2e2e;
    --manual:     var(--sonic-blue);
    --manual-text:#fff;
    --error:      var(--highvolt);

    --card-radius: 8px;
    --font-header: 'At Hauss Std Retina', 'Helvetica Neue', Helvetica, Arial, sans-serif;
    --font-body:   'Helvetica Now', 'Helvetica Neue', Helvetica, Arial, sans-serif;
  }}

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    font-family: var(--font-body);
    background: var(--inkcore);
    color: var(--zero-white);
    padding: 32px 28px;
    min-height: 100vh;
  }}

  /* ── HEADER ── */
  header {{
    display: flex;
    flex-direction: column;
    gap: 10px;
    border-bottom: 1px solid rgba(255,255,255,0.08);
    padding-bottom: 28px;
    margin-bottom: 28px;
  }}
  .header-top {{
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 16px;
  }}
  header h1 {{
    font-family: var(--font-header);
    font-size: 2rem;
    font-weight: 700;
    letter-spacing: -0.02em;
    color: var(--zero-white);
  }}
  header h1 span {{ color: var(--hypermint); }}
  header .meta {{
    font-size: 0.78rem;
    color: rgba(255,255,255,0.4);
    letter-spacing: 0.04em;
    text-transform: uppercase;
    margin-top: 2px;
  }}
  .overall {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 8px 18px;
    border-radius: 4px;
    font-family: var(--font-header);
    font-weight: 700;
    font-size: 0.85rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    flex-shrink: 0;
  }}
  .overall.green  {{ background: var(--hypermint); color: var(--pass-text); }}
  .overall.red    {{ background: var(--highvolt);  color: var(--zero-white); }}
  .overall.amber  {{ background: var(--warn);      color: var(--warn-text); }}
  .overall-dot {{ width: 8px; height: 8px; border-radius: 50%; background: currentColor; opacity: 0.7; }}

  /* ── SUMMARY PILLS ── */
  .summary-bar {{
    display: flex;
    gap: 10px;
    margin-bottom: 32px;
    flex-wrap: wrap;
  }}
  .summary-pill {{
    padding: 6px 16px;
    border-radius: 999px;
    font-size: 0.78rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    border: 1px solid;
  }}
  .summary-pill.green   {{ background: rgba(19,244,96,0.12);  color: var(--hypermint);  border-color: rgba(19,244,96,0.25); }}
  .summary-pill.red     {{ background: rgba(244,70,16,0.12);  color: #ff7d5c;           border-color: rgba(244,70,16,0.3); }}
  .summary-pill.amber   {{ background: rgba(245,196,0,0.12);  color: #f5c400;           border-color: rgba(245,196,0,0.25); }}
  .summary-pill.gray    {{ background: rgba(255,255,255,0.06); color: rgba(255,255,255,0.5); border-color: rgba(255,255,255,0.1); }}
  .summary-pill.pending {{ background: rgba(82,190,192,0.12); color: var(--ultraviolet); border-color: rgba(82,190,192,0.25); }}

  /* ── SECTION HEADINGS ── */
  h2 {{
    font-family: var(--font-header);
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: rgba(255,255,255,0.3);
    margin: 32px 0 14px;
    padding-bottom: 8px;
    border-bottom: 1px solid rgba(255,255,255,0.06);
  }}

  /* ── GRID ── */
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
    gap: 14px;
  }}

  /* ── CARDS ── */
  .card {{
    border-radius: var(--card-radius);
    border: 1px solid rgba(255,255,255,0.08);
    background: rgba(255,255,255,0.04);
    overflow: hidden;
    transition: border-color 0.15s, background 0.15s;
  }}
  .card:hover {{ background: rgba(255,255,255,0.07); border-color: rgba(255,255,255,0.15); }}

  .card.green  {{ border-color: rgba(19,244,96,0.3);  background: rgba(19,244,96,0.05); }}
  .card.red    {{ border-color: rgba(244,70,16,0.4);  background: rgba(244,70,16,0.06); }}
  .card.amber  {{ border-color: rgba(245,196,0,0.3);  background: rgba(245,196,0,0.05); }}
  .card.pending {{ border-color: rgba(82,190,192,0.3); background: rgba(82,190,192,0.05); }}
  .card.manual {{ border-color: rgba(45,64,233,0.4);  background: rgba(45,64,233,0.06); }}
  .card.error  {{ border-color: rgba(244,70,16,0.5);  background: rgba(244,70,16,0.08); }}

  .card-header {{
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 16px;
    border-bottom: 1px solid rgba(255,255,255,0.06);
  }}
  .card-title {{
    font-family: var(--font-header);
    font-weight: 600;
    font-size: 0.9rem;
    color: var(--zero-white);
    letter-spacing: 0.01em;
  }}
  .card-body {{
    padding: 14px 16px;
    font-size: 0.82rem;
    color: rgba(255,255,255,0.75);
  }}

  /* ── BADGES ── */
  .badge {{
    padding: 3px 10px;
    border-radius: 3px;
    font-size: 0.65rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    flex-shrink: 0;
    font-family: var(--font-header);
  }}
  .badge.green   {{ background: var(--hypermint);  color: var(--pass-text); }}
  .badge.red     {{ background: var(--highvolt);   color: var(--zero-white); }}
  .badge.amber   {{ background: var(--warn);       color: var(--warn-text); }}
  .badge.manual  {{ background: var(--sonic-blue); color: var(--zero-white); }}
  .badge.pending {{ background: var(--ultraviolet);color: var(--inkcore); }}
  .badge.error   {{ background: var(--highvolt);   color: var(--zero-white); }}

  /* ── KV TABLE ── */
  table.kv {{ width: 100%; border-collapse: collapse; margin-top: 8px; }}
  table.kv td {{ padding: 5px 6px; vertical-align: top; }}
  table.kv td.key {{
    color: rgba(255,255,255,0.35);
    white-space: nowrap;
    padding-right: 16px;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }}
  table.kv td strong {{ color: var(--zero-white); font-weight: 600; }}

  /* ── DETAIL TABLE ── */
  table.detail {{ width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 0.78rem; }}
  table.detail th {{
    background: rgba(255,255,255,0.06);
    padding: 6px 8px;
    text-align: left;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-size: 0.68rem;
    color: rgba(255,255,255,0.5);
  }}
  table.detail td {{ padding: 6px 8px; border-top: 1px solid rgba(255,255,255,0.05); color: rgba(255,255,255,0.75); }}
  table.detail tr.row-red td {{ background: rgba(244,70,16,0.08); }}

  /* ── FLAGS ── */
  ul.flags {{ list-style: none; margin-top: 12px; display: flex; flex-direction: column; gap: 6px; }}
  ul.flags li {{
    background: rgba(244,70,16,0.1);
    border-left: 3px solid var(--highvolt);
    padding: 7px 12px;
    border-radius: 3px;
    color: #ffb8a0;
    font-size: 0.8rem;
    line-height: 1.4;
  }}

  .note {{ color: var(--ultraviolet); font-style: italic; margin-bottom: 6px; font-size: 0.8rem; }}
  .error-msg {{ color: #ff7d5c; font-weight: 600; margin-bottom: 6px; }}

  /* ── FOOTER ── */
  footer {{
    margin-top: 48px;
    padding-top: 20px;
    border-top: 1px solid rgba(255,255,255,0.06);
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
    font-size: 0.72rem;
    color: rgba(255,255,255,0.25);
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }}
  .footer-dot {{
    display: inline-block;
    width: 6px; height: 6px;
    border-radius: 50%;
    background: var(--hypermint);
    margin-right: 8px;
    vertical-align: middle;
  }}

  @media (max-width: 640px) {{
    .grid {{ grid-template-columns: 1fr; }}
    body {{ padding: 20px 16px; }}
    header h1 {{ font-size: 1.5rem; }}
  }}
</style>
</head>
<body>

<header>
  <div class="header-top">
    <div>
      <h1>DDA <span>Daily BI</span> Checks</h1>
      <div class="meta">Run: {run_time} &nbsp;·&nbsp; {run_date} &nbsp;·&nbsp; Snowflake MCP</div>
    </div>
    <div class="overall {overall}">
      <span class="overall-dot"></span>
      {overall_label}
    </div>
  </div>
</header>

<div class="summary-bar">
  <span class="summary-pill green">{passes} Passed</span>
  <span class="summary-pill red">{fails} Failed</span>
  <span class="summary-pill amber">{warns} Warnings</span>
  <span class="summary-pill pending">{len(pending)} Pending</span>
  <span class="summary-pill gray">{len(manual)} Manual</span>
</div>

<h2>Automated Checks — Snowflake</h2>
<div class="grid">
  {auto_cards}
  {error_cards}
</div>

<h2>Pending MCP Access</h2>
<div class="grid">
  {pending_cards}
</div>

<h2>Manual Checks — Telco / Dashboards</h2>
<div class="grid">
  {manual_cards}
</div>

<footer>
  <span><span class="footer-dot"></span>Uconnect DDA &mdash; Snowflake UCONNECT_DW</span>
  <span>Refreshed daily 07:00 SAST &mdash; Claude MCP</span>
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
