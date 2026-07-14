import json
import datetime

with open("results.json", encoding="utf-8") as f:
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

try:
    display_date = datetime.date.fromisoformat(run_time.split()[0]).strftime("%d %B %Y").lstrip("0")
except Exception:
    display_date = run_time.split()[0]


def fmt(v):
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        return f"{v:,.2f}"
    return str(v)


def numeric_values(values: dict):
    return [(k, v) for k, v in values.items() if isinstance(v, (int, float)) and not isinstance(v, bool)]


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


STATUS_DOT = {
    "green": "var(--hypermint)",
    "red": "var(--highvolt)",
    "amber": "var(--warn)",
    "pending": "var(--ultraviolet)",
    "manual": "var(--sonic-blue)",
    "error": "var(--highvolt)",
}

BADGE_LABEL = {
    "green": "PASS",
    "red": "FAIL",
    "amber": "WARN",
    "pending": "PENDING",
    "manual": "MANUAL",
    "error": "ERROR",
}


def check_row(check: dict) -> str:
    status = check.get("status", "green")
    title  = check.get("check", "")
    values = check.get("values", {})
    flags  = check.get("flags",  [])
    note   = check.get("note",   "")
    nums   = numeric_values(values)

    headline = ""
    if len(nums) >= 2:
        headline = f"<strong>{fmt(nums[0][1])}</strong><span class='vs'>/ {fmt(nums[1][1])}</span>"
    elif len(nums) == 1:
        headline = f"<strong>{fmt(nums[0][1])}</strong>"

    detail = ""
    if values:
        detail += kv_table(values)
    if note:
        detail += f'<p class="note">{note}</p>'
    detail += flag_list(flags)

    has_detail = bool(detail.strip())

    return f"""
    <details class="check-row {'has-flags' if flags else ''}" {"open" if flags else ""}>
      <summary>
        <span class="row-dot" style="background:{STATUS_DOT.get(status, '#999')}"></span>
        <span class="row-title">{title}</span>
        <span class="row-headline">{headline}</span>
        <span class="badge {status}">{BADGE_LABEL.get(status, status.upper())}</span>
        {'<span class="chevron">&rsaquo;</span>' if has_detail else ''}
      </summary>
      {f'<div class="row-detail">{detail}</div>' if has_detail else ''}
    </details>"""


def note_row(check: dict) -> str:
    status = check.get("status", "manual")
    title  = check.get("check", "")
    note   = check.get("note", "")
    return f"""
    <div class="check-row static">
      <span class="row-dot" style="background:{STATUS_DOT.get(status, '#999')}"></span>
      <span class="row-title">{title}</span>
      <span class="row-note">{note}</span>
      <span class="badge {status}">{BADGE_LABEL.get(status, status.upper())}</span>
    </div>"""


auto_rows    = "\n      ".join(check_row(c) for c in automated)
pending_rows = "\n      ".join(note_row(c) for c in pending)
manual_rows  = "\n      ".join(note_row(c) for c in manual)

attention = [c for c in automated if c.get("status") in ("red", "amber") and c.get("flags")]
attention_html = "".join(
    f'<li><span class="row-dot" style="background:{STATUS_DOT.get(c["status"])}"></span>'
    f'<strong>{c["check"]}</strong> &mdash; {c["flags"][0]}</li>'
    for c in attention
) or '<li class="all-clear">No flags on automated checks.</li>'

