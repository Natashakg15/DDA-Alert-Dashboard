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
day_before = yesterday - datetime.timedelta(days=1)
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

# ── Sales (Last 30 Days) ───────────────────────────────────────────────────────
# UCONNECT_MAY_MERGE_REVENUE — same structure/thresholds as Cell C Recharges, but
# summed across all revenue streams (app purchases, Cell C recharge, bill run,
# website recharges, rewards, post-paid, retail voucher redemptions, resale
# wallet, subscription) instead of just recharges, with a MASTER_TENANT
# breakdown so a variance >10% can be attributed to a specific tenant rather
# than just reported as "overall".
#
# REVENUE_WHATSAPP_PURCHASES_VALUE and REVENUE_WHATSAPP_PURCHASES_QUANTITY are
# EXCLUDED — their MAX() is ~1.7e19, three orders of magnitude beyond every
# other revenue column (which top out in the low thousands). DESCRIBE TABLE
# shows both flagged with an unresolved "Unknown Policy!" — likely a masking
# policy artifact rather than real data. Needs data-team/Snowflake-admin
# follow-up before these two columns can be trusted.
sales_flags = []
REVENUE_COLUMNS = [
    "REVENUE_APP_PURCHASES", "REVENUE_CELLC_RECHARGE", "REVENUE_MAY_BILLRUN",
    "REVENUE_MAY_WEBSITE_RECHARGES", "REVENUE_PAID_FOR_REWARDS", "REVENUE_POST_PAID_SUCCESSFULL",
    "REVENUE_RETAIL_VOUCHER_REDEMPTIONS", "REVENUE_UCONNECT_RESALE_WALLET",
    "REVENUE_POST_PAID_VOUCHER_REDEEMED", "REVENUE_SUBSCRIPTION",
]  # REVENUE_WHATSAPP_PURCHASES deliberately omitted — see note above
sales_flags.append(
    "REVENUE_WHATSAPP_PURCHASES_VALUE/QUANTITY excluded from Sales totals — MAX() ~1.7e19, "
    "orders of magnitude beyond every other revenue column, with an unresolved 'Unknown Policy!' "
    "on both columns per DESCRIBE TABLE. Needs data-team/Snowflake-admin follow-up."
)
QTY_SUFFIX = {"REVENUE_MAY_BILLRUN": "_QUANITITY"}  # typo in the source column name — must match exactly
QTY_EXPR = " + ".join(f"COALESCE({c}{QTY_SUFFIX.get(c, '_QUANTITY')},0)" for c in REVENUE_COLUMNS)
VALUE_EXPR = " + ".join(f"COALESCE({c}_VALUE,0)" for c in REVENUE_COLUMNS)

def sales_period(where_sql, *args):
    cnt, val = q(f"""
        SELECT SUM({QTY_EXPR}), SUM({VALUE_EXPR})
        FROM UCONNECT_DW.ANALYTICS.UCONNECT_MAY_MERGE_REVENUE
        WHERE {where_sql}
    """, *args)[0]
    return int(cnt or 0), float(val or 0)

def sales_variance(a, b, threshold, label, unit):
    if not b:
        return "N/A"
    ratio = a / b * 100
    diff = ratio - 100
    direction = "up" if diff >= 0 else "down"
    s = f"{ratio:.1f}% ({direction} {abs(diff):.1f}%)"
    if abs(diff) > threshold:
        sales_flags.append(f"{label} {unit}: {direction} {abs(diff):.1f}% — exceeds {threshold}% threshold")
    return s, abs(diff) > 10

def sales_trend(v2, v1, v0, label, prefix=""):
    if not v2 or not v1:
        return "N/A"
    leg1, leg2 = (v1 - v2) / v2 * 100, (v0 - v1) / v1 * 100
    s = f"{prefix}{v2:,.0f} → {prefix}{v1:,.0f} → {prefix}{v0:,.0f} (legs: {leg1:+.1f}%, {leg2:+.1f}%)"
    total = (v0 - v2) / v2 * 100
    if abs(leg1) > 25 or abs(leg2) > 25 or (leg1 > 0 and leg2 > 0 and total > 20) or (leg1 < 0 and leg2 < 0 and total < -20):
        sales_flags.append(f"Abnormal 3-month Sales {label} trend: {s}")
    return s

