"""Guida in-app: visualizza docs/guida-utente.md (o user-guide.md in inglese).

Markdown supportato: titoli, grassetto, `codice`, elenchi, citazioni, tabelle,
immagini. Indice laterale cliccabile e ricerca nel testo.
"""

from __future__ import annotations

import re
import sys
import tkinter as tk
from pathlib import Path
from typing import Any, List, Optional

import customtkinter as ctk
from PIL import Image, ImageTk

from ..design import C, col
from ..i18n import current_language, t
from ..widgets import button
from .base import Dialog


def docs_dir() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    cands = [Path(meipass) / "docs"] if meipass else []
    cands.append(Path(__file__).resolve().parents[4] / "docs")
    return next((c for c in cands if c.is_dir()), cands[-1])


class GuideDialog(Dialog):
    def __init__(self, master: tk.Misc, win: Any = None):
        super().__init__(master, t("Guida"), width=1180, height=860, icon_name="circle-help", modal=False)
        name = "user-guide.md" if current_language() == "en-US" else "guida-utente.md"
        self.path = docs_dir() / name
        self._images: List[ImageTk.PhotoImage] = []

        self.body.columnconfigure(1, weight=1)
        self.body.rowconfigure(1, weight=1)
        self.search = ctk.CTkEntry(self.body, placeholder_text=t("Cerca nella guida…"), height=32)
        self.search.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.search.bind("<Return>", lambda e: self.find(), add="+")
        self.toc = ctk.CTkScrollableFrame(self.body, width=240, fg_color=C["surface"])
        self.toc.grid(row=1, column=0, sticky="ns", padx=(0, 10))
        frame = ctk.CTkFrame(self.body, fg_color=C["surface"], corner_radius=10)
        frame.grid(row=1, column=1, sticky="nsew")
        self.text = tk.Text(frame, wrap="word", relief="flat", bd=0, padx=28, pady=20, bg=col("surface"),
                            fg=col("text"), font=("Segoe UI", 11), spacing1=2, spacing3=4, cursor="arrow",
                            highlightthickness=0)
        sb = ctk.CTkScrollbar(frame, command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(fill="both", expand=True)
        self._tags()
        self.render()
        self.text.configure(state="disabled")
        button(self.footer, t("Chiudi"), self.close).pack(side="right", padx=20, pady=12)
        self.bind("<Control-f>", lambda e: self.search.focus_set())

    def _tags(self) -> None:
        tx = self.text
        tx.tag_configure("h1", font=("Segoe UI", 20, "bold"), spacing1=6, spacing3=10)
        tx.tag_configure("h2", font=("Segoe UI", 15, "bold"), spacing1=16, spacing3=6, foreground=col("link"))
        tx.tag_configure("h3", font=("Segoe UI", 12, "bold"), spacing1=10, spacing3=4)
        tx.tag_configure("b", font=("Segoe UI", 11, "bold"))
        tx.tag_configure("code", font=("Cascadia Mono", 10), background=col("surface_alt"))
        tx.tag_configure("quote", lmargin1=18, lmargin2=18, foreground=col("text_muted"),
                         background=col("info_soft"))
        tx.tag_configure("li", lmargin1=18, lmargin2=34)
        tx.tag_configure("table", font=("Cascadia Mono", 10), lmargin1=10)
        tx.tag_configure("hit", background=col("warning_soft"))

    def _inline(self, line: str, base: tuple = ()) -> None:
        for part in re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", line):
            if part.startswith("**") and part.endswith("**"):
                self.text.insert("end", part[2:-2], base + ("b",))
            elif part.startswith("`") and part.endswith("`"):
                self.text.insert("end", part[1:-1], base + ("code",))
            elif part:
                self.text.insert("end", part, base)

    def _image(self, rel: str) -> None:
        p = self.path.parent / rel
        try:
            with Image.open(p) as im:
                im = im.copy()
            im.thumbnail((760, 760))
            img = ImageTk.PhotoImage(im)
            self._images.append(img)
            self.text.image_create("end", image=img, padx=4, pady=6)
            self.text.insert("end", "\n")
        except OSError:
            pass

    def render(self) -> None:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            self.text.insert("end", t("Guida non trovata."))
            return
        table: List[List[str]] = []

        def flush_table() -> None:
            if not table:
                return
            widths = [max(len(r[i]) if i < len(r) else 0 for r in table) for i in range(len(table[0]))]
            for r in table:
                cells = [(r[i] if i < len(r) else "").ljust(widths[i]) for i in range(len(widths))]
                self.text.insert("end", "  ".join(cells).replace("`", "") + "\n", ("table",))
            self.text.insert("end", "\n")
            table.clear()

        for raw in lines:
            line = raw.rstrip()
            if line.startswith("|"):
                cells = [c.strip() for c in line.strip("|").split("|")]
                if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                    table.append(cells)
                continue
            flush_table()
            img = re.match(r"\s*!\[[^\]]*\]\(([^)]+)\)", line)
            if img:
                self._image(img.group(1))
                continue
            m = re.match(r"^(#{1,3})\s+(.*)", line)
            if m:
                level = len(m.group(1))
                mark = self.text.index("end-1c")
                self.text.insert("end", m.group(2) + "\n", (f"h{level}",))
                if level == 2:
                    ctk.CTkButton(self.toc, text=m.group(2), anchor="w", fg_color="transparent",
                                  hover_color=C["selection"], text_color=C["text"], height=28,
                                  command=lambda i=mark: self.text.yview(i)).pack(fill="x")
                continue
            if line.startswith(">"):
                self._inline(line.lstrip("> ") + "\n", ("quote",))
                continue
            li = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)", line)
            if li:
                bullet = "•  " if li.group(2) in "-*" else li.group(2) + " "
                indent = "      " if li.group(1) else ""
                self.text.insert("end", indent + bullet, ("li",))
                self._inline(li.group(3) + "\n", ("li",))
                continue
            if line.strip():
                self._inline(line.strip() + " ")
            else:
                self.text.insert("end", "\n")
        flush_table()

    def find(self) -> None:
        q = self.search.get().strip()
        self.text.tag_remove("hit", "1.0", "end")
        if not q:
            return
        first: Optional[str] = None
        start = "1.0"
        while True:
            pos = self.text.search(q, start, stopindex="end", nocase=True)
            if not pos:
                break
            end = f"{pos}+{len(q)}c"
            self.text.tag_add("hit", pos, end)
            first = first or pos
            start = end
        if first:
            self.text.see(first)
