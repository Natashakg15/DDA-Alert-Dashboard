"""
DDA Daily BI Checks — Snowflake runner.
Produces results.json consumed by the HTML dashboard.
"""

import json
import os
import sys
from datetime import date, timedelta

import snowflake.connector

# ---------------------------------------------------------------------------
# Connection — driven entirely by environment variables (set in GitHub Secrets)
# ---------------------------------------------------------------------------
def get_conn():
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
        database="UCONNECT_DW",
        schema="ANALYTICS",
        role=os.environ.get("SNOWFLAKE_ROLE", ""),
    )


def scalar(cur, sql, params=None):
    cur.execute(sql, params or [])
    row = cur.fetchone()
    return row[0] if row else None


def rows(cur, sql, params=None):
    cur.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Individual check helpers
# ---------------------------------------------------------------------------

TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)
TWO_DAYS_AGO = TODAY - timedelta(days=2)
SAME_DAY_LAST_MONTH = TODAY.replace(day=TODAY.day) - timedelta(days=30)


def check_cell_c_recharges(cur):
    """Cell C recharges are in line with the previous day."""
    results = []

    # Today's recharge count
    today_count = scalar(cur, """
        SELECT COUNT(*)
        FROM "UCONNECT_DW"."ANALYTICS"."VW_CELLC_RECHARGES"
        WHERE TRANSACTION_DATE::DATE = %s
    """, [str(TODAY)])

    # Yesterday's recharge count
    yesterday_count = scalar(cur, """
        SELECT COUNT(*)
        FROM "UCONNECT_DW"."ANALYTICS"."VW_CELLC_RECHARGES"
        WHERE TRANSACTION_DATE::DATE = %s
    """, [str(YESTERDAY)])

    # Same day last month
    last_month_count = scalar(cur, """
        SELECT COUNT(*)
        FROM "UCONNECT_DW"."ANALYTICS"."VW_CELLC_RECHARGES"
        WHERE TRANSACTION_DATE::DATE = %s
    """, [str(SAME_DAY_LAST_MONTH)])

    # Today revenue sum via merge table
    today_rev = scalar(cur, """
        SELECT SUM(REVENUE_CELLC_RECHARGE_QUANTITY)
        FROM "UCONNECT_DW"."ANALYTICS"."UCONNECT_MAY_MERGE_REVENUE"
        WHERE TRANSACTION_DATE >= %s AND TRANSACTION_DATE < %s
    """, [str(TODAY), str(TODAY + timedelta(days=1))])

    status = "green"
    flags = []

    if not today_count or today_count == 0:
        status = "red"
        flags.append("No recharges recorded for today")
    else:
        if yesterday_count and yesterday_count > 0:
            pct_vs_yesterday = today_count / yesterday_count
            if pct_vs_yesterday < 0.40:
                status = "red"
                flags.append(
                    f"Today ({today_count:,}) is {round((1-pct_vs_yesterday)*100)}% "
                    f"less than yesterday ({yesterday_count:,}) — exceeds 60% drop threshold"
                )
        if last_month_count and last_month_count > 0:
            pct_vs_lm = today_count / last_month_count
            if pct_vs_lm < 0.80:
                status = "red"
                flags.append(
                    f"Today ({today_count:,}) is {round((1-pct_vs_lm)*100)}% "
                    f"less than same day last month ({last_month_count:,}) — exceeds 20% drop threshold"
                )

    return {
        "check": "Cell C Recharges",
        "status": status,
        "values": {
            "today_count": today_count,
            "yesterday_count": yesterday_count,
            "same_day_last_month_count": last_month_count,
            "today_revenue_sum": float(today_rev) if today_rev else None,
        },
        "flags": flags,
    }


