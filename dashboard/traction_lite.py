"""
Traction Dashboard - Lightweight Edition
Charts 1-7 with supplementary metrics S1-S12. No pandas dependency.
"""
import csv
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

# ── Font setup (os.name to avoid platform.system() hang on Windows) ──
_os = "Windows" if os.name == "nt" else "Darwin" if os.name == "posix" and Path("/System").exists() else "Linux"
if _os == "Windows":
    _candidates = [
        r"C:\Windows\Fonts\meiryo.ttc",
        r"C:\Windows\Fonts\YuGothR.ttc",
        r"C:\Windows\Fonts\msgothic.ttc",
    ]
elif _os == "Darwin":
    _candidates = [
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
        "/Library/Fonts/NotoSansCJKjp-Regular.otf",
    ]
else:
    _candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansJP-Regular.ttf",
    ]

for _fpath in _candidates:
    if Path(_fpath).exists():
        _fp = fm.FontProperties(fname=_fpath)
        plt.rcParams["font.family"] = "sans-serif"
        plt.rcParams["font.sans-serif"] = [_fp.get_name()] + plt.rcParams["font.sans-serif"]
        break
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["axes.grid"] = True
plt.rcParams["grid.alpha"] = 0.3

# ── Settings ──
OUTPUT_DIR = Path(os.environ.get("TRACTION_OUTPUT_DIR", "output"))
OUTPUT_DIR.mkdir(exist_ok=True)

CSV_ENCODING = "utf-8-sig"


def find_latest_csv(pattern):
    """Find the latest CSV matching pattern in data/ directory."""
    import glob
    matches = sorted(glob.glob(str(Path("data") / pattern)))
    if not matches:
        raise FileNotFoundError(f"No CSV found matching data/{pattern}")
    latest = matches[-1]
    print(f"  Using: {latest}", flush=True)
    return Path(latest)


USER_CSV = find_latest_csv("raw_kpi - User*.csv")
ACTIVITY_CSV = find_latest_csv("raw_kpi - ChatMessagePair*.csv")

# Column detection: read headers and find by name
def detect_columns(csv_path, encoding="utf-8-sig"):
    """Read CSV header and return {column_name: index} mapping."""
    with open(csv_path, encoding=encoding, newline="") as f:
        reader = csv.reader(f)
        headers = next(reader)
    return {h.strip(): i for i, h in enumerate(headers)}

_user_cols = detect_columns(USER_CSV)
_act_cols = detect_columns(ACTIVITY_CSV)

USER_ID_COL = _user_cols.get("id", 0)
USER_CREATED_COL = _user_cols.get("createdAt", 2)
USER_ROLE_COL = _user_cols.get("role", 5)
# ── Doctor filter column detection ──
# CORRECT column: "doctorINfo名前無し or doctorINfoにIDなしで0" (strict: name+ID both present = 1)
# WRONG column:   "doctorIInfo" (loose flag — includes incomplete registrations)
# WARNING: These two columns coexist in the CSV. Using the wrong one inflates doctor count ~25%.
# Set ALL_USERS_MODE=1 env var to disable doctor filter for reference runs.
_STRICT_MARKER = "名前無し"  # unique substring that only appears in the strict column name
USER_DOCTOR_COL = None
_matched_col_name = None
if not os.environ.get("ALL_USERS_MODE"):
    for _col_name, _col_idx in _user_cols.items():
        if _STRICT_MARKER in _col_name:
            USER_DOCTOR_COL = _col_idx
            _matched_col_name = _col_name
            break
    if USER_DOCTOR_COL is None:
        print("  ERROR: Strict doctor filter column not found!", flush=True)
        print(f"  Available columns: {list(_user_cols.keys())}", flush=True)
        raise SystemExit("Cannot proceed without strict doctor filter. Check CSV column names.")
print(f"  User CSV columns: {len(_user_cols)}, doctor filter col: {USER_DOCTOR_COL}"
      f" ({_matched_col_name!r})", flush=True)

# ── Invitation column detection (for deemed-doctor logic) ──
# Users with Invitation >= 1 are treated as doctors even if doctorInfo == 0
USER_INVITATION_COL = _user_cols.get("Invitation")
if USER_INVITATION_COL is not None:
    print(f"  Invitation column found: col {USER_INVITATION_COL}", flush=True)
else:
    print("  WARNING: Invitation column not found. Deemed-doctor logic disabled.", flush=True)

ACT_CREATED_COL = _act_cols.get("createdAt", 3)
ACT_USERID_COL = _act_cols.get("userId", 4)

LOG_START = datetime(2025, 5, 31)
MILLE_START = datetime(2025, 11, 1)

# Targets (2026-06 end)
TARGET_DATE = datetime(2026, 6, 28)  # last Sunday of June 2026
TARGET_WAU = 500
TARGET_REG = 5000
TARGET_WAU_RATE = 10.0  # percent

# Heavy User (KGI) targets
TARGET_HEAVY = 200
TARGET_MAU_RATE = 20.0   # percent
TARGET_HEAVY_RATE = 20.0  # percent (heavy / MAU)

# Appendix: Pre-A minimum scenario (TARGET_HEAVY = 100)
APP_TARGET_HEAVY = 100
APP_TARGET_REG = 2500  # 100 / (20% × 20%)
APP_TARGET_MAU_RATE = 20.0
APP_TARGET_HEAVY_RATE = 20.0

# ── Weekly Search Volume targets (FIXED — do not recalculate) ──
# Derived from registration plan × active_rate(12.8%) × q_per_user(4.3)
# 社内向け: Registration plan 654→1437→2996→4217→5000
SEARCH_PLAN_MILESTONES = [
    (datetime(2026, 3, 1),   360),   # 654 × 0.128 × 4.3
    (datetime(2026, 3, 31),  790),   # 1437 × 0.128 × 4.3
    (datetime(2026, 4, 30), 1650),   # 2996 × 0.128 × 4.3
    (datetime(2026, 5, 31), 2320),   # 4217 × 0.128 × 4.3
    (datetime(2026, 6, 28), 2750),   # 5000 × 0.128 × 4.3
]
TARGET_WEEKLY_SEARCH = 2750

# 投資家向け: Registration plan (APP) 654→1045→1825→2435→2827
APP_SEARCH_PLAN_MILESTONES = [
    (datetime(2026, 3, 1),   360),   # 654 × 0.128 × 4.3
    (datetime(2026, 3, 31),  575),   # 1045 × 0.128 × 4.3
    (datetime(2026, 4, 30), 1005),   # 1825 × 0.128 × 4.3
    (datetime(2026, 5, 31), 1340),   # 2435 × 0.128 × 4.3
    (datetime(2026, 6, 28), 1555),   # 2827 × 0.128 × 4.3
]
APP_TARGET_WEEKLY_SEARCH = 1555

# ── Heavy User plan milestones (FIXED — 2026-04-20 CEO確定・今後変更禁止) ──
# (date, heavy_count, mau_rate%, heavy_rate%)
# 3/1 starting point = week-of-2026-03-02 actual (Heavy=22, MAU率=18.2%, Heavy化率=18.4%)
# heavy_count = reg_plan × mau_rate × heavy_rate (rates linear 18.2→20% / 18.4→20%)
# Main: TARGET_HEAVY=200, end rates 20%/20%
# ⚠️ これらの milestones は CEO確定値。実績やデータ更新で再計算しないこと。
HEAVY_PLAN_MILESTONES = [
    (datetime(2026, 3, 1),   22,  18.2, 18.4),  #  654 × 18.2% × 18.4%
    (datetime(2026, 3, 31),  50,  18.65, 18.80),  # 1437 × 18.65% × 18.80%
    (datetime(2026, 4, 30), 110,  19.11, 19.21),  # 2996 × 19.11% × 19.21%
    (datetime(2026, 5, 31), 162,  19.58, 19.62),  # 4217 × 19.58% × 19.62%
    (datetime(2026, 6, 28), 200,  20.0, 20.0),   # 5000 × 20% × 20%
]
# Appendix: Pre-A minimum scenario (APP_TARGET_HEAVY=100)
# heavy_count = app_reg_scaled × same rates (app_reg: 654→924→1614→2154→2500)
APP_HEAVY_PLAN_MILESTONES = [
    (datetime(2026, 3, 1),   22,  18.2, 18.4),
    (datetime(2026, 3, 31),  32,  18.65, 18.80),
    (datetime(2026, 4, 30),  59,  19.11, 19.21),
    (datetime(2026, 5, 31),  83,  19.58, 19.62),
    (datetime(2026, 6, 28), 100,  20.0, 20.0),
]

# Plan milestones from kpi-target-rationale.md (logistic curve model)
# (date, reg, wau_rate%, wau)
PLAN_MILESTONES = [
    (datetime(2026, 3, 1),  654,  6.6,  43),
    (datetime(2026, 3, 31), 1437, 8.0, 115),
    (datetime(2026, 4, 30), 2996, 8.9, 267),
    (datetime(2026, 5, 31), 4217, 9.5, 400),
    (datetime(2026, 6, 28), 5000, 10.0, 500),
]

# Plan B: conservative scenario (WAU=300, Reg=3000, WAU Rate=10%)
TARGET_WAU_B = 300
TARGET_REG_B = 3000
TARGET_WAU_RATE_B = 10.0
PLAN_B_MILESTONES = [
    (datetime(2026, 3, 1),  654,  6.6,   43),
    (datetime(2026, 3, 31), 925,  8.0,   74),
    (datetime(2026, 4, 30), 1455, 8.9,  129),
    (datetime(2026, 5, 31), 2140, 9.5,  203),
    (datetime(2026, 6, 28), 3000, 10.0, 300),
]

def interpolate_plan_weekly(milestones):
    """Interpolate monthly plan milestones to weekly (Monday) points."""
    plan_weeks, plan_reg, plan_rate, plan_wau = [], [], [], []
    first_mon = week_monday(milestones[0][0])
    last_mon = week_monday(milestones[-1][0])
    ms_days = [(m[0] - milestones[0][0]).days for m in milestones]
    w = first_mon
    while w <= last_mon + timedelta(days=6):
        d = (w - milestones[0][0]).days
        for i in range(len(ms_days) - 1):
            if ms_days[i] <= d <= ms_days[i + 1]:
                frac = (d - ms_days[i]) / (ms_days[i + 1] - ms_days[i]) if ms_days[i + 1] != ms_days[i] else 0
                plan_weeks.append(w)
                plan_reg.append(milestones[i][1] + frac * (milestones[i + 1][1] - milestones[i][1]))
                plan_rate.append(milestones[i][2] + frac * (milestones[i + 1][2] - milestones[i][2]))
                plan_wau.append(milestones[i][3] + frac * (milestones[i + 1][3] - milestones[i][3]))
                break
        w += timedelta(days=7)
    return plan_weeks, plan_wau, plan_reg, plan_rate

# Deferred: computed after week_monday is defined (see below)

# Cohort merging
MILLE_MERGES = {
    "2025-04~06": ["2025-04", "2025-05", "2025-06"],
    "2025-07~10": ["2025-07", "2025-08", "2025-09", "2025-10"],
}
MILLE_LABEL_MAP = {}
for label, months in MILLE_MERGES.items():
    for m in months:
        MILLE_LABEL_MAP[m] = label

RET_MERGE_MONTHS = {"2025-07", "2025-08", "2025-09", "2025-10"}
RET_MERGED_LABEL = "2025-07~10"


def parse_date(s):
    """Parse '2025-12-03T...' or '2025/12/03...' -> datetime"""
    return datetime.strptime(s[:10].replace("/", "-"), "%Y-%m-%d")


def week_monday(dt):
    """Monday of the week containing dt."""
    return datetime(dt.year, dt.month, dt.day) - timedelta(days=dt.weekday())


def cohort_month(dt):
    return dt.strftime("%Y-%m")


def next_month_start(dt):
    if dt.month == 12:
        return datetime(dt.year + 1, 1, 1)
    return datetime(dt.year, dt.month + 1, 1)


def week_range_label(monday):
    """Format week as 'M/D-M/D' showing Mon-Sun range."""
    sun = monday + timedelta(days=6)
    return f"{monday.month}/{monday.day}-{sun.month}/{sun.day}"


# Compute plan weekly now that week_monday is defined
PLAN_WEEKS, PLAN_WAU, PLAN_REG, PLAN_RATE = interpolate_plan_weekly(PLAN_MILESTONES)

# Appendix plan milestones: scale registration to APP_TARGET_REG (2500)
_app_scale = APP_TARGET_REG / PLAN_MILESTONES[-1][1]  # 2500/5000 = 0.5
APP_PLAN_MILESTONES = [
    (PLAN_MILESTONES[0][0], PLAN_MILESTONES[0][1], PLAN_MILESTONES[0][2], PLAN_MILESTONES[0][3]),
] + [
    (d, int(PLAN_MILESTONES[0][1] + (r - PLAN_MILESTONES[0][1]) * _app_scale), wr,
     int(PLAN_MILESTONES[0][3] + (w - PLAN_MILESTONES[0][3]) * _app_scale))
    for d, r, wr, w in PLAN_MILESTONES[1:]
]
APP_PLAN_WEEKS, _, APP_PLAN_REG, _ = interpolate_plan_weekly(APP_PLAN_MILESTONES)
PLAN_B_WEEKS, PLAN_B_WAU, PLAN_B_REG, PLAN_B_RATE = interpolate_plan_weekly(PLAN_B_MILESTONES)

# Search volume plan weekly interpolation
def interpolate_search_plan(milestones):
    """Interpolate (date, value) milestones to weekly (Monday) points."""
    weeks, values = [], []
    first_mon = week_monday(milestones[0][0])
    last_mon = week_monday(milestones[-1][0])
    ms_days = [(m[0] - milestones[0][0]).days for m in milestones]
    w = first_mon
    while w <= last_mon + timedelta(days=6):
        d = (w - milestones[0][0]).days
        for i in range(len(ms_days) - 1):
            if ms_days[i] <= d <= ms_days[i + 1]:
                frac = (d - ms_days[i]) / (ms_days[i + 1] - ms_days[i]) if ms_days[i + 1] != ms_days[i] else 0
                weeks.append(w)
                values.append(milestones[i][1] + frac * (milestones[i + 1][1] - milestones[i][1]))
                break
        w += timedelta(days=7)
    return weeks, values

SEARCH_PLAN_WEEKS, SEARCH_PLAN_VALS = interpolate_search_plan(SEARCH_PLAN_MILESTONES)
APP_SEARCH_PLAN_WEEKS, APP_SEARCH_PLAN_VALS = interpolate_search_plan(APP_SEARCH_PLAN_MILESTONES)

def interpolate_heavy_plan(milestones):
    """Interpolate heavy user plan milestones (date, heavy_count, mau_rate%, heavy_rate%) to weekly points."""
    weeks, heavy_vals, mau_rates, heavy_rates = [], [], [], []
    first_mon = week_monday(milestones[0][0])
    last_mon = week_monday(milestones[-1][0])
    ms_days = [(m[0] - milestones[0][0]).days for m in milestones]
    w = first_mon
    while w <= last_mon + timedelta(days=6):
        d = (w - milestones[0][0]).days
        for i in range(len(ms_days) - 1):
            if ms_days[i] <= d <= ms_days[i + 1]:
                frac = (d - ms_days[i]) / (ms_days[i + 1] - ms_days[i]) if ms_days[i + 1] != ms_days[i] else 0
                weeks.append(w)
                heavy_vals.append(milestones[i][1] + frac * (milestones[i + 1][1] - milestones[i][1]))
                mau_rates.append(milestones[i][2] + frac * (milestones[i + 1][2] - milestones[i][2]))
                heavy_rates.append(milestones[i][3] + frac * (milestones[i + 1][3] - milestones[i][3]))
                break
        w += timedelta(days=7)
    return weeks, heavy_vals, mau_rates, heavy_rates

HEAVY_PLAN_WEEKS, HEAVY_PLAN_VALS, HEAVY_PLAN_MAU_RATE, HEAVY_PLAN_HEAVY_RATE = interpolate_heavy_plan(HEAVY_PLAN_MILESTONES)
APP_HEAVY_PLAN_WEEKS, APP_HEAVY_PLAN_VALS, APP_HEAVY_PLAN_MAU_RATE, APP_HEAVY_PLAN_HEAVY_RATE = interpolate_heavy_plan(APP_HEAVY_PLAN_MILESTONES)

# ══════════════════════════════════════════════
# Load data
# ══════════════════════════════════════════════
print("Loading data...", flush=True)

user_reg = {}  # user_id -> registration_date
with open(USER_CSV, encoding=CSV_ENCODING, newline="") as f:
    reader = csv.reader(f)
    next(reader)  # skip header
    _deemed_doctor_count = 0
    for row in reader:
        if row[USER_ROLE_COL] != "user":
            continue
        # Doctor filter: doctorInfo == 1 OR Invitation >= 1 (deemed doctor)
        if USER_DOCTOR_COL is not None:
            is_certified = (row[USER_DOCTOR_COL] == "1")
            is_invited = False
            if USER_INVITATION_COL is not None and len(row) > USER_INVITATION_COL:
                try:
                    is_invited = (int(row[USER_INVITATION_COL]) >= 1)
                except (ValueError, IndexError):
                    pass
            if not is_certified and not is_invited:
                continue
            if not is_certified and is_invited:
                _deemed_doctor_count += 1
        user_reg[row[USER_ID_COL]] = parse_date(row[USER_CREATED_COL])

# ── Sanity check: detect anomalous doctor count ──
# Save last known count and warn if jump > 10% between runs.
_DOCTOR_COUNT_FILE = OUTPUT_DIR / ".last_doctor_count"
_current_doc_count = len(user_reg)
if _DOCTOR_COUNT_FILE.exists():
    try:
        _prev_count = int(_DOCTOR_COUNT_FILE.read_text().strip())
        if _prev_count > 0:
            _pct_change = abs(_current_doc_count - _prev_count) / _prev_count * 100
            if _pct_change > 10:
                print(f"  WARNING: Doctor count changed {_prev_count} -> {_current_doc_count}"
                      f" ({_pct_change:.1f}% change). Verify doctor filter column!", flush=True)
    except ValueError:
        pass
_DOCTOR_COUNT_FILE.write_text(str(_current_doc_count))

print(f"  Registered doctors: {_current_doc_count} (certified: {_current_doc_count - _deemed_doctor_count}, deemed via invitation: {_deemed_doctor_count})", flush=True)

# Email registrations (all role=user, no doctor filter) for reference metrics
email_reg = {}  # user_id -> createdAt
with open(USER_CSV, encoding=CSV_ENCODING, newline="") as f:
    reader = csv.reader(f)
    next(reader)
    for row in reader:
        if row[USER_ROLE_COL] != "user":
            continue
        email_reg[row[USER_ID_COL]] = parse_date(row[USER_CREATED_COL])

email_reg_by_week = defaultdict(int)
for rd in email_reg.values():
    email_reg_by_week[week_monday(rd)] += 1

# Cumulative email registrations
cum_email_reg = {}
_running_email = 0
for w in sorted(email_reg_by_week.keys()):
    _running_email += email_reg_by_week[w]
    cum_email_reg[w] = _running_email

email_registered_total = len(email_reg)

# Matured conversion: only count email registrations 4+ weeks old
# Users need time (20 free queries) before doctor verification triggers
MATURATION_WEEKS = 4

print(f"  Email registrations (all role=user): {email_registered_total}", flush=True)

activities = []  # (user_id, search_date, days_since_reg) — doctor-filtered
activities_all = []  # same but for ALL email-registered users (no doctor filter)
with open(ACTIVITY_CSV, encoding=CSV_ENCODING, newline="") as f:
    reader = csv.reader(f)
    next(reader)
    for row in reader:
        uid = row[ACT_USERID_COL]
        if uid in user_reg:
            sd = parse_date(row[ACT_CREATED_COL])
            activities.append((uid, sd, (sd - user_reg[uid]).days))
        if uid in email_reg:
            sd = parse_date(row[ACT_CREATED_COL])
            activities_all.append((uid, sd, (sd - email_reg[uid]).days))

print(f"  Activity events (doctors): {len(activities)}", flush=True)
print(f"  Activity events (all users): {len(activities_all)}", flush=True)

# DATA_END: derive upper bound from CSV filename date (e.g. "User0328.csv" -> 03-28)
import re as _re
_csv_date_match = _re.search(r'(\d{4})\.csv$', str(ACTIVITY_CSV))
_csv_date_limit = None
if _csv_date_match:
    _mmdd = _csv_date_match.group(1)
    _csv_month, _csv_day = int(_mmdd[:2]), int(_mmdd[2:])
    # Infer year from latest activity
    _latest_act_year = max(a[1] for a in activities).year
    _csv_date_limit = datetime(_latest_act_year, _csv_month, _csv_day)
    print(f"  CSV filename date limit: {_csv_date_limit.date()}")

# Trim noise days (last day with <10% of previous day's events)
_raw_data_end = max(a[1] for a in activities)
_day_counts = defaultdict(int)
for _, sd, _ in activities:
    _day_counts[sd.date()] += 1
_sorted_days = sorted(_day_counts.keys())
DATA_END = datetime(_raw_data_end.year, _raw_data_end.month, _raw_data_end.day)
if len(_sorted_days) >= 2:
    _last = _sorted_days[-1]
    _prev = _sorted_days[-2]
    if _day_counts[_last] < _day_counts[_prev] * 0.1:
        DATA_END = datetime(_prev.year, _prev.month, _prev.day)
        print(f"  Trimmed noise day {_last} ({_day_counts[_last]} events vs {_day_counts[_prev]} on {_prev})")
        activities = [(u, s, d) for u, s, d in activities if s.date() <= _prev]
        activities_all = [(u, s, d) for u, s, d in activities_all if s.date() <= _prev]

# Cap DATA_END at CSV filename date (CSV dated 0328 means data through 03-28)
if _csv_date_limit and DATA_END.date() > _csv_date_limit.date():
    print(f"  Capping DATA_END from {DATA_END.date()} to CSV date {_csv_date_limit.date()}")
    DATA_END = _csv_date_limit
    activities = [(u, s, d) for u, s, d in activities if s.date() <= DATA_END.date()]
    activities_all = [(u, s, d) for u, s, d in activities_all if s.date() <= DATA_END.date()]
# Override DATA_END if env var is set (e.g. DATA_END_OVERRIDE=2026-03-19)
_data_end_override = os.environ.get("DATA_END_OVERRIDE")
if _data_end_override:
    DATA_END = datetime.strptime(_data_end_override, "%Y-%m-%d")
    activities = [(u, s, d) for u, s, d in activities if s.date() <= DATA_END.date()]
    activities_all = [(u, s, d) for u, s, d in activities_all if s.date() <= DATA_END.date()]
    print(f"  DATA_END overridden to: {DATA_END.date()}")
print(f"  Data end: {DATA_END.date()}", flush=True)

# Cohort sizes
all_cohort_sizes = defaultdict(int)
for reg_date in user_reg.values():
    all_cohort_sizes[cohort_month(reg_date)] += 1

print(f"\n{'Cohort':<10} {'Reg':>6}")
for c in sorted(all_cohort_sizes.keys()):
    print(f"  {c:<8} {all_cohort_sizes[c]:>6}")

# ── Matured conversion rate (email → doctor, 4+ weeks old cohorts only) ──
# Build per-week email registration sets for cohort-based conversion tracking
_maturation_cutoff = week_monday(DATA_END) - timedelta(weeks=MATURATION_WEEKS)
email_ids_by_week = defaultdict(set)
for uid, rd in email_reg.items():
    email_ids_by_week[week_monday(rd)].add(uid)

# Per-week matured conversion
matured_conv_by_week = {}  # week -> (email_count, doctor_count, rate)
for w in sorted(email_ids_by_week.keys()):
    if w > _maturation_cutoff:
        continue  # too recent to measure
    eids = email_ids_by_week[w]
    e_count = len(eids)
    d_count = sum(1 for uid in eids if uid in user_reg)
    rate = d_count / e_count * 100 if e_count > 0 else 0
    matured_conv_by_week[w] = (e_count, d_count, rate)

# Rolling 4-week matured conversion (using 4 most recent matured weeks)
_matured_weeks_sorted = sorted(matured_conv_by_week.keys())
matured_r4w_weeks = []
matured_r4w_email = []
matured_r4w_doctor = []
matured_r4w_rate = []
for i, w in enumerate(_matured_weeks_sorted):
    start_i = max(0, i - 3)
    window = _matured_weeks_sorted[start_i:i + 1]
    if len(window) < 4:
        continue
    e4 = sum(matured_conv_by_week[ww][0] for ww in window)
    d4 = sum(matured_conv_by_week[ww][1] for ww in window)
    rate = d4 / e4 * 100 if e4 > 0 else 0
    matured_r4w_weeks.append(w)
    matured_r4w_email.append(e4)
    matured_r4w_doctor.append(d4)
    matured_r4w_rate.append(rate)

# Latest matured conversion rate for projections
MATURED_CONV_RATE = matured_r4w_rate[-1] / 100 if matured_r4w_rate else 0.5
_matured_cutoff_label = _maturation_cutoff.strftime("%Y-%m-%d")
print(f"\n  Matured conversion (cohorts registered before {_matured_cutoff_label}):")
print(f"    Latest 4-week matured rate: {MATURED_CONV_RATE*100:.0f}%")
if matured_r4w_weeks:
    for w, e, d, r in zip(matured_r4w_weeks[-4:], matured_r4w_email[-4:], matured_r4w_doctor[-4:], matured_r4w_rate[-4:]):
        print(f"    {w.strftime('%Y-%m-%d')}: Email={e}, Doctor={d}, Rate={r:.0f}%")


# ══════════════════════════════════════════════
# Chart 1: Millefeuille (stacked area WAU)
# ══════════════════════════════════════════════
print("\n" + "=" * 50)
print("Chart 1: Millefeuille")
print("=" * 50, flush=True)

# D4+ events grouped by (week, cohort_label) -> unique users
week_cohort_users = defaultdict(lambda: defaultdict(set))
for uid, sd, days in activities:
    if days >= 4:
        w = week_monday(sd)
        c_label = MILLE_LABEL_MAP.get(cohort_month(user_reg[uid]), cohort_month(user_reg[uid]))
        week_cohort_users[w][c_label].add(uid)