html = f"""<!DOCTYPE html>
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

    --warn:       #f5c400;
    --warn-text:  #3d2f00;

    --page-bg:    #f2f3f5;
    --panel-bg:   #ffffff;
    --panel-border: #e3e5e9;
    --text-dark:  #14151a;
    --text-muted: #6c6f78;

    --card-radius: 10px;
    --font-header: 'At Hauss Std Retina', 'Helvetica Neue', Helvetica, Arial, sans-serif;
    --font-body:   'Helvetica Now', 'Helvetica Neue', Helvetica, Arial, sans-serif;
  }}

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    font-family: var(--font-body);
    background: var(--page-bg);
    color: var(--text-dark);
    min-height: 100vh;
  }}

  /* ── Top bar ── */
  .topbar {{
    background: var(--panel-bg);
    border-bottom: 1px solid var(--panel-border);
    padding: 18px 32px 0;
  }}
  .topbar-row {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 12px;
    padding-bottom: 16px;
  }}
  .brand {{
    display: flex;
    align-items: center;
    gap: 14px;
  }}
  .brand-mark {{
    background: var(--inkcore);
    color: var(--zero-white);
    font-family: var(--font-header);
    font-weight: 700;
    font-size: 0.95rem;
    padding: 6px 14px;
    border-radius: 6px;
  }}
  .brand-title {{
    font-family: var(--font-header);
    font-weight: 700;
    font-size: 1.3rem;
    letter-spacing: -0.01em;
  }}
  .topbar-right {{
    display: flex;
    align-items: center;
    gap: 14px;
  }}
  .refreshed {{
    font-size: 0.78rem;
    color: var(--text-muted);
    display: flex;
    align-items: center;
    gap: 6px;
  }}
  .refreshed-dot {{
    width: 7px; height: 7px; border-radius: 50%;
    background: var(--hypermint);
  }}
  .overall-pill {{
    font-family: var(--font-header);
    font-weight: 700;
    font-size: 0.72rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    padding: 6px 14px;
    border-radius: 999px;
  }}
  .overall-pill.green {{ background: rgba(19,244,96,0.15); color: #0a7a35; }}
  .overall-pill.red   {{ background: rgba(244,70,16,0.12); color: var(--highvolt); }}
  .overall-pill.amber {{ background: rgba(245,196,0,0.15); color: #8a6d00; }}

  /* ── Tabs ── */
  .tabnav {{
    display: flex;
    gap: 28px;
    overflow-x: auto;
  }}
  .tab-btn {{
    background: none;
    border: none;
    font-family: var(--font-body);
    font-weight: 700;
    font-size: 0.92rem;
    color: var(--text-muted);
    padding: 10px 2px 12px;
    cursor: pointer;
    border-bottom: 2px solid transparent;
    white-space: nowrap;
  }}
  .tab-btn.active {{
    color: var(--highvolt);
    border-bottom-color: var(--highvolt);
  }}
  .tab-btn:hover {{ color: var(--text-dark); }}
  .tab-btn.active:hover {{ color: var(--highvolt); }}

  main {{ padding: 28px 32px 48px; max-width: 1400px; margin: 0 auto; }}
  .tab-panel {{ display: none; }}
  .tab-panel.active {{ display: block; }}

  /* ── Hero KPI tiles ── */
  .hero-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 14px;
    margin-bottom: 28px;
  }}
  .tile {{
    background: var(--inkcore);
    color: var(--zero-white);
    border-radius: var(--card-radius);
    padding: 20px 22px;
  }}
  .tile-label {{
    font-family: var(--font-header);
    font-size: 0.68rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: rgba(255,255,255,0.45);
    margin-bottom: 10px;
  }}
  .tile-value {{
    font-family: var(--font-header);
    font-size: 1.9rem;
    font-weight: 700;
    letter-spacing: -0.01em;
  }}
  .tile-value.accent {{ color: var(--highvolt); }}
  .tile-value.good   {{ color: var(--hypermint); }}
  .tile-sub {{
    font-size: 0.78rem;
    color: rgba(255,255,255,0.4);
    margin-top: 6px;
  }}

  /* ── Attention list (overview) ── */
  .attention-card {{
    background: var(--panel-bg);
    border: 1px solid var(--panel-border);
    border-radius: var(--card-radius);
    padding: 18px 22px;
    margin-bottom: 28px;
  }}
  .attention-card h3 {{
    font-family: var(--font-header);
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-muted);
    margin-bottom: 12px;
  }}
  .attention-card ul {{ list-style: none; display: flex; flex-direction: column; gap: 8px; }}
  .attention-card li {{ display: flex; align-items: center; gap: 10px; font-size: 0.85rem; }}
  .attention-card .row-dot {{ flex-shrink: 0; }}
  .attention-card .all-clear {{ color: var(--text-muted); font-style: italic; }}

  /* ── Numbered section cards ── */
  .section-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
    gap: 20px;
    align-items: start;
  }}
  .section-card {{
    background: var(--panel-bg);
    border: 1px solid var(--panel-border);
    border-left: 4px solid var(--section-accent, var(--highvolt));
    border-radius: var(--card-radius);
    overflow: hidden;
  }}
  .section-header {{
    display: flex;
    align-items: baseline;
    gap: 14px;
    padding: 20px 22px 14px;
  }}
  .section-num {{
    font-family: var(--font-header);
    font-size: 2.2rem;
    font-weight: 700;
    color: #e5e6e9;
    line-height: 1;
  }}
  .section-title {{
    font-family: var(--font-header);
    font-size: 1.05rem;
    font-weight: 700;
  }}
  .section-body {{ padding: 0 8px 8px; }}

  .check-row {{
    display: block;
    border-top: 1px solid var(--panel-border);
  }}
  .check-row summary {{
    list-style: none;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 14px;
    cursor: pointer;
  }}
  .check-row summary::-webkit-details-marker {{ display: none; }}
  .check-row.static {{
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 14px;
  }}
  .row-dot {{ width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }}
  .row-title {{ font-size: 0.88rem; font-weight: 600; flex: 1; min-width: 0; }}
  .row-headline {{ font-size: 0.9rem; color: var(--text-dark); white-space: nowrap; }}
  .row-headline .vs {{ color: var(--text-muted); font-weight: 400; margin-left: 3px; }}
  .row-note {{ font-size: 0.78rem; color: var(--text-muted); text-align: right; flex: 1; }}
  .chevron {{ color: var(--text-muted); font-size: 1.1rem; transition: transform 0.15s; }}
  .check-row[open] .chevron {{ transform: rotate(90deg); }}

  .row-detail {{ padding: 0 14px 16px 32px; }}

  .badge {{
    padding: 3px 9px;
    border-radius: 3px;
    font-size: 0.62rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    flex-shrink: 0;
    font-family: var(--font-header);
  }}
  .badge.green   {{ background: rgba(19,244,96,0.15);  color: #0a7a35; }}
  .badge.red     {{ background: var(--highvolt);   color: var(--zero-white); }}
  .badge.amber   {{ background: var(--warn);       color: var(--warn-text); }}
  .badge.manual  {{ background: rgba(45,64,233,0.12); color: var(--sonic-blue); }}
  .badge.pending {{ background: rgba(82,190,192,0.15); color: #1c7577; }}
  .badge.error   {{ background: var(--highvolt);   color: var(--zero-white); }}

  table.kv {{ width: 100%; border-collapse: collapse; margin-top: 6px; }}
  table.kv td {{ padding: 4px 6px; vertical-align: top; }}
  table.kv td.key {{
    color: var(--text-muted);
    white-space: nowrap;
    padding-right: 16px;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }}
  table.kv td strong {{ color: var(--text-dark); font-weight: 600; font-size: 0.85rem; }}

  ul.flags {{ list-style: none; margin-top: 10px; display: flex; flex-direction: column; gap: 6px; }}
  ul.flags li {{
    background: rgba(244,70,16,0.06);
    border-left: 3px solid var(--highvolt);
    padding: 7px 12px;
    border-radius: 3px;
    color: #9c3414;
    font-size: 0.78rem;
    line-height: 1.4;
  }}

  .note {{ color: #1c7577; font-style: italic; margin: 6px 0; font-size: 0.78rem; }}

  /* ── Footer bar ── */
  .footer-bar {{
    background: var(--inkcore);
    color: rgba(255,255,255,0.6);
    padding: 16px 32px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
    font-size: 0.75rem;
    letter-spacing: 0.02em;
  }}
  .footer-bar .footer-dot {{
    display: inline-block;
    width: 6px; height: 6px;
    border-radius: 50%;
    background: var(--hypermint);
    margin-right: 8px;
    vertical-align: middle;
  }}

  @media (max-width: 640px) {{
    .topbar {{ padding: 14px 16px 0; }}
    main {{ padding: 20px 16px 40px; }}
    .brand-title {{ font-size: 1.05rem; }}
    .footer-bar {{ padding: 14px 16px; flex-direction: column; align-items: flex-start; }}
  }}
</style>
</head>
<body>

<div class="topbar">
  <div class="topbar-row">
    <div class="brand">
      <span class="brand-mark">Spot&trade;</span>
      <span class="brand-title">DDA Daily BI Checks</span>
    </div>
    <div class="topbar-right">
      <span class="overall-pill {overall_cls}">{overall_label}</span>
      <span class="refreshed"><span class="refreshed-dot"></span>{display_date} &middot; Data as of {run_date} &middot; Snowflake</span>
    </div>
  </div>
  <div class="tabnav">
    <button class="tab-btn active" data-tab="overview">Overview</button>
    <button class="tab-btn" data-tab="automated">Automated Checks</button>
    <button class="tab-btn" data-tab="pending">Pending Access</button>
    <button class="tab-btn" data-tab="manual">Manual Checks</button>
  </div>
</div>

<main>

  <section class="tab-panel active" id="tab-overview">
    <div class="hero-grid">
      <div class="tile">
        <div class="tile-label">Automated Checks</div>
        <div class="tile-value {'accent' if failed else 'good'}">{passed}/{len(automated)}</div>
        <div class="tile-sub">passed</div>
      </div>
      <div class="tile">
        <div class="tile-label">Failed</div>
        <div class="tile-value {'accent' if failed else 'good'}">{failed}</div>
        <div class="tile-sub">{'requires attention' if failed else 'none'}</div>
      </div>
      <div class="tile">
        <div class="tile-label">Warnings</div>
        <div class="tile-value">{warnings}</div>
        <div class="tile-sub">{'review flagged items' if warnings else 'none'}</div>
      </div>
      <div class="tile">
        <div class="tile-label">Pending MCP Access</div>
        <div class="tile-value">{len(pending)}</div>
        <div class="tile-sub">awaiting grant</div>
      </div>
      <div class="tile">
        <div class="tile-label">Manual Verifications</div>
        <div class="tile-value">{len(manual)}</div>
        <div class="tile-sub">cross-check dashboards</div>
      </div>
    </div>

    <div class="attention-card">
      <h3>Needs Attention</h3>
      <ul>
        {attention_html}
      </ul>
    </div>
  </section>

  <section class="tab-panel" id="tab-automated">
    <div class="section-card" style="--section-accent: var(--highvolt);">
      <div class="section-header">
        <span class="section-num">01</span>
        <span class="section-title">Automated Checks &mdash; Snowflake</span>
      </div>
      <div class="section-body">
        {auto_rows}
      </div>
    </div>
  </section>

  <section class="tab-panel" id="tab-pending">
    <div class="section-card" style="--section-accent: var(--ultraviolet);">
      <div class="section-header">
        <span class="section-num">02</span>
        <span class="section-title">Pending MCP Access</span>
      </div>
      <div class="section-body">
        {pending_rows}
      </div>
    </div>
  </section>

  <section class="tab-panel" id="tab-manual">
    <div class="section-card" style="--section-accent: var(--sonic-blue);">
      <div class="section-header">
        <span class="section-num">03</span>
        <span class="section-title">Manual Checks &mdash; Telco / Dashboards</span>
      </div>
      <div class="section-body">
        {manual_rows}
      </div>
    </div>
  </section>

</main>

<div class="footer-bar">
  <span><span class="footer-dot"></span>Uconnect DDA &mdash; Snowflake UCONNECT_DW</span>
  <span>Refreshed daily 07:00 SAST &mdash; GitHub Actions</span>
</div>

<script>
  document.querySelectorAll('.tab-btn').forEach(function(btn) {{
    btn.addEventListener('click', function() {{
      document.querySelectorAll('.tab-btn').forEach(function(b) {{ b.classList.remove('active'); }});
      document.querySelectorAll('.tab-panel').forEach(function(p) {{ p.classList.remove('active'); }});
      btn.classList.add('active');
      document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
    }});
  }});
</script>

</body>
</html>"""

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html)

print(f"build_dashboard.py complete — index.html written ({run_date})")
