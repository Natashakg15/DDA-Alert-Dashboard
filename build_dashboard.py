import json
import re

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

import datetime
try:
    display_date = datetime.date.fromisoformat(run_time.split()[0]).strftime("%d %B %Y").lstrip("0")
except Exception:
    display_date = run_time.split()[0]


def fmt(v):
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        return f"{v:,.2f}"
    if v is None:
        return "N/A"
    return str(v)


ACRONYMS = {"mtd", "qos", "iccid", "dim", "vw", "sims", "id", "2lm", "lm"}
SMALL_WORDS = {"vs", "of", "in", "a"}


def label(key: str) -> str:
    """snake_case key -> human label, e.g. pct_mtd_vs_prev_count -> '% MTD vs Prev Count'."""
    s = re.sub(r"([a-zA-Z])(\d)", r"\1 \2", key.replace("_", " "))
    words = s.split()
    out = []
    for i, w in enumerate(words):
        lw = w.lower()
        if lw == "pct":
            out.append("%")
        elif lw in ACRONYMS:
            out.append(lw.upper())
        elif lw in SMALL_WORDS and i != 0:
            out.append(lw)
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out)


# Declarative grouping so related stats sit together instead of one long flat list.
# Any key present in a check's values but not listed here still renders, under "Other".
CHECK_GROUPS = {
    "Cell C Recharges": [
        ("Yesterday", ["yesterday_count", "yesterday_value"]),
        ("Same-Day History", ["same_day_last_month_count", "same_day_last_month_value",
                               "same_day_two_months_ago_count", "same_day_two_months_ago_value",
                               "pct_same_day_lm_vs_2lm_count", "pct_same_day_lm_vs_2lm_value"]),
        ("Month to Date", ["mtd_count", "mtd_value", "prev_mtd_count", "prev_mtd_value",
                            "pct_mtd_vs_prev_count", "pct_mtd_vs_prev_value"]),
        ("3-Month Trend", ["three_month_trend_count", "three_month_trend_value"]),
    ],
    "Sales (Last 30 Days)": [
        ("Yesterday", ["yesterday_qty", "yesterday_value"]),
        ("Same-Day History", ["same_day_last_month_qty", "same_day_last_month_value",
                               "same_day_two_months_ago_qty", "same_day_two_months_ago_value",
                               "pct_yesterday_vs_same_day_last_month_qty", "pct_yesterday_vs_same_day_last_month_value",
                               "pct_yesterday_vs_same_day_2_months_ago_qty", "pct_yesterday_vs_same_day_2_months_ago_value",
                               "pct_same_day_lm_vs_2lm_qty", "pct_same_day_lm_vs_2lm_value"]),
        ("Month to Date", ["mtd_qty", "mtd_value", "prev_mtd_qty", "prev_mtd_value",
                            "pct_mtd_vs_prev_qty", "pct_mtd_vs_prev_value"]),
        ("3-Month Trend", ["three_month_trend_qty", "three_month_trend_value"]),
    ],
    "Active 1": [
        ("Snapshot", ["total_sims_in_view", "active_0_30_days", "semi_active_31_60_days",
                      "inactive_over_60_days", "never_used", "used_in_last_1_day",
                      "never_used_vs_same_day_last_month"]),
        ("New-Subscriber Cohort", ["new_subs_yesterday", "new_subs_active1_yesterday",
                                   "new_subs_active1_rate_yesterday", "new_subs_day_before",
                                   "new_subs_active1_day_before", "new_subs_active1_rate_day_before",
                                   "pct_new_subs_vs_day_before", "pct_new_subs_active1_vs_day_before"]),
        ("Day 2-4 Registration Activity", ["cohort_2_4_days_active_yesterday",
                                            "cohort_2_4_days_active_avg_prior_7d",
                                            "pct_cohort_2_4_days_active_vs_7d_avg"]),
        ("Day-30 Active-7 Retention", ["cohort_day30_total", "cohort_day30_active7_count",
                                       "cohort_day30_active7_rate",
                                       "cohort_day30_active7_same_period_last_month"]),
        ("MTD Trend", ["mtd_new_subs", "mtd_new_subs_active1", "mtd_active1_rate",
                       "prev_mtd_new_subs", "prev_mtd_new_subs_active1", "prev_mtd_active1_rate",
                       "pct_mtd_active1_vs_prev_mtd"]),
    ],
    "DIM Subscriber Alignment": [
        ("Table Alignment", ["VW_ACTIVE_SUBSCRIPTIONS_snapshot", "DIM_SUBSCRIBERS_active",
                              "UCONNECT_MAY_MERGE_active_uConnect_only", "spread"]),
        ("Duplicate Check (Active, uConnect)", ["duplicate_account_numbers",
                                                 "duplicate_account_number_rows",
                                                 "duplicate_iccids", "duplicate_iccid_rows"]),
    ],
    "Terminations": [
        ("Terminations vs Threshold", ["mtd_terminations", "prev_mtd_terminations",
                                        "two_months_ago_mtd_terminations",
                                        "baseline_avg_last_2_months", "threshold_baseline_plus_500"]),
        ("Legacy Proxy", ["sims_over_60_days_no_usage_proxy"]),
    ],
}

