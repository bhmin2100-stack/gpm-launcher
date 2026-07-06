from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
ASSETS.mkdir(exist_ok=True)

size = 256
image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((16, 16, 240, 240), radius=44, fill=(27, 94, 170, 255))
draw.rectangle((16, 166, 240, 240), fill=(40, 163, 106, 255))

font = None
for name in ("C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf"):
    path = Path(name)
    if path.exists():
        font = ImageFont.truetype(str(path), 132)
        break
if font is None:
    font = ImageFont.load_default()

text = "G"
bbox = draw.textbbox((0, 0), text, font=font)
x = (size - (bbox[2] - bbox[0])) / 2 - bbox[0]
y = (size - (bbox[3] - bbox[1])) / 2 - bbox[1] - 8
draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))

image.save(ASSETS / "gpm_launcher.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
