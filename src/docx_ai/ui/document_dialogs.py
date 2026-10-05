"""Dialogs for the 4 AI document features:
- DocumentCreationDialog
- DocumentModificationDialog
- AuditDialog
- SmartFillDialog
"""

from __future__ import annotations

import logging
import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, Dict, List, Optional, Set

from ..docintelligence import (
    AuditEngine,
    AuditReport,
    DocumentGenerator,
    DocumentLoader,
    DocumentModifier,
    ModifiedDocument,
    ModificationRequest,
    RulesManager,
    SmartFillEngine,
    SmartFillResult,
    SourceRef,
)
from ..module_manager import LoadedModule, ModuleManager
from .theme import COLORS, FONTS, RoundedCard, ModernTheme, apply_theme, center_window


LOG = logging.getLogger(__name__)


# =============================================================
# HELPERS
# =============================================================
class _BackgroundWorker(tk.Toplevel):
    """Modal progress dialog with cancel button.

    Runs `target(*args, **kwargs)` in a background thread.
    Returns via callback(result, error).
    """

    def __init__(self, master, title: str, message: str,
                 target: Callable,
                 on_done: Callable,
                 on_progress: Optional[Callable[[str], None]] = None,
                 use_thread: bool = True,
                 args: tuple = (), kwargs: Optional[dict] = None):
        super().__init__(master)
        self.title(title)
        self.geometry("460x180")
        self.resizable(False, False)
        center_window(self, 460, 180)
        self.transient(master)
        try: self.grab_set()
        except Exception: pass
        apply_theme(self)
        self._result = None
        self._error: Optional[Exception] = None
        self._on_done = on_done
        self._on_progress_cb = on_progress
        self._cancelled = False

        frame = tk.Frame(self, bg=COLORS["card_bg"])
        frame.pack(fill="both", expand=True, padx=18, pady=18)
        tk.Label(frame, text=title, font=FONTS["h2"], fg=COLORS["text"],
                 bg=COLORS["card_bg"], anchor="w").pack(fill="x")
        self.status_var = tk.StringVar(value=message)
        tk.Label(frame, textvariable=self.status_var, font=FONTS["body"],
                 fg=COLORS["muted"], bg=COLORS["card_bg"],
                 anchor="w", justify="left", wraplength=400).pack(fill="x", pady=(10, 14))
        self.pb = ttk.Progressbar(frame, mode="indeterminate")
        self.pb.pack(fill="x", pady=(0, 14))
        self.pb.start(12)
        ttk.Button(frame, text="Annulla", style="Secondary.TButton",
                   command=self._on_cancel).pack(side="right")
        self.update()

        self._target = target
        self._args = args or ()
        self._kwargs = kwargs or {}
        if use_thread:
            t = threading.Thread(target=self._run, daemon=True)
            t.start()
        else:
            self.after(100, self._run)

    def progress(self, msg: str) -> None:
        try:
            self.status_var.set(msg)
            if self._on_progress_cb:
                try: self._on_progress_cb(msg)
                except Exception: pass
            self.update_idletasks()
        except Exception:  # noqa: BLE001
            pass

    def _on_cancel(self) -> None:
        self._cancelled = True
        self.status_var.set("Annullamento…")
        self.update()

    def _run(self) -> None:
        try:
            def progress_cb(m: str) -> None:
                if not self.winfo_exists():
                    return
                self.after(0, lambda: self.progress(m))
            self._kwargs["progress_cb"] = progress_cb
            self._result = self._target(*self._args, **self._kwargs)
        except Exception as exc:  # noqa: BLE001
            LOG.exception("Worker error")
            self._error = exc
        self.after(0, self._finish)

    def _finish(self) -> None:
        try:
            self.pb.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            res = self._result
            err = self._error
            self.destroy()
            self._on_done(res, err)
        except Exception as exc:  # noqa: BLE001
            # un errore qui lasciava la finestra "in elaborazione" senza nessun messaggio
            LOG.exception("Completamento operazione")
            try:
                messagebox.showerror("Errore", f"Operazione non completata: {exc}", parent=self.master)
            except Exception:  # noqa: BLE001
                pass


# =============================================================
# 1) DOCUMENT CREATION
# =============================================================
def _solid_header(win: tk.Misc, title: str, subtitle: str) -> tk.Frame:
    """Intestazione dei dialoghi documenti (tinta unita, testo che va a capo)."""
    bg = COLORS["header_start"]
    header = tk.Frame(win, bg=bg)
    header.pack(fill="x")
    tk.Label(header, text=title, fg="white", bg=bg, font=FONTS["h1"], anchor="w").pack(
        fill="x", padx=24, pady=(14, 0))
    tk.Label(header, text=subtitle, fg=COLORS["text_white_muted"], bg=bg, font=FONTS["body_sm"],
             anchor="w", justify="left", wraplength=860).pack(fill="x", padx=24, pady=(2, 14))
    return header


