"""Fetch User and ChatMessagePair sheets from Google Sheets, trim sensitive columns, save as CSV."""
import gspread
import csv
import os
import json
import time
from datetime import datetime, timezone, timedelta

# 2026-08-27の日次実行がSheets APIの一時エラー(409 "The operation was aborted")1発で
# 丸1日停止したため、一時エラーはリトライで自己回復させる
RETRY_STATUS = {409, 429, 500, 502, 503, 504}
RETRY_ATTEMPTS = 3


def fetch_all_values(spreadsheet, tab_name):
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            return spreadsheet.worksheet(tab_name).get_all_values()
        except gspread.exceptions.APIError as e:
            status = e.response.status_code if e.response is not None else None
            if status not in RETRY_STATUS or attempt == RETRY_ATTEMPTS:
                raise
            wait = 30 * (2 ** (attempt - 1))  # 30s, 60s
            print(f"{tab_name}: APIError {status} (attempt {attempt}/{RETRY_ATTEMPTS}), retrying in {wait}s")
            time.sleep(wait)

import base64
SA_JSON_B64 = os.environ["SERVICE_ACCOUNT_JSON"]
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
# Secret is base64-encoded to avoid JSON escaping issues
sa_info = json.loads(base64.b64decode(SA_JSON_B64).decode("utf-8"))
gc = gspread.service_account_from_dict(sa_info)
sh = gc.open_by_key(SHEET_ID)

# --- User ---
all_data = fetch_all_values(sh, "User")
header = all_data[0]
keep_idx = [i for i, h in enumerate(header) if h not in USER_EXCLUDE]
out1 = os.path.join(DATA_DIR, f"raw_kpi - User{today_mmdd}.csv")
with open(out1, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    for row in all_data:
        w.writerow([row[i] for i in keep_idx])
print(f"User: {len(all_data)-1} rows -> {out1}")

# --- ChatMessagePair ---
all_data2 = fetch_all_values(sh, "ChatMessagePair")
header2 = all_data2[0]
keep_idx2 = [i for i, h in enumerate(header2) if h not in CMP_EXCLUDE][:14]
out2 = os.path.join(DATA_DIR, f"raw_kpi - ChatMessagePair{today_mmdd}.csv")
with open(out2, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    for row in all_data2:
        w.writerow([row[i] if i < len(row) else "" for i in keep_idx2])
print(f"ChatMessagePair: {len(all_data2)-1} rows -> {out2}")

# --- LoginHistory (2026-07-24追加: ログインベース参考版用。列=id/__typename/createdAt/updatedAt/userId、PIIなし) ---
all_data3 = fetch_all_values(sh, "LoginHistory")
out3 = os.path.join(DATA_DIR, f"raw_kpi - LoginHistory{today_mmdd}.csv")
with open(out3, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    for row in all_data3:
        w.writerow(row)
print(f"LoginHistory: {len(all_data3)-1} rows -> {out3}")

# Export DATA_END_DATE for next step
with open(os.environ["GITHUB_ENV"], "a") as env_file:
    env_file.write(f"DATA_END_DATE={data_end}\n")
print(f"DATA_END_DATE={data_end}")