def check_wholesale_usage(cur):
    """Wholesale usage is not lagging and within normal ranges."""
    status = "green"
    flags = []

    # Today total
    today_total = scalar(cur, """
        SELECT COUNT(*)
        FROM "UCONNECT_DW"."ANALYTICS"."VW_WHOLESALE_USAGE"
        WHERE USAGE_DATE::DATE = %s
    """, [str(TODAY)])

    yesterday_total = scalar(cur, """
        SELECT COUNT(*)
        FROM "UCONNECT_DW"."ANALYTICS"."VW_WHOLESALE_USAGE"
        WHERE USAGE_DATE::DATE = %s
    """, [str(YESTERDAY)])

    last_month_total = scalar(cur, """
        SELECT COUNT(*)
        FROM "UCONNECT_DW"."ANALYTICS"."VW_WHOLESALE_USAGE"
        WHERE USAGE_DATE::DATE = %s
    """, [str(SAME_DAY_LAST_MONTH)])

    # Per USAGE_TYPE today
    today_by_type = rows(cur, """
        SELECT USAGE_TYPE, COUNT(*) AS CNT
        FROM "UCONNECT_DW"."ANALYTICS"."VW_WHOLESALE_USAGE"
        WHERE USAGE_DATE::DATE = %s
        GROUP BY USAGE_TYPE
    """, [str(TODAY)])

    yesterday_by_type = rows(cur, """
        SELECT USAGE_TYPE, COUNT(*) AS CNT
        FROM "UCONNECT_DW"."ANALYTICS"."VW_WHOLESALE_USAGE"
        WHERE USAGE_DATE::DATE = %s
        GROUP BY USAGE_TYPE
    """, [str(YESTERDAY)])

    last_month_by_type = rows(cur, """
        SELECT USAGE_TYPE, COUNT(*) AS CNT
        FROM "UCONNECT_DW"."ANALYTICS"."VW_WHOLESALE_USAGE"
        WHERE USAGE_DATE::DATE = %s
        GROUP BY USAGE_TYPE
    """, [str(SAME_DAY_LAST_MONTH)])

    if not today_total or today_total == 0:
        status = "red"
        flags.append("No wholesale usage records for today")
    else:
        if yesterday_total and yesterday_total > 0:
            pct = today_total / yesterday_total
            if pct < 0.40:
                status = "red"
                flags.append(
                    f"Total today ({today_total:,}) is {round((1-pct)*100)}% less than yesterday ({yesterday_total:,})"
                )
        if last_month_total and last_month_total > 0:
            pct = today_total / last_month_total
            if pct < 0.80:
                status = "red"
                flags.append(
                    f"Total today ({today_total:,}) is {round((1-pct)*100)}% less than same day last month ({last_month_total:,})"
                )

    # Per-type checks
    yest_map = {r["USAGE_TYPE"]: r["CNT"] for r in yesterday_by_type}
    lm_map = {r["USAGE_TYPE"]: r["CNT"] for r in last_month_by_type}
    type_detail = []

    for r in today_by_type:
        ut = r["USAGE_TYPE"]
        cnt = r["CNT"]
        t_status = "green"
        t_flags = []

        if ut in yest_map and yest_map[ut] > 0:
            pct = cnt / yest_map[ut]
            if pct < 0.40:
                t_status = "red"
                t_flags.append(f"{round((1-pct)*100)}% less than yesterday")
                status = "red"
                flags.append(f"USAGE_TYPE '{ut}': {round((1-pct)*100)}% below yesterday")

        if ut in lm_map and lm_map[ut] > 0:
            pct = cnt / lm_map[ut]
            if pct < 0.80:
                t_status = "red"
                t_flags.append(f"{round((1-pct)*100)}% less than same day last month")
                status = "red"
                flags.append(f"USAGE_TYPE '{ut}': {round((1-pct)*100)}% below same day last month")

        # Outlier: type present yesterday but completely absent today
        if ut not in [r2["USAGE_TYPE"] for r2 in today_by_type] and ut in yest_map:
            t_status = "red"
            t_flags.append("Usage type present yesterday but absent today")
            status = "red"
            flags.append(f"USAGE_TYPE '{ut}' is missing today (was {yest_map[ut]:,} yesterday)")

        type_detail.append({"type": ut, "today": cnt, "yesterday": yest_map.get(ut), "status": t_status, "flags": t_flags})

    # Types in yesterday but not today
    today_types = {r["USAGE_TYPE"] for r in today_by_type}
    for ut, cnt in yest_map.items():
        if ut not in today_types and cnt > 0:
            status = "red"
            flags.append(f"USAGE_TYPE '{ut}' had {cnt:,} records yesterday but is absent today")
            type_detail.append({"type": ut, "today": 0, "yesterday": cnt, "status": "red", "flags": ["Missing today"]})

    return {
        "check": "Wholesale Usage",
        "status": status,
        "values": {
            "today_total": today_total,
            "yesterday_total": yesterday_total,
            "same_day_last_month_total": last_month_total,
            "by_type": type_detail,
        },
        "flags": flags,
    }


