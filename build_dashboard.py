import json

with open("results.json") as f:
    data = json.load(f)

automated = data.get("automated", [])
pending   = data.get("pending",   [])
manual    = data.get("manual",    [])
errors    = data.get("errors",    [])

passed   = sum(1 for c in automated if c["status"] == "green")
failed   = sum(1 for c in automated if c["status"] == "red")
warnings = sum(1 for c in automated if c["status"] == "amber")

if failed:
    overall_cls   = "red"
    overall_label = "FAILURES DETECTED"
elif warnings:
    overall_cls   = "amber"
    overall_label = "WARNINGS"
else:
    overall_cls   = "green"
    overall_label = "ALL CHECKS PASSED"

run_date = data.get("run_date", "")
run_time = data.get("run_time", "")

# Format display date as "30 June 2026" from run_time (e.g. "2026-06-30 — ...")
import datetime
try:
    display_date = datetime.date.fromisoformat(run_time.split(" — ")[0]).strftime("%-d %B %Y")
except Exception:
    display_date = run_time.split(" — ")[0]


def fmt(v):
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        return f"{v:,.2f}"
    return str(v)


def kv_table(values: dict) -> str:
    rows = "".join(
        f"<tr><td class='key'>{k}</td><td><strong>{fmt(v)}</strong></td></tr>"
        for k, v in values.items()
    )
    return f"<table class='kv'>{rows}</table>"


def flag_list(flags: list) -> str:
    if not flags:
        return ""
    items = "".join(f"<li>{f}</li>" for f in flags)
    return f'<ul class="flags">{items}</ul>'


def card(check: dict) -> str:
    status = check.get("status", "green")
    title  = check.get("check", "")
    values = check.get("values", {})
    flags  = check.get("flags",  [])
    note   = check.get("note",   "")

    badge_label = {
        "green":   "PASS",
        "red":     "FAIL",
        "amber":   "WARN",
        "pending": "PENDING",
        "manual":  "MANUAL",
        "error":   "ERROR",
    }.get(status, status.upper())

    body = ""
    if note:
        body += f'<p class="note">{note}</p>'
    if values:
        body += kv_table(values)
    body += flag_list(flags)

    return f"""
    <div class="card {status}">
        <div class="card-header">
            <span class="badge {status}">{badge_label}</span>
            <span class="card-title">{title}</span>
        </div>
        <div class="card-body">{body}</div>
    </div>"""


auto_cards    = "\n  ".join(card(c) for c in automated)
pending_cards = "\n  ".join(card(c) for c in pending)
manual_cards  = "\n  ".join(card(c) for c in manual)

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DDA Daily BI Checks — {display_date}</title>
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

  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
    gap: 14px;
  }}

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
      <h1>DDA <span>Daily BI</span> Checks &mdash; {display_date}</h1>
      <div class="meta">Data as of {run_date} &nbsp;&middot;&nbsp; Snowflake</div>
    </div>
    <div class="overall {overall_cls}">
      <span class="overall-dot"></span>
      {overall_label}
    </div>
  </div>
</header>

<div class="summary-bar">
  <span class="summary-pill green">{passed} Passed</span>
  <span class="summary-pill red">{failed} Failed</span>
  <span class="summary-pill amber">{warnings} Warnings</span>
  <span class="summary-pill pending">{len(pending)} Pending</span>
  <span class="summary-pill gray">{len(manual)} Manual</span>
</div>

<h2>Automated Checks — Snowflake</h2>
<div class="grid">
  {auto_cards}
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
  <span>Refreshed daily 07:00 SAST &mdash; GitHub Actions</span>
</footer>

</body>
</html>"""

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html)

print(f"build_dashboard.py complete — index.html written ({run_date})")
