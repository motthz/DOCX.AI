"""Componenti AI: stato, hardware e download (runtime CPU/GPU, modelli, ricerca semantica)."""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from tkinter import messagebox
from typing import Callable, Optional

import customtkinter as ctk

from ..config import Config
from ..llm import hardware
from ..llm.ai_installer import EMBEDDING_MODEL, MODELS, AIInstaller, InstallCancelled
from ..llm.embeddings import EMBED_MODEL_PATH
from .design import C, font
from .dialogs.base import Dialog
from .i18n import t
from .widgets import Chip, button, label

LOG = logging.getLogger(__name__)


class AISetupDialog(Dialog):
    def __init__(self, master: tk.Misc, config: Config, on_installed: Optional[Callable[[], None]] = None,
                 auto_model: Optional[str] = None):
        super().__init__(master, t("Componenti AI"), width=700, height=720, icon_name="cpu",
                         subtitle=t("L'AI funziona offline: i dati non lasciano mai questo PC. "
                                    "Il download serve una sola volta."))
        self.config = config
        self.on_installed = on_installed
        self._installer: Optional[AIInstaller] = None
        self._busy = False
        self.hw = hardware.refresh_memory(hardware.detect())

        label(self.body, self.hw.summary(), kind="small", muted=True, wraplength=640).pack(anchor="w")
        self.status_box = ctk.CTkFrame(self.body, fg_color=C["surface"], corner_radius=10, border_width=1,
                                       border_color=C["border"])
        self.status_box.pack(fill="x", pady=(8, 12))
        self._render_status()

        label(self.body, t("Modello da installare"), kind="h4").pack(anchor="w")
        rec = auto_model if auto_model in MODELS else self.hw.recommended_model()
        self.model_var = ctk.StringVar(value=rec)
        for name, info in MODELS.items():
            if info.get("hidden") and name != rec:
                continue
            text = t(info["label"]) + ("  ·  " + t("consigliato per questo PC") if name == rec else "")
            ctk.CTkRadioButton(self.body, text=text, value=name, variable=self.model_var,
                               font=font("body")).pack(anchor="w", pady=2)

        label(self.body, t("Opzioni"), kind="h4").pack(anchor="w", pady=(12, 0))
        self.gpu_var = ctk.BooleanVar(value=self.hw.gpu_accel)
        ctk.CTkCheckBox(self.body, text=t("Accelerazione GPU (Vulkan, ~30 MB in più)"), variable=self.gpu_var,
                        font=font("body")).pack(anchor="w", pady=2)
        if not self.hw.vulkan:
            label(self.body, t("Nessun driver Vulkan rilevato: verrà usata la CPU."), kind="caption",
                  muted=True).pack(anchor="w", padx=(30, 0))
        self.emb_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(self.body, text=t(next(iter(EMBEDDING_MODEL.values()))["label"]), variable=self.emb_var,
                        font=font("body")).pack(anchor="w", pady=2)
        label(self.body, t("I file vengono salvati in: {p}", p=config.data_root), kind="caption", muted=True,
              wraplength=640).pack(anchor="w", pady=(10, 4))

        self.install_btn = button(self.footer, t("Scarica e installa"), self.start, kind="primary",
                                  icon_name="download")
        self.install_btn.pack(side="right", padx=(8, 20), pady=12)
        self.close_btn = button(self.footer, t("Chiudi"), self.cancel)
        self.close_btn.pack(side="right", pady=12)
        # avanzamento nel piede, sempre visibile: nel corpo finiva sotto il bordo della
        # finestra sugli schermi bassi (la finestra viene ridotta all'altezza dello schermo)
        prog = ctk.CTkFrame(self.footer, fg_color="transparent")
        prog.pack(side="left", fill="x", expand=True, padx=(20, 8))
        self.progress = ctk.CTkProgressBar(prog, mode="determinate")
        self.progress.set(0)
        self.progress.pack(fill="x", pady=(14, 2))
        self.msg = label(prog, "", kind="small", muted=True, anchor="w")
        self.msg.pack(fill="x")
        if auto_model:  # scelta fatta nell'installer: parte subito
            self.after(800, self.start)

    def _render_status(self) -> None:
        for w in self.status_box.winfo_children():
            w.destroy()
        st = self.config.ai_components_status()
        gpu_ok = (self.config.resolve_ai_path("runtime/llama-vulkan") / "llama-server.exe").is_file()
        emb_ok = self.config.resolve_ai_path(EMBED_MODEL_PATH).is_file()
        rows = [(t("Runtime llama.cpp (CPU)"), st["runtime_ok"]),
                (t("Runtime GPU (Vulkan)"), gpu_ok),
                (t("Modello principale · {n}", n=st["model"].name if st["model"] else "-"), st["model_ok"]),
                (t("Modello leggero · {n}", n=st["fallback"].name if st["fallback"] else "-"), st["fallback_ok"]),
                (t("Ricerca semantica"), emb_ok)]
        for text, ok in rows:
            r = ctk.CTkFrame(self.status_box, fg_color="transparent")
            r.pack(fill="x", padx=12, pady=3)
            label(r, text).pack(side="left")
            Chip(r, t("installato") if ok else t("non installato"), "success" if ok else "neutral").pack(side="right")

    def _progress_cb(self, frac: Optional[float], msg: str) -> None:
        def ui():
            try:
                if frac is None:
                    if self.progress.cget("mode") != "indeterminate":
                        self.progress.configure(mode="indeterminate")
                        self.progress.start()
                else:
                    if self.progress.cget("mode") != "determinate":
                        self.progress.stop()
                        self.progress.configure(mode="determinate")
                    self.progress.set(frac)
                self.msg.configure(text=msg)
            except tk.TclError:
                pass
        try:
            self.after(0, ui)
        except (tk.TclError, RuntimeError):
            pass

    def start(self) -> None:
        if self._busy:
            return
        self._busy = True
        self.install_btn.configure(state="disabled")
        self.close_btn.configure(text=t("Annulla"))
        self._installer = AIInstaller(self.config.data_root)
        threading.Thread(target=self._worker, args=(self.model_var.get(), self.gpu_var.get(), self.emb_var.get()),
                         daemon=True, name="ai-install").start()

    def _worker(self, model: str, gpu: bool, emb: bool) -> None:
        try:
            assert self._installer is not None
            self._installer.install(model, self._progress_cb, gpu=gpu, embeddings=emb)
            self.after(0, self._done_ok)
        except InstallCancelled:
            self.after(0, lambda: self._done_err(None))
        except Exception as exc:  # noqa: BLE001
            LOG.exception("AI install failed")
            self.after(0, lambda e=exc: self._done_err(e))

    def _done_ok(self) -> None:
        self._busy = False
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.set(1)
        self.msg.configure(text=t("Installazione completata."))
        self.close_btn.configure(text=t("Chiudi"))
        self.install_btn.configure(state="normal")
        self._render_status()
        if self.on_installed:
            self.on_installed()

    def _done_err(self, exc: Optional[BaseException]) -> None:
        self._busy = False
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.set(0)
        self.install_btn.configure(state="normal")
        self.close_btn.configure(text=t("Chiudi"))
        if exc is None:
            self.msg.configure(text=t("Download annullato."))
            return
        self.msg.configure(text=t("Installazione non riuscita."))
        messagebox.showerror(t("Installazione AI non riuscita"),
                             t("{e}\n\nVerifica la connessione a Internet (proxy o firewall aziendali possono "
                               "bloccare GitHub o HuggingFace) e riprova.", e=exc), parent=self)

    def cancel(self) -> None:
        if self._busy and self._installer is not None:
            if messagebox.askyesno(t("Annullare il download?"), t("Il download è in corso. Vuoi annullarlo?"),
                                   parent=self):
                self._installer.cancel()
            return
        super().cancel()
