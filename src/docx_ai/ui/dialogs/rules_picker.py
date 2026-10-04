"""Scelta delle regole AI da modificare: per funzione o per modulo."""

from __future__ import annotations

from typing import Any

import customtkinter as ctk

from ..i18n import t
from ..widgets import button, label
from .base import Dialog


class RulesPicker(Dialog):
    def __init__(self, win: Any):
        super().__init__(win.root, t("Regole AI"), width=620, height=600, icon_name="shield-check",
                         subtitle=t("L'AI legge queste regole ma non può modificarle. Un file vuoto = comportamento standard."))
        self.win = win
        from ..rules_dialog import FEATURE_LABELS_IT
        tabs = ctk.CTkTabview(self.body)
        tabs.pack(fill="both", expand=True)
        feat = tabs.add(t("Per funzione"))
        mods = tabs.add(t("Per modulo"))
        sf = ctk.CTkScrollableFrame(feat, fg_color="transparent")
        sf.pack(fill="both", expand=True)
        for key, lbl in FEATURE_LABELS_IT.items():
            r = ctk.CTkFrame(sf, fg_color="transparent")
            r.pack(fill="x", pady=2)
            label(r, t(lbl), kind="body_b").pack(side="left")
            button(r, t("Modifica"), lambda k=key: self._feature(k), height=28).pack(side="right")
        sm = ctk.CTkScrollableFrame(mods, fg_color="transparent")
        sm.pack(fill="both", expand=True)
        if not win.modules:
            label(sm, t("Nessun modulo."), muted=True).pack(pady=10)
        for m in win.modules:
            r = ctk.CTkFrame(sm, fg_color="transparent")
            r.pack(fill="x", pady=2)
            label(r, m.name, kind="body_b").pack(side="left")
            button(r, t("Modifica"), lambda mm=m: self._module(mm), height=28).pack(side="right")
        button(self.footer, t("Chiudi"), self.close).pack(side="right", padx=20, pady=12)

    def _feature(self, key: str) -> None:
        from ..rules_dialog import RulesEditorDialog
        self.close()
        RulesEditorDialog(self.win.root, self.win.app.rules_manager, feature_key=key)

    def _module(self, mod) -> None:
        from ..rules_dialog import RulesEditorDialog
        self.close()
        RulesEditorDialog(self.win.root, self.win.app.rules_manager, module_name=mod.name,
                          module_folder=mod.folder_path)
