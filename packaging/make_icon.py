r"""Generate the MaintenanceAI logo/icon set (run once, outputs are committed).

    .venv\\Scripts\\python.exe packaging\\make_icon.py

Outputs:
  src/maintenance_ai/assets/app.ico        multi-size Windows icon (16..256)
  src/maintenance_ai/assets/logo.png       256 px, used by window/header/splash
  packaging/installer/wizard_large.bmp     Inno Setup side image
  packaging/installer/wizard_small.bmp     Inno Setup header image
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "src" / "maintenance_ai" / "assets"
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


def _wrench_mask() -> Image.Image:
    m = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(m)
    cy = S // 2
    # handle
    d.rounded_rectangle((330, cy - 58, 800, cy + 58), radius=58, fill=255)
    # open-end head
    d.ellipse((150, cy - 175, 470, cy + 175), fill=255)
    # jaw opening
    d.rectangle((120, cy - 62, 320, cy + 62), fill=0)
    d.ellipse((250, cy - 62, 374, cy + 62), fill=0)
    # hole at the handle end
    d.ellipse((712, cy - 30, 772, cy + 30), fill=0)
    return m.rotate(45, resample=Image.BICUBIC, center=(S // 2, S // 2))


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

    wrench = _wrench_mask()
    # soft drop shadow
    shadow = wrench.filter(ImageFilter.GaussianBlur(18))
    shadow = ImageChops.offset(shadow, 10, 16).point(lambda v: int(v * 0.45))
    bg = Image.composite(Image.new("RGBA", (S, S), (10, 15, 40, 255)), bg, shadow)
    bg = Image.composite(Image.new("RGBA", (S, S), (255, 255, 255, 255)), bg, wrench)

    d = ImageDraw.Draw(bg)
    d.polygon(_spark(800, 225, 135), fill=SPARK + (255,))
    d.polygon(_spark(625, 130, 58), fill=(167, 243, 208, 255))

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