all_weeks = sorted(w for w in week_cohort_users if w >= week_monday(MILLE_START))
all_cohorts_mille = sorted({c for wd in week_cohort_users.values() for c in wd})

# Trim last incomplete week (< 7 days of data)
last_w = all_weeks[-1]
last_w_sunday = last_w + timedelta(days=6)
HAS_TRAILING = False
TRAILING_MONDAY = None  # virtual Monday for the trailing 7-day window
TRAILING_LABEL = ""
if DATA_END.date() < last_w_sunday.date():
    all_weeks = all_weeks[:-1]
    print(f"  Trimmed incomplete week {last_w.date()} (data ends {DATA_END.date()})")
    # Trailing 7-day window: DATA_END-6 ~ DATA_END
    TRAILING_MONDAY = datetime(DATA_END.year, DATA_END.month, DATA_END.day) - timedelta(days=6)
    HAS_TRAILING = True
    t_start = TRAILING_MONDAY
    t_end_dt = datetime(DATA_END.year, DATA_END.month, DATA_END.day)
    TRAILING_LABEL = f"直近7日 ({t_start.month}/{t_start.day}-{t_end_dt.month}/{t_end_dt.day})"
    print(f"  Trailing 7-day window: {t_start.date()} ~ {DATA_END.date()} ({TRAILING_LABEL})")

    # Compute trailing WAU for millefeuille (cohort -> set of users active in trailing window)
    trailing_cohort_users = defaultdict(set)
    for uid, sd, days in activities:
        if days >= 4 and TRAILING_MONDAY.date() <= sd.date() <= DATA_END.date():
            c_label = MILLE_LABEL_MAP.get(cohort_month(user_reg[uid]), cohort_month(user_reg[uid]))
            trailing_cohort_users[c_label].add(uid)
    week_cohort_users[TRAILING_MONDAY] = trailing_cohort_users
    all_weeks.append(TRAILING_MONDAY)

# Build matrix
mille_matrix = [[len(week_cohort_users[w].get(c, set())) for w in all_weeks] for c in all_cohorts_mille]

# Plot
n_c = len(all_cohorts_mille)
colors = plt.cm.viridis_r([i / max(n_c - 1, 1) for i in range(n_c)])

fig, ax = plt.subplots(figsize=(14, 7))
ax.stackplot(all_weeks, mille_matrix, labels=all_cohorts_mille, colors=colors, alpha=0.85)
ax.set_xlabel("週", fontsize=12)
ax.set_ylabel("WAU（人）", fontsize=12)
ax.set_title("6. コホート別WAU推移 — 医師認証済み（ミルフィーユチャート）", fontsize=14, fontweight="bold")
ax.legend(title="Registration Cohort", loc="upper left", fontsize=9, title_fontsize=10, ncol=2)

# X-axis labels
fd, ld = all_weeks[0], all_weeks[-1]
mt, ml = [], []
dt = next_month_start(fd)
while dt < ld:
    if (dt - fd).days > 10 and (ld - dt).days > 10:
        mt.append(dt)
        ml.append(dt.strftime("%Y/%m"))
    dt = next_month_start(dt)
_ld_label = TRAILING_LABEL if (HAS_TRAILING and ld == TRAILING_MONDAY) else week_range_label(ld)
ax.set_xticks([fd] + mt + [ld])
ax.set_xticklabels([fd.strftime("%Y/%m/%d")] + ml + [_ld_label], rotation=45, ha="right")
plt.tight_layout()
fig.savefig(OUTPUT_DIR / "chart1_millefeuille.png", dpi=150, bbox_inches="tight")
print("[OK] Chart 1 -> output/chart1_millefeuille.png", flush=True)
plt.close(fig)

# ── Chart 1b: Millefeuille (all users, no doctor filter) ──
print("\nChart 1b: Millefeuille (all users)", flush=True)

week_cohort_users_all = defaultdict(lambda: defaultdict(set))
for uid, sd, days in activities_all:
    if days >= 4:
        w = week_monday(sd)
        c_label = MILLE_LABEL_MAP.get(cohort_month(email_reg[uid]), cohort_month(email_reg[uid]))
        week_cohort_users_all[w][c_label].add(uid)

all_weeks_1b = sorted(w for w in week_cohort_users_all if w >= week_monday(MILLE_START))
all_cohorts_mille_1b = sorted({c for wd in week_cohort_users_all.values() for c in wd})

# Trim incomplete week + trailing (same logic as Chart 1)
if all_weeks_1b:
    last_w_1b = all_weeks_1b[-1]
    if DATA_END.date() < (last_w_1b + timedelta(days=6)).date():
        all_weeks_1b = all_weeks_1b[:-1]
    if HAS_TRAILING:
        trailing_cohort_users_all = defaultdict(set)
        for uid, sd, days in activities_all:
            if days >= 4 and TRAILING_MONDAY.date() <= sd.date() <= DATA_END.date():
                c_label = MILLE_LABEL_MAP.get(cohort_month(email_reg[uid]), cohort_month(email_reg[uid]))
                trailing_cohort_users_all[c_label].add(uid)
        week_cohort_users_all[TRAILING_MONDAY] = trailing_cohort_users_all
        all_weeks_1b.append(TRAILING_MONDAY)

mille_matrix_1b = [[len(week_cohort_users_all[w].get(c, set())) for w in all_weeks_1b] for c in all_cohorts_mille_1b]
n_c_1b = len(all_cohorts_mille_1b)
colors_1b = plt.cm.viridis_r([i / max(n_c_1b - 1, 1) for i in range(n_c_1b)])

fig1b, ax1b = plt.subplots(figsize=(14, 7))
ax1b.stackplot(all_weeks_1b, mille_matrix_1b, labels=all_cohorts_mille_1b, colors=colors_1b, alpha=0.85)
ax1b.set_xlabel("週", fontsize=12)
ax1b.set_ylabel("WAU（人）", fontsize=12)
ax1b.set_title("6b. コホート別WAU推移 — 全メール登録者（ミルフィーユチャート）", fontsize=14, fontweight="bold")
ax1b.legend(title="Registration Cohort", loc="upper left", fontsize=9, title_fontsize=10, ncol=2)

fd1b, ld1b = all_weeks_1b[0], all_weeks_1b[-1]
mt1b, ml1b = [], []
dt1b = next_month_start(fd1b)
while dt1b < ld1b:
    if (dt1b - fd1b).days > 10 and (ld1b - dt1b).days > 10:
        mt1b.append(dt1b)
        ml1b.append(dt1b.strftime("%Y/%m"))
    dt1b = next_month_start(dt1b)
_ld1b_label = TRAILING_LABEL if (HAS_TRAILING and ld1b == TRAILING_MONDAY) else week_range_label(ld1b)
ax1b.set_xticks([fd1b] + mt1b + [ld1b])
ax1b.set_xticklabels([fd1b.strftime("%Y/%m/%d")] + ml1b + [_ld1b_label], rotation=45, ha="right")
plt.tight_layout()
fig1b.savefig(OUTPUT_DIR / "chart1b_millefeuille_all.png", dpi=150, bbox_inches="tight")
print("[OK] Chart 1b -> output/chart1b_millefeuille_all.png", flush=True)
plt.close(fig1b)

# WAU totals for Chart 3
wau_by_week = {w: sum(len(week_cohort_users[w].get(c, set())) for c in all_cohorts_mille) for w in all_weeks}

# Trailing D4+ weekly user sets (for exp_weekly_sets and other metrics)
if HAS_TRAILING:
    trailing_d4_users = set()
    for uid, sd, days in activities:
        if days >= 4 and TRAILING_MONDAY.date() <= sd.date() <= DATA_END.date():
            trailing_d4_users.add(uid)


# ══════════════════════════════════════════════
# Chart 2: Retention Curve
# ══════════════════════════════════════════════
print("\n" + "=" * 50)
print("Chart 2: Retention Curve")
print("=" * 50, flush=True)


def retention_period(days):
    if days <= 3:
        return 0  # D0-D3
    elif days <= 10:
        return 1  # D4-D10
    elif days <= 40:
        return 2  # M1 (D11-D40)
    else:
        return (days - 41) // 30 + 3  # M2=3(D41-D70), M3=4(D71-D100), ...

PERIOD_LABELS = {0: "D0-D3", 1: "D4-D10", 2: "M1"}
def period_label(p):
    if p in PERIOD_LABELS:
        return PERIOD_LABELS[p]
    return f"M{p - 1}"  # period 3=M2, 4=M3, ...


# Exclude cohorts dynamically
exclude_cohorts = set()
for c_str in sorted(all_cohort_sizes.keys()):
    c_start = datetime.strptime(c_str, "%Y-%m")
    c_end = next_month_start(c_start) - timedelta(days=1)
    if c_end + timedelta(days=29) < LOG_START:
        exclude_cohorts.add(c_str)
        print(f"  Excluding {c_str}: log truncation")
        continue
    if c_start + timedelta(days=29) < LOG_START:
        exclude_cohorts.add(c_str)
        print(f"  Excluding {c_str}: log truncation (partial)")
        continue
    latest = max(
        (rd for uid, rd in user_reg.items() if cohort_month(rd) == c_str),
        default=None,
    )
    if latest and (DATA_END - latest).days < 3:
        exclude_cohorts.add(c_str)
        print(f"  Excluding {c_str}: observation too short ({(DATA_END - latest).days}d)")

# Retention data: label -> period -> set(uids)
ret_data = defaultdict(lambda: defaultdict(set))
for uid, sd, days in activities:
    c = cohort_month(user_reg[uid])
    if c in exclude_cohorts:
        continue
    label = RET_MERGED_LABEL if c in RET_MERGE_MONTHS else c
    ret_data[label][retention_period(days)].add(uid)

# Cohort sizes (merged)
ret_sizes = defaultdict(int)
for c, sz in all_cohort_sizes.items():
    if c in exclude_cohorts:
        continue
    ret_sizes[RET_MERGED_LABEL if c in RET_MERGE_MONTHS else c] += sz

# Max observable period per cohort
max_obs = {}
for label in ret_sizes:
    months = RET_MERGE_MONTHS if label == RET_MERGED_LABEL else {label}
    latest = max(
        (rd for uid, rd in user_reg.items() if cohort_month(rd) in months and cohort_month(rd) not in exclude_cohorts),
        default=None,
    )
    if latest:
        md = (DATA_END - latest).days
        if md < 3:
            max_obs[label] = -1
        elif md < 10:
            max_obs[label] = 0   # D0-D3 only
        elif md < 40:
            max_obs[label] = 1   # up to D4-D10
        elif md < 70:
            max_obs[label] = 2   # up to M1 (D11-D40)
        else:
            max_obs[label] = (md - 41) // 30 + 2

print(f"\nRetention cohorts:")
for label in sorted(ret_sizes.keys()):
    mo = max_obs.get(label, -1)
    print(f"  {label}: n={ret_sizes[label]}, up to {period_label(mo)}" if mo >= 0 else f"  {label}: n={ret_sizes[label]}, insufficient data")

# Print table
ret_labels = sorted(ret_sizes.keys())
print(f"\nRetention Rate (%):")
for label in ret_labels:
    periods = sorted(p for p in ret_data[label] if p <= max_obs.get(label, -1))
    parts = []
    for p in periods:
        rate = len(ret_data[label][p]) / ret_sizes[label] * 100
        parts.append(f"{period_label(p)}={rate:.1f}%")
    print(f"  {label}: {', '.join(parts)}")

# Plot
n_ret = len(ret_labels)
ret_colors = plt.cm.viridis_r([i / max(n_ret - 1, 1) for i in range(n_ret)])

fig, ax = plt.subplots(figsize=(14, 7))
max_p = 0
for i, label in enumerate(ret_labels):
    periods = sorted(p for p in ret_data[label] if p <= max_obs.get(label, -1))
    if not periods:
        continue
    x_vals = [0] + [p + 1 for p in periods]
    rates = [100.0] + [len(ret_data[label][p]) / ret_sizes[label] * 100 for p in periods]
    max_p = max(max_p, max(periods))
    ax.plot(x_vals, rates, marker="o", markersize=5, linewidth=2,
            label=f"{label} (n={ret_sizes[label]})", color=ret_colors[i])

ax.set_xlabel("登録からの経過期間", fontsize=12)
ax.set_ylabel("リテンション率（%）", fontsize=12)
ax.set_title("8. コホート別リテンションカーブ（登録月基準）", fontsize=14, fontweight="bold")
ax.legend(title="Registration Cohort", loc="upper right", fontsize=9, title_fontsize=10, ncol=2)
ax.set_ylim(0, 105)
ax.set_xlim(-0.3, max_p + 1.5)
ax.set_xticks(range(0, max_p + 2))
ax.set_xticklabels(["Reg"] + [period_label(p) for p in range(0, max_p + 1)])
fig.text(0.99, 0.01, "Base: all registered doctors / D0-D3, D4-D10 separated from M1",
         ha="right", va="bottom", fontsize=8, color="gray", style="italic")
plt.tight_layout()
plt.subplots_adjust(bottom=0.12)
fig.savefig(OUTPUT_DIR / "chart2_retention_curve.png", dpi=150, bbox_inches="tight")
print(f"\n[OK] Chart 2 -> output/chart2_retention_curve.png", flush=True)
plt.close(fig)


# ══════════════════════════════════════════════
# Chart 3: KGI/KPI Weekly Trends (3 subplots)
# ══════════════════════════════════════════════
print("\n" + "=" * 50)
print("Chart 3: KGI/KPI Weekly Trends")
print("=" * 50, flush=True)

# Cumulative registrations by week
reg_by_week = defaultdict(int)
for rd in user_reg.values():
    reg_by_week[week_monday(rd)] += 1

cum_reg = {}
running = 0
for w in sorted(reg_by_week.keys()):
    running += reg_by_week[w]
    cum_reg[w] = running

# D4+ eligible: doctors registered >= 4 days before end of week (Sunday)
d4_eligible_by_week = {}
for w in sorted(cum_reg.keys()):
    week_end = w + timedelta(days=6)  # Sunday
    d4_cutoff = week_end - timedelta(days=3)  # registered on or before this date → D4+ eligible
    eligible = sum(1 for rd in user_reg.values() if rd.date() <= d4_cutoff.date())
    d4_eligible_by_week[w] = eligible

# Add trailing data for Chart 3 metrics
if HAS_TRAILING:
    # cum_reg at trailing point = latest cumulative value
    cum_reg[TRAILING_MONDAY] = max(cum_reg.values())
    cum_email_reg[TRAILING_MONDAY] = max(cum_email_reg.values()) if cum_email_reg else 0
    # D4+ eligible at trailing point: use DATA_END as the window end
    t_d4_cutoff = DATA_END - timedelta(days=3)
    d4_eligible_by_week[TRAILING_MONDAY] = sum(1 for rd in user_reg.values() if rd.date() <= t_d4_cutoff.date())

# Common weeks
common_weeks = sorted(w for w in all_weeks if w in cum_reg)
wau_vals = [wau_by_week[w] for w in common_weeks]
reg_vals = [cum_reg[w] for w in common_weeks]
d4_eligible_vals = [d4_eligible_by_week.get(w, cum_reg[w]) for w in common_weeks]
rate_vals = [wau_by_week[w] / cum_reg[w] * 100 for w in common_weeks]

# Email registration vals for common_weeks (cumulative, forward-fill)
email_reg_vals = []
_last_email_cum = 0
for w in common_weeks:
    if w in cum_email_reg:
        _last_email_cum = cum_email_reg[w]
    email_reg_vals.append(_last_email_cum)

# Email -> Doctor conversion rate (cumulative)
email_doctor_conv_rate = reg_vals[-1] / email_reg_vals[-1] * 100 if email_reg_vals and email_reg_vals[-1] > 0 else 0

# Helper: trailing point index for visual distinction
TRAILING_IDX = len(common_weeks) - 1 if HAS_TRAILING else -999

def trailing_week_label(w):
    """Return TRAILING_LABEL if w is the trailing point, else week_range_label."""
    if HAS_TRAILING and w == TRAILING_MONDAY:
        return TRAILING_LABEL
    return week_range_label(w)

def week_end_date(w):
    """Return the end date (Sunday) of the week, or DATA_END for trailing."""
    if HAS_TRAILING and w == TRAILING_MONDAY:
        return datetime(DATA_END.year, DATA_END.month, DATA_END.day)
    return w + timedelta(days=6)

def week_end_label(w):
    """Return just the week-end date (Sunday) as M/D label."""
    d = week_end_date(w)
    if os.name == "nt":
        return d.strftime("%#m/%#d")
    return d.strftime("%-m/%-d")

def set_weekly_xticks(ax, weeks, equal_spacing=False):
    """Set X-axis ticks with proper trailing labels.
    equal_spacing=True: bar charts use integer positions (0,1,2,...) for equal spacing.
    equal_spacing=False: line charts use datetime positions (date-proportional).
    """
    labels = [trailing_week_label(w) for w in weeks]
    if equal_spacing:
        ax.set_xticks(range(len(weeks)))
        ax.set_xticklabels(labels, rotation=45, ha="right")
    else:
        ax.set_xticks(weeks)
        ax.set_xticklabels(labels, rotation=45, ha="right")

# X-axis: extend to TARGET_DATE
target_monday = week_monday(TARGET_DATE)
fd3 = common_weeks[0]
ld3_extended = target_monday
mt3, ml3 = [], []
dt3 = next_month_start(fd3)
while dt3 <= ld3_extended:
    if (dt3 - fd3).days > 10 and (ld3_extended - dt3).days > 10:
        mt3.append(dt3)
        ml3.append(dt3.strftime("%Y/%m"))
    dt3 = next_month_start(dt3)
ticks3 = [fd3] + mt3 + [ld3_extended]
labels3 = [fd3.strftime("%Y/%m/%d")] + ml3 + [week_range_label(ld3_extended)]

# ── Email registration plan lines (needed for Charts 2a, 3c, and 10b) ──
LATEST_CONV_RATE = MATURED_CONV_RATE
EMAIL_TARGET_REG = int(TARGET_REG / LATEST_CONV_RATE) if LATEST_CONV_RATE > 0 else TARGET_REG
EMAIL_TARGET_REG_B = int(TARGET_REG_B / LATEST_CONV_RATE) if LATEST_CONV_RATE > 0 else TARGET_REG_B

def email_plan_from_doctor_plan(milestones, conv_rate):
    """Convert doctor registration milestones to email registration milestones."""
    return [(m[0], int(m[1] / conv_rate), m[2], m[3]) for m in milestones]

def interpolate_email_plan_weekly(milestones):
    """Interpolate email plan milestones to weekly points (reg values only)."""
    first_mon = week_monday(milestones[0][0])
    last_mon = week_monday(milestones[-1][0])
    ms_days = [(m[0] - milestones[0][0]).days for m in milestones]
    weeks, regs = [], []
    w = first_mon
    while w <= last_mon + timedelta(days=6):
        d = (w - milestones[0][0]).days
        for i in range(len(ms_days) - 1):
            if ms_days[i] <= d <= ms_days[i + 1]:
                frac = (d - ms_days[i]) / (ms_days[i + 1] - ms_days[i]) if ms_days[i + 1] != ms_days[i] else 0
                weeks.append(w)
                regs.append(milestones[i][1] + frac * (milestones[i + 1][1] - milestones[i][1]))
                break
        w += timedelta(days=7)
    return weeks, regs

EMAIL_PLAN_MILESTONES = email_plan_from_doctor_plan(PLAN_MILESTONES, LATEST_CONV_RATE)
EMAIL_PLAN_B_MILESTONES = email_plan_from_doctor_plan(PLAN_B_MILESTONES, LATEST_CONV_RATE)
EMAIL_PLAN_WEEKS, EMAIL_PLAN_REG = interpolate_email_plan_weekly(EMAIL_PLAN_MILESTONES)
EMAIL_PLAN_B_WEEKS, EMAIL_PLAN_B_REG = interpolate_email_plan_weekly(EMAIL_PLAN_B_MILESTONES)
print(f"\n  Email plan (matured conv {LATEST_CONV_RATE*100:.0f}%): Plan A={EMAIL_TARGET_REG:,}, Plan B={EMAIL_TARGET_REG_B:,}")

# NOTE: Chart 3 (KGI/KPI trends) is deferred — drawn after s15_count is computed.
# See "DEFERRED CHART 3" section below.

# ══════════════════════════════════════════════
# Chart 3b: KGI/KPI Weekly Trends (Actual only, no Plan)
# ══════════════════════════════════════════════
print("\n" + "=" * 50)
print("Chart 3b: KGI/KPI Weekly Trends (Actual Only)")
print("=" * 50, flush=True)

# X-axis: fit to actual data only (no extension to target date)
fd3b = common_weeks[0]
ld3b = common_weeks[-1]
mt3b, ml3b = [], []
dt3b = next_month_start(fd3b)
while dt3b <= ld3b:
    if (dt3b - fd3b).days > 10 and (ld3b - dt3b).days > 10:
        mt3b.append(dt3b)
        ml3b.append(dt3b.strftime("%Y/%m"))
    dt3b = next_month_start(dt3b)
ticks3b = [fd3b] + mt3b + [ld3b]
labels3b = [fd3b.strftime("%Y/%m/%d")] + ml3b + [trailing_week_label(ld3b)]

fig3b, axes3b = plt.subplots(3, 1, figsize=(14, 12), sharex=True)

# WAU
ax1 = axes3b[0]
ax1.plot(common_weeks, wau_vals, marker="o", markersize=4, linewidth=2, color="#2196F3")
ax1.set_ylabel("WAU（人）", fontsize=11)
ax1.set_title("(旧) WAU KPI推移 — 実績のみ", fontsize=14, fontweight="bold")
ax1.text(0.01, 0.95, "WAU (D4+)", transform=ax1.transAxes,
         fontsize=10, fontweight="bold", va="top", color="#2196F3")
for idx in [0, -1]:
    ax1.annotate(f"{wau_vals[idx]}", (common_weeks[idx], wau_vals[idx]),
                 textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8, color="#555")
ax1.set_xlim(fd3b - timedelta(days=3), ld3b + timedelta(days=7))

# Cumulative registrations
ax2 = axes3b[1]
ax2.plot(common_weeks, reg_vals, marker="o", markersize=4, linewidth=2, color="#4CAF50")
ax2.set_ylabel("累計登録医師数", fontsize=11)
ax2.text(0.01, 0.95, "累計登録医師数", transform=ax2.transAxes,
         fontsize=10, fontweight="bold", va="top", color="#4CAF50")
for idx in [0, -1]:
    ax2.annotate(f"{reg_vals[idx]}", (common_weeks[idx], reg_vals[idx]),
                 textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8, color="#555")

# WAU rate
ax3 = axes3b[2]
ax3.plot(common_weeks, rate_vals, marker="o", markersize=4, linewidth=2, color="#FF9800")
ax3.set_ylabel("WAU Rate (%)", fontsize=11)
ax3.set_xlabel("週", fontsize=12)
ax3.text(0.01, 0.95, "WAU率（WAU / 累計登録医師数）", transform=ax3.transAxes,
         fontsize=10, fontweight="bold", va="top", color="#FF9800")
for idx in [0, -1]:
    ax3.annotate(f"{rate_vals[idx]:.1f}%", (common_weeks[idx], rate_vals[idx]),
                 textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8, color="#555")

ax3.set_xticks(ticks3b)
ax3.set_xticklabels(labels3b, rotation=45, ha="right")
plt.tight_layout()
fig3b.savefig(OUTPUT_DIR / "chart3b_kpi_actual.png", dpi=150, bbox_inches="tight")
print(f"\n[OK] Chart 3b -> output/chart3b_kpi_actual.png", flush=True)
plt.close(fig3b)

# ══════════════════════════════════════════════
# Chart 3c: KGI/KPI Weekly Trends — Actual vs Plan B (WAU=300)
# ══════════════════════════════════════════════
print("\n" + "=" * 50)
print("Chart 3c: KGI/KPI Weekly Trends (Plan B: WAU=300)")
print("=" * 50, flush=True)

fig3c, axes3c = plt.subplots(4, 1, figsize=(14, 16), sharex=True)

# WAU
ax1 = axes3c[0]
ax1.plot(common_weeks, wau_vals, marker="o", markersize=4, linewidth=2, color="#2196F3", label="実績")
ax1.plot(PLAN_B_WEEKS, PLAN_B_WAU, linestyle="--", linewidth=1.5, color="#2196F3", alpha=0.4, label="計画B")
ax1.scatter([PLAN_B_WEEKS[-1]], [PLAN_B_WAU[-1]], marker="*", s=120, color="#2196F3", alpha=0.6, zorder=5)
ax1.annotate(f"目標: {TARGET_WAU_B}", (PLAN_B_WEEKS[-1], PLAN_B_WAU[-1]),
             textcoords="offset points", xytext=(-50, 10), ha="center", fontsize=9, color="#2196F3", fontweight="bold")
ax1.set_ylabel("WAU（人）", fontsize=11)
ax1.set_title("(旧) WAU KPI推移 — 計画B（WAU=300）", fontsize=14, fontweight="bold")
ax1.text(0.01, 0.95, "WAU (D4+)", transform=ax1.transAxes,
         fontsize=10, fontweight="bold", va="top", color="#2196F3")
ax1.legend(loc="center left", fontsize=8, framealpha=0.7)
for idx in [0, -1]:
    ax1.annotate(f"{wau_vals[idx]}", (common_weeks[idx], wau_vals[idx]),
                 textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8, color="#555")
ax1.set_xlim(fd3 - timedelta(days=3), ld3_extended + timedelta(days=7))

# Cumulative doctor registrations
ax2 = axes3c[1]
ax2.plot(common_weeks, reg_vals, marker="o", markersize=4, linewidth=2, color="#4CAF50", label="実績")
ax2.plot(PLAN_B_WEEKS, PLAN_B_REG, linestyle="--", linewidth=1.5, color="#4CAF50", alpha=0.4, label="計画B")
ax2.scatter([PLAN_B_WEEKS[-1]], [PLAN_B_REG[-1]], marker="*", s=120, color="#4CAF50", alpha=0.6, zorder=5)
ax2.annotate(f"目標: {TARGET_REG_B:,}", (PLAN_B_WEEKS[-1], PLAN_B_REG[-1]),
             textcoords="offset points", xytext=(-50, 10), ha="center", fontsize=9, color="#4CAF50", fontweight="bold")
