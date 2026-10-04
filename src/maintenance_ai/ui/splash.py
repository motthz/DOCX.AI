"""Splash animato all'avvio: logo, anello rotante e dissolvenza.

L'inizializzazione (config, database, servizi) gira in un thread mentre lo
splash anima nel thread principale; poi lo splash si chiude in dissolvenza.
"""

from __future__ import annotations

import threading
import time
import tkinter as tk
from typing import Any, Callable, Optional

from .assets import asset_path

BG = "#0f172a"


def run_with_splash(work: Callable[[], Any], *, subtitle: str = "Avvio in corso…") -> Any:
    """Esegue ``work`` in background mostrando lo splash; ritorna il suo risultato
    (o rilancia la sua eccezione)."""
    result: dict = {}

    def target() -> None:
        try:
            result["value"] = work()
        except BaseException as exc:  # noqa: BLE001
            result["error"] = exc

    th = threading.Thread(target=target, daemon=True, name="bootstrap")
    try:
        root = tk.Tk()
    except tk.TclError:
        th.start()
        th.join()
        if "error" in result:
            raise result["error"]
        return result.get("value")
    root.overrideredirect(True)
    root.configure(bg=BG)
    w, h = 380, 300
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 3}")
    root.attributes("-topmost", True)
    try:
        root.attributes("-alpha", 0.0)
    except tk.TclError:
        pass
    c = tk.Canvas(root, width=w, height=h, bg=BG, highlightthickness=0)
    c.pack()
    logo: Optional[tk.PhotoImage] = None
    try:
        logo = tk.PhotoImage(file=str(asset_path("logo.png"))).subsample(2, 2)
        c.create_image(w // 2, 118, image=logo)
    except tk.TclError:
        pass
    arc = c.create_arc(w // 2 - 86, 118 - 86, w // 2 + 86, 118 + 86, start=90, extent=70,
                       style="arc", outline="#34d399", width=4)
    c.create_text(w // 2, 236, text="MaintenanceAI", fill="#ffffff", font=("Segoe UI", 18, "bold"))
    c.create_text(w // 2, 266, text=subtitle, fill="#94a3b8", font=("Segoe UI", 10))
    start = time.monotonic()
    state = {"alpha": 0.0, "closing": False}

    def tick() -> None:
        t = time.monotonic() - start
        c.itemconfigure(arc, start=(90 - t * 300) % 360, extent=60 + 50 * abs(((t * 0.8) % 2) - 1))
        a = state["alpha"]
        if state["closing"]:
            a = max(0.0, a - 0.12)
        elif a < 1.0:
            a = min(1.0, a + 0.08)
        state["alpha"] = a
        try:
            root.attributes("-alpha", a)
        except tk.TclError:
            pass
        if not th.is_alive() and not state["closing"] and t > 0.6:
            state["closing"] = True
        if state["closing"] and a <= 0.0:
            root.destroy()
            return
        root.after(16, tick)

    th.start()
    root.after(0, tick)
    root.mainloop()
    th.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")
