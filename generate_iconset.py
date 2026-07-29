"""Regenerate the macOS/Windows app-icon assets from the committed raster master.

The master (`mac-build/icon_master_1024.png`) is a 1024x1024 rasterization of the
brand vector `brand/td_Icon.svg` (dark #1B1A17 field, light «t», accent «d»).
We keep a committed PNG master because the build hosts don't ship an SVG
rasterizer; regenerate the master from the SVG only when the brand mark changes.
"""
from pathlib import Path
from PIL import Image, ImageDraw

MASTER = Path("mac-build") / "icon_master_1024.png"
MACOS_ICON_CANVAS = 1024
MACOS_ARTWORK_SIZE = 824
MACOS_ARTWORK_INSET = (MACOS_ICON_CANVAS - MACOS_ARTWORK_SIZE) // 2
MACOS_CORNER_RADIUS = 185
MACOS_COMPOSED_ICON = Path("mac-build") / "AppIcon_composed_1024.png"

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

master = Image.open(MASTER)


def compose_macos_icon(master: Image.Image) -> Image.Image:
    """Fit the full-bleed master to the macOS icon template with alpha."""
    artwork = master.convert("RGBA").resize(
        (MACOS_ARTWORK_SIZE, MACOS_ARTWORK_SIZE), Image.LANCZOS
    )
    mask = Image.new("L", artwork.size)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, MACOS_ARTWORK_SIZE - 1, MACOS_ARTWORK_SIZE - 1),
        radius=MACOS_CORNER_RADIUS,
        fill=255,
    )
    artwork.putalpha(mask)

    canvas = Image.new("RGBA", (MACOS_ICON_CANVAS, MACOS_ICON_CANVAS))
    canvas.alpha_composite(artwork, (MACOS_ARTWORK_INSET, MACOS_ARTWORK_INSET))
    return canvas


macos_icon = compose_macos_icon(master)
macos_icon.save(MACOS_COMPOSED_ICON)

out_dir = Path("mac-build") / "AppIcon.iconset"
out_dir.mkdir(parents=True, exist_ok=True)
for size, name in ICONSET_SIZES:
    macos_icon.resize((size, size), Image.LANCZOS).save(out_dir / name)

master.save("icon.ico", sizes=ICO_SIZES)

print(
    f"saved {MACOS_COMPOSED_ICON}, {len(ICONSET_SIZES)} iconset PNGs into "
    f"{out_dir}, and icon.ico"
)
