"""Cronologia delle versioni di un rapporto, con confronto e ripristino."""

from __future__ import annotations

import json
from tkinter import messagebox
from typing import Any, Dict, List

import customtkinter as ctk

from ..design import C, font
from ..i18n import t
from ..widgets import button, label
from .base import Dialog


def _fmt(v: Any) -> str:
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return "" if v is None else str(v)


class VersionsDialog(Dialog):
    def __init__(self, win: Any, report_id: int):
        super().__init__(win.root, t("Versioni del documento #{id}", id=report_id), width=980, height=680,
                         icon_name="git-compare",
                         subtitle=t("Ogni approvazione o modifica salva una versione. Seleziona una versione "
                                    "per vedere cosa cambia rispetto a quella attuale."))
        self.win = win
        self.report_id = report_id
        self.versions: List[Dict[str, Any]] = win.db.list_report_versions(report_id)
        row = win.db.get_report(report_id) or {}
        self.current = json.loads(row.get("final_json") or row.get("draft_json") or "{}")

        self.body.columnconfigure(1, weight=1)
        self.body.rowconfigure(0, weight=1)
        listbox = ctk.CTkScrollableFrame(self.body, width=260, fg_color=C["surface"])
        listbox.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        self.diff = ctk.CTkScrollableFrame(self.body, fg_color=C["surface"])
        self.diff.grid(row=0, column=1, sticky="nsew")
        if not self.versions:
            label(listbox, t("Nessuna versione salvata."), muted=True).pack(pady=12)
        self._buttons = []
        for v in self.versions:
            b = ctk.CTkButton(listbox, anchor="w", height=48, fg_color="transparent", hover_color=C["selection"],
                              text_color=C["text"], font=font("small"),
                              text=f"v{v['version']} · {(v['created_at'] or '')[:16].replace('T', ' ')}\n{v.get('note') or ''}",
                              command=lambda vv=v: self.show(vv))
            b.pack(fill="x", pady=2)
            try:  # testo su due righe allineato a sinistra (Tk centra le righe per default)
                b._text_label.configure(justify="left")
            except Exception:  # noqa: BLE001
                pass
            self._buttons.append((b, v))
        self.restore_btn = button(self.footer, t("Ripristina questa versione"), self.restore, kind="primary",
                                  icon_name="rotate-ccw")
        self.restore_btn.pack(side="right", padx=(8, 20), pady=12)
        self.restore_btn.configure(state="disabled")
        button(self.footer, t("Chiudi"), self.close).pack(side="right", pady=12)
        self.selected = None
        if self.versions:
            self.show(self.versions[0])

    def show(self, v: Dict[str, Any]) -> None:
        self.selected = v
        for b, vv in self._buttons:
            b.configure(fg_color=C["selection"] if vv is v else "transparent")
        for w in self.diff.winfo_children():
            w.destroy()
        data = json.loads(v["data_json"])
        keys = list(dict.fromkeys(list(data) + list(self.current)))
        changed = [k for k in keys if _fmt(data.get(k)) != _fmt(self.current.get(k))]
        label(self.diff, t("{n} campi diversi dalla versione attuale", n=len(changed)) if changed
              else t("Identica alla versione attuale"), kind="h4").pack(anchor="w", padx=8, pady=(6, 8))
        for k in changed:
            box = ctk.CTkFrame(self.diff, fg_color=C["surface_alt"], corner_radius=8)
            box.pack(fill="x", padx=8, pady=3)
            label(box, k.replace("_", " ").capitalize(), kind="small_b").pack(anchor="w", padx=10, pady=(6, 0))
            label(box, t("Versione {n}: {v}", n=v["version"], v=_fmt(data.get(k)) or "—"), kind="small",
                  text_color=C["danger"], wraplength=600).pack(anchor="w", padx=10)
            label(box, t("Attuale: {v}", v=_fmt(self.current.get(k)) or "—"), kind="small",
                  text_color=C["success"], wraplength=600).pack(anchor="w", padx=10, pady=(0, 6))
        self.restore_btn.configure(state="normal" if changed else "disabled")

    def restore(self) -> None:
        if not self.selected or not messagebox.askyesno(
                t("Ripristina versione"),
                t("Ripristinare la versione {n}? Verrà salvata come nuova versione e il documento dovrà essere riesportato.",
                  n=self.selected["version"]), parent=self):
            return
        self.win.reports.restore_version(self.report_id, self.selected)
        self.win.emit("reports")
        self.win.toast(t("Versione ripristinata. Apri il documento per riesportarlo."), "success")
        self.close()
