# Not run by CI — the live board is refreshed via a local scheduled task
# that queries through the Snowflake MCP connection instead of direct
# credentials. Kept here as a reference for the check logic/thresholds.
import os
import json
import datetime
import snowflake.connector

ACCOUNT   = os.environ["SNOWFLAKE_ACCOUNT"]
USER      = os.environ["SNOWFLAKE_USER"]
PASSWORD  = os.environ["SNOWFLAKE_PASSWORD"]
WAREHOUSE = os.environ["SNOWFLAKE_WAREHOUSE"]
ROLE      = os.environ.get("SNOWFLAKE_ROLE", "")

conn = snowflake.connector.connect(
    account=ACCOUNT,
    user=USER,
    password=PASSWORD,
    warehouse=WAREHOUSE,
    role=ROLE if ROLE else None,
    database="UCONNECT_DW",
    schema="ANALYTICS",
)
cur = conn.cursor()

today      = datetime.date.today()
yesterday  = today - datetime.timedelta(days=1)
lm_month   = yesterday.month - 1 if yesterday.month > 1 else 12
lm_year    = yesterday.year if yesterday.month > 1 else yesterday.year - 1
same_day_lm = yesterday.replace(month=lm_month, year=lm_year)
lm2_month  = yesterday.month - 2 if yesterday.month > 2 else yesterday.month + 10
lm2_year   = yesterday.year if yesterday.month > 2 else yesterday.year - 1
same_day_2lm = yesterday.replace(month=lm2_month, year=lm2_year)

month_start_current = yesterday.replace(day=1)
month_start_prior    = same_day_lm.replace(day=1)
month_start_2prior   = same_day_2lm.replace(day=1)

def q(sql, *args):
    cur.execute(sql, args)
    return cur.fetchall()

def scalar(sql, *args):
    rows = q(sql, *args)
    return rows[0][0] if rows else 0

automated = []

# ── Cell C Recharges ──────────────────────────────────────────────────────────
cellc_flags = []

def period_stats(where_sql, *args):
    """COUNT/SUM/MIN/MAX/AVG(VALUE) for one period — feeds both the raw count and the anomaly check."""
    cnt, rev, min_v, max_v, avg_v = q(f"""
        SELECT COUNT(*), SUM(VALUE), MIN(VALUE), MAX(VALUE), AVG(VALUE)
        FROM UCONNECT_DW.ANALYTICS.VW_CELLC_RECHARGES
        WHERE {where_sql}
    """, *args)[0]
    return int(cnt or 0), float(rev or 0), avg_v, max_v

def safe_value(rev, avg_v, max_v, label):
    """Normal recharge is ~R2-R500 (avg ~R15). AVG is the primary signal — a single large-but-plausible
    transaction gets diluted across thousands of normal ones and barely moves it, so don't exclude on
    MAX alone. Only exclude when AVG is 10x+ normal, or MAX is multiple orders of magnitude beyond normal
    (matching the 2026-07-13 incident: one R262,144,000 txn pushed that day's AVG to R108,319)."""
    if avg_v is not None and (avg_v > 150 or (max_v or 0) > 1_000_000):
        cellc_flags.append(
            f"{label} revenue excluded — data anomaly (AVG=R{avg_v:,.0f}, MAX=R{max_v:,.0f} "
            f"vs normal ~R15 avg / R2-R500 range)"
        )
        return "excluded — data anomaly (see flags)"
    return int(rev)

def variance(a, b, threshold, label, unit):
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)) or not b:
        return "N/A — value excluded" if not isinstance(a, (int, float)) or not isinstance(b, (int, float)) else "N/A"
    ratio = a / b * 100
    diff  = ratio - 100
    direction = "up" if diff >= 0 else "down"
    s = f"{ratio:.1f}% ({direction} {abs(diff):.1f}%)"
    if abs(diff) > threshold:
        cellc_flags.append(f"{label} {unit}: {direction} {abs(diff):.1f}% — exceeds {threshold}% threshold")
    return s

def trend(v2, v1, v0, label, prefix=""):
    if not isinstance(v2, (int, float)) or not isinstance(v1, (int, float)) or not isinstance(v0, (int, float)) or not v2 or not v1:
        return "N/A — value excluded"
    leg1, leg2 = (v1 - v2) / v2 * 100, (v0 - v1) / v1 * 100
    s = f"{prefix}{v2:,.0f} → {prefix}{v1:,.0f} → {prefix}{v0:,.0f} (legs: {leg1:+.1f}%, {leg2:+.1f}%)"
    total = (v0 - v2) / v2 * 100
    if abs(leg1) > 25 or abs(leg2) > 25 or (leg1 > 0 and leg2 > 0 and total > 20) or (leg1 < 0 and leg2 < 0 and total < -20):
        cellc_flags.append(f"Abnormal 3-month {label} trend: {s}")
    return s