def check_active1(cur):
    """Active 1 subscriber count is in line."""
    status = "green"
    flags = []

    today_count = scalar(cur, """
        SELECT COUNT(*)
        FROM "UCONNECT_DW"."ANALYTICS"."VW_ACTIVE_SUBSCRIPTIONS_USAGE_DETAILS"
        WHERE DATE_TRUNC('DAY', LAST_UPDATED)::DATE = %s
    """, [str(TODAY)])

    yesterday_count = scalar(cur, """
        SELECT COUNT(*)
        FROM "UCONNECT_DW"."ANALYTICS"."VW_ACTIVE_SUBSCRIPTIONS_USAGE_DETAILS"
        WHERE DATE_TRUNC('DAY', LAST_UPDATED)::DATE = %s
    """, [str(YESTERDAY)])

    if not today_count or today_count == 0:
        status = "red"
        flags.append("No Active 1 records for today")
    else:
        if yesterday_count and yesterday_count > 0:
            pct = today_count / yesterday_count
            if pct < 0.40:
                status = "red"
                flags.append(
                    f"Active 1 today ({today_count:,}) is {round((1-pct)*100)}% less than yesterday ({yesterday_count:,})"
                )
        # Sanity: more than 2x yesterday is also suspicious
        if yesterday_count and yesterday_count > 0:
            pct = today_count / yesterday_count
            if pct > 2.0:
                status = "red"
                flags.append(
                    f"Active 1 today ({today_count:,}) is more than 2× yesterday ({yesterday_count:,}) — may be amiss"
                )

    return {
        "check": "Active 1",
        "status": status,
        "values": {"today_count": today_count, "yesterday_count": yesterday_count},
        "flags": flags,
    }


def check_smartconnect_vs_dw(cur):
    """SmartConnect RICAs vs merge table and DIM_SUBSCRIBERS are aligned."""
    status = "green"
    flags = []

    # SmartConnect RICAs for yesterday
    sc_count = scalar(cur, """
        SELECT COUNT(*)
        FROM "UCONNECT_DW"."ANALYTICS"."VW_SC_RICA_REPORT"
        WHERE ACTIVATION_DATETIME >= %s AND ACTIVATION_DATETIME < %s
    """, [str(YESTERDAY), str(TODAY)])

    # Merge table RICAs for yesterday
    merge_count = scalar(cur, """
        SELECT COUNT(*)
        FROM "UCONNECT_DW"."ANALYTICS"."UCONNECT_MAY_MERGE"
        WHERE ACTIVATION_DATE = %s
    """, [str(YESTERDAY)])

    diff = abs((sc_count or 0) - (merge_count or 0))
    if diff > 10:
        status = "red"
        flags.append(
            f"SmartConnect RICAs ({sc_count:,}) differ from merge table ({merge_count:,}) by {diff} — exceeds 10 threshold"
        )

    # Per-tenant check: SmartConnect > merge for known retailers
    tenants_sc = rows(cur, """
        SELECT UPPER(TENANT_NAME) AS TENANT, COUNT(*) AS CNT
        FROM "UCONNECT_DW"."ANALYTICS"."VW_SC_RICA_REPORT"
        WHERE ACTIVATION_DATETIME >= %s AND ACTIVATION_DATETIME < %s
        GROUP BY UPPER(TENANT_NAME)
    """, [str(YESTERDAY), str(TODAY)])

    tenants_merge = rows(cur, """
        SELECT UPPER(RETAILER_NAME) AS TENANT, COUNT(*) AS CNT
        FROM "UCONNECT_DW"."ANALYTICS"."UCONNECT_MAY_MERGE"
        WHERE ACTIVATION_DATE = %s
        GROUP BY UPPER(RETAILER_NAME)
    """, [str(YESTERDAY)])

    merge_tenant_map = {r["TENANT"]: r["CNT"] for r in tenants_merge}
    tenant_detail = []

    watched_tenants = {"SPAR", "BUILD IT", "MIDAS", "PET POOL AND HOME", "PET POOL", "HOME"}

    for r in tenants_sc:
        t = r["TENANT"]
        sc_cnt = r["CNT"]
        m_cnt = merge_tenant_map.get(t, 0)
        t_status = "green"
        t_flags = []

        if sc_cnt > m_cnt:
            is_watched = any(w in t for w in watched_tenants)
            if is_watched or sc_cnt - m_cnt > 5:
                t_status = "red"
                t_flags.append(f"SmartConnect ({sc_cnt}) > merge ({m_cnt}) for tenant '{t}'")
                status = "red"
                flags.append(f"Tenant '{t}': SmartConnect has {sc_cnt - m_cnt} more RICAs than merge table")

        tenant_detail.append({"tenant": t, "sc": sc_cnt, "merge": m_cnt, "status": t_status, "flags": t_flags})

    return {
        "check": "SmartConnect vs Datawarehouse",
        "status": status,
        "values": {
            "sc_total": sc_count,
            "merge_total": merge_count,
            "difference": diff,
            "by_tenant": tenant_detail,
        },
        "flags": flags,
    }


