"""Regenerate the macOS/Windows app-icon assets from the committed raster master.

The master (`mac-build/icon_master_1024.png`) is a 1024x1024 rasterization of the
brand vector `brand/td_Icon.svg` (dark #1B1A17 field, light «t», accent «d»).
We keep a committed PNG master because the build hosts don't ship an SVG
rasterizer; regenerate the master from the SVG only when the brand mark changes.
"""
from pathlib import Path
from PIL import Image

MASTER = Path("mac-build") / "icon_master_1024.png"

ICONSET_SIZES = [
    (16, "icon_16x16.png"),
    (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"),
    (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"),
    (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"),
    (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"),
    (1024, "icon_512x512@2x.png"),
]

ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

master = Image.open(MASTER).convert("RGB")

out_dir = Path("mac-build") / "AppIcon.iconset"
out_dir.mkdir(parents=True, exist_ok=True)
for size, name in ICONSET_SIZES:
    master.resize((size, size), Image.LANCZOS).save(out_dir / name)

master.save("icon.ico", sizes=ICO_SIZES)

print(f"saved {len(ICONSET_SIZES)} iconset PNGs into {out_dir} and icon.ico")
