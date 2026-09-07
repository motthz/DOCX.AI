"""Template preview widget: 260px panel for DOCX/XLSX templates.

- DOCX: paragraph list (heading/text bullets)
- XLSX: sheet cell snapshot (mini table or text dump)
- Fallback: label with filename / path / file size
"""

from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from typing import Optional

try:
    from tkinter import ttk
except Exception:  # noqa: BLE001
    ttk = None  # type: ignore


class TemplatePreview(ttk.Frame if ttk else tk.Frame):
    """Embeddable preview panel. Use `show(template_path)` to display."""

    def __init__(self, master, *, panel_width: int = 260, panel_height: int = 360):
        super().__init__(master, width=panel_width, height=panel_height)
        self.pack_propagate(False)
        self.panel_width = int(panel_width)
        self.panel_height = int(panel_height)
        if ttk is not None:
            self._title = ttk.Label(self, text="Anteprima template", style="Title.H4.TLabel")
        else:
            self._title = tk.Label(self, text="Anteprima template")
        self._title.pack(anchor="w", padx=8, pady=(6, 4))
        # Body canvas
        self._body = tk.Frame(self, bg="#f8fafc", highlightthickness=1, highlightbackground="#cbd5e1")
        self._body.pack(fill="both", expand=True, padx=6, pady=(0, 8))
        self._inner = None
        self._label_status = None
        self._build_empty()

    # --------------------------------------------------------------
    def _build_empty(self) -> None:
        for w in self._body.winfo_children():
            w.destroy()
        self._inner = tk.Frame(self._body, bg="#f8fafc")
        self._inner.pack(fill="both", expand=True, padx=6, pady=6)
        if ttk is not None:
            ttk.Label(self._inner, text="Nessun template selezionato",
                      style="Subtle.TLabel").pack(pady=20)
        else:
            tk.Label(self._inner, text="Nessun template selezionato",
                     bg="#f8fafc").pack(pady=20)

    # --------------------------------------------------------------
    def show(self, template_path) -> None:
        path = Path(template_path) if template_path is not None else None
        if path is None or not path.is_file():
            self._build_empty()
            return
        try:
            size_kb = max(1, int(path.stat().st_size / 1024))
        except OSError:
            size_kb = 0
        for w in self._body.winfo_children():
            w.destroy()
        self._inner = tk.Frame(self._body, bg="#ffffff")
        self._inner.pack(fill="both", expand=True, padx=4, pady=4)
        header = tk.Label(self._inner,
                          text=f"{path.name}\n({size_kb} KB)",
                          bg="#ffffff", fg="#1e293b", justify="left", anchor="w")
        header.pack(fill="x", padx=6, pady=(6, 2))
        sep = tk.Frame(self._inner, bg="#e2e8f0", height=1)
        sep.pack(fill="x", pady=4)
        ext = path.suffix.lower()
        try:
            if ext == ".docx":
                self._render_docx(path)
            elif ext == ".xlsx":
                self._render_xlsx(path)
            else:
                tk.Label(self._inner,
                         text=f"Anteprima non disponibile per {ext}",
                         bg="#ffffff", fg="#64748b").pack(padx=8, pady=10)
        except Exception as exc:  # noqa: BLE001
            tk.Label(self._inner,
                     text=f"Errore anteprima:\n{str(exc)[:240]}",
                     bg="#ffffff", fg="#b91c1c", justify="left").pack(padx=8, pady=10)

    # --------------------------------------------------------------
    def _render_docx(self, path: Path) -> None:
        try:
            from ..parsers.docx_parser import load_document, extract_text
            doc = load_document(path)
            ext = extract_text(doc)
            if ttk is not None:
                sb = ttk.Scrollbar(self._inner, orient="vertical")
            else:
                sb = tk.Scrollbar(self._inner, orient="vertical")
            txt = tk.Text(self._inner, height=14, wrap="word",
                          bg="#ffffff", fg="#1e293b", relief="flat",
                          yscrollcommand=sb.set,
                          font=("Segoe UI", 9))
            sb.configure(command=txt.yview)
            sb.pack(side="right", fill="y")
            txt.pack(side="left", fill="both", expand=True, padx=(4, 0))
            for para in ext.paragraphs[:60]:
                text = para.text.strip()
                if not text:
                    continue
                level = para.style_name.lower().startswith("heading")
                if level:
                    txt.insert("end", text + "\n", ("h",))
                else:
                    txt.insert("end", text + "\n")
            try:
                txt.tag_configure("h", font=("Segoe UI", 9, "bold"))
            except Exception:  # noqa: BLE001
                pass
            txt.configure(state="disabled")
        except Exception as exc:  # noqa: BLE001
            tk.Label(self._inner, text=f"Impossibile leggere DOCX: {exc}",
                     bg="#ffffff", fg="#b91c1c", wraplength=220,
                     justify="left").pack(padx=6, pady=6)

    def _render_xlsx(self, path: Path) -> None:
        try:
            from ..parsers.xlsx_parser import load_workbook_safe, extract_text
            wb = load_workbook_safe(path)
            ext = extract_text(wb)
            if ttk is not None:
                tv = ttk.Treeview(self._inner, columns=("sheet", "cells"), show="headings", height=10)
                tv.heading("sheet", text="Foglio")
                tv.heading("cells", text="Prima riga / celle")
                tv.column("sheet", width=70, anchor="w")
                tv.column("cells", width=160, anchor="w")
            else:
                tv = None
            if tv is None:
                # Fallback text
                lines = []
                for sheet_name, rows in list(ext.sheets.items())[:4]:
                    lines.append(f"--- {sheet_name} ---")
                    for r in rows[:8]:
                        cells = [("" if v is None else str(v)) for v in r[:6]]
                        lines.append(" | ".join(cells))
                msg = "\n".join(lines)
                tk.Label(self._inner, text=msg, bg="#ffffff", fg="#1e293b",
                         justify="left", anchor="w", wraplength=230).pack(padx=6, pady=6, anchor="w")
                return
            sb = ttk.Scrollbar(self._inner, orient="vertical", command=tv.yview)
            tv.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            tv.pack(side="left", fill="both", expand=True, padx=(4, 0))
            for sheet_name, rows in list(ext.sheets.items())[:10]:
                first_row = rows[0] if rows else []
                cells_str = " | ".join("" if v is None else str(v) for v in first_row[:6])
                tv.insert("", "end", values=(sheet_name, cells_str))
        except Exception as exc:  # noqa: BLE001
            tk.Label(self._inner, text=f"Impossibile leggere XLSX: {exc}",
                     bg="#ffffff", fg="#b91c1c", wraplength=220,
                     justify="left").pack(padx=6, pady=6)
