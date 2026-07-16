"""Generate the PWA icons (served from /static) from the committed raster master.

Run at container build (see docker-server/Dockerfile). The master
`icon_master_1024.png` is COPYed next to this script; it's a 1024x1024
rasterization of the brand vector `brand/td_Icon.svg`. Resizing a committed PNG
keeps the build reproducible without needing an SVG rasterizer in the image.
"""
import os
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
# In the container the master is copied next to this script (cwd == /app);
# locally it lives under mac-build/. Try both.
CANDIDATES = [
    os.path.join(HERE, "icon_master_1024.png"),
    os.path.join(HERE, "..", "mac-build", "icon_master_1024.png"),
]
master_path = next((p for p in CANDIDATES if os.path.isfile(p)), CANDIDATES[0])

PWA_ICONS = [("static/apple-touch-icon.png", 180), ("static/icon-192.png", 192), ("static/icon-512.png", 512)]

master = Image.open(master_path).convert("RGB")
for path, size in PWA_ICONS:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    master.resize((size, size), Image.LANCZOS).save(path)

print(f"generated {len(PWA_ICONS)} PWA icons from {master_path}")
