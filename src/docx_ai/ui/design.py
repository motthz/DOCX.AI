"""Design system dell'interfaccia (CustomTkinter).

- Token colore come coppie (chiaro, scuro): CustomTkinter sceglie in base al tema.
- Scala tipografica unica (Segoe UI Variable su Windows 11, Segoe UI altrimenti).
- Tema: "light" | "dark" | "system" (segue Windows), titlebar scura nativa.
- Sincronizza la palette legacy (theme.COLORS) usata dalle finestre Tk esistenti,
  cosi' anche loro si aprono nel tema corrente.
"""

from __future__ import annotations

import sys
import tkinter as tk
from typing import Dict, Optional, Tuple

import customtkinter as ctk

from . import theme as legacy

Color = Tuple[str, str]

# ---------------------------------------------------------------- colori
# Contrasti verificati WCAG AA (>= 4.5:1 testo normale) su bg e surface.
C: Dict[str, Color] = {
    "bg":            ("#f4f6fb", "#0b1120"),
    "surface":       ("#ffffff", "#131c2e"),
    "surface_alt":   ("#f8fafc", "#18233a"),
    "sidebar":       ("#eef2f8", "#0f172a"),
    "border":        ("#e2e8f0", "#253247"),
    "text":          ("#0f172a", "#e8edf5"),
    "text_muted":    ("#475569", "#a3b1c6"),
    "text_faint":    ("#64748b", "#8394ab"),
    "primary":       ("#2563eb", "#2563eb"),  # sfondi/pulsanti; per i testi blu usare "link"
    "primary_hover": ("#1d4ed8", "#1d4ed8"),
    "primary_soft":  ("#e8efff", "#1a2a4d"),
    "on_primary":    ("#ffffff", "#ffffff"),
    "success":       ("#047857", "#34d399"),
    "success_soft":  ("#e7f8f0", "#11352b"),
    "warning":       ("#b45309", "#fbbf24"),
    "warning_soft":  ("#fff6e5", "#3a2c0e"),
    "danger":        ("#b91c1c", "#f87171"),
    "danger_soft":   ("#fdecec", "#3d1518"),
    "info_soft":     ("#eef4ff", "#16233f"),
    "link":          ("#2563eb", "#7cb0ff"),
    "header":        ("#0f172a", "#060b16"),
    "header_text":   ("#ffffff", "#ffffff"),
    "header_muted":  ("#cbd5e1", "#94a3b8"),
    "selection":     ("#dbe7ff", "#22355e"),
}


def col(name: str) -> str:
    """Colore effettivo nel tema corrente (per widget Tk non-CTk)."""
    light, dark = C[name]
    return dark if ctk.get_appearance_mode() == "Dark" else light


# ---------------------------------------------------------------- font
FONT_FAMILY = "Segoe UI Variable Text" if sys.platform == "win32" else "Segoe UI"
FONT_DISPLAY = "Segoe UI Variable Display" if sys.platform == "win32" else "Segoe UI"
TYPE_SCALE = {
    "display": (FONT_DISPLAY, 26, "bold"),
    "h1":      (FONT_DISPLAY, 22, "bold"),
    "h2":      (FONT_DISPLAY, 18, "bold"),
    "h3":      (FONT_FAMILY, 15, "bold"),
    "h4":      (FONT_FAMILY, 13, "bold"),
    "body":    (FONT_FAMILY, 13, "normal"),
    "body_b":  (FONT_FAMILY, 13, "bold"),
    "small":   (FONT_FAMILY, 12, "normal"),
    "small_b": (FONT_FAMILY, 12, "bold"),
    "caption": (FONT_FAMILY, 11, "normal"),
    "mono":    ("Cascadia Mono" if sys.platform == "win32" else "Consolas", 12, "normal"),
}
_FONT_CACHE: Dict[str, ctk.CTkFont] = {}


def font(key: str = "body") -> ctk.CTkFont:
    if key not in _FONT_CACHE:
        fam, size, weight = TYPE_SCALE[key]
        _FONT_CACHE[key] = ctk.CTkFont(family=fam, size=size, weight=weight)
    return _FONT_CACHE[key]


def ensure_font_family(root: tk.Misc) -> None:
    """Segoe UI Variable esiste solo su Windows 11: altrimenti Segoe UI."""
    global FONT_FAMILY, FONT_DISPLAY
    try:
        families = set(root.tk.call("font", "families"))
    except tk.TclError:
        return
    if FONT_FAMILY not in families:
        FONT_FAMILY = FONT_DISPLAY = "Segoe UI"
        for k, (fam, size, weight) in list(TYPE_SCALE.items()):
            if fam.startswith("Segoe UI Variable"):
                TYPE_SCALE[k] = ("Segoe UI", size, weight)


# ---------------------------------------------------------------- spaziatura
PAD = 16
GAP = 12
RADIUS = 12

# ---------------------------------------------------------------- tema
_LEGACY_LIGHT = dict(legacy.COLORS)
_LEGACY_DARK = {
    **legacy.DARK_COLORS,
    "white": "#131c2e",
    "card_bg": "#131c2e",
    "bg": "#0b1120",
    "text": "#e8edf5",
    "muted": "#a3b1c6",
    "primary_50": "#1a2a4d",
    "success_50": "#11352b",
    "warning_50": "#3a2c0e",
    "danger_50": "#3d1518",
}


def effective_mode() -> str:
    return "dark" if ctk.get_appearance_mode() == "Dark" else "light"


def apply_appearance(mode: str, root: Optional[tk.Misc] = None,
                     legacy_theme: Optional["legacy.ModernTheme"] = None) -> str:
    """Applica il tema ("light" | "dark" | "system") e lo propaga ovunque."""
    mode = mode if mode in ("light", "dark", "system") else "system"
    ctk.set_appearance_mode(mode)
    eff = effective_mode()
    legacy.COLORS.clear()
    legacy.COLORS.update(_LEGACY_DARK if eff == "dark" else _LEGACY_LIGHT)
    if legacy_theme is not None:
        try:
            legacy_theme.theme_name = eff
            legacy_theme._configure_styles()
        except Exception:  # noqa: BLE001
            pass
    if root is not None:
        set_dark_titlebar(root, eff == "dark")
    return eff


def set_dark_titlebar(window: tk.Misc, dark: bool) -> None:
    """Titlebar scura nativa (Windows 10 1809+ / 11) via DWM."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
        value = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (nuovo, vecchio)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except Exception:  # noqa: BLE001
        pass


def set_ui_scale(factor: float) -> None:
    """Dimensione del testo/interfaccia regolabile (accessibilita')."""
    factor = max(0.8, min(1.6, float(factor)))
    ctk.set_widget_scaling(factor)


def user_scale() -> float:
    """Dimensione del testo scelta dall'utente (1.0 = 100%)."""
    try:
        return float(ctk.ScalingTracker.widget_scaling) or 1.0
    except Exception:  # noqa: BLE001
        return 1.0


def init_ctk() -> None:
    ctk.set_default_color_theme("blue")