ax2.set_ylabel("累計登録医師数", fontsize=11)
ax2.text(0.01, 0.95, "累計登録医師数", transform=ax2.transAxes,
         fontsize=10, fontweight="bold", va="top", color="#4CAF50")
ax2.legend(loc="center left", fontsize=8, framealpha=0.7)
for idx in [0, -1]:
    ax2.annotate(f"{reg_vals[idx]}", (common_weeks[idx], reg_vals[idx]),
                 textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8, color="#555")

# Cumulative email registrations (below doctor registrations)
ax2e = axes3c[2]
ax2e.plot(common_weeks, email_reg_vals, marker="o", markersize=4, linewidth=2, color="#1976D2", label="実績")
ax2e.plot(EMAIL_PLAN_B_WEEKS, EMAIL_PLAN_B_REG, linestyle="--", linewidth=1.5, color="#1976D2", alpha=0.4, label=f"計画B（確定転換率{LATEST_CONV_RATE*100:.0f}%）")
ax2e.scatter([EMAIL_PLAN_B_WEEKS[-1]], [EMAIL_PLAN_B_REG[-1]], marker="*", s=120, color="#1976D2", alpha=0.6, zorder=5)
ax2e.annotate(f"必要数: {EMAIL_TARGET_REG_B:,}", (EMAIL_PLAN_B_WEEKS[-1], EMAIL_PLAN_B_REG[-1]),
              textcoords="offset points", xytext=(-60, 10), ha="center", fontsize=9, color="#1976D2", fontweight="bold")
ax2e.set_ylabel("累計メール登録数", fontsize=11)
ax2e.text(0.01, 0.95, "参考: 累計メール登録数", transform=ax2e.transAxes,
          fontsize=10, fontweight="bold", va="top", color="#1976D2")
ax2e.legend(loc="center left", fontsize=8, framealpha=0.7)
for idx in [0, -1]:
    ax2e.annotate(f"{email_reg_vals[idx]}", (common_weeks[idx], email_reg_vals[idx]),
                  textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8, color="#555")

# WAU rate (same target 10%)
ax3 = axes3c[3]
ax3.plot(common_weeks, rate_vals, marker="o", markersize=4, linewidth=2, color="#FF9800", label="実績")
ax3.plot(PLAN_B_WEEKS, PLAN_B_RATE, linestyle="--", linewidth=1.5, color="#FF9800", alpha=0.4, label="計画B")
ax3.scatter([PLAN_B_WEEKS[-1]], [PLAN_B_RATE[-1]], marker="*", s=120, color="#FF9800", alpha=0.6, zorder=5)
ax3.annotate(f"目標: {TARGET_WAU_RATE_B}%", (PLAN_B_WEEKS[-1], PLAN_B_RATE[-1]),
             textcoords="offset points", xytext=(-50, 10), ha="center", fontsize=9, color="#FF9800", fontweight="bold")
ax3.set_ylabel("WAU Rate (%)", fontsize=11)
ax3.set_xlabel("週", fontsize=12)
ax3.legend(loc="center left", fontsize=8, framealpha=0.7)
ax3.text(0.01, 0.95, "WAU率（WAU / 累計登録医師数）", transform=ax3.transAxes,
         fontsize=10, fontweight="bold", va="top", color="#FF9800")
for idx in [0, -1]:
    ax3.annotate(f"{rate_vals[idx]:.1f}%", (common_weeks[idx], rate_vals[idx]),
                 textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8, color="#555")

ax3.set_xticks(ticks3)
ax3.set_xticklabels(labels3, rotation=45, ha="right")
plt.tight_layout()
fig3c.savefig(OUTPUT_DIR / "chart3c_kpi_planB.png", dpi=150, bbox_inches="tight")
print(f"\n[OK] Chart 3c -> output/chart3c_kpi_planB.png", flush=True)
plt.close(fig3c)

# ══════════════════════════════════════════════
# MAU / DAU metrics (for Chart 8 and summary cards)
# ══════════════════════════════════════════════
print("\n" + "=" * 50)
print("Computing MAU / DAU metrics...")
print("=" * 50, flush=True)

# DAU by date (D4+ only)
dau_by_date_early = defaultdict(set)
for uid, sd, days in activities:
    if days >= 4:
        dau_by_date_early[sd.date()].add(uid)

# MAU (28-day window ending each week's Sunday), avg DAU, and rates
mau_by_week = {}
mau_rate_by_week = {}
avg_dau_by_week = {}
dau_rate_by_week = {}

for w in common_weeks:
    w_end = week_end_date(w)
    w28 = w_end - timedelta(days=27)
    # MAU: unique D4+ users in 28-day window
    mau_set = set()
    for uid, sd, days_since in activities:
        if days_since >= 4 and w28.date() <= sd.date() <= w_end.date():
            mau_set.add(uid)
    mau = len(mau_set)
    mau_by_week[w] = mau
    reg_w = cum_reg.get(w, 1)
    mau_rate_by_week[w] = mau / reg_w * 100 if reg_w > 0 else 0
    # Avg DAU in this week
    week_daus = []
    for dd in range(7):
        day = (w + timedelta(days=dd)).date()
        week_daus.append(len(dau_by_date_early.get(day, set())))
    avg_dau = sum(week_daus) / 7
    avg_dau_by_week[w] = avg_dau
    dau_rate_by_week[w] = avg_dau / reg_w * 100 if reg_w > 0 else 0

mau_vals = [mau_by_week[w] for w in common_weeks]
mau_rate_vals = [mau_rate_by_week[w] for w in common_weeks]
avg_dau_vals = [avg_dau_by_week[w] for w in common_weeks]
dau_rate_vals = [dau_rate_by_week[w] for w in common_weeks]

print(f"  MAU (latest): {mau_vals[-1]}")
print(f"  MAU Rate (latest): {mau_rate_vals[-1]:.1f}%")
print(f"  Avg DAU (latest): {avg_dau_vals[-1]:.1f}")
print(f"  DAU Rate (latest): {dau_rate_vals[-1]:.1f}%")

print(f"\n  Recent 4 weeks:")
for w, mau, mau_r, dau, dau_r in zip(common_weeks[-4:], mau_vals[-4:], mau_rate_vals[-4:], avg_dau_vals[-4:], dau_rate_vals[-4:]):
    print(f"    {w.strftime('%Y-%m-%d')}: MAU={mau}, MAU Rate={mau_r:.1f}%, Avg DAU={dau:.1f}, DAU Rate={dau_r:.1f}%")

print("[OK] MAU/DAU metrics computed", flush=True)


# ══════════════════════════════════════════════
# Shared prep for Charts 4-7
# ══════════════════════════════════════════════
print("\n" + "=" * 50)
print("Preparing supplementary metrics (S1-S12)...")
print("=" * 50, flush=True)

registered_total = len(user_reg)

# D4+ events by (week -> set of user_ids)  — reuse week_cohort_users but flatten
exp_weekly_sets = defaultdict(set)
for uid, sd, days in activities:
    if days >= 4:
        exp_weekly_sets[week_monday(sd)].add(uid)

# Add trailing window to exp_weekly_sets
if HAS_TRAILING:
    exp_weekly_sets[TRAILING_MONDAY] = trailing_d4_users.copy()

exp_weeks = sorted(exp_weekly_sets.keys())

# Chart weeks: MILLE_START onwards, trim last incomplete
exp_chart_weeks = [w for w in exp_weeks if w >= week_monday(MILLE_START)]
# Trim incomplete week but keep trailing (trailing is already properly windowed)
if exp_chart_weeks and not HAS_TRAILING and DATA_END.date() < (exp_chart_weeks[-1] + timedelta(days=6)).date():
    exp_chart_weeks = exp_chart_weeks[:-1]
elif exp_chart_weeks and HAS_TRAILING:
    # Remove the incomplete calendar week if it's in there (different from TRAILING_MONDAY)
    _trimmed = []
    for w in exp_chart_weeks:
        if w == TRAILING_MONDAY:
            _trimmed.append(w)
        elif DATA_END.date() < (w + timedelta(days=6)).date():
            continue  # skip incomplete calendar week
        else:
            _trimmed.append(w)
    exp_chart_weeks = _trimmed

# First D4+ date per user
first_d4 = {}  # user_id -> first search_date with days>=4
for uid, sd, days in activities:
    if days >= 4:
        if uid not in first_d4 or sd < first_d4[uid]:
            first_d4[uid] = sd

# activation_week per user
activation_week = {uid: week_monday(dt) for uid, dt in first_d4.items()}

# D4+ query counts by (week, user_id)
d4_queries_by_week_user = defaultdict(lambda: defaultdict(int))
for uid, sd, days in activities:
    if days >= 4:
        d4_queries_by_week_user[week_monday(sd)][uid] += 1

# Add trailing query counts
if HAS_TRAILING:
    for uid, sd, days in activities:
        if days >= 4 and TRAILING_MONDAY.date() <= sd.date() <= DATA_END.date():
            d4_queries_by_week_user[TRAILING_MONDAY][uid] += 1

# Total D4+ queries per week
d4_total_queries_by_week = defaultdict(int)
d4_unique_users_by_week = defaultdict(int)
for w in exp_weeks:
    d4_total_queries_by_week[w] = sum(d4_queries_by_week_user[w].values())
    d4_unique_users_by_week[w] = len(d4_queries_by_week_user[w])

# D4+ query counts — all users (no doctor filter)
d4_queries_by_week_user_all = defaultdict(lambda: defaultdict(int))
for uid, sd, days in activities_all:
    if days >= 4:
        d4_queries_by_week_user_all[week_monday(sd)][uid] += 1

if HAS_TRAILING:
    for uid, sd, days in activities_all:
        if days >= 4 and TRAILING_MONDAY.date() <= sd.date() <= DATA_END.date():
            d4_queries_by_week_user_all[TRAILING_MONDAY][uid] += 1

d4_total_queries_by_week_all = defaultdict(int)
d4_unique_users_by_week_all = defaultdict(int)
for w in exp_weeks:
    d4_total_queries_by_week_all[w] = sum(d4_queries_by_week_user_all[w].values())
    d4_unique_users_by_week_all[w] = len(d4_queries_by_week_user_all[w])

# ALL query counts (including D0-D3) — doctors
all_queries_by_week_user = defaultdict(lambda: defaultdict(int))
for uid, sd, days in activities:
    all_queries_by_week_user[week_monday(sd)][uid] += 1
if HAS_TRAILING:
    for uid, sd, days in activities:
        if TRAILING_MONDAY.date() <= sd.date() <= DATA_END.date():
            all_queries_by_week_user[TRAILING_MONDAY][uid] += 1

# ALL query counts (including D0-D3) — all users
all_queries_by_week_user_all = defaultdict(lambda: defaultdict(int))
for uid, sd, days in activities_all:
    all_queries_by_week_user_all[week_monday(sd)][uid] += 1
if HAS_TRAILING:
    for uid, sd, days in activities_all:
        if TRAILING_MONDAY.date() <= sd.date() <= DATA_END.date():
            all_queries_by_week_user_all[TRAILING_MONDAY][uid] += 1

all_total_queries_by_week = defaultdict(int)
all_unique_users_by_week = defaultdict(int)
all_total_queries_by_week_all = defaultdict(int)
all_unique_users_by_week_all = defaultdict(int)
for w in exp_weeks:
    all_total_queries_by_week[w] = sum(all_queries_by_week_user[w].values())
    all_unique_users_by_week[w] = len(all_queries_by_week_user[w])
    all_total_queries_by_week_all[w] = sum(all_queries_by_week_user_all[w].values())
    all_unique_users_by_week_all[w] = len(all_queries_by_week_user_all[w])


# ══════════════════════════════════════════════
# Business hours overlay aggregation
# 月〜金 8:00-18:00 JST（祝休日は考慮せず、曜日と時刻のみで判定）の週次検索回数。
# parse_date は時刻を捨てるため、ChatMessagePair CSV を再読込して hour 情報を復元する。
# ══════════════════════════════════════════════
print("\n" + "=" * 50)
print("Business hours overlay aggregation")
print("=" * 50, flush=True)

BIZ_WEEKDAYS = set(range(0, 5))  # 月-金
BIZ_HOUR_START = 8
BIZ_HOUR_END = 18

biz_count_by_week_all = defaultdict(int)  # 全 email 登録ユーザー
biz_count_by_week_doc = defaultdict(int)  # 医師のみ

with open(ACTIVITY_CSV, encoding=CSV_ENCODING, newline="") as f:
    reader = csv.reader(f)
    next(reader)
    for row in reader:
        uid = row[ACT_USERID_COL]
        ts = row[ACT_CREATED_COL]
        try:
            dt = datetime.fromisoformat(ts)
        except ValueError:
            continue
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)  # 既に JST、tz情報のみ剥がす
        if dt.date() > DATA_END.date():
            continue
        if not (dt.weekday() in BIZ_WEEKDAYS and BIZ_HOUR_START <= dt.hour < BIZ_HOUR_END):
            continue
        wm = week_monday(dt)
        if uid in email_reg:
            biz_count_by_week_all[wm] += 1
        if uid in user_reg:
            biz_count_by_week_doc[wm] += 1

# trailing 7日window 用の集計（HAS_TRAILING時）
if HAS_TRAILING:
    with open(ACTIVITY_CSV, encoding=CSV_ENCODING, newline="") as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            uid = row[ACT_USERID_COL]
            ts = row[ACT_CREATED_COL]
            try:
                dt = datetime.fromisoformat(ts)
            except ValueError:
                continue
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
            if not (TRAILING_MONDAY.date() <= dt.date() <= DATA_END.date()):
                continue
            if not (dt.weekday() in BIZ_WEEKDAYS and BIZ_HOUR_START <= dt.hour < BIZ_HOUR_END):
                continue
            if uid in email_reg:
                biz_count_by_week_all[TRAILING_MONDAY] += 1
            if uid in user_reg:
                biz_count_by_week_doc[TRAILING_MONDAY] += 1

print(f"[OK] Business hours: {len(biz_count_by_week_all)} weeks (all), {len(biz_count_by_week_doc)} weeks (doc)", flush=True)
if biz_count_by_week_all:
    _last_w = max(biz_count_by_week_all.keys())
    print(f"  Latest week ({_last_w.date()}): biz_all={biz_count_by_week_all[_last_w]}, biz_doc={biz_count_by_week_doc[_last_w]}")


# ── S1: Cumulative Activation Rate ──
print("\n── S1: Activation Rate ──", flush=True)
# Cumulative activated users by week / cumulative registered by week
new_activations_by_week = defaultdict(int)
for uid, aw in activation_week.items():
    new_activations_by_week[aw] += 1

# All weeks union (registration + activity)
reg_by_week_all = defaultdict(int)
for rd in user_reg.values():
    reg_by_week_all[week_monday(rd)] += 1

all_weeks_union = sorted(set(exp_weeks) | set(reg_by_week_all.keys()))
cum_act = {}
cum_reg_all = {}
running_act = 0
running_reg = 0
for w in all_weeks_union:
    running_act += new_activations_by_week.get(w, 0)
    running_reg += reg_by_week_all.get(w, 0)
    cum_act[w] = running_act
    cum_reg_all[w] = running_reg

act_rate_ts = {}
for w in all_weeks_union:
    act_rate_ts[w] = min(cum_act[w] / cum_reg_all[w] * 100, 100.0) if cum_reg_all[w] > 0 else 0.0

overall_act_rate = len(first_d4) / registered_total * 100
print(f"  Overall: {len(first_d4)}/{registered_total} = {overall_act_rate:.1f}%")

# ── Weekly Continuation Rate time series (for KPI decomposition) ──
# Weekly Continuation Rate = WAU / cumulative activated doctors
return_rate_ts = {}
for w in common_weeks:
    ca = cum_act.get(w, 0)
    return_rate_ts[w] = wau_by_week[w] / ca * 100 if ca > 0 else 0.0

return_rate_vals = [return_rate_ts[w] for w in common_weeks]
print(f"\n── Weekly Continuation Rate (KPI3) ──")
print(f"  Latest: {return_rate_vals[-1]:.1f}% (WAU={wau_vals[-1]} / Activated={cum_act.get(common_weeks[-1], 0)})")


# ── S2: WAU Composition (New / Continuing / Reactivated) ──
print("\n── S2: WAU Composition ──", flush=True)
s2_ever = set()
s2_prev = set()
s2_new_vals = {}
s2_cont_vals = {}
s2_react_vals = {}

# For trailing week: compute non-overlapping "previous 7 days" set
if HAS_TRAILING:
    _s2_trailing_prev_start = TRAILING_MONDAY - timedelta(days=7)
    _s2_trailing_prev_end = TRAILING_MONDAY - timedelta(days=1)
    _s2_trailing_prev = set()
    for uid, sd, days in activities:
        if days >= 4 and _s2_trailing_prev_start.date() <= sd.date() <= _s2_trailing_prev_end.date():
            _s2_trailing_prev.add(uid)
    print(f"  Trailing prev window: {_s2_trailing_prev_start.date()} ~ {_s2_trailing_prev_end.date()} ({len(_s2_trailing_prev)} users)")

for week in exp_weeks:
    cur = exp_weekly_sets.get(week, set())
    # For trailing week, use non-overlapping previous 7 days instead of s2_prev
    if HAS_TRAILING and week == TRAILING_MONDAY:
        prev_for_compare = _s2_trailing_prev
    else:
        prev_for_compare = s2_prev
    s2_n = cur - s2_ever
    s2_c = cur & prev_for_compare
    s2_r = (cur & s2_ever) - prev_for_compare
    s2_new_vals[week] = len(s2_n)
    s2_cont_vals[week] = len(s2_c)
    s2_react_vals[week] = len(s2_r)
    s2_ever |= cur
    s2_prev = cur

print("  Recent 4 weeks:")
for w in exp_chart_weeks[-4:]:
    tot = s2_new_vals.get(w, 0) + s2_cont_vals.get(w, 0) + s2_react_vals.get(w, 0)
    print(f"    {w.strftime('%Y-%m-%d')}: New={s2_new_vals.get(w, 0)}, Cont={s2_cont_vals.get(w, 0)}, React={s2_react_vals.get(w, 0)} (={tot})")


# ── S3: Dormancy Rate ──
print("\n── S3: Dormancy Rate ──", flush=True)
s3_dormant = {}
s3_activated = {}
s3_rate = {}

for i, week in enumerate(exp_weeks):
    # All users activated up to this week
    act_set = {uid for uid, aw in activation_week.items() if aw <= week}
    # Users active in last 4 weeks
    recent = set()
    for j in range(max(0, i - 3), i + 1):
        recent |= exp_weekly_sets.get(exp_weeks[j], set())
    dorm = act_set - recent
    rate = len(dorm) / len(act_set) * 100 if act_set else 0
    s3_dormant[week] = len(dorm)
    s3_activated[week] = len(act_set)
    s3_rate[week] = rate

print("  Recent 4 weeks:")
for w in exp_chart_weeks[-4:]:
    print(f"    {w.strftime('%Y-%m-%d')}: {s3_dormant.get(w, 0)}/{s3_activated.get(w, 0)} = {s3_rate.get(w, 0):.1f}%")


# ── S4: Query Depth ──
print("\n── S4: Query Depth (queries/user/week) ──", flush=True)
s4_depth = {}
for w in exp_weeks:
    nu = d4_unique_users_by_week[w]
    s4_depth[w] = d4_total_queries_by_week[w] / nu if nu > 0 else 0

print("  Recent 4 weeks:")
for w in exp_chart_weeks[-4:]:
    print(f"    {w.strftime('%Y-%m-%d')}: {s4_depth.get(w, 0):.1f}")


# ── S5: WAU/MAU Stickiness ──
print("\n── S5: WAU/MAU Stickiness ──", flush=True)
s5_ratio = {}
for week in exp_weeks:
    w_end = week_end_date(week)
    w28 = w_end - timedelta(days=27)
    # MAU: unique users with D4+ activity in 28-day window ending this week's Sunday
    mau_set = set()
    for uid, sd, days in activities:
        if days >= 4 and w28.date() <= sd.date() <= w_end.date():
            mau_set.add(uid)
    wau = len(exp_weekly_sets.get(week, set()))
    mau = len(mau_set)
    s5_ratio[week] = wau / mau * 100 if mau > 0 else 0

print("  Recent 4 weeks:")
for w in exp_chart_weeks[-4:]:
    print(f"    {w.strftime('%Y-%m-%d')}: {s5_ratio.get(w, 0):.1f}%")


# ── S6: W4 Retention by cohort ──
print("\n── S6: W4 Retention (by cohort) ──", flush=True)
# For each activated user: check if they were active 4 weeks after activation
exp_active_pairs = set()
for uid, sd, days in activities:
    if days >= 4:
        exp_active_pairs.add((uid, week_monday(sd)))

last_exp_week = exp_weeks[-1] if exp_weeks else None
s6_cohorts = defaultdict(lambda: {"total": 0, "retained": 0})

for uid, aw in activation_week.items():
    w4_week = aw + timedelta(weeks=4)
    if last_exp_week and w4_week <= last_exp_week:
        c = cohort_month(user_reg[uid])
        s6_cohorts[c]["total"] += 1
        if (uid, w4_week) in exp_active_pairs:
            s6_cohorts[c]["retained"] += 1

for c in sorted(s6_cohorts.keys()):
    d = s6_cohorts[c]
    rate = d["retained"] / d["total"] * 100 if d["total"] > 0 else 0
    print(f"  {c}: {d['retained']}/{d['total']} = {rate:.1f}%")


# ── S8: Day-of-Week Usage Pattern ──
print("\n── S8: Day-of-Week Usage Pattern ──", flush=True)
dow_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
dow_searches = defaultdict(int)
dow_users = defaultdict(set)
for uid, sd, days in activities:
    if days >= 4:
        d = sd.weekday()
        dow_searches[d] += 1
        dow_users[d].add(uid)

for d in range(7):
    print(f"  {dow_labels[d]}: {dow_searches[d]} searches, {len(dow_users[d])} users")


# ── S9: DAU/MAU Ratio ──
print("\n── S9: DAU/MAU Ratio ──", flush=True)
# DAU by date
dau_by_date = defaultdict(set)
for uid, sd, days in activities:
    if days >= 4:
        dau_by_date[sd.date()].add(uid)

s9_ratio = {}
for week in exp_weeks:
    w_start = week
    w_end = week_end_date(week)
    w28 = w_end - timedelta(days=27)
    # avg DAU in this week
    week_daus = []
    for dd in range(7):
        day = (w_start + timedelta(days=dd)).date()
        week_daus.append(len(dau_by_date.get(day, set())))
    avg_dau = sum(week_daus) / len(week_daus) if week_daus else 0
    # MAU (28-day window)
    mau_set = set()
    for uid, sd, days in activities:
        if days >= 4 and w28.date() <= sd.date() <= w_end.date():
            mau_set.add(uid)
    mau = len(mau_set)
    s9_ratio[week] = avg_dau / mau * 100 if mau > 0 else 0

print("  Recent 4 weeks:")
for w in exp_chart_weeks[-4:]:
    print(f"    {w.strftime('%Y-%m-%d')}: DAU/MAU={s9_ratio.get(w, 0):.1f}%")


# ── S10-S12: Enthusiasm Metrics (4-week rolling) ──
print("\n── S10-S12: Enthusiasm Metrics ──", flush=True)
s10_q_per_user = {}
s11_power_count = {}
s11_power_pct = {}
s12_top10_share = {}

for week in exp_weeks:
    w_end = week_end_date(week)
    w28 = w_end - timedelta(days=27)

    # Collect D4+ activity in 28-day window
    window_user_queries = defaultdict(int)  # user_id -> total queries in window
    window_user_week_queries = defaultdict(lambda: defaultdict(int))  # user_id -> week -> count
    for uid, sd, days in activities:
        if days >= 4 and w28.date() <= sd.date() <= w_end.date():
            window_user_queries[uid] += 1
            window_user_week_queries[uid][week_monday(sd)] += 1

    total_q = sum(window_user_queries.values())
    active_u = len(window_user_queries)

    # S10
    s10_q_per_user[week] = total_q / active_u if active_u > 0 else 0

    # S11: Power users (weekly avg queries >= 5 in 4-week window)
    power = 0
    for uid, wq in window_user_week_queries.items():
        avg_wq = sum(wq.values()) / len(wq) if wq else 0
        if avg_wq >= 5:
            power += 1
    s11_power_count[week] = power
    s11_power_pct[week] = power / active_u * 100 if active_u > 0 else 0

    # S12: Top 10% query concentration
    if total_q > 0:
        sorted_q = sorted(window_user_queries.values(), reverse=True)
        top10_n = max(1, int(len(sorted_q) * 0.1))
        top10_sum = sum(sorted_q[:top10_n])
        s12_top10_share[week] = top10_sum / total_q * 100
    else:
        s12_top10_share[week] = 0

if exp_chart_weeks:
    lw = exp_chart_weeks[-1]
    print(f"  Latest: S10={s10_q_per_user.get(lw, 0):.1f} q/user, S11={s11_power_count.get(lw, 0)} power users ({s11_power_pct.get(lw, 0):.0f}%), S12={s12_top10_share.get(lw, 0):.1f}%")

# ── S11b: Power Users (all users, no doctor filter) ──
print("\n── S11b: Power Users (all users) ──", flush=True)
s11b_power_count = {}

for week in exp_weeks:
    w_end = week_end_date(week)
    w28 = w_end - timedelta(days=27)
    wuq_all = defaultdict(lambda: defaultdict(int))
    for uid, sd, days in activities_all:
        if days >= 4 and w28.date() <= sd.date() <= w_end.date():
            wuq_all[uid][week_monday(sd)] += 1
    power = 0
    for uid, wq in wuq_all.items():
        avg_wq = sum(wq.values()) / len(wq) if wq else 0
        if avg_wq >= 5:
            power += 1
    s11b_power_count[week] = power

if exp_chart_weeks:
    lw = exp_chart_weeks[-1]
    print(f"  Latest: S11b={s11b_power_count.get(lw, 0)} (doctors: {s11_power_count.get(lw, 0)})")