s_yest_qty, s_yest_val   = sales_period("DATE(TRANSACTION_DATE) = %s", str(yesterday))
s_lm_qty,   s_lm_val     = sales_period("DATE(TRANSACTION_DATE) = %s", str(same_day_lm))
s_lm2_qty,  s_lm2_val    = sales_period("DATE(TRANSACTION_DATE) = %s", str(same_day_2lm))
s_mtd_qty,  s_mtd_val    = sales_period("DATE(TRANSACTION_DATE) BETWEEN %s AND %s", str(month_start_current), str(yesterday))
s_pmtd_qty, s_pmtd_val   = sales_period("DATE(TRANSACTION_DATE) BETWEEN %s AND %s", str(month_start_prior), str(same_day_lm))
s_p2mtd_qty, s_p2mtd_val = sales_period("DATE(TRANSACTION_DATE) BETWEEN %s AND %s", str(month_start_2prior), str(same_day_2lm))

if s_yest_qty == 0:
    sales_flags.append("No sales recorded for yesterday")

pct_yest_vs_lm_qty,   flag_yest_lm_qty   = sales_variance(s_yest_qty, s_lm_qty, 20, "Yesterday vs same day last month", "qty")
pct_yest_vs_lm_val,   flag_yest_lm_val   = sales_variance(s_yest_val, s_lm_val, 20, "Yesterday vs same day last month", "value")
pct_yest_vs_2lm_qty,  flag_yest_2lm_qty  = sales_variance(s_yest_qty, s_lm2_qty, 20, "Yesterday vs same day two months ago", "qty")
pct_yest_vs_2lm_val,  flag_yest_2lm_val  = sales_variance(s_yest_val, s_lm2_val, 20, "Yesterday vs same day two months ago", "value")
pct_lm_vs_2lm_qty,    flag_lm_2lm_qty    = sales_variance(s_lm_qty, s_lm2_qty, 5, "Same-day last-month vs two-months-ago", "qty")
pct_lm_vs_2lm_val,    flag_lm_2lm_val    = sales_variance(s_lm_val, s_lm2_val, 5, "Same-day last-month vs two-months-ago", "value")
pct_mtd_vs_pmtd_qty,  flag_mtd_qty       = sales_variance(s_mtd_qty, s_pmtd_qty, 10, "MTD vs prior-month MTD", "qty")
pct_mtd_vs_pmtd_val,  flag_mtd_val       = sales_variance(s_mtd_val, s_pmtd_val, 10, "MTD vs prior-month MTD", "value")
three_month_trend_qty = sales_trend(s_p2mtd_qty, s_pmtd_qty, s_mtd_qty, "qty")
three_month_trend_val = sales_trend(s_p2mtd_val, s_pmtd_val, s_mtd_val, "value", prefix="R")

