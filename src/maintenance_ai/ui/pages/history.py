"""Storico: ricerca globale, filtri, paginazione e azioni sui rapporti."""

from __future__ import annotations

import json
import os
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, List, Optional

import customtkinter as ctk

from ..design import col
from ..i18n import t
from ..widgets import Card, EmptyState, button, label

PAGE_SIZE = 100
STATUS = [("all", "Tutti"), ("draft", "Bozze"), ("approved", "Approvati"), ("exported", "Esportati")]
STATUS_LABEL = {"draft": "Bozza", "approved": "Approvato", "exported": "Esportato", "failed": "Fallito"}


class HistoryPage(ctk.CTkFrame):
    def __init__(self, parent, win: Any):
        super().__init__(parent, fg_color="transparent")
        self.win = win
        self.rows: List[Dict[str, Any]] = []
        self.total = 0
        self._after: Optional[str] = None

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x")
        label(head, t("Storico rapporti"), kind="h2").pack(side="left")
        self.count_lbl = label(head, "", muted=True)
        self.count_lbl.pack(side="left", padx=12, pady=(6, 0))
        button(head, t("Importa CSV/Excel"), self.import_table, icon_name="file-input").pack(side="right")
        button(head, t("Esporta Excel"), self.export_excel, icon_name="file-spreadsheet").pack(side="right", padx=8)

        filt = Card(self, padding=12)
        filt.pack(fill="x", pady=(10, 8))
        f = filt.body
        self.query = ctk.CTkEntry(f, height=34, placeholder_text=t("Cerca in descrizioni e dati dei rapporti…  (Ctrl+F)"))
        self.query.grid(row=0, column=0, columnspan=4, sticky="ew", padx=(0, 8))
        self.status = ctk.CTkSegmentedButton(f, values=[t(lbl) for _k, lbl in STATUS], command=lambda v: self.reload())
        self.status.set(t("Tutti"))
        self.status.grid(row=0, column=4, columnspan=2, sticky="e")
        self.module = ctk.CTkOptionMenu(f, values=[t("Tutti i moduli")], command=lambda v: self.reload(), height=30)
        self.module.grid(row=1, column=0, sticky="ew", pady=(8, 0), padx=(0, 8))
        self.date_from = ctk.CTkEntry(f, height=30, placeholder_text=t("Dal (gg/mm/aaaa)"), width=130)
        self.date_from.grid(row=1, column=1, sticky="ew", pady=(8, 0), padx=(0, 8))
        self.date_to = ctk.CTkEntry(f, height=30, placeholder_text=t("Al (gg/mm/aaaa)"), width=130)
        self.date_to.grid(row=1, column=2, sticky="ew", pady=(8, 0), padx=(0, 8))
        self.tech = ctk.CTkEntry(f, height=30, placeholder_text=t("Tecnico"), width=150)
        self.tech.grid(row=1, column=3, sticky="ew", pady=(8, 0), padx=(0, 8))
        self.plant = ctk.CTkEntry(f, height=30, placeholder_text=t("Impianto / reparto / macchina"), width=190)
        self.plant.grid(row=1, column=4, sticky="ew", pady=(8, 0), padx=(0, 8))
        button(f, t("Azzera"), self.clear_filters, kind="ghost", height=30).grid(row=1, column=5, pady=(8, 0))
        for c in range(5):
            f.columnconfigure(c, weight=1)
        for e in (self.query, self.date_from, self.date_to, self.tech, self.plant):
            e.bind("<KeyRelease>", lambda ev: self._schedule(), add="+")

        table = Card(self, padding=6)
        table.pack(fill="both", expand=True)
        self._style()
        cols = ("id", "module", "status", "created", "desc")
        self.tree = ttk.Treeview(table.body, columns=cols, show="headings", style="Mai.Treeview",
                                 selectmode="extended")
        for c_, title, w, anchor in (("id", "#", 60, "e"), ("module", t("Modulo"), 200, "w"),
                                     ("status", t("Stato"), 100, "w"), ("created", t("Creato"), 140, "w"),
                                     ("desc", t("Descrizione"), 520, "w")):
            self.tree.heading(c_, text=title)
            self.tree.column(c_, width=w, anchor=anchor, stretch=(c_ == "desc"))
        vsb = ctk.CTkScrollbar(table.body, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self.open_selected(), add="+")
        self.tree.bind("<Button-3>", self._context_menu, add="+")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._update_actions(), add="+")
        self.tree.bind("<Delete>", lambda e: self.delete_selected(), add="+")
        self.empty = EmptyState(table.body, "history", t("Nessun rapporto trovato"),
                                t("Crea un rapporto dalla scheda Rapporto o modifica i filtri di ricerca."))

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", pady=(8, 0))
        self.more_btn = button(bar, t("Carica altri"), self.load_more, kind="ghost")
        self.actions: List[ctk.CTkButton] = []
        for text, ic, cmd in ((t("Anteprima PDF"), "eye", self.preview), (t("Apri / modifica"), "pencil", self.open_selected),
                              (t("Duplica"), "copy", self.duplicate), (t("Versioni"), "git-compare", self.versions),
                              (t("Cartella"), "folder-open", self.open_folder), (t("Elimina"), "trash-2", self.delete_selected)):
            b = button(bar, text, cmd, icon_name=ic, kind="danger" if ic == "trash-2" else "secondary", height=30)
            b.pack(side="right", padx=(6, 0))
            self.actions.append(b)
        win.on("reports", self.reload)
        win.on("modules", self._fill_modules)
        win.on("theme", lambda m: self._style())
        self._fill_modules()
        self.reload()

    # ------------------------------------------------------------------ stile
    def _style(self) -> None:
        s = ttk.Style(self)
        s.configure("Mai.Treeview", background=col("surface"), fieldbackground=col("surface"),
                    foreground=col("text"), rowheight=32, borderwidth=0, font=("Segoe UI", 11))
        s.configure("Mai.Treeview.Heading", background=col("surface_alt"), foreground=col("text_muted"),
                    font=("Segoe UI", 10, "bold"), relief="flat", borderwidth=0)
        s.map("Mai.Treeview", background=[("selected", col("selection"))], foreground=[("selected", col("text"))])
        s.layout("Mai.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        if hasattr(self, "tree"):
            self.tree.tag_configure("draft", foreground=col("warning"))

    def on_show(self) -> None:
        self.reload()

    def focus_search(self) -> None:
        self.query.focus_set()

    def _fill_modules(self) -> None:
        names = [t("Tutti i moduli")] + [m.name for m in self.win.modules]
        self.module.configure(values=names)
        if self.module.get() not in names:
            self.module.set(names[0])

    def clear_filters(self) -> None:
        for e in (self.query, self.date_from, self.date_to, self.tech, self.plant):
            e.delete(0, "end")
        self.status.set(t("Tutti"))
        self.module.set(t("Tutti i moduli"))
        self.reload()

    def _schedule(self) -> None:
        if self._after:
            self.after_cancel(self._after)
        self._after = self.after(250, self.reload)

    @staticmethod
    def _iso(text: str) -> Optional[str]:
        text = text.strip()
        if not text:
            return None
        for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"):
            try:
                return time.strftime("%Y-%m-%d", time.strptime(text, fmt))
            except ValueError:
                continue
        return None

    def _filters(self) -> Dict[str, Any]:
        status = dict((t(lbl), k) for k, lbl in STATUS).get(self.status.get(), "all")
        mod = next((m for m in self.win.modules if m.name == self.module.get()), None)
        return dict(query=self.query.get(), status=None if status == "all" else status,
                    module_id=mod.id if mod else None, date_from=self._iso(self.date_from.get()),
                    date_to=self._iso(self.date_to.get()),
                    field_filters={"tecnico": self.tech.get(), "impianto": self.plant.get()})

    def reload(self) -> None:
        self.rows, self.total = self.win.db.search_reports(limit=PAGE_SIZE, offset=0, **self._filters())
        self._render(clear=True)

    def load_more(self) -> None:
        more, self.total = self.win.db.search_reports(limit=PAGE_SIZE, offset=len(self.rows), **self._filters())
        self.rows.extend(more)
        self._render(clear=False, new=more)

    def _render(self, clear: bool, new: Optional[List[Dict[str, Any]]] = None) -> None:
        if clear:
            self.tree.delete(*self.tree.get_children())
        for r in (self.rows if clear else new or []):
            desc = (r.get("input_description") or "").replace("\n", " ")
            self.tree.insert("", "end", iid=str(r["id"]), tags=(r.get("status"),), values=(
                r["id"], r.get("module"), t(STATUS_LABEL.get(r.get("status"), r.get("status") or "")),
                (r.get("created_at") or "")[:16].replace("T", " "), desc[:160]))
        self.count_lbl.configure(text=t("{n} di {total} rapporti", n=len(self.rows), total=self.total))
        if self.total > len(self.rows):
            self.more_btn.pack(side="left")
        else:
            self.more_btn.pack_forget()
        if not self.rows:
            self.empty.place(relx=0.5, rely=0.45, anchor="center")
        else:
            self.empty.place_forget()
        self._update_actions()

    # ------------------------------------------------------------------ azioni
    def _selected(self) -> List[Dict[str, Any]]:
        ids = {int(i) for i in self.tree.selection()}
        return [r for r in self.rows if r["id"] in ids]

    def _update_actions(self) -> None:
        state = "normal" if self.tree.selection() else "disabled"
        for b in self.actions:
            b.configure(state=state)

    def _context_menu(self, event) -> None:
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        if iid not in self.tree.selection():
            self.tree.selection_set(iid)
        m = tk.Menu(self, tearoff=0)
        for text, cmd in ((t("Anteprima PDF"), self.preview), (t("Apri / modifica"), self.open_selected),
                          (t("Duplica"), self.duplicate), (t("Versioni"), self.versions),
                          (t("Apri cartella"), self.open_folder), (t("Esporta selezionati in Excel"),
                                                                   lambda: self.export_excel(selected=True)),
                          (t("Elimina"), self.delete_selected)):
            m.add_command(label=text, command=cmd)
        m.tk_popup(event.x_root, event.y_root)

    def preview(self) -> None:
        sel = self._selected()
        if not sel:
            return
        pdf = sel[0].get("output_pdf_path")
        if not pdf or not Path(pdf).is_file():
            self.win.toast(t("Questo rapporto non ha ancora un PDF: approvalo per esportarlo."), "info")
            return
        from ..dialogs.pdf_preview import PdfPreview
        PdfPreview(self.win.root, Path(pdf), win=self.win)

    def open_folder(self) -> None:
        sel = self._selected()
        p = sel[0].get("output_json_path") if sel else None
        if p and Path(p).exists():
            os.startfile(str(Path(p).parent))  # type: ignore[attr-defined]
        else:
            self.win.toast(t("Cartella di esportazione non disponibile."), "warning")

    def open_selected(self) -> None:
        sel = self._selected()
        if not sel:
            return
        r = self.win.db.get_report(sel[0]["id"])
        if r is None:
            return
        if r.get("status") == "draft":
            self.win.page("report").resume_draft(r["id"])
            return
        mod = next((m for m in self.win.modules if m.id == r.get("module_id")), None)
        if mod is None:
            self.win.toast(t("Il modulo di questo rapporto non esiste più."), "error")
            return
        from ..dialogs.review import ReviewDialog
        data = json.loads(r.get("final_json") or r.get("draft_json") or "{}")
        dlg = ReviewDialog(self.win, mod, None, data, description=r.get("input_description") or "",
                           notes=r.get("review_notes") or "", title=t("Modifica rapporto #{id}", id=r["id"]),
                           approve_text=t("Salva nuova versione e riesporta"))
        result = dlg.wait()
        if result is None:
            return
        notes = result.pop("__review_notes__", "")
        self.win.reports.update_approved(r["id"], result, t("Modifica dopo l'approvazione"))
        self.win.db.update_report(r["id"], review_notes=notes)

        def work():
            try:
                self.win.reports.finalize_exports(r["id"], mod)
                self.after(0, lambda: (self.win.emit("reports"),
                                       self.win.toast(t("Nuova versione salvata ed esportata."), "success")))
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda e=exc: self.win.toast(t("Esportazione non riuscita: {e}", e=e), "error"))
        threading.Thread(target=work, daemon=True).start()

    def duplicate(self) -> None:
        sel = self._selected()
        if not sel:
            return
        new_id = self.win.reports.duplicate_report(sel[0]["id"])
        self.win.emit("reports")
        self.win.toast(t("Creata la bozza #{id} come copia.", id=new_id), "success",
                       action=(t("Apri"), lambda: self.win.page("report").resume_draft(new_id)))

    def versions(self) -> None:
        sel = self._selected()
        if sel:
            from ..dialogs.versions import VersionsDialog
            VersionsDialog(self.win, sel[0]["id"])

    def delete_selected(self) -> None:
        sel = self._selected()
        if not sel or not messagebox.askyesno(
                t("Elimina rapporti"), t("Eliminare {n} rapporti dallo storico? I file già esportati restano su disco.",
                                         n=len(sel)), parent=self.win.root, icon="warning"):
            return
        for r in sel:
            self.win.db.delete_report(r["id"])
        self.win.emit("reports")
        self.win.toast(t("{n} rapporti eliminati.", n=len(sel)), "success")

    def export_excel(self, selected: bool = False) -> None:
        if selected:
            rows = [self.win.db.get_report(r["id"]) for r in self._selected()]
        else:
            rows, _n = self.win.db.search_reports(limit=100000, **self._filters())
        rows = [r for r in rows if r]
        if not rows:
            self.win.toast(t("Nessun rapporto da esportare con i filtri attuali."), "warning")
            return
        dest = filedialog.asksaveasfilename(
            parent=self.win.root, defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")],
            initialfile=f"Riepilogo_rapporti_{time.strftime('%Y%m%d')}.xlsx")
        if not dest:
            return
        from ...exporters.summary_xlsx import export_summary
        f = self._filters()
        period = " - ".join(x for x in (f["date_from"], f["date_to"]) if x)
        export_summary(rows, Path(dest), title=t("Riepilogo rapporti {p}", p=period).strip())
        self.win.toast(t("Esportati {n} rapporti in Excel.", n=len(rows)), "success",
                       action=(t("Apri"), lambda: os.startfile(dest)))

    def import_table(self) -> None:
        mod = self.win.require_module()
        if mod is None:
            return
        from ..dialogs.table_import import TableImportDialog
        TableImportDialog(self.win, mod)