# ══════════════════════════════════════════════
# S13-S16: New Exploration Metrics
# ══════════════════════════════════════════════
print("\n" + "=" * 50)
print("Computing S13-S16: Exploration Metrics...")
print("=" * 50, flush=True)

import math as _math

def _median(vals):
    s = sorted(vals)
    n = len(s)
    if n == 0: return 0
    return s[n // 2] if n % 2 == 1 else (s[n // 2 - 1] + s[n // 2]) / 2

# ── S13: Retained vs All WAU avg searches ──
print("\n-- S13: Retained WAU search depth --", flush=True)
s13_all_avg = {}
s13_ret_avg = {}
s13_new_avg = {}
s13_ret_n = {}

_s13_ever = set()
_s13_prev = set()
for week in exp_weeks:
    cur = exp_weekly_sets.get(week, set())
    retained = cur & _s13_prev
    new_users = cur - _s13_ever

    # All WAU avg
    all_searches = [d4_queries_by_week_user[week].get(uid, 0) for uid in cur]
    s13_all_avg[week] = sum(all_searches) / len(all_searches) if all_searches else 0

    # Retained avg
    ret_searches = [d4_queries_by_week_user[week].get(uid, 0) for uid in retained]
    s13_ret_avg[week] = sum(ret_searches) / len(ret_searches) if ret_searches else 0
    s13_ret_n[week] = len(retained)

    # New avg
    new_searches = [d4_queries_by_week_user[week].get(uid, 0) for uid in new_users]
    s13_new_avg[week] = sum(new_searches) / len(new_searches) if new_searches else 0

    _s13_ever |= cur
    _s13_prev = cur

print("  Recent 4 weeks:")
for w in exp_chart_weeks[-4:]:
    ratio = s13_ret_avg.get(w, 0) / s13_all_avg.get(w, 1) if s13_all_avg.get(w, 0) > 0 else 0
    print(f"    {w.strftime('%Y-%m-%d')}: All={s13_all_avg.get(w,0):.1f}, Retained({s13_ret_n.get(w,0)})={s13_ret_avg.get(w,0):.1f} ({ratio:.1f}x), New={s13_new_avg.get(w,0):.1f}")

# ── S14: Cohort Deepening (monthly) ──
print("\n-- S14: Cohort Deepening --", flush=True)
# Monthly search counts per user (D4+ only)
_user_monthly_searches = defaultdict(lambda: defaultdict(int))
for uid, sd, days in activities:
    if days >= 4:
        mk = sd.strftime('%Y-%m')
        _user_monthly_searches[uid][mk] += 1

# Group by activation month
_act_month_cohorts = defaultdict(list)
for uid, dt in first_d4.items():
    _act_month_cohorts[dt.strftime('%Y-%m')].append(uid)

_month_list = sorted(set(sd.strftime('%Y-%m') for _, sd, d in activities if d >= 4))

s14_data = {}  # {cohort_month: [(offset, active_n, total_n, avg_active, median_active)]}
for cm in sorted(_act_month_cohorts.keys()):
    if cm < '2025-11':
        continue
    users = _act_month_cohorts[cm]
    cm_idx = _month_list.index(cm) if cm in _month_list else -1
    if cm_idx < 0:
        continue
    series = []
    for offset in range(6):
        ti = cm_idx + offset
        if ti >= len(_month_list):
            break
        tm = _month_list[ti]
        vals = [_user_monthly_searches[uid].get(tm, 0) for uid in users]
        active_vals = [v for v in vals if v > 0]
        active_n = len(active_vals)
        avg_active = sum(active_vals) / len(active_vals) if active_vals else 0
        med_active = _median(active_vals) if active_vals else 0
        series.append((offset, tm, active_n, len(users), round(avg_active, 1), med_active))
    s14_data[cm] = series
    print(f"  Cohort {cm} (N={len(users)}):")
    for off, tm, an, tn, avg, med in series:
        print(f"    M+{off} ({tm}): active={an}/{tn}, avg(active)={avg}, median={med}")

# ── S15: Habitual Doctors (10+/28d, D4+ only) ──
print("\n-- S15: Habitual Doctors (10+ searches / 28d) --", flush=True)
s15_count = {}
s15_pct_mau = {}
s15_mau = {}
s15_avg_searches = {}
s15_user_sets = {}  # week -> set of heavy user IDs

s15_avg_active_days = {}

for week in exp_weeks:
    w_end = week_end_date(week)
    w28 = w_end - timedelta(days=27)
    u28 = defaultdict(int)
    u28_days = defaultdict(set)  # uid -> set of active dates
    for uid, sd, days in activities:
        if days >= 4 and w28.date() <= sd.date() <= w_end.date():
            u28[uid] += 1
            u28_days[uid].add(sd.date())
    mau = len(u28)
    hab_uids = {uid for uid, v in u28.items() if v >= 10}
    hab_counts = [u28[uid] for uid in hab_uids]
    hab = len(hab_uids)
    s15_count[week] = hab
    s15_mau[week] = mau
    s15_pct_mau[week] = round(hab / mau * 100, 1) if mau > 0 else 0
    s15_avg_searches[week] = round(sum(hab_counts) / hab, 1) if hab > 0 else 0
    s15_avg_active_days[week] = round(sum(len(u28_days[uid]) for uid in hab_uids) / hab, 1) if hab > 0 else 0
    s15_user_sets[week] = hab_uids

# ── S15 continuity: consecutive heavy users ──
s15_continuity_count = {}  # week -> count of users who were heavy in prev week too
s15_continuity_pct = {}    # week -> % of this week's heavy users who were also heavy last week
_sorted_exp_weeks = sorted(exp_weeks)
for i, week in enumerate(_sorted_exp_weeks):
    if i == 0:
        s15_continuity_count[week] = 0
        s15_continuity_pct[week] = 0
        continue
    prev_week = _sorted_exp_weeks[i - 1]
    curr_set = s15_user_sets.get(week, set())
    prev_set = s15_user_sets.get(prev_week, set())
    cont = len(curr_set & prev_set)
    s15_continuity_count[week] = cont
    # Retention view: what % of LAST week's heavy users remained heavy this week
    s15_continuity_pct[week] = round(cont / len(prev_set) * 100, 1) if prev_set else 0

print("  Recent 4 weeks:")
for w in exp_chart_weeks[-4:]:
    cont = s15_continuity_count.get(w, 0)
    cont_pct = s15_continuity_pct.get(w, 0)
    print(f"    {w.strftime('%Y-%m-%d')}: {s15_count.get(w,0)} ({s15_pct_mau.get(w,0)}% of MAU={s15_mau.get(w,0)}) avg={s15_avg_searches.get(w,0)}回 avg_days={s15_avg_active_days.get(w,0)}日 | 継続={cont} ({cont_pct}%)")

# ── S17: 習慣化ユーザー (3/4週で1回以上, D4+) ──
print("\n-- S17: Habitual Users (3/4 weeks active, D4+) --", flush=True)
s17_count = {}
s17_avg_days = {}
s17_avg_searches = {}
s17_user_sets = {}

for week in exp_weeks:
    w_end = week_end_date(week)
    w28 = w_end - timedelta(days=27)
    # Per-user: search count, active days, weekly activity
    u_searches = defaultdict(int)
    u_days = defaultdict(set)
    u_weekly = defaultdict(lambda: defaultdict(int))
    for uid, sd, days_since in activities:
        if days_since >= 4 and w28.date() <= sd.date() <= w_end.date():
            u_searches[uid] += 1
            u_days[uid].add(sd.date())
            u_weekly[uid][week_monday(sd)] += 1
    # Filter: active in 3+ of the weeks within the 28-day window
    hab_uids = set()
    for uid in u_searches:
        active_weeks = sum(1 for wm, cnt in u_weekly[uid].items() if cnt >= 1)
        if active_weeks >= 3:
            hab_uids.add(uid)
    s17_count[week] = len(hab_uids)
    s17_avg_days[week] = round(sum(len(u_days[uid]) for uid in hab_uids) / len(hab_uids), 1) if hab_uids else 0
    s17_avg_searches[week] = round(sum(u_searches[uid] for uid in hab_uids) / len(hab_uids), 1) if hab_uids else 0
    s17_user_sets[week] = hab_uids

print("  Recent 4 weeks:")
for w in exp_chart_weeks[-4:]:
    print(f"    {w.strftime('%Y-%m-%d')}: {s17_count.get(w,0)}人 avg_days={s17_avg_days.get(w,0)} avg_searches={s17_avg_searches.get(w,0)}")

# ── S15b: Habitual Users (all users, D4+ only, 10+/28d) with doctor breakdown ──
print("\n-- S15b: Habitual Users - all users, D4+ (10+ searches / 28d) --", flush=True)
s15b_count = {}
s15b_mau = {}
s15b_avg_searches = {}
s15b_doctor_count = {}
s15b_nondoctor_count = {}

for week in exp_weeks:
    w_end = week_end_date(week)
    w28 = w_end - timedelta(days=27)
    u28_all = defaultdict(int)
    for uid, sd, days in activities_all:
        if days >= 4 and w28.date() <= sd.date() <= w_end.date():
            u28_all[uid] += 1
    mau_all = len(u28_all)
    hab_all_uids = {uid for uid, v in u28_all.items() if v >= 10}
    hab_all_counts = [u28_all[uid] for uid in hab_all_uids]
    hab_all = len(hab_all_uids)
    hab_doctor_uids = hab_all_uids & set(user_reg.keys())
    hab_nondoctor_uids = hab_all_uids - set(user_reg.keys())
    s15b_count[week] = hab_all
    s15b_mau[week] = mau_all
    s15b_avg_searches[week] = round(sum(hab_all_counts) / hab_all, 1) if hab_all > 0 else 0
    s15b_doctor_count[week] = len(hab_doctor_uids)
    s15b_nondoctor_count[week] = len(hab_nondoctor_uids)

print("  Recent 4 weeks:")
for w in exp_chart_weeks[-4:]:
    _all = s15b_count.get(w, 0)
    _doc = s15b_doctor_count.get(w, 0)
    _nondoc = s15b_nondoctor_count.get(w, 0)
    print(f"    {w.strftime('%Y-%m-%d')}: All={_all} (Doctor={_doc}, Non-doctor={_nondoc}) MAU_all={s15b_mau.get(w,0)}, avg={s15b_avg_searches.get(w,0)}")

# ── S16: Post-Activation Monthly Retention (per-user rolling 30d windows) ──
# Each user's timeline starts from their own activation date (first D4+ search).
# M+0 = Day 0 (activation day only, trivially 100%)
# M+1 = Day 1-30 after activation
# M+2 = Day 31-60
# M+3 = Day 61-90, etc.
# Cohorts grouped by activation month.
print("\n-- S16: Post-Activation Monthly Retention (per-user rolling) --", flush=True)

# Build set of active dates per user (D4+ only)
_user_active_dates = defaultdict(set)
for uid, sd, days in activities:
    if days >= 4:
        _user_active_dates[uid].add(sd.date())

# Group by activation month, merging small cohorts (same as retention heatmap)
_S16_MERGE_MONTHS = {"2025-07", "2025-08", "2025-09", "2025-10"}
_S16_MERGED_LABEL = "2025-07~10"

_s16_cohort_users = defaultdict(list)
for uid, dt in first_d4.items():
    am = dt.strftime('%Y-%m')
    label = _S16_MERGED_LABEL if am in _S16_MERGE_MONTHS else am
    _s16_cohort_users[label].append(uid)

s16_matrix = {}  # activation_month -> {n, retention: [M0%, M1%, M2%, ...]}
for am in sorted(_s16_cohort_users.keys()):
    if am < '2025-06':
        continue
    users = _s16_cohort_users[am]
    n = len(users)
    if n < 3:
        continue
    # Find latest activation date in cohort — trim periods based on this
    latest_act = max(first_d4[uid].date() for uid in users)
    ret = []
    for period in range(13):  # up to M+12 (360 days)
        if period == 0:
            # M+0: activation day itself (always 100%)
            ret.append(100.0)
            continue
        # M+N: day ((N-1)*30+1) to (N*30) after activation
        day_start = (period - 1) * 30 + 1
        day_end = period * 30
        # Trim: only show period if ALL cohort members have completed it
        if latest_act + timedelta(days=day_end) > DATA_END.date():
            break  # this period not yet complete for all members
        active = 0
        for uid in users:
            act_date = first_d4[uid].date()
            window_start = act_date + timedelta(days=day_start)
            window_end = act_date + timedelta(days=day_end)
            user_dates = _user_active_dates.get(uid, set())
            if any(window_start <= d <= window_end for d in user_dates):
                active += 1
        ret.append(round(active / n * 100, 1))
    if len(ret) > 1:  # at least M+0 and M+1
        s16_matrix[am] = {'n': n, 'ret': ret}
        curve = " | ".join([f"M+{i}:{ret[i]}%" for i in range(len(ret))])
        print(f"  {am} (N={n}): {curve}")

# Weighted average
s16_wavg = []
max_off = max(len(d['ret']) for d in s16_matrix.values()) if s16_matrix else 0
for offset in range(max_off):
    tw, tv = 0, 0
    for d in s16_matrix.values():
        if offset < len(d['ret']):
            tw += d['n']
            tv += d['ret'][offset] * d['n']
    s16_wavg.append(round(tv / tw, 1) if tw > 0 else None)

if s16_wavg:
    curve = " | ".join([f"M+{i}:{s16_wavg[i]}%" if s16_wavg[i] is not None else f"M+{i}:-" for i in range(len(s16_wavg))])
    print(f"  Weighted avg: {curve}")
    m1_3 = [v for v in s16_wavg[1:4] if v is not None]
    if m1_3:
        print(f"  Stabilized (M1-M3 avg): {sum(m1_3)/len(m1_3):.1f}%")

print("[OK] S13-S16 computed", flush=True)


# ══════════════════════════════════════════════
# Chart 4a: S1 Activation Rate
# ══════════════════════════════════════════════
print("\n" + "=" * 50)
print("Chart 4a: S1 Activation Rate")
print("=" * 50, flush=True)

fig, ax = plt.subplots(figsize=(10, 5))
s1_weeks = [w for w in exp_chart_weeks if w in act_rate_ts]
s1_vals = [act_rate_ts[w] for w in s1_weeks]
ax.plot(s1_weeks, s1_vals, marker="o", ms=5, lw=2, color="#2196F3")
ax.set_ylabel("アクティベーション率（%）")
ax.set_ylim(0, 105)
ax.set_title("(参考) 累計アクティベーション率", fontsize=14, fontweight="bold")
if s1_vals:
    ax.annotate(f"{s1_vals[-1]:.1f}%", (s1_weeks[-1], s1_vals[-1]),
                textcoords="offset points", xytext=(0, 10), ha="center", fontsize=10)
set_weekly_xticks(ax, s1_weeks)
fig.tight_layout()
fig.savefig(OUTPUT_DIR / "chart4a_s1_activation.png", dpi=150, bbox_inches="tight")
print("[OK] Chart 4a -> output/chart4a_s1_activation.png", flush=True)
plt.close(fig)

# ══════════════════════════════════════════════
# Chart 4b: S2 WAU Composition
# ══════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(10, 5))
s2_weeks = [w for w in exp_chart_weeks if w in s2_cont_vals]
s2_c = [s2_cont_vals[w] for w in s2_weeks]
s2_r = [s2_react_vals[w] for w in s2_weeks]
s2_n = [s2_new_vals[w] for w in s2_weeks]
s2_cr = [c + r for c, r in zip(s2_c, s2_r)]
_s2_x = list(range(len(s2_weeks)))
ax.bar(_s2_x, s2_c, width=0.7, label="継続", color="#4CAF50")
ax.bar(_s2_x, s2_r, width=0.7, bottom=s2_c, label="復帰", color="#FF9800")
ax.bar(_s2_x, s2_n, width=0.7, bottom=s2_cr, label="新規", color="#2196F3")
ax.set_ylabel("WAU（人）")
ax.set_title("7. WAU構成（新規 / 継続 / 復帰）", fontsize=14, fontweight="bold")
ax.legend(fontsize=9, loc="upper left")
set_weekly_xticks(ax, s2_weeks, equal_spacing=True)
fig.tight_layout()
fig.savefig(OUTPUT_DIR / "chart4b_s2_composition.png", dpi=150, bbox_inches="tight")
print("[OK] Chart 4b -> output/chart4b_s2_composition.png", flush=True)
plt.close(fig)

# ══════════════════════════════════════════════
# Chart 5a: S5 WAU/MAU Stickiness
# ══════════════════════════════════════════════
print("\n" + "=" * 50)
print("Chart 5: Engagement Metrics")
print("=" * 50, flush=True)

fig, ax = plt.subplots(figsize=(10, 5))
s5_weeks = [w for w in exp_chart_weeks if w in s5_ratio]
s5_vals = [s5_ratio[w] for w in s5_weeks]
ax.plot(s5_weeks, s5_vals, marker="o", ms=5, lw=2, color="#00BCD4")
# (60% reference line removed)
ax.set_ylabel("WAU/MAU（%）")
ax.set_title("11. WAU/MAU比率", fontsize=14, fontweight="bold")
ax.legend(fontsize=9)
if s5_vals:
    ax.annotate(f"{s5_vals[-1]:.1f}%", (s5_weeks[-1], s5_vals[-1]),
                textcoords="offset points", xytext=(0, 10), ha="center", fontsize=10)
# X-axis: week-end date only (28-day window metric)
ax.set_xticks(s5_weeks)
ax.set_xticklabels([week_end_label(w) for w in s5_weeks], rotation=45, ha="right")
fig.tight_layout()
fig.savefig(OUTPUT_DIR / "chart5a_s5_stickiness.png", dpi=150, bbox_inches="tight")
print("[OK] Chart 5a -> output/chart5a_s5_stickiness.png", flush=True)
plt.close(fig)

# ══════════════════════════════════════════════
# Chart 5b: S9 DAU/MAU Ratio
# ══════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(10, 5))
s9_weeks = [w for w in exp_chart_weeks if w in s9_ratio]
s9_vals = [s9_ratio[w] for w in s9_weeks]
ax.plot(s9_weeks, s9_vals, marker="o", ms=5, lw=2, color="#795548")
ax.set_ylabel("DAU/MAU（%）")
ax.set_title("12. DAU/MAU比率", fontsize=14, fontweight="bold")
if s9_vals:
    ax.annotate(f"{s9_vals[-1]:.1f}%", (s9_weeks[-1], s9_vals[-1]),
                textcoords="offset points", xytext=(0, 10), ha="center", fontsize=10)
# X-axis: week-end date only (28-day window metric)
ax.set_xticks(s9_weeks)
ax.set_xticklabels([week_end_label(w) for w in s9_weeks], rotation=45, ha="right")
fig.tight_layout()
fig.savefig(OUTPUT_DIR / "chart5b_s9_dau_mau.png", dpi=150, bbox_inches="tight")
print("[OK] Chart 5b -> output/chart5b_s9_dau_mau.png", flush=True)
plt.close(fig)

# ══════════════════════════════════════════════
# Chart 5c: S8 Day-of-Week Usage
# ══════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(10, 5))
x8 = list(range(7))
s8_searches = [dow_searches[d] for d in range(7)]
s8_users = [len(dow_users[d]) for d in range(7)]
ax.bar(x8, s8_searches, color="#607D8B", alpha=0.7, label="検索数")
ax.set_xticks(x8)
ax.set_xticklabels(dow_labels)
ax.set_ylabel("検索数")
ax.set_title("(参考) 曜日別利用パターン", fontsize=14, fontweight="bold")
ax8r = ax.twinx()
ax8r.plot(x8, s8_users, marker="o", color="#E91E63", lw=2, label="ユニークユーザー数")
ax8r.set_ylabel("ユニークユーザー数", color="#E91E63")
h1, l1 = ax.get_legend_handles_labels()
h2, l2 = ax8r.get_legend_handles_labels()
ax.legend(h1 + h2, l1 + l2, fontsize=9, loc="upper right")
fig.tight_layout()
fig.savefig(OUTPUT_DIR / "chart5c_s8_dow.png", dpi=150, bbox_inches="tight")
print("[OK] Chart 5c -> output/chart5c_s8_dow.png", flush=True)
plt.close(fig)


# ══════════════════════════════════════════════
# Chart 6: Retention Heatmap (S7)
# ══════════════════════════════════════════════
print("\n" + "=" * 50)
print("Chart 6: Retention Heatmap")
print("=" * 50, flush=True)

# Build heatmap matrix from ret_data, ret_sizes, max_obs
hm_labels = sorted(ret_sizes.keys())
hm_max_p = max(max_obs.get(l, -1) for l in hm_labels)
hm_periods = list(range(0, hm_max_p + 1))
hm_col_labels = [period_label(p) for p in hm_periods]

hm_matrix = np.full((len(hm_labels), len(hm_periods)), np.nan)
for i, label in enumerate(hm_labels):
    for j, p in enumerate(hm_periods):
        if p <= max_obs.get(label, -1) and p in ret_data[label]:
            hm_matrix[i, j] = len(ret_data[label][p]) / ret_sizes[label] * 100

fig6, ax6 = plt.subplots(figsize=(12, 5))
im = ax6.imshow(hm_matrix, cmap="YlOrRd_r", aspect="auto", vmin=0, vmax=100)
ax6.set_xticks(range(len(hm_col_labels)))
ax6.set_xticklabels(hm_col_labels)
ax6.set_yticks(range(len(hm_labels)))
ax6.set_yticklabels([f"{l} (n={ret_sizes[l]})" for l in hm_labels])
for i in range(len(hm_labels)):
    for j in range(len(hm_col_labels)):
        v = hm_matrix[i, j]
        if not np.isnan(v):
            ax6.text(j, i, f"{v:.1f}", ha="center", va="center", fontsize=9)
fig6.colorbar(im, ax=ax6, label="リテンション率（%）")
ax6.set_title("9. コホート別リテンション ヒートマップ（登録月基準）", fontsize=13, fontweight="bold")
ax6.set_xlabel("リテンション期間")
ax6.set_ylabel("登録月コホート")
fig6.tight_layout()
fig6.savefig(OUTPUT_DIR / "chart6_retention_heatmap.png", dpi=150, bbox_inches="tight")
print("[OK] Chart 6 -> output/chart6_retention_heatmap.png", flush=True)
plt.close(fig6)


# ══════════════════════════════════════════════
# Chart 7: Enthusiasm Metrics (S11)
# ══════════════════════════════════════════════
print("\n" + "=" * 50)
print("Chart 7: Enthusiasm Metrics (S11)")
print("=" * 50, flush=True)

fig7, ax7 = plt.subplots(1, 1, figsize=(10, 5))

ec_weeks = [w for w in exp_chart_weeks if w in s11_power_count]

# S11: Power User Count
ec11 = [s11_power_count[w] for w in ec_weeks]
_ec_x = list(range(len(ec_weeks)))
bars = ax7.bar(_ec_x, ec11, color="#ec4899", width=0.7)
for bar, val in zip(bars, ec11):
    ax7.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
            str(int(val)), ha="center", fontsize=8)
ax7.set_ylabel("定着指数（週平均5回以上の医師数）")
ax7.set_title("(参考) 定着指数（4週ローリング）", fontweight="bold")
set_weekly_xticks(ax7, ec_weeks, equal_spacing=True)

fig7.tight_layout()
fig7.savefig(OUTPUT_DIR / "chart7_enthusiasm.png", dpi=150, bbox_inches="tight")
print("[OK] Chart 7 -> output/chart7_enthusiasm.png", flush=True)
plt.close(fig7)

# ── Chart 7b: Power User Count (all users) ──
fig7b, ax7b = plt.subplots(1, 1, figsize=(10, 5))
ec_weeks_b = [w for w in exp_chart_weeks if w in s11b_power_count]
ec11_doc = [s11_power_count.get(w, 0) for w in ec_weeks_b]
ec11_all = [s11b_power_count.get(w, 0) for w in ec_weeks_b]
_ec_x_b = list(range(len(ec_weeks_b)))
bars_all = ax7b.bar(_ec_x_b, ec11_all, color="#90CAF9", width=0.7, label="全ユーザー")
bars_doc = ax7b.bar(_ec_x_b, ec11_doc, color="#ec4899", width=0.7, label="医師のみ")
for bar, val_a, val_d in zip(bars_all, ec11_all, ec11_doc):
    ax7b.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
              str(int(val_a)), ha="center", fontsize=8, color="#1976D2")
ax7b.set_ylabel("定着指数（週平均5回以上のユーザー数）")
ax7b.set_title("(参考) 定着指数 — 全ユーザー vs 医師のみ", fontweight="bold")
ax7b.legend(loc="upper left", fontsize=9)
set_weekly_xticks(ax7b, ec_weeks_b, equal_spacing=True)
fig7b.tight_layout()
fig7b.savefig(OUTPUT_DIR / "chart7b_enthusiasm_all.png", dpi=150, bbox_inches="tight")
print("[OK] Chart 7b -> output/chart7b_enthusiasm_all.png", flush=True)
plt.close(fig7b)


# ══════════════════════════════════════════════
# Chart 11: Exploration Metrics (S13-S16) — 2x2
# ══════════════════════════════════════════════
print("\n" + "=" * 50)
print("Chart 11: Exploration Metrics (S13, S15, S16, S16b)")
print("=" * 50, flush=True)

# ── Chart 11a: S13 Search Depth by User Type ──
fig, ax = plt.subplots(figsize=(10, 5))
s13_weeks = [w for w in exp_chart_weeks if w in s13_all_avg]
ax.plot(s13_weeks, [s13_ret_avg.get(w, 0) for w in s13_weeks],
        marker="o", ms=5, lw=2, color="#4CAF50", label="継続ユーザー")
ax.plot(s13_weeks, [s13_all_avg.get(w, 0) for w in s13_weeks],
        marker="s", ms=4, lw=1.5, color="#90CAF9", label="全WAU")
ax.plot(s13_weeks, [s13_new_avg.get(w, 0) for w in s13_weeks],
        marker="^", ms=4, lw=1, color="#BDBDBD", alpha=0.7, label="新規")
