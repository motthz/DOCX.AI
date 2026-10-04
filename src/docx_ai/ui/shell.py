"""Finestra principale (CustomTkinter): intestazione, barra laterale moduli,
schede caricate al primo utilizzo, barra di stato, scorciatoie e stato persistente."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from typing import Any, Callable, Dict, List, Optional

import customtkinter as ctk

from ..module_manager import LoadedModule
from . import design
from .assets import apply_window_icon, asset_path
from .design import C, font
from .i18n import install_tk_translator, set_language, t
from .icons import icon
from .widgets import TabBar, Toasts

LOG = logging.getLogger(__name__)

PAGES = [
    ("home", "Home", "house"),
    ("report", "Compila", "file-text"),
    ("history", "Storico", "history"),
    ("module", "Modulo", "package"),
    ("documents", "Documenti AI", "sparkles"),
    ("settings", "Impostazioni", "settings"),
]


def open_path(path: Path) -> bool:
    try:
        p = Path(path)
        if sys.platform == "win32":
            os.startfile(str(p))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(p)])
        return True
    except OSError:
        return False


class MainWindow:
    def __init__(self, app: Any):
        self.app = app
        self.config = app.config
        self.db = app.db
        self.mm = app.module_manager
        self.reports = app.reports
        self.settings = app.settings
        self.ai = app.ai_service

        set_language(self.settings.get("ui.lang"))
        install_tk_translator()
        design.init_ctk()
        design.set_ui_scale(float(self.settings.get("ui.scale")))
        saved = self.settings.get("llm.profile")
        if saved in self.config.available_profiles():
            self.config.set_profile(saved)

        self.root = ctk.CTk()
        design.ensure_font_family(self.root)
        self.root.title("DOCX.AI")
        apply_window_icon(self.root)
        from .theme import ModernTheme
        self.legacy_theme = ModernTheme(self.root, theme_name="light")
        self.mode = design.apply_appearance(self.settings.get("ui.theme"), self.root, self.legacy_theme)
        self.root.configure(fg_color=C["bg"])
        self._restore_geometry()

        self.toasts = Toasts(self.root)
        self.modules: List[LoadedModule] = []
        self.selected: Optional[LoadedModule] = None
        self.pages: Dict[str, Any] = {}
        self.ai_state = "idle"
        self._listeners: Dict[str, List[Callable]] = {}

        self._build_header()
        self._build_statusbar()
        self._build_body()
        self._install_shortcuts()
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.refresh_modules(quiet=True)
        self.show_page(self.settings.get("ui.last_tab") if self.settings.get("ui.last_tab") in
                       dict((k, 1) for k, *_ in PAGES) else "home")
        self.root.after(30000, self._watch_system_theme)

    # ------------------------------------------------------------------ eventi
    def on(self, event: str, cb: Callable) -> None:
        """Pagine e dialoghi si iscrivono a eventi: modules, reports, ai, theme."""
        self._listeners.setdefault(event, []).append(cb)

    def emit(self, event: str, *args: Any) -> None:
        for cb in list(self._listeners.get(event, [])):
            try:
                cb(*args)
            except Exception:  # noqa: BLE001
                LOG.exception("listener %s", event)

    def toast(self, msg: str, kind: str = "info", action=None) -> None:
        self.toasts.show(msg, kind, action=action)

    # ------------------------------------------------------------------ layout
    def _restore_geometry(self) -> None:
        g = self.db.get_setting("ui.geometry")
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        ok = False
        if g and "x" in g and "+" in g:
            try:
                size, x, y = g.split("+")[0], int(g.split("+")[1]), int(g.split("+")[2])
                w, h = (int(v) for v in size.split("x"))
                ok = 600 < w <= sw + 50 and 400 < h <= sh + 50 and -50 < x < sw - 100 and -50 < y < sh - 100
            except (ValueError, IndexError):
                ok = False
        if ok:
            self.root.geometry(g)
        else:
            w, h = min(1320, int(sw * 0.85)), min(860, int(sh * 0.85))
            self.root.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 3)}")
        if self.db.get_setting("ui.zoomed") == "1":
            self.root.after(10, lambda: self.root.state("zoomed"))
        self.root.minsize(1000, 640)

    def _build_header(self) -> None:
        hdr = ctk.CTkFrame(self.root, fg_color=C["header"], corner_radius=0, height=64)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        from PIL import Image
        logo = ctk.CTkImage(Image.open(asset_path("logo.png")), size=(38, 38))
        ctk.CTkLabel(hdr, text="", image=logo).pack(side="left", padx=(18, 10))
        titles = ctk.CTkFrame(hdr, fg_color="transparent")
        titles.pack(side="left")
        ctk.CTkLabel(titles, text="DOCX.AI", font=font("h3"), text_color=C["header_text"]
                     ).pack(anchor="w")
        ctk.CTkLabel(titles, text=t("Compilazione documenti con AI locale · Offline"), font=font("caption"),
                     text_color=C["header_muted"]).pack(anchor="w")

        right = ctk.CTkFrame(hdr, fg_color="transparent")
        right.pack(side="right", padx=14)
        self._theme_btn = ctk.CTkButton(right, text="", width=36, height=34, fg_color="transparent",
                                        hover_color=("#1e293b", "#1e293b"), command=self.cycle_theme,
                                        image=icon(self._theme_icon(), 18, "white"))
        self._theme_btn.pack(side="right", padx=(6, 0))
        ctk.CTkButton(right, text="", width=36, height=34, fg_color="transparent",
                      hover_color=("#1e293b", "#1e293b"), image=icon("circle-help", 18, "white"),
                      command=self.show_help).pack(side="right", padx=(6, 0))
        self._ai_btn = ctk.CTkButton(right, text=t("AI: verifica…"), height=34, corner_radius=17,
                                     fg_color=("#1e293b", "#1e293b"), hover_color=("#334155", "#334155"),
                                     text_color="#ffffff", font=font("small_b"),
                                     image=icon("cpu", 16, "white"), command=self.open_ai_setup)
        self._ai_btn.pack(side="right", padx=(6, 0))
        from .tooltip import bind as tip
        tip(self._ai_btn, t("Stato del motore AI locale. Clic per installare o gestire i componenti."))
        tip(self._theme_btn, t("Tema: chiaro / scuro / come Windows"))

    def _theme_icon(self) -> str:
        pref = self.settings.get("ui.theme")
        return {"light": "sun", "dark": "moon"}.get(pref, "monitor")

    def _build_body(self) -> None:
        self._paned = tk.PanedWindow(self.root, orient="horizontal", sashwidth=6, bd=0,
                                     sashrelief="flat", bg=design.col("border"), showhandle=False)
        self._paned.pack(fill="both", expand=True)
        from .sidebar import Sidebar
        self.sidebar = Sidebar(self._paned, self)
        self.content = ctk.CTkFrame(self._paned, fg_color=C["bg"], corner_radius=0)
        width = int(self.settings.get("ui.sidebar_width"))
        self._paned.add(self.sidebar, minsize=64, width=width, stretch="never")
        self._paned.add(self.content, minsize=560, stretch="always")
        if self.settings.get("ui.sidebar_collapsed"):
            self.root.after(20, lambda: self.sidebar.set_collapsed(True))

        top = ctk.CTkFrame(self.content, fg_color="transparent")
        top.pack(fill="x", padx=24, pady=(12, 0))
        self.tabbar = TabBar(top, [(k, t(lbl), ic) for k, lbl, ic in PAGES], self._on_tab)
        self.tabbar.pack(fill="x")
        self.page_host = ctk.CTkFrame(self.content, fg_color="transparent")
        self.page_host.pack(fill="both", expand=True, padx=24, pady=(10, 14))

    def _build_statusbar(self) -> None:
        bar = ctk.CTkFrame(self.root, fg_color=C["header"], corner_radius=0, height=28)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)
        self._status: Dict[str, ctk.CTkLabel] = {}
        for key in ("ai", "module", "today", "last"):
            lbl = ctk.CTkLabel(bar, text="", font=font("caption"), text_color=C["header_muted"])
            lbl.pack(side="left", padx=(14, 6))
            self._status[key] = lbl
            ctk.CTkFrame(bar, width=1, height=14, fg_color=("#334155", "#334155")).pack(side="left")
        ctk.CTkLabel(bar, text=t("Offline · Locale · Privacy first"), font=font("caption"),
                     text_color=("#64748b", "#64748b")).pack(side="right", padx=14)

    def refresh_status(self) -> None:
        try:
            self._status["ai"].configure(text=self._ai_btn.cget("text"))
            self._status["module"].configure(
                text=t("Modulo: {name}", name=self.selected.name) if self.selected else t("Nessun modulo"))
            self._status["today"].configure(
                text=t("Oggi: {n}", n=self.db.count_reports_on(time.strftime("%Y-%m-%d"))))
            last = self.db.last_report_timestamp(status="exported")
            self._status["last"].configure(text=t("Ultima esportazione: {ts}", ts=time.strftime(
                "%d/%m/%Y %H:%M", time.localtime(last)) if last else "—"))
        except (tk.TclError, KeyError):
            pass

    # ------------------------------------------------------------------ pagine
    def _page_class(self, key: str):
        from .pages import documents, history, home, module, report, settings
        return {"home": home.HomePage, "report": report.ReportPage, "history": history.HistoryPage,
                "module": module.ModulePage, "documents": documents.DocumentsPage,
                "settings": settings.SettingsPage}[key]

    def page(self, key: str):
        """Pagina (creata al primo utilizzo: avvio piu' rapido)."""
        if key not in self.pages:
            t0 = time.perf_counter()
            self.pages[key] = self._page_class(key)(self.page_host, self)
            LOG.info("Pagina %s costruita in %.0f ms", key, (time.perf_counter() - t0) * 1000)
        return self.pages[key]

    def show_page(self, key: str) -> None:
        self.tabbar.select(key)

    def _on_tab(self, key: str) -> None:
        for k, p in self.pages.items():
            if k != key:
                p.pack_forget()
        pg = self.page(key)
        pg.pack(fill="both", expand=True)
        if hasattr(pg, "on_show"):
            pg.on_show()
        self.settings.set("ui.last_tab", key)

    # ------------------------------------------------------------------ moduli
    def refresh_modules(self, *, quiet: bool = False) -> None:
        try:
            self.modules = self.mm.list_modules()
        except Exception as exc:  # noqa: BLE001
            self.toast(t("Errore caricamento moduli: {e}", e=exc), "error")
            self.modules = []
        if self.selected is not None:
            self.selected = next((m for m in self.modules if m.slug == self.selected.slug), None)
        if self.selected is None and self.modules:
            last = self.db.get_setting("ui.last_module")
            self.selected = next((m for m in self.modules if m.slug == last), self.modules[0])
        self.emit("modules")
        self.refresh_status()
        if not quiet:
            self.toast(t("Caricati {n} moduli.", n=len(self.modules)), "info")

    def select_module(self, slug: str) -> None:
        mod = next((m for m in self.modules if m.slug == slug), None)
        if mod is None:
            return
        self.selected = mod
        self.db.set_setting("ui.last_module", slug)
        self.emit("module_selected", mod)
        self.refresh_status()

    def require_module(self) -> Optional[LoadedModule]:
        if self.selected is None:
            self.toast(t("Seleziona o crea prima un modulo nella barra laterale."), "warning")
        return self.selected

    # ------------------------------------------------------------------ AI
    def set_ai_state(self, state: str, text: Optional[str] = None) -> None:
        self.ai_state = state
        colors = {"idle": ("#1e293b", "#1e293b"), "ok": ("#065f46", "#065f46"),
                  "busy": ("#92400e", "#92400e"), "error": ("#7f1d1d", "#7f1d1d")}
        self._ai_btn.configure(fg_color=colors.get(state, colors["idle"]),
                               text=text or self._ai_btn.cget("text"))
        self.refresh_status()

    def refresh_ai(self) -> None:
        if self.ai_state == "busy":
            return
        st = self.config.ai_components_status()
        ready = st["runtime_ok"] and (st["model_ok"] or st["fallback_ok"])
        if not ready:
            self.set_ai_state("error", t("AI non installata"))
        elif self.ai.is_running:
            self.set_ai_state("ok", t("AI attiva"))
        else:
            self.set_ai_state("idle", t("AI pronta"))
        self.emit("ai")

    def open_ai_setup(self, auto_model: Optional[str] = None) -> None:
        from .ai_setup_dialog import AISetupDialog
        AISetupDialog(self.root, self.config, on_installed=self._on_ai_installed, auto_model=auto_model)

    def _installer_ai_request(self) -> Optional[str]:
        """Modello scelto nell'installer (file ai_request.json nella cartella locale dell'app)."""
        import json
        from ..datadir import local_app_dir
        req = local_app_dir() / "ai_request.json"
        if not req.is_file():
            return None
        try:
            model = json.loads(req.read_text(encoding="utf-8")).get("model")
        except (OSError, ValueError):
            model = None
        try:
            req.unlink()
        except OSError:
            pass
        st = self.config.ai_components_status()
        return None if st["runtime_ok"] and (st["model_ok"] or st["fallback_ok"]) else model

    def _on_ai_installed(self) -> None:
        threading.Thread(target=self.ai.reset, daemon=True).start()
        self.refresh_ai()
        self.toast(t("Componenti AI installati: l'AI locale è pronta."), "success")

    # ------------------------------------------------------------------ tema
    def cycle_theme(self) -> None:
        order = ["system", "light", "dark"]
        cur = self.settings.get("ui.theme")
        nxt = order[(order.index(cur) + 1) % 3] if cur in order else "system"
        self.set_theme(nxt)
        labels = {"system": t("come Windows"), "light": t("chiaro"), "dark": t("scuro")}
        self.toast(t("Tema: {name}", name=labels[nxt]), "info")

    def set_theme(self, pref: str) -> None:
        self.settings.set("ui.theme", pref)
        self.mode = design.apply_appearance(pref, self.root, self.legacy_theme)
        self._theme_btn.configure(image=icon(self._theme_icon(), 18, "white"))
        self._paned.configure(bg=design.col("border"))
        self.tabbar.refresh_colors()
        self.emit("theme", self.mode)

    def _watch_system_theme(self) -> None:
        """Con il tema "come Windows" segue i cambi di Windows anche ad app aperta."""
        if self.settings.get("ui.theme") == "system":
            eff = design.effective_mode()
            if eff != self.mode:
                self.set_theme("system")
        self.root.after(30000, self._watch_system_theme)

    # ------------------------------------------------------------------ varie
    def show_help(self):
        from .dialogs.guide import GuideDialog
        return GuideDialog(self.root, self)

    def _install_shortcuts(self) -> None:
        r = self.root
        r.bind_all("<Control-n>", lambda e: self.sidebar.new_module())
        r.bind_all("<Control-e>", lambda e: (self.show_page("report"), self.page("report").generate()))
        r.bind_all("<Control-f>", lambda e: (self.show_page("history"), self.page("history").focus_search()))
        r.bind_all("<Control-comma>", lambda e: self.show_page("settings"))
        r.bind_all("<Control-b>", lambda e: self.sidebar.set_collapsed(not self.sidebar.collapsed))
        r.bind_all("<F5>", lambda e: self.refresh_modules())
        r.bind_all("<F1>", lambda e: self.show_help())
        r.bind_all("<Control-Tab>", lambda e: self._cycle(1))
        r.bind_all("<Control-Shift-Tab>", lambda e: self._cycle(-1))
        for i, (key, *_r) in enumerate(PAGES, 1):
            r.bind_all(f"<Control-Key-{i}>", lambda e, k=key: self.show_page(k))

    def _cycle(self, step: int) -> str:
        keys = [k for k, *_ in PAGES]
        cur = self.tabbar.current or "home"
        self.show_page(keys[(keys.index(cur) + step) % len(keys)])
        return "break"

    def _after_start(self) -> None:
        elapsed = time.perf_counter() - (self.app.started_at or time.perf_counter())
        LOG.info("Avvio completato in %.2f s (finestra pronta)", elapsed)
        if self.app.restore_message:
            messagebox.showinfo(t("Ripristino backup"), self.app.restore_message, parent=self.root)
        self.refresh_ai()
        if self.db.get_setting("first_run_done") is None:
            from .first_run_wizard import FirstRunWizard
            default_ws = self.config.data_root / "workspace"
            lang_before = self.settings.get("ui.lang")
            wiz = FirstRunWizard(self.root, default_workspace=default_ws, config=self.config, db=self.db)
            if not wiz.run():
                return
            # applica davvero le scelte della procedura guidata (lingua, cartella dati)
            from ..datadir import set_configured_data_dir
            chosen = Path(wiz.workspace.get()).expanduser()
            if chosen.name.lower() == "workspace":
                chosen = chosen.parent
            needs_restart = self.settings.get("ui.lang") != lang_before
            if chosen.resolve() != self.config.data_root.resolve():
                set_configured_data_dir(chosen)
                needs_restart = True
            if needs_restart:
                self.restart()
                return
        requested = self._installer_ai_request()
        if requested:
            self.root.after(300, lambda: self.open_ai_setup(auto_model=requested))
        elif not self.settings.get("ui.tour_done"):
            self.root.after(600, self.start_tour)
        st = self.config.ai_components_status()
        if st["runtime_ok"] and (st["model_ok"] or st["fallback_ok"]) and self.settings.get("ai.preload"):
            self.set_ai_state("busy", t("AI: avvio…"))

            def _preload():
                try:
                    self.ai.pipeline()
                finally:
                    self.root.after(0, lambda: (setattr(self, "ai_state", "idle"), self.refresh_ai()))
            threading.Thread(target=_preload, daemon=True, name="ai-preload").start()
        self.app.start_background_tasks()
        self.root.after(60000, self._poll_ai)

    def _poll_ai(self) -> None:
        self.refresh_ai()  # riflette lo spegnimento per inattivita'
        self.root.after(60000, self._poll_ai)

    def start_tour(self) -> None:
        from .tour import Tour
        Tour(self).start()

    def show(self) -> None:
        # Le attivita' di avvio (procedura guidata modale, tour, precaricamento AI)
        # partono solo a mainloop avviato: CTk.mainloop() nasconde e rimostra la
        # finestra per colorare la titlebar e una finestra modale aperta in quel
        # momento resterebbe invisibile.
        self.root.after(0, lambda: self.root.after(400, self._after_start))
        self.root.mainloop()

    def restart(self) -> None:
        """Riavvia l'applicazione (dopo lingua, cartella dati o ripristino backup)."""
        self._restart = True
        self.close(force=True)

    def relaunch_command(self) -> List[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable]
        return [sys.executable, "-m", "docx_ai.main"]

    def close(self, force: bool = False) -> None:
        busy = any(getattr(p, "busy", False) for p in self.pages.values())
        if busy and not force and not messagebox.askyesno(
                t("Elaborazione in corso"),
                t("Un'elaborazione AI è in corso. Chiudere comunque? Il lavoro non salvato andrà perso."),
                parent=self.root):
            return
        try:
            zoomed = self.root.state() == "zoomed"
            self.db.set_setting("ui.zoomed", "1" if zoomed else "0")
            if not zoomed:
                self.db.set_setting("ui.geometry", self.root.geometry())
            if not self.sidebar.collapsed:
                self.settings.set("ui.sidebar_width", self.sidebar.winfo_width())
            self.settings.set("ui.sidebar_collapsed", self.sidebar.collapsed)
        except Exception:  # noqa: BLE001
            pass
        self.root.destroy()
