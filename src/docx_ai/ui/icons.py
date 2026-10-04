"""Icone vettoriali Lucide (PNG pre-renderizzati) come CTkImage chiaro/scuro."""

from __future__ import annotations

from typing import Dict, Tuple

import customtkinter as ctk
from PIL import Image

from .assets import asset_path

_CACHE: Dict[Tuple[str, int, str], ctk.CTkImage] = {}


def _load(name: str, variant: str) -> Image.Image:
    return Image.open(asset_path(f"icons/{name}_{variant}.png"))


def icon(name: str, size: int = 18, tone: str = "auto") -> ctk.CTkImage:
    """tone: "auto" (segue il tema), "white" (su sfondi colorati), "primary"."""
    key = (name, size, tone)
    img = _CACHE.get(key)
    if img is None:
        if tone == "auto":
            img = ctk.CTkImage(_load(name, "light"), _load(name, "dark"), size=(size, size))
        else:
            pil = _load(name, tone)
            img = ctk.CTkImage(pil, pil, size=(size, size))
        _CACHE[key] = img
    return img