ax.set_ylabel("平均検索回数 / ユーザー / 週")
ax.set_title("(参考) ユーザータイプ別 週次検索回数", fontsize=14, fontweight="bold")
ax.legend(fontsize=9, loc="upper left")
if s13_weeks:
    ax.annotate(f"Ret:{s13_ret_avg.get(s13_weeks[-1],0):.1f}",
                (s13_weeks[-1], s13_ret_avg.get(s13_weeks[-1], 0)),
                textcoords="offset points", xytext=(0, 10), ha="center", fontsize=10, color="#4CAF50")
set_weekly_xticks(ax, s13_weeks)
fig.tight_layout()
fig.savefig(OUTPUT_DIR / "chart11a_s13_search_depth.png", dpi=150, bbox_inches="tight")
print("[OK] Chart 11a -> output/chart11a_s13_search_depth.png", flush=True)
plt.close(fig)

# ── Chart 11b: S15 Habitual Doctors (bar + avg line) ──
s15_weeks = [w for w in exp_chart_weeks if w in s15_count]
s15_c_vals = [s15_count.get(w, 0) for w in s15_weeks]
s15_avg_vals = [s15_avg_searches.get(w, 0) for w in s15_weeks]
_s15_x = list(range(len(s15_weeks)))
_s15_xlabels = [week_end_label(w) for w in s15_weeks]

# Chart 11b: ヘビーユーザー数（上）+ 平均検索回数（中）+ 平均アクティブ日数（下）— 3段構成
s15_days_vals = [s15_avg_active_days.get(w, 0) for w in s15_weeks]
fig, (ax_top, ax_mid, ax_bot) = plt.subplots(3, 1, figsize=(10, 10), sharex=True,
                                              gridspec_kw={"height_ratios": [3, 2, 2]})

# Top: 棒グラフ — ヘビーユーザー数（医師=濃紫 + 非医師=薄紫を上乗せ）
# Non-doctor heavy users from S15c (all users, D4+) on top as reference
_s15_nondoc_vals = [s15b_nondoctor_count.get(w, 0) for w in s15_weeks]
_s15_total_vals = [d + nd for d, nd in zip(s15_c_vals, _s15_nondoc_vals)]
ax_top.bar(_s15_x, s15_c_vals, width=0.7, color="#9C27B0", alpha=0.85, label="医師")
ax_top.bar(_s15_x, _s15_nondoc_vals, width=0.7, bottom=s15_c_vals, color="#90CAF9", alpha=0.45, label="医師未登録（参考）")
ax_top.set_ylabel("ヘビーユーザー数")
ax_top.set_title("2. ヘビーユーザー詳細（人数・検索回数・アクティブ日数）", fontsize=14, fontweight="bold")
ax_top.legend(loc="upper left", fontsize=8)
if s15_c_vals:
    for _xi, _v, _vnd, _vtotal in zip(_s15_x, s15_c_vals, _s15_nondoc_vals, _s15_total_vals):
        # Doctor count (KGI) — bold
        ax_top.text(_xi, _v + 0.3 if _vnd == 0 else _v / 2, str(_v), ha="center", fontsize=9, color="#9C27B0" if _vnd == 0 else "white", fontweight="bold")
        # Non-doctor count on top (if > 0)
        if _vnd > 0:
            ax_top.text(_xi, _v + _vnd / 2, str(_vnd), ha="center", fontsize=8, color="#7B1FA2", alpha=0.7)
            ax_top.text(_xi, _vtotal + 0.3, str(_vtotal), ha="center", fontsize=8, color="#42A5F5")

# Middle: 折れ線 — 平均検索回数
ax_mid.plot(_s15_x, s15_avg_vals, color="#FF9800", marker="o", linewidth=2)
ax_mid.set_ylabel("平均検索回数/人")
ax_mid.set_ylim(0, max(s15_avg_vals) * 1.3 if s15_avg_vals and max(s15_avg_vals) > 0 else 30)
for _xi, _v in zip(_s15_x, s15_avg_vals):
    ax_mid.text(_xi, _v + 0.5, f"{_v:.1f}", ha="center", fontsize=9, color="#FF9800", fontweight="bold")

# Bottom: 折れ線 — 平均アクティブ日数
ax_bot.plot(_s15_x, s15_days_vals, color="#2196F3", marker="s", linewidth=2)
ax_bot.fill_between(_s15_x, s15_days_vals, alpha=0.1, color="#2196F3")
ax_bot.set_ylabel("平均アクティブ日数/人")
ax_bot.axhline(y=28, color="#ccc", linestyle=":", linewidth=1)
ax_bot.set_ylim(0, 28)
ax_bot.text(len(_s15_x) - 1, 28.5, "28日（上限）", fontsize=8, color="#999", ha="right")
for _xi, _v in zip(_s15_x, s15_days_vals):
    ax_bot.text(_xi, _v + 0.7, f"{_v:.1f}", ha="center", fontsize=9, color="#2196F3", fontweight="bold")
ax_bot.set_xticks(_s15_x)
ax_bot.set_xticklabels(_s15_xlabels, rotation=45, ha="right")

fig.tight_layout()
fig.savefig(OUTPUT_DIR / "chart11b_s15_habitual.png", dpi=150, bbox_inches="tight")
print("[OK] Chart 11b -> output/chart11b_s15_habitual.png", flush=True)
plt.close(fig)

# ══════════════════════════════════════════════
# DEFERRED CHART 3: KGI/KPI Weekly Trends (needs s15_count)
# ══════════════════════════════════════════════
print("\n" + "=" * 50)
print("Chart 3 (deferred): KGI/KPI Weekly Trends")
print("=" * 50)

heavy_vals_cw = [s15_count.get(w, 0) for w in common_weeks]
mau_rate_vals_cw = [mau_rate_by_week.get(w, 0) for w in common_weeks]
heavy_rate_vals_cw = [s15_pct_mau.get(w, 0) for w in common_weeks]

# Heavy User plan line: fixed milestones from 3/1 (see HEAVY_PLAN_MILESTONES at module top).
# HEAVY_PLAN_WEEKS / VALS / MAU_RATE / HEAVY_RATE are precomputed at module load.

fig3, axes3 = plt.subplots(5, 1, figsize=(14, 20), sharex=True)

# 1段目: KGI: ヘビーユーザー数
ax1 = axes3[0]
ax1.plot(common_weeks, heavy_vals_cw, marker="o", markersize=4, linewidth=2, color="#7B1FA2", label="実績")
ax1.plot(HEAVY_PLAN_WEEKS, HEAVY_PLAN_VALS, linestyle="--", linewidth=1.5, color="#7B1FA2", alpha=0.4, label="計画")
ax1.scatter([HEAVY_PLAN_WEEKS[-1]], [HEAVY_PLAN_VALS[-1]], marker="*", s=120, color="#7B1FA2", alpha=0.6, zorder=5)
ax1.annotate(f"目標: {TARGET_HEAVY}", (HEAVY_PLAN_WEEKS[-1], HEAVY_PLAN_VALS[-1]),
             textcoords="offset points", xytext=(-50, 10), ha="center", fontsize=9, color="#7B1FA2", fontweight="bold")
ax1.set_ylabel("ヘビーユーザー数", fontsize=11)
ax1.set_title("A1. ヘビーユーザー分解（実績 vs 計画）", fontsize=14, fontweight="bold")
ax1.text(0.01, 0.95, "ヘビーユーザー数（28日間10回以上検索・医師）", transform=ax1.transAxes,
         fontsize=10, fontweight="bold", va="top", color="#7B1FA2")
ax1.legend(loc="center left", fontsize=8, framealpha=0.7)
for idx in [0, -1]:
    if heavy_vals_cw[idx] > 0:
        ax1.annotate(f"{heavy_vals_cw[idx]}", (common_weeks[idx], heavy_vals_cw[idx]),
                     textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8, color="#555")
ax1.set_xlim(fd3 - timedelta(days=3), ld3_extended + timedelta(days=7))

# 2段目: KPI1: 登録医師数
ax2 = axes3[1]
ax2.plot(common_weeks, reg_vals, marker="o", markersize=4, linewidth=2, color="#4CAF50", label="実績")
ax2.plot(PLAN_WEEKS, PLAN_REG, linestyle="--", linewidth=1.5, color="#4CAF50", alpha=0.4, label="計画")
ax2.scatter([PLAN_WEEKS[-1]], [PLAN_REG[-1]], marker="*", s=120, color="#4CAF50", alpha=0.6, zorder=5)
ax2.annotate(f"目標: {TARGET_REG:,}", (PLAN_WEEKS[-1], PLAN_REG[-1]),
             textcoords="offset points", xytext=(-50, 10), ha="center", fontsize=9, color="#4CAF50", fontweight="bold")
ax2.set_ylabel("累計登録医師数", fontsize=11)
ax2.text(0.01, 0.95, "登録医師数", transform=ax2.transAxes,
         fontsize=10, fontweight="bold", va="top", color="#4CAF50")
ax2.legend(loc="center left", fontsize=8, framealpha=0.7)
for idx in [0, -1]:
    ax2.annotate(f"{reg_vals[idx]}", (common_weeks[idx], reg_vals[idx]),
                 textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8, color="#555")

# 3段目: 参考: メール登録数
ax2e = axes3[2]
ax2e.plot(common_weeks, email_reg_vals, marker="o", markersize=4, linewidth=2, color="#1976D2", label="実績")
ax2e.plot(EMAIL_PLAN_WEEKS, EMAIL_PLAN_REG, linestyle="--", linewidth=1.5, color="#1976D2", alpha=0.4, label=f"計画（確定転換率{LATEST_CONV_RATE*100:.0f}%）")
ax2e.scatter([EMAIL_PLAN_WEEKS[-1]], [EMAIL_PLAN_REG[-1]], marker="*", s=120, color="#1976D2", alpha=0.6, zorder=5)
ax2e.annotate(f"必要数: {EMAIL_TARGET_REG:,}", (EMAIL_PLAN_WEEKS[-1], EMAIL_PLAN_REG[-1]),
              textcoords="offset points", xytext=(-60, 10), ha="center", fontsize=9, color="#1976D2", fontweight="bold")
ax2e.set_ylabel("累計メール登録数", fontsize=11)
ax2e.text(0.01, 0.95, "参考: メール登録数", transform=ax2e.transAxes,
          fontsize=10, fontweight="bold", va="top", color="#1976D2")
ax2e.legend(loc="center left", fontsize=8, framealpha=0.7)
for idx in [0, -1]:
    ax2e.annotate(f"{email_reg_vals[idx]}", (common_weeks[idx], email_reg_vals[idx]),
                  textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8, color="#555")

# 4段目: KPI2: MAU率
ax3a = axes3[3]
ax3a.plot(common_weeks, mau_rate_vals_cw, marker="o", markersize=4, linewidth=2, color="#E91E63", label="実績")
ax3a.plot(HEAVY_PLAN_WEEKS, HEAVY_PLAN_MAU_RATE, linestyle="--", linewidth=1.5, color="#E91E63", alpha=0.4, label="計画")
ax3a.scatter([HEAVY_PLAN_WEEKS[-1]], [TARGET_MAU_RATE], marker="*", s=120, color="#E91E63", alpha=0.6, zorder=5)
ax3a.annotate(f"目標: {TARGET_MAU_RATE}%", (HEAVY_PLAN_WEEKS[-1], TARGET_MAU_RATE),
              textcoords="offset points", xytext=(-50, 10), ha="center", fontsize=9, color="#E91E63", fontweight="bold")
ax3a.set_ylabel("MAU率 (%)", fontsize=11)
ax3a.text(0.01, 0.95, "MAU率（MAU / 累計登録医師数）", transform=ax3a.transAxes,
         fontsize=10, fontweight="bold", va="top", color="#E91E63")
ax3a.legend(loc="center left", fontsize=8, framealpha=0.7)
for idx in [0, -1]:
    ax3a.annotate(f"{mau_rate_vals_cw[idx]:.1f}%", (common_weeks[idx], mau_rate_vals_cw[idx]),
                 textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8, color="#555")

# 5段目: KPI3: ヘビー化率（Heavy / MAU）
ax4 = axes3[4]
ax4.plot(common_weeks, heavy_rate_vals_cw, marker="o", markersize=4, linewidth=2, color="#FF9800", label="実績")
ax4.plot(HEAVY_PLAN_WEEKS, HEAVY_PLAN_HEAVY_RATE, linestyle="--", linewidth=1.5, color="#FF9800", alpha=0.4, label="計画")
ax4.scatter([HEAVY_PLAN_WEEKS[-1]], [TARGET_HEAVY_RATE], marker="*", s=120, color="#FF9800", alpha=0.6, zorder=5)
ax4.annotate(f"目標: {TARGET_HEAVY_RATE}%", (HEAVY_PLAN_WEEKS[-1], TARGET_HEAVY_RATE),
             textcoords="offset points", xytext=(-50, 10), ha="center", fontsize=9, color="#FF9800", fontweight="bold")
ax4.set_ylabel("ヘビー化率 (%)", fontsize=11)
ax4.set_xlabel("週", fontsize=12)
ax4.text(0.01, 0.95, "ヘビー化率（ヘビーユーザー / MAU）", transform=ax4.transAxes,
         fontsize=10, fontweight="bold", va="top", color="#FF9800")
ax4.legend(loc="center left", fontsize=8, framealpha=0.7)
for idx in [0, -1]:
    ax4.annotate(f"{heavy_rate_vals_cw[idx]:.1f}%", (common_weeks[idx], heavy_rate_vals_cw[idx]),
                 textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8, color="#555")

ax4.set_xticks(ticks3)
ax4.set_xticklabels(labels3, rotation=45, ha="right")
plt.tight_layout()
fig3.savefig(OUTPUT_DIR / "chart3_kpi_trends.png", dpi=150, bbox_inches="tight")
print(f"[OK] Chart 3 -> output/chart3_kpi_trends.png", flush=True)
plt.close(fig3)

# ══════════════════════════════════════════════
# Appendix Chart 1: KGI/KPI Weekly Trends (TARGET_HEAVY = 100)
# ══════════════════════════════════════════════
print("\n" + "=" * 50)
print("Appendix Chart 1: KGI/KPI Weekly Trends (Target=100)")
print("=" * 50, flush=True)

# Appendix heavy plan line: fixed milestones from 3/1 (see APP_HEAVY_PLAN_MILESTONES at module top).
# APP_HEAVY_PLAN_WEEKS / VALS / MAU_RATE / HEAVY_RATE are precomputed at module load.

fig_app1, axes_app1 = plt.subplots(5, 1, figsize=(14, 20), sharex=True)

# 1段目: KGI: ヘビーユーザー数
ax1 = axes_app1[0]
ax1.plot(common_weeks, heavy_vals_cw, marker="o", markersize=4, linewidth=2, color="#7B1FA2", label="実績")
ax1.plot(APP_HEAVY_PLAN_WEEKS, APP_HEAVY_PLAN_VALS, linestyle="--", linewidth=1.5, color="#7B1FA2", alpha=0.4, label="計画")
ax1.scatter([APP_HEAVY_PLAN_WEEKS[-1]], [APP_HEAVY_PLAN_VALS[-1]], marker="*", s=120, color="#7B1FA2", alpha=0.6, zorder=5)
ax1.annotate(f"目標: {APP_TARGET_HEAVY}", (APP_HEAVY_PLAN_WEEKS[-1], APP_HEAVY_PLAN_VALS[-1]),
             textcoords="offset points", xytext=(-50, 10), ha="center", fontsize=9, color="#7B1FA2", fontweight="bold")
ax1.set_ylabel("ヘビーユーザー数", fontsize=11)
ax1.set_title("A1. ヘビーユーザー分解（実績 vs 計画）", fontsize=14, fontweight="bold")
ax1.text(0.01, 0.95, "ヘビーユーザー数（28日間10回以上検索・医師）", transform=ax1.transAxes,
         fontsize=10, fontweight="bold", va="top", color="#7B1FA2")
ax1.legend(loc="center left", fontsize=8, framealpha=0.7)
for idx in [0, -1]:
    if heavy_vals_cw[idx] > 0:
        ax1.annotate(f"{heavy_vals_cw[idx]}", (common_weeks[idx], heavy_vals_cw[idx]),
                     textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8, color="#555")
ax1.set_xlim(fd3 - timedelta(days=3), ld3_extended + timedelta(days=7))

# 2段目: KPI1: 登録医師数
ax2 = axes_app1[1]
ax2.plot(common_weeks, reg_vals, marker="o", markersize=4, linewidth=2, color="#4CAF50", label="実績")
ax2.plot(APP_PLAN_WEEKS, APP_PLAN_REG, linestyle="--", linewidth=1.5, color="#4CAF50", alpha=0.4, label="計画")
ax2.scatter([APP_PLAN_WEEKS[-1]], [APP_PLAN_REG[-1]], marker="*", s=120, color="#4CAF50", alpha=0.6, zorder=5)
ax2.annotate(f"目標: {APP_TARGET_REG:,}", (APP_PLAN_WEEKS[-1], APP_PLAN_REG[-1]),
             textcoords="offset points", xytext=(-50, 10), ha="center", fontsize=9, color="#4CAF50", fontweight="bold")
ax2.set_ylabel("累計登録医師数", fontsize=11)
ax2.text(0.01, 0.95, "登録医師数", transform=ax2.transAxes,
         fontsize=10, fontweight="bold", va="top", color="#4CAF50")
ax2.legend(loc="center left", fontsize=8, framealpha=0.7)
for idx in [0, -1]:
    ax2.annotate(f"{reg_vals[idx]}", (common_weeks[idx], reg_vals[idx]),
                 textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8, color="#555")

# 3段目: 参考: メール登録数
_app_email_target = int(APP_TARGET_REG / LATEST_CONV_RATE) if LATEST_CONV_RATE > 0 else APP_TARGET_REG
ax2e = axes_app1[2]
ax2e.plot(common_weeks, email_reg_vals, marker="o", markersize=4, linewidth=2, color="#1976D2", label="実績")
# Email plan for appendix: scale from doctor plan
_app_email_plan_ms = email_plan_from_doctor_plan(APP_PLAN_MILESTONES, LATEST_CONV_RATE)
_app_email_plan_w, _app_email_plan_r = interpolate_email_plan_weekly(_app_email_plan_ms)
ax2e.plot(_app_email_plan_w, _app_email_plan_r, linestyle="--", linewidth=1.5, color="#1976D2", alpha=0.4, label=f"計画（確定転換率{LATEST_CONV_RATE*100:.0f}%）")
ax2e.scatter([_app_email_plan_w[-1]], [_app_email_plan_r[-1]], marker="*", s=120, color="#1976D2", alpha=0.6, zorder=5)
ax2e.annotate(f"必要数: {_app_email_target:,}", (_app_email_plan_w[-1], _app_email_plan_r[-1]),
              textcoords="offset points", xytext=(-60, 10), ha="center", fontsize=9, color="#1976D2", fontweight="bold")
ax2e.set_ylabel("累計メール登録数", fontsize=11)
ax2e.text(0.01, 0.95, "参考: メール登録数", transform=ax2e.transAxes,
          fontsize=10, fontweight="bold", va="top", color="#1976D2")
ax2e.legend(loc="center left", fontsize=8, framealpha=0.7)
for idx in [0, -1]:
    ax2e.annotate(f"{email_reg_vals[idx]}", (common_weeks[idx], email_reg_vals[idx]),
                  textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8, color="#555")

# 4段目: KPI2: MAU率
ax3a = axes_app1[3]
ax3a.plot(common_weeks, mau_rate_vals_cw, marker="o", markersize=4, linewidth=2, color="#E91E63", label="実績")
ax3a.plot(APP_HEAVY_PLAN_WEEKS, APP_HEAVY_PLAN_MAU_RATE, linestyle="--", linewidth=1.5, color="#E91E63", alpha=0.4, label="計画")
ax3a.scatter([APP_HEAVY_PLAN_WEEKS[-1]], [APP_TARGET_MAU_RATE], marker="*", s=120, color="#E91E63", alpha=0.6, zorder=5)
ax3a.annotate(f"目標: {APP_TARGET_MAU_RATE}%", (APP_HEAVY_PLAN_WEEKS[-1], APP_TARGET_MAU_RATE),
              textcoords="offset points", xytext=(-50, 10), ha="center", fontsize=9, color="#E91E63", fontweight="bold")
ax3a.set_ylabel("MAU率 (%)", fontsize=11)
ax3a.text(0.01, 0.95, "MAU率（MAU / 累計登録医師数）", transform=ax3a.transAxes,
         fontsize=10, fontweight="bold", va="top", color="#E91E63")
ax3a.legend(loc="center left", fontsize=8, framealpha=0.7)
for idx in [0, -1]:
    ax3a.annotate(f"{mau_rate_vals_cw[idx]:.1f}%", (common_weeks[idx], mau_rate_vals_cw[idx]),
                 textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8, color="#555")

# 5段目: KPI3: ヘビー化率
ax4 = axes_app1[4]
ax4.plot(common_weeks, heavy_rate_vals_cw, marker="o", markersize=4, linewidth=2, color="#FF9800", label="実績")
ax4.plot(APP_HEAVY_PLAN_WEEKS, APP_HEAVY_PLAN_HEAVY_RATE, linestyle="--", linewidth=1.5, color="#FF9800", alpha=0.4, label="計画")
ax4.scatter([APP_HEAVY_PLAN_WEEKS[-1]], [APP_TARGET_HEAVY_RATE], marker="*", s=120, color="#FF9800", alpha=0.6, zorder=5)
ax4.annotate(f"目標: {APP_TARGET_HEAVY_RATE}%", (APP_HEAVY_PLAN_WEEKS[-1], APP_TARGET_HEAVY_RATE),
             textcoords="offset points", xytext=(-50, 10), ha="center", fontsize=9, color="#FF9800", fontweight="bold")
ax4.set_ylabel("ヘビー化率 (%)", fontsize=11)
ax4.set_xlabel("週", fontsize=12)
ax4.text(0.01, 0.95, "ヘビー化率（ヘビーユーザー / MAU）", transform=ax4.transAxes,
         fontsize=10, fontweight="bold", va="top", color="#FF9800")
ax4.legend(loc="center left", fontsize=8, framealpha=0.7)
for idx in [0, -1]:
    ax4.annotate(f"{heavy_rate_vals_cw[idx]:.1f}%", (common_weeks[idx], heavy_rate_vals_cw[idx]),
                 textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8, color="#555")

ax4.set_xticks(ticks3)
ax4.set_xticklabels(labels3, rotation=45, ha="right")
plt.tight_layout()
fig_app1.savefig(OUTPUT_DIR / "chart_appendix1_kpi_trends.png", dpi=150, bbox_inches="tight")
print(f"[OK] Appendix Chart 1 -> output/chart_appendix1_kpi_trends.png", flush=True)
plt.close(fig_app1)

# ── Chart 12c: ヘビーユーザー / MAU 比率 推移 ──
fig, ax = plt.subplots(figsize=(10, 5))
_s15c_weeks = [w for w in exp_chart_weeks if w in s15_count]
_s15c_x = list(range(len(_s15c_weeks)))
_s15c_pct = [s15_pct_mau.get(w, 0) for w in _s15c_weeks]
_s15c_xlabels = [week_end_label(w) for w in _s15c_weeks]

ax.plot(_s15c_x, _s15c_pct, color="#9C27B0", marker="o", linewidth=2)
ax.fill_between(_s15c_x, _s15c_pct, alpha=0.15, color="#9C27B0")
for _xi, _v in zip(_s15c_x, _s15c_pct):
    ax.text(_xi, _v + 0.5, f"{_v:.1f}%", ha="center", fontsize=9, color="#9C27B0", fontweight="bold")
ax.set_ylabel("ヘビーユーザー / MAU (%)")
ax.set_title("4. ヘビーユーザー / MAU 比率", fontsize=14, fontweight="bold")
ax.set_xticks(_s15c_x)
ax.set_xticklabels(_s15c_xlabels, rotation=45, ha="right")
ax.set_ylim(0, max(_s15c_pct) * 1.3 if _s15c_pct else 30)
fig.tight_layout()
fig.savefig(OUTPUT_DIR / "chart12c_heavy_mau_ratio.png", dpi=150, bbox_inches="tight")
print("[OK] Chart 12c -> output/chart12c_heavy_mau_ratio.png", flush=True)
plt.close(fig)

# ── Chart 12d: ヘビーユーザー継続率（前週もヘビーだった割合） ──
fig, (ax_top, ax_bot) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
_s15d_weeks = [w for w in exp_chart_weeks if w in s15_continuity_count and _sorted_exp_weeks.index(w) > 0]
_s15d_x = list(range(len(_s15d_weeks)))
_s15d_cont = [s15_continuity_count.get(w, 0) for w in _s15d_weeks]
_s15d_new = [s15_count.get(w, 0) - s15_continuity_count.get(w, 0) for w in _s15d_weeks]
_s15d_pct = [s15_continuity_pct.get(w, 0) for w in _s15d_weeks]
_s15d_xlabels = [week_end_label(w) for w in _s15d_weeks]

# Top: stacked bar — 継続 vs 新規ヘビーユーザー
ax_top.bar(_s15d_x, _s15d_cont, width=0.7, color="#9C27B0", alpha=0.8, label="継続ヘビー（前週も）")
ax_top.bar(_s15d_x, _s15d_new, width=0.7, bottom=_s15d_cont, color="#CE93D8", alpha=0.8, label="新規ヘビー")
for _xi, _vc, _vn in zip(_s15d_x, _s15d_cont, _s15d_new):
    _total = _vc + _vn
    if _total > 0:
        ax_top.text(_xi, _total + 0.3, str(_total), ha="center", fontsize=9, fontweight="bold")
        if _vc > 0:
            ax_top.text(_xi, _vc / 2, str(_vc), ha="center", fontsize=9, color="white", fontweight="bold")
ax_top.set_ylabel("ヘビーユーザー数")
ax_top.set_title("3. ヘビーユーザー継続分析", fontsize=14, fontweight="bold")
ax_top.legend(loc="upper left", fontsize=9)

