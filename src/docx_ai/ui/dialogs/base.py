"""Base per le finestre di dialogo: modale, centrata, tema e titlebar coerenti."""

from __future__ import annotations

import tkinter as tk
from typing import Optional

import customtkinter as ctk

from ..assets import apply_window_icon
from ..design import C, font
from ..icons import icon


class Dialog(ctk.CTkToplevel):
    def __init__(self, master: tk.Misc, title: str, *, width: int = 720, height: int = 560,
                 subtitle: str = "", icon_name: Optional[str] = None, modal: bool = True,
                 resizable: bool = True):
        super().__init__(master)
        # niente withdraw(): CTkToplevel ricolora la titlebar nascondendo e
        # rimostrando la finestra e ripristinerebbe lo stato "nascosto"
        self.title(title)
        self.configure(fg_color=C["bg"])
        self.resizable(resizable, resizable)
        self.transient(master.winfo_toplevel())
        self.result = None
        apply_window_icon(self)  # CTkToplevel reimposta l'icona: la riapplichiamo
        self.after(250, lambda: apply_window_icon(self))

        head = ctk.CTkFrame(self, fg_color=C["surface"], corner_radius=0, border_width=0)
        head.pack(fill="x")
        inner = ctk.CTkFrame(head, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=14)
        if icon_name:
            ctk.CTkLabel(inner, text="", image=icon(icon_name, 26, "primary"), width=44, height=44,
                         corner_radius=22, fg_color=C["primary_soft"]).pack(side="left", padx=(0, 12))
        tt = ctk.CTkFrame(inner, fg_color="transparent")
        tt.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(tt, text=title, font=font("h3"), text_color=C["text"], anchor="w").pack(fill="x")
        if subtitle:
            ctk.CTkLabel(tt, text=subtitle, font=font("small"), text_color=C["text_muted"], anchor="w",
                         justify="left", wraplength=width - 140).pack(fill="x")
        ctk.CTkFrame(self, height=1, fg_color=C["border"]).pack(fill="x")

        self.footer = ctk.CTkFrame(self, fg_color=C["surface"], corner_radius=0, height=60)
        self.footer.pack(fill="x", side="bottom")
        ctk.CTkFrame(self, height=1, fg_color=C["border"]).pack(fill="x", side="bottom")
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=20, pady=16)

        self.bind("<Escape>", lambda e: self.cancel())
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self._size = (width, height)
        self._modal = modal
        self.after(10, self._present)

    def _present(self) -> None:
        w, h = self._size
        scale = ctk.ScalingTracker.get_window_scaling(self) if hasattr(ctk, "ScalingTracker") else 1.0
        parent = self.master.winfo_toplevel()
        parent.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        rw, rh = int(w * scale), int(h * scale)
        rw, rh = min(rw, sw - 40), min(rh, sh - 80)
        x = max(0, px + (pw - rw) // 2)
        y = max(0, py + (ph - rh) // 3)
        self.geometry(f"{int(rw / scale)}x{int(rh / scale)}+{x}+{y}")
        self.after(300, self._ensure_visible)

    def _ensure_visible(self) -> None:
        try:
            if self.state() == "withdrawn":
                self.deiconify()
            self.lift()
            self.focus_force()
        except tk.TclError:
            return
        if self._modal:
            try:
                self.grab_set()
            except tk.TclError:
                self.after(100, self._regrab)

    def _regrab(self) -> None:
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def _revert_withdraw_after_windows_set_titlebar_color(self) -> None:
        # CustomTkinter su Windows mostra la finestra ~200 ms dopo la creazione: se nel
        # frattempo e' stata chiusa (es. l'editor passa alla vista semplificata) la
        # chiamata fallirebbe con "bad window path name".
        try:
            if self.winfo_exists():
                super()._revert_withdraw_after_windows_set_titlebar_color()  # type: ignore[misc]
        except tk.TclError:
            pass

    def cancel(self) -> None:
        self.result = None
        self.close()

    def close(self) -> None:
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()

    def wait(self):
        self.master.wait_window(self)
        return self.result
