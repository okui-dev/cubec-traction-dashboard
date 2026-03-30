"""Convert dashboard.html with external PNG references into a self-contained HTML with base64-embedded images."""
import re
import base64
import os

HTML_PATH = "dashboard/output/dashboard.html"
OUT_PATH = "index.html"
IMG_DIR = "dashboard/output"


def replace_img(match):
    src = match.group(1)
    img_path = os.path.join(IMG_DIR, src)
    if os.path.exists(img_path):
        with open(img_path, "rb") as img:
            b64 = base64.b64encode(img.read()).decode()
        return f'src="data:image/png;base64,{b64}"'
    return match.group(0)


with open(HTML_PATH, "r", encoding="utf-8") as f:
    html = f.read()

html_standalone = re.sub(r'src="([^"]+\.png)"', replace_img, html)

with open(OUT_PATH, "w", encoding="utf-8") as f:
    f.write(html_standalone)

print(f"Standalone HTML: {os.path.getsize(OUT_PATH) / 1024 / 1024:.1f} MB")