# Any variance over 10% (any comparison, qty or value) triggers a tenant-level breakdown so the
# flag can say whether the move is overall or attributable to one tenant.
if any([flag_yest_lm_qty, flag_yest_lm_val, flag_yest_2lm_qty, flag_yest_2lm_val,
        flag_lm_2lm_qty, flag_lm_2lm_val, flag_mtd_qty, flag_mtd_val]):
    tenant_rows = q(f"""
        SELECT MASTER_TENANT,
               SUM(CASE WHEN DATE(TRANSACTION_DATE) = %s THEN ({QTY_EXPR}) ELSE 0 END) AS yest_qty,
               SUM(CASE WHEN DATE(TRANSACTION_DATE) = %s THEN ({VALUE_EXPR}) ELSE 0 END) AS yest_val,
               SUM(CASE WHEN DATE(TRANSACTION_DATE) = %s THEN ({QTY_EXPR}) ELSE 0 END) AS lm_qty,
               SUM(CASE WHEN DATE(TRANSACTION_DATE) = %s THEN ({VALUE_EXPR}) ELSE 0 END) AS lm_val
        FROM UCONNECT_DW.ANALYTICS.UCONNECT_MAY_MERGE_REVENUE
        WHERE DATE(TRANSACTION_DATE) IN (%s, %s)
        GROUP BY MASTER_TENANT
    """, str(yesterday), str(yesterday), str(same_day_lm), str(same_day_lm), str(yesterday), str(same_day_lm))
    breakdown = []
    for tenant, t_yest_qty, t_yest_val, t_lm_qty, t_lm_val in tenant_rows:
        t_val_diff = ((float(t_yest_val) / float(t_lm_val)) * 100 - 100) if t_lm_val else None
        if t_val_diff is not None:
            breakdown.append(f"{tenant}: R{t_lm_val:,.0f} → R{t_yest_val:,.0f} ({t_val_diff:+.1f}%)")
        else:
            breakdown.append(f"{tenant}: R{t_lm_val:,.0f} → R{t_yest_val:,.0f} (N/A)")
    sales_flags.append("Tenant breakdown (yesterday vs same day last month, value): " + "; ".join(breakdown))

automated.append({
    "check": "Sales (Last 30 Days)",
    "status": "red" if sales_flags else "green",
    "values": {
        "yesterday_qty": s_yest_qty, "yesterday_value": round(s_yest_val, 2),
        "same_day_last_month_qty": s_lm_qty, "same_day_last_month_value": round(s_lm_val, 2),
        "same_day_two_months_ago_qty": s_lm2_qty, "same_day_two_months_ago_value": round(s_lm2_val, 2),
        "mtd_qty": s_mtd_qty, "mtd_value": round(s_mtd_val, 2),
        "prev_mtd_qty": s_pmtd_qty, "prev_mtd_value": round(s_pmtd_val, 2),
        "pct_yesterday_vs_same_day_last_month_qty": pct_yest_vs_lm_qty,
        "pct_yesterday_vs_same_day_last_month_value": pct_yest_vs_lm_val,
        "pct_yesterday_vs_same_day_2_months_ago_qty": pct_yest_vs_2lm_qty,
        "pct_yesterday_vs_same_day_2_months_ago_value": pct_yest_vs_2lm_val,
        "pct_same_day_lm_vs_2lm_qty": pct_lm_vs_2lm_qty,
        "pct_same_day_lm_vs_2lm_value": pct_lm_vs_2lm_val,
        "pct_mtd_vs_prev_qty": pct_mtd_vs_pmtd_qty,
        "pct_mtd_vs_prev_value": pct_mtd_vs_pmtd_val,
        "three_month_trend_qty": three_month_trend_qty,
        "three_month_trend_value": three_month_trend_val,
    },
    "flags": sales_flags,
})

# ── Active 1 ────────────────────────────────────────────────────────────────
# "Active 1" == USAGE_0_30_DAYS = '1' (the view's first usage bucket) — there is no
# column literally named ACTIVE_1; this mapping should be confirmed against the
# business definition the first time these numbers are reviewed.
DRASTIC_DROP = 60  # % — matches the existing Active 1 snapshot convention

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

# New-subscriber cohort: of subscribers created yesterday vs the day before, how many are Active 1
new_cohort = {row[0]: (int(row[1]), int(row[2] or 0)) for row in q("""
    SELECT DATE(ACCOUNTCREATEDATE), COUNT(*), SUM(CASE WHEN USAGE_0_30_DAYS = '1' THEN 1 ELSE 0 END)
    FROM UCONNECT_DW.ANALYTICS.VW_ACTIVE_SUBSCRIPTIONS_USAGE_DETAILS
    WHERE DATE(ACCOUNTCREATEDATE) IN (%s, %s)
    GROUP BY 1
""", str(yesterday), str(day_before))}
new_subs_yest, new_active1_yest = new_cohort.get(yesterday, (0, 0))
new_subs_prev, new_active1_prev = new_cohort.get(day_before, (0, 0))
new_active1_rate_yest = (new_active1_yest / new_subs_yest * 100) if new_subs_yest else None
new_active1_rate_prev = (new_active1_prev / new_subs_prev * 100) if new_subs_prev else None

