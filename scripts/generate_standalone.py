"""Convert dashboard HTML files with external PNG references into self-contained HTML with base64-embedded images."""
import re
import base64
import os

IMG_DIR = "dashboard/output"

TARGETS = [
    ("dashboard/output/dashboard.html", "index.html"),
    ("dashboard/output/dashboard_overview.html", "overview.html"),
]


def replace_img(match):
    src = match.group(1)
    img_path = os.path.join(IMG_DIR, src)
    if os.path.exists(img_path):
        with open(img_path, "rb") as img:
            b64 = base64.b64encode(img.read()).decode()
        return f'src="data:image/png;base64,{b64}"'
    return match.group(0)


for html_path, out_path in TARGETS:
    if not os.path.exists(html_path):
        print(f"Skipping {html_path} (not found)")
        continue
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()
    html_standalone = re.sub(r'src="([^"]+\.png)"', replace_img, html)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_standalone)
    print(f"{out_path}: {os.path.getsize(out_path) / 1024 / 1024:.1f} MB")

# Copy weekly CSV to repo root so overview.html's download link works
import shutil
_csv_src = os.path.join(IMG_DIR, "traction_weekly.csv")
if os.path.exists(_csv_src):
    shutil.copyfile(_csv_src, "traction_weekly.csv")
    print(f"traction_weekly.csv: {os.path.getsize('traction_weekly.csv') / 1024:.1f} KB")
else:
    print(f"Skipping traction_weekly.csv (not found at {_csv_src})")