yest_cnt, yest_rev, yest_avg, yest_max     = period_stats("DATE(TRANSACTION_DATE) = %s", str(yesterday))
lm_cnt,   lm_rev,   lm_avg,   lm_max       = period_stats("DATE(TRANSACTION_DATE) = %s", str(same_day_lm))
lm2_cnt,  lm2_rev,  lm2_avg,  lm2_max      = period_stats("DATE(TRANSACTION_DATE) = %s", str(same_day_2lm))
mtd_cnt,  mtd_rev,  mtd_avg,  mtd_max      = period_stats("DATE(TRANSACTION_DATE) BETWEEN %s AND %s", str(month_start_current), str(yesterday))
pmtd_cnt, pmtd_rev, pmtd_avg, pmtd_max     = period_stats("DATE(TRANSACTION_DATE) BETWEEN %s AND %s", str(month_start_prior), str(same_day_lm))
p2mtd_cnt, p2mtd_rev, p2mtd_avg, p2mtd_max = period_stats("DATE(TRANSACTION_DATE) BETWEEN %s AND %s", str(month_start_2prior), str(same_day_2lm))

if yest_cnt == 0:
    cellc_flags.append("No recharges recorded for yesterday")
else:
    if lm_cnt and yest_cnt / lm_cnt < 0.80:
        cellc_flags.append(f"{yest_cnt:,} recharges — >20% drop vs same day last month ({lm_cnt:,})")
    if lm2_cnt and yest_cnt / lm2_cnt < 0.80:
        cellc_flags.append(f"{yest_cnt:,} recharges — >20% drop vs same day two months ago ({lm2_cnt:,})")

yest_val  = safe_value(yest_rev,  yest_avg,  yest_max,  "Yesterday")
lm_val    = safe_value(lm_rev,    lm_avg,    lm_max,    "Same-day-last-month")
lm2_val   = safe_value(lm2_rev,   lm2_avg,   lm2_max,   "Same-day-two-months-ago")
mtd_val   = safe_value(mtd_rev,   mtd_avg,   mtd_max,   "Current MTD")
pmtd_val  = safe_value(pmtd_rev,  pmtd_avg,  pmtd_max,  "Prior-month MTD")
p2mtd_val = safe_value(p2mtd_rev, p2mtd_avg, p2mtd_max, "Two-months-ago MTD")

if isinstance(yest_val, int) and isinstance(lm_val, int) and lm_val and yest_val / lm_val < 0.80:
    cellc_flags.append(f"R{yest_val:,} revenue — >20% drop vs same day last month (R{lm_val:,})")
if isinstance(yest_val, int) and isinstance(lm2_val, int) and lm2_val and yest_val / lm2_val < 0.80:
    cellc_flags.append(f"R{yest_val:,} revenue — >20% drop vs same day two months ago (R{lm2_val:,})")

automated.append({
    "check": "Cell C Recharges",
    "status": "red" if cellc_flags else "green",
    "values": {
        "yesterday_count":               yest_cnt,
        "yesterday_value":               yest_val,
        "same_day_last_month_count":     lm_cnt,
        "same_day_last_month_value":     lm_val,
        "same_day_two_months_ago_count": lm2_cnt,
        "same_day_two_months_ago_value": lm2_val,
        "mtd_count":                     mtd_cnt,
        "mtd_value":                     mtd_val,
        "prev_mtd_count":                pmtd_cnt,
        "prev_mtd_value":                pmtd_val,
        "pct_mtd_vs_prev_count":         variance(mtd_cnt, pmtd_cnt, 10, "MTD vs prior-month MTD", "count"),
        "pct_mtd_vs_prev_value":         variance(mtd_val, pmtd_val, 10, "MTD vs prior-month MTD", "value"),
        "pct_same_day_lm_vs_2lm_count":  variance(lm_cnt, lm2_cnt, 5, "Same-day last-month vs two-months-ago", "count"),
        "pct_same_day_lm_vs_2lm_value":  variance(lm_val, lm2_val, 5, "Same-day last-month vs two-months-ago", "value"),
        "three_month_trend_count":       trend(p2mtd_cnt, pmtd_cnt, mtd_cnt, "count"),
        "three_month_trend_value":       trend(p2mtd_val, pmtd_val, mtd_val, "value", prefix="R"),
    },
    "flags": cellc_flags,
})

# ── Active 1 (snapshot view) ──────────────────────────────────────────────────
rows = q("""
    SELECT
        COUNT(*)                                                          AS total,
        SUM(CASE WHEN USAGE_0_30_DAYS = '1' THEN 1 ELSE 0 END)          AS active_30,
        SUM(CASE WHEN USAGE_31_60_DAYS = '1' THEN 1 ELSE 0 END)         AS semi_active,
        SUM(CASE WHEN USAGE_GREATER_THAN_60_DAYS = '1' THEN 1 ELSE 0 END) AS over_60,
        SUM(CASE WHEN DAYS_SINCE_LAST_USAGE = 'SIM Never Used' THEN 1 ELSE 0 END) AS never_used
    FROM UCONNECT_DW.ANALYTICS.VW_ACTIVE_SUBSCRIPTIONS_USAGE_DETAILS
""")
total, active_30, semi_active, over_60, never_used = rows[0]

used_yesterday = scalar("""
    SELECT COUNT(*)
    FROM UCONNECT_DW.ANALYTICS.VW_ACTIVE_SUBSCRIPTIONS_USAGE_DETAILS
    WHERE TRY_TO_NUMBER(DAYS_SINCE_LAST_USAGE) <= 1
""")

