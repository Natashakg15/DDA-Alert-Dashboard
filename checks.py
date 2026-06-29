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
day_before = today - datetime.timedelta(days=2)
lm_month   = yesterday.month - 1 if yesterday.month > 1 else 12
lm_year    = yesterday.year if yesterday.month > 1 else yesterday.year - 1
same_day_lm = yesterday.replace(month=lm_month, year=lm_year)

def q(sql, *args):
    cur.execute(sql, args)
    return cur.fetchall()

def scalar(sql, *args):
    rows = q(sql, *args)
    return rows[0][0] if rows else 0

def pct(a, b):
    if not b:
        return "N/A"
    ratio = a / b * 100
    diff  = ratio - 100
    direction = "up" if diff >= 0 else "down"
    return f"{ratio:.1f}% ({direction} {abs(diff):.1f}%)"

automated = []

# ── Cell C Recharges ──────────────────────────────────────────────────────────
rows = q("""
    SELECT DATE(TRANSACTION_DATE) AS dt, COUNT(*) AS cnt, SUM(VALUE) AS rev
    FROM UCONNECT_DW.ANALYTICS.VW_CELLC_RECHARGES
    WHERE DATE(TRANSACTION_DATE) IN (%s, %s, %s)
    GROUP BY 1
""", str(yesterday), str(day_before), str(same_day_lm))

by_date = {str(r[0]): (r[1], r[2]) for r in rows}
yest_cnt, yest_rev = by_date.get(str(yesterday), (0, 0))
db_cnt,   _        = by_date.get(str(day_before), (0, 0))
lm_cnt,   _        = by_date.get(str(same_day_lm), (0, 0))

flags = []
if yest_cnt == 0:
    flags.append("No recharges recorded for yesterday")
elif db_cnt and yest_cnt / db_cnt < 0.40:
    flags.append(f"{yest_cnt:,} recharges — >60% drop vs day before ({db_cnt:,})")
if lm_cnt and yest_cnt / lm_cnt < 0.80:
    flags.append(f">{20}% drop vs same day last month ({lm_cnt:,})")

automated.append({
    "check": "Cell C Recharges",
    "status": "red" if flags else "green",
    "values": {
        "yesterday_count":            yest_cnt,
        "day_before_count":           db_cnt,
        "same_day_last_month_count":  lm_cnt,
        "yesterday_revenue_sum":      int(yest_rev or 0),
        "pct_vs_day_before":          pct(yest_cnt, db_cnt),
        "pct_vs_same_day_last_month": pct(yest_cnt, lm_cnt),
    },
    "flags": flags,
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
        f"All comparisons use completed days: yesterday ({yesterday}) vs "
        f"day before ({day_before}). Today is excluded as it is an incomplete day."
    ),
    "automated": automated,
    "pending":   pending,
    "manual":    manual,
    "errors":    [],
}

with open("results.json", "w") as f:
    json.dump(output, f, indent=2, default=str)

print(f"checks.py complete — {len(automated)} automated checks written to results.json")
