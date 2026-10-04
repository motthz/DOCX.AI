"""Traduzioni dell'interfaccia (italiano = lingua sorgente, inglese = catalogo).

Uso nel codice nuovo::

    from .i18n import t
    ttk.Label(text=t("Nuovo rapporto"))
    t("Caricati {n} moduli", n=3)

Il testo italiano e' la chiave; ``locales/en.json`` contiene le traduzioni.
Per le finestre Tk preesistenti, ``install_tk_translator()`` traduce al volo le
opzioni ``text``/``title``/``label`` di tutti i widget Tk/ttk, i titoli delle
finestre e i messagebox, usando lo stesso catalogo.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict

LANGS = {"it-IT": "Italiano", "en-US": "English"}
_lang = "it-IT"
_catalog: Dict[str, str] = {}
_LOCALES = Path(__file__).resolve().parent.parent / "locales"
# Prefisso di icone/emoji/spazi da preservare (es. "📝  Crea documento").
_PREFIX = re.compile(r"^([^\w«(\"'¿¡{\[]*)(.*?)(\s*)$", re.S)


def _load_catalog() -> Dict[str, str]:
    import sys
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "maintenance_ai" / "locales" / "en.json")
    candidates.append(_LOCALES / "en.json")
    for c in candidates:
        if c.is_file():
            try:
                return json.loads(c.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return {}
    return {}


def set_language(code: str) -> None:
    global _lang, _catalog
    _lang = code if code in LANGS else "it-IT"
    _catalog = _load_catalog() if _lang == "en-US" else {}


def current_language() -> str:
    return _lang


def _lookup(text: str) -> str:
    if not _catalog or not text:
        return text
    hit = _catalog.get(text)
    if hit is not None:
        return hit
    m = _PREFIX.match(text)
    if m and m.group(2):
        core = _catalog.get(m.group(2))
        if core is not None:
            return m.group(1) + core + m.group(3)
    return text


def t(text: str, **fmt: Any) -> str:
    out = _lookup(text)
    return out.format(**fmt) if fmt else out


# ---------------------------------------------------------------- legacy Tk
_installed = False
_TEXT_KEYS = ("text", "-text", "title", "-title", "label", "-label")


def install_tk_translator() -> None:
    """Traduce automaticamente i testi delle finestre Tk/ttk esistenti."""
    global _installed
    if _installed:
        return
    _installed = True
    import tkinter as tk
    from tkinter import messagebox, ttk

    orig_options = tk.Misc._options

    def _options(self, cnf, kw=None):  # type: ignore[no-untyped-def]
        if _catalog:
            for d in (cnf, kw):
                if isinstance(d, dict):
                    for k in _TEXT_KEYS:
                        v = d.get(k)
                        if isinstance(v, str):
                            d[k] = _lookup(v)
        return orig_options(self, cnf, kw)

    tk.Misc._options = _options  # type: ignore[method-assign]

    orig_fmt = ttk._format_optdict

    def _format_optdict(optdict, script=False, ignore=None):  # type: ignore[no-untyped-def]
        if _catalog and isinstance(optdict, dict):
            optdict = {k: (_lookup(v) if k in ("text", "-text") and isinstance(v, str) else v)
                       for k, v in optdict.items()}
        return orig_fmt(optdict, script, ignore)

    ttk._format_optdict = _format_optdict  # type: ignore[assignment]

    orig_title = tk.Wm.wm_title

    def wm_title(self, string=None):  # type: ignore[no-untyped-def]
        if isinstance(string, str):
            string = _lookup(string)
        return orig_title(self, string)

    tk.Wm.wm_title = tk.Wm.title = wm_title  # type: ignore[method-assign]

    for name in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel",
                 "askyesnocancel", "askquestion", "askretrycancel"):
        orig = getattr(messagebox, name)

        def wrapper(title=None, message=None, _orig=orig, **options):  # type: ignore[no-untyped-def]
            return _orig(_lookup(title) if isinstance(title, str) else title,
                         _lookup(message) if isinstance(message, str) else message, **options)

        setattr(messagebox, name, wrapper)
