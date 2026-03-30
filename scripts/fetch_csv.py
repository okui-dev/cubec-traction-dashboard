"""Fetch User and ChatMessagePair sheets from Google Sheets, trim sensitive columns, save as CSV."""
import gspread
import csv
import os
import json
from datetime import datetime, timezone, timedelta

SA_JSON = os.environ["SERVICE_ACCOUNT_JSON"]
SHEET_ID = "1gPIZiWiKxTenKOUtnO7b5OqI0UycQ0qbrdv_SkEcKg0"
DATA_DIR = "dashboard/data"

# JST = UTC+9. At UTC 16:00, JST is 01:00 next day.
# DATA_END = yesterday in JST = today in UTC (since cron runs at UTC 16:00)
jst = timezone(timedelta(hours=9))
now_jst = datetime.now(jst)
data_end = (now_jst - timedelta(days=1)).strftime("%Y-%m-%d")
today_mmdd = now_jst.strftime("%m%d")

# Columns to EXCLUDE (security: personal data / user content)
USER_EXCLUDE = {"email"}
CMP_EXCLUDE = {"content_q", "content_a", "responseTimeS", "user_role"}

# Auth via JSON string from GitHub Secret
sa_info = json.loads(SA_JSON)
gc = gspread.service_account_from_dict(sa_info)
sh = gc.open_by_key(SHEET_ID)

# --- User ---
ws = sh.worksheet("User")
all_data = ws.get_all_values()
header = all_data[0]
keep_idx = [i for i, h in enumerate(header) if h not in USER_EXCLUDE]
out1 = os.path.join(DATA_DIR, f"raw_kpi - User{today_mmdd}.csv")
with open(out1, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    for row in all_data:
        w.writerow([row[i] for i in keep_idx])
print(f"User: {len(all_data)-1} rows -> {out1}")

# --- ChatMessagePair ---
ws2 = sh.worksheet("ChatMessagePair")
all_data2 = ws2.get_all_values()
header2 = all_data2[0]
keep_idx2 = [i for i, h in enumerate(header2) if h not in CMP_EXCLUDE][:14]
out2 = os.path.join(DATA_DIR, f"raw_kpi - ChatMessagePair{today_mmdd}.csv")
with open(out2, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    for row in all_data2:
        w.writerow([row[i] if i < len(row) else "" for i in keep_idx2])
print(f"ChatMessagePair: {len(all_data2)-1} rows -> {out2}")

# Export DATA_END_DATE for next step
with open(os.environ["GITHUB_ENV"], "a") as env_file:
    env_file.write(f"DATA_END_DATE={data_end}\n")
print(f"DATA_END_DATE={data_end}")