def check_dim_subscriber(cur):
    """DIM_SUBSCRIBERS, merge table, and active subscriptions view are aligned."""
    status = "green"
    flags = []

    dim_count = scalar(cur, """
        SELECT COUNT(*)
        FROM "UCONNECT_DW"."ANALYTICS"."DIM_SUBSCRIBERS"
        WHERE CREATE_DATE = %s
    """, [str(YESTERDAY)])

    merge_count = scalar(cur, """
        SELECT COUNT(*)
        FROM "UCONNECT_DW"."ANALYTICS"."UCONNECT_MAY_MERGE"
        WHERE ACTIVATION_DATE = %s
    """, [str(YESTERDAY)])

    active_count = scalar(cur, """
        SELECT COUNT(*)
        FROM "UCONNECT_DW"."ANALYTICS"."VW_ACTIVE_SUBSCRIPTIONS_USAGE_DETAILS"
        WHERE DATE_TRUNC('DAY', ACTIVATION_DATE)::DATE = %s
    """, [str(YESTERDAY)])

    counts = {"DIM_SUBSCRIBERS": dim_count, "MERGE_TABLE": merge_count, "ACTIVE_SUBSCRIPTIONS": active_count}

    # Any blank while others are not
    non_null = {k: v for k, v in counts.items() if v is not None and v > 0}
    null_keys = [k for k, v in counts.items() if not v or v == 0]

    if null_keys and non_null:
        status = "red"
        flags.append(f"These tables returned 0/NULL while others had data: {', '.join(null_keys)}")

    # Divergence > 15
    values = [v for v in counts.values() if v is not None]
    if len(values) >= 2:
        spread = max(values) - min(values)
        if spread > 15:
            status = "red"
            flags.append(
                f"Spread across tables is {spread} (max diff threshold: 15). "
                f"DIM={dim_count}, MERGE={merge_count}, ACTIVE={active_count}"
            )

    return {
        "check": "DIM Subscriber Alignment",
        "status": status,
        "values": counts,
        "flags": flags,
    }


def check_cdrs(cur):
    """Wholesale CDRs have been received (not lagging)."""
    status = "green"
    flags = []

    # Check if file recon records exist for 2 days ago
    recon_count = scalar(cur, """
        SELECT COUNT(*)
        FROM "DATAWAREHOUSE"."MVNX"."UC_FILE_RECON"
        WHERE FILE_DATE::DATE = %s
    """, [str(TWO_DAYS_AGO)])

    if not recon_count or recon_count == 0:
        status = "red"
        flags.append(
            f"No CDR recon records in DATAWAREHOUSE.MVNX.UC_FILE_RECON for {TWO_DAYS_AGO} — CDRs may be lagging"
        )

    return {
        "check": "CDRs (Wholesale)",
        "status": status,
        "values": {"recon_count_2days_ago": recon_count},
        "flags": flags,
    }