# Keys whose value is a genuine 3-point "a -> b -> c" trend string -> render as a real sparkline
TREND_KEY_RE = re.compile(r"three_month_trend")
TREND_VALUE_RE = re.compile(r"([R\-\d,\.]+)\s*→\s*([R\-\d,\.]+)\s*→\s*([R\-\d,\.]+)")


def parse_trend(value: str):
    m = TREND_VALUE_RE.search(str(value))
    if not m:
        return None
    try:
        return [float(g.replace("R", "").replace(",", "")) for g in m.groups()]
    except ValueError:
        return None


def sparkline_svg(points):
    lo, hi = min(points), max(points)
    span = (hi - lo) or 1
    xs = [4, 30, 56]
    ys = [18 - ((p - lo) / span) * 14 for p in points]
    coords = " ".join(f"{x},{y:.1f}" for x, y in zip(xs, ys))
    area = f"4,20 {coords} 56,20"
    return (
        f'<svg class="spark" viewBox="0 0 60 22" preserveAspectRatio="none">'
        f'<polygon points="{area}" fill="url(#sparkfill)"></polygon>'
        f'<polyline points="{coords}" fill="none" stroke="var(--highvolt)" stroke-width="1.6" '
        f'stroke-linecap="round" stroke-linejoin="round"></polyline>'
        f"</svg>"
    )


def stat_rows(values: dict) -> str:
    rows = []
    for k, v in values.items():
        trend = parse_trend(v) if TREND_KEY_RE.search(k) else None
        if trend:
            spark = sparkline_svg(trend)
        else:
            spark = '<span class="stat-spacer"></span>'
        rows.append(
            f"<div class='stat-row'>"
            f"<span class='stat-label'>{label(k)}</span>"
            f"{spark}"
            f"<span class='stat-value'>{fmt(v)}</span>"
            f"</div>"
        )
    return f"<div class='stat-rows'>{''.join(rows)}</div>"


def kv_table(check_name: str, values: dict) -> str:
    groups = CHECK_GROUPS.get(check_name)
    if not groups:
        return stat_rows(values)

    seen = set()
    sections = []
    for group_label, keys in groups:
        present = {k: values[k] for k in keys if k in values}
        seen.update(present)
        if present:
            sections.append(
                f"<div class='stat-group'><h4>{group_label}</h4>{stat_rows(present)}</div>"
            )
    leftover = {k: v for k, v in values.items() if k not in seen}
    if leftover:
        sections.append(f"<div class='stat-group'><h4>Other</h4>{stat_rows(leftover)}</div>")
    return "".join(sections)


def flag_list(flags: list) -> str:
    if not flags:
        return ""
    items = "".join(f"<li>{f}</li>" for f in flags)
    return f'<ul class="flags">{items}</ul>'


# Cycle of decorative left-border accents for card numerals (categorical, not status-based)
ACCENT_CYCLE = ["accent-a", "accent-b", "accent-c"]


def card(check: dict, index: int) -> str:
    status = check.get("status", "green")
    title  = check.get("check", "")
    values = check.get("values", {})
    flags  = check.get("flags",  [])
    note   = check.get("note",   "")
    accent = ACCENT_CYCLE[index % len(ACCENT_CYCLE)]

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
        body += kv_table(title, values)
    body += flag_list(flags)

    return f"""
    <div class="card {accent}">
        <div class="card-number">{index + 1:02d}</div>
        <div class="card-header">
            <span class="card-title">{title}</span>
            <span class="badge {status}">{badge_label}</span>
        </div>
        <div class="card-body">{body}</div>
    </div>"""


