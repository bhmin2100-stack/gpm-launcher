from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
ASSETS.mkdir(exist_ok=True)

def load_font(size):
    for name in ("C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf"):
        path = Path(name)
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def make_icon(filename, text, top_color, bottom_color, font_size):
    size = 256
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((16, 16, 240, 240), radius=44, fill=top_color)
    draw.rectangle((16, 166, 240, 240), fill=bottom_color)

    font = load_font(font_size)
    bbox = draw.textbbox((0, 0), text, font=font)
    x = (size - (bbox[2] - bbox[0])) / 2 - bbox[0]
    y = (size - (bbox[3] - bbox[1])) / 2 - bbox[1] - 8
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))
    image.save(ASSETS / filename, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


make_icon("gpm_launcher.ico", "G", (27, 94, 170, 255), (40, 163, 106, 255), 132)
make_icon("oi_launcher.ico", "OI", (38, 76, 89, 255), (42, 126, 161, 255), 104)
