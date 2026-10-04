"""Impostazioni utente tipizzate (salvate nella tabella ``settings`` del DB)."""

from __future__ import annotations

from typing import Any, Dict

from ..db import Database

DEFAULTS: Dict[str, Any] = {
    # interfaccia
    "ui.theme": "system",          # light | dark | system
    "ui.lang": "it-IT",
    "ui.scale": 1.0,               # 0.8 .. 1.6
    "ui.last_tab": "home",
    "ui.sidebar_width": 300,
    "ui.sidebar_collapsed": False,
    "ui.tour_done": False,
    # AI
    "llm.profile": "balanced",
    "ai.gpu": "auto",              # auto | on | off
    "ai.preload": True,            # carica il modello all'avvio in background
    "ai.idle_minutes": 15,         # spegne il motore dopo N minuti di inattivita' (0 = mai)
    "ai.embeddings": True,         # ricerca semantica se il modello di embedding e' installato
    "ai.threads": 0,               # 0 = automatico
    "ai.context": 0,               # 0 = da profilo
    "ai.grounding": True,          # evidenzia i valori non trovati nelle fonti
    # backup
    "backup.auto_days": 7,         # 0 = disattivato
    "backup.keep": 5,
}


class Settings:
    def __init__(self, db: Database):
        self.db = db

    def get(self, key: str) -> Any:
        default = DEFAULTS.get(key)
        raw = self.db.get_setting(key)
        if raw is None:
            return default
        if isinstance(default, bool):
            return str(raw).lower() in ("1", "true", "yes", "si", "on")
        if isinstance(default, int):
            try:
                return int(float(raw))
            except ValueError:
                return default
        if isinstance(default, float):
            try:
                return float(raw)
            except ValueError:
                return default
        return raw

    def set(self, key: str, value: Any) -> None:
        if isinstance(value, bool):
            value = "1" if value else "0"
        self.db.set_setting(key, str(value))

    def all(self) -> Dict[str, Any]:
        return {k: self.get(k) for k in DEFAULTS}
