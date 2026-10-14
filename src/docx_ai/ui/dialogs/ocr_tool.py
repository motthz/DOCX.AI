"""Estrazione testo da foto/PDF scansionati con l'OCR integrato di Windows."""

from __future__ import annotations

import threading
from pathlib import Path
from tkinter import filedialog
from typing import Any

import customtkinter as ctk

from ..design import C, font
from ..i18n import t
from ..widgets import button, label
from .base import Dialog


def _hard_to_read(text: str) -> bool:
    """Lettura OCR con poche parole riconoscibili (tipico del corsivo)."""
    from ...docintelligence.ocr_service import _COMMON_WORDS
    words = [w.strip(".,;:()\"'").lower() for w in text.split() if not w.startswith("===")]
    if len(words) < 8:
        return False
    return sum(w in _COMMON_WORDS for w in words) / len(words) < 0.08


def _page_images(path: Path, tmp: Path):
    """Immagini da leggere: il file stesso, o le immagini delle pagine di un PDF scansionato."""
    if path.suffix.lower() != ".pdf":
        return [path]
    from pypdf import PdfReader
    from ...docintelligence.pdf_parser import PDFParser
    out = []
    for i, page in enumerate(PdfReader(str(path)).pages):
        imgs = [im for im in PDFParser._extract_page_images(PDFParser(), page) if im is not None]
        if imgs:
            big = max(imgs, key=lambda im: im.width * im.height)
            q = tmp / f"pagina_{i + 1}.png"
            big.convert("RGB").save(q)
            out.append(q)
    if not out:
        raise RuntimeError(t("Nel PDF non ci sono pagine scansionate da leggere."))
    return out


class OcrDialog(Dialog):
    def __init__(self, win: Any):
        super().__init__(win.root, t("Testo da scansione (OCR)"), width=860, height=660, icon_name="scan-text",
                         subtitle=t("Usa il motore OCR di Windows (nessun download). Le pagine storte vengono raddrizzate."))
        self.win = win
        top = ctk.CTkFrame(self.body, fg_color="transparent")
        top.pack(fill="x")
        button(top, t("Scegli immagini o PDF…"), self.pick, kind="primary", icon_name="images").pack(side="left")
        button(top, t("Lettura avanzata (scrittura a mano)…"), self.pick_advanced, icon_name="sparkles").pack(
            side="left", padx=(8, 0))
        self.status = label(top, "", muted=True)
        self.status.pack(side="left", padx=10)
        self.out = ctk.CTkTextbox(self.body, wrap="word", font=font("body"), border_width=1,
                                  border_color=C["border"])
        self.out.pack(fill="both", expand=True, pady=(10, 0))
        button(self.footer, t("Copia testo"), self.copy, icon_name="copy").pack(side="right", padx=(8, 20), pady=12)
        button(self.footer, t("Usa come informazioni del documento"), self.to_report, icon_name="file-text").pack(
            side="right", pady=12)
        button(self.footer, t("Chiudi"), self.close, kind="ghost").pack(side="right", padx=8, pady=12)

    def pick(self) -> None:
        files = filedialog.askopenfilenames(parent=self, filetypes=[(t("Immagini e PDF"), "*.png *.jpg *.jpeg *.pdf")])
        if not files:
            return
        self.status.configure(text=t("Riconoscimento in corso…"))
        threading.Thread(target=self._work, args=([Path(f) for f in files],), daemon=True).start()

    def _work(self, files) -> None:
        loader = self.win.app.doc_loader
        parts = []
        for f in files:
            try:
                doc = loader.load_file(f, run_ocr=True)
                text = getattr(doc, "full_text", "") or getattr(doc, "text", "")
            except Exception as exc:  # noqa: BLE001
                text = t("[errore: {e}]", e=exc)
            parts.append(f"=== {f.name} ===\n{text.strip()}\n")
        self.after(0, lambda: self._done("\n".join(parts)))

    def _done(self, text: str, *, advanced: bool = False) -> None:
        msg = t("Completato")
        if not advanced and _hard_to_read(text):
            msg = t("Testo poco leggibile: per la scrittura a mano prova la «Lettura avanzata».")
        self.status.configure(text=msg)
        self.out.delete("1.0", "end")
        self.out.insert("1.0", text)

    def pick_advanced(self) -> None:
        from tkinter import messagebox
        reader = self.win.ai.handwriting
        if not reader.available():
            if messagebox.askyesno(
                    t("Lettura avanzata"),
                    t("La lettura avanzata usa un modello AI che legge anche il corsivo (~1,5 GB, da scaricare "
                      "una sola volta). Aprire Componenti AI per installarlo?"), parent=self):
                self.win.open_ai_setup()
            return
        files = filedialog.askopenfilenames(parent=self, filetypes=[(t("Immagini e PDF"), "*.png *.jpg *.jpeg *.pdf")])
        if not files:
            return
        self.status.configure(text=t("Lettura avanzata in corso: sulla CPU può richiedere qualche minuto a pagina…"))
        threading.Thread(target=self._work_advanced, args=([Path(f) for f in files],), daemon=True).start()

    def _work_advanced(self, files) -> None:
        import tempfile
        reader = self.win.ai.handwriting
        parts = []
        tmp = Path(tempfile.mkdtemp(prefix="docx_ai_vision_"))
        try:
            for f in files:
                try:
                    pages = _page_images(f, tmp)
                    texts = []
                    total = len(pages)
                    for i, img in enumerate(pages, 1):
                        self.after(0, lambda n=f.name, i=i, k=total: self.status.configure(
                            text=t("Lettura avanzata: {f} (pagina {i}/{k})…", f=n, i=i, k=k)))
                        texts.append(reader.read(img))
                    text = "\n\n".join(texts)
                except Exception as exc:  # noqa: BLE001
                    text = t("[errore: {e}]", e=exc)
                parts.append(f"=== {f.name} ===\n{text.strip()}\n")
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
        self.after(0, lambda: self._done("\n".join(parts), advanced=True))

    def copy(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.out.get("1.0", "end"))
        self.win.toast(t("Testo copiato."), "success")

    def to_report(self) -> None:
        import re
        page = self.win.page("report")
        text = "\n".join(ln for ln in self.out.get("1.0", "end").splitlines()
                         if not re.fullmatch(r"=== .+ ===", ln.strip())).strip()
        if page.mode.get() != t("Scrivi le informazioni"):
            page.mode.set(t("Scrivi le informazioni"))
            page._switch_mode(t("Scrivi le informazioni"))
        existing = page._text()
        page._hide_placeholder()
        # si aggiunge al testo gia' scritto (prima lo sostituiva senza chiedere)
        page.desc.insert("end", ("\n\n" if existing else "") + text)
        page._update_quality()
        self.close()
        self.win.show_page("report")