auto_cards    = "\n  ".join(card(c, i) for i, c in enumerate(automated))
pending_cards = "\n  ".join(card(c, i) for i, c in enumerate(pending))
manual_cards  = "\n  ".join(card(c, i) for i, c in enumerate(manual))

kpi_tiles = f"""
  <div class="kpi-tile">
    <div class="kpi-label">Checks Passed</div>
    <div class="kpi-value good">{passed}</div>
    <div class="kpi-sub">of {len(automated)} automated checks</div>
  </div>
  <div class="kpi-tile">
    <div class="kpi-label">Checks Failed</div>
    <div class="kpi-value bad">{failed}</div>
    <div class="kpi-sub">red flags today</div>
  </div>
  <div class="kpi-tile">
    <div class="kpi-label">Warnings</div>
    <div class="kpi-value warn">{warnings}</div>
    <div class="kpi-sub">amber flags today</div>
  </div>
  <div class="kpi-tile">
    <div class="kpi-label">Pending MCP Access</div>
    <div class="kpi-value neutral">{len(pending)}</div>
    <div class="kpi-sub">tables awaiting connection</div>
  </div>
  <div class="kpi-tile">
    <div class="kpi-label">Manual Cross-Checks</div>
    <div class="kpi-value neutral">{len(manual)}</div>
    <div class="kpi-sub">verify on Telco / PowerBI</div>
  </div>"""

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
  /* Spot CI 2025 -- THERMOLINE, laid out to match the Telco KPI Dashboard format */
  :root {{
    --inkcore:    #0e0e0e;
    --navy:       #10162b;
    --zero-white: #ffffff;
    --page:       #f4f5f7;
    --hypermint:  #13f460;
    --sonic-blue: #2d40e9;
    --ultraviolet:#52bec0;
    --highvolt:   #f44610;
    --warn:       #f5c400;

    --ink:        #101114;
    --ink-soft:   rgba(16,17,20,0.55);
    --ink-faint:  rgba(16,17,20,0.32);
    --border:     rgba(16,17,20,0.09);

    --card-radius: 10px;
    --font-header: 'At Hauss Std Retina', 'Helvetica Neue', Helvetica, Arial, sans-serif;
    --font-body:   'Helvetica Now', 'Helvetica Neue', Helvetica, Arial, sans-serif;
  }}

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    font-family: var(--font-body);
    background: var(--page);
    color: var(--ink);
    padding: 0 0 40px;
    min-height: 100vh;
  }}

  .topbar {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 16px 28px;
    background: var(--zero-white);
    border-bottom: 1px solid var(--border);
    flex-wrap: wrap;
  }}
  .brand {{ display: flex; align-items: center; gap: 14px; }}
  .spot-logo {{
    display: inline-flex;
    align-items: center;
    gap: 2px;
    background: var(--inkcore);
    color: var(--zero-white);
    font-family: var(--font-header);
    font-weight: 700;
    font-size: 0.95rem;
    letter-spacing: -0.01em;
    padding: 7px 12px;
    border-radius: 6px;
  }}
  .spot-logo sup {{ font-size: 0.55em; }}
  .brand h1 {{
    font-family: var(--font-header);
    font-size: 1.15rem;
    font-weight: 700;
    color: var(--ink);
  }}
  .topbar .status-line {{
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 0.78rem;
    color: var(--ink-soft);
    letter-spacing: 0.01em;
  }}
  .status-dot {{ width: 8px; height: 8px; border-radius: 50%; background: var(--hypermint); flex-shrink: 0; }}
  .status-dot.red {{ background: var(--highvolt); }}
  .status-dot.amber {{ background: var(--warn); }}

  .tab-panel, footer {{ padding: 0 28px; }}

  /* ---- CSS-only tabs ---- */
  .tabs-wrapper input[type="radio"] {{ display: none; }}
  .tabbar {{
    display: flex;
    gap: 26px;
    border-bottom: 1px solid var(--border);
    background: var(--zero-white);
    padding: 0 28px;
    margin: 0 -28px 28px;
    flex-wrap: wrap;
  }}
  .tabbar label {{
    padding: 16px 2px;
    font-family: var(--font-header);
    font-weight: 600;
    font-size: 0.88rem;
    color: var(--ink-faint);
    cursor: pointer;
    border-bottom: 2px solid transparent;
    user-select: none;
  }}
  .tab-panel {{ display: none; }}
  #tab-overview:checked ~ .tabbar label[for="tab-overview"],
  #tab-auto:checked ~ .tabbar label[for="tab-auto"],
  #tab-pending:checked ~ .tabbar label[for="tab-pending"],
  #tab-manual:checked ~ .tabbar label[for="tab-manual"] {{
    color: var(--highvolt);
    border-bottom-color: var(--highvolt);
  }}
  #tab-overview:checked ~ #content-overview,
  #tab-auto:checked ~ #content-auto,
  #tab-pending:checked ~ #content-pending,
  #tab-manual:checked ~ #content-manual {{ display: block; }}

  /* ---- KPI tile row ---- */
  .kpi-row {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 14px;
    margin-bottom: 30px;
  }}
  .kpi-tile {{
    background: var(--navy);
    border-radius: var(--card-radius);
    padding: 18px 18px 16px;
  }}
  .kpi-label {{
    font-size: 0.68rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: rgba(255,255,255,0.45);
    margin-bottom: 10px;
  }}
  .kpi-value {{
    font-family: var(--font-header);
    font-size: 1.9rem;
    font-weight: 700;
    color: var(--zero-white);
    line-height: 1;
  }}
  .kpi-value.good {{ color: var(--hypermint); }}
  .kpi-value.bad  {{ color: var(--highvolt); }}
  .kpi-value.warn {{ color: var(--warn); }}
  .kpi-sub {{
    margin-top: 6px;
    font-size: 0.72rem;
    color: rgba(255,255,255,0.4);
  }}

  .overall-banner {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 9px 18px;
    border-radius: 6px;
    font-family: var(--font-header);
    font-weight: 700;
    font-size: 0.82rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    margin-bottom: 22px;
  }}
  .overall-banner.green {{ background: rgba(19,244,96,0.14); color: #0a7d38; }}
  .overall-banner.red   {{ background: rgba(244,70,16,0.12); color: var(--highvolt); }}
  .overall-banner.amber {{ background: rgba(245,196,0,0.16); color: #8a6a00; }}

  h2.section-title {{
    font-family: var(--font-header);
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--ink-faint);
    margin: 0 0 14px;
  }}

  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
    gap: 16px;
    align-items: start;
  }}

  .card {{
    position: relative;
    border-radius: var(--card-radius);
    border: 1px solid var(--border);
    background: var(--zero-white);
    overflow: hidden;
    padding-left: 5px;
    box-shadow: 0 1px 2px rgba(16,17,20,0.04);
  }}
  .card.accent-a {{ box-shadow: inset 4px 0 0 var(--highvolt); }}
  .card.accent-b {{ box-shadow: inset 4px 0 0 var(--sonic-blue); }}
  .card.accent-c {{ box-shadow: inset 4px 0 0 var(--ultraviolet); }}

  .card-number {{
    position: absolute;
    top: 10px;
    right: 16px;
    font-family: var(--font-header);
    font-weight: 700;
    font-size: 1.8rem;
    color: rgba(16,17,20,0.06);
    line-height: 1;
  }}

  .card-header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding: 16px 18px 12px;
  }}
  .card-title {{
    font-family: var(--font-header);
    font-weight: 700;
    font-size: 0.95rem;
    color: var(--ink);
  }}
  .card-body {{
    padding: 0 18px 16px;
    font-size: 0.82rem;
    color: var(--ink-soft);
  }}

  .badge {{
    padding: 3px 10px;
    border-radius: 3px;
    font-size: 0.63rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    flex-shrink: 0;
    font-family: var(--font-header);
  }}
  .badge.green   {{ background: rgba(19,244,96,0.16);  color: #0a7d38; }}
  .badge.red     {{ background: var(--highvolt);       color: var(--zero-white); }}
  .badge.amber   {{ background: rgba(245,196,0,0.22);  color: #8a6a00; }}
  .badge.manual  {{ background: var(--sonic-blue);      color: var(--zero-white); }}
  .badge.pending {{ background: var(--ultraviolet);    color: var(--inkcore); }}
  .badge.error   {{ background: var(--highvolt);       color: var(--zero-white); }}

  .stat-group {{ margin-top: 12px; }}
  .stat-group:first-child {{ margin-top: 0; }}
  .stat-group h4 {{
    font-family: var(--font-header);
    font-size: 0.65rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: var(--sonic-blue);
    margin-bottom: 6px;
    padding-bottom: 5px;
    border-bottom: 1px solid var(--border);
  }}

  .stat-rows {{ display: flex; flex-direction: column; }}
  .stat-row {{
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 7px 0;
    border-bottom: 1px solid rgba(16,17,20,0.05);
  }}
  .stat-row:last-child {{ border-bottom: none; }}
  .stat-label {{
    flex: 1 1 auto;
    min-width: 0;
    color: var(--ink-soft);
    font-size: 0.78rem;
  }}
  .stat-spacer {{ width: 60px; flex-shrink: 0; }}
  .spark {{ width: 60px; height: 22px; flex-shrink: 0; }}
  .stat-value {{
    color: var(--ink);
    font-weight: 600;
    font-size: 0.82rem;
    text-align: right;
    white-space: nowrap;
  }}

  ul.flags {{ list-style: none; margin-top: 12px; display: flex; flex-direction: column; gap: 6px; }}
  ul.flags li {{
    background: rgba(244,70,16,0.07);
    border-left: 3px solid var(--highvolt);
    padding: 7px 12px;
    border-radius: 3px;
    color: #9a3a1c;
    font-size: 0.78rem;
    line-height: 1.4;
  }}

  .note {{ color: var(--sonic-blue); font-style: italic; margin-bottom: 6px; font-size: 0.78rem; }}

  footer {{
    margin-top: 40px;
    padding: 18px 0 0;
    border-top: 1px solid var(--border);
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
    font-size: 0.7rem;
    color: var(--ink-faint);
    letter-spacing: 0.03em;
    text-transform: uppercase;
  }}

  @media (max-width: 640px) {{
    .grid {{ grid-template-columns: 1fr; }}
    .page {{ padding: 0 16px; }}
    .topbar {{ padding: 14px 16px; }}
    .tabbar {{ padding: 0 16px; margin: 0 -16px 22px; }}
  }}

  svg.spark defs {{ display: none; }}
</style>
</head>
<body>

<svg width="0" height="0" style="position:absolute">
  <defs>
    <linearGradient id="sparkfill" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#f44610" stop-opacity="0.28"></stop>
      <stop offset="100%" stop-color="#f44610" stop-opacity="0"></stop>
    </linearGradient>
  </defs>
</svg>

<div class="topbar">
  <div class="brand">
    <span class="spot-logo">Spot<sup>TM</sup></span>
    <h1>DDA Daily BI Checks</h1>
  </div>
  <div class="status-line">
    <span class="status-dot {overall_cls}"></span>
    {display_date} &nbsp;&middot;&nbsp; Data as of {run_date} &nbsp;&middot;&nbsp; Snowflake UCONNECT_DW
  </div>
</div>

<div class="tabs-wrapper">
  <input type="radio" name="tabs" id="tab-overview" checked>
  <input type="radio" name="tabs" id="tab-auto">
  <input type="radio" name="tabs" id="tab-pending">
  <input type="radio" name="tabs" id="tab-manual">

  <nav class="tabbar">
    <label for="tab-overview">Overview</label>
    <label for="tab-auto">Automated Checks</label>
    <label for="tab-pending">Pending MCP Access</label>
    <label for="tab-manual">Manual Checks</label>
  </nav>

  <div id="content-overview" class="tab-panel">
    <div class="overall-banner {overall_cls}">{overall_label}</div>
    <div class="kpi-row">{kpi_tiles}</div>
    <h2 class="section-title">Automated Checks — Snowflake</h2>
    <div class="grid">
      {auto_cards}
    </div>
  </div>

  <div id="content-auto" class="tab-panel">
    <h2 class="section-title">Automated Checks — Snowflake</h2>
    <div class="grid">
      {auto_cards}
    </div>
  </div>

  <div id="content-pending" class="tab-panel">
    <h2 class="section-title">Pending MCP Access</h2>
    <div class="grid">
      {pending_cards}
    </div>
  </div>

  <div id="content-manual" class="tab-panel">
    <h2 class="section-title">Manual Checks — Telco / Dashboards</h2>
    <div class="grid">
      {manual_cards}
    </div>
  </div>

  <footer>
    <span>Uconnect DDA &mdash; Snowflake UCONNECT_DW</span>
    <span>Refreshed daily 07:00 SAST &mdash; GitHub Actions</span>
  </footer>
</div>

</body>
</html>"""

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html)

print(f"build_dashboard.py complete — index.html written ({run_date})")
