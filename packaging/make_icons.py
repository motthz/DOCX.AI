r"""Genera le icone PNG dell'interfaccia dal font Lucide (licenza ISC).

    .venv\Scripts\python.exe packaging\make_icons.py

Per ogni icona produce src/docx_ai/assets/icons/<nome>_{light,dark,white}.png
(64 px; CustomTkinter le ridimensiona in base al DPI). Le icone usate dall'app
sono elencate in ICONS: aggiungerne una qui e rilanciare lo script.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT = ROOT / "packaging" / "third_party" / "lucide.ttf"
INFO = ROOT / "packaging" / "third_party" / "info.json"
OUT = ROOT / "src" / "docx_ai" / "assets" / "icons"
SIZE = 64

ICONS = """house file-text history package folder-open sparkles upload download file-plus
pencil search shield-check puzzle settings sun moon monitor circle-help cpu refresh-cw plus
trash-2 copy image camera file-spreadsheet file-down archive archive-restore eye git-compare
circle-check triangle-alert x chevron-left chevron-right panel-left-close panel-left-open bug
life-buoy wand-sparkles filter calendar user factory list-checks play square gauge hard-drive
zap info external-link folder file-json layout-template table file-input save rotate-ccw clock
check printer mail send languages accessibility type map-pin bot brain-circuit circle-x
file-search scan-text images keyboard log-out arrow-right arrow-left loader-circle circle-dot
list""".split()

VARIANTS = {"light": (51, 65, 85), "dark": (226, 232, 240), "white": (255, 255, 255),
            "primary": (37, 99, 235)}


def main() -> None:
    info = json.loads(INFO.read_text(encoding="utf-8"))
    font = ImageFont.truetype(str(FONT), int(SIZE * 0.86))
    OUT.mkdir(parents=True, exist_ok=True)
    for name in ICONS:
        code = int(info[name]["encodedCode"].lstrip("\\"), 16)
        ch = chr(code)
        for variant, rgb in VARIANTS.items():
            img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            bbox = d.textbbox((0, 0), ch, font=font)
            w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
            d.text(((SIZE - w) / 2 - bbox[0], (SIZE - h) / 2 - bbox[1]), ch, font=font, fill=rgb + (255,))
            img.save(OUT / f"{name}_{variant}.png", optimize=True)
    print(f"{len(ICONS)} icone x {len(VARIANTS)} varianti -> {OUT}")


if __name__ == "__main__":
    main()
