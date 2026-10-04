r"""Generate the DOCX.AI logo/icon set (run once, outputs are committed).

    .venv\\Scripts\\python.exe packaging\\make_icon.py

Outputs:
  src/docx_ai/assets/app.ico        multi-size Windows icon (16..256)
  src/docx_ai/assets/logo.png       256 px, used by window/header/splash
  packaging/installer/wizard_large.bmp     Inno Setup side image
  packaging/installer/wizard_small.bmp     Inno Setup header image
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "src" / "docx_ai" / "assets"
INSTALLER = ROOT / "packaging" / "installer"

S = 1024  # supersampled canvas
TOP = (37, 99, 235)      # blue-600
BOTTOM = (49, 46, 129)   # indigo-900
SPARK = (52, 211, 153)   # emerald-400


def _gradient(size: int) -> Image.Image:
    g = Image.new("RGB", (size, size))
    px = g.load()
    for y in range(size):
        for x in range(size):
            t = (x * 0.35 + y * 0.65) / size
            px[x, y] = tuple(int(TOP[i] * (1 - t) + BOTTOM[i] * t) for i in range(3))
    return g


def _rounded_mask(size: int, radius: int) -> Image.Image:
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return m


def _document_masks() -> tuple:
    """Foglio con angolo piegato (maschera pagina, maschera piega, maschera righe)."""
    x1, y1, x2, y2, fold = 250, 175, 720, 850, 150
    page = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(page)
    d.rounded_rectangle((x1, y1, x2, y2), radius=46, fill=255)
    d.polygon([(x2 - fold, y1 - 2), (x2 + 2, y1 - 2), (x2 + 2, y1 + fold)], fill=0)
    corner = Image.new("L", (S, S), 0)
    ImageDraw.Draw(corner).polygon([(x2 - fold, y1), (x2 - fold, y1 + fold - 18), (x2 - 18, y1 + fold),
                                    (x2, y1 + fold)], fill=255)
    lines = Image.new("L", (S, S), 0)
    dl = ImageDraw.Draw(lines)
    for k, (ly, lw) in enumerate([(430, 340), (530, 340), (630, 250), (730, 300)]):
        dl.rounded_rectangle((x1 + 70, ly, x1 + 70 + lw, ly + 38), radius=19, fill=255)
    return page, corner, lines


def _spark(cx: int, cy: int, r: int) -> list:
    pts = []
    for i in range(8):
        ang = math.pi / 4 * i - math.pi / 2
        rad = r if i % 2 == 0 else r * 0.28
        pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    return pts


def make_logo() -> Image.Image:
    bg = _gradient(S).convert("RGBA")
    # subtle top highlight
    hl = Image.new("L", (S, S), 0)
    ImageDraw.Draw(hl).ellipse((-S * 0.3, -S * 0.75, S * 1.3, S * 0.45), fill=24)
    bg = Image.composite(Image.new("RGBA", (S, S), (255, 255, 255, 255)), bg, hl)

    page, corner, lines = _document_masks()
    # ombra morbida del foglio
    shadow = page.filter(ImageFilter.GaussianBlur(20))
    shadow = ImageChops.offset(shadow, 12, 18).point(lambda v: int(v * 0.45))
    bg = Image.composite(Image.new("RGBA", (S, S), (10, 15, 40, 255)), bg, shadow)
    bg = Image.composite(Image.new("RGBA", (S, S), (255, 255, 255, 255)), bg, page)
    bg = Image.composite(Image.new("RGBA", (S, S), (191, 210, 255, 255)), bg, corner)
    bg = Image.composite(Image.new("RGBA", (S, S), (147, 170, 230, 255)), bg, lines)

    d = ImageDraw.Draw(bg)
    d.polygon(_spark(760, 640, 165), fill=SPARK + (255,))
    d.polygon(_spark(870, 450, 70), fill=(167, 243, 208, 255))

    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    out.paste(bg, (0, 0), _rounded_mask(S, 220))
    return out


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    INSTALLER.mkdir(parents=True, exist_ok=True)
    logo = make_logo()
    logo.resize((256, 256), Image.LANCZOS).save(ASSETS / "logo.png")
    logo.resize((64, 64), Image.LANCZOS).save(ASSETS / "logo_64.png")
    sizes = [(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64),
             (128, 128), (256, 256)]
    logo.save(ASSETS / "app.ico", sizes=sizes)

    # Inno Setup wizard images (opaque BMP)
    large = Image.new("RGB", (164, 314))
    grad = _gradient(314).resize((164, 314))
    large.paste(grad)
    icon = logo.resize((112, 112), Image.LANCZOS)
    large.paste(icon, (26, 70), icon)
    large.save(INSTALLER / "wizard_large.bmp")
    small = Image.new("RGB", (55, 58), (255, 255, 255))
    icon_s = logo.resize((50, 50), Image.LANCZOS)
    small.paste(icon_s, (2, 4), icon_s)
    small.save(INSTALLER / "wizard_small.bmp")
    print("Icone generate in", ASSETS, "e", INSTALLER)


if __name__ == "__main__":
    main()
