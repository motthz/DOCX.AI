"""Dialog: status + one-click download of the local AI components."""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Optional

from ..config import Config
from ..llm.ai_installer import MODELS, AIInstaller, InstallCancelled
from .assets import logo_image
from .theme import COLORS, FONTS, center_window

LOG = logging.getLogger(__name__)


class AISetupDialog:
    def __init__(self, master: tk.Misc, config: Config,
                 on_installed: Optional[Callable[[], None]] = None):
        self.config = config
        self.on_installed = on_installed
        self._installer: Optional[AIInstaller] = None
        self._busy = False

        self.top = tk.Toplevel(master)
        self.top.title("MaintenanceAI · Componenti AI")
        self.top.configure(bg=COLORS["white"])
        self.top.resizable(False, False)
        self.top.transient(master)
        self.top.protocol("WM_DELETE_WINDOW", self._on_close)

        head = tk.Frame(self.top, bg=COLORS["slate_900"])
        head.pack(fill="x")
        img = logo_image(self.top, 48)
        if img is not None:
            tk.Label(head, image=img, bg=COLORS["slate_900"]).pack(side="left", padx=(18, 12), pady=14)
        tit = tk.Frame(head, bg=COLORS["slate_900"])
        tit.pack(side="left", pady=14)
        tk.Label(tit, text="Motore AI locale", font=FONTS["h3"],
                 bg=COLORS["slate_900"], fg=COLORS["white"]).pack(anchor="w")
        tk.Label(tit, text="Funziona offline: i dati non lasciano mai questo PC.",
                 font=FONTS["body_sm"], bg=COLORS["slate_900"],
                 fg=COLORS["slate_300"]).pack(anchor="w")

        body = tk.Frame(self.top, bg=COLORS["white"], padx=22, pady=16)
        body.pack(fill="both", expand=True)

        self._status_frame = tk.Frame(body, bg=COLORS["white"])
        self._status_frame.pack(fill="x")
        self._render_status()

        tk.Label(body, text="Modello da installare", font=FONTS["body_bold"],
                 bg=COLORS["white"], fg=COLORS["text"]).pack(anchor="w", pady=(14, 4))
        self._model_var = tk.StringVar(value=next(iter(MODELS)))
        for name, info in MODELS.items():
            ttk.Radiobutton(body, text=info["label"], value=name,
                            variable=self._model_var).pack(anchor="w")

        tk.Label(body,
                 text="Il download (una sola volta) richiede Internet e circa 2 GB di spazio.\n"
                      "I file vengono salvati in:  " + str(config.data_root),
                 font=FONTS["body_sm"], bg=COLORS["white"], fg=COLORS["slate_500"],
                 justify="left").pack(anchor="w", pady=(12, 8))

        self._progress = ttk.Progressbar(body, length=460, mode="determinate", maximum=1000)
        self._progress.pack(fill="x", pady=(4, 4))
        self._msg = tk.Label(body, text="", font=FONTS["body_sm"], bg=COLORS["white"],
                             fg=COLORS["slate_600"], anchor="w")
        self._msg.pack(fill="x")

        btns = tk.Frame(body, bg=COLORS["white"])
        btns.pack(fill="x", pady=(14, 0))
        self._close_btn = ttk.Button(btns, text="Chiudi", style="Subtle.TButton",
                                     command=self._on_close)
        self._close_btn.pack(side="right")
        self._install_btn = ttk.Button(btns, text="⬇  Scarica e installa",
                                       style="Accent.TButton", command=self._start)
        self._install_btn.pack(side="right", padx=(0, 8))
        if self._ready():
            self._install_btn.configure(text="⬇  Installa modello selezionato")

        self.top.update_idletasks()
        center_window(self.top, self.top.winfo_reqwidth(), self.top.winfo_reqheight())
        self.top.grab_set()

    # ------------------------------------------------------------------
    def _ready(self) -> bool:
        st = self.config.ai_components_status()
        return st["runtime_ok"] and (st["model_ok"] or st["fallback_ok"])

    def _render_status(self) -> None:
        for w in self._status_frame.winfo_children():
            w.destroy()
        st = self.config.ai_components_status()
        rows = [
            ("Runtime llama.cpp", st["runtime_ok"]),
            (f"Modello principale ({st['model'].name if st['model'] else '-'})", st["model_ok"]),
            (f"Modello leggero ({st['fallback'].name if st['fallback'] else '-'})", st["fallback_ok"]),
        ]
        for label, ok in rows:
            row = tk.Frame(self._status_frame, bg=COLORS["white"])
            row.pack(fill="x", pady=1)
            tk.Label(row, text="●", font=FONTS["body_bold"], bg=COLORS["white"],
                     fg=COLORS["success_500"] if ok else COLORS["slate_300"]).pack(side="left")
            tk.Label(row, text=f"  {label}", font=FONTS["body"], bg=COLORS["white"],
                     fg=COLORS["text"]).pack(side="left")
            tk.Label(row, text="installato" if ok else "mancante", font=FONTS["body_sm"],
                     bg=COLORS["white"],
                     fg=COLORS["success_600"] if ok else COLORS["slate_500"]).pack(side="right")

    def _progress_cb(self, frac: Optional[float], msg: str) -> None:
        def _ui():
            try:
                if frac is None:
                    if str(self._progress.cget("mode")) != "indeterminate":
                        self._progress.configure(mode="indeterminate")
                        self._progress.start(12)
                else:
                    if str(self._progress.cget("mode")) != "determinate":
                        self._progress.stop()
                        self._progress.configure(mode="determinate")
                    self._progress.configure(value=int(frac * 1000))
                self._msg.configure(text=msg)
            except tk.TclError:
                pass
        try:
            self.top.after(0, _ui)
        except Exception:  # noqa: BLE001
            pass

    def _start(self) -> None:
        if self._busy:
            return
        self._busy = True
        self._install_btn.state(["disabled"])
        self._close_btn.configure(text="Annulla")
        self._installer = AIInstaller(self.config.data_root)
        model = self._model_var.get()
        threading.Thread(target=self._worker, args=(model,), daemon=True,
                         name="ai-install").start()

    def _worker(self, model: str) -> None:
        try:
            assert self._installer is not None
            self._installer.install(model, self._progress_cb)
            self.top.after(0, self._done_ok)
        except InstallCancelled:
            self.top.after(0, lambda: self._done_err(None))
        except Exception as exc:  # noqa: BLE001
            LOG.exception("AI install failed")
            self.top.after(0, lambda e=exc: self._done_err(e))

    def _done_ok(self) -> None:
        self._busy = False
        self._progress.stop()
        self._progress.configure(mode="determinate", value=1000)
        self._msg.configure(text="Installazione completata.")
        self._close_btn.configure(text="Chiudi")
        self._render_status()
        if self.on_installed:
            self.on_installed()

    def _done_err(self, exc: Optional[BaseException]) -> None:
        self._busy = False
        self._progress.stop()
        self._progress.configure(mode="determinate", value=0)
        self._install_btn.state(["!disabled"])
        self._close_btn.configure(text="Chiudi")
        if exc is None:
            self._msg.configure(text="Download annullato.")
            return
        self._msg.configure(text="Installazione non riuscita.")
        messagebox.showerror(
            "Installazione AI non riuscita",
            f"{exc}\n\nVerifica la connessione a Internet (proxy/firewall aziendali "
            "possono bloccare GitHub o HuggingFace) e riprova.",
            parent=self.top)

    def _on_close(self) -> None:
        if self._busy and self._installer is not None:
            if not messagebox.askyesno("Annullare il download?",
                                       "Il download è in corso. Vuoi annullarlo?",
                                       parent=self.top):
                return
            self._installer.cancel()
            return
        try:
            self.top.grab_release()
        except tk.TclError:
            pass
        self.top.destroy()