# Bottom: line — リテンション率（前週ヘビーのうち今週も残った割合）
ax_bot.plot(_s15d_x, _s15d_pct, color="#9C27B0", marker="o", linewidth=2)
ax_bot.fill_between(_s15d_x, _s15d_pct, alpha=0.15, color="#9C27B0")
for _xi, _v in zip(_s15d_x, _s15d_pct):
    ax_bot.text(_xi, _v + 1.5, f"{_v:.0f}%", ha="center", fontsize=9, color="#9C27B0", fontweight="bold")
ax_bot.set_ylabel("リテンション率 (%)")
ax_bot.set_ylim(0, 100)
ax_bot.axhline(y=50, color="gray", linestyle="--", alpha=0.4)
ax_bot.set_xticks(_s15d_x)
ax_bot.set_xticklabels(_s15d_xlabels, rotation=45, ha="right")

fig.tight_layout()
fig.savefig(OUTPUT_DIR / "chart12d_heavy_continuity.png", dpi=150, bbox_inches="tight")
print("[OK] Chart 12d -> output/chart12d_heavy_continuity.png", flush=True)
plt.close(fig)

# ── Chart 12e: 習慣化ユーザー (3/4週 1+) — 人数・利用日数・利用回数 ──
fig, axes = plt.subplots(3, 1, figsize=(12, 12), sharex=True)
_s17_weeks = [w for w in exp_chart_weeks if w in s17_count]
_s17_x = list(range(len(_s17_weeks)))
_s17_xlabels = [week_end_label(w) for w in _s17_weeks]
_s17_counts = [s17_count.get(w, 0) for w in _s17_weeks]
_s17_days = [s17_avg_days.get(w, 0) for w in _s17_weeks]
_s17_searches = [s17_avg_searches.get(w, 0) for w in _s17_weeks]

# Row 1: 人数
ax = axes[0]
ax.plot(_s17_x, _s17_counts, color="#4CAF50", marker="o", markersize=5, linewidth=2.5)
ax.fill_between(_s17_x, _s17_counts, alpha=0.12, color="#4CAF50")
for _xi, _v in zip(_s17_x, _s17_counts):
    ax.text(_xi, _v + 0.5, str(_v), ha="center", fontsize=9, color="#4CAF50", fontweight="bold")
ax.set_ylabel("人数", fontsize=12)
ax.set_title("5. 習慣化ユーザー — 人数・利用深度の推移", fontsize=14, fontweight="bold")
ax.set_ylim(bottom=0)

# Row 2: 利用日数/人
ax = axes[1]
ax.plot(_s17_x, _s17_days, color="#2196F3", marker="o", markersize=5, linewidth=2.5)
ax.fill_between(_s17_x, _s17_days, alpha=0.12, color="#2196F3")
for _xi, _v in zip(_s17_x, _s17_days):
    ax.text(_xi, _v + 0.2, f"{_v:.1f}", ha="center", fontsize=9, color="#2196F3", fontweight="bold")
ax.set_ylabel("利用日数/人 (28日間)", fontsize=12)
ax.set_ylim(bottom=0)

# Row 3: 利用回数/人
ax = axes[2]
ax.plot(_s17_x, _s17_searches, color="#FF9800", marker="o", markersize=5, linewidth=2.5)
ax.fill_between(_s17_x, _s17_searches, alpha=0.12, color="#FF9800")
for _xi, _v in zip(_s17_x, _s17_searches):
    ax.text(_xi, _v + 0.5, f"{_v:.1f}", ha="center", fontsize=9, color="#FF9800", fontweight="bold")
ax.set_ylabel("利用回数/人 (28日間)", fontsize=12)
ax.set_ylim(bottom=0)
ax.set_xticks(_s17_x)
ax.set_xticklabels(_s17_xlabels, rotation=45, ha="right")

fig.tight_layout()
fig.savefig(OUTPUT_DIR / "chart12e_habitual_user.png", dpi=150, bbox_inches="tight")
print("[OK] Chart 12e -> output/chart12e_habitual_user.png", flush=True)
plt.close(fig)

# ── Chart 11c: S16b Post-Activation Monthly Retention (activation month cohort) ──
fig, ax = plt.subplots(figsize=(10, 6))
s16_cohorts = sorted(s16_matrix.keys())
if s16_cohorts and s16_wavg:
    n_months_b = len(s16_wavg)
    n_rows_b = len(s16_cohorts) + 1
    hm_data_16b = []
    for cm in s16_cohorts:
        row = [s16_matrix[cm]['ret'][i] if i < len(s16_matrix[cm]['ret']) else float('nan') for i in range(n_months_b)]
        hm_data_16b.append(row)
    hm_data_16b.append([v if v is not None else float('nan') for v in s16_wavg])
    hm_array_16b = np.array(hm_data_16b)
    im_b = ax.imshow(hm_array_16b, aspect='auto', cmap='YlGn', vmin=0, vmax=100)
    ax.set_xticks(range(n_months_b))
    ax.set_xticklabels([f"M+{i}" for i in range(n_months_b)])
    ax.set_yticks(range(n_rows_b))
    ax.set_yticklabels([f"{cm} (n={s16_matrix[cm]['n']})" for cm in s16_cohorts] + ["加重平均"], fontsize=9)
    ax.set_title("10. アクティベーション後 月次リテンション", fontsize=13, fontweight="bold")
    for r in range(n_rows_b):
        for c in range(n_months_b):
            val = hm_array_16b[r, c]
            if not np.isnan(val):
                ax.text(c, r, f"{val:.0f}%", ha="center", va="center", fontsize=9, color="white" if val > 50 else "black")
    plt.colorbar(im_b, ax=ax, shrink=0.8, label="%")
fig.tight_layout()
fig.savefig(OUTPUT_DIR / "chart11c_s16_retention.png", dpi=150, bbox_inches="tight")
print("[OK] Chart 11d -> output/chart11c_s16_retention.png", flush=True)
plt.close(fig)


# ══════════════════════════════════════════════
# Chart 8: MAU / DAU Trends (individual charts)
# ══════════════════════════════════════════════
print("\n" + "=" * 50)
print("Chart 8: MAU / DAU Trends")
print("=" * 50, flush=True)

for _c8_name, _c8_vals, _c8_color, _c8_ylabel, _c8_title, _c8_fmt, _c8_fname in [
    ("MAU", mau_vals, "#9C27B0", "MAU（人）", "14. MAU（28日窓・D4+）", "d", "chart8a_mau.png"),
    ("MAU Rate", mau_rate_vals, "#E91E63", "MAU率（%）", "15. MAU率（MAU / 累計登録医師数）", ".1f", "chart8b_mau_rate.png"),
    ("Avg DAU", avg_dau_vals, "#00BCD4", "平均DAU（人）", "16. 平均DAU（日次D4+アクティブ医師数）", ".1f", "chart8c_avg_dau.png"),
    ("DAU Rate", dau_rate_vals, "#FF5722", "DAU率（%）", "17. DAU率（平均DAU / 累計登録医師数）", ".1f", "chart8d_dau_rate.png"),
]:
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(common_weeks, _c8_vals, marker="o", ms=5, lw=2, color=_c8_color)
    ax.set_ylabel(_c8_ylabel)
    ax.set_title(_c8_title, fontsize=14, fontweight="bold")
    if _c8_vals:
        _lbl = f"{_c8_vals[-1]:{_c8_fmt}}" + ("%" if "%" in _c8_ylabel else "")
        ax.annotate(_lbl, (common_weeks[-1], _c8_vals[-1]),
                    textcoords="offset points", xytext=(0, 10), ha="center", fontsize=10)
    # X-axis: week-end date only (28-day window metric)
    ax.set_xticks(common_weeks)
    ax.set_xticklabels([week_end_label(w) for w in common_weeks], rotation=45, ha="right")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / _c8_fname, dpi=150, bbox_inches="tight")
    plt.close(fig)

print("[OK] Chart 8a-d -> output/chart8[a-d]_*.png", flush=True)


# ══════════════════════════════════════════════
# Chart 9: KPI Decomposition Trend (3 subplots)
# ══════════════════════════════════════════════
print("\n" + "=" * 50)
print("Chart 9: KPI Decomposition Trend")
print("=" * 50, flush=True)

# X-axis: fit to actual data only
fd9 = common_weeks[0]
ld9 = common_weeks[-1]
mt9, ml9 = [], []
dt9 = next_month_start(fd9)
while dt9 <= ld9:
    if (dt9 - fd9).days > 10 and (ld9 - dt9).days > 10:
        mt9.append(dt9)
        ml9.append(dt9.strftime("%Y/%m"))
    dt9 = next_month_start(dt9)
ticks9 = [fd9] + mt9 + [ld9]
labels9 = [fd9.strftime("%Y/%m/%d")] + ml9 + [trailing_week_label(ld9)]

# Activation rate vals for common_weeks
act_rate_vals_cw = [act_rate_ts.get(w, 0) for w in common_weeks]

fig9, axes9 = plt.subplots(3, 1, figsize=(14, 12), sharex=True)

# Top: Registered Doctors (cumulative)
ax = axes9[0]
ax.plot(common_weeks, reg_vals, marker="o", markersize=4, linewidth=2, color="#4CAF50")
ax.set_ylabel("累計登録医師数", fontsize=11)
ax.set_title("Ref. WAU率の内部分解（アクティベーション率 × 週次継続率）", fontsize=14, fontweight="bold")
ax.text(0.01, 0.95, "\u767b\u9332\u533b\u5e2b\u6570", transform=ax.transAxes,
        fontsize=10, fontweight="bold", va="top", color="#4CAF50")
for idx in [0, -1]:
    ax.annotate(f"{reg_vals[idx]}", (common_weeks[idx], reg_vals[idx]),
                textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8, color="#555")
ax.set_xlim(fd9 - timedelta(days=3), ld9 + timedelta(days=7))

# Middle: Activation Rate
ax = axes9[1]
ax.plot(common_weeks, act_rate_vals_cw, marker="o", markersize=4, linewidth=2, color="#009688")
ax.set_ylabel("アクティベーション率（%）", fontsize=11)
ax.text(0.01, 0.95, "\u30a2\u30af\u30c6\u30a3\u30d9\u30fc\u30b7\u30e7\u30f3\u7387", transform=ax.transAxes,
        fontsize=10, fontweight="bold", va="top", color="#009688")
for idx in [0, -1]:
    ax.annotate(f"{act_rate_vals_cw[idx]:.1f}%", (common_weeks[idx], act_rate_vals_cw[idx]),
                textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8, color="#555")

# Bottom: Weekly Continuation Rate
ax = axes9[2]
ax.plot(common_weeks, return_rate_vals, marker="o", markersize=4, linewidth=2, color="#673AB7")
ax.set_ylabel("週次継続率（%）", fontsize=11)
ax.set_xlabel("週", fontsize=12)
ax.text(0.01, 0.95, "\u9031\u6b21\u7d99\u7d9a\u7387", transform=ax.transAxes,
        fontsize=10, fontweight="bold", va="top", color="#673AB7")
for idx in [0, -1]:
    ax.annotate(f"{return_rate_vals[idx]:.1f}%", (common_weeks[idx], return_rate_vals[idx]),
                textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8, color="#555")

axes9[2].set_xticks(ticks9)
axes9[2].set_xticklabels(labels9, rotation=45, ha="right")
plt.tight_layout()
fig9.savefig(OUTPUT_DIR / "chart9_kpi_decomposition.png", dpi=150, bbox_inches="tight")
print("[OK] Chart 9 -> output/chart9_kpi_decomposition.png", flush=True)
plt.close(fig9)


# ══════════════════════════════════════════════
# Chart 10: Registration Funnel — Rolling 4-week (raw)
# ══════════════════════════════════════════════
print("\n" + "=" * 50)
print("Chart 10: Registration Funnel (Rolling 4-week)")
print("=" * 50, flush=True)

# All weeks with any registration activity
all_reg_weeks = sorted(set(email_reg_by_week.keys()) | set(reg_by_week.keys()))

# Rolling 4-week aggregates (raw — includes recent unmatured cohorts)
r4w_weeks = []
r4w_email = []
r4w_doctor = []
r4w_rate = []

for i, w in enumerate(all_reg_weeks):
    start_i = max(0, i - 3)
    window = all_reg_weeks[start_i:i + 1]
    if len(window) < 4:
        continue
    e4 = sum(email_reg_by_week.get(ww, 0) for ww in window)
    d4 = sum(reg_by_week.get(ww, 0) for ww in window)
    rate = d4 / e4 * 100 if e4 > 0 else 0
    r4w_weeks.append(w)
    r4w_email.append(e4)
    r4w_doctor.append(d4)
    r4w_rate.append(rate)

# Filter to MILLE_START onwards for chart, trim incomplete final week
r4w_chart_idx = [i for i, w in enumerate(r4w_weeks) if w >= week_monday(MILLE_START)]
r4w_chart_idx = [i for i in r4w_chart_idx if (r4w_weeks[i] + timedelta(days=6)).date() <= DATA_END.date()]
r4w_chart_weeks = [r4w_weeks[i] for i in r4w_chart_idx]
r4w_chart_email = [r4w_email[i] for i in r4w_chart_idx]
r4w_chart_doctor = [r4w_doctor[i] for i in r4w_chart_idx]
r4w_chart_rate = [r4w_rate[i] for i in r4w_chart_idx]

print(f"  Rolling 4-week (recent 4 points):")
for w, e, d, r in zip(r4w_chart_weeks[-4:], r4w_chart_email[-4:], r4w_chart_doctor[-4:], r4w_chart_rate[-4:]):
    print(f"    {w.strftime('%Y-%m-%d')}: Email={e}, Doctor={d}, Rate={r:.0f}%")

fig10, ax10a = plt.subplots(figsize=(14, 6))

# Bar: rolling 4-week email registrations
ax10a.bar(r4w_chart_weeks, r4w_chart_email, width=5, color="#90CAF9", alpha=0.7, label="メール登録（4週）")
ax10a.bar(r4w_chart_weeks, r4w_chart_doctor, width=5, color="#4CAF50", alpha=0.85, label="医師登録（4週）")
ax10a.set_ylabel("登録数 / 4週", fontsize=11)
ax10a.set_xlabel("週", fontsize=12)

# Right axis: conversion rate
ax10b = ax10a.twinx()
ax10b.plot(r4w_chart_weeks, r4w_chart_rate, marker="o", markersize=5, linewidth=2.5,
           color="#E65100", label="転換率（4週）", zorder=5)
ax10b.set_ylabel("転換率（%）", fontsize=11, color="#E65100")
ax10b.tick_params(axis="y", labelcolor="#E65100")
ax10b.set_ylim(0, 105)

# Annotate latest rate
if r4w_chart_rate:
    ax10b.annotate(f"{r4w_chart_rate[-1]:.0f}%", (r4w_chart_weeks[-1], r4w_chart_rate[-1]),
                   textcoords="offset points", xytext=(0, 10), ha="center", fontsize=10,
                   fontweight="bold", color="#E65100")

ax10a.set_title("5. 登録ファネル: メール登録 × 医師登録転換率（4週ローリング）", fontsize=14, fontweight="bold")

# Combined legend
h1, l1 = ax10a.get_legend_handles_labels()
h2, l2 = ax10b.get_legend_handles_labels()
ax10a.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=9)

fig10.text(0.99, 0.01,
           "createdAt = email registration date. Doctor verification completion date is not separately recorded.",
           ha="right", va="bottom", fontsize=8, color="gray", style="italic")

# X-axis
fd10 = r4w_chart_weeks[0]
ld10 = r4w_chart_weeks[-1]
mt10, ml10 = [], []
dt10 = next_month_start(fd10)
while dt10 <= ld10:
    if (dt10 - fd10).days > 10 and (ld10 - dt10).days > 10:
        mt10.append(dt10)
        ml10.append(dt10.strftime("%Y/%m"))
    dt10 = next_month_start(dt10)
ticks10 = [fd10] + mt10 + [ld10]
labels10 = [fd10.strftime("%Y/%m/%d")] + ml10 + [trailing_week_label(ld10)]
ax10a.set_xticks(ticks10)
ax10a.set_xticklabels(labels10, rotation=45, ha="right")

plt.tight_layout()
plt.subplots_adjust(bottom=0.15)
fig10.savefig(OUTPUT_DIR / "chart10_reference_metrics.png", dpi=150, bbox_inches="tight")
print("[OK] Chart 10 -> output/chart10_reference_metrics.png", flush=True)
plt.close(fig10)


# ══════════════════════════════════════════════
# Chart 10b: Cumulative Email vs Doctor Registrations
# ══════════════════════════════════════════════
print("\n" + "=" * 50)
print("Chart 10b: Cumulative Email vs Doctor Registrations")
print("=" * 50, flush=True)

# Filter to MILLE_START onwards
c10b_idx = [i for i, w in enumerate(common_weeks) if w >= week_monday(MILLE_START)]
c10b_weeks = [common_weeks[i] for i in c10b_idx]
c10b_email = [email_reg_vals[i] for i in c10b_idx]
c10b_doctor = [reg_vals[i] for i in c10b_idx]

fig10b, ax10b_l = plt.subplots(figsize=(14, 6))

# Cumulative lines
ax10b_l.plot(c10b_weeks, c10b_email, marker="o", markersize=4, linewidth=2.5,
             color="#1976D2", label="メール登録（累計実績）")
ax10b_l.plot(c10b_weeks, c10b_doctor, marker="s", markersize=4, linewidth=2.5,
             color="#4CAF50", label="医師登録（累計実績）")
ax10b_l.fill_between(c10b_weeks, c10b_doctor, c10b_email, alpha=0.08, color="#90CAF9")

# Plan lines: email registration targets
_conv_label = f"(conv {LATEST_CONV_RATE*100:.0f}%)"
ax10b_l.plot(EMAIL_PLAN_WEEKS, EMAIL_PLAN_REG, linestyle="--", linewidth=2, color="#1976D2",
             alpha=0.5, label=f"Plan A {_conv_label}")
ax10b_l.plot(EMAIL_PLAN_B_WEEKS, EMAIL_PLAN_B_REG, linestyle=":", linewidth=2, color="#1976D2",
             alpha=0.4, label=f"Plan B {_conv_label}")

# Plan lines: doctor registration targets (same as Chart 3)
ax10b_l.plot(PLAN_WEEKS, PLAN_REG, linestyle="--", linewidth=2, color="#4CAF50",
             alpha=0.5, label="Doctor Plan A")
ax10b_l.plot(PLAN_B_WEEKS, PLAN_B_REG, linestyle=":", linewidth=2, color="#4CAF50",
             alpha=0.4, label="Doctor Plan B")

ax10b_l.set_ylabel("累計登録数", fontsize=11)
ax10b_l.set_xlabel("週", fontsize=12)

# Annotate latest values
if c10b_email:
    ax10b_l.annotate(f"{c10b_email[-1]:,}", (c10b_weeks[-1], c10b_email[-1]),
                     textcoords="offset points", xytext=(8, 5), ha="left", fontsize=10,
                     fontweight="bold", color="#1976D2")
    ax10b_l.annotate(f"{c10b_doctor[-1]:,}", (c10b_weeks[-1], c10b_doctor[-1]),
                     textcoords="offset points", xytext=(8, -10), ha="left", fontsize=10,
                     fontweight="bold", color="#388E3C")

# Annotate plan targets at endpoint
if EMAIL_PLAN_REG:
    ax10b_l.annotate(f"{EMAIL_TARGET_REG:,}", (EMAIL_PLAN_WEEKS[-1], EMAIL_PLAN_REG[-1]),
                     textcoords="offset points", xytext=(5, 5), ha="left", fontsize=9,
                     color="#1976D2", alpha=0.7)
if EMAIL_PLAN_B_REG:
    ax10b_l.annotate(f"{EMAIL_TARGET_REG_B:,}", (EMAIL_PLAN_B_WEEKS[-1], EMAIL_PLAN_B_REG[-1]),
                     textcoords="offset points", xytext=(5, -8), ha="left", fontsize=9,
                     color="#1976D2", alpha=0.6)

ax10b_l.set_title("(参考) 登録ファネル: メール登録 vs 医師登録（累計 + 計画線）", fontsize=14, fontweight="bold")
ax10b_l.legend(loc="upper left", fontsize=8, ncol=2)

# Note about conversion rate assumption
fig10b.text(0.99, 0.01,
            f"Plan lines assume matured cohort conv rate: {LATEST_CONV_RATE*100:.0f}% ({MATURATION_WEEKS}+ weeks old)",
            ha="right", va="bottom", fontsize=9, color="gray", style="italic")

# X-axis: extend to include plan end date
all_10b_dates = c10b_weeks + EMAIL_PLAN_WEEKS
fd10b = min(all_10b_dates)
ld10b = max(all_10b_dates)
mt10b, ml10b = [], []
dt10b = next_month_start(fd10b)
while dt10b <= ld10b:
    if (dt10b - fd10b).days > 10 and (ld10b - dt10b).days > 10:
        mt10b.append(dt10b)
        ml10b.append(dt10b.strftime("%Y/%m"))
    dt10b = next_month_start(dt10b)
ticks10b = [fd10b] + mt10b + [ld10b]
labels10b = [fd10b.strftime("%Y/%m/%d")] + ml10b + [ld10b.strftime("%Y/%m/%d")]
ax10b_l.set_xticks(ticks10b)
ax10b_l.set_xticklabels(labels10b, rotation=45, ha="right")

plt.tight_layout()
plt.subplots_adjust(bottom=0.15)
fig10b.savefig(OUTPUT_DIR / "chart10b_cumulative_registrations.png", dpi=150, bbox_inches="tight")
print(f"[OK] Chart 10b -> output/chart10b_cumulative_registrations.png", flush=True)
print(f"  Latest: Email={c10b_email[-1]}, Doctor={c10b_doctor[-1]}")
plt.close(fig10b)


# ══════════════════════════════════════════════
# Chart 14: Weekly Search Volume (total queries + unique users)
# ══════════════════════════════════════════════
print("\n" + "=" * 50)
print("Chart 14: Weekly Search Volume")
print("=" * 50, flush=True)

c14_weeks = [w for w in exp_chart_weeks if w in d4_total_queries_by_week]
c14_total_doc = [d4_total_queries_by_week[w] for w in c14_weeks]
c14_total_all = [d4_total_queries_by_week_all[w] for w in c14_weeks]
c14_users_doc = [d4_unique_users_by_week[w] for w in c14_weeks]
c14_users_all = [d4_unique_users_by_week_all[w] for w in c14_weeks]

fig14, ax14 = plt.subplots(figsize=(12, 6))
_c14_x = list(range(len(c14_weeks)))
bar_w = 0.35

# Stacked bars: doctor (green) + non-doctor delta (light blue)
c14_delta = [a - d for a, d in zip(c14_total_all, c14_total_doc)]
ax14.bar(_c14_x, c14_total_doc, width=bar_w * 2, label="検索回数（医師）", color="#4CAF50", alpha=0.85)
ax14.bar(_c14_x, c14_delta, width=bar_w * 2, bottom=c14_total_doc,
         label="検索回数（非医師）", color="#90CAF9", alpha=0.7)

ax14.set_ylabel("検索回数", fontsize=11)
ax14.set_xlabel("")

# Right axis: unique users
ax14r = ax14.twinx()
ax14r.plot(_c14_x, c14_users_all, marker="o", ms=5, lw=2, color="#1565C0",
           label="ユニークユーザー数（全）")
ax14r.plot(_c14_x, c14_users_doc, marker="s", ms=4, lw=2, color="#388E3C",
           linestyle="--", label="ユニークユーザー数（医師）")
ax14r.set_ylabel("ユニークユーザー数", fontsize=11)

# Annotate latest
if c14_total_all:
    ax14.annotate(f"{c14_total_all[-1]:,}", (_c14_x[-1], c14_total_all[-1]),
                  textcoords="offset points", xytext=(0, 8), ha="center",
                  fontsize=10, fontweight="bold", color="#333")
    ax14r.annotate(f"{c14_users_all[-1]}", (_c14_x[-1], c14_users_all[-1]),
                   textcoords="offset points", xytext=(8, 5), ha="left",
                   fontsize=9, color="#1565C0")
    ax14r.annotate(f"{c14_users_doc[-1]}", (_c14_x[-1], c14_users_doc[-1]),
                   textcoords="offset points", xytext=(8, -8), ha="left",
                   fontsize=9, color="#388E3C")

ax14.set_title("(参考) 週次検索ボリューム（D4+）", fontsize=14, fontweight="bold")

# Combined legend
lines1, labels1 = ax14.get_legend_handles_labels()
lines2, labels2 = ax14r.get_legend_handles_labels()
ax14.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=8)

set_weekly_xticks(ax14, c14_weeks, equal_spacing=True)
fig14.tight_layout()
fig14.savefig(OUTPUT_DIR / "chart14_weekly_search_volume.png", dpi=150, bbox_inches="tight")
print(f"[OK] Chart 14 -> output/chart14_weekly_search_volume.png", flush=True)
if c14_total_all:
    print(f"  Latest: Total(all)={c14_total_all[-1]}, Total(doc)={c14_total_doc[-1]}, "
          f"Users(all)={c14_users_all[-1]}, Users(doc)={c14_users_doc[-1]}")
plt.close(fig14)

# ══════════════════════════════════════════════
# Chart 14b: Weekly Search Volume — ALL (including D0-D3)
# ══════════════════════════════════════════════
print("\n" + "=" * 50)
print("Chart 14b: Weekly Search Volume (ALL, incl. D0-D3)")
print("=" * 50, flush=True)

c14b_weeks = [w for w in exp_chart_weeks if w in all_total_queries_by_week]
c14b_total_doc = [all_total_queries_by_week[w] for w in c14b_weeks]
c14b_total_all = [all_total_queries_by_week_all[w] for w in c14b_weeks]
c14b_d4_doc = [d4_total_queries_by_week[w] for w in c14b_weeks]
c14b_d4_all = [d4_total_queries_by_week_all[w] for w in c14b_weeks]
# D0-D3 portion
c14b_d03_doc = [t - d for t, d in zip(c14b_total_doc, c14b_d4_doc)]
c14b_d03_all = [t - d for t, d in zip(c14b_total_all, c14b_d4_all)]
c14b_users_all = [all_unique_users_by_week_all[w] for w in c14b_weeks]
c14b_users_doc = [all_unique_users_by_week[w] for w in c14b_weeks]

