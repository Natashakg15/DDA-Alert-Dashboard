# DDA Daily BI Checks Dashboard

Automated daily checks against the Uconnect Snowflake data warehouse.  
The dashboard is published to **GitHub Pages** and updates every weekday morning at 07:00 SAST.

## Live dashboard

Once deployed, your dashboard URL will be:  
`https://<your-github-username>.github.io/<repo-name>/`

Share that link with your team — no login required.

---

## Checks covered

| Check | Source | Type |
|---|---|---|
| Cell C Recharges | `VW_CELLC_RECHARGES` + `UCONNECT_MAY_MERGE_REVENUE` | Automated |
| Wholesale Usage (total + per USAGE_TYPE) | `VW_WHOLESALE_USAGE` | Automated |
| Active 1 | `VW_ACTIVE_SUBSCRIPTIONS_USAGE_DETAILS` | Automated |
| SmartConnect vs DW (total + per tenant) | `VW_SC_RICA_REPORT` vs `UCONNECT_MAY_MERGE` | Automated |
| DIM Subscriber alignment | `DIM_SUBSCRIBERS` / `UCONNECT_MAY_MERGE` / `VW_ACTIVE_SUBSCRIPTIONS_USAGE_DETAILS` | Automated |
| CDR Recon (UC_FILE_RECON) | `DATAWAREHOUSE.MVNX.UC_FILE_RECON` | Automated |
| Terminations (>60 day usage) | `VW_ACTIVE_SUBSCRIPTIONS_USAGE_DETAILS` | Automated |
| Warehouse freshness | `INFORMATION_SCHEMA.TABLES` | Automated |
| Telco platform checks | Telco UI / dashboards | **Manual** |
| CDR PowerBI report | PowerBI | **Manual** |

---

## Setup (one-time)

### 1. Create the GitHub repo

```bash
cd dda-dashboard
git init
git add .
git commit -m "init: DDA daily checks dashboard"
# create a new repo on github.com then:
git remote add origin https://github.com/<your-org>/<repo-name>.git
git push -u origin main
```

### 2. Add Snowflake credentials as GitHub Secrets

Go to your repo → **Settings → Secrets and variables → Actions → New repository secret** and add:

| Secret name | Value |
|---|---|
| `SNOWFLAKE_ACCOUNT` | e.g. `abc12345.eu-west-1` |
| `SNOWFLAKE_USER` | your Snowflake username |
| `SNOWFLAKE_PASSWORD` | your Snowflake password |
| `SNOWFLAKE_WAREHOUSE` | e.g. `COMPUTE_WH` |
| `SNOWFLAKE_ROLE` | e.g. `ANALYST` (or leave blank) |

### 3. Enable GitHub Pages

Go to repo → **Settings → Pages**  
- Source: **Deploy from a branch**  
- Branch: **gh-pages** / root  
- Save

### 4. Trigger the first run

Go to **Actions → DDA Daily BI Checks → Run workflow** to run it immediately.  
Your dashboard will be live at `https://<your-github-username>.github.io/<repo-name>/` within ~2 minutes.

---

## Schedule

Runs automatically **Monday–Friday at 05:00 UTC (07:00 SAST)**.  
You can also trigger manually from the Actions tab at any time.

---

## Flag thresholds

| Metric | Red condition |
|---|---|
| Cell C Recharges | No recharges yesterday, OR >20% drop vs same-day-last-month or same-day-2-months-ago (count or value), OR MTD vs prior-month MTD varies >10% (count or value), OR same-day-last-month vs same-day-2-months-ago varies >5% (count or value), OR abnormal 3-month MTD trend (>25% single-month swing, or >20% sustained same-direction move) |
| Wholesale Usage | No usage today, OR >60% drop total/per type vs yesterday, OR >20% drop vs same day last month, OR type missing |
| Active 1 | No count today, OR >60% drop vs yesterday, OR anomalous (>2× yesterday) |
| SmartConnect vs DW | Difference >10 total, OR SC > merge for any retail tenant |
| DIM Subscriber | Any table blank while others are not, OR spread >15 across tables |
| CDRs | No recon records in `UC_FILE_RECON` for 2 days ago |
| Terminations | >3,000 SIMs with usage >60 days ago |
| Warehouse Freshness | Any key table not updated today |