flags = []
if total == 0:
    flags.append("Snapshot view returned 0 records — data may be missing")

automated.append({
    "check": "Active 1 (Snapshot)",
    "status": "red" if flags else "green",
    "values": {
        "total_sims_in_view":     int(total),
        "active_0_30_days":       int(active_30),
        "semi_active_31_60_days": int(semi_active),
        "inactive_over_60_days":  int(over_60),
        "never_used":             int(never_used),
        "used_in_last_1_day":     int(used_yesterday),
    },
    "flags": flags,
})

# ── DIM Subscriber Alignment ──────────────────────────────────────────────────
dim_active = scalar("""
    SELECT COUNT(*) FROM UCONNECT_DW.ANALYTICS.DIM_SUBSCRIBERS
    WHERE TERMINATION_DATE IS NULL OR TERMINATION_DATE > CURRENT_DATE
""")
mrg_active = scalar("""
    SELECT COUNT(*) FROM UCONNECT_DW.ANALYTICS.UCONNECT_MAY_MERGE
    WHERE TERMINATION_DATE IS NULL OR TERMINATION_DATE > CURRENT_DATE
""")
act_snapshot = int(total)

spread = max(act_snapshot, dim_active, mrg_active) - min(act_snapshot, dim_active, mrg_active)

flags = []
counts = {"VW_ACTIVE_SUBSCRIPTIONS": act_snapshot, "DIM_SUBSCRIBERS": dim_active, "UCONNECT_MAY_MERGE": mrg_active}
non_zero = [v for v in counts.values() if v > 0]
if non_zero and any(v == 0 for v in counts.values()):
    flags.append("One or more tables returned 0 while others have data")
if spread > 15:
    flags.append(f"Spread of {spread:,} across subscriber tables — MERGE ({mrg_active:,}) vs VW_ACTIVE ({act_snapshot:,})")

automated.append({
    "check": "DIM Subscriber Alignment",
    "status": "red" if flags else "green",
    "values": {
        "VW_ACTIVE_SUBSCRIPTIONS_snapshot": act_snapshot,
        "DIM_SUBSCRIBERS_active":           int(dim_active),
        "UCONNECT_MAY_MERGE_active":        int(mrg_active),
        "spread":                           int(spread),
    },
    "flags": flags,
})

# ── Terminations (>60 day usage) ──────────────────────────────────────────────
sims_over_60 = int(over_60)
threshold = 3000
flags = []
if sims_over_60 > threshold:
    flags.append(f"{sims_over_60:,} SIMs with no usage in over 60 days — significantly exceeds the {threshold:,} threshold")

automated.append({
    "check": "Terminations (>60 day usage)",
    "status": "red" if flags else "green",
    "values": {
        "sims_over_60_days": sims_over_60,
        "threshold":         threshold,
    },
    "flags": flags,
})

cur.close()
conn.close()

# ── Write results.json ────────────────────────────────────────────────────────
pending = [
    {
        "check": "Wholesale Usage",
        "status": "pending",
        "note": "Awaiting MCP access to UCONNECT_DW.ANALYTICS.VW_WHOLESALE_USAGE",
        "flags": [],
    },
    {
        "check": "SmartConnect vs Datawarehouse",
        "status": "pending",
        "note": "Awaiting MCP access to UCONNECT_DW.ANALYTICS.VW_SC_RICA_REPORT",
        "flags": [],
    },
    {
        "check": "CDRs (Wholesale)",
        "status": "pending",
        "note": "Awaiting MCP access to DATAWAREHOUSE.MVNX.UC_FILE_RECON",
        "flags": [],
    },
]

manual = [
    {
        "check": "Cell C Recharges — Telco Dashboard Alignment",
        "status": "manual",
        "note": "Verify recharges on Telco BI dashboard — App, V Redemptions & Subs",
        "flags": [],
    },
    {
        "check": "Wholesale Usage — Telco Dashboard",
        "status": "manual",
        "note": "Cross-check usage totals on Telco dashboard",
        "flags": [],
    },
    {
        "check": "CDR PowerBI Dashboard",
        "status": "manual",
        "note": "Verify on PowerBI: https://app.powerbi.com/groups/me/reports/99160c3f-a907-43c4-a499-c701fdf5daf2",
        "flags": [],
    },
]

output = {
    "run_date": str(yesterday),
    "run_time": str(today) + " — GitHub Actions",
    "comparison_note": (
        f"All comparisons use completed days: yesterday ({yesterday}) is the run_date. "
        f"Today is excluded as it is an incomplete day. Cell C Recharges compares yesterday "
        f"against same-day-last-month and same-day-two-months-ago, plus MTD-vs-prior-MTD "
        f"(same day-of-month cutoff, so periods are equal length)."
    ),
    "automated": automated,
    "pending":   pending,
    "manual":    manual,
    "errors":    [],
}

with open("results.json", "w") as f:
    json.dump(output, f, indent=2, default=str)

print(f"checks.py complete — {len(automated)} automated checks written to results.json")