def drastic(a, b, label, threshold=DRASTIC_DROP):
    if not b:
        return "N/A"
    ratio = a / b * 100
    diff = ratio - 100
    direction = "up" if diff >= 0 else "down"
    s = f"{ratio:.1f}% ({direction} {abs(diff):.1f}%)"
    if diff <= -threshold:
        flags.append(f"{label}: down {abs(diff):.1f}% — exceeds {threshold}% drastic-drop threshold")
    return s

# Registration activity: subscribers created 2-4 days before each of the last 8 days —
# yesterday's cohort-active count vs the trailing-7-day average of that same cohort measure
cohort_rows = q("""
    WITH d AS (
        SELECT DATEADD(day, -seq4(), %s::date) AS report_date
        FROM TABLE(GENERATOR(ROWCOUNT => 8))
    )
    SELECT d.report_date, COUNT(v.ACCOUNTCREATEDATE),
           SUM(CASE WHEN v.USAGE_0_30_DAYS = '1' THEN 1 ELSE 0 END)
    FROM d
    LEFT JOIN UCONNECT_DW.ANALYTICS.VW_ACTIVE_SUBSCRIPTIONS_USAGE_DETAILS v
        ON DATE(v.ACCOUNTCREATEDATE) BETWEEN DATEADD(day,-4,d.report_date) AND DATEADD(day,-2,d.report_date)
    GROUP BY d.report_date
    ORDER BY d.report_date
""", str(yesterday))
cohort_series = {row[0]: (int(row[1]), int(row[2] or 0)) for row in cohort_rows}
cohort_active_yest = cohort_series.get(yesterday, (0, 0))[1]
prior_7 = [cohort_series[d][1] for d in cohort_series if d != yesterday]
cohort_active_avg_7d = sum(prior_7) / len(prior_7) if prior_7 else None

# Day-30 Active 7 retention: subscribers created ~1 month ago (same day-of-month cutoff),
# what % have used in the last 7 days. "Same period last month" needs a snapshot log —
# see snapshots.json below; this will read as N/A until ~1 month of history has accumulated.
day30_total, day30_active7 = q("""
    SELECT COUNT(*), SUM(CASE WHEN TRY_TO_NUMBER(DAYS_SINCE_LAST_USAGE) <= 7 THEN 1 ELSE 0 END)
    FROM UCONNECT_DW.ANALYTICS.VW_ACTIVE_SUBSCRIPTIONS_USAGE_DETAILS
    WHERE DATE(ACCOUNTCREATEDATE) = %s
""", str(same_day_lm))[0]
day30_total, day30_active7 = int(day30_total), int(day30_active7 or 0)

# MTD Active 1: new subscribers created this MTD who are Active 1, vs the equal-length prior-MTD window
mtd_new, mtd_new_active1 = q("""
    SELECT COUNT(*), SUM(CASE WHEN USAGE_0_30_DAYS = '1' THEN 1 ELSE 0 END)
    FROM UCONNECT_DW.ANALYTICS.VW_ACTIVE_SUBSCRIPTIONS_USAGE_DETAILS
    WHERE DATE(ACCOUNTCREATEDATE) BETWEEN %s AND %s
""", str(month_start_current), str(yesterday))[0]
pmtd_new, pmtd_new_active1 = q("""
    SELECT COUNT(*), SUM(CASE WHEN USAGE_0_30_DAYS = '1' THEN 1 ELSE 0 END)
    FROM UCONNECT_DW.ANALYTICS.VW_ACTIVE_SUBSCRIPTIONS_USAGE_DETAILS
    WHERE DATE(ACCOUNTCREATEDATE) BETWEEN %s AND %s
""", str(month_start_prior), str(same_day_lm))[0]
mtd_new, mtd_new_active1 = int(mtd_new), int(mtd_new_active1 or 0)
pmtd_new, pmtd_new_active1 = int(pmtd_new), int(pmtd_new_active1 or 0)

