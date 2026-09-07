"""Minimal i18n dict lookup: it-IT default, en-US fallback. No extra dependencies.

Used by dialogs/widgets to translate a small fixed set of common labels.
"""

from __future__ import annotations

from typing import Dict, Optional

_LABELS: Dict[str, Dict[str, str]] = {
    "it-IT": {
        "APP_TITLE": "MaintenanceAI",
        "BUTTON_SAVE": "Salva",
        "BUTTON_CANCEL": "Annulla",
        "BUTTON_OK": "OK",
        "BUTTON_NEW": "Nuovo",
        "BUTTON_OPEN": "Apri",
        "BUTTON_DELETE": "Elimina",
        "BUTTON_EDIT": "Modifica",
        "BUTTON_EXPORT": "Esporta",
        "BUTTON_IMPORT": "Importa",
        "BUTTON_APPROVE": "Approva",
        "BUTTON_DUPLICATE": "Duplica",
        "BUTTON_ARCHIVE": "Archivia",
        "BUTTON_RESTORE": "Ripristina",
        "BUTTON_GENERATE": "Genera bozza",
        "BUTTON_SEARCH": "Cerca",
        "COLUMN_NAME": "Nome",
        "COLUMN_STATUS": "Stato",
        "COLUMN_DATE": "Data",
        "COLUMN_VERSION": "Versione",
        "STATUS_DRAFT": "Bozza",
        "STATUS_APPROVED": "Approvato",
        "STATUS_EXPORTED": "Esportato",
        "STATUS_ALL": "Tutti",
        "HEADER_MODULES": "Moduli",
        "HEADER_REPORTS": "Rapporti",
        "HEADER_DOCUMENTS": "Documenti di riferimento",
        "MSG_WAIT": "Attendere…",
        "MSG_CONFIRM_EXIT": "Chiudere MaintenanceAI? Le modifiche non salvate andranno perse.",
        "MSG_UNSAVED": "Sono presenti modifiche non salvate. Cosa vuoi fare?",
        "MSG_FIRST_RUN": "Benvenuto in MaintenanceAI",
        "ERR_GENERIC": "Si è verificato un errore",
        "ERR_NO_MODULE": "Selezionare un modulo",
        "ERR_NO_TEMPLATE": "Template mancante",
        "QUALITY_GOOD": "Ottima",
        "QUALITY_OK": "Sufficiente",
        "QUALITY_LOW": "Bassa",
        "NOTE_REVIEWER": "Note del revisore",
    },
    "en-US": {
        "APP_TITLE": "MaintenanceAI",
        "BUTTON_SAVE": "Save",
        "BUTTON_CANCEL": "Cancel",
        "BUTTON_OK": "OK",
        "BUTTON_NEW": "New",
        "BUTTON_OPEN": "Open",
        "BUTTON_DELETE": "Delete",
        "BUTTON_EDIT": "Edit",
        "BUTTON_EXPORT": "Export",
        "BUTTON_IMPORT": "Import",
        "BUTTON_APPROVE": "Approve",
        "BUTTON_DUPLICATE": "Duplicate",
        "BUTTON_ARCHIVE": "Archive",
        "BUTTON_RESTORE": "Restore",
        "BUTTON_GENERATE": "Generate draft",
        "BUTTON_SEARCH": "Search",
        "COLUMN_NAME": "Name",
        "COLUMN_STATUS": "Status",
        "COLUMN_DATE": "Date",
        "COLUMN_VERSION": "Version",
        "STATUS_DRAFT": "Draft",
        "STATUS_APPROVED": "Approved",
        "STATUS_EXPORTED": "Exported",
        "STATUS_ALL": "All",
        "HEADER_MODULES": "Modules",
        "HEADER_REPORTS": "Reports",
        "HEADER_DOCUMENTS": "Reference documents",
        "MSG_WAIT": "Please wait…",
        "MSG_CONFIRM_EXIT": "Close MaintenanceAI? Unsaved changes will be lost.",
        "MSG_UNSAVED": "You have unsaved changes. What do you want to do?",
        "MSG_FIRST_RUN": "Welcome to MaintenanceAI",
        "ERR_GENERIC": "An error occurred",
        "ERR_NO_MODULE": "Select a module",
        "ERR_NO_TEMPLATE": "Missing template",
        "QUALITY_GOOD": "Great",
        "QUALITY_OK": "Fair",
        "QUALITY_LOW": "Low",
        "NOTE_REVIEWER": "Reviewer notes",
    },
}


class I18n:
    def __init__(self, lang: str = "it-IT"):
        self.lang = lang if lang in _LABELS else "it-IT"

    def set_lang(self, lang: str) -> None:
        if lang in _LABELS:
            self.lang = lang

    @staticmethod
    def available_langs():
        return list(_LABELS.keys())

    def tr(self, key: str, default: Optional[str] = None) -> str:
        if not key:
            return ""
        lang_map = _LABELS.get(self.lang, _LABELS["it-IT"])
        if key in lang_map:
            return lang_map[key]
        # Fallback en
        en_map = _LABELS.get("en-US", {})
        if key in en_map:
            return en_map[key]
        if default is not None:
            return str(default)
        return str(key)


# Singleton app-wide
_DEFAULT = I18n("it-IT")


def tr(key: str, default: Optional[str] = None) -> str:
    return _DEFAULT.tr(key, default=default)


def set_lang(lang: str) -> None:
    _DEFAULT.set_lang(lang)


def current_lang() -> str:
    return _DEFAULT.lang