class DocumentCreationDialog(tk.Toplevel):
    def __init__(self, master,
                 generator: DocumentGenerator,
                 rules_manager: RulesManager,
                 output_dir_root: Path,
                 modules: Optional[ModuleManager] = None):
        super().__init__(master)
        self.generator = generator
        self.rules_manager = rules_manager
        self.output_dir_root = output_dir_root
        self.modules = modules
        self._last_result: Optional[tuple] = None  # (GeneratedDocument, docs)

        apply_theme(self)
        self.title("Creazione documento — DOCX.AI")
        self.geometry("900x680")
        self.minsize(820, 600)
        center_window(self, 900, 680)
        self.transient(master)

        self.reference_folder_var = tk.StringVar()
        self.template_var = tk.StringVar()
        self.selected_module_var = tk.StringVar()

        self._build_ui()

    # --------------------------------------------------------------
    def _build_ui(self) -> None:
        _solid_header(self, "Creazione documento",
                      "Crea una bozza di documento aziendale partendo dai riferimenti selezionati.")

        body = tk.Frame(self, bg=COLORS["bg"])
        body.pack(fill="both", expand=True, padx=16, pady=12)

        # --- Input card ---
        in_card = RoundedCard(body, bg=COLORS["card_bg"])
        in_card.pack(fill="x")
        in_f = in_card.content

        row = tk.Frame(in_f, bg=COLORS["card_bg"])
        row.pack(fill="x", pady=2)
        tk.Label(row, text="Cartella riferimenti:", font=FONTS["body_bold"],
                 fg=COLORS["text"], bg=COLORS["card_bg"], width=22, anchor="w").pack(side="left")
        ttk.Entry(row, textvariable=self.reference_folder_var).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(row, text="Sfoglia…", style="Secondary.TButton",
                   command=self._pick_folder).pack(side="left")

        row2 = tk.Frame(in_f, bg=COLORS["card_bg"])
        row2.pack(fill="x", pady=2)
        tk.Label(row2, text="Template DOCX (opzionale):", font=FONTS["body_bold"],
                 fg=COLORS["text"], bg=COLORS["card_bg"], width=22, anchor="w").pack(side="left")
        ttk.Entry(row2, textvariable=self.template_var).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(row2, text="Sfoglia…", style="Secondary.TButton",
                   command=self._pick_template).pack(side="left")

        row3 = tk.Frame(in_f, bg=COLORS["card_bg"])
        row3.pack(fill="x", pady=2)
        tk.Label(row3, text="Modulo (per regole):", font=FONTS["body_bold"],
                 fg=COLORS["text"], bg=COLORS["card_bg"], width=22, anchor="w").pack(side="left")
        self.modules_combo = ttk.Combobox(row3, textvariable=self.selected_module_var,
                                          state="readonly", values=[])
        self.modules_combo.pack(side="left", fill="x", expand=True)
        if self.modules:
            try:
                mods = self.modules.list_modules()
                self.modules_combo["values"] = [m.slug for m in mods]
            except Exception:  # noqa: BLE001
                pass

        tk.Label(in_f, text="Descrizione del documento da creare:", font=FONTS["body_bold"],
                 fg=COLORS["text"], bg=COLORS["card_bg"], anchor="w").pack(
                     fill="x", pady=(10, 4))
        self.desc = tk.Text(in_f, height=6,
                            **ModernTheme.text_widget_kwargs(multiline=True))
        self.desc.pack(fill="x")

        bar = tk.Frame(in_f, bg=COLORS["card_bg"])
        bar.pack(fill="x", pady=(10, 0))
        ttk.Button(bar, text="🧠  Genera bozza", style="Primary.TButton",
                   command=self._on_generate).pack(side="right")

        # --- Output card ---
        out_card = RoundedCard(body, bg=COLORS["card_bg"])
        out_card.pack(fill="both", expand=True, pady=(12, 0))
        of = out_card.content

        nb = ttk.Notebook(of)
        nb.pack(fill="both", expand=True)
        self.tab_anteprima = tk.Frame(nb, bg=COLORS["card_bg"])
        self.tab_fonti = tk.Frame(nb, bg=COLORS["card_bg"])
        self.tab_segnalazioni = tk.Frame(nb, bg=COLORS["card_bg"])
        nb.add(self.tab_anteprima, text=" Anteprima bozza ")
        nb.add(self.tab_fonti, text=" Fonti usate ")
        nb.add(self.tab_segnalazioni, text=" Segnalazioni ")

        self.preview_text = tk.Text(self.tab_anteprima,
                                    **ModernTheme.text_widget_kwargs(multiline=True))
        sb = ttk.Scrollbar(self.tab_anteprima, orient="vertical", command=self.preview_text.yview)
        self.preview_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.preview_text.pack(side="left", fill="both", expand=True)

        self.fonti_text = tk.Text(self.tab_fonti,
                                  **ModernTheme.text_widget_kwargs(multiline=True))
        sb2 = ttk.Scrollbar(self.tab_fonti, orient="vertical", command=self.fonti_text.yview)
        self.fonti_text.configure(yscrollcommand=sb2.set)
        sb2.pack(side="right", fill="y")
        self.fonti_text.pack(side="left", fill="both", expand=True)

        self.segnalazioni_text = tk.Text(self.tab_segnalazioni,
                                         **ModernTheme.text_widget_kwargs(multiline=True))
        sb3 = ttk.Scrollbar(self.tab_segnalazioni, orient="vertical", command=self.segnalazioni_text.yview)
        self.segnalazioni_text.configure(yscrollcommand=sb3.set)
        sb3.pack(side="right", fill="y")
        self.segnalazioni_text.pack(side="left", fill="both", expand=True)

        # Bottom
        bottom = tk.Frame(body, bg=COLORS["bg"])
        bottom.pack(fill="x", side="bottom", pady=(10, 0), before=out_card)
        self.lbl_status = tk.Label(bottom, text="", font=FONTS["body_sm"],
                                   fg=COLORS["muted"], bg=COLORS["bg"], anchor="w")
        self.lbl_status.pack(side="left")
        ttk.Button(bottom, text="Chiudi", style="Secondary.TButton",
                   command=self.destroy).pack(side="right", padx=(8, 0))
        self.btn_save = ttk.Button(bottom, text="💾  Salva versione approvata",
                                   style="Primary.TButton", command=self._on_save,
                                   state="disabled")
        self.btn_save.pack(side="right")

    def _pick_folder(self) -> None:
        f = filedialog.askdirectory(parent=self, title="Seleziona cartella riferimenti")
        if f:
            self.reference_folder_var.set(f)

    def _pick_template(self) -> None:
        f = filedialog.askopenfilename(
            parent=self, title="Seleziona template DOCX",
            filetypes=[("Documenti Word", "*.docx")],
        )
        if f:
            self.template_var.set(f)

    # --------------------------------------------------------------
    def _on_generate(self) -> None:
        desc = self.desc.get("1.0", "end-1c").strip()
        folder = self.reference_folder_var.get().strip()
        template = self.template_var.get().strip()
        if not desc:
            messagebox.showwarning("Input obbligatorio",
                                   "Inserisci una descrizione del documento da creare.",
                                   parent=self)
            return
        if not folder:
            if not messagebox.askyesno(
                "Nessun riferimento",
                "Nessuna cartella riferimenti selezionata. Vuoi procedere comunque?",
                parent=self,
            ):
                return
        mod_slug = self.selected_module_var.get().strip()
        loaded_mod: Optional[LoadedModule] = None
        if mod_slug and self.modules:
            try:
                loaded_mod = self.modules.load_module(mod_slug)
            except Exception:  # noqa: BLE001
                loaded_mod = None

        def _worker(progress_cb=None):
            return self.generator.generate(
                user_description=desc,
                reference_folder=Path(folder) if folder else None,
                reference_files=None,
                template_docx=Path(template) if template else None,
                module=loaded_mod,
                progress_cb=progress_cb or (lambda m: None),
            )

        def _done(res, err):
            if err:
                messagebox.showerror("Errore generazione",
                                     f"Errore durante la generazione:\n\n{err}",
                                     parent=self)
                return
            gen, docs = res
            self._last_result = (gen, docs)
            self.preview_text.delete("1.0", "end")
            self.preview_text.insert("1.0", gen.body_markdown)
            # Highlight [DA DEFINIRE]
            try:
                self.preview_text.tag_configure("missing", background="#fff3cd",
                                                foreground="#856404")
                idx = "1.0"
                while True:
                    idx = self.preview_text.search("[DA DEFINIRE]", idx, nocase=1,
                                                   stopindex="end")
                    if not idx:
                        break
                    end = f"{idx}+12c"
                    self.preview_text.tag_add("missing", idx, end)
                    idx = end
            except Exception:  # noqa: BLE001
                pass
            self.fonti_text.delete("1.0", "end")
            lines = [f"Documenti analizzati: {len(docs)}", ""]
            for d in docs:
                lines.append(f"• {d.path.name}" + (f" — {d.pages_count} pagine" if d.pages_count else ""))
                if d.used_ocr:
                    lines[-1] += " [OCR]"
            lines.append("")
            lines.append("Fonti usate per l'output:")
            if gen.sources:
                for s in gen.sources:
                    lines.append(f"- {s.to_display()}")
            else:
                lines.append("(nessuna tracciata)")
            self.fonti_text.insert("1.0", "\n".join(lines))
            self.segnalazioni_text.delete("1.0", "end")
            if gen.placeholders_found:
                self.segnalazioni_text.insert("1.0",
                    "⚠  Dati mancanti con [DA DEFINIRE] nelle sezioni:\n\n" +
                    "\n".join(f"• {p}" for p in gen.placeholders_found),
                )
            else:
                self.segnalazioni_text.insert(
                    "1.0", "Nessun placeholder [DA DEFINIRE] rilevato.\n\n"
                    "Verifica comunque la bozza prima di approvare."
                )
            self.btn_save.configure(state="normal")
            self.lbl_status.configure(
                text=f"✓  Bozza generata — {len(docs)} documenti analizzati")
        self.lbl_status.configure(text="⏳  Elaborazione in corso…")
        self.btn_save.configure(state="disabled")
        _BackgroundWorker(
            self, "Generazione bozza", "Avvio generazione documento…",
            target=_worker, on_done=_done,
        )

    # --------------------------------------------------------------
    def _on_save(self) -> None:
        if not self._last_result:
            return
        target = filedialog.askdirectory(
            parent=self, title="Salva documento approvato in…",
            initialdir=str(self.output_dir_root),
        )
        if not target:
            return
        gen, docs = self._last_result
        try:
            paths = self.generator.save_approved(gen, Path(target))
        except Exception as exc:  # noqa: BLE001
            LOG.exception("Salvataggio fallito")
            messagebox.showerror("Errore salvataggio", str(exc), parent=self)
            return
        names = ", ".join(p.name for p in paths.values())
        messagebox.showinfo(
            "Salvato",
            f"Documento approvato salvato in:\n{target}\n\nFile creati: {names}",
            parent=self,
        )


