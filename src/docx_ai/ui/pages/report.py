"""Compila: informazioni dell'utente -> bozza AI -> revisione -> esportazione."""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog
from typing import Any, Dict, List, Optional

import customtkinter as ctk
from PIL import Image

from ...module_manager import LoadedModule
from ..design import C, GAP, font
from ..i18n import t
from ..icons import icon
from ..widgets import Card, Chip, Stepper, autowrap, button, label, section, separator

LOG = logging.getLogger(__name__)
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
DOC_EXT = {".docx", ".xlsx", ".pdf", ".txt", ".jpg", ".jpeg", ".png"}


class ReportPage(ctk.CTkFrame):
    def __init__(self, parent, win: Any):
        super().__init__(parent, fg_color="transparent")
        self.win = win
        self.busy = False
        self.photos: List[Path] = []
        self.doc_files: List[Path] = []
        self._thumbs: List[ctk.CTkImage] = []
        self._token_buf: List[str] = []
        self._flush_after: Optional[str] = None

        self.columnconfigure(0, weight=3, uniform="c")
        self.columnconfigure(1, weight=2, uniform="c")
        self.rowconfigure(0, weight=1)

        # ---------------------------------------------------------- colonna principale
        main = Card(self)
        main.grid(row=0, column=0, sticky="nsew", padx=(0, GAP // 2))
        b = main.body
        top = ctk.CTkFrame(b, fg_color="transparent")
        top.pack(fill="x")
        label(top, t("Nuovo documento"), kind="h2").pack(side="left")
        self.module_chip = Chip(top, "—", "info")
        self.module_chip.pack(side="left", padx=10)

        mrow = ctk.CTkFrame(b, fg_color="transparent")
        mrow.pack(fill="x", pady=(12, 10))
        self.mode = ctk.CTkSegmentedButton(mrow, values=[t("Scrivi le informazioni"), t("Da documenti")],
                                           command=self._switch_mode, font=font("body_b"), height=32)
        self.mode.set(t("Scrivi le informazioni"))
        self.mode.pack(side="left")

        self.input_host = ctk.CTkFrame(b, fg_color="transparent")
        self.input_host.pack(fill="both", expand=True)
        self.desc_frame = ctk.CTkFrame(self.input_host, fg_color="transparent")
        self.desc = ctk.CTkTextbox(self.desc_frame, height=170, wrap="word", font=font("body"),
                                   border_width=1, border_color=C["border"], fg_color=C["surface"])
        self.desc.pack(fill="both", expand=True)
        # lunghezza del testo sotto la casella: in alto veniva tagliata con nomi lunghi o testo ingrandito
        self.quality = Chip(self.desc_frame, "", "neutral")
        self.quality.pack(anchor="e", pady=(6, 0))
        self._placeholder = t("Scrivi tutto ciò che il documento deve contenere, a parole tue. Esempi: «Riunione del 2 ottobre con "
                              "Rossi e Bianchi: approvato il budget di 12.000 €, prossimo incontro il 15» oppure «Il tecnico Rossi ha sostituito la cinghia del compressore C-12, prova ok». "
                              "Più dettagli dai, più campi vengono compilati.")
        self._show_placeholder()
        self.desc.bind("<FocusIn>", lambda e: self._hide_placeholder(), add="+")
        self.desc.bind("<FocusOut>", lambda e: self._show_placeholder(), add="+")
        self.desc.bind("<KeyRelease>", lambda e: self._update_quality(), add="+")

        self.docs_frame = ctk.CTkFrame(self.input_host, fg_color="transparent")
        self.docs_list = ctk.CTkScrollableFrame(self.docs_frame, height=140, fg_color=C["surface_alt"])
        self.docs_list.pack(fill="both", expand=True)
        drow = ctk.CTkFrame(self.docs_frame, fg_color="transparent")
        drow.pack(fill="x", pady=(8, 0))
        button(drow, t("Aggiungi documenti…"), self._add_docs, icon_name="plus").pack(side="left")
        label(drow, t("DOCX, XLSX, PDF, TXT, foto: le scansioni passano dall'OCR"), kind="caption",
              muted=True).pack(side="left", padx=10)
        self.desc_frame.pack(fill="both", expand=True)

        # foto
        separator(b).pack(fill="x", pady=12)
        prow = ctk.CTkFrame(b, fg_color="transparent")
        prow.pack(fill="x")
        label(prow, t("Foto e immagini"), kind="h4").pack(side="left")
        button(prow, t("Fotocamera"), self._open_camera, icon_name="camera", kind="ghost", height=30).pack(
            side="right")
        button(prow, t("Aggiungi foto"), self._add_photos, icon_name="images", kind="ghost", height=30).pack(
            side="right")
        self.photo_strip = ctk.CTkFrame(b, fg_color="transparent", height=84)
        self.photo_strip.pack(fill="x", pady=(6, 0))
        self._render_photos()

        # azione
        separator(b).pack(fill="x", pady=12)
        self.go_btn = button(b, t("Compila con AI   (Ctrl+E)"), self.generate, kind="primary",
                             icon_name="sparkles", height=44)
        self.go_btn.pack(fill="x")
        self.stepper = Stepper(b, [t("Contesto"), t("AI"), t("Verifica fonti"), t("Revisione"), t("Export")])
        self.stepper.pack(anchor="w", pady=(10, 0))
        self.live_toggle = ctk.CTkCheckBox(b, text=t("Mostra l'output dell'AI in tempo reale"),
                                           font=font("small"), command=self._toggle_live)
        self.live_toggle.pack(anchor="w", pady=(8, 0))
        self.live = ctk.CTkTextbox(b, height=110, font=font("mono"), fg_color=C["surface_alt"],
                                   border_width=1, border_color=C["border"], state="disabled")

        # ---------------------------------------------------------- opzioni
        side = Card(self)
        side.grid(row=0, column=1, sticky="nsew", padx=(GAP // 2, 0))
        s = side.body
        label(s, t("Opzioni"), kind="h3").pack(anchor="w")
        st = self.win.settings
        self.use_refs = ctk.BooleanVar(value=True)
        self.use_hist = ctk.BooleanVar(value=True)
        self.grounding = ctk.BooleanVar(value=bool(st.get("ai.grounding")))
        for var, title, sub in (
                (self.use_refs, t("Documenti di riferimento"),
                 t("Procedure e checklist del modulo come istruzioni per l'AI.")),
                (self.use_hist, t("Storico del modulo"),
                 t("I documenti già approvati insegnano forma e terminologia; i dati non vengono copiati.")),
                (self.grounding, t("Controllo delle fonti"),
                 t("Evidenzia in revisione i valori che non compaiono nella descrizione."))):
            box = ctk.CTkFrame(s, fg_color="transparent")
            box.pack(fill="x", pady=(12, 0))
            ctk.CTkSwitch(box, text=title, variable=var, font=font("body_b")).pack(anchor="w")
            autowrap(label(box, sub, kind="small", muted=True, wraplength=300)).pack(fill="x", padx=(46, 0))
        self.grounding.trace_add("write", lambda *a: st.set("ai.grounding", self.grounding.get()))

        section(s, t("Creatività dell'AI"), t("Bassa = più fedele al testo (consigliato).")).pack(
            fill="x", pady=(18, 4))
        self.temp = ctk.DoubleVar(value=0.05)
        trow = ctk.CTkFrame(s, fg_color="transparent")
        trow.pack(fill="x")
        ctk.CTkSlider(trow, from_=0.0, to=0.6, number_of_steps=12, variable=self.temp,
                      command=lambda v: self.temp_lbl.configure(text=f"{float(v):.2f}")).pack(
            side="left", fill="x", expand=True)
        self.temp_lbl = label(trow, "0.05", kind="small_b", width=40)
        self.temp_lbl.pack(side="left", padx=(8, 0))

        separator(s).pack(fill="x", pady=16)
        self.ai_info = autowrap(label(s, "", kind="small", muted=True, wraplength=300))
        self.ai_info.pack(fill="x")

        win.on("module_selected", lambda m: self._update_module())
        win.on("modules", self._update_module)
        win.on("ai", self._update_ai_info)
        self._update_module()
        self._update_ai_info()
        self._update_quality()

    # ------------------------------------------------------------------ UI helpers
    def on_show(self) -> None:
        self._update_module()
        self._update_ai_info()

    def _update_module(self) -> None:
        m = self.win.selected
        self.module_chip.set(m.name if m else t("nessun modulo"), "info" if m else "warning")

    def _update_ai_info(self) -> None:
        st = self.win.config.ai_components_status()
        if not (self.win.ai.is_running or self.win.ollama_available) and not (
                st["runtime_ok"] and (st["model_ok"] or st["fallback_ok"])):
            self.ai_info.configure(text=t("AI non installata: la bozza avrà i campi da compilare a mano. "
                                          "Installa l'AI dal pulsante in alto."))
        else:
            self.ai_info.configure(text=t("AI locale pronta. I dati non lasciano questo PC."))

    def _text(self) -> str:
        txt = self.desc.get("1.0", "end").strip()
        return "" if txt == self._placeholder else txt

    def _show_placeholder(self) -> None:
        if not self.desc.get("1.0", "end").strip():
            self.desc.insert("1.0", self._placeholder)
            self.desc.configure(text_color=C["text_faint"])

    def _hide_placeholder(self) -> None:
        if self.desc.get("1.0", "end").strip() == self._placeholder:
            self.desc.delete("1.0", "end")
        self.desc.configure(text_color=C["text"])

    def _update_quality(self) -> None:
        n = len(self._text())
        if n < 20:
            self.quality.set(t("{n} caratteri · troppo breve", n=n), "danger")
        elif n < 80:
            self.quality.set(t("{n} caratteri · sufficiente", n=n), "warning")
        else:
            self.quality.set(t("{n} caratteri · buona", n=n), "success")

    def _switch_mode(self, value: str) -> None:
        docs = value == t("Da documenti")
        (self.desc_frame if docs else self.docs_frame).pack_forget()
        (self.docs_frame if docs else self.desc_frame).pack(fill="both", expand=True)
        if docs:
            self._render_docs()
        self._update_quality()
        self.go_btn.configure(text=t("Compila da documenti") if docs else t("Compila con AI   (Ctrl+E)"))

    def _toggle_live(self) -> None:
        if self.live_toggle.get():
            self.live.pack(fill="both", expand=True, pady=(6, 0))
        else:
            self.live.pack_forget()

    # ------------------------------------------------------------------ documenti
    def _add_docs(self) -> None:
        files = filedialog.askopenfilenames(parent=self.win.root, title=t("Documenti sorgente"),
                                            filetypes=[(t("Supportati"), "*.docx *.xlsx *.pdf *.txt *.jpg *.jpeg *.png")])
        for f in files:
            p = Path(f)
            if p.suffix.lower() in DOC_EXT and p not in self.doc_files:
                self.doc_files.append(p)
        self._render_docs()

    def _render_docs(self) -> None:
        for w in self.docs_list.winfo_children():
            w.destroy()
        if not self.doc_files:
            label(self.docs_list, t("Nessun documento: aggiungi file, tabelle o scansioni da cui leggere i dati."),
                  muted=True).pack(pady=12)
        for p in self.doc_files:
            r = ctk.CTkFrame(self.docs_list, fg_color="transparent")
            r.pack(fill="x", pady=1)
            ctk.CTkLabel(r, text="", image=icon("file-text", 16)).pack(side="left", padx=6)
            label(r, p.name).pack(side="left", fill="x", expand=True)
            ctk.CTkButton(r, text="", image=icon("x", 14), width=26, height=26, fg_color="transparent",
                          hover_color=C["selection"],
                          command=lambda q=p: (self.doc_files.remove(q), self._render_docs())).pack(side="right")

    # ------------------------------------------------------------------ foto
    def _add_photos(self) -> None:
        files = filedialog.askopenfilenames(parent=self.win.root, title=t("Foto e immagini"),
                                            filetypes=[(t("Immagini"), "*.jpg *.jpeg *.png *.webp *.bmp")])
        for f in files:
            p = Path(f)
            if p.suffix.lower() in IMG_EXT and p not in self.photos:
                self.photos.append(p)
        self._render_photos()

    def _open_camera(self) -> None:
        """Apre l'app Fotocamera di Windows; poi si aggiungono gli scatti (Rullino)."""
        try:
            subprocess.Popen(["explorer.exe", "microsoft.windows.camera:"])
        except OSError:
            self.win.toast(t("Impossibile aprire la Fotocamera di Windows."), "error")
            return
        roll = Path.home() / "Pictures" / "Camera Roll"
        self.win.toast(t("Scatta le foto, poi aggiungile dal Rullino."), "info",
                       action=(t("Aggiungi dal Rullino"), lambda: self._add_from(roll)))

    def _add_from(self, folder: Path) -> None:
        files = filedialog.askopenfilenames(parent=self.win.root, initialdir=str(folder) if folder.is_dir() else None,
                                            filetypes=[(t("Immagini"), "*.jpg *.jpeg *.png")])
        self.photos.extend(Path(f) for f in files if Path(f) not in self.photos)
        self._render_photos()

    def _render_photos(self) -> None:
        for w in self.photo_strip.winfo_children():
            w.destroy()
        self._thumbs.clear()
        if not self.photos:
            label(self.photo_strip, t("Nessuna foto: verranno inserite nel PDF del documento."), kind="small",
                  muted=True).pack(anchor="w")
            return
        for p in self.photos:
            try:
                with Image.open(p) as im:
                    im.thumbnail((160, 160))
                    img = ctk.CTkImage(im.copy(), size=(72, 72))
            except Exception:  # noqa: BLE001
                continue
            self._thumbs.append(img)
            cell = ctk.CTkFrame(self.photo_strip, fg_color="transparent")
            cell.pack(side="left", padx=(0, 8))
            ctk.CTkLabel(cell, text="", image=img).pack()
            ctk.CTkButton(cell, text=t("Rimuovi"), height=20, width=72, font=font("caption"),
                          fg_color="transparent", text_color=C["danger"], hover_color=C["danger_soft"],
                          command=lambda q=p: (self.photos.remove(q), self._render_photos())).pack()

    # ------------------------------------------------------------------ flusso
    def generate(self) -> None:
        if self.busy:
            return
        if self.mode.get() == t("Da documenti"):
            self._compile_from_docs()
            return
        mod = self.win.require_module()
        if mod is None:
            return
        desc = self._text()
        if len(desc) < 10:
            self.win.toast(t("Scrivi almeno una frase con le informazioni (10 caratteri)."), "warning")
            self.desc.focus_set()
            return
        self.busy = True
        self.go_btn.configure(state="disabled", text=t("Elaborazione in corso…"))
        self.stepper.reset()
        self.stepper.set(0, "run")
        self.win.set_ai_state("busy", t("AI al lavoro…"))
        self.live.configure(state="normal")
        self.live.delete("1.0", "end")
        self.live.configure(state="disabled")
        args = dict(use_references=self.use_refs.get(), use_history=self.use_hist.get(),
                    temperature=float(self.temp.get()))
        threading.Thread(target=self._worker, args=(mod, desc, args), daemon=True, name="extract").start()

    def _worker(self, mod: LoadedModule, desc: str, args: Dict[str, Any]) -> None:
        def prog(step, total, msg):
            self.after(0, lambda: self._progress(step))

        try:
            outcome = self.win.reports.create_draft(mod, desc, on_progress=prog, on_token=self._on_token, **args)
            sources = [desc]
            if args["use_references"]:
                try:
                    sources += [txt for _n, txt in self.win.app.context.parse_reference_documents(mod)]
                except Exception:  # noqa: BLE001
                    pass
            if self.photos and outcome.report_id:
                self.win.reports.add_photos(outcome.report_id, self.photos)
            self.after(0, lambda: self._after_draft(mod, outcome, desc, sources))
        except Exception as exc:  # noqa: BLE001
            LOG.exception("estrazione")
            self.after(0, lambda e=exc: self._fail(str(e)))

    def _progress(self, step: int) -> None:
        if step >= 2:
            self.stepper.set(0, "ok")
            self.stepper.set(1, "run")

    def _on_token(self, delta: str) -> None:
        self._token_buf.append(delta)
        if self._flush_after is None:
            try:
                self._flush_after = self.after(80, self._flush_tokens)
            except RuntimeError:
                pass

    def _flush_tokens(self) -> None:
        self._flush_after = None
        text, self._token_buf = "".join(self._token_buf), []
        if not text:
            return
        self.live.configure(state="normal")
        self.live.insert("end", text)
        self.live.see("end")
        self.live.configure(state="disabled")

    def _fail(self, msg: str) -> None:
        self.busy = False
        self.stepper.set(1, "err")
        self.go_btn.configure(state="normal", text=t("Compila con AI   (Ctrl+E)"))
        self.win.set_ai_state("error", t("AI: errore"))
        self.win.toast(t("Estrazione non riuscita: {e}", e=msg), "error")
        self.after(4000, self.win.refresh_ai)

    def _after_draft(self, mod, outcome, desc: str, sources: List[str]) -> None:
        self.busy = False
        self.go_btn.configure(state="normal", text=t("Compila con AI   (Ctrl+E)"))
        self.win.ai_state = "idle"  # altrimenti refresh_ai lascerebbe "AI al lavoro…" per sempre
        self.win.refresh_ai()
        if not outcome.data:
            self._fail(outcome.error or t("dati non validi"))
            return
        self.stepper.set(1, "ok")
        self.stepper.set(2, "ok")
        self.stepper.set(3, "run")
        fixes = getattr(outcome, "corrections", None) or []
        if fixes:
            LOG.info("Controllo dei fatti: %s", "; ".join(fixes))
            fields = sorted({f.split(":", 1)[0].split("[", 1)[0] for f in fixes})
            self.win.toast(t("Controllo automatico: {n} valori corretti, tolti o completati dal programma ({f}). "
                             "Verificali nella revisione.", n=len(fixes), f=", ".join(fields[:4])), "warning")
        if getattr(outcome, "ai_failed", ""):
            self.win.toast(t("L'AI non è riuscita a compilare il modulo: completa i campi nella revisione."),
                           "warning")
        elif not self.win.ai.is_real_ai:
            self.win.toast(t("AI non installata: compila i campi a mano nella revisione."), "warning",
                           action=(t("Installa AI"), self.win.open_ai_setup))
        self.win.emit("reports")
        self.open_review(mod, outcome.report_id, outcome.data, desc, sources,
                         evidence=getattr(outcome, "evidence", None) or {})

    def open_review(self, mod: LoadedModule, report_id: int, data: Dict[str, Any], desc: str,
                    sources: List[str], *, notes: str = "", evidence: Optional[Dict[str, str]] = None) -> None:
        from ..dialogs.review import ReviewDialog
        dlg = ReviewDialog(self.win, mod, report_id, data, description=desc, sources=sources,
                           grounding=bool(self.grounding.get()), notes=notes, evidence=evidence)
        approved = dlg.wait()
        if approved is None:
            self.stepper.set(3, "todo")
            self.win.toast(t("Revisione chiusa: la bozza resta salvata in Home e nello Storico."), "info")
            self.win.emit("reports")
            return
        self.stepper.set(3, "ok")
        self.stepper.set(4, "run")
        self.finalize(mod, report_id, approved)

    def finalize(self, mod: LoadedModule, report_id: int, approved: Dict[str, Any]) -> None:
        self.busy = True

        def work():
            try:
                self.win.reports.approve_draft(report_id, approved)
                json_p, doc_p, pdf_p = self.win.reports.finalize_exports(report_id, mod)
                self.after(0, lambda: self._done(mod, json_p, doc_p, pdf_p))
            except Exception as exc:  # noqa: BLE001
                LOG.exception("export")
                self.after(0, lambda e=exc: (setattr(self, "busy", False), self.stepper.set(4, "err"),
                                             self.win.toast(t("Esportazione non riuscita: {e}", e=e), "error")))
        threading.Thread(target=work, daemon=True, name="export").start()

    def _done(self, mod, json_p: Path, doc_p: Optional[Path], pdf_p: Path) -> None:
        self.busy = False
        self.stepper.set(4, "ok")
        self.photos.clear()
        self._render_photos()
        self.win.emit("reports")
        self.win.refresh_status()
        from ..dialogs.export_done import ExportDoneDialog
        ExportDoneDialog(self.win, mod, json_p, doc_p, pdf_p, on_new=self.reset)

    def reset(self) -> None:
        self.desc.delete("1.0", "end")
        self._show_placeholder()
        self.stepper.reset()
        self._update_quality()
        self.win.show_page("report")

    def resume_draft(self, report_id: int) -> None:
        row = self.win.db.get_report(report_id)
        if row is None:
            return
        mod = next((m for m in self.win.modules if m.id == row.get("module_id")), None)
        if mod is None:
            self.win.toast(t("Il modulo di questa bozza non esiste più."), "error")
            return
        try:
            data = json.loads(row.get("draft_json") or row.get("final_json") or "{}")
        except ValueError:
            data = {}
        self.win.select_module(mod.slug)
        self.win.show_page("report")
        self.stepper.reset()
        for i in range(3):
            self.stepper.set(i, "ok")
        self.stepper.set(3, "run")
        desc = row.get("input_description") or ""
        self.open_review(mod, report_id, data, desc, [desc], notes=row.get("review_notes") or "")

    def _compile_from_docs(self) -> None:
        mod = self.win.require_module()
        if mod is None:
            return
        if not self.doc_files:
            self.win.toast(t("Aggiungi almeno un documento."), "warning")
            return
        from ..document_dialogs import SmartFillDialog
        try:
            dlg = SmartFillDialog(self.win.root, self.win.app.smart_fill_engine, self.win.app.rules_manager,
                                  self.win.mm, self.win.config.exports_root())
            dlg.on_use = self._use_documents_data
            dlg.preload(list(self.doc_files), mod.slug)
        except Exception as exc:  # noqa: BLE001
            self.win.toast(t("Errore: {e}", e=exc), "error")

    def _use_documents_data(self, mod: LoadedModule, data: Dict[str, Any], sources: List[str]) -> None:
        """Dati letti dai documenti -> bozza nello Storico -> revisione -> esportazione."""
        names = ", ".join(p.name for p in self.doc_files)
        desc = t("Compilato dai documenti: {f}", f=names)
        rid = self.win.db.create_report(module_id=mod.id, module_version=mod.version, status="draft",
                                        input_description=desc,
                                        draft_json=json.dumps(data, ensure_ascii=False), source="documents")
        self.win.emit("reports")
        self.stepper.reset()
        for i in range(3):
            self.stepper.set(i, "ok")
        self.stepper.set(3, "run")
        self.open_review(mod, rid, data, desc, sources)


__all__ = ["ReportPage", "tk"]
