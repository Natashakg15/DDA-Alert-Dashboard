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
same_day_lm = yesterday.replace(month=yesterday.month - 1 if yesterday.month > 1 else 12,
                                 year=yesterday.year if yesterday.month > 1 else yesterday.year - 1)

def q(sql, *args):
    cur.execute(sql, args)
    return cur.fetchall()

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
    SELECT
        RECHARGE_DATE,
        COUNT(*)          AS cnt,
        SUM(RECHARGE_AMOUNT) AS rev
    FROM UCONNECT_DW.ANALYTICS.VW_CELLC_RECHARGES
    WHERE RECHARGE_DATE IN (%s, %s, %s)
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

# ── Active 1 ──────────────────────────────────────────────────────────────────
rows = q("""
    SELECT USAGE_DATE, COUNT(DISTINCT MSISDN) AS cnt
    FROM UCONNECT_DW.ANALYTICS.VW_ACTIVE_SUBSCRIPTIONS_USAGE_DETAILS
    WHERE USAGE_DATE IN (%s, %s)
    GROUP BY 1
""", str(yesterday), str(day_before))

by_date = {str(r[0]): r[1] for r in rows}
yest_cnt = by_date.get(str(yesterday), 0)
db_cnt   = by_date.get(str(day_before), 0)

flags = []
if yest_cnt == 0:
    flags.append("No active subscriptions recorded for yesterday")
elif db_cnt and yest_cnt / db_cnt < 0.40:
    flags.append(f"{yest_cnt:,} active — >60% drop vs day before ({db_cnt:,})")
elif db_cnt and yest_cnt > db_cnt * 2:
    flags.append(f"Anomalous spike: {yest_cnt:,} vs {db_cnt:,} day before")

automated.append({
    "check": "Active 1",
    "status": "red" if flags else "green",
    "values": {
        "yesterday_count":  yest_cnt,
        "day_before_count": db_cnt,
        "pct_vs_day_before": pct(yest_cnt, db_cnt),
    },
    "flags": flags,
})

# ── DIM Subscriber Alignment ──────────────────────────────────────────────────
def active_count(date):
    r = q("""
        SELECT COUNT(DISTINCT MSISDN)
        FROM UCONNECT_DW.ANALYTICS.VW_ACTIVE_SUBSCRIPTIONS_USAGE_DETAILS
        WHERE USAGE_DATE = %s
    """, str(date))
    return r[0][0] if r else 0

def dim_count(date):
    r = q("""
        SELECT COUNT(*)
        FROM UCONNECT_DW.ANALYTICS.DIM_SUBSCRIBERS
        WHERE DATE(CREATED_AT) <= %s
          AND (DATE(DELETED_AT) > %s OR DELETED_AT IS NULL)
    """, str(date), str(date))
    return r[0][0] if r else 0

def merge_count(date):
    r = q("""
        SELECT COUNT(DISTINCT MSISDN)
        FROM UCONNECT_DW.ANALYTICS.UCONNECT_MAY_MERGE
        WHERE DATE(CREATED_AT) <= %s
          AND (DATE(DELETED_AT) > %s OR DELETED_AT IS NULL)
    """, str(date), str(date))
    return r[0][0] if r else 0

dim_y  = dim_count(yesterday)
mrg_y  = merge_count(yesterday)
act_y  = active_count(yesterday)
dim_db = dim_count(day_before)
mrg_db = merge_count(day_before)

spread_y  = max(dim_y, mrg_y, act_y) - min(dim_y, mrg_y, act_y)
spread_db = max(dim_db, mrg_db) - min(dim_db, mrg_db)

flags = []
counts = {"DIM_SUBSCRIBERS": dim_y, "MERGE_TABLE": mrg_y, "ACTIVE_SUBSCRIPTIONS": act_y}
non_zero = [v for v in counts.values() if v > 0]
if non_zero and any(v == 0 for v in counts.values()):
    flags.append("One or more tables returned 0 while others have data")
if spread_y > 15:
    flags.append(f"Spread of {spread_y:,} across subscriber tables exceeds threshold of 15")

automated.append({
    "check": "DIM Subscriber Alignment",
    "status": "red" if flags else "green",
    "values": {
        "DIM_SUBSCRIBERS_yesterday":     dim_y,
        "MERGE_TABLE_yesterday":         mrg_y,
        "ACTIVE_SUBSCRIPTIONS_yesterday": act_y,
        "spread_yesterday":              spread_y,
        "DIM_SUBSCRIBERS_day_before":    dim_db,
        "MERGE_TABLE_day_before":        mrg_db,
        "spread_day_before":             spread_db,
    },
    "flags": flags,
})

# ── Terminations (>60 day usage) ──────────────────────────────────────────────
cutoff = today - datetime.timedelta(days=60)
rows = q("""
    SELECT COUNT(DISTINCT MSISDN)
    FROM UCONNECT_DW.ANALYTICS.VW_ACTIVE_SUBSCRIPTIONS_USAGE_DETAILS
    WHERE USAGE_DATE < %s
      AND MSISDN NOT IN (
          SELECT DISTINCT MSISDN
          FROM UCONNECT_DW.ANALYTICS.VW_ACTIVE_SUBSCRIPTIONS_USAGE_DETAILS
          WHERE USAGE_DATE >= %s
      )
""", str(cutoff), str(cutoff))

sims_over_60 = rows[0][0] if rows else 0
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
    "run_time": str(today),
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
