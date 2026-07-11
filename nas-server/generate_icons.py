from PIL import Image, ImageDraw, ImageFont

def make_icon(size, path):
    img = Image.new("RGB", (size, size), "#0b0b0d")
    draw = ImageDraw.Draw(img)
    text = "M↓"
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", int(size * 0.42))
    except Exception:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size - w) / 2 - bbox[0], (size - h) / 2 - bbox[1]), text, font=font, fill="#22c55e")
    img.save(path)

for size, name in [(180, "static/apple-touch-icon.png"), (192, "static/icon-192.png"), (512, "static/icon-512.png")]:
    make_icon(size, name)
