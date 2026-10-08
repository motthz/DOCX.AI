"""Rules Editor Dialog: UI "Regole AI".

Editor testuale per regole feature o modulo:
- editor testo;
- Salva;
- Annulla modifiche non salvate;
- indicazione della feature/modulo associato.
"""

from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Dict, Optional

from ..docintelligence import RulesManager, FEATURE_RULES_FILES, GLOBAL_FEATURE_KEY, FEATURE_LABELS_V2
from .theme import COLORS, FONTS, RoundedCard, ModernTheme, apply_theme, center_window


LOG = logging.getLogger(__name__)


FEATURE_LABELS_IT: Dict[str, str] = dict(FEATURE_LABELS_V2)


class RulesEditorDialog(tk.Toplevel):
    def __init__(
        self,
        master,
        rules_manager: RulesManager,
        *,
        feature_key: Optional[str] = None,
        module_name: Optional[str] = None,
        module_folder: Optional[Path] = None,
    ):
        super().__init__(master)
        self.rules_manager = rules_manager
        self.feature_key = feature_key
        self.module_name = module_name
        self.module_folder = module_folder
        if feature_key and module_folder:
            raise ValueError("Non puoi passare sia feature_key che module_folder.")
        if module_folder and not module_name:
            module_name = module_folder.name

        apply_theme(self)
        self.title("Regole AI — DOCX.AI")
        self.geometry("820x740")
        self.minsize(720, 600)
        center_window(self, 820, 740)
        self.transient(master)
        try:
            self.grab_set()
        except Exception:  # noqa: BLE001
            pass

        self._build_ui()
        self._load_initial()
        self._dirty = False
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # --------------------------------------------------------------
    def _build_ui(self) -> None:
        scale = getattr(self, "_dpi_scale", None) or 1.0
        # Gradient header
        hbg = COLORS["header_start"]
        header = tk.Frame(self, bg=hbg)
        header.pack(fill="x")
        tk.Label(header, text="Regole AI", fg="white", bg=hbg, font=FONTS["h1"], anchor="w").pack(
            fill="x", padx=int(24 * scale), pady=(int(16 * scale), 0))
        tk.Label(header, text=self._header_subtitle(), fg=COLORS["text_white_muted"], bg=hbg,
                 font=FONTS["body_sm"], anchor="w", justify="left", wraplength=int(740 * scale)).pack(
            fill="x", padx=int(24 * scale), pady=(2, int(16 * scale)))

        # Buttons (packed BEFORE expand body so they always stay visible inside viewport)
        btns = tk.Frame(self, bg=COLORS["bg"])
        btns.pack(fill="x", side="bottom", padx=int(16 * scale), pady=(10, 12))
        ttk.Button(
            btns, text="🔄  Annulla modifiche", style="Secondary.TButton",
            command=self._on_reload,
        ).pack(side="left")
        ttk.Button(
            btns, text="Chiudi", style="Secondary.TButton",
            command=self._on_close,
        ).pack(side="right", padx=(8, 0))
        ttk.Button(
            btns, text="💾  Salva", style="Primary.TButton",
            command=self._on_save,
        ).pack(side="right")

        body = tk.Frame(self, bg=COLORS["bg"])
        body.pack(fill="both", expand=True, padx=int(16 * scale), pady=(int(12 * scale), 0))

        card = RoundedCard(body, bg=COLORS["card_bg"])
        card.pack(fill="both", expand=True)
        card_inner = card.content

        top_bar = tk.Frame(card_inner, bg=COLORS["card_bg"])
        top_bar.pack(fill="x", pady=(0, 8))
        tk.Label(
            top_bar, text="Istruzioni permanenti per l'AI (una per riga)",
            font=FONTS["body_bold"], fg=COLORS["text"], bg=COLORS["card_bg"], anchor="w",
        ).pack(side="left")
        self.status_var = tk.StringVar(value="— Nessuna modifica —")
        tk.Label(
            top_bar, textvariable=self.status_var,
            font=FONTS["body_sm"], fg=COLORS["muted"], bg=COLORS["card_bg"], anchor="e",
        ).pack(side="right")

        banner = tk.Frame(card_inner, bg=COLORS["danger_50"],
                          highlightthickness=1,
                          highlightbackground=COLORS["danger_300"])
        banner.pack(fill="x", pady=(0, 10))
        tk.Label(
            banner,
            text=(
                "L'AI segue queste regole ogni volta che compila, ma non può modificarle:\n"
                "le cambi solo tu, da questa finestra, premendo Salva."
            ),
            bg=COLORS["danger_50"], fg=COLORS["danger_800"],
            font=FONTS["body_bold"], justify="left", anchor="w",
            padx=12, pady=8,
        ).pack(fill="x")

        text_frame = tk.Frame(card_inner, bg=COLORS["card_bg"])
        text_frame.pack(fill="both", expand=True)
        self.text = tk.Text(
            text_frame, undo=True,
            **ModernTheme.text_widget_kwargs(multiline=True)
        )
        sb = ttk.Scrollbar(text_frame, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.text.bind("<<Modified>>", self._on_modified)

        info_bar = tk.Label(
            card_inner,
            text=(
                "Esempi: «Scrivi le date nel formato gg/mm/aaaa» · «Il reparto va sempre in maiuscolo» · "
                "«Se manca il numero di protocollo lascia il campo vuoto».\n"
                "Priorità: regole dell'app, poi regole della funzione, poi regole del modulo, poi la tua richiesta."
            ),
            font=FONTS["body_sm"], fg=COLORS["muted"], bg=COLORS["card_bg"],
            justify="left", anchor="w", wraplength=int(640 * scale),
        )
        info_bar.pack(fill="x", pady=(8, 0))

        # a capo alla larghezza della finestra: su una riga sola gli esempi allargavano il
        # riquadro oltre il bordo destro (testo e stato "Nessuna modifica" tagliati)
        def _rewrap(e=None):
            if e is not None and e.widget is not self:
                return
            info_bar.configure(wraplength=max(240, self.winfo_width() - int(110 * scale)))
        self.bind("<Configure>", _rewrap, add="+")

    # --------------------------------------------------------------
    def _header_subtitle(self) -> str:
        if self.feature_key:
            fkey = self.feature_key if self.feature_key in FEATURE_RULES_FILES else GLOBAL_FEATURE_KEY
            file_name = FEATURE_RULES_FILES.get(fkey, GLOBAL_FEATURE_KEY + "_rules.txt")
            label = FEATURE_LABELS_IT.get(fkey, FEATURE_LABELS_IT.get(GLOBAL_FEATURE_KEY, self.feature_key))
            return f"Funzione: {label}  ·  {file_name}"
        if self.module_folder:
            return f"Modulo: {self.module_name or self.module_folder.name}  ·  rules.txt"
        return "Seleziona una regola."

    # --------------------------------------------------------------
    def _load_initial(self) -> None:
        try:
            if self.feature_key:
                content = self.rules_manager.read_feature_rules(self.feature_key)
            elif self.module_folder:
                content = self.rules_manager.read_module_rules(self.module_folder)
            else:
                content = ""
        except Exception as exc:  # noqa: BLE001
            LOG.error("Lettura rules fallita: %s", exc)
            content = ""
            messagebox.showwarning(
                "Regole AI",
                f"Impossibile leggere il file rules. Dettaglio: {exc}",
                parent=self,
            )
        self.text.delete("1.0", "end")
        self.text.insert("1.0", content or "")
        self.text.edit_reset()
        self._dirty = False
        self.status_var.set("— Nessuna modifica —")

    def _on_modified(self, _event=None) -> None:
        try:
            if self.text.edit_modified():
                self._dirty = True
                self.status_var.set("⚠  Modifiche non salvate")
                self.text.edit_modified(False)
        except Exception:  # noqa: BLE001
            pass

    def _on_close(self) -> None:
        if self._dirty and not messagebox.askyesno(
                "Regole AI", "Chiudere senza salvare le modifiche alle regole?", parent=self):
            return
        self.destroy()

    def _on_reload(self) -> None:
        if self._dirty:
            if not messagebox.askyesno(
                "Regole AI",
                "Scartare le modifiche non salvate?",
                parent=self,
            ):
                return
        self._load_initial()

    def _on_save(self) -> None:
        content = self.text.get("1.0", "end-1c")
        try:
            if self.feature_key:
                self.rules_manager.user_save_feature_rules(
                    self.feature_key, content, _from_ui=True)
            elif self.module_folder:
                self.rules_manager.user_save_module_rules(
                    self.module_folder, content, _from_ui=True)
            else:
                messagebox.showwarning(
                    "Regole AI", "Nessun file rules associato.", parent=self,
                )
                return
        except Exception as exc:  # noqa: BLE001
            LOG.error("Salvataggio rules fallito: %s", exc)
            messagebox.showerror(
                "Errore salvataggio regole",
                f"Impossibile salvare il file rules.\n\nDettaglio: {exc}",
                parent=self,
            )
            return
        self._dirty = False
        self.status_var.set("✓  Salvato — " + self._now_iso())
        messagebox.showinfo("Regole AI", "Regole salvate correttamente.", parent=self)

    @staticmethod
    def _now_iso() -> str:
        from datetime import datetime
        return datetime.now().strftime("%H:%M:%S")
