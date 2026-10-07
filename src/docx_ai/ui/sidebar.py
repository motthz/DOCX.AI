"""Barra laterale: elenco moduli con ricerca, ridimensionabile e comprimibile."""

from __future__ import annotations

from pathlib import Path
from tkinter import filedialog
from typing import Any, Dict, List

import customtkinter as ctk

from . import design
from .design import C, font
from .i18n import t
from .icons import icon
from .widgets import EmptyState, button


class Sidebar(ctk.CTkFrame):
    def __init__(self, parent, win: Any):
        super().__init__(parent, fg_color=C["sidebar"], corner_radius=0)
        self.win = win
        self.collapsed = False
        self._rows: Dict[str, ctk.CTkFrame] = {}
        self._search_after = None

        # --- vista espansa
        self.full = ctk.CTkFrame(self, fg_color="transparent")
        head = ctk.CTkFrame(self.full, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(14, 6))
        ctk.CTkLabel(head, text=t("Moduli"), font=font("h3"), text_color=C["text"]).pack(side="left")
        ctk.CTkButton(head, text="", image=icon("panel-left-close", 18), width=30, height=30,
                      fg_color="transparent", hover_color=C["selection"],
                      command=lambda: self.set_collapsed(True)).pack(side="right")
        self.search = ctk.CTkEntry(self.full, placeholder_text=t("Cerca modulo…"),
                                   height=34, corner_radius=8, border_color=C["border"], fg_color=C["surface"])
        self.search.pack(fill="x", padx=14, pady=(0, 8))
        self.search.bind("<KeyRelease>", lambda e: self._schedule_filter(), add="+")
        self.listbox = ctk.CTkScrollableFrame(self.full, fg_color="transparent")
        self.listbox.pack(fill="both", expand=True, padx=6)
        actions = ctk.CTkFrame(self.full, fg_color="transparent")
        actions.pack(fill="x", padx=14, pady=12)
        button(actions, t("Nuovo modulo"), self.new_module, kind="primary", icon_name="plus").pack(fill="x")
        button(actions, t("Importa modulo (ZIP)"), self.import_module, icon_name="download").pack(
            fill="x", pady=(6, 0))

        # --- vista compressa (rail di icone)
        self.rail = ctk.CTkFrame(self, fg_color="transparent")
        for ic, cmd, tip in (("panel-left-open", lambda: self.set_collapsed(False), "Espandi (Ctrl+B)"),
                             ("plus", self.new_module, "Nuovo modulo (Ctrl+N)"),
                             ("download", self.import_module, "Importa modulo")):
            b = ctk.CTkButton(self.rail, text="", image=icon(ic, 20), width=40, height=40,
                              fg_color="transparent", hover_color=C["selection"], command=cmd)
            b.pack(pady=(12, 0))
            from .tooltip import bind as tip_bind
            tip_bind(b, t(tip))

        self.full.pack(fill="both", expand=True)
        win.on("modules", self.render)
        win.on("reports", self.render)  # conteggi bozze/completati aggiornati dopo ogni documento
        win.on("module_selected", lambda m: self._highlight())

    # ------------------------------------------------------------------
    def set_collapsed(self, value: bool) -> None:
        if value == self.collapsed:
            return
        paned = self.win._paned
        if value:
            self._expanded_width = self.winfo_width()
            self.full.pack_forget()
            self.rail.pack(fill="y")
            paned.paneconfigure(self, width=int(64 * design.user_scale()), minsize=int(64 * design.user_scale()))
        else:
            self.rail.pack_forget()
            self.full.pack(fill="both", expand=True)
            scale = design.user_scale()
            width = max(int(240 * scale), min(int(520 * scale), getattr(self, "_expanded_width", 0) or 0))
            paned.paneconfigure(self, width=width, minsize=int(220 * scale))
        self.collapsed = value

    def apply_scale(self, old: float, new: float) -> None:
        """Ridimensiona la barra quando cambia la dimensione del testo."""
        if self.collapsed:
            self.win._paned.paneconfigure(self, width=int(64 * new), minsize=int(64 * new))
            return
        logical = max(240, min(520, self.winfo_width() / (old or 1.0)))
        self.win._paned.paneconfigure(self, width=int(logical * new), minsize=int(220 * new))

    def _schedule_filter(self) -> None:
        if self._search_after:
            self.after_cancel(self._search_after)
        self._search_after = self.after(150, self.render)

    def render(self) -> None:
        for w in self.listbox.winfo_children():
            w.destroy()
        self._rows.clear()
        mods = self.win.modules
        if not mods:
            EmptyState(self.listbox, "package", t("Nessun modulo"),
                       t("Un modulo è il modello di documento (DOCX o XLSX) che l'AI compilerà."),
                       action=(t("Crea il primo modulo"), self.new_module), wraplength=190,
                       secondary=(t("Aggiungi moduli di esempio"), self.add_examples)).pack(fill="x", pady=10)
            return
        q = self.search.get().strip().lower()
        counts = self.win.db.count_reports_by_module()  # una sola query per tutti i moduli
        shown = 0
        for mod in mods:
            hay = f"{mod.name} {mod.slug} {mod.description or ''}".lower()
            if q and q not in hay:
                continue
            shown += 1
            c = counts.get(mod.id or -1, {})
            self._rows[mod.slug] = self._row(mod, c)
        if not shown:
            ctk.CTkLabel(self.listbox, text=t("Nessun modulo corrisponde alla ricerca."),
                         font=font("small"), text_color=C["text_muted"]).pack(pady=12)
        self._highlight()

    def _row(self, mod, counts: Dict[str, int]) -> ctk.CTkFrame:
        row = ctk.CTkFrame(self.listbox, fg_color="transparent", corner_radius=8, cursor="hand2")
        row.pack(fill="x", pady=2)
        tpl_ok = bool(getattr(mod, "template_path", None)) and Path(mod.template_path).exists()
        ic = ctk.CTkLabel(row, text="", image=icon("file-spreadsheet" if mod.template_type == "xlsx"
                                                   else "file-text", 18), width=26)
        ic.pack(side="left", padx=(8, 4), pady=8)
        txt = ctk.CTkFrame(row, fg_color="transparent")
        txt.pack(side="left", fill="x", expand=True, pady=6)
        name = ctk.CTkLabel(txt, text=mod.name, font=font("body_b"), text_color=C["text"], anchor="w",
                            justify="left", wraplength=210)
        name.pack(fill="x")
        parts: List[str] = []
        if counts.get("draft"):
            parts.append(t("{n} bozza", n=1) if counts["draft"] == 1 else t("{n} bozze", n=counts["draft"]))
        done = counts.get("exported", 0) + counts.get("approved", 0)
        if done:
            parts.append(t("{n} completato", n=1) if done == 1 else t("{n} completati", n=done))
        if not tpl_ok:
            parts.append(t("template mancante"))
        meta = ctk.CTkLabel(txt, text=" · ".join(parts) or t("nessun documento"), font=font("caption"),
                            text_color=C["danger"] if not tpl_ok else C["text_muted"], anchor="w")
        meta.pack(fill="x")
        for w in (row, ic, txt, name, meta):
            w.bind("<Button-1>", lambda e, s=mod.slug: self.win.select_module(s), add="+")
            w.bind("<Double-Button-1>", lambda e: self.win.show_page("module"), add="+")
        return row

    def _highlight(self) -> None:
        sel = self.win.selected.slug if self.win.selected else None
        for slug, row in self._rows.items():
            try:
                row.configure(fg_color=C["selection"] if slug == sel else "transparent")
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    def add_examples(self) -> None:
        try:
            added = self.win.mm.install_examples()
        except Exception as exc:  # noqa: BLE001
            self.win.toast(t("Errore: {e}", e=exc), "error")
            return
        self.win.refresh_modules(quiet=True)
        if added:
            self.win.toast(t("Aggiunti {n} moduli di esempio.", n=len(added)), "success")
        else:
            self.win.toast(t("Moduli di esempio non disponibili in questa installazione."), "warning")

    def new_module(self) -> None:
        from .dialogs.new_module import NewModuleDialog
        NewModuleDialog(self.win)

    def import_module(self, path=None) -> None:
        path = path or filedialog.askopenfilename(title=t("Importa modulo (ZIP)"),
                                                  filetypes=[(t("Archivio modulo"), "*.zip")],
                                                  parent=self.win.root)
        if not path:
            return
        try:
            mod = self.win.mm.import_module_zip(Path(path))
        except Exception as exc:  # noqa: BLE001
            self.win.toast(t("Importazione non riuscita: {e}", e=exc), "error")
            return
        self.win.refresh_modules(quiet=True)
        self.win.select_module(mod.slug)
        self.win.toast(t("Modulo importato: {name}", name=mod.name), "success")
