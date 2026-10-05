"""Home: panoramica, azioni rapide, bozze da riprendere e stato dell'AI."""

from __future__ import annotations

import time
from typing import Any

import customtkinter as ctk

from ..design import C, GAP, font
from ..i18n import t
from ..icons import icon
from ..widgets import Card, EmptyState, StatCard, autowrap, button, label, scrollable


def _greeting() -> str:
    h = time.localtime().tm_hour
    return t("Buongiorno") if h < 13 else t("Buon pomeriggio") if h < 18 else t("Buonasera")


class HomePage(ctk.CTkFrame):
    def __init__(self, parent, win: Any):
        super().__init__(parent, fg_color="transparent")
        self.win = win
        page = scrollable(self)
        page.pack(fill="both", expand=True)
        self.page = page

        ctk.CTkLabel(page, text=_greeting(), font=font("display"), text_color=C["text"], anchor="w").pack(
            fill="x")
        label(page, t("Scrivi le informazioni a parole tue: l'AI compila il modulo, tu controlli e approvi."),
              muted=True).pack(fill="x", pady=(2, 16))

        stats = ctk.CTkFrame(page, fg_color="transparent")
        stats.pack(fill="x")
        stats.columnconfigure((0, 1, 2, 3), weight=1, uniform="s")
        self.cards = {
            "modules": StatCard(stats, "package", t("Moduli"), C["link"]),
            "drafts": StatCard(stats, "pencil", t("Bozze aperte"), C["warning"]),
            "done": StatCard(stats, "circle-check", t("Documenti completati"), C["success"]),
            "month": StatCard(stats, "calendar", t("Questo mese"), C["text"]),
        }
        for i, c in enumerate(self.cards.values()):
            c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else GAP // 2, 0 if i == 3 else GAP // 2))

        quick = ctk.CTkFrame(page, fg_color="transparent")
        quick.pack(fill="x", pady=(18, 0))
        quick.columnconfigure((0, 1, 2, 3), weight=1, uniform="q")
        actions = [
            ("sparkles", t("Nuovo documento"), t("Scrivi le informazioni e lascia lavorare l'AI"),
             lambda: win.show_page("report")),
            ("file-plus", t("Nuovo modulo"), t("Da un tuo documento DOCX o XLSX"), lambda: win.sidebar.new_module()),
            ("file-input", t("Importa da tabella"), t("Da file CSV o Excel"),
             lambda: (win.show_page("history"), win.page("history").import_table())),
            ("archive", t("Backup"), t("Salva tutti i dati in un file"),
             lambda: win.page("settings").backup_now()),
        ]
        for i, (ic, title, sub, cmd) in enumerate(actions):
            card = Card(quick, padding=14)
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else GAP // 2, 0 if i == 3 else GAP // 2))
            card.configure(cursor="hand2")
            ctk.CTkLabel(card.body, text="", image=icon(ic, 22, "primary")).pack(anchor="w")
            ctk.CTkLabel(card.body, text=title, font=font("body_b"), text_color=C["text"], anchor="w").pack(
                fill="x", pady=(8, 0))
            autowrap(ctk.CTkLabel(card.body, text=sub, font=font("small"), text_color=C["text_muted"], anchor="w",
                                  justify="left", wraplength=220)).pack(fill="x")
            for w in (card, card.body, *card.body.winfo_children()):
                w.bind("<Button-1>", lambda e, c=cmd: c(), add="+")

        lower = ctk.CTkFrame(page, fg_color="transparent")
        lower.pack(fill="both", expand=True, pady=(18, 0))
        lower.columnconfigure(0, weight=3, uniform="l")
        lower.columnconfigure(1, weight=2, uniform="l")
        self.recent = Card(lower)
        self.recent.grid(row=0, column=0, sticky="nsew", padx=(0, GAP // 2))
        self.ai_card = Card(lower)
        self.ai_card.grid(row=0, column=1, sticky="nsew", padx=(GAP // 2, 0))

        win.on("modules", self.refresh)
        win.on("reports", self.refresh)
        win.on("ai", self._render_ai)
        self.refresh()

    def on_show(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        db = self.win.db
        self.cards["modules"].set(str(len(self.win.modules)))
        self.cards["drafts"].set(str(db.count_reports(status="draft")))
        self.cards["done"].set(str(db.count_reports(status="exported") + db.count_reports(status="approved")))
        month = time.strftime("%Y-%m")
        _rows, n_month = db.search_reports(date_from=f"{month}-01", date_to=f"{month}-31", limit=1)
        self.cards["month"].set(str(n_month))
        self._render_recent()
        self._render_ai()

    def _render_recent(self) -> None:
        body = self.recent.body
        for w in body.winfo_children():
            w.destroy()
        head = ctk.CTkFrame(body, fg_color="transparent")
        head.pack(fill="x")
        label(head, t("Bozze da completare"), kind="h4").pack(side="left")
        button(head, t("Apri storico"), lambda: self.win.show_page("history"), kind="ghost",
               icon_name="arrow-right", height=28).pack(side="right")
        drafts, _n = self.win.db.search_reports(status="draft", limit=6)
        if not drafts:
            EmptyState(body, "circle-check", t("Nessuna bozza in sospeso"),
                       t("Le bozze non approvate compaiono qui e si possono riprendere in qualsiasi momento.")
                       ).pack(fill="x")
            return
        for r in drafts:
            row = ctk.CTkFrame(body, fg_color="transparent")
            row.pack(fill="x", pady=3)
            ctk.CTkLabel(row, text="", image=icon("file-text", 16)).pack(side="left", padx=(0, 8))
            desc = (r.get("input_description") or "").strip().replace("\n", " ")
            box = ctk.CTkFrame(row, fg_color="transparent")
            box.pack(side="left", fill="x", expand=True)
            label(box, (desc[:70] + "…") if len(desc) > 70 else desc or t("(senza descrizione)"),
                  kind="body").pack(fill="x")
            label(box, f"{r.get('module')} · {(r.get('created_at') or '')[:16].replace('T', ' ')}",
                  kind="caption", muted=True).pack(fill="x")
            button(row, t("Riprendi"), lambda rid=r["id"]: self.win.page("report").resume_draft(rid),
                   kind="secondary", height=28).pack(side="right")

    def _render_ai(self) -> None:
        body = self.ai_card.body
        for w in body.winfo_children():
            w.destroy()
        label(body, t("Motore AI"), kind="h4").pack(anchor="w")
        st = self.win.config.ai_components_status()
        ready = st["runtime_ok"] and (st["model_ok"] or st["fallback_ok"])
        ai = self.win.ai
        if not ready and not ai.is_running and not self.win.ollama_available:  # Ollama locale = AI disponibile
            autowrap(label(body, t("L'AI locale non è ancora installata. Senza AI puoi comunque compilare i documenti "
                                   "a mano."), muted=True, wraplength=320)).pack(fill="x", pady=(4, 10))
            button(body, t("Installa AI (una volta)"), self.win.open_ai_setup, kind="primary",
                   icon_name="download").pack(anchor="w")
            return
        state = t("attivo") if ai.is_running else t("pronto (si avvia alla prima richiesta)")
        autowrap(label(body, t("Stato: {s}", s=state), wraplength=320)).pack(fill="x", pady=(4, 0))
        if ai.is_running:
            label(body, ai.backend_label, kind="caption", muted=True).pack(fill="x")
        if getattr(ai, "ram_warning", ""):
            label(body, ai.ram_warning, kind="small", wraplength=320,
                  text_color=C["warning"]).pack(fill="x", pady=(6, 0))
        from ...llm import hardware
        hw = hardware.refresh_memory()
        autowrap(label(body, hw.summary(), kind="caption", muted=True, wraplength=320)).pack(fill="x", pady=(8, 10))
        button(body, t("Gestisci componenti AI"), self.win.open_ai_setup, icon_name="cpu").pack(anchor="w")
