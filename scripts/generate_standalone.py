"""Convert dashboard HTML files with external PNG references into self-contained HTML with base64-embedded images."""
import re
import base64
import os

# (html_path, out_path, img_dir)
# 参考版（allsearch=全検索 / login=ログインベース）は 2026-07-24 追加。
TARGETS = [
    ("dashboard/output/dashboard.html", "index.html", "dashboard/output"),
    ("dashboard/output/dashboard_overview.html", "overview.html", "dashboard/output"),
    ("dashboard/output_allsearch/dashboard.html", "index_allsearch.html", "dashboard/output_allsearch"),
    ("dashboard/output_allsearch/dashboard_overview.html", "overview_allsearch.html", "dashboard/output_allsearch"),
    ("dashboard/output_login/dashboard.html", "index_login.html", "dashboard/output_login"),
    ("dashboard/output_login/dashboard_overview.html", "overview_login.html", "dashboard/output_login"),
]


def make_replacer(img_dir):
    def replace_img(match):
        src = match.group(1)
        img_path = os.path.join(img_dir, src)
        if os.path.exists(img_path):
            with open(img_path, "rb") as img:
                b64 = base64.b64encode(img.read()).decode()
            return f'src="data:image/png;base64,{b64}"'
        return match.group(0)
    return replace_img


for html_path, out_path, img_dir in TARGETS:
    if not os.path.exists(html_path):
        print(f"Skipping {html_path} (not found)")
        continue
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()
    html_standalone = re.sub(r'src="([^"]+\.png)"', make_replacer(img_dir), html)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_standalone)
    print(f"{out_path}: {os.path.getsize(out_path) / 1024 / 1024:.1f} MB")

# Copy weekly CSVs to repo root so each overview page's download link works
import shutil
CSV_COPIES = [
    ("dashboard/output/traction_weekly.csv", "traction_weekly.csv"),
    ("dashboard/output_allsearch/traction_weekly.csv", "traction_weekly_allsearch.csv"),
    ("dashboard/output_login/traction_weekly.csv", "traction_weekly_login.csv"),
]
for _csv_src, _csv_dst in CSV_COPIES:
    if os.path.exists(_csv_src):
        shutil.copyfile(_csv_src, _csv_dst)
        print(f"{_csv_dst}: {os.path.getsize(_csv_dst) / 1024:.1f} KB")
    else:
        print(f"Skipping {_csv_dst} (not found at {_csv_src})")