# ── Daily snapshot log (needed for "never used" and day-30 Active-7 MTD/month-over-month
#    comparisons — the source view has no history, so we build our own by appending one
#    row per run) ────────────────────────────────────────────────────────────────────────
SNAPSHOT_PATH = "snapshots.json"
try:
    with open(SNAPSHOT_PATH, encoding="utf-8") as f:
        snapshots = json.load(f)
except FileNotFoundError:
    snapshots = []

snapshots = [s for s in snapshots if s["date"] != str(yesterday)]
snapshots.append({
    "date": str(yesterday),
    "total": int(total),
    "active_30": int(active_30),
    "semi_active": int(semi_active),
    "over_60": int(over_60),
    "never_used": int(never_used),
    "used_yesterday": int(used_yesterday),
    "day30_active7_rate": (day30_active7 / day30_total * 100) if day30_total else None,
})
snapshots.sort(key=lambda s: s["date"])

with open(SNAPSHOT_PATH, "w", encoding="utf-8") as f:
    json.dump(snapshots, f, indent=2)

by_date = {s["date"]: s for s in snapshots}
never_used_lm_snap = by_date.get(str(same_day_lm))
never_used_mtd_trend = (
    drastic(never_used, never_used_lm_snap["never_used"], "Never used vs same day last month")
    if never_used_lm_snap else f"N/A — snapshot history starts {yesterday}"
)
day30_active7_lm_snap = by_date.get(str(same_day_2lm))
day30_active7_rate = (day30_active7 / day30_total * 100) if day30_total else None
day30_active7_same_period_lm = (
    f"{day30_active7_lm_snap['day30_active7_rate']:.1f}%"
    if day30_active7_lm_snap and day30_active7_lm_snap["day30_active7_rate"] is not None
    else f"N/A — snapshot history starts {yesterday}"
)

automated.append({
    "check": "Active 1",
    "status": "red" if flags else "green",
    "values": {
        "total_sims_in_view":     int(total),
        "active_0_30_days":       int(active_30),
        "semi_active_31_60_days": int(semi_active),
        "inactive_over_60_days":  int(over_60),
        "never_used":             int(never_used),
        "used_in_last_1_day":     int(used_yesterday),
        "never_used_vs_same_day_last_month": never_used_mtd_trend,

        "new_subs_yesterday":            new_subs_yest,
        "new_subs_active1_yesterday":    new_active1_yest,
        "new_subs_active1_rate_yesterday": f"{new_active1_rate_yest:.1f}%" if new_active1_rate_yest is not None else "N/A",
        "new_subs_day_before":           new_subs_prev,
        "new_subs_active1_day_before":   new_active1_prev,
        "new_subs_active1_rate_day_before": f"{new_active1_rate_prev:.1f}%" if new_active1_rate_prev is not None else "N/A",
        "pct_new_subs_vs_day_before":         drastic(new_subs_yest, new_subs_prev, "New subscribers"),
        "pct_new_subs_active1_vs_day_before": drastic(new_active1_yest, new_active1_prev, "New-subscriber Active 1 count"),

        "cohort_2_4_days_active_yesterday":  cohort_active_yest,
        "cohort_2_4_days_active_avg_prior_7d": round(cohort_active_avg_7d) if cohort_active_avg_7d is not None else None,
        "pct_cohort_2_4_days_active_vs_7d_avg": drastic(cohort_active_yest, cohort_active_avg_7d, "Day 2-4 registration-activity cohort"),

        "cohort_day30_total":        day30_total,
        "cohort_day30_active7_count": day30_active7,
        "cohort_day30_active7_rate": f"{day30_active7_rate:.1f}%" if day30_active7_rate is not None else "N/A",
        "cohort_day30_active7_same_period_last_month": day30_active7_same_period_lm,

        "mtd_new_subs":              mtd_new,
        "mtd_new_subs_active1":      mtd_new_active1,
        "mtd_active1_rate":          f"{(mtd_new_active1 / mtd_new * 100):.1f}%" if mtd_new else "N/A",
        "prev_mtd_new_subs":         pmtd_new,
        "prev_mtd_new_subs_active1": pmtd_new_active1,
        "prev_mtd_active1_rate":    f"{(pmtd_new_active1 / pmtd_new * 100):.1f}%" if pmtd_new else "N/A",
        "pct_mtd_active1_vs_prev_mtd": drastic(mtd_new_active1, pmtd_new_active1, "MTD Active 1"),
    },
    "flags": flags,
})