# Build extended X axis (actual + future weeks to target date)
# Use week_monday to align future weeks with plan milestones
c14b_future_weeks = []
_fw = week_monday(c14b_weeks[-1] + timedelta(days=7)) if c14b_weeks else week_monday(datetime.now())
while _fw <= target_monday:
    c14b_future_weeks.append(_fw)
    _fw += timedelta(days=7)
c14b_all_weeks = c14b_weeks + c14b_future_weeks
c14b_week_to_x = {w: i for i, w in enumerate(c14b_all_weeks)}

def draw_search_volume_chart(title, plan_weeks, plan_vals, target_val, color, filename, biz_vals=None):
    """Generate weekly search volume chart with target line.

    biz_vals (optional): 月〜金 8:00-18:00 JST（祝休日は考慮せず）の週次検索回数。
                        指定すると緑バーの内側に濃緑でオーバーレイ描画する。
    """
    fig, ax = plt.subplots(figsize=(14, 6))
    actual_x = [c14b_week_to_x[w] for w in c14b_weeks]

    # Bars (actual data only)
    ax.bar(actual_x, c14b_total_all, width=0.7, label="総検索回数", color="#4CAF50", alpha=0.85)
    # Business hours overlay
    if biz_vals is not None:
        ax.bar(actual_x, biz_vals, width=0.7,
               label="うち月〜金 8:00-18:00 JST（祝休日は考慮せず）",
               color="#1B5E20", alpha=0.95)
    ax.set_ylabel("検索回数", fontsize=11)

    # Target plan line (logistic curve, fixed milestones)
    _plan_x = [c14b_week_to_x[w] for w in plan_weeks if w in c14b_week_to_x]
    _plan_y = [v for w, v in zip(plan_weeks, plan_vals) if w in c14b_week_to_x]
    if _plan_x and _plan_y:
        ax.plot(_plan_x, _plan_y, linestyle="--", linewidth=2.5, color=color,
                alpha=0.7, label=f"目標: {target_val:,}/週")
        ax.annotate(f"{target_val:,}", (_plan_x[-1], _plan_y[-1]),
                    textcoords="offset points", xytext=(8, 5), ha="left",
                    fontsize=11, fontweight="bold", color=color)

    # Annotate latest actual
    if c14b_total_all:
        ax.annotate(f"{c14b_total_all[-1]:,}", (actual_x[-1], c14b_total_all[-1]),
                    textcoords="offset points", xytext=(0, 8), ha="center",
                    fontsize=10, fontweight="bold", color="#333")
    # Annotate latest biz hours
    if biz_vals is not None and biz_vals:
        ax.annotate(f"{biz_vals[-1]:,}", (actual_x[-1], biz_vals[-1]),
                    textcoords="offset points", xytext=(0, -14), ha="center",
                    fontsize=9, fontweight="bold", color="#fff")

    # Right axis: unique users
    ax_r = ax.twinx()
    ax_r.plot(actual_x, c14b_users_all, marker="o", ms=4, lw=2, color="#1565C0",
              label="ユニークユーザー数")
    ax_r.set_ylabel("ユニークユーザー数", fontsize=11)
    if c14b_users_all:
        ax_r.annotate(f"{c14b_users_all[-1]}", (actual_x[-1], c14b_users_all[-1]),
                      textcoords="offset points", xytext=(8, 5), ha="left",
                      fontsize=9, color="#1565C0")

    ax.set_title(title, fontsize=14, fontweight="bold")

    # X-axis labels
    _labels = [trailing_week_label(w) for w in c14b_all_weeks]
    ax.set_xticks(range(len(c14b_all_weeks)))
    ax.set_xticklabels(_labels, rotation=45, ha="right", fontsize=7)

    # Combined legend
    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax_r.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=9)

    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / filename, dpi=150, bbox_inches="tight")
    print(f"[OK] {filename}", flush=True)
    plt.close(fig)

# biz_vals: 月〜金 8:00-18:00 JST 週次検索回数（c14b_weeks に整列）
c14b_biz_vals = [biz_count_by_week_all[w] for w in c14b_weeks]

# 社内向けチャート (target: 2750)
draw_search_volume_chart(
    "1. 週次検索ボリューム（全検索）",
    SEARCH_PLAN_WEEKS, SEARCH_PLAN_VALS, TARGET_WEEKLY_SEARCH, "#E91E63",
    "chart14b_weekly_search_volume_all.png",
    biz_vals=c14b_biz_vals,
)
# 投資家向けチャート (target: 1555)
draw_search_volume_chart(
    "1. 週次検索ボリューム（全検索）",
    APP_SEARCH_PLAN_WEEKS, APP_SEARCH_PLAN_VALS, APP_TARGET_WEEKLY_SEARCH, "#FF9800",
    "chart14b_weekly_search_volume_app.png",
    biz_vals=c14b_biz_vals,
)
if c14b_total_all:
    print(f"  Latest: Total(all)={c14b_total_all[-1]} (D4+={c14b_d4_all[-1]}, D0-3={c14b_d03_all[-1]}), "
          f"Total(doc)={c14b_total_doc[-1]} (D4+={c14b_d4_doc[-1]}, D0-3={c14b_d03_doc[-1]})")


# ══════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════
print("\n" + "=" * 50)
print("SUMMARY")
print("=" * 50)
print(f"  Email registrations: {email_registered_total}")
print(f"  Registered doctors: {len(user_reg)}")
print(f"  Email->Doctor conv: {email_doctor_conv_rate:.0f}%")
print(f"  Activity events: {len(activities)}")
print(f"  WAU (latest week): {wau_vals[-1]}")
print(f"  Cumulative reg (latest): {reg_vals[-1]}")
print(f"  WAU rate (latest): {rate_vals[-1]:.1f}% (WAU / registered)")
print(f"  MAU (latest): {mau_vals[-1]}")
print(f"  MAU rate (latest): {mau_rate_vals[-1]:.1f}%")
print(f"  Avg DAU (latest): {avg_dau_vals[-1]:.1f}")
print(f"  DAU rate (latest): {dau_rate_vals[-1]:.1f}%")

# KPI Decomposition
_latest_cum_act = cum_act.get(common_weeks[-1], 0)
_latest_act_rate = act_rate_vals_cw[-1] if act_rate_vals_cw else 0
_latest_return_rate = return_rate_vals[-1] if return_rate_vals else 0
_decomp_check = reg_vals[-1] * _latest_act_rate / 100 * _latest_return_rate / 100
print(f"\n  --- KGI/KPI Decomposition (Heavy Users) ---")
print(f"  KGI: Heavy Users = {s15_count.get(common_weeks[-1], 0)}")
print(f"  KPI1: Registered Doctors = {reg_vals[-1]}")
print(f"  KPI2: MAU Rate = {mau_rate_vals[-1]:.1f}%")
print(f"  KPI3: Heavy Rate = {s15_pct_mau.get(common_weeks[-1], 0)}%")
print(f"  Check: {reg_vals[-1]} x {_latest_act_rate:.1f}% x {_latest_return_rate:.1f}% = {_decomp_check:.0f} (WAU={wau_vals[-1]})")

# Recent 4 weeks
print(f"\n  Recent 4 weeks:")
for w, wau, reg, rate, mau, mau_r, dau, dau_r in zip(
    common_weeks[-4:], wau_vals[-4:], reg_vals[-4:], rate_vals[-4:],
    mau_vals[-4:], mau_rate_vals[-4:], avg_dau_vals[-4:], dau_rate_vals[-4:]):
    print(f"    {w.strftime('%Y-%m-%d')}: WAU={wau}, MAU={mau}, Avg DAU={dau:.1f}, Reg={reg}, WAU Rate={rate:.1f}%, MAU Rate={mau_r:.1f}%, DAU Rate={dau_r:.1f}%")

# Supplementary Metrics Summary Table
if exp_chart_weeks:
    lw = exp_chart_weeks[-1]
    print(f"\n" + "=" * 50)
    print("SUPPLEMENTARY METRICS SUMMARY")
    print("=" * 50)
    print(f"\n{'Metric':<40} {'Latest':>10} {'Note'}")
    print("-" * 70)
    print(f"{'S1: Activation Rate':<40} {act_rate_ts.get(lw, 0):>9.1f}% {'cumulative'}")
    if lw in s2_cont_vals:
        _tot = s2_new_vals[lw] + s2_cont_vals[lw] + s2_react_vals[lw]
        _cpct = s2_cont_vals[lw] / _tot * 100 if _tot > 0 else 0
        print(f"{'S2: Continuing WAU share':<40} {_cpct:>9.1f}% {'of weekly WAU'}")
    print(f"{'S3: Dormancy Rate':<40} {s3_rate.get(lw, 0):>9.1f}% {'4-week window'}")
    print(f"{'S4: Query Depth':<40} {s4_depth.get(lw, 0):>9.1f}  {'queries/user/week'}")
    print(f"{'S5: WAU/MAU Ratio':<40} {s5_ratio.get(lw, 0):>9.1f}%")
    print(f"{'S6: W4 Retention':<40} {'see chart':>10} {'by cohort'}")
    print(f"{'S7: Retention Heatmap':<40} {'see chart':>10} {''}")
    print(f"{'S8: Peak usage day':<40} {'see chart':>10} {''}")
    print(f"{'S9: DAU/MAU':<40} {s9_ratio.get(lw, 0):>9.1f}% {'on-demand product'}")
    print(f"{'S10: Queries/Active User':<40} {s10_q_per_user.get(lw, 0):>9.1f}  {'4-week rolling'}")
    print(f"{'S11: Power User Count':<40} {s11_power_count.get(lw, 0):>9d}  {'weekly avg >= 5'}")
    print(f"{'S12: Top10% Concentration':<40} {s12_top10_share.get(lw, 0):>9.1f}% {'query share'}")


# ══════════════════════════════════════════════
# Generate dashboard.html
# ══════════════════════════════════════════════
print("\nGenerating dashboard.html...", flush=True)

# Latest complete week for display
disp_week = common_weeks[-1]
disp_week_label = trailing_week_label(disp_week)

# Recent 4 weeks table rows
recent_rows = ""
for w, wau, reg, rate, mau, mau_r, dau, dau_r in zip(
    common_weeks[-4:], wau_vals[-4:], reg_vals[-4:], rate_vals[-4:],
    mau_vals[-4:], mau_rate_vals[-4:], avg_dau_vals[-4:], dau_rate_vals[-4:]):
    _wlabel = TRAILING_LABEL if (HAS_TRAILING and w == TRAILING_MONDAY) else w.strftime("%Y-%m-%d")
    _style = ' style="background:#fff3e0;font-weight:bold"' if (HAS_TRAILING and w == TRAILING_MONDAY) else ''
    recent_rows += f'    <tr{_style}><td>{_wlabel}</td><td>{wau}</td><td>{mau}</td><td>{dau:.1f}</td><td>{reg}</td><td>{rate:.1f}%</td><td>{mau_r:.1f}%</td><td>{dau_r:.1f}%</td></tr>\n'

# Retention table rows
ret_table_header = "<th>コホート</th><th>n</th><th>D0-D3</th><th>D4-D10</th>"
for p in range(2, hm_max_p + 1):
    ret_table_header += f"<th>{period_label(p)}</th>"
ret_table_rows = ""
for label in sorted(ret_sizes.keys()):
    row = f'    <tr><td>{label}</td><td>{ret_sizes[label]}</td>'
    for p in range(0, hm_max_p + 1):
        if p <= max_obs.get(label, -1) and p in ret_data[label]:
            val = len(ret_data[label][p]) / ret_sizes[label] * 100
            row += f"<td>{val:.1f}</td>"
        else:
            row += "<td></td>"
    row += "</tr>\n"
    ret_table_rows += row

# Supplementary metrics for summary table
supp_rows = ""
if exp_chart_weeks:
    lw = exp_chart_weeks[-1]
    metrics = [
        ("4. アクティベーション率", f"{act_rate_ts.get(lw, 0):.1f}%", "分子=D4+を1回以上使った医師数 / 分母=累計登録医師数"),
        ("5. 継続WAU比率", f"{s2_cont_vals.get(lw,0) / max(s2_new_vals.get(lw,0)+s2_cont_vals.get(lw,0)+s2_react_vals.get(lw,0), 1) * 100:.1f}%", "分子=前週もアクティブだったWAU / 分母=当週WAU合計"),
        ("6. WAU/MAU比率", f"{s5_ratio.get(lw, 0):.1f}%", "分子=WAU / 分母=MAU（28日窓）"),
        ("MAU", f"{mau_by_week.get(lw, 0)}", "過去28日間にD4+検索を1回以上行った医師数"),
        ("MAU率", f"{mau_rate_by_week.get(lw, 0):.1f}%", "分子=MAU / 分母=累計登録医師数"),
        ("平均DAU", f"{avg_dau_by_week.get(lw, 0):.1f}", "週内の日別D4+検索者数の平均"),
        ("DAU率", f"{dau_rate_by_week.get(lw, 0):.1f}%", "分子=平均DAU / 分母=累計登録医師数"),
        ("7. DAU/MAU", f"{s9_ratio.get(lw, 0):.1f}%", "分子=平均DAU / 分母=MAU。日次利用の頻度を示す"),
        ("13. 定着指数", f"{s11_power_count.get(lw, 0)}", "4週間の週平均検索数が5回以上の医師数"),
        ("11. 継続ユーザー週次検索回数", f"{s13_ret_avg.get(lw, 0):.1f} ({s13_ret_avg.get(lw,0)/max(s13_all_avg.get(lw,1),0.1):.1f}x)", "継続ユーザーの週次平均検索数（カッコ内は全WAU比）"),
        ("12. ヘビーユーザー数", f"{s15_count.get(lw, 0)} ({s15_pct_mau.get(lw, 0):.1f}%)", "28日間に10回以上検索した医師数（カッコ内はMAU中の比率）"),
        ("12. HU平均検索回数/日数", f"{s15_avg_searches.get(lw, 0)}回 / {s15_avg_active_days.get(lw, 0)}日", "ヘビーユーザー1人あたり平均検索回数・アクティブ日数（28日間）"),
        ("10. アクティベーション後M1-M3リテンション", f"{sum(v for v in s16_wavg[1:4] if v is not None)/max(len([v for v in s16_wavg[1:4] if v is not None]),1):.1f}%" if s16_wavg and len(s16_wavg) > 1 else "-", "D4+初検索後30-90日のリテンション率（加重平均、アクティベーション月コホート）"),
    ]
    for name, val, note in metrics:
        supp_rows += f'    <tr><td>{name}</td><td>{val}</td><td class="def">{note}</td></tr>\n'

# Reference metrics table rows — rolling 4-week (last 4 points)
ref_table_r4w = ""
for w, e, d, r in zip(r4w_chart_weeks[-4:], r4w_chart_email[-4:], r4w_chart_doctor[-4:], r4w_chart_rate[-4:]):
    ref_table_r4w += f'    <tr><td>{w.strftime("%Y-%m-%d")}</td><td>{e}</td><td>{d}</td><td>{r:.0f}%</td></tr>\n'

# Reference metrics table rows — weekly detail (last 4 weeks)
ref_table_weekly = ""
for w in common_weeks[-4:]:
    e_reg = email_reg_by_week.get(w, 0)
    d_reg = reg_by_week.get(w, 0)
    conv = d_reg / e_reg * 100 if e_reg > 0 else 0
    ref_table_weekly += f'    <tr><td>{w.strftime("%Y-%m-%d")}</td><td>{e_reg}</td><td>{d_reg}</td><td>{conv:.0f}%</td></tr>\n'

# KPI decomposition values for HTML
_html_cum_act = cum_act.get(common_weeks[-1], 0)
_html_act_rate = act_rate_vals_cw[-1] if act_rate_vals_cw else 0
_html_return_rate = return_rate_vals[-1] if return_rate_vals else 0

html = f'''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>Traction Dashboard — {DATA_END.strftime("%Y-%m-%d")}</title>
<style>
  body {{ font-family: 'Segoe UI', sans-serif; background: #f5f5f5; margin: 0; padding: 20px; max-width: 1100px; margin: 0 auto; }}
  h1 {{ text-align: center; color: #333; margin-bottom: 5px; }}
  .subtitle {{ text-align: center; color: #888; font-size: 14px; margin-bottom: 30px; }}
  .summary {{ display: flex; justify-content: center; gap: 30px; margin-bottom: 30px; flex-wrap: wrap; }}
  .card {{ background: #fff; border-radius: 10px; padding: 20px 30px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); text-align: center; min-width: 160px; }}
  .card .value {{ font-size: 36px; font-weight: bold; }}
  .card .label {{ font-size: 13px; color: #888; margin-top: 4px; }}
  .card.blue .value {{ color: #2196F3; }}
  .card.green .value {{ color: #4CAF50; }}
  .card.orange .value {{ color: #FF9800; }}
  .card.purple .value {{ color: #9C27B0; }}
  .card.pink .value {{ color: #E91E63; }}
  .card.cyan .value {{ color: #00BCD4; }}
  .card.red .value {{ color: #FF5722; }}
  .chart-section {{ background: #fff; border-radius: 10px; padding: 20px; margin-bottom: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
  .chart-section h2 {{ margin: 0 0 4px 0; font-size: 16px; color: #555; }}
  .chart-section img {{ width: 100%; max-width: 960px; display: block; margin: 0 auto; }}
  .def {{ font-size: 11px; color: #999; font-weight: normal; line-height: 1.4; }}
  .chart-section .def {{ margin: 0 0 12px 0; }}
  table {{ margin: 0 auto; border-collapse: collapse; font-size: 14px; }}
  th, td {{ padding: 6px 14px; border-bottom: 1px solid #eee; text-align: right; }}
  th {{ color: #888; font-weight: normal; }}
  td:first-child, th:first-child {{ text-align: left; }}
  td.def {{ text-align: left; font-size: 11px; color: #999; }}
  .kpi-banner {{ background: linear-gradient(135deg, #1a237e, #283593); color: #fff; border-radius: 12px; padding: 20px 30px; margin-bottom: 24px; text-align: center; box-shadow: 0 4px 12px rgba(0,0,0,0.15); }}
  .kpi-banner .formula {{ font-size: 15px; opacity: 0.85; margin-bottom: 8px; }}
  .kpi-banner .numbers {{ font-size: 22px; font-weight: bold; letter-spacing: 1px; }}
  .kpi-banner .numbers .kgi-val {{ font-size: 28px; color: #90CAF9; }}
  .footer {{ text-align: center; color: #bbb; font-size: 12px; margin-top: 30px; }}
</style>
</head>
<body>

<h1>Cubec トラクションダッシュボード</h1>
<p class="subtitle">データ最終日: {DATA_END.strftime("%Y-%m-%d")} | 最終完全週: {disp_week_label}</p>

<div class="chart-section" style="background:#f8f9ff;border-left:4px solid #1a237e;margin-bottom:24px;">
  <h2 style="color:#1a237e;">用語定義</h2>
  <p class="def" style="font-size:12px;color:#555;line-height:1.8;">
    <b>D4+</b>: 登録から4日以上経過した状態。初期探索期間（登録直後の試用）を除外し、真の利用意思を持つユーザーのみを計測対象とするためのフィルタ。<br>
    <b>WAU</b>（Weekly Active Users）: D4+で当該週に1回以上検索した医師数。<br>
    <b>MAU</b>（Monthly Active Users）: 過去28日間にD4+検索を1回以上行った医師数。<br>
    <b>DAU</b>（Daily Active Users）: 当日にD4+検索を1回以上行った医師数。「平均DAU」は週内7日間の平均。<br>
    <b>WAU率</b>: WAU / 累計登録医師数。登録した医師のうち、週次でアクティブな割合。<br>
    <b>アクティベーション</b>: 医師がD4+で初めて検索を行うこと。アクティベーション率 = 累計アクティベート済み医師数 / 累計登録医師数。<br>
    <b>コホート</b>: 登録月またはアクティベーション月でグループ化したユーザー群。チャートごとに基準が異なる場合は個別に記載。<br>
    <b>リテンション</b>: ある期間に再びアクティブだったユーザーの割合。分母はコホート全員。<br>
    <b>ヘビーユーザー</b>: 28日間に10回以上検索した医師。習慣的利用の指標。<br>
  </p>
</div>

<div class="chart-section">
  <h2>1. 週次検索ボリューム（全検索）</h2>
  <p class="def">【定義】棒グラフ: 当該週の全ユーザーの総検索回数（緑）、内側の濃緑は月〜金 8:00-18:00 JST（祝休日は考慮せず、単純に曜日と時刻のみで判定）の検索回数。折れ線（右軸）: ユニークユーザー数。点線: 登録医師{TARGET_REG:,}人計画に連動した検索ボリューム目標（{TARGET_WEEKLY_SEARCH:,}回/週）</p>
  <img src="chart14b_weekly_search_volume_all.png" alt="Weekly Search Volume">
</div>

<div class="kpi-banner">
  <div class="formula">ヘビーユーザー = 登録医師数 × MAU率 × ヘビー化率</div>
  <div class="numbers"><span class="kgi-val">{s15_count.get(exp_chart_weeks[-1], 0) if exp_chart_weeks else 0}</span> = {reg_vals[-1]} × {mau_rate_vals[-1]:.1f}% × {s15_pct_mau.get(exp_chart_weeks[-1] if exp_chart_weeks else common_weeks[-1], 0)}%</div>
  <div style="font-size:13px;opacity:0.7;margin-top:8px;">目標（6月末）: <span style="font-weight:bold;">{TARGET_HEAVY}</span> = {TARGET_REG:,} × {TARGET_MAU_RATE}% × {TARGET_HEAVY_RATE}%</div>
</div>

<h2 style="color:#1a237e;border-bottom:2px solid #f5773f;padding-bottom:6px;margin:32px 0 16px;">A. ヘビーユーザー（定着指標）</h2>

<div class="chart-section">
  <h2>A1. ヘビーユーザー分解（実績 vs 計画）</h2>
  <p class="def">1段目: ヘビーユーザー数。2段目: 登録医師数。3段目: メール登録数（参考）。4段目: MAU率。5段目: ヘビー化率。点線 = 計画線<br>目標（6月末）: ヘビー{TARGET_HEAVY} = 登録{TARGET_REG:,} × MAU率{TARGET_MAU_RATE}% × ヘビー化率{TARGET_HEAVY_RATE}%</p>
  <img src="chart3_kpi_trends.png" alt="Heavy User Trends">
</div>

<div class="chart-section">
  <h2>A2. ヘビーユーザー詳細（人数・検索回数・アクティブ日数）</h2>
  <p class="def">【定義】上段: 過去28日間にD4+検索を10回以上行った医師数。中段: 同ユーザーの1人当たり平均検索回数。下段: 同ユーザーの1人当たり平均アクティブ日数（28日中何日使ったか）</p>
  <img src="chart11b_s15_habitual.png" alt="S15">
</div>

<div class="chart-section">
  <h2>A3. ヘビーユーザー継続分析</h2>
  <p class="def">【定義】上段: 今週のヘビーユーザーのうち、前週もヘビーだった人（継続）と今週新たにヘビーになった人（新規）の内訳。<br>下段: リテンション率＝前週もヘビーだった人 / <b>前週のヘビーユーザー総数</b>。前週のヘビーユーザーが翌週も残る割合を測る</p>
  <img src="chart12d_heavy_continuity.png" alt="Heavy User Continuity">
</div>

<div class="chart-section">
  <h2>A4. ヘビーユーザー / MAU 比率</h2>
  <p class="def">【定義】MAU（28日間D4+アクティブ医師）のうちヘビーユーザー（10回以上検索）が占める割合。<br>MAUの「質」を測る指標。MAU減少局面でも比率上昇なら、コアユーザーの深化が進んでいることを示す</p>
  <img src="chart12c_heavy_mau_ratio.png" alt="Heavy/MAU Ratio">
</div>

<div class="chart-section">
  <h2>A5. 習慣化ユーザー（人数・利用深度）</h2>
  <p class="def">【定義】直近28日間のうち3週以上で1回以上検索した医師（D4+）。バースト型利用を除外し、週をまたいで継続的に使っているユーザーを測定する。<br>上段: 人数推移（灰色破線はヘビーユーザー参考値）。中段: 1人当たり平均アクティブ日数（28日中）。下段: 1人当たり平均検索回数（28日間）</p>
  <img src="chart12e_habitual_user.png" alt="Habitual Users">
</div>

<h2 style="color:#1a237e;border-bottom:2px solid #f5773f;padding-bottom:6px;margin:32px 0 16px;">B. 登録・成長</h2>

<div class="chart-section">
  <h2>B1. 登録ファネル: メール登録 × 医師登録転換率（4週ローリング）</h2>
  <p class="def">直近4週のメール登録数と医師登録数、およびその転換率。<br>【注意】直近コホートはまだ医師認証に至っていない可能性があるため、転換率は構造的に低めに出る。確定転換率は{MATURED_CONV_RATE*100:.0f}%（登録{MATURATION_WEEKS}週以上前のコホートで算出）。<br>【定義】メール登録 = メールアドレスでアカウント作成した全ユーザー。医師登録 = 医師免許確認を完了した登録者。転換率 = 医師登録数 / メール登録数</p>
  <img src="chart10_reference_metrics.png" alt="Registration Funnel">
</div>

<div class="chart-section">
  <h2>B2. コホート別WAU推移 — 医師認証済み（ミルフィーユチャート）</h2>
  <p class="def">登録月別に色分けした週間アクティブユーザー数の積み上げ面グラフ。<br>【定義】WAU = 当該週にD4+検索を1回以上行った医師認証済みユーザー数。ヘビーユーザーの母集団となる医師ユーザーの利用動向を可視化</p>
  <img src="chart1_millefeuille.png" alt="Millefeuille">
</div>

<div class="chart-section">
  <h2>B3. コホート別WAU推移 — 全メール登録者（ミルフィーユチャート）</h2>
  <p class="def">医師登録の有無を問わず、全メール登録者が対象。B2との差分が医師未登録のアクティブユーザー</p>
  <img src="chart1b_millefeuille_all.png" alt="Millefeuille All">
</div>

<div class="chart-section">
  <h2>B4. WAU構成（新規 / 継続 / 復帰）</h2>
  <p class="def">WAUの内訳を積み上げ棒グラフで表示。<br>【定義】新規=当週初めてD4+検索した医師。継続=前週もアクティブだった医師。復帰=2週以上ぶりに戻った医師。<br>継続比率が高いほど安定したエンゲージメントを示す</p>
  <img src="chart4b_s2_composition.png" alt="S2">
</div>

<h2 style="color:#1a237e;border-bottom:2px solid #f5773f;padding-bottom:6px;margin:32px 0 16px;">C. リテンション</h2>

<div class="chart-section">
  <h2>C1. コホート別リテンションカーブ（登録月基準）</h2>
  <p class="def">各期間に1回以上検索した医師の割合。<br>【定義】分子=当該期間に検索した医師数 / 分母=コホート全登録医師数。<br>D0-D3=登録0〜3日、D4-D10=登録4〜10日、M1=登録11〜40日、M2=登録41〜70日（以降30日刻み）。コホート=登録月。期間が未完了のコホートはその期間を非表示</p>
  <img src="chart2_retention_curve.png" alt="Retention Curve">
</div>

<div class="chart-section">
  <h2>C2. コホート別リテンション ヒートマップ（登録月基準）</h2>
  <p class="def">登録月コホート × リテンション期間のマトリクス。<br>【定義】各セルの値 = 当該期間に1回以上検索した医師数 / コホート全登録医師数（%）。<br>期間: D0-D3=登録0〜3日、D4-D10=4〜10日、M1=11〜40日（以降30日刻み）。コホート全員の期間が未完了の列は非表示</p>
  <img src="chart6_retention_heatmap.png" alt="Retention Heatmap">
</div>

<div class="chart-section">
  <h2>C3. アクティベーション後 月次リテンション</h2>
  <p class="def">各ユーザーのD4+初検索日（=アクティベーション日）を起点とした30日ローリング窓でのリテンション。<br>【定義】M+0=アクティベーション日（100%）。M+1=アクティベーション後1〜30日目に1回以上検索した割合。M+2=31〜60日目。以降30日刻み。<br>分子=当該窓で検索した医師数 / 分母=コホート全員。コホート=アクティベーション月（初めてD4+検索した月）。コホート全員の期間が未完了の列は非表示</p>
  <img src="chart11c_s16_retention.png" alt="S16">
</div>

<h2 style="color:#1a237e;border-bottom:2px solid #f5773f;padding-bottom:6px;margin:32px 0 16px;">D. エンゲージメント深度</h2>

<div class="chart-section">
  <h2>D1. WAU/MAU比率</h2>
  <p class="def">【定義】分子=WAU / 分母=MAU（28日窓）。ユーザーがどれだけ頻繁に戻ってくるかを示す</p>
  <img src="chart5a_s5_stickiness.png" alt="S5">
</div>

<div class="chart-section">
  <h2>D2. DAU/MAU比率</h2>
  <p class="def">【定義】分子=平均DAU（週内の日別D4+検索者数の平均） / 分母=MAU（28日窓）。<br>ユーザーが月内で平均何割の日にアクティブかを示す。on-demand型プロダクトでは10〜20%が一般的</p>
  <img src="chart5b_s9_dau_mau.png" alt="S9">
</div>

<div class="chart-section">
  <h2>D3. MAU（28日窓・D4+）</h2>
  <p class="def">【定義】過去28日間にD4+検索を1回以上行った医師数。WAUより長い観察窓で利用者の裾野を捉える</p>
  <img src="chart8a_mau.png" alt="MAU">
</div>

<div class="chart-section">
  <h2>D4. MAU率（MAU / 累計登録医師数）</h2>
  <p class="def">【定義】分子=MAU / 分母=累計登録医師数。月次で見た利用率</p>
  <img src="chart8b_mau_rate.png" alt="MAU Rate">
</div>

<div class="chart-section">
  <h2>D5. 平均DAU（日次アクティブ医師数・D4+）</h2>
  <p class="def">【定義】当該週の各日にD4+検索を行った医師数の7日間平均。日次の利用規模を示す</p>
  <img src="chart8c_avg_dau.png" alt="Avg DAU">
</div>

<div class="chart-section">
  <h2>D6. DAU率（平均DAU / 累計登録医師数）</h2>
  <p class="def">【定義】分子=平均DAU / 分母=累計登録医師数。日次ベースでの利用率</p>
  <img src="chart8d_dau_rate.png" alt="DAU Rate">
</div>

<hr style="margin:40px 0;border:none;border-top:3px solid #1a237e;">
<h1 style="color:#1a237e;">Appendix</h1>

<div class="chart-section">
  <h2>App-1. 週次検索ボリューム（全検索・投資家向け目標）</h2>
  <p class="def">【定義】棒グラフ: 当該週の全ユーザーの総検索回数（緑）、内側の濃緑は月〜金 8:00-18:00 JST（祝休日は考慮せず、単純に曜日と時刻のみで判定）の検索回数。折れ線（右軸）: ユニークユーザー数。点線: 登録医師2,827人計画に連動した検索ボリューム目標（{APP_TARGET_WEEKLY_SEARCH:,}回/週）</p>
  <img src="chart14b_weekly_search_volume_app.png" alt="Weekly Search Volume App">
</div>

<div class="kpi-banner" style="background: linear-gradient(135deg, #4a148c, #6a1b9a);">
  <div class="formula">ヘビーユーザー = 登録医師数 × MAU率 × ヘビー化率</div>
  <div class="numbers"><span class="kgi-val">{s15_count.get(exp_chart_weeks[-1], 0) if exp_chart_weeks else 0}</span> = {reg_vals[-1]} × {mau_rate_vals[-1]:.1f}% × {s15_pct_mau.get(exp_chart_weeks[-1] if exp_chart_weeks else common_weeks[-1], 0)}%</div>
  <div style="font-size:13px;opacity:0.7;margin-top:8px;">目標（6月末）: <span style="font-weight:bold;">{APP_TARGET_HEAVY}</span> = {APP_TARGET_REG:,} × {APP_TARGET_MAU_RATE}% × {APP_TARGET_HEAVY_RATE}%</div>
</div>

<div class="chart-section">
  <h2>App-2. ヘビーユーザー分解（実績 vs 計画）</h2>
  <p class="def">1段目: ヘビーユーザー数。2段目: 登録医師数。3段目: メール登録数（参考）。4段目: MAU率。5段目: ヘビー化率。点線 = 計画線<br>目標（6月末）: ヘビー{APP_TARGET_HEAVY} = 登録{APP_TARGET_REG:,} × MAU率{APP_TARGET_MAU_RATE}% × ヘビー化率{APP_TARGET_HEAVY_RATE}%</p>
  <img src="chart_appendix1_kpi_trends.png" alt="Heavy User Trends">
</div>

<div class="footer">Cubec トラクションダッシュボード | 生成日: {DATA_END.strftime("%Y-%m-%d")}</div>

</body>
</html>
'''

