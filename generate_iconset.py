from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

MASTER_SIZE = 1024
FONT_PATH = r"C:\Windows\Fonts\arialbd.ttf"

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

out_dir = Path("mac-build") / "AppIcon.iconset"
out_dir.mkdir(parents=True, exist_ok=True)

master = Image.new("RGB", (MASTER_SIZE, MASTER_SIZE), "#0b0b0d")
draw = ImageDraw.Draw(master)
text = "M↓"
font = ImageFont.truetype(FONT_PATH, int(MASTER_SIZE * 0.42))
bbox = draw.textbbox((0, 0), text, font=font)
w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
draw.text(((MASTER_SIZE - w) / 2 - bbox[0], (MASTER_SIZE - h) / 2 - bbox[1]), text, font=font, fill="#22c55e")

for size, name in ICONSET_SIZES:
    resized = master.resize((size, size), Image.LANCZOS)
    resized.save(out_dir / name)

print(f"saved {len(ICONSET_SIZES)} icons into {out_dir}")