# ── DIM Subscriber Alignment ──────────────────────────────────────────────────
dim_active = scalar("""
    SELECT COUNT(*) FROM UCONNECT_DW.ANALYTICS.DIM_SUBSCRIBERS
    WHERE TERMINATION_DATE IS NULL OR TERMINATION_DATE > CURRENT_DATE
""")
# MASTER_TENANT filter is required — UCONNECT_MAY_MERGE holds both uConnect and ME&YOU rows,
# and the un-filtered total was inflating this check's active count (and hence its spread vs
# DIM_SUBSCRIBERS/VW_ACTIVE, which are Uconnect-only) by roughly ME&YOU's active count.
mrg_active = scalar("""
    SELECT COUNT(*) FROM UCONNECT_DW.ANALYTICS.UCONNECT_MAY_MERGE
    WHERE (TERMINATION_DATE IS NULL OR TERMINATION_DATE > CURRENT_DATE)
      AND MASTER_TENANT = 'uConnect'
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

# 1:1 check — active (non-terminated), uConnect-only rows should have one row per ACCOUNT_NUMBER
# and one row per ICCID. DUP_*_ENTITIES = distinct keys that appear more than once;
# DUP_*_ROWS = total rows those duplicated keys account for (always >= 2x the entity count).
dup_account_entities, dup_account_rows, dup_iccid_entities, dup_iccid_rows = q("""
    WITH active_uconnect AS (
        SELECT ACCOUNT_NUMBER, ICCID
        FROM UCONNECT_DW.ANALYTICS.UCONNECT_MAY_MERGE
        WHERE (TERMINATION_DATE IS NULL OR TERMINATION_DATE > CURRENT_DATE)
          AND MASTER_TENANT = 'uConnect'
    )
    SELECT
        (SELECT COUNT(*) FROM (SELECT ACCOUNT_NUMBER FROM active_uconnect GROUP BY ACCOUNT_NUMBER HAVING COUNT(*) > 1)),
        COALESCE((SELECT SUM(cnt) FROM (SELECT COUNT(*) AS cnt FROM active_uconnect GROUP BY ACCOUNT_NUMBER HAVING COUNT(*) > 1)), 0),
        (SELECT COUNT(*) FROM (SELECT ICCID FROM active_uconnect GROUP BY ICCID HAVING COUNT(*) > 1)),
        COALESCE((SELECT SUM(cnt) FROM (SELECT COUNT(*) AS cnt FROM active_uconnect GROUP BY ICCID HAVING COUNT(*) > 1)), 0)
""")[0]
dup_account_entities, dup_account_rows = int(dup_account_entities), int(dup_account_rows)
dup_iccid_entities, dup_iccid_rows = int(dup_iccid_entities), int(dup_iccid_rows)
if dup_account_entities > 100:
    flags.append(f"{dup_account_entities:,} ACCOUNT_NUMBERs appear more than once among active uConnect records ({dup_account_rows:,} rows total) — exceeds 100 threshold")
if dup_iccid_entities > 100:
    flags.append(f"{dup_iccid_entities:,} ICCIDs appear more than once among active uConnect records ({dup_iccid_rows:,} rows total) — exceeds 100 threshold")

automated.append({
    "check": "DIM Subscriber Alignment",
    "status": "red" if flags else "green",
    "values": {
        "VW_ACTIVE_SUBSCRIPTIONS_snapshot": act_snapshot,
        "DIM_SUBSCRIBERS_active":           int(dim_active),
        "UCONNECT_MAY_MERGE_active_uConnect_only": int(mrg_active),
        "spread":                           int(spread),
        "duplicate_account_numbers":        dup_account_entities,
        "duplicate_account_number_rows":    dup_account_rows,
        "duplicate_iccids":                 dup_iccid_entities,
        "duplicate_iccid_rows":             dup_iccid_rows,
    },
    "flags": flags,
})

# ── Terminations ───────────────────────────────────────────────────────────────
# Switched from the ">60 day no usage" proxy to actual TERMINATION_DATE counts (uConnect only),
# per the 2026-07-22 threshold change request: flag RED if this month's terminations are
# LOWER than (avg of the last 2 months + 500) — a drop below normal churn-processing volume,
# not a spike, is what's being watched for here.
mtd_term, pmtd_term, p2mtd_term = q("""
    SELECT
        SUM(CASE WHEN TERMINATION_DATE BETWEEN %s AND %s AND MASTER_TENANT = 'uConnect' THEN 1 ELSE 0 END),
        SUM(CASE WHEN TERMINATION_DATE BETWEEN %s AND %s AND MASTER_TENANT = 'uConnect' THEN 1 ELSE 0 END),
        SUM(CASE WHEN TERMINATION_DATE BETWEEN %s AND %s AND MASTER_TENANT = 'uConnect' THEN 1 ELSE 0 END)
    FROM UCONNECT_DW.ANALYTICS.UCONNECT_MAY_MERGE
""", str(month_start_current), str(yesterday), str(month_start_prior), str(same_day_lm), str(month_start_2prior), str(same_day_2lm))[0]
mtd_term, pmtd_term, p2mtd_term = int(mtd_term or 0), int(pmtd_term or 0), int(p2mtd_term or 0)

term_baseline = (pmtd_term + p2mtd_term) / 2
term_threshold = term_baseline + 500

flags = []
if mtd_term < term_threshold:
    flags.append(
        f"{mtd_term:,} terminations MTD is below the (avg of last 2 months + 500) threshold of {term_threshold:,.0f} "
        f"— avg of {pmtd_term:,} and {p2mtd_term:,} = {term_baseline:,.0f}"
    )
# Data-shape caveat: terminations look batch-processed within a month rather than flowing evenly
# day-by-day (e.g. 2026-05-01..05-21 had only 1,088 vs 26,879 for the full month of May) — a
# day-of-month-cutoff MTD comparison, which works fine for recharges/sales, may not be reliable
# here. Surfacing this rather than silently trusting the cutoff-based comparison above.
status = "red" if flags else "amber"
if not flags:
    flags.append(
        "No red flag on the MTD-vs-threshold rule, but termination dates look batch-applied within "
        "a month rather than flowing evenly day-by-day (e.g. 2026-05-01 to 05-21 had only 1,088 "
        "terminations vs 26,879 for the full month of May) — a day-of-month-cutoff MTD comparison "
        "may not be a reliable read on this metric the way it is for recharges/sales. Worth confirming "
        "with the data team whether termination processing runs in batches before trusting this trend."
    )

automated.append({
    "check": "Terminations",
    "status": status,
    "values": {
        "mtd_terminations":            mtd_term,
        "prev_mtd_terminations":       pmtd_term,
        "two_months_ago_mtd_terminations": p2mtd_term,
        "baseline_avg_last_2_months":  round(term_baseline),
        "threshold_baseline_plus_500": round(term_threshold),
        "sims_over_60_days_no_usage_proxy": int(over_60),
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
    {
        "check": "QOS by Tenant & Store (Active 1, Day 2-4)",
        "status": "manual",
        "note": "Cross-check Active 1 quality-of-sales by tenant and store on the Telco dashboard's Sales page — not available via the Uconnect Snowflake schema.",
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