# =============================================================
# 2) DOCUMENT MODIFICATION
# =============================================================
class DocumentModificationDialog(tk.Toplevel):
    def __init__(self, master,
                 modifier: DocumentModifier,
                 loader: DocumentLoader,
                 output_dir_root: Path,
                 *,
                 module_manager: Any = None,
                 loaded_module: Any = None):
        super().__init__(master)
        self.modifier = modifier
        self.loader = loader
        self.output_dir_root = output_dir_root
        self.mm = module_manager
        self._loaded_module = loaded_module
        self._modules_cache: Dict[str, Any] = {}
        self._last_modified: Optional[ModifiedDocument] = None
        self._last_path: Optional[Path] = None
        self._last_doc = None
        self._callig_handwriting_fonts: List[str] = []

        apply_theme(self)
        self.title("Modifica documento — DOCX.AI")
        self.geometry("1000x720")
        self.minsize(900, 640)
        center_window(self, 1000, 720)
        self.transient(master)

        self.source_var = tk.StringVar()
        self.module_var = tk.StringVar()
        self.req_template_var = tk.StringVar(value="— Template richieste —")
        self.callig_enable_var = tk.BooleanVar(value=False)
        self.callig_font_var = tk.StringVar(value="")
        self._discover_calligraphic_fonts()
        self._build_ui()

    # --------------------------------------------------------------
    @staticmethod
    def _discover_calligraphic_fonts_system() -> List[str]:
        """Cerca font calligrafici nella cartella Fonts di Windows.

        Ritorna lista di nomi font tipo "Segoe Script", "Bradley Hand ITC",
        "Lucida Handwriting", "Vivaldi", "Freestyle Script", "French Script MT",
        "Mistral", "Brush Script MT", "Monotype Corsiva".
        """
        found: List[str] = []
        candidates = [
            "Segoe Script", "Bradley Hand ITC", "Lucida Handwriting",
            "Vivaldi", "Freestyle Script", "French Script MT",
            "Mistral", "Brush Script MT", "Monotype Corsiva",
            "Gigi", "Jokerman", "Comic Sans MS",
        ]
        fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        try:
            available_names: Set[str] = set()
            if fonts_dir.is_dir():
                for f in fonts_dir.iterdir():
                    if f.is_file() and f.suffix.lower() in {".ttf", ".otf", ".ttc"}:
                        stem = f.stem
                        # Nome font approssimato dallo stem
                        base = stem.split(" ")[0] if " " in stem else stem
                        available_names.add(stem)
                        available_names.add(base)
            # Confronta con candidati (match fuzzy)
            for c in candidates:
                if c in available_names:
                    found.append(c)
                    continue
                # Match per stem parziale
                first_word = c.split()[0]
                if any(first_word.lower() in x.lower() for x in available_names):
                    found.append(c)
        except Exception:  # noqa: BLE001
            pass
        # Fallback: sempre Comic Sans MS se esiste (quasi sempre in Windows)
        fallback = [c for c in ["Segoe Script", "Comic Sans MS"] if c not in found]
        found = found + fallback
        # Deduplica preservando ordine
        out: List[str] = []
        for c in found:
            if c not in out:
                out.append(c)
        return out

    def _discover_calligraphic_fonts(self) -> None:
        try:
            self._callig_handwriting_fonts = self._discover_calligraphic_fonts_system()
        except Exception:  # noqa: BLE001
            self._callig_handwriting_fonts = ["Segoe Script", "Comic Sans MS"]
        if self._callig_handwriting_fonts:
            self.callig_font_var.set(self._callig_handwriting_fonts[0])

    def _build_ui(self) -> None:
        _solid_header(self, "Modifica documento",
                      "Carica un documento (o scansione), seleziona il modulo, evidenzia le parti e genera la nuova versione.")

        body = tk.Frame(self, bg=COLORS["bg"])
        body.pack(fill="both", expand=True, padx=16, pady=12)

        in_card = RoundedCard(body, bg=COLORS["card_bg"])
        in_card.pack(fill="x")
        inf = in_card.content

        r1 = tk.Frame(inf, bg=COLORS["card_bg"])
        r1.pack(fill="x", pady=2)
        tk.Label(r1, text="File sorgente:", font=FONTS["body_bold"],
                 fg=COLORS["text"], bg=COLORS["card_bg"], width=18, anchor="w").pack(side="left")
        ttk.Entry(r1, textvariable=self.source_var).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(r1, text="Sfoglia…", style="Secondary.TButton",
                   command=self._pick_source).pack(side="left")
        self.btn_load = ttk.Button(r1, text="Carica", style="Secondary.TButton",
                                   command=self._on_load)
        self.btn_load.pack(side="left", padx=(8, 0))

        # Badge OCR / stato
        self.load_badge_lbl = tk.Label(inf, text="",
                                       bg=COLORS["card_bg"], fg=COLORS["muted"],
                                       font=("Segoe UI", 9, "bold"))
        self.load_badge_lbl.pack(fill="x", pady=(4, 0), anchor="w")

        # Modulo associato (se abbiamo ModuleManager)
        rmod = tk.Frame(inf, bg=COLORS["card_bg"])
        rmod.pack(fill="x", pady=(6, 2))
        tk.Label(rmod, text="📦  Modulo associato:",
                 font=FONTS["body_bold"], fg=COLORS["text"],
                 bg=COLORS["card_bg"], width=18, anchor="w").pack(side="left")
        if self.mm is not None:
            vals: List[str] = []
            try:
                for entry in self.mm.list_modules() or []:
                    slug = entry["slug"] if isinstance(entry, dict) else entry.slug
                    try:
                        mobj = entry if hasattr(entry, "schema") else self.mm.load_module(slug)
                        name = mobj.name if hasattr(mobj, "name") else slug
                        lab = f"{name}  (slug: {slug})"
                        vals.append(lab)
                        self._modules_cache[lab] = mobj
                    except Exception:  # noqa: BLE001
                        continue
            except Exception:  # noqa: BLE001
                vals = []
            self.module_cmb = ttk.Combobox(
                rmod, values=vals, state="readonly",
                textvariable=self.module_var,
            )
            self.module_cmb.pack(side="left", fill="x", expand=True, padx=(0, 8))
            if self._loaded_module is not None:
                try:
                    nm = self._loaded_module.name if hasattr(self._loaded_module, "name") else ""
                    sl = self._loaded_module.slug if hasattr(self._loaded_module, "slug") else ""
                    want = f"{nm}  (slug: {sl})"
                    if want in vals:
                        self.module_var.set(want)
                except Exception:  # noqa: BLE001
                    pass
            if vals and not self.module_var.get():
                self.module_var.set(vals[0])
        else:
            self.module_cmb = ttk.Combobox(
                rmod, values=["(nessun module manager disponibile)"],
                state="disabled",
            )
            self.module_cmb.pack(side="left", fill="x", expand=True, padx=(0, 8))

        tk.Label(inf, text="Richiesta/e di modifica (una per riga):",
                 font=FONTS["body_bold"], fg=COLORS["text"],
                 bg=COLORS["card_bg"], anchor="w").pack(fill="x", pady=(10, 2))
        # Template richieste (suggerimenti veloci per scansioni)
        rtpl_row = tk.Frame(inf, bg=COLORS["card_bg"])
        rtpl_row.pack(fill="x", pady=(0, 4))
        ttk.Label(rtpl_row, text="💡  Template:",
                  background=COLORS["card_bg"], foreground=COLORS["muted"],
                  ).pack(side="left")
        tpl_values = [
            "— Template richieste —",
            "Rimuovi questa scritta a mano: <INSERISCI TESTO>",
            "Aggiungi scritta (stesso stile calligrafico): <INSERISCI TESTO>",
            "Riscrivi come testo formattato, rimuovendo note scritte a mano",
            "Integra le note a mano nel testo del modulo, mantenendo lo schema",
            "Cancella tutti i timbri e le firme a mano, lascia solo testo stampato",
            "Copia i valori dalla tabella di sinistra nei campi corrispondenti",
        ]
        self.req_template_cmb = ttk.Combobox(
            rtpl_row, values=tpl_values, textvariable=self.req_template_var,
            state="readonly", width=54,
        )
        self.req_template_cmb.pack(side="left", fill="x", expand=True, padx=(8, 8))
        ttk.Button(rtpl_row, text="Appendi a richieste",
                   style="Secondary.TButton",
                   command=self._on_append_req_template,
                   ).pack(side="right")

        self.req_text = tk.Text(inf, height=5,
                                **ModernTheme.text_widget_kwargs(multiline=True))
        self.req_text.pack(fill="x")

        bbar = tk.Frame(inf, bg=COLORS["card_bg"])
        bbar.pack(fill="x", pady=(10, 0))
        ttk.Button(bbar, text="🧠  Genera versione modificata",
                   style="Primary.TButton", command=self._on_modify).pack(side="right")

        out_card = RoundedCard(body, bg=COLORS["card_bg"])
        out_card.pack(fill="both", expand=True, pady=(12, 0))
        of = out_card.content
        nb = ttk.Notebook(of)
        nb.pack(fill="both", expand=True)
        self.tab_orig = tk.Frame(nb, bg=COLORS["card_bg"])
        self.tab_new = tk.Frame(nb, bg=COLORS["card_bg"])
        self.tab_diff = tk.Frame(nb, bg=COLORS["card_bg"])
        self.tab_riassunto = tk.Frame(nb, bg=COLORS["card_bg"])
        nb.add(self.tab_orig, text=" 📄 Originale ")
        nb.add(self.tab_new, text=" ✨ Nuova versione ")
        nb.add(self.tab_diff, text=" 🔄 Confronto ")
        nb.add(self.tab_riassunto, text=" 📋 Riassunto modifiche ")

        orig_wrap = tk.Frame(self.tab_orig, bg=COLORS["card_bg"])
        orig_wrap.pack(fill="both", expand=True, padx=6, pady=6)
        self.orig_txt = self._make_text(orig_wrap)
        self.orig_txt.configure(height=14)
        orig_btn_bar = tk.Frame(self.tab_orig, bg=COLORS["card_bg"])
        orig_btn_bar.pack(fill="x", padx=6, pady=(0, 8))
        ttk.Button(orig_btn_bar,
                   text="➕  Aggiungi selezione a richieste di modifica",
                   style="Primary.TButton",
                   command=self._on_add_orig_selection_to_reqs,
                   ).pack(side="right")
        tk.Label(orig_btn_bar,
                 text="Seleziona una porzione di testo sopra, quindi clicca il pulsante per aggiungerla automaticamente alle richieste.",
                 bg=COLORS["card_bg"], fg=COLORS["muted"],
                 font=FONTS["body_sm"]).pack(side="left", fill="x", expand=True)

        self.new_txt = self._make_text(self.tab_new)
        self.diff_txt = self._make_text(self.tab_diff)
        self.riass_txt = self._make_text(self.tab_riassunto)

        bottom = tk.Frame(body, bg=COLORS["bg"])
        bottom.pack(fill="x", side="bottom", pady=(10, 0), before=out_card)

        # Calligrafia export
        callig_row = tk.Frame(bottom, bg=COLORS["bg"])
        callig_row.pack(side="left", fill="x", expand=True)
        ttk.Checkbutton(callig_row, text="✍️  Applica font calligrafico in output:",
                        variable=self.callig_enable_var,
                        ).pack(side="left")
        if self._callig_handwriting_fonts:
            self.callig_cmb = ttk.Combobox(
                callig_row, values=self._callig_handwriting_fonts,
                textvariable=self.callig_font_var, width=22, state="readonly",
            )
        else:
            self.callig_cmb = ttk.Combobox(
                callig_row, values=["(nessun font trovato)"],
                state="disabled", width=22,
            )
        self.callig_cmb.pack(side="left", padx=(8, 0))

        right_btns = tk.Frame(bottom, bg=COLORS["bg"])
        right_btns.pack(side="right")
        self.lbl_status = tk.Label(right_btns, text="", font=FONTS["body_sm"],
                                   fg=COLORS["muted"], bg=COLORS["bg"], anchor="e")
        self.lbl_status.pack(side="left", fill="x", expand=True, padx=(0, 20))
        ttk.Button(right_btns, text="Chiudi", style="Secondary.TButton",
                   command=self.destroy).pack(side="right", padx=(8, 0))
        self.btn_save = ttk.Button(right_btns, text="💾  Salva nuova versione",
                                   style="Primary.TButton", command=self._on_save,
                                   state="disabled")
        self.btn_save.pack(side="right")

    def _on_append_req_template(self) -> None:
        v = self.req_template_var.get() or ""
        if not v or v.startswith("—"):
            return
        try:
            cur = self.req_text.get("1.0", "end-1c") or ""
            sep = "\n" if (cur and not cur.endswith("\n")) else ""
            self.req_text.insert("end", sep + v)
            self.req_text.see("end")
            self.req_text.focus_set()
        except Exception as exc:  # noqa: BLE001
            LOG.warning("Append template richieste fallito: %s", exc)

    def _on_add_orig_selection_to_reqs(self) -> None:
        try:
            sel = self.orig_txt.get("sel.first", "sel.last") or ""
        except Exception:  # noqa: BLE001
            sel = ""
        if not sel:
            messagebox.showinfo(
                "Selezione vuota",
                "Seleziona prima una porzione di testo nel tab 📄 Originale.",
                parent=self,
            )
            return
        # Evidenzia con tag giallo
        try:
            self.orig_txt.tag_remove("hl", "1.0", "end")
        except Exception:  # noqa: BLE001
            pass
        try:
            self.orig_txt.tag_configure("hl", background="#fff59d", foreground="#2b2b2b")
            self.orig_txt.tag_add("hl", "sel.first", "sel.last")
        except Exception:  # noqa: BLE001
            pass
        # Appendi a richieste
        selection_short = sel.strip().replace("\n", " ⏎ ")
        if len(selection_short) > 120:
            selection_short = selection_short[:117] + "…"
        append_line = (
            f"Modifica: \"{selection_short}\" → [DESCRIVI QUI COSA VUOI CAMBIARE]"
        )
        try:
            cur = self.req_text.get("1.0", "end-1c") or ""
            sep = "\n" if (cur and not cur.endswith("\n")) else ""
            self.req_text.insert("end", sep + append_line + "\n")
            self.req_text.see("end")
            # Sposta focus a richieste e seleziona il prompt
            self.req_text.focus_set()
        except Exception as exc:  # noqa: BLE001
            LOG.warning("Aggiungi selezione a richieste fallito: %s", exc)
        self.lbl_status.configure(
            text=f"✓  Aggiunta selezione ({len(sel)} caratteri) alle richieste.")

    @staticmethod
    def _make_text(parent) -> tk.Text:
        t = tk.Text(parent, **ModernTheme.text_widget_kwargs(multiline=True))
        sb = ttk.Scrollbar(parent, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        t.pack(side="left", fill="both", expand=True)
        return t

    def _pick_source(self):
        f = filedialog.askopenfilename(
            parent=self, title="Seleziona documento sorgente",
            filetypes=[
                ("Tutti i formati supportati",
                 "*.pdf *.docx *.xlsx *.txt *.jpg *.jpeg *.png"),
                ("PDF", "*.pdf"), ("Word", "*.docx"), ("Excel", "*.xlsx"),
                ("Testo", "*.txt"), ("Immagini / Scansioni", "*.jpg *.jpeg *.png"),
            ],
        )
        if f:
            self.source_var.set(f)
            self.load_badge_lbl.configure(text="")

    def _on_load(self):
        p = self.source_var.get().strip()
        if not p:
            return
        try:
            self._last_doc = self.loader.load_file(Path(p))
            self._last_path = Path(p)
            pages = self._last_doc.pages_count or 0
            # Rileva se OCR e' stato applicato o file è immagine
            ext = Path(p).suffix.lower().lstrip(".")
            ocr_applied = bool(getattr(self._last_doc, "used_ocr", False))
            is_image = ext in {"jpg", "jpeg", "png"}
            msg_core = f"✓  Caricato: {Path(p).name}" + (f" ({pages} pagine)" if pages else "")
            self.lbl_status.configure(text=msg_core)
            if ocr_applied or is_image:
                badge = (
                    "📷  [OCR applicato] Testo estratto da scansione/immagine — "
                    "controlla che non ci siano errori di battitura prima di modificare."
                )
                self.load_badge_lbl.configure(
                    text=badge, fg=COLORS["success_800"],
                    bg=COLORS["success_50"],
                )
                # Aggiungi un bordo colorato al badge per evidenziare
                try:
                    self.load_badge_lbl.configure(
                        padx=10, pady=6,
                    )
                except Exception:
                    pass
            else:
                self.load_badge_lbl.configure(
                    text="(formato testo/DOCX/XLSX — nessun OCR necessario)",
                    fg=COLORS["muted"], bg=COLORS["card_bg"],
                )
            # Popola tab Originale con il testo caricato
            try:
                orig_text = getattr(self._last_doc, "full_text", None) or ""
                self.orig_txt.delete("1.0", "end")
                self.orig_txt.insert("1.0", orig_text or "(nessun testo estratto)")
            except Exception:  # noqa: BLE001
                pass
        except Exception as exc:  # noqa: BLE001
            LOG.exception("Load fallito")
            messagebox.showerror("Errore", str(exc), parent=self)

    def _on_modify(self):
        if self._last_doc is None:
            messagebox.showwarning("Carica prima", "Carica un documento sorgente.",
                                   parent=self)
            return
        req_raw = self.req_text.get("1.0", "end-1c").strip()
        if not req_raw:
            messagebox.showwarning("Modifica vuota",
                                   "Inserisci almeno una modifica da applicare.",
                                   parent=self)
            return
        requests = [ModificationRequest(instruction=r.strip())
                    for r in req_raw.splitlines() if r.strip()]
        def _worker(progress_cb=None):
            return self.modifier.modify(self._last_doc, requests,
                                        progress_cb=progress_cb or (lambda m: None))
        def _done(res, err):
            if err:
                messagebox.showerror("Errore modifica", str(err), parent=self)
                return
            mod = res
            self._last_modified = mod
            self.new_txt.delete("1.0", "end"); self.new_txt.insert("1.0", mod.modified_text)
            self.riass_txt.delete("1.0", "end")
            lines = ["RIEPILOGO MODIFICHE:"]
            lines += [f"- {c}" for c in mod.changes_summary] or ["(nessuno)"]
            if mod.warnings:
                lines += ["", "AVVERTENZE:"] + [f"• {w}" for w in mod.warnings]
            self.riass_txt.insert("1.0", "\n".join(lines))
            # Diff
            self.diff_txt.delete("1.0", "end")
            try:
                self.diff_txt.tag_configure("rem", background="#f8d7da", foreground="#721c24")
                self.diff_txt.tag_configure("add", background="#d4edda", foreground="#155724")
                for kind, line in mod.diff_lines():
                    tag = "rem" if kind == "-" else "add"
                    prefix = "— " if kind == "-" else "+ "
                    self.diff_txt.insert("end", prefix + line + "\n", tag)
            except Exception:  # noqa: BLE001
                self.diff_txt.insert("1.0", "(confronto non disponibile)")
            self.btn_save.configure(state="normal")
            self.lbl_status.configure(text="✓  Bozza di modifica generata")
        self.lbl_status.configure(text="⏳  Applicazione modifiche…")
        self.btn_save.configure(state="disabled")
        _BackgroundWorker(self, "Modifica documento",
                          "Analisi e applicazione modifiche…",
                          target=_worker, on_done=_done)

    # ================================================================
    # Calligrafia: applica font ai file DOCX/PDF esportati
    # ================================================================
    def _apply_calligraphic_font(self, paths: Dict[str, Path]) -> None:
        """Post-processa i file salvati per applicare il font calligrafico scelto.

        - DOCX: usa python-docx per settare .font.name a tutti i runs.
        - PDF:  usa reportlab (se il percorso e' nostro) oppure pypdf non lo supporta nativamente
          → come best effort per PDF rigeneriamo una mini cover note con il font;
          la richiesta principale è DOCX quindi basta.
        """
        if not self.callig_enable_var.get():
            return
        font_name = (self.callig_font_var.get() or "").strip()
        if not font_name:
            return
        # DOCX
        docx_path = paths.get("docx")
        if docx_path is not None and docx_path.is_file():
            try:
                from docx import Document as DocxDocument  # noqa: F401  (python-docx)
                doc = DocxDocument(str(docx_path))
                changed = 0
                for para in doc.paragraphs:
                    for run in para.runs:
                        try:
                            run.font.name = font_name
                            changed += 1
                        except Exception:  # noqa: BLE001
                            continue
                # Anche tabelle
                try:
                    for table in doc.tables:
                        for row in table.rows:
                            for cell in row.cells:
                                for para in cell.paragraphs:
                                    for run in para.runs:
                                        try:
                                            run.font.name = font_name
                                            changed += 1
                                        except Exception:  # noqa: BLE001
                                            continue
                except Exception:  # noqa: BLE001
                    pass
                # styles default
                try:
                    for s in doc.styles:
                        try:
                            if s.type is not None and hasattr(s, "font") and s.font is not None:
                                s.font.name = font_name
                        except Exception:  # noqa: BLE001
                            continue
                except Exception:  # noqa: BLE001
                    pass
                tmp = docx_path.with_suffix(docx_path.suffix + ".callig.tmp")
                doc.save(str(tmp))
                if tmp.is_file():
                    tmp.replace(docx_path)
                    LOG.info("DOCX %s: applicato font calligrafico %s (%d runs)",
                             docx_path.name, font_name, changed)
                else:
                    LOG.warning("callig write fallito per %s", docx_path)
            except Exception as exc:  # noqa: BLE001
                LOG.warning("Applicazione calligrafico DOCX fallita: %s", exc)

    def _on_save(self):
        if not self._last_modified or not self._last_path:
            return
        target = filedialog.askdirectory(
            parent=self, title="Salva nuova versione in…",
            initialdir=str(self.output_dir_root),
        )
        if not target:
            return
        try:
            paths = self.modifier.save_new_version(
                self._last_path, self._last_modified, Path(target),
            )
        except Exception as exc:  # noqa: BLE001
            LOG.exception("Salvataggio fallito")
            messagebox.showerror("Errore", str(exc), parent=self)
            return
        # Post-process calligrafico (se abilitato)
        try:
            self._apply_calligraphic_font(paths)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("Callig post-process fallito: %s", exc)
        names = ", ".join(p.name for p in paths.values())
        extra = ""
        if self.callig_enable_var.get():
            f = (self.callig_font_var.get() or "").strip() or "(scelto)"
            extra = f"\nFont calligrafico applicato: {f}"
        messagebox.showinfo(
            "Salvato",
            f"Nuova versione salvata in:\n{target}\n\nFile: {names}\n"
            f"L'originale è rimasto intatto.{extra}",
            parent=self,
        )


# =============================================================
# 3) AUDIT
# =============================================================
class AuditDialog(tk.Toplevel):
    def __init__(self, master,
                 audit_engine: AuditEngine,
                 output_dir_root: Path):
        super().__init__(master)
        self.engine = audit_engine
        self.output_dir_root = output_dir_root
        self._last_report: Optional[AuditReport] = None

        apply_theme(self)
        self.title("Audit documenti — DOCX.AI")
        self.geometry("1060x760")
        self.minsize(960, 680)
        center_window(self, 1060, 760)
        self.transient(master)

        self.folder_var = tk.StringVar()
        self.notes_var = tk.StringVar()
        self.sev_filter_var = tk.StringVar(value="TUTTI")

        self._build_ui()

    def _build_ui(self):
        _solid_header(self, "Audit documenti",
                      "Analisi automatica di criticità, incoerenze, tracciabilità.")

        body = tk.Frame(self, bg=COLORS["bg"])
        body.pack(fill="both", expand=True, padx=16, pady=12)

        in_card = RoundedCard(body, bg=COLORS["card_bg"])
        in_card.pack(fill="x")
        inf = in_card.content

        r1 = tk.Frame(inf, bg=COLORS["card_bg"])
        r1.pack(fill="x", pady=2)
        tk.Label(r1, text="Cartella da auditare:", font=FONTS["body_bold"],
                 fg=COLORS["text"], bg=COLORS["card_bg"], width=22, anchor="w").pack(side="left")
        ttk.Entry(r1, textvariable=self.folder_var).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(r1, text="Sfoglia…", style="Secondary.TButton",
                   command=self._pick).pack(side="left")

        r2 = tk.Frame(inf, bg=COLORS["card_bg"])
        r2.pack(fill="x", pady=2)
        tk.Label(r2, text="Note aggiuntive (opzionali):", font=FONTS["body_bold"],
                 fg=COLORS["text"], bg=COLORS["card_bg"], width=22, anchor="w").pack(side="left")
        ttk.Entry(r2, textvariable=self.notes_var).pack(side="left", fill="x", expand=True)

        bbar = tk.Frame(inf, bg=COLORS["card_bg"])
        bbar.pack(fill="x", pady=(8, 0))
        ttk.Button(bbar, text="🧠  Avvia audit", style="Primary.TButton",
                   command=self._on_start).pack(side="right")

        out_card = RoundedCard(body, bg=COLORS["card_bg"])
        out_card.pack(fill="both", expand=True, pady=(12, 0))
        of = out_card.content

        summary_bar = tk.Frame(of, bg=COLORS["card_bg"])
        summary_bar.pack(fill="x", pady=(0, 8))
        self.summary_lbl = tk.Label(summary_bar, text="Nessun audit ancora eseguito.",
                                    font=FONTS["body_bold"], fg=COLORS["text"],
                                    bg=COLORS["card_bg"], anchor="w")
        self.summary_lbl.pack(side="left", fill="x", expand=True)
        tk.Label(summary_bar, text="Filtro gravità:", bg=COLORS["card_bg"],
                 fg=COLORS["muted"], font=FONTS["body_sm"]).pack(side="left", padx=(8, 4))
        values = ["TUTTI", "CRITICO", "ALTO", "MEDIO", "BASSO", "OSSERVAZIONE"]
        self.cmb_sev = ttk.Combobox(summary_bar, values=values, width=16,
                                    textvariable=self.sev_filter_var, state="readonly")
        self.cmb_sev.pack(side="left")
        self.cmb_sev.bind("<<ComboboxSelected>>", lambda e: self._reload_findings())

        nb = ttk.Notebook(of)
        nb.pack(fill="both", expand=True)
        self.tab_findings = tk.Frame(nb, bg=COLORS["card_bg"])
        self.tab_report = tk.Frame(nb, bg=COLORS["card_bg"])
        self.tab_q = tk.Frame(nb, bg=COLORS["card_bg"])
        nb.add(self.tab_findings, text=" Criticità ")
        nb.add(self.tab_report, text=" Report completo ")
        nb.add(self.tab_q, text=" Domande / Coerenze ")

        # Findings: treeview + details
        tv_frame = tk.Frame(self.tab_findings, bg=COLORS["card_bg"])
        tv_frame.pack(fill="both", expand=True)
        cols = ("sev", "title", "conf", "files")
        self.tv = ttk.Treeview(tv_frame, columns=cols, show="headings", height=14)
        self.tv.heading("sev", text="Gravità")
        self.tv.heading("title", text="Titolo")
        self.tv.heading("conf", text="Fiducia")
        self.tv.heading("files", text="File")
        self.tv.column("sev", width=110, anchor="center")
        self.tv.column("title", width=420)
        self.tv.column("conf", width=180)
        self.tv.column("files", width=240)
        self.tv.pack(side="left", fill="both", expand=True)
        sbtv = ttk.Scrollbar(tv_frame, orient="vertical", command=self.tv.yview)
        self.tv.configure(yscrollcommand=sbtv.set)
        sbtv.pack(side="right", fill="y")
        try:
            self.tv.tag_configure("CRITICO", background="#f8d7da")
            self.tv.tag_configure("ALTO", background="#ffe5b4")
            self.tv.tag_configure("MEDIO", background="#fff3cd")
            self.tv.tag_configure("BASSO", background="#d1ecf1")
            self.tv.tag_configure("OSSERVAZIONE", background="#e2e3e5")
        except Exception:  # noqa: BLE001
            pass
        self.details = tk.Text(self.tab_findings, height=12,
                               **ModernTheme.text_widget_kwargs(multiline=True))
        self.details.pack(fill="x", pady=(6, 0))
        self.tv.bind("<<TreeviewSelect>>", self._on_select)

        self.report_txt = self._mk_txt(self.tab_report)
        self.q_txt = self._mk_txt(self.tab_q)

        bottom = tk.Frame(body, bg=COLORS["bg"])
        bottom.pack(fill="x", side="bottom", pady=(10, 0), before=out_card)
        self.lbl_status = tk.Label(bottom, text="", font=FONTS["body_sm"],
                                   fg=COLORS["muted"], bg=COLORS["bg"], anchor="w")
        self.lbl_status.pack(side="left")
        ttk.Button(bottom, text="Chiudi", style="Secondary.TButton",
                   command=self.destroy).pack(side="right", padx=(8, 0))
        self.btn_save = ttk.Button(bottom, text="💾  Esporta report",
                                   style="Primary.TButton", command=self._on_save,
                                   state="disabled")
        self.btn_save.pack(side="right")

    @staticmethod
    def _mk_txt(parent):
        t = tk.Text(parent, **ModernTheme.text_widget_kwargs(multiline=True))
        sb = ttk.Scrollbar(parent, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        t.pack(side="left", fill="both", expand=True)
        return t

    def _pick(self):
        f = filedialog.askdirectory(parent=self, title="Seleziona cartella da auditare")
        if f:
            self.folder_var.set(f)

    def _on_start(self):
        folder = self.folder_var.get().strip()
        if not folder:
            messagebox.showwarning("Cartella mancante",
                                   "Seleziona una cartella da auditare.", parent=self)
            return
        notes = self.notes_var.get().strip()
        def _worker(progress_cb=None):
            return self.engine.audit_folder(
                Path(folder), extra_user_notes=notes or None,
                progress_cb=progress_cb or (lambda m: None),
            )
        def _done(res, err):
            if err:
                messagebox.showerror("Errore audit", str(err), parent=self)
                return
            report, docs = res
            self._last_report = report
            self.summary_lbl.configure(text=report.summary)
            self._reload_findings()
            # Report tab
            self.report_txt.delete("1.0", "end")
            self.report_txt.insert("1.0",
                "\n".join([
                    report.summary,
                    "",
                    f"File analizzati: {', '.join(report.files) if report.files else '(nessun file)'}",
                    "",
                    "=== CONTROLLI EFFETTUATI ===",
                    "\n".join(f"- {c}" for c in report.controls_executed),
                    "",
                    "=== COLLEGAMENTI TRA DOCUMENTI ===",
                    "\n".join(f"- {c}" for c in report.links_between_documents) or "(nessuno)",
                    "",
                ]),
            )
            # Q tab
            qlines = []
            for title, items in [
                ("DOMANDE APERTE", report.open_questions),
                ("INCOERENZE", report.inconsistencies),
                ("DATI MANCANTI", report.missing_data),
                ("PROBLEMI TRACCIABILITÀ", report.traceability_issues),
                ("DOCUMENTI POTENZIALMENTE MANCANTI", report.potentially_missing_documents),
            ]:
                qlines.append(f"=== {title} ===")
                qlines += [f"- {x}" for x in items] or ["(nessuno)"]
                qlines.append("")
            self.q_txt.delete("1.0", "end")
            self.q_txt.insert("1.0", "\n".join(qlines))
            self.btn_save.configure(state="normal")
            self.lbl_status.configure(
                text=f"✓  Audit completato — {len(report.findings)} criticità, "
                     f"{len(docs)} file analizzati.")
        self.lbl_status.configure(text="⏳  Analisi pacchetto documentale…")
        self.btn_save.configure(state="disabled")
        _BackgroundWorker(self, "Audit documenti",
                          "Avvio analisi critica dei documenti…",
                          target=_worker, on_done=_done)

    def _reload_findings(self):
        if self._last_report is None:
            return
        filt = self.sev_filter_var.get()
        self.tv.delete(*self.tv.get_children())
        for i, f in enumerate(self._last_report.findings):
            if filt != "TUTTI" and f.severity != filt:
                continue
            sev = f.severity
            self.tv.insert("", "end", iid=str(i), tags=(sev,),
                           values=(sev, f.title, f.confidence,
                                   ", ".join(f.files[:2])[:80]))
        self.details.delete("1.0", "end")

    def _on_select(self, _event=None):
        sel = self.tv.selection()
        if not sel or self._last_report is None:
            return
        try:
            idx = int(sel[0])
            f = self._last_report.findings[idx]
        except Exception:  # noqa: BLE001
            return
        text = (
            f"TITOLO: {f.title}\n"
            f"GRAVITÀ: {f.severity}   —   FIDUCIA: {f.confidence}\n\n"
            f"DESCRIZIONE:\n{f.description}\n\n"
            f"FILE: {', '.join(f.files)}\n"
            f"POSIZIONI: {'; '.join(f.locations)}\n\n"
            f"EVIDENZA: {f.evidence}\n\n"
            f"MOTIVO: {f.reason}\n\n"
            f"SUGGERIMENTO: {f.suggestion}\n"
        )
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)

    def _on_save(self):
        if self._last_report is None:
            return
        target = filedialog.askdirectory(
            parent=self, title="Esporta report audit in…",
            initialdir=str(self.output_dir_root),
        )
        if not target:
            return
        try:
            paths = self.engine.save_report(self._last_report, Path(target))
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Errore", str(exc), parent=self)
            return
        messagebox.showinfo(
            "Esportato",
            f"Report esportato in:\n{target}\n\n"
            + ", ".join(p.name for p in paths.values()),
            parent=self,
        )


# =============================================================
# 4) SMART FILL
# =============================================================
class SmartFillDialog(tk.Toplevel):
    def __init__(self, master,
                 smart_fill_engine: SmartFillEngine,
                 rules_manager: RulesManager,
                 module_manager: ModuleManager,
                 output_dir_root: Path):
        super().__init__(master)
        self.engine = smart_fill_engine
        self.rules_manager = rules_manager
        self.mm = module_manager
        self.output_dir_root = output_dir_root
        self._last_result: Optional[SmartFillResult] = None
        self._loaded_module: Optional[LoadedModule] = None
        self._module_slug_var = tk.StringVar()
        self._folder_var = tk.StringVar()
        self._files_var: List[str] = []
        self._entries: Dict[str, tk.Widget] = {}

        apply_theme(self)
        self.title("Compilazione smart — DOCX.AI")
        self.geometry("1020x760")
        self.minsize(900, 640)
        center_window(self, 1020, 760)
        self.transient(master)
        self._build_ui()

    def _build_ui(self):
        _solid_header(self, "Compilazione smart da documenti",
                      "Compila il modulo leggendo informazioni da PDF/DOCX/XLSX/immagini.")

        body = tk.Frame(self, bg=COLORS["bg"])
        body.pack(fill="both", expand=True, padx=16, pady=12)

        in_card = RoundedCard(body, bg=COLORS["card_bg"])
        in_card.pack(fill="x")
        inf = in_card.content

        r1 = tk.Frame(inf, bg=COLORS["card_bg"])
        r1.pack(fill="x", pady=2)
        tk.Label(r1, text="Modulo:", font=FONTS["body_bold"],
                 fg=COLORS["text"], bg=COLORS["card_bg"], width=18, anchor="w").pack(side="left")
        mod_vals = []
        try:
            mod_vals = [m.slug for m in self.mm.list_modules()]
        except Exception:  # noqa: BLE001
            pass
        self.mod_combo = ttk.Combobox(r1, values=mod_vals, textvariable=self._module_slug_var,
                                      state="readonly")
        self.mod_combo.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(r1, text="Carica modulo", style="Secondary.TButton",
                   command=self._on_load_module).pack(side="left")

        r2 = tk.Frame(inf, bg=COLORS["card_bg"])
        r2.pack(fill="x", pady=2)
        tk.Label(r2, text="Cartella documenti:", font=FONTS["body_bold"],
                 fg=COLORS["text"], bg=COLORS["card_bg"], width=18, anchor="w").pack(side="left")
        ttk.Entry(r2, textvariable=self._folder_var).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(r2, text="Sfoglia…", style="Secondary.TButton",
                   command=self._pick_folder).pack(side="left")

        r3 = tk.Frame(inf, bg=COLORS["card_bg"])
        r3.pack(fill="x", pady=2)
        tk.Label(r3, text="File aggiuntivi:", font=FONTS["body_bold"],
                 fg=COLORS["text"], bg=COLORS["card_bg"], width=18, anchor="w").pack(side="left")
        self.files_lbl = tk.Label(r3, text="(nessuno)", font=FONTS["body"],
                                  fg=COLORS["muted"], bg=COLORS["card_bg"], anchor="w")
        self.files_lbl.pack(side="left", fill="x", expand=True)
        ttk.Button(r3, text="Scegli file…", style="Secondary.TButton",
                   command=self._pick_files).pack(side="left", padx=(0, 6))
        ttk.Button(r3, text="Pulisci", style="Secondary.TButton",
                   command=self._clear_files).pack(side="left")

        bbar = tk.Frame(inf, bg=COLORS["card_bg"])
        bbar.pack(fill="x", pady=(8, 0))
        ttk.Button(bbar, text="🧠  Compila da documenti",
                   style="Primary.TButton", command=self._on_fill).pack(side="right")

        # Output: fields editor
        out_card = RoundedCard(body, bg=COLORS["card_bg"])
        out_card.pack(fill="both", expand=True, pady=(12, 0))
        of = out_card.content
        tk.Label(of, text="Campi modificabili (puoi correggere prima di approvare):",
                 font=FONTS["body_bold"], fg=COLORS["text"], bg=COLORS["card_bg"],
                 anchor="w").pack(fill="x")
        frm_container = tk.Frame(of, bg=COLORS["card_bg"])
        frm_container.pack(fill="both", expand=True, pady=(4, 0))
        self.fields_canvas = tk.Canvas(frm_container, bg=COLORS["card_bg"],
                                       highlightthickness=0)
        self.fields_sb = ttk.Scrollbar(frm_container, orient="vertical",
                                        command=self.fields_canvas.yview)
        self.fields_canvas.configure(yscrollcommand=self.fields_sb.set)
        self.fields_sb.pack(side="right", fill="y")
        self.fields_canvas.pack(side="left", fill="both", expand=True)
        self.fields_inner = tk.Frame(self.fields_canvas, bg=COLORS["card_bg"])
        self._fields_window = self.fields_canvas.create_window(
            (0, 0), window=self.fields_inner, anchor="nw")
        self.fields_inner.bind(
            "<Configure>",
            lambda e: self.fields_canvas.configure(
                scrollregion=self.fields_canvas.bbox("all")),
        )

        # Bottom
        bottom = tk.Frame(body, bg=COLORS["bg"])
        bottom.pack(fill="x", side="bottom", pady=(10, 0), before=out_card)
        self.lbl_status = tk.Label(bottom, text="", font=FONTS["body_sm"],
                                   fg=COLORS["muted"], bg=COLORS["bg"], anchor="w")
        self.lbl_status.pack(side="left")
        ttk.Button(bottom, text="Chiudi", style="Secondary.TButton",
                   command=self.destroy).pack(side="right", padx=(8, 0))
        self.btn_save = ttk.Button(bottom, text="💾  Salva dati approvati",
                                   style="Primary.TButton", command=self._on_save,
                                   state="disabled")
        self.btn_save.pack(side="right")
        # Dalla pagina Compila: i dati proseguono nel flusso normale (revisione -> documento
        # compilato DOCX/XLSX/PDF nello Storico). Senza questo si salvava solo un JSON.
        self.on_use: Optional[Callable[[Any, Dict[str, Any], List[str]], None]] = None
        self.btn_use = ttk.Button(bottom, text="✓  Crea il documento con questi dati",
                                  style="Primary.TButton", command=self._on_use, state="disabled")

    def _on_use(self) -> None:
        if self._last_result is None or self._loaded_module is None or self.on_use is None:
            return
        data = self._collect_edited_data()
        texts = [d.full_text for d in (self._last_result.documents_used or []) if d.full_text]
        names = [d.path.name for d in (self._last_result.documents_used or [])]
        mod = self._loaded_module
        self.destroy()
        self.on_use(mod, data, texts or names)

    # --------------------------------------------------------------
    def preload(self, files, module_slug: Optional[str] = None) -> None:
        """Precompila file e modulo (avvio dalla pagina Compila) e avvia subito la compilazione."""
        self._files_var = [str(f) for f in files]
        try:
            self.files_lbl.configure(text=f"{len(self._files_var)} file selezionati")
        except Exception:  # noqa: BLE001
            pass
        if module_slug:
            self._module_slug_var.set(module_slug)
            try:
                self._on_load_module()
            except Exception:  # noqa: BLE001
                pass
        if self._files_var and self._loaded_module is not None:
            self.after(300, self._on_fill)

    def _on_load_module(self):
        slug = self._module_slug_var.get().strip()
        if not slug:
            return
        try:
            mod = self.mm.load_module(slug)
            self._loaded_module = mod
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Modulo", str(exc), parent=self)
            return
        self._render_fields(mod.schema or {}, {}, {}, [])

    def _pick_folder(self):
        f = filedialog.askdirectory(parent=self, title="Cartella con documenti sorgente")
        if f:
            self._folder_var.set(f)

    def _pick_files(self):
        fs = filedialog.askopenfilenames(
            parent=self, title="File sorgenti",
            filetypes=[("Tutti i formati",
                        "*.pdf *.docx *.xlsx *.txt *.jpg *.jpeg *.png")],
        )
        if fs:
            self._files_var.extend(list(fs))
            self.files_lbl.configure(text=f"{len(self._files_var)} file selezionati")

    def _clear_files(self):
        self._files_var = []
        self.files_lbl.configure(text="(nessuno)")

    # --------------------------------------------------------------
    def _render_fields(self, schema, data, sources: Dict[str, Any],
                       conflicts: List[Any]):
        for w in self.fields_inner.winfo_children():
            w.destroy()
        self._entries = {}
        props = schema.get("properties", {})
        if not props:
            tk.Label(self.fields_inner,
                     text="(nessun campo definito nello schema del modulo)",
                     font=FONTS["body"], fg=COLORS["muted"],
                     bg=COLORS["card_bg"]).pack(anchor="w")
            return
        for key, spec in props.items():
            prop_type = spec.get("type", "string")
            is_array = prop_type == "array"
            is_obj = prop_type == "object"
            row = tk.Frame(self.fields_inner, bg=COLORS["card_bg"])
            row.pack(fill="x", pady=4)
            # Left: label + conflict badge + sources
            left = tk.Frame(row, bg=COLORS["card_bg"])
            left.pack(side="left", fill="both", expand=True)
            title_row = tk.Frame(left, bg=COLORS["card_bg"])
            title_row.pack(fill="x")
            lbl = tk.Label(title_row, text=key, font=FONTS["body_bold"],
                           fg=COLORS["text"], bg=COLORS["card_bg"], anchor="w")
            lbl.pack(side="left")
            tk.Label(title_row, text=f" [{prop_type}]",
                     font=FONTS["body_sm"], fg=COLORS["muted"],
                     bg=COLORS["card_bg"], anchor="w").pack(side="left")
            # Conflict badge
            has_conflict = any(c.field == key for c in conflicts)
            if has_conflict:
                tk.Label(title_row, text="  ⚠ CONFLITTO  ",
                         background="#dc3545", foreground="white",
                         font=FONTS["body_sm_bold"]).pack(side="left", padx=6)
            desc = spec.get("description")
            if desc:
                tk.Label(left, text=desc, font=FONTS["body_sm"],
                         fg=COLORS["muted"], bg=COLORS["card_bg"],
                         anchor="w", justify="left", wraplength=700).pack(fill="x")
            # Source
            field_src = sources.get(key)
            if field_src:
                txt_srcs = []
                for s in (field_src.sources if hasattr(field_src, "sources") else []):
                    if isinstance(s, SourceRef):
                        txt_srcs.append(s.to_display())
                if txt_srcs:
                    src_lbl = tk.Label(left,
                        text="Fonte: " + " | ".join(txt_srcs[:3]),
                        font=FONTS["body_sm"], fg="#155724", bg="#d4edda",
                        anchor="w", justify="left", wraplength=700, padx=6, pady=2)
                    src_lbl.pack(fill="x", pady=(2, 0))
            if has_conflict:
                for c in conflicts:
                    if c.field == key:
                        alts = "  /  ".join(f"{v}" for v in c.alternatives)
                        tk.Label(left,
                            text=f"Alternative: {alts}",
                            font=FONTS["body_sm"], fg="#721c24", bg="#f8d7da",
                            anchor="w", justify="left", wraplength=700,
                            padx=6, pady=2).pack(fill="x", pady=(2, 0))
            # Right: editor entry
            right = tk.Frame(row, bg=COLORS["card_bg"])
            right.pack(side="right", padx=(10, 0))
            if is_array or is_obj:
                txt = tk.Text(right, height=3, width=52,
                              **ModernTheme.text_widget_kwargs(multiline=True))
                txt.pack()
                import json as _j
                val = data.get(key)
                if val not in (None, ""):
                    if isinstance(val, (dict, list)):
                        try: val = _j.dumps(val, ensure_ascii=False)
                        except Exception: val = str(val)
                    txt.insert("1.0", str(val))
                self._entries[key] = txt
            else:
                var = tk.StringVar()
                ent = ttk.Entry(right, textvariable=var, width=52)
                ent.pack()
                val = data.get(key)
                if val not in (None, ""):
                    var.set(str(val))
                self._entries[key] = var

    def _collect_edited_data(self):
        import json as _j
        out = {}
        if self._loaded_module is None:
            return out
        schema = self._loaded_module.schema or {}
        for k, w in self._entries.items():
            spec = schema.get("properties", {}).get(k, {}) or {}
            t = spec.get("type", "string")
            if isinstance(w, tk.StringVar):
                raw = w.get()
            else:  # Text
                raw = w.get("1.0", "end-1c")
            if t in ("object", "array"):
                try:
                    out[k] = _j.loads(raw) if raw.strip() else ({} if t == "object" else [])
                except Exception:  # noqa: BLE001
                    out[k] = raw
            else:
                out[k] = raw
        return out

    # --------------------------------------------------------------
    def _on_fill(self):
        if self._loaded_module is None:
            messagebox.showwarning("Modulo", "Prima seleziona e carica un modulo.",
                                   parent=self)
            return
        folder = self._folder_var.get().strip()
        if not folder and not self._files_var:
            if not messagebox.askyesno("Nessun documento",
                "Nessuna cartella/file selezionato. Vuoi procedere lo stesso?"):
                return
        module = self._loaded_module
        folder_p = Path(folder) if folder else None
        files_p = [Path(p) for p in self._files_var]
        def _worker(progress_cb=None):
            return self.engine.fill_from_documents(
                module=module,
                reference_folder=folder_p,
                reference_files=files_p or None,
                progress_cb=progress_cb or (lambda m: None),
            )
        def _done(res, err):
            if err:
                messagebox.showerror("Errore compilazione", str(err), parent=self)
                return
            r: SmartFillResult = res
            self._last_result = r
            self._render_fields(module.schema or {}, r.data, r.fields_with_sources,
                                r.conflicts)
            msg = r.summary
            if r.validation_errors:
                msg += f" — {len(r.validation_errors)} errori di validazione"
            self.lbl_status.configure(text="✓  " + msg)
            self.btn_save.configure(state="normal")
            if self.on_use is not None:
                self.btn_use.pack(side="right", padx=(0, 8))
                self.btn_use.configure(state="normal")
        self.lbl_status.configure(text="⏳  Compilazione smart in corso…")
        self.btn_save.configure(state="disabled")
        _BackgroundWorker(self, "Compilazione smart",
                          "Analisi documenti e campi del modulo…",
                          target=_worker, on_done=_done)

    def _on_save(self):
        if self._last_result is None or self._loaded_module is None:
            return
        target = filedialog.askdirectory(
            parent=self, title="Salva dati approvati in…",
            initialdir=str(self.output_dir_root),
        )
        if not target:
            return
        edited = self._collect_edited_data()
        try:
            paths = self.engine.save_approved(
                module=self._loaded_module, result=self._last_result,
                output_dir=Path(target), approved_data=edited,
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Errore", str(exc), parent=self)
            return
        messagebox.showinfo("Salvato",
            f"Dati approvati salvati in:\n{target}\n\n"
            + ", ".join(p.name for p in paths.values()), parent=self)
