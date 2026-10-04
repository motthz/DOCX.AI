"""Impostazioni: aspetto, AI, dati e backup, supporto, informazioni."""

from __future__ import annotations

import os
import shutil
import threading
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any, Callable, List, Tuple

import customtkinter as ctk

from ... import __version__
from ...datadir import configured_data_dir, set_configured_data_dir
from ...services import backup_service, diagnostics
from .. import design
from ..design import GAP
from ..i18n import LANGS, t
from ..widgets import Card, button, label, scrollable

DOCS_URL = "https://github.com/motthz/DOCX.AI/blob/main/docs/guida-utente.md"


class SettingsPage(ctk.CTkFrame):
    def __init__(self, parent, win: Any):
        super().__init__(parent, fg_color="transparent")
        self.win = win
        self.s = win.settings
        page = scrollable(self)
        page.pack(fill="both", expand=True)
        self.page = page
        label(page, t("Impostazioni"), kind="h2").pack(anchor="w", pady=(0, 10))
        self._appearance()
        self._ai()
        self._data()
        self._support()
        self._about()

    # ------------------------------------------------------------------ helpers
    def _card(self, title: str, sub: str = "") -> ctk.CTkFrame:
        card = Card(self.page)
        card.pack(fill="x", pady=(0, GAP))
        label(card.body, title, kind="h3").pack(anchor="w")
        if sub:
            label(card.body, sub, kind="small", muted=True, wraplength=900).pack(anchor="w", pady=(0, 6))
        return card.body

    def _row(self, parent, title: str, sub: str = "") -> ctk.CTkFrame:
        r = ctk.CTkFrame(parent, fg_color="transparent")
        r.pack(fill="x", pady=6)
        box = ctk.CTkFrame(r, fg_color="transparent")
        box.pack(side="left", fill="x", expand=True)
        label(box, title, kind="body_b").pack(anchor="w")
        if sub:
            label(box, sub, kind="caption", muted=True, wraplength=620).pack(anchor="w")
        right = ctk.CTkFrame(r, fg_color="transparent")
        right.pack(side="right")
        return right

    def _option(self, parent, title: str, sub: str, key: str, options: List[Tuple[str, Any]],
                on_change: Callable[[Any], None] | None = None) -> ctk.CTkOptionMenu:
        right = self._row(parent, title, sub)
        labels = [lbl for lbl, _v in options]
        cur = self.s.get(key)
        cur_lbl = next((lbl for lbl, v in options if str(v) == str(cur)), labels[0])

        def _set(lbl: str) -> None:
            val = dict(options)[lbl]
            self.s.set(key, val)
            if on_change:
                on_change(val)
        m = ctk.CTkOptionMenu(right, values=labels, command=_set, width=220)
        m.set(cur_lbl)
        m.pack()
        return m

    def _switch(self, parent, title: str, sub: str, key: str, on_change=None) -> None:
        right = self._row(parent, title, sub)
        var = ctk.BooleanVar(value=bool(self.s.get(key)))

        def _set() -> None:
            self.s.set(key, var.get())
            if on_change:
                on_change(var.get())
        ctk.CTkSwitch(right, text="", variable=var, command=_set).pack()

    # ------------------------------------------------------------------ sezioni
    def _appearance(self) -> None:
        b = self._card(t("Aspetto e accessibilità"))
        right = self._row(b, t("Tema"), t("«Come Windows» segue automaticamente il tema chiaro/scuro del sistema."))
        seg = ctk.CTkSegmentedButton(right, values=[t("Come Windows"), t("Chiaro"), t("Scuro")],
                                     command=lambda v: self.win.set_theme(
                                         {t("Come Windows"): "system", t("Chiaro"): "light", t("Scuro"): "dark"}[v]))
        seg.set({"system": t("Come Windows"), "light": t("Chiaro"), "dark": t("Scuro")}[self.s.get("ui.theme")])
        seg.pack()
        self._option(b, t("Lingua"), t("Richiede il riavvio dell'app."), "ui.lang",
                     [(name, code) for code, name in LANGS.items()],
                     on_change=lambda v: self._ask_restart())
        right = self._row(b, t("Dimensione del testo e dei controlli"),
                          t("Ingrandisce tutta l'interfaccia (utile su schermi piccoli o per leggere meglio)."))
        scale_lbl = label(right, f"{int(float(self.s.get('ui.scale')) * 100)}%", kind="small_b", width=48)
        scale_lbl.pack(side="right", padx=(8, 0))
        sl = ctk.CTkSlider(right, from_=80, to=160, number_of_steps=8, width=220)
        sl.set(float(self.s.get("ui.scale")) * 100)
        sl.configure(command=lambda v: scale_lbl.configure(text=f"{int(v)}%"))
        sl.bind("<ButtonRelease-1>", lambda e: self._apply_scale(sl.get()), add="+")
        sl.pack(side="right")
        right = self._row(b, t("Scorciatoie da tastiera"), t("Tutte le funzioni principali sono raggiungibili da tastiera."))
        button(right, t("Mostra"), self._shortcuts, icon_name="keyboard").pack()

    def _apply_scale(self, value: float) -> None:
        factor = round(value / 100, 2)
        self.s.set("ui.scale", factor)
        design.set_ui_scale(factor)

    def _ai(self) -> None:
        from ...llm import hardware
        hw = hardware.detect()
        b = self._card(t("Intelligenza artificiale"), hw.summary())
        profiles = list(self.win.config.available_profiles())
        self._option(b, t("Profilo"), t("compatibility = PC lenti (modello piccolo) · balanced = consigliato · "
                                        "fastest = più thread CPU"), "llm.profile",
                     [(p, p) for p in profiles], on_change=self._profile_changed)
        gpu_sub = (t("GPU compatibile rilevata: {g}.", g=", ".join(hw.gpus)) if hw.vulkan and hw.gpus
                   else t("Nessuna GPU Vulkan rilevata: si usa la CPU."))
        self._option(b, t("Accelerazione GPU"), gpu_sub + " " + t("Richiede il runtime GPU (Componenti AI)."),
                     "ai.gpu", [(t("Automatica"), "auto"), (t("Sempre CPU"), "off"), (t("Forza GPU"), "on")],
                     on_change=lambda v: self._reset_ai())
        self._switch(b, t("Precarica il modello all'avvio"),
                     t("La prima bozza è subito pronta; usa RAM anche se non compili documenti."), "ai.preload")
        self._option(b, t("Spegni il motore AI se inattivo"),
                     t("Libera la RAM dopo un periodo senza richieste; si riavvia da solo quando serve."),
                     "ai.idle_minutes", [(t("dopo 5 minuti"), 5), (t("dopo 15 minuti"), 15),
                                         (t("dopo 30 minuti"), 30), (t("dopo 1 ora"), 60), (t("mai"), 0)])
        cores = hw.cpu_cores
        self._option(b, t("Thread CPU"), t("Automatico usa quasi tutti i core lasciandone liberi per il PC."),
                     "ai.threads", [(t("Automatico"), 0)] + [(str(n), n) for n in (2, 4, 6, 8, 12, 16) if n <= cores],
                     on_change=lambda v: self._reset_ai())
        self._option(b, t("Contesto (testo che l'AI può leggere)"),
                     t("Più contesto = più documenti considerati, ma più RAM e più lentezza."),
                     "ai.context", [(t("Da profilo"), 0), ("2048", 2048), ("4096", 4096), ("8192", 8192)],
                     on_change=lambda v: self._reset_ai())
        self._switch(b, t("Ricerca semantica nei documenti"),
                     t("Trova i brani pertinenti anche senza parole in comune (modello di ricerca opzionale)."),
                     "ai.embeddings", on_change=lambda v: setattr(self.win.app.semantic, "enabled", v))
        self._switch(b, t("Controllo delle fonti in revisione"),
                     t("Segnala i valori dell'AI che non compaiono nella descrizione o nei documenti."), "ai.grounding")
        right = self._row(b, t("Componenti AI"), t("Installa o aggiorna runtime, modelli, GPU e ricerca semantica."))
        button(right, t("Gestisci"), self.win.open_ai_setup, kind="primary", icon_name="cpu").pack()

    def _profile_changed(self, name: str) -> None:
        self.win.config.set_profile(name)
        self._reset_ai()

    def _reset_ai(self) -> None:
        threading.Thread(target=self.win.ai.reset, daemon=True).start()
        self.win.toast(t("Impostazioni AI applicate: il motore si riavvierà alla prossima richiesta."), "info")

    def _data(self) -> None:
        b = self._card(t("Dati e backup"))
        right = self._row(b, t("Cartella dati"), str(self.win.config.data_root))
        button(right, t("Apri"), lambda: os.startfile(str(self.win.config.data_root)), kind="ghost").pack(
            side="left")
        button(right, t("Cambia…"), self.change_data_dir, icon_name="folder").pack(side="left", padx=(6, 0))
        if configured_data_dir():
            button(right, t("Predefinita"), self.reset_data_dir, kind="ghost").pack(side="left", padx=(6, 0))
        right = self._row(b, t("Backup"), t("Database, moduli, regole e foto in un unico file ZIP."))
        button(right, t("Crea backup ora"), self.backup_now, kind="primary", icon_name="archive").pack(side="left")
        button(right, t("Ripristina…"), self.restore, icon_name="archive-restore").pack(side="left", padx=(6, 0))
        self._option(b, t("Backup automatico"), t("Nella cartella backups dei dati utente."), "backup.auto_days",
                     [(t("ogni giorno"), 1), (t("ogni settimana"), 7), (t("ogni mese"), 30), (t("disattivato"), 0)])
        self._option(b, t("Backup automatici da conservare"), "", "backup.keep",
                     [("3", 3), ("5", 5), ("10", 10), ("20", 20)])

    def _support(self) -> None:
        b = self._card(t("Aiuto e supporto"))
        right = self._row(b, t("Guida"), t("Manuale d'uso con esempi e domande frequenti."))
        button(right, t("Apri guida"), self.win.show_help, icon_name="circle-help").pack(side="left")
        button(right, t("Guida online"), lambda: webbrowser.open(DOCS_URL), kind="ghost",
               icon_name="external-link").pack(side="left", padx=(6, 0))
        right = self._row(b, t("Tour guidato"), t("Rivedi la presentazione delle funzioni principali."))
        button(right, t("Avvia tour"), self.win.start_tour, icon_name="play").pack()
        right = self._row(b, t("Pacchetto diagnostico"),
                          t("Log e informazioni tecniche, senza i tuoi documenti. Salvato sul Desktop."))
        button(right, t("Crea"), self.diag, icon_name="life-buoy").pack()
        right = self._row(b, t("Segnala un problema"),
                          t("Apre la pagina di segnalazione con versione e sistema già compilati."))
        button(right, t("Segnala"), self.report_issue, icon_name="bug").pack()

    def _about(self) -> None:
        b = self._card(t("Informazioni"))
        label(b, f"DOCX.AI {__version__}", kind="body_b").pack(anchor="w")
        label(b, t("Copyright © 2026 DOCX.AI. Tutti i diritti riservati. Componenti di terze parti "
                   "con licenze nella cartella LICENSES."), kind="small", muted=True, wraplength=900).pack(anchor="w")
        lic = self.win.config.app_root / "LICENSES"
        if not lic.is_dir():
            lic = self.win.config.app_root / "_internal" / "LICENSES"
        button(b, t("Licenze di terze parti"), lambda: os.startfile(str(lic)), kind="ghost",
               icon_name="file-text").pack(anchor="w", pady=(6, 0))

    # ------------------------------------------------------------------ azioni
    def _ask_restart(self) -> None:
        if messagebox.askyesno(t("Riavvio necessario"), t("Riavviare ora DOCX.AI per applicare la modifica?"),
                               parent=self.win.root):
            self.win.restart()

    def _shortcuts(self) -> None:
        text = "\n".join([
            "Ctrl+1…6   " + t("vai alle schede (Home, Compila, Storico, Modulo, Documenti AI, Impostazioni)"),
            "Ctrl+Tab   " + t("scheda successiva"),
            "Ctrl+N     " + t("nuovo modulo"),
            "Ctrl+E     " + t("genera la bozza del documento"),
            "Ctrl+F     " + t("cerca nello storico"),
            "Ctrl+B     " + t("mostra/nascondi la barra laterale"),
            "Ctrl+,     " + t("impostazioni"),
            "F1         " + t("guida"),
            "F5         " + t("ricarica i moduli"),
            "Esc        " + t("chiude la finestra di dialogo"),
            "Canc       " + t("elimina i documenti selezionati (Storico)"),
        ])
        messagebox.showinfo(t("Scorciatoie da tastiera"), text, parent=self.win.root)

    def backup_now(self) -> None:
        self.win.show_page("settings")
        dest = filedialog.asksaveasfilename(
            parent=self.win.root, defaultextension=".zip", filetypes=[("ZIP", "*.zip")],
            initialdir=str(backup_service.backups_dir(self.win.config)),
            initialfile=f"DOCX.AI_backup_{__import__('time').strftime('%Y%m%d_%H%M%S')}.zip")
        if not dest:
            return
        inc = messagebox.askyesno(t("Backup"), t("Includere anche i file esportati (PDF, DOCX)? Il backup sarà più grande."),
                                  parent=self.win.root)
        self.win.toast(t("Backup in corso…"), "info")

        def work():
            try:
                p = backup_service.create_backup(self.win.config, self.win.db, Path(dest), include_exports=inc)
                self.after(0, lambda: self.win.toast(t("Backup creato."), "success",
                                                     action=(t("Mostra"), lambda: os.startfile(str(p.parent)))))
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda e=exc: self.win.toast(t("Backup non riuscito: {e}", e=e), "error"))
        threading.Thread(target=work, daemon=True).start()

    def restore(self) -> None:
        f = filedialog.askopenfilename(parent=self.win.root, filetypes=[(t("Backup DOCX.AI"), "*.zip")],
                                       initialdir=str(backup_service.backups_dir(self.win.config)))
        if not f:
            return
        try:
            info = backup_service.validate_backup(Path(f))
        except Exception as exc:  # noqa: BLE001
            self.win.toast(str(exc), "error")
            return
        if not messagebox.askyesno(
                t("Ripristina backup"),
                t("Ripristinare il backup del {d} (versione {v})?\n\nI dati attuali verranno sostituiti (ne resta "
                  "una copia di sicurezza). L'app si riavvierà.", d=info.get("created", "?")[:16].replace("T", " "),
                  v=info.get("version", "?")), parent=self.win.root, icon="warning"):
            return
        backup_service.schedule_restore(self.win.config, Path(f))
        self.win.restart()

    def change_data_dir(self) -> None:
        new = filedialog.askdirectory(parent=self.win.root, title=t("Nuova cartella dati (anche di rete)"))
        if not new:
            return
        new_p = Path(new)
        cur = self.win.config.data_root
        if new_p.resolve() == cur.resolve():
            return
        move = messagebox.askyesnocancel(
            t("Cartella dati"),
            t("Copiare i dati attuali nella nuova cartella?\n\nSì = copia database, moduli, regole e foto\n"
              "No = usa la cartella così com'è (es. già condivisa da un collega)"), parent=self.win.root)
        if move is None:
            return
        if move:
            try:
                backup = backup_service.create_backup(self.win.config, self.win.db,
                                                      Path(new_p) / "_migrazione.zip")
                shutil.copy2(backup, new_p / backup_service.PENDING)
                backup.unlink()
            except Exception as exc:  # noqa: BLE001
                self.win.toast(t("Copia non riuscita: {e}", e=exc), "error")
                return
        set_configured_data_dir(new_p)
        self.win.restart()

    def reset_data_dir(self) -> None:
        set_configured_data_dir(None)
        self._ask_restart()

    def diag(self) -> None:
        desk = Path(os.path.join(os.environ.get("USERPROFILE", str(Path.home())), "Desktop"))
        p = diagnostics.create_package(self.win.app, desk if desk.is_dir() else self.win.config.data_root)
        self.win.toast(t("Pacchetto diagnostico creato sul Desktop."), "success",
                       action=(t("Mostra"), lambda: os.startfile(str(p.parent))))
        return p

    def report_issue(self) -> None:
        self.diag()
        webbrowser.open(diagnostics.issue_url(self.win.app))
        self.win.toast(t("Allega alla segnalazione il pacchetto diagnostico appena creato sul Desktop."), "info")