with open(OUTPUT_DIR / "dashboard.html", "w", encoding="utf-8") as f:
    f.write(html)
print("[OK] dashboard.html -> output/dashboard.html", flush=True)

# ══════════════════════════════════════════════
# Export weekly time-series CSV (investor-facing download)
# ══════════════════════════════════════════════
print("\nGenerating traction_weekly.csv...", flush=True)
_c14b_search_total = {w: v for w, v in zip(c14b_weeks, c14b_total_all)}
_c14b_search_users = {w: v for w, v in zip(c14b_weeks, c14b_users_all)}
_csv_rows = [
    ("週開始日(月)", "週終了日(日)", "累計登録医師数", "WAU", "WAU率(%)",
     "MAU", "MAU率(%)", "平均DAU", "DAU率(%)",
     "ヘビーユーザー数", "ヘビー化率(%)", "週次検索ボリューム", "週次ユニークユーザー数"),
    # Row 2: 定義（ダッシュボードのチャート/用語定義と同一文言）
    ("週の月曜日",
     "週の日曜日",
     "医師認証済み（doctorInfo=1）または招待コード経由（みなし医師）の累計登録数",
     "D4+で当該週に1回以上検索した医師数",
     "WAU / 累計登録医師数。登録した医師のうち、週次でアクティブな割合",
     "過去28日間にD4+検索を1回以上行った医師数",
     "分子=MAU / 分母=累計登録医師数。月次で見た利用率",
     "週内の日別D4+検索者数の平均",
     "分子=平均DAU / 分母=累計登録医師数。日次ベースでの利用率",
     "28日間に10回以上検索した医師。習慣的利用の指標",
     "ヘビーユーザー / MAU",
     "当該週の全ユーザーの総検索回数",
     "当該週の全ユーザーのユニークユーザー数"),
]
for i, w in enumerate(common_weeks):
    sun = w + timedelta(days=6)
    _csv_rows.append((
        w.strftime("%Y-%m-%d"),
        sun.strftime("%Y-%m-%d"),
        reg_vals[i],
        wau_vals[i],
        f"{rate_vals[i]:.2f}",
        mau_vals[i],
        f"{mau_rate_vals[i]:.2f}",
        f"{avg_dau_vals[i]:.2f}",
        f"{dau_rate_vals[i]:.2f}",
        s15_count.get(w, 0),
        f"{s15_pct_mau.get(w, 0):.2f}",
        _c14b_search_total.get(w, ""),
        _c14b_search_users.get(w, ""),
    ))
import csv as _csv
with open(OUTPUT_DIR / "traction_weekly.csv", "w", encoding="utf-8-sig", newline="") as _f:
    _csv.writer(_f).writerows(_csv_rows)
print(f"[OK] traction_weekly.csv -> output/traction_weekly.csv ({len(_csv_rows)-1} rows)", flush=True)

# ══════════════════════════════════════════════
# Generate dashboard_overview.html (investor-facing)
# Same charts but: #1 = App1 (ヘビー100人目標), KPI banner = App targets, no Appendix
# ══════════════════════════════════════════════
print("\nGenerating dashboard_overview.html...", flush=True)

html_overview = f'''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>Traction Dashboard — {DATA_END.strftime("%Y-%m-%d")}</title>
<style>
  body {{ font-family: 'Segoe UI', sans-serif; background: #f5f5f5; margin: 0; padding: 20px; max-width: 1100px; margin: 0 auto; }}
  h1 {{ text-align: center; color: #333; margin-bottom: 5px; }}
  .subtitle {{ text-align: center; color: #888; font-size: 14px; margin-bottom: 30px; }}
  .summary {{ display: flex; justify-content: center; gap: 30px; margin-bottom: 30px; flex-wrap: wrap; }}
  .card {{ background: #fff; border-radius: 10px; padding: 20px 30px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); text-align: center; min-width: 160px; }}
  .card .value {{ font-size: 36px; font-weight: bold; }}
  .card .label {{ font-size: 13px; color: #888; margin-top: 4px; }}
  .card.blue .value {{ color: #2196F3; }}
  .card.green .value {{ color: #4CAF50; }}
  .card.orange .value {{ color: #FF9800; }}
  .card.purple .value {{ color: #9C27B0; }}
  .card.pink .value {{ color: #E91E63; }}
  .card.cyan .value {{ color: #00BCD4; }}
  .card.red .value {{ color: #FF5722; }}
  .chart-section {{ background: #fff; border-radius: 10px; padding: 20px; margin-bottom: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
  .chart-section h2 {{ margin: 0 0 4px 0; font-size: 16px; color: #555; }}
  .chart-section img {{ width: 100%; max-width: 960px; display: block; margin: 0 auto; }}
  .def {{ font-size: 11px; color: #999; font-weight: normal; line-height: 1.4; }}
  .chart-section .def {{ margin: 0 0 12px 0; }}
  table {{ margin: 0 auto; border-collapse: collapse; font-size: 14px; }}
  th, td {{ padding: 6px 14px; border-bottom: 1px solid #eee; text-align: right; }}
  th {{ color: #888; font-weight: normal; }}
  td:first-child, th:first-child {{ text-align: left; }}
  td.def {{ text-align: left; font-size: 11px; color: #999; }}
  .kpi-banner {{ background: linear-gradient(135deg, #4a148c, #6a1b9a); color: #fff; border-radius: 12px; padding: 20px 30px; margin-bottom: 24px; text-align: center; box-shadow: 0 4px 12px rgba(0,0,0,0.15); }}
  .kpi-banner .formula {{ font-size: 15px; opacity: 0.85; margin-bottom: 8px; }}
  .kpi-banner .numbers {{ font-size: 22px; font-weight: bold; letter-spacing: 1px; }}
  .kpi-banner .numbers .kgi-val {{ font-size: 28px; color: #90CAF9; }}
  .footer {{ text-align: center; color: #bbb; font-size: 12px; margin-top: 30px; }}
</style>
</head>
<body>

<h1>Cubec トラクションダッシュボード</h1>
<p class="subtitle">データ最終日: {DATA_END.strftime("%Y-%m-%d")} | 最終完全週: {disp_week_label}</p>

<div style="text-align:center;margin-bottom:24px;">
  <a href="traction_weekly.csv" download
     style="display:inline-block;background:#083d7c;color:#fff;text-decoration:none;padding:10px 22px;border-radius:6px;font-size:14px;font-weight:bold;box-shadow:0 2px 6px rgba(0,0,0,0.1);">
    📥 週次データ（CSV）をダウンロード
  </a>
  <div style="color:#888;font-size:11px;margin-top:6px;">登録医師数 / WAU / MAU / ヘビーユーザー / 週次検索ボリューム 等（週次時系列）</div>
</div>

<div class="chart-section" style="background:#f8f9ff;border-left:4px solid #1a237e;margin-bottom:24px;">
  <h2 style="color:#1a237e;">用語定義</h2>
  <p class="def" style="font-size:12px;color:#555;line-height:1.8;">
    <b>D4+</b>: 登録から4日以上経過した状態。初期探索期間（登録直後の試用）を除外し、真の利用意思を持つユーザーのみを計測対象とするためのフィルタ。<br>
    <b>WAU</b>（Weekly Active Users）: D4+で当該週に1回以上検索した医師数。<br>
    <b>MAU</b>（Monthly Active Users）: 過去28日間にD4+検索を1回以上行った医師数。<br>
    <b>DAU</b>（Daily Active Users）: 当日にD4+検索を1回以上行った医師数。「平均DAU」は週内7日間の平均。<br>
    <b>WAU率</b>: WAU / 累計登録医師数。登録した医師のうち、週次でアクティブな割合。<br>
    <b>アクティベーション</b>: 医師がD4+で初めて検索を行うこと。アクティベーション率 = 累計アクティベート済み医師数 / 累計登録医師数。<br>
    <b>コホート</b>: 登録月またはアクティベーション月でグループ化したユーザー群。チャートごとに基準が異なる場合は個別に記載。<br>
    <b>リテンション</b>: ある期間に再びアクティブだったユーザーの割合。分母はコホート全員。<br>
    <b>ヘビーユーザー</b>: 28日間に10回以上検索した医師。習慣的利用の指標。<br>
  </p>
</div>

<div class="chart-section">
  <h2>1. 週次検索ボリューム（全検索）</h2>
  <p class="def">【定義】棒グラフ: 当該週の全ユーザーの総検索回数（緑）、内側の濃緑は月〜金 8:00-18:00 JST（祝休日は考慮せず、単純に曜日と時刻のみで判定）の検索回数。折れ線（右軸）: ユニークユーザー数。点線: 登録医師2,827人計画に連動した検索ボリューム目標（{APP_TARGET_WEEKLY_SEARCH:,}回/週）</p>
  <img src="chart14b_weekly_search_volume_app.png" alt="Weekly Search Volume">
</div>

<div class="kpi-banner">
  <div class="formula">ヘビーユーザー = 登録医師数 × MAU率 × ヘビー化率</div>
  <div class="numbers"><span class="kgi-val">{s15_count.get(exp_chart_weeks[-1], 0) if exp_chart_weeks else 0}</span> = {reg_vals[-1]} × {mau_rate_vals[-1]:.1f}% × {s15_pct_mau.get(exp_chart_weeks[-1] if exp_chart_weeks else common_weeks[-1], 0)}%</div>
  <div style="font-size:13px;opacity:0.7;margin-top:8px;">目標（6月末）: <span style="font-weight:bold;">{APP_TARGET_HEAVY}</span> = {APP_TARGET_REG:,} × {APP_TARGET_MAU_RATE}% × {APP_TARGET_HEAVY_RATE}%</div>
</div>

<h2 style="color:#1a237e;border-bottom:2px solid #f5773f;padding-bottom:6px;margin:32px 0 16px;">A. ヘビーユーザー（定着指標）</h2>

<div class="chart-section">
  <h2>A1. ヘビーユーザー分解（実績 vs 計画）</h2>
  <p class="def">1段目: ヘビーユーザー数。2段目: 登録医師数。3段目: メール登録数（参考）。4段目: MAU率。5段目: ヘビー化率。点線 = 計画線<br>目標（6月末）: ヘビー{APP_TARGET_HEAVY} = 登録{APP_TARGET_REG:,} × MAU率{APP_TARGET_MAU_RATE}% × ヘビー化率{APP_TARGET_HEAVY_RATE}%</p>
  <img src="chart_appendix1_kpi_trends.png" alt="Heavy User Trends">
</div>

<div class="chart-section">
  <h2>A2. ヘビーユーザー詳細（人数・検索回数・アクティブ日数）</h2>
  <p class="def">【定義】上段: 過去28日間にD4+検索を10回以上行った医師数。中段: 同ユーザーの1人当たり平均検索回数。下段: 同ユーザーの1人当たり平均アクティブ日数（28日中何日使ったか）</p>
  <img src="chart11b_s15_habitual.png" alt="S15">
</div>

<div class="chart-section">
  <h2>A3. ヘビーユーザー継続分析</h2>
  <p class="def">【定義】上段: 今週のヘビーユーザーのうち、前週もヘビーだった人（継続）と今週新たにヘビーになった人（新規）の内訳。<br>下段: リテンション率＝前週もヘビーだった人 / <b>前週のヘビーユーザー総数</b>。前週のヘビーユーザーが翌週も残る割合を測る</p>
  <img src="chart12d_heavy_continuity.png" alt="Heavy User Continuity">
</div>

<div class="chart-section">
  <h2>A4. ヘビーユーザー / MAU 比率</h2>
  <p class="def">【定義】MAU（28日間D4+アクティブ医師）のうちヘビーユーザー（10回以上検索）が占める割合。<br>MAUの「質」を測る指標。MAU減少局面でも比率上昇なら、コアユーザーの深化が進んでいることを示す</p>
  <img src="chart12c_heavy_mau_ratio.png" alt="Heavy/MAU Ratio">
</div>

<div class="chart-section">
  <h2>A5. 習慣化ユーザー（人数・利用深度）</h2>
  <p class="def">【定義】直近28日間のうち3週以上で1回以上検索した医師（D4+）。バースト型利用を除外し、週をまたいで継続的に使っているユーザーを測定する。<br>上段: 人数推移（灰色破線はヘビーユーザー参考値）。中段: 1人当たり平均アクティブ日数（28日中）。下段: 1人当たり平均検索回数（28日間）</p>
  <img src="chart12e_habitual_user.png" alt="Habitual Users">
</div>

<h2 style="color:#1a237e;border-bottom:2px solid #f5773f;padding-bottom:6px;margin:32px 0 16px;">B. 登録・成長</h2>

<div class="chart-section">
  <h2>B1. 登録ファネル: メール登録 × 医師登録転換率（4週ローリング）</h2>
  <p class="def">直近4週のメール登録数と医師登録数、およびその転換率。<br>【注意】直近コホートはまだ医師認証に至っていない可能性があるため、転換率は構造的に低めに出る。確定転換率は{MATURED_CONV_RATE*100:.0f}%（登録{MATURATION_WEEKS}週以上前のコホートで算出）。<br>【定義】メール登録 = メールアドレスでアカウント作成した全ユーザー。医師登録 = 医師免許確認を完了した登録者。転換率 = 医師登録数 / メール登録数</p>
  <img src="chart10_reference_metrics.png" alt="Registration Funnel">
</div>

<div class="chart-section">
  <h2>B2. コホート別WAU推移 — 医師認証済み（ミルフィーユチャート）</h2>
  <p class="def">登録月別に色分けした週間アクティブユーザー数の積み上げ面グラフ。<br>【定義】WAU = 当該週にD4+検索を1回以上行った医師認証済みユーザー数。ヘビーユーザーの母集団となる医師ユーザーの利用動向を可視化</p>
  <img src="chart1_millefeuille.png" alt="Millefeuille">
</div>

<div class="chart-section">
  <h2>B3. コホート別WAU推移 — 全メール登録者（ミルフィーユチャート）</h2>
  <p class="def">医師登録の有無を問わず、全メール登録者が対象。B2との差分が医師未登録のアクティブユーザー</p>
  <img src="chart1b_millefeuille_all.png" alt="Millefeuille All">
</div>

<div class="chart-section">
  <h2>B4. WAU構成（新規 / 継続 / 復帰）</h2>
  <p class="def">WAUの内訳を積み上げ棒グラフで表示。<br>【定義】新規=当週初めてD4+検索した医師。継続=前週もアクティブだった医師。復帰=2週以上ぶりに戻った医師。<br>継続比率が高いほど安定したエンゲージメントを示す</p>
  <img src="chart4b_s2_composition.png" alt="S2">
</div>

<h2 style="color:#1a237e;border-bottom:2px solid #f5773f;padding-bottom:6px;margin:32px 0 16px;">C. リテンション</h2>

<div class="chart-section">
  <h2>C1. コホート別リテンションカーブ（登録月基準）</h2>
  <p class="def">各期間に1回以上検索した医師の割合。<br>【定義】分子=当該期間に検索した医師数 / 分母=コホート全登録医師数。<br>D0-D3=登録0〜3日、D4-D10=登録4〜10日、M1=登録11〜40日、M2=登録41〜70日（以降30日刻み）。コホート=登録月。期間が未完了のコホートはその期間を非表示</p>
  <img src="chart2_retention_curve.png" alt="Retention Curve">
</div>

<div class="chart-section">
  <h2>C2. コホート別リテンション ヒートマップ（登録月基準）</h2>
  <p class="def">登録月コホート × リテンション期間のマトリクス。<br>【定義】各セルの値 = 当該期間に1回以上検索した医師数 / コホート全登録医師数（%）。<br>期間: D0-D3=登録0〜3日、D4-D10=4〜10日、M1=11〜40日（以降30日刻み）。コホート全員の期間が未完了の列は非表示</p>
  <img src="chart6_retention_heatmap.png" alt="Retention Heatmap">
</div>

<div class="chart-section">
  <h2>C3. アクティベーション後 月次リテンション</h2>
  <p class="def">各ユーザーのD4+初検索日（=アクティベーション日）を起点とした30日ローリング窓でのリテンション。<br>【定義】M+0=アクティベーション日（100%）。M+1=アクティベーション後1〜30日目に1回以上検索した割合。M+2=31〜60日目。以降30日刻み。<br>分子=当該窓で検索した医師数 / 分母=コホート全員。コホート=アクティベーション月（初めてD4+検索した月）。コホート全員の期間が未完了の列は非表示</p>
  <img src="chart11c_s16_retention.png" alt="S16">
</div>

<h2 style="color:#1a237e;border-bottom:2px solid #f5773f;padding-bottom:6px;margin:32px 0 16px;">D. エンゲージメント深度</h2>

<div class="chart-section">
  <h2>D1. WAU/MAU比率</h2>
  <p class="def">【定義】分子=WAU / 分母=MAU（28日窓）。ユーザーがどれだけ頻繁に戻ってくるかを示す</p>
  <img src="chart5a_s5_stickiness.png" alt="S5">
</div>

<div class="chart-section">
  <h2>D2. DAU/MAU比率</h2>
  <p class="def">【定義】分子=平均DAU（週内の日別D4+検索者数の平均） / 分母=MAU（28日窓）。<br>ユーザーが月内で平均何割の日にアクティブかを示す。on-demand型プロダクトでは10〜20%が一般的</p>
  <img src="chart5b_s9_dau_mau.png" alt="S9">
</div>

<div class="chart-section">
  <h2>D3. MAU（28日窓・D4+）</h2>
  <p class="def">【定義】過去28日間にD4+検索を1回以上行った医師数。WAUより長い観察窓で利用者の裾野を捉える</p>
  <img src="chart8a_mau.png" alt="MAU">
</div>

<div class="chart-section">
  <h2>D4. MAU率（MAU / 累計登録医師数）</h2>
  <p class="def">【定義】分子=MAU / 分母=累計登録医師数。月次で見た利用率</p>
  <img src="chart8b_mau_rate.png" alt="MAU Rate">
</div>

<div class="chart-section">
  <h2>D5. 平均DAU（日次アクティブ医師数・D4+）</h2>
  <p class="def">【定義】当該週の各日にD4+検索を行った医師数の7日間平均。日次の利用規模を示す</p>
  <img src="chart8c_avg_dau.png" alt="Avg DAU">
</div>

<div class="chart-section">
  <h2>D6. DAU率（平均DAU / 累計登録医師数）</h2>
  <p class="def">【定義】分子=平均DAU / 分母=累計登録医師数。日次ベースでの利用率</p>
  <img src="chart8d_dau_rate.png" alt="DAU Rate">
</div>

<div class="footer">Cubec トラクションダッシュボード | 生成日: {DATA_END.strftime("%Y-%m-%d")}</div>

</body>
</html>
'''

with open(OUTPUT_DIR / "dashboard_overview.html", "w", encoding="utf-8") as f:
    f.write(html_overview)
print("[OK] dashboard_overview.html -> output/dashboard_overview.html", flush=True)

print(f"\n  Output:")
print(f"    chart1_millefeuille.png")
print(f"    chart2_retention_curve.png")
print(f"    chart3_kpi_trends.png")
print(f"    chart3b_kpi_actual.png")
print(f"    chart3c_kpi_planB.png")
print(f"    chart4_lifecycle.png")
print(f"    chart5_engagement.png")
print(f"    chart6_retention_heatmap.png")
print(f"    chart7_enthusiasm.png")
print(f"    chart8_mau_dau.png")
print(f"    chart9_kpi_decomposition.png")
print(f"    chart10_reference_metrics.png")
print(f"    chart11_exploration.png")
print(f"    dashboard.html")
print(f"    dashboard_overview.html")
print("\nDone!", flush=True)