def check_terminations(cur):
    """SIMs with usage more than 60 days ago is less than 3,000."""
    status = "green"
    flags = []

    count = scalar(cur, """
        SELECT COUNT(ACCOUNT_NUMBER)
        FROM "UCONNECT_DW"."ANALYTICS"."VW_ACTIVE_SUBSCRIPTIONS_USAGE_DETAILS"
        WHERE USAGE_GREATER_THAN_60_DAYS = '1'
    """)

    if count is None:
        status = "red"
        flags.append("Query returned NULL — view may not be refreshed")
    elif count > 3000:
        status = "red"
        flags.append(f"SIMs with usage >60 days ago: {count:,} — exceeds 3,000 threshold")
    elif count > 2700:
        # Approaching threshold — warn but not red
        flags.append(f"SIMs with usage >60 days ago: {count:,} — approaching 3,000 threshold (currently amber)")
        status = "amber"

    return {
        "check": "Terminations (>60 day usage)",
        "status": status,
        "values": {"sims_over_60_days": count},
        "flags": flags,
    }


def check_warehouse_freshness(cur):
    """Key warehouse tables have been updated today."""
    status = "green"
    flags = []

    tables = [
        ("UCONNECT_DW", "ANALYTICS", "VW_CELLC_RECHARGES"),
        ("UCONNECT_DW", "ANALYTICS", "VW_WHOLESALE_USAGE"),
        ("UCONNECT_DW", "ANALYTICS", "DIM_SUBSCRIBERS"),
        ("UCONNECT_DW", "ANALYTICS", "UCONNECT_MAY_MERGE"),
        ("UCONNECT_DW", "ANALYTICS", "VW_SC_RICA_REPORT"),
        ("UCONNECT_DW", "ANALYTICS", "VW_ACTIVE_SUBSCRIPTIONS_USAGE_DETAILS"),
    ]

    table_results = []
    for db, schema, tbl in tables:
        last_updated = scalar(cur, f"""
            SELECT MAX(LAST_ALTERED)
            FROM "{db}".INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = '{schema}' AND TABLE_NAME = '{tbl}'
        """)
        is_fresh = last_updated and last_updated.date() >= TODAY
        t_status = "green" if is_fresh else "red"
        if not is_fresh:
            status = "red"
            flags.append(f"{tbl} last altered {last_updated} — not updated today")
        table_results.append({
            "table": f"{db}.{schema}.{tbl}",
            "last_updated": str(last_updated) if last_updated else "unknown",
            "status": t_status,
        })

    return {
        "check": "Warehouse Freshness",
        "status": status,
        "values": {"tables": table_results},
        "flags": flags,
    }


# ---------------------------------------------------------------------------
# Manual-only checks (cannot be verified in Snowflake)
# ---------------------------------------------------------------------------
MANUAL_CHECKS = [
    {
        "check": "Telco Platform — Recharges Telco UI",
        "status": "manual",
        "note": "Requires manual verification on Telco platform — not accessible via Snowflake",
        "flags": [],
    },
    {
        "check": "Cell C Recharges — Telco Dashboard Alignment",
        "status": "manual",
        "note": "Dashboard-level check — verify on Telco BI dashboard",
        "flags": [],
    },
    {
        "check": "CDR PowerBI Dashboard",
        "status": "manual",
        "note": "Verify on PowerBI: https://app.powerbi.com/groups/me/reports/99160c3f-a907-43c4-a499-c701fdf5daf2",
        "flags": [],
    },
    {
        "check": "Wholesale Usage — Telco Dashboard",
        "status": "manual",
        "note": "Cross-check usage totals on Telco dashboard",
        "flags": [],
    },
]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def run_all_checks():
    conn = get_conn()
    cur = conn.cursor()

    automated = []
    errors = []

    check_fns = [
        check_cell_c_recharges,
        check_wholesale_usage,
        check_active1,
        check_smartconnect_vs_dw,
        check_dim_subscriber,
        check_cdrs,
        check_terminations,
        check_warehouse_freshness,
    ]

    for fn in check_fns:
        try:
            result = fn(cur)
            automated.append(result)
        except Exception as e:
            errors.append({"check": fn.__name__, "error": str(e), "status": "error"})

    cur.close()
    conn.close()

    output = {
        "run_date": str(TODAY),
        "run_time": None,  # stamped after return
        "automated": automated,
        "manual": MANUAL_CHECKS,
        "errors": errors,
    }
    return output


if __name__ == "__main__":
    from datetime import datetime
    result = run_all_checks()
    result["run_time"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    with open("results.json", "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"Done. {len(result['automated'])} automated checks, {len(result['errors'])} errors.")
    if result["errors"]:
        for e in result["errors"]:
            print(f"  ERROR in {e['check']}: {e['error']}", file=sys.stderr)
