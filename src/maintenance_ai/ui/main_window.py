"""Tkinter main window: PREMIUM MaintenanceAI dashboard.

Improvements over the basic version:
- Gradient header canvas (slate 900 → primary 800)
- Rounded cards with soft shadows and accent stripes
- Smooth stepwise hover animations on every clickable surface
- Toast notifications (fade-in / fade-out stacked)
- Keyboard shortcuts: Ctrl+N/E/S/F, Ctrl+Tab, F5, Esc
- Live debounced search on module list (no enter required)
- AI status pulse animation when busy
- Extract button: animated loading spinner + step progress
- Description quality meter (min chars, badging)
- History toolbar with status filters
- Wizard "Nuovo modulo" as selectable RoundedCards
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, Dict, List, Optional, Tuple

LOG = logging.getLogger(__name__)

from ..config import Config
from ..db import Database
from ..llm.llama_server import MockLlamaServer
from ..llm.json_pipeline import JsonPipeline
from ..module_manager import LoadedModule, ModuleManager
from ..security import SecurityError, SecurityLimits
from ..services.context_service import ContextService
from ..services.report_service import DraftOutcome, ReportService
from .help_dialog import run_help
from .review_dialog import ReviewDialog, run_review
from .rules_dialog import RulesEditorDialog, FEATURE_LABELS_IT
from .document_dialogs import (
    DocumentCreationDialog,
    DocumentModificationDialog,
    AuditDialog,
    SmartFillDialog,
)
from .dnd_handler import DragDropHandlerFrame
from .first_run_wizard import FirstRunWizard
from .splash import SplashScreen
from .theme import (
    COLORS,
    FONTS,
    FONT_FAMILY,
    GradientCanvas,
    HoverAnimator,
    ModernTheme,
    RoundedCard,
    ScrollFrame,
    ToastManager,
    apply_theme,
    bind_tooltip,
    center_window,
    darken,
    lighten,
    make_scrollable_frame,
    mix_colors,
)


# ============================================================
# Helpers
# ============================================================

def _tk_text(**overrides: Any) -> dict:
    base = ModernTheme.text_widget_kwargs(multiline=False)
    base.update(overrides)
    return base


def _tk_text_multi(**overrides: Any) -> dict:
    base = ModernTheme.text_widget_kwargs(multiline=True)
    base.update(overrides)
    return base


def _open_folder(path: Path, toast_cb: Optional[Callable] = None) -> bool:
    try:
        p = Path(path)
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(p))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
        return True
    except Exception as e:
        if toast_cb:
            toast_cb(f"Impossibile aprire cartella: {e}", "error", "⚠️")
        return False


_STATUS_STYLES: Dict[str, Tuple[str, str, str]] = {
    "draft":      ("draft",      "Badge.Warning.TLabel", "warning"),
    "review":     ("in revisione", "Badge.Info.TLabel",   "info"),
    "approved":   ("approvato",   "Badge.Neutral.TLabel","neutral"),
    "exported":   ("esportato",   "Badge.Success.TLabel","success"),
    "failed":     ("fallito",     "Badge.Danger.TLabel", "error"),
}

_LOADING_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


# ============================================================
# Main Window
# ============================================================

class MainWindow:
    def __init__(self, config: Config, db: Database, mm: ModuleManager,
                 context: ContextService, reports: ReportService,
                 *,
                 rules_manager=None,
                 doc_generator=None,
                 doc_modifier=None,
                 audit_engine=None,
                 smart_fill_engine=None,
                 doc_loader=None):
        self.config = config
        self.db = db
        self.mm = mm
        self.context = context
        self.reports = reports
        self.rules_manager = rules_manager
        self.doc_generator = doc_generator
        self.doc_modifier = doc_modifier
        self.audit_engine = audit_engine
        self.smart_fill_engine = smart_fill_engine
        self.doc_loader = doc_loader

        self.root = tk.Tk()
        self.root.title("MaintenanceAI")

        # ---- FR9: restore geometry from DB settings, fallback center ----
        self._geom_initial: Optional[str] = None
        try:
            g = db.get_setting("ui.geometry") if hasattr(db, "get_setting") else None
            if g and isinstance(g, str) and "x" in g and "+" in g:
                try:
                    # WxH+X+Y
                    sz, rest = g.split("+", 1)
                    wx, hx = sz.split("x")
                    if 0 < int(wx) < 10000 and 0 < int(hx) < 10000:
                        self._geom_initial = g
                except Exception:  # noqa: BLE001
                    self._geom_initial = None
        except Exception:  # noqa: BLE001
            self._geom_initial = None

        self._dpi_scale = self._detect_dpi_scale()
        try:
            _tk_scale = self.root.tk.call("tk", "scaling")
            if _tk_scale and float(_tk_scale) < self._dpi_scale * 0.9:
                try:
                    self.root.tk.call("tk", "scaling", self._dpi_scale)
                except Exception:
                    pass
        except Exception:
            pass

        # ---- FR3 dark/light theme from DB setting ----
        try:
            saved_theme = (db.get_setting("ui.theme") if hasattr(db, "get_setting") else None) or "light"
        except Exception:  # noqa: BLE001
            saved_theme = "light"
        self.root.withdraw()
        self._theme: ModernTheme = ModernTheme(self.root, theme_name=saved_theme)
        self.root.deiconify()
        root_bg = self._theme.current_colors().get("bg", COLORS["white"])
        try:
            self.root.configure(bg=root_bg)
        except Exception:  # noqa: BLE001
            self.root.configure(bg=COLORS["white"])

        self._hover: HoverAnimator = self._theme.hover
        self._toast: Callable[..., None] = self._theme.toast

        ui_cfg = config.ui_config()
        if self._geom_initial:
            self.root.geometry(self._geom_initial)
            # Ensure out-of-monitor fallback: force min size, do not center blindly
        else:
            base_w = int(ui_cfg.get("window_width", 1240))
            base_h = int(ui_cfg.get("window_height", 820))
            w = int(round(base_w * min(self._dpi_scale, 1.25)))
            h = int(round(base_h * min(self._dpi_scale, 1.25)))
            self.root.geometry(f"{w}x{h}")
            center_window(self.root, w, h)
        min_w = int(round(1080 * min(self._dpi_scale, 1.15)))
        min_h = int(round(700 * min(self._dpi_scale, 1.15)))
        self.root.minsize(min_w, min_h)

        # State
        self._modules: List[LoadedModule] = []
        self._selected_module: Optional[LoadedModule] = None
        self._ai_state: str = "idle"       # idle | busy | ok | error
        self._ai_pulse_after: Optional[str] = None
        self._ai_pulse_t: float = 0
        self._search_after: Optional[str] = None
        self._loading_btn_after: Optional[str] = None
        self._loading_btn_frame: int = 0
        self._status_history_filter: str = "all"
        self._last_approved: Optional[Tuple[LoadedModule, Dict[str, Any], Path]] = None
        self._toplevels_open: List[tk.Toplevel] = []
        self._unsaved_changes: bool = False  # FR12: on_close ask confirm

        self._build_header()
        self._build_body()
        self._apply_tooltips()
        self._build_statusbar()
        self._install_shortcuts()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(300, self._refresh_modules)
        self.root.after(500, lambda: self._set_status(
            "Pronto. Seleziona un modulo dal pannello laterale o creane uno nuovo (Ctrl+N)."))
        # ---- FR1/FR19: splash screen (1s min) then first-run wizard if needed ----
        self.root.after(120, self._show_splash_and_then_first_run_wizard)

    # ==================== DPI helpers ====================

    def _detect_dpi_scale(self) -> float:
        scale = 1.0
        try:
            import os as _os
            if _os.name != "nt":
                try:
                    _fb = self.root.winfo_fpixels("1i") / 72.0
                    return max(_fb, 1.0)
                except Exception:
                    return 1.0
        except Exception:
            pass
        try:
            import ctypes
            try:
                _shcore = ctypes.windll.shcore
                _monitor = _shcore.MonitorFromWindow(
                    ctypes.windll.user32.GetDesktopWindow(), 0)
                _sf = ctypes.c_uint()
                if _shcore.GetScaleFactorForMonitor(
                        _monitor, ctypes.byref(_sf)) == 0:
                    scale = _sf.value / 100.0
            except Exception:
                try:
                    _hdc = ctypes.windll.user32.GetDC(0)
                    _dpi = ctypes.windll.gdi32.GetDeviceCaps(_hdc, 88)
                    ctypes.windll.user32.ReleaseDC(0, _hdc)
                    if _dpi and _dpi > 0:
                        scale = _dpi / 96.0
                except Exception:
                    pass
        except Exception:
            pass
        try:
            _fb = self.root.winfo_fpixels("1i") / 72.0
            scale = max(scale, _fb)
        except Exception:
            pass
        return max(scale, 1.0)

    def _wp(self, base_px: int) -> int:
        return max(int(round(base_px * self._dpi_scale)), base_px)

    # ==================== Lifecycle ====================

    def show(self) -> None:
        self.root.mainloop()

    # ---- Geometry helpers ----
    def _save_geometry(self) -> None:
        try:
            g = self.root.geometry()
            if g and self.db is not None and hasattr(self.db, "set_setting"):
                self.db.set_setting("ui.geometry", g)
        except Exception:  # noqa: BLE001
            pass

    # ---- Splash + first-run wizard ----
    def _show_splash_and_then_first_run_wizard(self) -> None:
        try:
            splash = SplashScreen(self.root,
                                  title="MaintenanceAI",
                                  subtitle="Caricamento moduli e servizi…",
                                  min_display_ms=1000)
            splash.show()
        except Exception:  # noqa: BLE001
            splash = None

        def _on_done() -> None:
            try:
                first_run = None
                try:
                    if self.db is not None and hasattr(self.db, "get_setting"):
                        first_run = self.db.get_setting("first_run_done")
                except Exception:  # noqa: BLE001
                    first_run = None
                if first_run is None:
                    try:
                        default_ws = (Path(os.environ.get("LOCALAPPDATA",
                                                         Path.home() / "AppData" / "Local"))
                                     / "MaintenanceAI" / "workspace")
                        wizard = FirstRunWizard(
                            self.root,
                            default_workspace=default_ws,
                            config=self.config,
                            db=self.db,
                        )
                        ok = wizard.run()
                        if not ok:
                            return
                    except SystemExit:
                        raise
                    except Exception as exc:  # noqa: BLE001
                        LOG.exception("first-run wizard error")
                        try:
                            messagebox.showwarning(
                                "Wizard interrotto",
                                f"Errore wizard prima esecuzione: {exc}",
                                parent=self.root,
                            )
                        except Exception:  # noqa: BLE001
                            pass
            finally:
                # Ensure main window is visible/raised
                try:
                    self.root.deiconify()
                    try:
                        self.root.lift()
                    except Exception:  # noqa: BLE001
                        pass
                except Exception:  # noqa: BLE001
                    pass

        if splash is not None:
            try:
                splash.dismiss(_on_done)
            except Exception:  # noqa: BLE001
                self.root.after(1200, _on_done)
        else:
            self.root.after(150, _on_done)

    # ---- Close/unsaved confirm FR12 + geometry persist FR9 ----
    def _on_close(self) -> None:
        if self._unsaved_changes:
            try:
                ans = messagebox.askyesnocancel(
                    "Uscire da MaintenanceAI?",
                    "Ci sono modifiche non salvate in un rapporto in revisione.\n\n"
                    "· Sì = salva posizione finestra e chiudi\n"
                    "· No = annulla e torna al lavoro\n"
                    "· Annulla = non salvare modifiche ma chiudi l'app",
                    parent=self.root,
                )
            except Exception:  # noqa: BLE001
                ans = False
            if ans is None:
                # Annulla = non salvare modifiche ma chiudi lo stesso
                self._save_geometry()
            elif ans is False:
                return
            else:
                self._save_geometry()
        else:
            self._save_geometry()
        for tl in list(self._toplevels_open):
            try: tl.destroy()
            except Exception: pass
        self._toplevels_open.clear()
        try:
            self.reports.shutdown()
        finally:
            try: self.db.close()
            except Exception: pass
            try: self.root.destroy()
            except Exception: pass

    # ==================== Shortcuts ====================

    def _install_shortcuts(self) -> None:
        self.root.bind_all("<Control-n>", lambda e: self._on_new_module())
        self.root.bind_all("<Control-N>", lambda e: self._on_new_module())
        self.root.bind_all("<Control-e>", lambda e: self._on_extract())
        self.root.bind_all("<Control-E>", lambda e: self._on_extract())
        self.root.bind_all("<Control-s>", lambda e: self._on_export_quick())
        self.root.bind_all("<Control-S>", lambda e: self._on_export_quick())
        self.root.bind_all("<Control-f>", lambda e: self._focus_search())
        self.root.bind_all("<Control-F>", lambda e: self._focus_search())
        self.root.bind_all("<F5>", lambda e: self._refresh_modules())
        self.root.bind_all("<F1>", lambda e: self._on_show_help())
        self.root.bind_all("<Control-Tab>", self._cycle_tab_next)
        self.root.bind_all("<Control-ISO_Left_Tab>", self._cycle_tab_prev)
        self.root.bind_all("<Control-Prior>", self._cycle_tab_prev)
        self.root.bind_all("<Control-Next>", self._cycle_tab_next)
        self.root.bind_all("<Escape>", lambda e: self._escape_handler())

    def _cycle_tab_next(self, *_e) -> str:
        try:
            nb = self._notebook
            idx = nb.index("current")
            total = nb.index("end")
            nb.select((idx + 1) % total)
        except Exception: pass
        return "break"

    def _cycle_tab_prev(self, *_e) -> str:
        try:
            nb = self._notebook
            idx = nb.index("current")
            total = nb.index("end")
            nb.select((idx - 1) % total)
        except Exception: pass
        return "break"

    def _escape_handler(self) -> None:
        # Close topmost transient dialog if present, otherwise no-op
        for tl in reversed(self._toplevels_open):
            try:
                if tl.winfo_exists():
                    tl.destroy()
                    if tl in self._toplevels_open:
                        self._toplevels_open.remove(tl)
                    return
            except Exception:
                continue

    def _focus_search(self) -> str:
        try:
            self._search_entry.focus_set()
            self._search_entry.select_range(0, "end")
        except Exception: pass
        return "break"

    def _apply_tooltips(self) -> None:
        """Applica tooltips di aiuto ai controlli principali."""
        tips: List[Tuple[tk.Misc, str]] = []
        try: tips.append((self._new_btn, "Crea un nuovo modulo vuoto o da template DOCX/XLSX. Scorciatoia: Ctrl+N"))
        except Exception: pass
        try: tips.append((self._import_btn, "Importa un modulo precedentemente esportato come archivio ZIP."))
        except Exception: pass
        try: tips.append((self._refresh_btn, "Ricarica la lista dei moduli dal disco. Scorciatoia: F5"))
        except Exception: pass
        try: tips.append((self._search_entry, "Cerca moduli per nome o slug (anche parziale). Scorciatoia: Ctrl+F"))
        except Exception: pass
        try: tips.append((self.root.nametowidget(self._notebook.select(0)), "Home page: statistiche e azioni rapide"))
        except Exception: pass
        try:
            for w, txt in tips:
                bind_tooltip(w, txt, delay=450)
        except Exception:  # noqa: BLE001
            pass

    # ==================== Help ====================

    def _on_show_help(self) -> None:
        try:
            run_help(self.root)
        except Exception as e:
            self._toast(f"Impossibile aprire la guida: {e}", "error", "❌")

    def _help_hover(self, inside: bool) -> None:
        try:
            bg = (lighten(COLORS["slate_800"], 0.15)
                  if inside else COLORS["slate_800"])
            fg = COLORS["white"] if inside else COLORS["slate_100"]
            self._help_pill_frame.configure(bg=bg)
            self._help_lbl.configure(bg=bg, fg=fg)
            self._help_shortcut_lbl.configure(
                bg=bg,
                fg=COLORS["primary_300"] if inside else COLORS["slate_400"])
        except Exception:
            pass

    def _theme_toggle_icon(self) -> str:
        try:
            return "☀️" if self._theme.theme_name == "dark" else "🌙"
        except Exception:  # noqa: BLE001
            return "🌙"

    def _toggle_theme(self) -> None:
        try:
            self._theme.toggle_theme(persist_db=self.db)
            self._theme_icon_lbl.configure(text=self._theme_toggle_icon())
            self.root.configure(bg=self._theme.current_colors().get(
                "bg", COLORS["white"]))
            self._toast(
                f"Tema: {'scuro' if self._theme.theme_name == 'dark' else 'chiaro'}",
                "info",
                "🌗",
            )
        except Exception as exc:  # noqa: BLE001
            LOG.exception("theme toggle error")
            self._toast(f"Errore cambio tema: {exc}", "error", "❌")

    # ==================== Header (gradient) ====================

    def _build_header(self) -> None:
        header = GradientCanvas(self.root,
                                COLORS["slate_900"],
                                COLORS["primary_800"],
                                direction="horizontal",
                                height=78)
        header.pack(fill="x")

        # Overlay frame on top of the gradient canvas
        inner = tk.Frame(header, bg=COLORS["slate_900"])
        header.create_window((22, 12), anchor="nw", window=inner,
                             tags="overlay")
        # Make width follow canvas
        def _resize(_e=None):
            try:
                w = header.winfo_width() - 44
                if w < 300: w = 300
                inner.configure(width=w)
            except Exception: pass
        header.bind("<Configure>", _resize, add="+")

        # Left column: brand
        left = tk.Frame(inner, bg=COLORS["slate_900"])
        left.pack(side="left", fill="y")

        mark = tk.Frame(left, bg=COLORS["slate_900"])
        mark.pack(side="left")
        bar1 = tk.Frame(mark, bg=COLORS["primary_400"], width=6, height=42,
                        bd=0, highlightthickness=0)
        bar1.pack(side="left")
        bar2 = tk.Frame(mark, bg=COLORS["success_400"], width=6, height=42,
                        bd=0, highlightthickness=0)
        bar2.pack(side="left", padx=(3, 14))

        titles = tk.Frame(left, bg=COLORS["slate_900"])
        titles.pack(side="left")
        tk.Label(titles, text="MaintenanceAI",
                 bg=COLORS["slate_900"], fg=COLORS["white"],
                 font=FONTS["h2"]).pack(anchor="w")
        tk.Label(titles,
                 text="Generazione rapporti di manutenzione · AI locale · Offline",
                 bg=COLORS["slate_900"], fg=COLORS["slate_300"],
                 font=FONTS["body_sm"]).pack(anchor="w", pady=(2, 0))

        # Right column: profile pill + AI status
        right = tk.Frame(inner, bg=COLORS["slate_900"])
        right.pack(side="right")

        # Help pill (?) discretissimo — F1
        help_box = tk.Frame(right, bg=COLORS["slate_900"])
        help_box.pack(side="right", padx=(0, 16))
        tk.Label(help_box, text="TEMA",
                 bg=COLORS["slate_900"], fg=COLORS["slate_400"],
                 font=("Segoe UI", 8, "bold")).pack(anchor="e")
        theme_pill_bg = COLORS["slate_800"]
        self._theme_pill_frame = tk.Frame(help_box, bg=theme_pill_bg,
                                          highlightthickness=0, bd=0,
                                          padx=12, pady=5, cursor="hand2")
        self._theme_pill_frame.pack(anchor="e", pady=(3, 10))
        self._theme_icon_lbl = tk.Label(
            self._theme_pill_frame, text=self._theme_toggle_icon(),
            bg=theme_pill_bg, fg=COLORS["slate_100"],
            font=("Segoe UI", 12, "bold"))
        self._theme_icon_lbl.pack(side="left")
        for w in (self._theme_pill_frame, self._theme_icon_lbl):
            try:
                w.bind("<Button-1>", lambda _e: self._toggle_theme())
                w.bind("<Enter>", lambda _e: self._theme_pill_frame.configure(bg=lighten(
                    COLORS["slate_800"], 0.15)))
                w.bind("<Leave>", lambda _e: self._theme_pill_frame.configure(bg=COLORS["slate_800"]))
            except Exception:  # noqa: BLE001
                pass

        help_box2 = tk.Frame(right, bg=COLORS["slate_900"])
        help_box2.pack(side="right", padx=(0, 16))
        tk.Label(help_box2, text="AIUTO",
                 bg=COLORS["slate_900"], fg=COLORS["slate_400"],
                 font=("Segoe UI", 8, "bold")).pack(anchor="e")
        help_pill_bg = COLORS["slate_800"]
        self._help_pill_frame = tk.Frame(help_box2, bg=help_pill_bg,
                                         highlightthickness=0, bd=0,
                                         padx=14, pady=6, cursor="hand2")
        self._help_pill_frame.pack(anchor="e", pady=(3, 0))
        self._help_lbl = tk.Label(
            self._help_pill_frame, text="?",
            bg=help_pill_bg, fg=COLORS["slate_100"],
            font=("Segoe UI", 11, "bold"))
        self._help_lbl.pack(side="left")
        self._help_shortcut_lbl = tk.Label(
            self._help_pill_frame, text=" F1",
            bg=help_pill_bg, fg=COLORS["slate_400"],
            font=("Segoe UI", 8, "bold"))
        self._help_shortcut_lbl.pack(side="left")
        for w in (self._help_pill_frame, self._help_lbl, self._help_shortcut_lbl):
            try:
                w.bind("<Button-1>", lambda _e: self._on_show_help())
                w.bind("<Enter>", lambda _e: self._help_hover(True))
                w.bind("<Leave>", lambda _e: self._help_hover(False))
            except Exception:
                pass

        # LLM profile selector
        prof_box = tk.Frame(right, bg=COLORS["slate_900"])
        prof_box.pack(side="right", padx=(0, 16))
        tk.Label(prof_box, text="PROFILO LLM",
                 bg=COLORS["slate_900"], fg=COLORS["slate_400"],
                 font=("Segoe UI", 8, "bold")).pack(anchor="e")
        try:
            profiles = list((self.config.llm_profiles or {}).keys())
        except Exception:
            profiles = ["default"]
        if not profiles: profiles = ["default"]
        self._profile_var = tk.StringVar(value=profiles[0])
        self._profile_combo = ttk.Combobox(
            prof_box, textvariable=self._profile_var,
            values=profiles, state="readonly", width=18)
        self._profile_combo.pack(anchor="e", pady=(3, 0))

        # AI status pill (animated when busy)
        pill = tk.Frame(right, bg=COLORS["slate_900"])
        pill.pack(side="right")
        tk.Label(pill, text="STATO AI",
                 bg=COLORS["slate_900"], fg=COLORS["slate_400"],
                 font=("Segoe UI", 8, "bold")).pack(anchor="e")
        self._ai_pill_bg = COLORS["slate_800"]
        self._ai_pill_frame = tk.Frame(pill, bg=self._ai_pill_bg,
                                       highlightthickness=0, bd=0,
                                       padx=14, pady=6)
        self._ai_pill_frame.pack(anchor="e", pady=(3, 0))
        self._ai_dot_canvas = tk.Canvas(self._ai_pill_frame,
                                        bg=self._ai_pill_bg,
                                        width=14, height=14,
                                        highlightthickness=0, bd=0)
        self._ai_dot_canvas.pack(side="left", padx=(0, 8))
        self._ai_status_lbl = tk.Label(self._ai_pill_frame,
                                       text="Inattivo",
                                       bg=self._ai_pill_bg,
                                       fg=COLORS["slate_200"],
                                       font=("Segoe UI", 10, "bold"))
        self._ai_status_lbl.pack(side="left")
        self._redraw_ai_dot()
        self._ai_start_pulse()

    # -------- AI pill helpers --------

    def _redraw_ai_dot(self) -> None:
        c = self._ai_dot_canvas
        state_colors = {
            "idle":  COLORS["slate_400"],
            "busy":  COLORS["warning_500"],
            "ok":    COLORS["success_500"],
            "error": COLORS["danger_500"],
        }
        col = state_colors.get(self._ai_state, COLORS["slate_400"])
        if self._ai_state == "busy":
            # Pulse interpolation effect
            self._ai_pulse_t = (self._ai_pulse_t + 0.08) % 1.0
            pulse = 0.5 + 0.5 * (
                1 if self._ai_pulse_t < 0.5 else -1) * (
                    1 - abs(self._ai_pulse_t - 0.5) * 2)
            t = 0.5 + 0.5 * pulse
            col = mix_colors(COLORS["warning_500"],
                             COLORS["warning_300"]
                             if "warning_300" in COLORS
                             else lighten(COLORS["warning_500"], 0.4),
                             t)
        try:
            c.delete("all")
            bg = c.cget("background")
            outer = lighten(col, 0.55) if self._ai_state == "busy" else darken(col, 0.3)
            c.create_oval(1, 1, 13, 13, outline=outer, fill=col, width=2)
        except Exception:
            pass

    def _ai_start_pulse(self) -> None:
        try:
            self._redraw_ai_dot()
        except Exception:
            pass
        self._ai_pulse_after = self.root.after(120, self._ai_start_pulse)

    def _set_ai_state(self, state: str, label: Optional[str] = None) -> None:
        self._ai_state = state
        texts = {
            "idle":  "Inattivo",
            "busy":  "Elaborazione…",
            "ok":    "OK",
            "error": "Errore",
        }
        text = label or texts.get(state, state)
        try:
            self._ai_status_lbl.configure(text=text)
        except Exception:
            pass

    # ==================== Body (sidebar + notebook) ====================

    def _build_body(self) -> None:
        body = tk.Frame(self.root, bg=COLORS["white"])
        body.pack(fill="both", expand=True)

        # ----- Sidebar -----
        self._sidebar = tk.Frame(body, bg=COLORS["slate_50"],
                                 width=350, bd=0, highlightthickness=0)
        self._sidebar.pack(side="left", fill="y")
        self._sidebar.pack_propagate(False)

        # Search card
        search_card = RoundedCard(self._sidebar, padding=14, radius=12,
                                  shadow=False, bg=COLORS["white"],
                                  border=COLORS["slate_200"])
        search_card.pack(fill="x", padx=14, pady=(16, 12))
        ttk.Label(search_card.content,
                  text="📦  Moduli",
                  style="Title.H3.TLabel").pack(anchor="w")
        ttk.Label(search_card.content,
                  text="Cerca o crea un modulo di manutenzione",
                  style="Subtitle.TLabel",
                  wraplength=310).pack(anchor="w", pady=(2, 10))

        search_wrap = tk.Frame(search_card.content, bg=COLORS["white"])
        search_wrap.pack(fill="x")
        tk.Label(search_wrap, text="🔍", bg=COLORS["white"],
                 fg=COLORS["slate_400"],
                 font=("Segoe UI", 11), padx=8, pady=6, bd=0,
                 highlightthickness=0).pack(side="left")
        self._search_entry = tk.Entry(
            search_wrap,
            **_tk_text(),
        )
        self._search_entry.pack(side="left", fill="x", expand=True, ipady=6)
        self._search_entry.insert(0, "")
        self._search_entry.bind(
            "<KeyRelease>",
            lambda e: self._schedule_search(), add="+")

        # Tree card: always visible vertical scrollbar.
        tree_card = RoundedCard(self._sidebar, padding=0, radius=12,
                                shadow=False, bg=COLORS["white"],
                                border=COLORS["slate_200"])
        tree_card.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        tree_host = tk.Frame(tree_card.content, bg=COLORS["white"])
        tree_host.pack(fill="both", expand=True, padx=2, pady=2)
        self._modules_tree = ttk.Treeview(
            tree_host, columns=("meta",), show="tree",
            selectmode="browse", height=14)
        try:
            self._modules_tree.column("#0", width=340, minwidth=300, stretch=True)
            self._modules_tree.column("meta", width=30, minwidth=20, stretch=False)
        except Exception:  # noqa: BLE001
            pass
        vsb_mod = ttk.Scrollbar(tree_host, orient="vertical",
                                 command=self._modules_tree.yview)
        hsb_mod = ttk.Scrollbar(tree_host, orient="horizontal",
                                 command=self._modules_tree.xview)
        self._modules_tree.configure(yscrollcommand=vsb_mod.set,
                                     xscrollcommand=hsb_mod.set)
        hsb_mod.pack(side="bottom", fill="x")
        vsb_mod.pack(side="right", fill="y")  # ALWAYS visible
        self._modules_tree.pack(side="left", fill="both", expand=True)
        self._modules_tree.bind(
            "<<TreeviewSelect>>", self._on_select_module, add="+")
        self._modules_tree.bind(
            "<Double-1>", lambda e: self._open_current_module_tab(), add="+")

        # Actions
        btn_col = tk.Frame(self._sidebar, bg=COLORS["slate_50"])
        btn_col.pack(fill="x", padx=14, pady=(0, 16))
        self._new_btn = ttk.Button(
            btn_col, text="＋  Nuovo modulo  (Ctrl+N)",
            style="Accent.TButton", command=self._on_new_module)
        self._new_btn.pack(fill="x", pady=(0, 8))
        self._import_btn = ttk.Button(
            btn_col, text="⬇️  Importa modulo…",
            style="Subtle.TButton", command=self._on_import_module)
        self._import_btn.pack(fill="x", pady=(0, 8))
        self._refresh_btn = ttk.Button(
            btn_col, text="🔄  Ricarica  (F5)",
            style="Subtle.TButton", command=self._refresh_modules)
        self._refresh_btn.pack(fill="x")

        # Documenti AI
        sep = tk.Frame(self._sidebar, height=1, bg=COLORS["slate_200"])
        sep.pack(fill="x", padx=14, pady=(0, 10))
        lbl = tk.Label(self._sidebar, text="⚙  Documenti AI",
                       font=FONTS["body_bold"], fg=COLORS["text"],
                       bg=COLORS["slate_50"], anchor="w")
        lbl.pack(fill="x", padx=14)
        doc_col = tk.Frame(self._sidebar, bg=COLORS["slate_50"])
        doc_col.pack(fill="x", padx=14, pady=(6, 16))
        ttk.Button(doc_col, text="📝  Crea documento",
                   style="Subtle.TButton",
                   command=self._on_doc_create).pack(fill="x", pady=2)
        ttk.Button(doc_col, text="✏️  Modifica documento",
                   style="Subtle.TButton",
                   command=self._on_doc_edit).pack(fill="x", pady=2)
        ttk.Button(doc_col, text="🔍  Audit documenti",
                   style="Subtle.TButton",
                   command=self._on_doc_audit).pack(fill="x", pady=2)
        ttk.Button(doc_col, text="🧩  Compila da documenti",
                   style="Subtle.TButton",
                   command=self._on_doc_smart_fill).pack(fill="x", pady=2)
        ttk.Button(doc_col, text="🛡  Regole AI",
                   style="Subtle.TButton",
                   command=self._on_doc_rules_picker).pack(fill="x", pady=2)

        # ----- Right: Notebook -----
        self._notebook = ttk.Notebook(body, style="Card.TNotebook")
        self._notebook.pack(side="left", fill="both", expand=True,
                            padx=16, pady=16)

        # ---- Tab wrappers: every content tab is ALWAYS scrollable with
        # a permanently visible vertical bar (user requirement).
        # We attach an outer frame to the notebook, then wrap the actual
        # content frame inside make_scrollable_frame so the vertical
        # scrollbar shows up even on short content.

        home_outer = ttk.Frame(self._notebook, style="TFrame")
        report_outer = ttk.Frame(self._notebook, style="TFrame")
        history_outer = ttk.Frame(self._notebook, style="TFrame")
        module_outer = ttk.Frame(self._notebook, style="TFrame")
        doc_outer = ttk.Frame(self._notebook, style="TFrame")

        self._notebook.add(home_outer, text="  🏠  HOME  ")
        self._notebook.add(report_outer, text="  📝  RAPPORTO  ")
        self._notebook.add(history_outer, text="  📚  STORICO  ")
        self._notebook.add(module_outer, text="  ℹ️  DETTAGLI MODULO  ")
        self._notebook.add(doc_outer, text="  📂  DOCUMENTI AI  ")

        def _wrap(parent, bg=COLORS["white"]):
            sf = make_scrollable_frame(parent, bg=bg, show_scrollbars="always")
            sf.outer.pack(fill="both", expand=True)
            return sf.inner

        self._tab_home = _wrap(home_outer)
        self._tab_report = _wrap(report_outer)
        self._tab_history = _wrap(history_outer)
        self._tab_module = _wrap(module_outer)
        self._tab_documents = _wrap(doc_outer)

        self._build_home_tab()
        self._build_report_tab()
        self._build_history_tab()
        self._build_module_tab()
        self._build_documents_tab()

    # ==================== Search live ====================

    def _schedule_search(self) -> None:
        if self._search_after is not None:
            try: self.root.after_cancel(self._search_after)
            except Exception: pass
        self._search_after = self.root.after(160, self._apply_search)

    def _apply_search(self) -> None:
        self._search_after = None
        try:
            q = (self._search_entry.get() or "").strip().lower()
        except Exception:
            q = ""
        visible_slugs: set = set()
        for child in self._modules_tree.get_children(""):
            self._modules_tree.delete(child)
        for mod in self._modules:
            hay = (mod.name + " " + mod.slug + " "
                   + (mod.description or "")).lower()
            if q and q not in hay:
                continue
            visible_slugs.add(mod.slug)
            try:
                mid = mod.id
                nd = self.db.count_reports(status="draft", module_id=mid) if mid else 0
                ne = self.db.count_reports(status="exported", module_id=mid) if mid else 0
            except Exception:
                nd, ne = 0, 0
            try:
                tpl_ok = (getattr(mod, "template_path", None) is not None
                          and Path(mod.template_path).exists())
            except Exception:
                tpl_ok = False
            tpl_badge = "✅" if tpl_ok else "⚠️"
            parts = [f"  📋  {mod.name}"]
            badges = []
            if nd or ne:
                badges.append(f"Bozze {nd}" if nd else None)
                badges.append(f"Esp {ne}" if ne else None)
            badges_s = " · ".join(b for b in badges if b)
            if badges_s:
                parts.append(f"  [{badges_s}]")
            parts.append(f"  {tpl_badge}")
            self._modules_tree.insert(
                "", "end", iid=mod.slug,
                text="".join(parts),
                values=(f"slug: {mod.slug}",),)
        # Re-select currently selected module if still visible
        if self._selected_module and (self._selected_module.slug
                                       in visible_slugs):
            try:
                self._modules_tree.selection_set(
                    self._selected_module.slug)
            except Exception: pass

    # ==================== Home tab ====================

    def _build_home_tab(self) -> None:
        frame = self._tab_home

        # Headline
        head = tk.Frame(frame, bg=COLORS["white"])
        head.pack(fill="x", padx=18, pady=(18, 4))
        ttk.Label(head, text="Benvenuto in MaintenanceAI",
                  style="Title.H1.TLabel").pack(anchor="w")
        ttk.Label(
            head,
            text="Crea o seleziona un modulo, descrivi l'intervento e lascia che l'AI compili il rapporto in modo strutturato. "
                 "Ricontrolla sempre prima dell'esportazione finale.",
            style="Subtitle.TLabel").pack(anchor="w", pady=(6, 0))

        # Stat row (4 cards)
        stats_row = tk.Frame(frame, bg=COLORS["white"])
        stats_row.pack(fill="x", padx=18, pady=(18, 8))
        for i in range(4):
            stats_row.columnconfigure(i, weight=1, uniform="stat")

        self._stat_cards: List[RoundedCard] = []
        stat_defs = [
            ("📦", "Moduli",          "0",   COLORS["primary_600"], "primary_50"),
            ("📝", "Bozze/rapporti",  "0",   COLORS["indigo_600"]
                                            if "indigo_600" in COLORS
                                            else COLORS["primary_600"],
                 "primary_50"),
            ("✅", "Esportati",       "0",   COLORS["success_600"], "success_50"),
            ("🕒", "Ultimo intervento", "—",  COLORS["warning_600"], "warning_50"),
        ]
        for idx, (icon, title, value, accent, accent_50_name) in enumerate(stat_defs):
            accent_50 = COLORS.get(accent_50_name, COLORS["primary_50"])
            card = RoundedCard(stats_row, padding=16, radius=14,
                               shadow=True, accent=accent)
            card.grid(row=0, column=idx, sticky="nsew", padx=6, pady=6)
            self._stat_cards.append(card)
            top = tk.Frame(card.content, bg=COLORS["white"])
            top.pack(fill="x")
            icon_circle = tk.Canvas(top, width=60, height=60,
                                    bg=COLORS["white"],
                                    highlightthickness=0, bd=0)
            icon_circle.pack(side="left")
            def _paint_circle(cc, col=accent, col50=accent_50):
                try:
                    cc.delete("all")
                    cc.create_oval(2, 2, 58, 58, fill=col50,
                                   outline="", width=0)
                    cc.create_text(31, 31, text=icon,
                                   font=("Segoe UI", 20, "bold"),
                                   fill=col)
                except Exception: pass
            _paint_circle(icon_circle)
            vcol = tk.Frame(top, bg=COLORS["white"])
            vcol.pack(side="left", padx=14, fill="both", expand=True)
            val_lbl = tk.Label(vcol, text=value,
                               bg=COLORS["white"], fg=COLORS["slate_900"],
                               font=FONTS["h2"])
            val_lbl.pack(anchor="w")
            tk.Label(vcol, text=title, bg=COLORS["white"],
                     fg=COLORS["slate_500"],
                     font=FONTS["body_sm"]).pack(anchor="w")
            # keep reference for later updates
            card._state = {"value_label": val_lbl, "title": title, "index": idx}

        # Subtitle action cards
        mid = tk.Frame(frame, bg=COLORS["white"])
        mid.pack(fill="both", expand=True, padx=18, pady=(8, 18))
        for i in range(3):
            mid.columnconfigure(i, weight=1, uniform="feat", minsize=360)

        actions = [
            ("✨", "Crea un nuovo modulo",
             "Avvia la procedura guidata per creare un modulo vuoto o da template DOCX/XLSX.",
             "Avvia wizard  (Ctrl+N)",
             self._on_new_module,
             COLORS["primary_600"], COLORS["primary_50"]),
            ("⬇️", "Importa moduli esistenti",
             "Importa un archivio ZIP di un modulo precedentemente esportato.",
             "Importa file ZIP…",
             self._on_import_module,
             COLORS["success_600"], COLORS["success_50"]),
            ("📄", "Modelli di riferimento",
             "Apri la cartella dei modelli vuoti e dei documenti allegabili.",
             "Apri cartella modelli",
             lambda: self._open_templates_folder(),
             (COLORS["indigo_600"] if "indigo_600" in COLORS
              else COLORS["primary_600"]),
             COLORS["primary_50"]),
        ]
        for idx, (ico, title, desc, cta_text, cta_cmd, accent, accent_50) \
                in enumerate(actions):
            card = RoundedCard(mid, padding=18, radius=14, shadow=True,
                               accent=accent)
            card.grid(row=0, column=idx, sticky="nsew", padx=6, pady=6)
            banner = tk.Canvas(card.content, height=90,
                               bg=accent_50, bd=0, highlightthickness=0)
            banner.pack(fill="x")
            try:
                banner.create_text(54, 45, text=ico,
                                   font=("Segoe UI", 34), fill=accent)
                banner.create_text(124, 45, text=title,
                                   anchor="w",
                                   font=(FONTS["h3"][0], 16, "bold"),
                                   fill=darken(accent, 0.4))
            except Exception: pass
            tk.Label(card.content, text=title,
                     bg=COLORS["white"], fg=COLORS["slate_900"],
                     font=FONTS["h3"]).pack(anchor="w", pady=(14, 6))
            tk.Label(card.content, text=desc,
                     bg=COLORS["white"], fg=COLORS["slate_500"],
                     font=FONTS["body"], wraplength=self._wp(370),
                     justify="left").pack(anchor="w")
            cta = ttk.Button(card.content, text=cta_text,
                             style="Accent.TButton", command=cta_cmd)
            cta.pack(anchor="w", pady=(18, 2))
            # subtle hover
            try:
                card.bind_click(lambda e, c=cta_cmd: c(), cursor="hand2")
            except Exception: pass
        self._update_home_stats()

    def _open_templates_folder(self) -> None:
        try:
            mod = self._selected_module
            if mod is not None:
                target = mod.template_path.parent
            else:
                target = self.mm.workspace
            _open_folder(target, self._toast)
        except Exception as e:
            self._toast(f"Impossibile aprire: {e}", "error", "⚠️")

    def _update_home_stats(self) -> None:
        try:
            n_modules = len(self._modules)
            n_total_reports = self.db.count_reports(status=None)
            n_exported = self.db.count_reports(status="exported")
            last = self.db.last_report_timestamp()
            vals = [str(n_modules), str(n_total_reports),
                    str(n_exported),
                    (time.strftime("%d/%m/%Y %H:%M",
                                   time.localtime(last))
                     if last else "—")]
            for card, val in zip(self._stat_cards, vals):
                lbl = card._state["value_label"]
                try:
                    lbl.configure(text=val)
                except Exception: pass
        except Exception:
            pass

    # ==================== Report tab ====================

    def _build_report_tab(self) -> None:
        frame = self._tab_report
        top = tk.Frame(frame, bg=COLORS["white"])
        top.pack(fill="x", padx=18, pady=(18, 4))
        ttk.Label(top, text="Nuovo rapporto",
                  style="Title.H2.TLabel").pack(anchor="w")
        ttk.Label(top,
                  text="Scegli come produrre il rapporto: descrivendo l'intervento oppure caricando i documenti. "
                       "Il risultato finale viene sempre rivisto prima dell'esportazione.",
                  style="Subtitle.TLabel").pack(anchor="w", pady=(4, 0))

        main_row = tk.Frame(frame, bg=COLORS["white"])
        main_row.pack(fill="both", expand=True, padx=18, pady=(14, 18))
        main_row.columnconfigure(0, weight=3, uniform="col")
        main_row.columnconfigure(1, weight=2, uniform="col")
        main_row.rowconfigure(0, weight=1)

        # --- Description column ---
        left_card = RoundedCard(main_row, padding=18, radius=14,
                                shadow=True)
        left_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        head_l = tk.Frame(left_card.content, bg=COLORS["white"])
        head_l.pack(fill="x")
        tk.Label(head_l, text="📝  Produci rapporto",
                 bg=COLORS["white"], fg=COLORS["slate_900"],
                 font=FONTS["h3"]).pack(side="left")
        self._quality_lbl = tk.Label(
            head_l, text="",
            bg=COLORS["white"], fg=COLORS["slate_500"],
            font=("Segoe UI", 9, "bold"))
        self._quality_lbl.pack(side="right")

        # ====== Segment control (Prompt / Carica documenti) ======
        mode_frame = tk.Frame(left_card.content, bg=COLORS["white"])
        mode_frame.pack(fill="x", pady=(6, 10))
        self._rp_mode_var = tk.StringVar(value="prompt")

        def _mode_radio(parent, value, label):
            r = tk.Radiobutton(
                parent, text=label, value=value,
                variable=self._rp_mode_var,
                indicatoron=True, selectcolor=COLORS["primary_50"],
                activebackground=COLORS["white"],
                background=COLORS["white"],
                foreground=COLORS["slate_900"],
                font=FONTS["body_bold"],
                borderwidth=0,
                command=lambda: self._switch_report_mode(self._rp_mode_var.get()))
            return r

        _mode_radio(mode_frame, "prompt", "📝  Scrivi descrizione").pack(side="left", padx=(0, 16))
        _mode_radio(mode_frame, "docs",   "📎  Carica documenti").pack(side="left")

        ttk.Separator(left_card.content).pack(fill="x", pady=(0, 10))

        # Hero button + progress (contenuti COMUNI a entrambe le modalità, ma
        # in Carica documenti vengono nascosti per lasciare spazio al bottone
        # secondario "Compila da documenti".)
        self._extract_btn = ttk.Button(
            left_card.content,
            text="🚀  Avvia estrazione AI  (Ctrl+E)",
            style="Hero.TButton", command=self._on_extract)
        self._progress = ttk.Progressbar(
            left_card.content, mode="determinate", maximum=100, value=0)

        # ====== FRAME 1: PROMPT TESTUALE ======
        self._rp_prompt_frame = tk.Frame(left_card.content, bg=COLORS["white"])
        # Hint compatto (massimo 40-50 px, padding minimo, radius 5
        hint = RoundedCard(self._rp_prompt_frame, padding=2, radius=5,
                           shadow=False,
                           bg=COLORS["primary_50"],
                           border=COLORS["primary_200"])
        hint.pack(fill="x", pady=(0, 4))
        self._rp_hint_lbl = tk.Label(
            hint.content,
            text="💡 Includi data, impianto, componenti, attività, esiti. Più dettagli, più campi precisi.",
            bg=COLORS["primary_50"], fg=COLORS["primary_800"],
            font=FONTS["body_sm"], justify="left",
            wraplength=self._wp(650),
        )
        self._rp_hint_lbl.pack(anchor="w", fill="x")
        self._extract_btn_prompt = self._extract_btn
        self._progress_prompt = self._progress
        self._extract_btn_prompt.pack(in_=self._rp_prompt_frame, fill="x", pady=(2, 4))
        self._progress_prompt.pack(in_=self._rp_prompt_frame, fill="x", pady=(0, 6))
        self._desc_text = tk.Text(
            self._rp_prompt_frame,
            height=1,
            **_tk_text_multi())
        self._desc_text.pack(fill="both", expand=True, pady=(4, 0))
        self._desc_text.bind(
            "<<Modified>>", lambda e: self._update_quality(), add="+")
        self._desc_text.bind(
            "<KeyRelease>", lambda e: self._update_quality(), add="+")

        # ====== FRAME 2: CARICA DOCUMENTI ======
        self._rp_docs_frame = tk.Frame(left_card.content, bg=COLORS["white"])

        row_list = tk.Frame(self._rp_docs_frame, bg=COLORS["white"])
        row_list.pack(fill="both", expand=True, pady=(0, 8))
        list_wrap = tk.Frame(row_list, bg=COLORS["card_bg"],
                             highlightthickness=1,
                             highlightbackground=COLORS["slate_200"])
        list_wrap.pack(side="left", fill="both", expand=True)
        self._rp_files_listbox = tk.Listbox(
            list_wrap, selectmode="extended",
            bg=COLORS["card_bg"], fg=COLORS["slate_900"],
            font=FONTS["body"], height=6,
            activestyle="none", relief="flat", bd=0,
        )
        self._rp_files_listbox.pack(fill="both", expand=True, padx=4, pady=4)
        btns_col = tk.Frame(row_list, bg=COLORS["white"])
        btns_col.pack(side="right", fill="y", padx=(10, 0))
        ttk.Button(btns_col, text="➕  Aggiungi file…",
                   command=self._on_rp_add_file,
                   style="Secondary.TButton").pack(fill="x", pady=(0, 6))
        ttk.Button(btns_col, text="➖  Rimuovi",
                   command=self._on_rp_remove_file,
                   style="Secondary.TButton").pack(fill="x")
        self._rp_files: List[Path] = []

        tip_docs = tk.Label(
            self._rp_docs_frame,
            text=("💡  Formati accettati: DOCX · XLSX · PDF · TXT · JPG · PNG. "
                  "Le scansioni vengono sottoposte a OCR automaticamente."),
            bg=COLORS["white"], fg=COLORS["muted"],
            font=FONTS["body_sm"], justify="left",
            wraplength=self._wp(480))
        tip_docs.pack(anchor="w", pady=(0, 8))

        self._rp_compile_btn = ttk.Button(
            self._rp_docs_frame,
            text="🚀  Compila da documenti",
            style="Hero.TButton",
            command=self._on_rp_compile_from_docs)
        self._rp_compile_btn.pack(fill="x", pady=(2, 0))

        # Default: mostra prompt frame, nascondi docs
        self._rp_prompt_frame.pack(fill="both", expand=True)
        self._switch_report_mode("prompt", _force=True)

        # --- Options column ---
        right_card = RoundedCard(main_row, padding=18, radius=14,
                                 shadow=True)
        right_card.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        tk.Label(right_card.content, text="⚙️  Opzioni estrazione",
                 bg=COLORS["white"], fg=COLORS["slate_900"],
                 font=FONTS["h3"]).pack(anchor="w")
        tk.Label(right_card.content,
                 text="Personalizza i blocchi di contesto che verranno inclusi nel prompt all'intelligenza artificiale.",
                 bg=COLORS["white"], fg=COLORS["slate_500"],
                 font=FONTS["body_sm"], justify="left",
                 wraplength=self._wp(280)).pack(anchor="w", pady=(6, 14))

        self._var_refs = tk.BooleanVar(value=True)
        self._var_hist = tk.BooleanVar(value=True)
        self._var_temp = tk.DoubleVar(value=0.2)

        checks = [
            ("📚  Usa documenti di riferimento come contesto",
             self._var_refs,
             "Le procedure, check list e listini vengono inviati come istruzioni e contesto."),
            ("🕒  Usa storico interventi come esempio",
             self._var_hist,
             "Formato e terminologia vengono appresi dallo storico; i dati concreti non vengono copiati."),
        ]
        for title, var, desc in checks:
            row = tk.Frame(right_card.content, bg=COLORS["white"])
            row.pack(fill="x", pady=6)
            ttk.Checkbutton(row, text=title, variable=var).pack(anchor="w")
            tk.Label(row, text=desc, bg=COLORS["white"],
                     fg=COLORS["slate_500"], font=FONTS["body_sm"],
                     wraplength=self._wp(260), justify="left").pack(
                anchor="w", padx=(28, 0), pady=(3, 0))

        ttk.Separator(right_card.content).pack(fill="x", pady=14)
        tk.Label(right_card.content, text="Temperatura AI",
                 bg=COLORS["white"], fg=COLORS["slate_800"],
                 font=FONTS["h4"]).pack(anchor="w")
        self._temp_lbl = tk.Label(
            right_card.content,
            text=f"T = {self._var_temp.get():.2f}  "
                 "(più alto = più creativo, più basso = più deterministico)",
            bg=COLORS["white"], fg=COLORS["slate_500"],
            font=FONTS["body_sm"], wraplength=self._wp(280), justify="left")
        self._temp_lbl.pack(anchor="w", pady=(2, 6))
        temp_scale = ttk.Scale(
            right_card.content, from_=0.0, to=0.5,
            orient="horizontal", variable=self._var_temp,
            command=lambda v: self._temp_lbl.configure(
                text=f"T = {float(v):.2f}  "
                     "(più alto = più creativo, più basso = più deterministico)"))
        temp_scale.pack(fill="x")
        tk.Frame(right_card.content, bg=COLORS["white"]).pack(
            fill="both", expand=True)

        self._update_quality()

    # ---------- Modalità tab Rapporto ----------
    def _switch_report_mode(self, mode: str, *, _force: bool = False) -> None:
        try:
            self._rp_mode_var.set(mode)
        except Exception:
            pass
        try:
            self._rp_prompt_frame.pack_forget()
        except Exception:
            pass
        try:
            self._rp_docs_frame.pack_forget()
        except Exception:
            pass
        if mode == "prompt":
            self._rp_prompt_frame.pack(fill="both", expand=True)
            try:
                self._quality_lbl.configure(text="")
            except Exception:
                pass
            try:
                self._update_quality()
            except Exception:
                pass
        else:
            self._rp_docs_frame.pack(fill="both", expand=True)
            try:
                self._quality_lbl.configure(
                    text=f"{len(self._rp_files)} file · qualità: DOCUMENTI  📎",
                    fg=COLORS["primary_700"])
            except Exception:
                pass
        for _ in range(4):
            try:
                self.root.update_idletasks()
                self.root.update()
            except Exception:
                break

    def _selected_rp_module(self) -> Optional[LoadedModule]:
        return self._selected_module

    def _on_rp_add_file(self) -> None:
        from tkinter import filedialog
        exts = [
            ("File supportati", "*.docx *.xlsx *.pdf *.txt *.jpg *.jpeg *.png"),
            ("Tutti i file", "*.*"),
        ]
        try:
            files = filedialog.askopenfilenames(
                title="Seleziona documenti da usare per la compilazione",
                filetypes=exts,
                parent=self.root,
            )
        except Exception:  # noqa: BLE001
            return
        if not files:
            return
        added = 0
        for f in files:
            try:
                p = Path(f)
                if not p.is_file():
                    continue
                if p in self._rp_files:
                    continue
                # Filtro estensioni security
                ext = p.suffix.lower().lstrip(".")
                if ext not in {"docx", "xlsx", "pdf", "txt", "jpg", "jpeg", "png"}:
                    self._toast(
                        f"Estensione non consentita: .{ext}", "warning", "⚠️")
                    continue
                self._rp_files.append(p)
                self._rp_files_listbox.insert("end", f"{p.name}")
                added += 1
            except Exception:  # noqa: BLE001
                continue
        if added:
            self._toast(f"Aggiunti {added} file", "info", "📎")
        try:
            self._quality_lbl.configure(
                text=f"{len(self._rp_files)} file · qualità: DOCUMENTI  📎",
                fg=COLORS["primary_700"])
        except Exception:
            pass

    def _on_rp_remove_file(self) -> None:
        try:
            sel = list(self._rp_files_listbox.curselection())
        except Exception:
            sel = []
        if not sel:
            self._toast("Nessun file selezionato nella lista.", "warning", "⚠️")
            return
        sel_sorted = sorted(set(sel), reverse=True)
        removed = 0
        for idx in sel_sorted:
            try:
                del self._rp_files[idx]
                self._rp_files_listbox.delete(idx)
                removed += 1
            except Exception:  # noqa: BLE001
                continue
        if removed:
            self._toast(f"Rimossi {removed} file", "info", "🗑️")
        try:
            self._quality_lbl.configure(
                text=f"{len(self._rp_files)} file · qualità: DOCUMENTI  📎",
                fg=COLORS["primary_700"])
        except Exception:
            pass

    def _on_rp_compile_from_docs(self) -> None:
        mod = self._selected_rp_module()
        if mod is None:
            self._toast(
                "Seleziona un modulo nella colonna sinistra Moduli prima di compilare da documenti.",
                "warning", "⚠️")
            return
        if not self._rp_files:
            self._toast(
                "Aggiungi almeno un file da usare come sorgente.",
                "warning", "⚠️")
            return
        # Avvia SmartFill dialog passando il contesto gia' caricato
        try:
            self._select_module(mod.slug)
        except Exception:  # noqa: BLE001
            pass
        # Passa al tab DOCUMENTI AI e apri SmartFillDialog
        try:
            self._notebook.select(self._tab_docs)
        except Exception:  # noqa: BLE001
            try:
                self._notebook.select(4)
            except Exception:
                pass
        # Chiamiamo direttamente _on_doc_smart_fill; i file e il modulo sono gia'
        # nello stato della MainWindow; l'utente li riversa con pochi click.
        try:
            self._on_doc_smart_fill()
        except Exception as e:  # noqa: BLE001
            LOG.exception("Errore avvio SmartFill da tab RAPPORTO")
            self._toast(f"Errore avvio compilazione: {e}", "error", "❌")

    # ---------- Quality meter ----------
    def _update_quality(self, *_args) -> None:
        try:
            txt = self._desc_text.get("1.0", "end-1c")
        except Exception:
            return
        n = len(txt)
        if n < 20:
            color = COLORS["danger_600"]
            label = f"{n} caratteri · qualità: BASSA  🔴"
        elif n < 60:
            color = COLORS["warning_600"]
            label = f"{n} caratteri · qualità: MEDIA  🟡"
        else:
            color = COLORS["success_600"]
            label = f"{n} caratteri · qualità: BUONA  🟢"
        try:
            self._quality_lbl.configure(text=label, fg=color)
        except Exception: pass

    # ---------- Button loading animation ----------

    def _start_extract_loading(self, initial_text: str = "Elaborazione…") -> None:
        try:
            self._extract_btn.configure(state="disabled",
                                         text=f"⏳  {initial_text}")
        except Exception: pass
        self._loading_btn_frame = 0
        self._progress.configure(mode="indeterminate")
        try: self._progress.start(60)
        except Exception: pass
        def _tick():
            self._loading_btn_frame = (
                (self._loading_btn_frame + 1) % len(_LOADING_FRAMES))
            ch = _LOADING_FRAMES[self._loading_btn_frame]
            try:
                self._extract_btn.configure(
                    text=f"{ch}  {initial_text}  ·  non chiudere l'app")
            except Exception: pass
            self._loading_btn_after = self.root.after(120, _tick)
        _tick()

    def _stop_extract_loading(self, ok: bool, label: Optional[str] = None) -> None:
        if self._loading_btn_after is not None:
            try: self.root.after_cancel(self._loading_btn_after)
            except Exception: pass
            self._loading_btn_after = None
        try:
            self._progress.stop()
        except Exception: pass
        self._progress.configure(mode="determinate",
                                 value=100 if ok else 0)
        try:
            self._extract_btn.configure(
                state="normal",
                text=(("✅  " + (label or "Estrazione completata")) if ok
                      else ("❌  " + (label or "Estrazione fallita — riprova"))))
        except Exception: pass
        # Restore default after a short while
        def _back():
            try:
                self._extract_btn.configure(
                    text="🚀  Avvia estrazione AI  (Ctrl+E)")
                self._progress.configure(value=0)
            except Exception: pass
        self.root.after(2800, _back)

    # ==================== History tab ====================

    def _build_history_tab(self) -> None:
        frame = self._tab_history
        top = tk.Frame(frame, bg=COLORS["white"])
        top.pack(fill="x", padx=18, pady=(18, 12))
        ttk.Label(top, text="Storico rapporti",
                  style="Title.H2.TLabel").pack(side="left")
        self._history_total_lbl = ttk.Label(
            top, text="0 rapporti", style="Subtitle.TLabel")
        self._history_total_lbl.pack(side="left", padx=(14, 0), pady=(8, 0))

        # ---- FR18 4-controls filter row [Stato | Da | A | Keyword] ----
        filter_row = tk.Frame(frame, bg=COLORS["white"])
        filter_row.pack(fill="x", padx=18, pady=(0, 10))

        tk.Label(filter_row, text="Stato:",
                 bg=COLORS["white"], fg=COLORS["slate_600"],
                 font=FONTS["body"]).pack(side="left")
        self._status_filter_var = tk.StringVar(value="all")
        statuses = [("Tutti", "all"),
                    ("Bozze", "draft"),
                    ("Approvati", "approved"),
                    ("Esportati", "exported"),
                    ("Falliti", "failed")]
        self._status_combo = ttk.Combobox(
            filter_row, textvariable=self._status_filter_var,
            values=[s[0] for s in statuses], state="readonly", width=12)
        self._status_combo.current(0)
        self._status_combo._value_map = {label: val for label, val in statuses}
        self._status_combo._label_map = {val: label for label, val in statuses}
        self._status_combo.pack(side="left", padx=(4, 14))
        self._status_combo.bind(
            "<<ComboboxSelected>>",
            lambda e: self._on_filter_status_change(), add="+")

        tk.Label(filter_row, text="Da:",
                 bg=COLORS["white"], fg=COLORS["slate_600"],
                 font=FONTS["body"]).pack(side="left")
        self._hist_date_from = tk.StringVar(value="")
        self._hist_date_from_entry = tk.Entry(
            filter_row, textvariable=self._hist_date_from,
            width=12, **_tk_text())
        self._hist_date_from_entry.pack(side="left", padx=(4, 14), ipady=3)

        tk.Label(filter_row, text="A:",
                 bg=COLORS["white"], fg=COLORS["slate_600"],
                 font=FONTS["body"]).pack(side="left")
        self._hist_date_to = tk.StringVar(value="")
        self._hist_date_to_entry = tk.Entry(
            filter_row, textvariable=self._hist_date_to,
            width=12, **_tk_text())
        self._hist_date_to_entry.pack(side="left", padx=(4, 14), ipady=3)
        tk.Label(filter_row, text="(YYYY-MM-DD)",
                 bg=COLORS["white"], fg=COLORS["slate_400"],
                 font=("Segoe UI", 8)).pack(side="left", padx=(0, 14))

        tk.Label(filter_row, text="🔍", bg=COLORS["white"],
                 fg=COLORS["slate_400"],
                 font=("Segoe UI", 11), padx=8, pady=3, bd=0,
                 highlightthickness=0).pack(side="left")
        self._hist_search = tk.Entry(filter_row, width=28, **_tk_text())
        self._hist_search.pack(side="left", ipady=3)
        self._hist_search.bind(
            "<KeyRelease>", lambda e: self._schedule_hist_search(), add="+")

        self._refresh_hist_btn = ttk.Button(
            filter_row, text="🔄 Aggiorna",
            style="Subtle.TButton",
            command=self._refresh_history)
        self._refresh_hist_btn.pack(side="right")
        tk.Label(filter_row, text="(Ctrl+F)",
                 bg=COLORS["white"], fg=COLORS["slate_400"],
                 font=("Segoe UI", 8)).pack(side="right", padx=(0, 8))

        # Tree: ALWAYS visible vertical scrollbar.
        tree_card = RoundedCard(frame, padding=0, radius=14, shadow=True)
        tree_card.pack(fill="both", expand=True, padx=18, pady=(4, 18))
        hist_host = tk.Frame(tree_card.content, bg=COLORS["white"])
        hist_host.pack(fill="both", expand=True, padx=4, pady=4)
        self._history_tree = ttk.Treeview(
            hist_host,
            columns=("module", "status", "created", "stamp"),
            show="headings", selectmode="browse", height=16)
        self._history_tree.heading("module", text="Modulo")
        self._history_tree.heading("status", text="Stato")
        self._history_tree.heading("created", text="Data creazione")
        self._history_tree.heading("stamp", text="Cartella")
        self._history_tree.column("module", width=260, anchor="w", minwidth=200)
        self._history_tree.column("status", width=140, anchor="center", minwidth=120)
        self._history_tree.column("created", width=200, anchor="w", minwidth=180)
        self._history_tree.column("stamp", width=300, anchor="w", minwidth=240)
        vsb_hist = ttk.Scrollbar(hist_host, orient="vertical",
                                  command=self._history_tree.yview)
        self._history_tree.configure(yscrollcommand=vsb_hist.set)
        vsb_hist.pack(side="right", fill="y")  # ALWAYS visible
        self._history_tree.pack(side="left", fill="both", expand=True)
        self._history_tree.bind(
            "<Double-1>", self._on_history_double_click, add="+")
        self._hist_search_after: Optional[str] = None
        self._refresh_history()

    def _on_filter_status_change(self) -> None:
        label = self._status_filter_var.get()
        self._status_history_filter = (
            self._status_combo._label_map.get(label, "all"))
        self._refresh_history()

    def _schedule_hist_search(self) -> None:
        if getattr(self, "_hist_search_after", None) is not None:
            try: self.root.after_cancel(self._hist_search_after)
            except Exception: pass
        self._hist_search_after = self.root.after(200, self._refresh_history)

    def _refresh_history(self) -> None:
        # Build 4-controls arguments: status + date_from/date_to + keyword via DB FTS/LIKE
        status = (None if self._status_history_filter == "all"
                  else self._status_history_filter)
        keyword_raw: str = ""
        try:
            keyword_raw = (self._hist_search.get() or "").strip()
        except Exception:  # noqa: BLE001
            keyword_raw = ""
        keyword = keyword_raw or None
        def _norm_date(v: str) -> Optional[str]:
            v = (v or "").strip()
            if not v:
                return None
            if len(v) == 10 and v[4] == "-" and v[7] == "-":
                # Accept YYYY-MM-DD → append 00:00:00 / 23:59:59
                return v
            return None
        date_from = None
        date_to = None
        try:
            date_from = _norm_date(self._hist_date_from.get())
            date_to = _norm_date(self._hist_date_to.get())
        except Exception:  # noqa: BLE001
            date_from = date_to = None
        if date_from:
            date_from = f"{date_from} 00:00:00"
        if date_to:
            date_to = f"{date_to} 23:59:59"
        try:
            rows = self.db.list_reports(
                status=status,
                keyword=keyword,
                date_from=date_from,
                date_to=date_to,
            )
        except Exception:  # noqa: BLE001
            rows = []
        for ch in self._history_tree.get_children(""):
            self._history_tree.delete(ch)
        count = 0
        for r in rows:
            r_mod = (r.get("module") or "")
            count += 1
            status_raw = r.get("status") or "draft"
            tup = _STATUS_STYLES.get(status_raw, _STATUS_STYLES["draft"])
            pretty = tup[0]
            iid = str(r.get("id") or count)
            self._history_tree.insert(
                "", "end", iid=iid,
                values=(r_mod, pretty, r.get("created") or "—",
                        r.get("stamp") or "—"),
                tags=(tup[2],))
        try:
            suffix = ""
            parts = []
            if status is not None:
                parts.append(f"stato={status}")
            if keyword:
                parts.append(f"testo='{keyword}'")
            if date_from or date_to:
                parts.append(f"data {date_from or '…'} → {date_to or '…'}")
            suffix = f" ({'; '.join(parts)})" if parts else ""
            self._history_total_lbl.configure(text=f"{count} rapporti mostrati{suffix}")
        except Exception:  # noqa: BLE001
            pass
        # Status coloring (tree tags)
        tag_colors = {
            "warning": (COLORS["warning_50"],  COLORS["warning_700"]),
            "success": (COLORS["success_50"],  COLORS["success_700"]),
            "neutral": (COLORS["slate_100"],  COLORS["slate_700"]),
            "info":    (COLORS["primary_50"],  COLORS["primary_700"]),
            "error":   (COLORS["danger_50"],   COLORS["danger_700"]),
        }
        for tag, (bg, fg) in tag_colors.items():
            try:
                self._history_tree.tag_configure(tag, background=bg,
                                                 foreground=fg)
            except Exception: pass

    def _on_history_double_click(self, *_e) -> None:
        sel = self._history_tree.selection()
        if not sel: return
        try:
            vals = self._history_tree.item(sel[0], "values")
            stamp = vals[3] if len(vals) >= 4 else ""
            if stamp:
                target = Path(stamp)
                if target.exists():
                    _open_folder(target, self._toast)
                    self._toast(
                        f"Cartella rapporto aperta: {target.name}",
                        "success", "✅")
                else:
                    self._toast(
                        "Cartella rapporto inesistente o spostata.",
                        "warning", "⚠️")
        except Exception as e:
            self._toast(f"Errore apertura: {e}", "error", "❌")

    # ==================== Module tab ====================

    def _build_module_tab(self) -> None:
        frame = self._tab_module
        # Summary card (placeholder)
        self._mod_summary_card = RoundedCard(frame, padding=18, radius=14,
                                             shadow=True,
                                             accent=COLORS["primary_600"])
        self._mod_summary_card.pack(fill="x", padx=18, pady=(18, 12))
        self._render_module_summary(None)

        # Tree (files)
        files_card = RoundedCard(frame, padding=14, radius=14, shadow=True)
        files_card.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        head = tk.Frame(files_card.content, bg=COLORS["white"])
        head.pack(fill="x", pady=(0, 10))
        tk.Label(head, text="📁  Contenuto del modulo",
                 bg=COLORS["white"], fg=COLORS["slate_900"],
                 font=FONTS["h3"]).pack(side="left")
        for txt, cb, style in [
            ("Apri cartella modulo",
             lambda: self._open_selected_folder("root"),
             "Subtle.TButton"),
            ("01 · Vuoto",
             lambda: self._open_selected_folder("01"),
             "Subtle.TButton"),
            ("02 · Riferimenti",
             lambda: self._open_selected_folder("02"),
             "Subtle.TButton"),
            ("03 · Storico",
             lambda: self._open_selected_folder("03"),
             "Subtle.TButton"),
        ]:
            b = ttk.Button(head, text=txt, style=style, command=cb)
            b.pack(side="right", padx=(6, 0))

        files_host = tk.Frame(files_card.content, bg=COLORS["white"])
        files_host.pack(fill="both", expand=True, pady=(4, 0))
        self._module_tree = ttk.Treeview(
            files_host,
            columns=("size", "kind"), show="tree headings",
            selectmode="browse", height=16)
        self._module_tree.heading("#0", text="Nome")
        self._module_tree.heading("size", text="Dimensione")
        self._module_tree.heading("kind", text="Tipo")
        self._module_tree.column("#0", width=360, anchor="w", minwidth=280)
        self._module_tree.column("size", width=140, anchor="e", minwidth=100)
        self._module_tree.column("kind", width=140, anchor="w", minwidth=100)
        vsb_files = ttk.Scrollbar(files_host, orient="vertical",
                                   command=self._module_tree.yview)
        self._module_tree.configure(yscrollcommand=vsb_files.set)
        vsb_files.pack(side="right", fill="y")  # ALWAYS visible
        self._module_tree.pack(side="left", fill="both", expand=True)

    def _open_selected_folder(self, kind: str) -> None:
        try:
            mod = self._selected_module
            if mod is None:
                self._toast("Seleziona prima un modulo dalla lista.",
                            "warning", "⚠️")
                return
            if kind == "root":
                target = mod.folder_path
            elif kind == "01":
                target = mod.template_path.parent
            elif kind == "02":
                target = mod.reference_folder()
            elif kind == "03":
                target = mod.history_folder()
            else:
                target = mod.folder_path
            target.mkdir(parents=True, exist_ok=True)
            _open_folder(target, self._toast)
            self._toast(f"Aperta {target.name}", "success", "📂")
        except Exception as e:
            self._toast(f"Errore: {e}", "error", "❌")

    def _render_module_summary(self, mod: Optional[LoadedModule]) -> None:
        card = self._mod_summary_card
        for ch in card.content.winfo_children():
            try: ch.destroy()
            except Exception: pass
        if mod is None:
            tk.Label(card.content,
                     text="Nessun modulo selezionato",
                     bg=COLORS["white"], fg=COLORS["slate_500"],
                     font=FONTS["h3"]).pack(anchor="w")
            tk.Label(card.content,
                     text=("Seleziona un modulo dal pannello laterale oppure "
                           "creane uno nuovo con Ctrl+N."),
                     bg=COLORS["white"], fg=COLORS["slate_400"],
                     font=FONTS["body"], wraplength=self._wp(980),
                     justify="left").pack(anchor="w", pady=(6, 0))
            return
        tk.Label(card.content, text=f"📋  {mod.name}",
                 bg=COLORS["white"], fg=COLORS["slate_900"],
                 font=FONTS["h2"]).pack(anchor="w")
        tk.Label(card.content, text=(mod.description or "")
                 or "—", bg=COLORS["white"], fg=COLORS["slate_500"],
                 font=FONTS["body"], wraplength=self._wp(980),
                 justify="left").pack(anchor="w", pady=(6, 14))
        try:
            mid = mod.id
            nd = self.db.count_reports(status="draft", module_id=mid) if mid else 0
            ne = self.db.count_reports(status="exported", module_id=mid) if mid else 0
            na = self.db.count_reports(status="approved", module_id=mid) if mid else 0
        except Exception:
            nd, ne, na = 0, 0, 0
        try:
            tpl_exists = (getattr(mod, "template_path", None) is not None
                          and Path(mod.template_path).exists())
            sch_exists = (getattr(mod, "schema", None) is not None)
        except Exception:
            tpl_exists, sch_exists = False, False
        badge_row = tk.Frame(card.content, bg=COLORS["white"])
        badge_row.pack(fill="x", pady=(0, 14))
        def _chip(parent, txt, bgc, fgc):
            c = tk.Frame(parent, bg=bgc, highlightthickness=0, bd=0)
            c.pack(side="left", padx=(0, 8))
            tk.Label(c, text=f"  {txt}  ", bg=bgc, fg=fgc,
                     font=FONTS["body_sm_bold"]).pack(padx=2, pady=4)
            return c
        _chip(badge_row, f"📝 Bozze {nd}",
              COLORS.get("warning_50", COLORS["primary_50"]),
              COLORS.get("warning_800", COLORS["primary_800"]))
        _chip(badge_row, f"✅ Approvati {na}",
              COLORS.get("info_50", COLORS["primary_50"]),
              COLORS.get("info_800", COLORS["primary_800"]))
        _chip(badge_row, f"📤 Esportati {ne}",
              COLORS.get("success_50", COLORS["primary_50"]),
              COLORS.get("success_800", COLORS["primary_800"]))
        _chip(badge_row, f"Template {'OK ✅' if tpl_exists else 'MANCANTE ⚠️'}",
              (COLORS.get("success_50") if tpl_exists else COLORS.get("danger_50")) or COLORS["primary_50"],
              (COLORS.get("success_800") if tpl_exists else COLORS.get("danger_800")) or COLORS["primary_800"])
        _chip(badge_row, f"Schema {'OK 🧱' if sch_exists else 'ASSENTE ⚠️'}",
              (COLORS.get("success_50") if sch_exists else COLORS.get("warning_50")) or COLORS["primary_50"],
              (COLORS.get("success_800") if sch_exists else COLORS.get("warning_800")) or COLORS["primary_800"])
        stats_row = tk.Frame(card.content, bg=COLORS["white"])
        stats_row.pack(fill="x")
        entries = [
            ("slug", mod.slug, "🔖"),
            ("cartella", str(mod.folder_path), "📁"),
            ("template", (mod.template_path.name if getattr(mod, "template_path", None)
                          else "—"), "📄"),
            ("schema",
             "JSON Schema caricato" if getattr(mod, "schema", None)
             else "nessuno schema", "🧱"),
        ]
        for label, value, icon in entries:
            cell = tk.Frame(stats_row, bg=COLORS["white"])
            cell.pack(side="left", fill="x", expand=True)
            tk.Label(cell, text=f"{icon}  {label.upper()}",
                     bg=COLORS["white"], fg=COLORS["slate_400"],
                     font=("Segoe UI", 8, "bold")).pack(anchor="w")
            tk.Label(cell, text=value, bg=COLORS["white"],
                     fg=COLORS["slate_800"],
                     font=FONTS["body"], wraplength=self._wp(480),
                     justify="left").pack(anchor="w")
        self._repopulate_module_tree(mod)

    def _repopulate_module_tree(self, mod: LoadedModule) -> None:
        for ch in self._module_tree.get_children(""):
            self._module_tree.delete(ch)
        try:
            base = mod.folder_path
            def _size(p: Path) -> str:
                try:
                    if p.is_dir():
                        total = 0
                        for sub in p.rglob("*"):
                            try: total += sub.stat().st_size
                            except Exception: pass
                        return f"{total/1024:.1f} KB"
                    return f"{p.stat().st_size/1024:.1f} KB"
                except Exception:
                    return "—"
            def _kind(p: Path) -> str:
                return "cartella" if p.is_dir() else p.suffix.upper()[1:] or "file"
            def _icon(p: Path) -> str:
                if p.is_dir():
                    return "📁"
                ext = p.suffix.lower()
                return {
                    ".docx": "📘", ".xlsx": "📗", ".pdf": "📕",
                    ".json": "🧾", ".txt": "📝", ".png": "🖼️",
                    ".jpg": "🖼️", ".jpeg": "🖼️", ".zip": "🗜️",
                }.get(ext, "📄")
            def _walk(parent_iid: str, folder: Path) -> None:
                items = sorted(folder.iterdir(),
                               key=lambda p: (not p.is_dir(), p.name.lower()))
                for p in items:
                    iid = f"{parent_iid}::{p.name}"
                    label_txt = f"  {_icon(p)}  {p.name}"
                    self._module_tree.insert(
                        parent_iid, "end", iid=iid, text=label_txt,
                        values=(_size(p), _kind(p)), open=False)
                    if p.is_dir():
                        _walk(iid, p)
            base_iid = "root"
            self._module_tree.insert(
                "", "end", iid=base_iid,
                text=f"  📁  {base.name}",
                values=(str(base), "root"), open=True)
            _walk(base_iid, base)
        except Exception:
            pass

    # ==================== Status bar ====================

    def _build_statusbar(self) -> None:
        bar = tk.Frame(self.root, bg=COLORS["slate_900"],
                       padx=10, pady=6, bd=0, highlightthickness=0)
        bar.pack(fill="x", side="bottom")
        # FR4 status bar: 4 sections [LLM state dot | Modulo | Oggi N | Ultima exp ts]
        sep_color = "#334155"
        self._status_labels: Dict[str, tk.Label] = {}

        def _seg(text: str, *, width: int = 14, sticky: str = "w", dot: bool = False) -> tk.Label:
            bg = COLORS["slate_900"]
            fg = COLORS["slate_200"]
            seg_w = tk.Frame(bar, bg=bg)
            seg_w.pack(side="left", fill="y")
            tk.Frame(seg_w, width=1, bg=sep_color, bd=0).pack(side="left", fill="y", padx=(0, 8))
            if dot:
                self._status_dot_canvas = tk.Canvas(seg_w, width=12, height=12,
                                                     bg=bg, highlightthickness=0, bd=0)
                self._status_dot_canvas.pack(side="left", padx=(0, 6), pady=4)
                self._redraw_status_dot()
            lbl = tk.Label(seg_w, text=text, bg=bg, fg=fg, anchor=sticky,
                           width=width, font=("Segoe UI", 9))
            lbl.pack(side="left", fill="y")
            return lbl

        self._status_labels["llm"] = _seg("AI: Inattivo", width=18, dot=True)
        self._status_labels["module"] = _seg("Modulo: (nessuno)", width=28)
        self._status_labels["today"] = _seg("Oggi: 0 rapporti", width=16)
        self._status_labels["last"] = _seg("Ultima esp: —", width=28, sticky="w")

        # Right side: offline branding
        tk.Label(bar, text="Offline · Locale · Privacy first",
                 bg=COLORS["slate_900"], fg=COLORS["slate_500"],
                 font=("Segoe UI", 8, "bold")).pack(side="right", padx=8)
        # Update values immediately
        self._refresh_status_sections()

    def _redraw_status_dot(self) -> None:
        mapping = {
            "idle":  "#64748b",
            "busy":  "#f59e0b",
            "ok":    "#10b981",
            "error": "#dc2626",
        }
        col = mapping.get(self._ai_state, mapping["idle"])
        try:
            c = self._status_dot_canvas
            c.delete("all")
            c.create_oval(1, 1, 11, 11, fill=col, outline="")
        except Exception:  # noqa: BLE001
            pass

    def _set_status(self, msg: str) -> None:
        # Keep legacy status message also via statusbar's last/now toast area? Update today/last fields.
        self._refresh_status_sections()

    # Refresh statusbar labels from current DB state
    def _refresh_status_sections(self) -> None:
        try:
            self._redraw_status_dot()
        except Exception:  # noqa: BLE001
            pass
        labels = getattr(self, "_status_labels", None)
        if not labels:
            return
        try:
            llm_text = {"idle": "AI: Inattivo",
                        "busy": "AI: Elaborazione…",
                        "ok": "AI: OK",
                        "error": "AI: Errore"}.get(self._ai_state, "AI: Inattivo")
            labels["llm"].configure(text=llm_text)
        except Exception:  # noqa: BLE001
            pass
        try:
            mod = self._selected_module
            labels["module"].configure(
                text=f"Modulo: {mod.name}" if mod else "Modulo: (nessuno)")
        except Exception:  # noqa: BLE001
            pass
        try:
            today = time.strftime("%Y-%m-%d")
            n_today = 0
            try:
                rows = self.db.list_reports(status=None, date_from=today + " 00:00:00",
                                            date_to=today + " 23:59:59")
                n_today = len(rows or [])
            except Exception:  # noqa: BLE001
                n_today = 0
            labels["today"].configure(text=f"Oggi: {n_today}")
        except Exception:  # noqa: BLE001
            pass
        try:
            last_ts = self.db.last_report_timestamp() if hasattr(self.db, "last_report_timestamp") else None
            if last_ts:
                text = time.strftime("%d/%m/%Y %H:%M", time.localtime(last_ts))
            else:
                text = "—"
            labels["last"].configure(text=f"Ultima esp: {text}")
        except Exception:  # noqa: BLE001
            pass

    # ==================== Modules list ====================

    def _refresh_modules(self, *_e) -> None:
        try:
            mods = self.mm.list_modules()
        except Exception as e:
            self._toast(f"Errore caricamento moduli: {e}",
                        "error", "❌")
            mods = []
        self._modules = mods
        self._apply_search()
        self._update_home_stats()
        if self._modules:
            msg = f"Caricati {len(self._modules)} moduli."
            if not self._selected_module:
                self._select_module(self._modules[0].slug)
        else:
            msg = ("Nessun modulo trovato. Creane uno nuovo con Ctrl+N"
                   " o importane uno esistente.")
        self._set_status(msg)
        self._toast(msg, "info", "ℹ️")

    def _select_module(self, slug: str) -> None:
        mod = next((m for m in self._modules if m.slug == slug), None)
        self._selected_module = mod
        self._render_module_summary(mod)
        self._update_home_stats()

    def _on_select_module(self, *_e) -> None:
        sel = self._modules_tree.selection()
        if not sel: return
        self._select_module(sel[0])

    def _open_current_module_tab(self) -> None:
        try: self._notebook.select(self._tab_module)
        except Exception: pass

    # ==================== Actions: new module ====================

    def _on_new_module(self) -> None:
        try:
            wizard = tk.Toplevel(self.root)
        except Exception as e:
            self._toast(f"Errore wizard: {e}", "error", "❌")
            return
        self._toplevels_open.append(wizard)
        wizard.title("Nuovo modulo")
        wizard.configure(bg=COLORS["white"])
        wizard.geometry("880x680")
        wizard.minsize(780, 620)
        center_window(wizard, 880, 680)
        wizard.transient(self.root)
        try:
            try:
                _sf = self.root.tk.call("tk", "scaling")
                if _sf and float(_sf) > 0:
                    wizard.tk.call("tk", "scaling", float(_sf))
            except Exception:
                pass
        except Exception:
            pass
        wizard.grab_set()
        try:
            apply_theme(wizard)
        except Exception: pass

        head = GradientCanvas(wizard, COLORS["primary_800"],
                              COLORS["slate_900"], height=92)
        head.pack(fill="x")
        title_f = tk.Frame(wizard, bg=COLORS["primary_800"])
        head.create_window((20, 16), anchor="nw", window=title_f)
        tk.Label(title_f, text="Crea un nuovo modulo di manutenzione",
                 bg=COLORS["primary_800"], fg=COLORS["white"],
                 font=FONTS["h2"]).pack(anchor="w")
        tk.Label(title_f,
                 text="Scegli la modalità di creazione. Puoi usare un modello esistente o partire da zero.",
                 bg=COLORS["primary_800"], fg=COLORS["slate_300"],
                 wraplength=self._wp(780), justify="left",
                 font=FONTS["body_sm"]).pack(anchor="w", pady=(4, 0))

        footer = tk.Frame(wizard, bg=COLORS["slate_50"], padx=24, pady=14)
        footer.pack(fill="x", side="bottom")
        ttk.Label(footer,
                  text="Verrà creata una nuova cartella in workspace/modules/<slug>/ con 01, 02, 03, schema.json, mapping.json e module.json.",
                  style="Small.TLabel", wraplength=self._wp(520)).pack(side="left")
        btns = tk.Frame(footer, bg=COLORS["slate_50"])
        btns.pack(side="right")
        ttk.Button(btns, text="Annulla",
                   style="Subtle.TButton",
                   command=lambda: (
                       wizard.destroy() if wizard in self._toplevels_open
                       else None)).pack(side="right", padx=(8, 0))
        create_btn = ttk.Button(btns, text="Crea modulo",
                                style="Accent.TButton")
        create_btn.pack(side="right")

        scroll_wrap = make_scrollable_frame(wizard, bg=COLORS["white"],
                                            horizontal=False, vertical=True,
                                            show_scrollbars="always",
                                            min_inner_width=800)
        scroll_wrap.outer.pack(fill="both", expand=True, padx=8, pady=(8, 12))
        body = scroll_wrap.inner
        body.configure(bg=COLORS["white"])
        inner_pad = tk.Frame(body, bg=COLORS["white"])
        inner_pad.pack(fill="both", expand=True, padx=20, pady=14)
        tk.Label(inner_pad, text="Passo 1 · Modalità",
                 bg=COLORS["white"], fg=COLORS["slate_700"],
                 font=FONTS["h4"]).pack(anchor="w")
        mode_row = tk.Frame(inner_pad, bg=COLORS["white"])
        mode_row.pack(fill="x", pady=(8, 16))
        for i in range(2): mode_row.columnconfigure(i, weight=1, uniform="mode")
        mode_var: Dict[str, Any] = {"value": None}
        cards: List[RoundedCard] = []
        modes = [
            ("template", "📄  Da file template (DOCX / XLSX)",
             "Carica un file DOCX o XLSX con i campi {{nome_campo}} già inseriti. "
             "Verranno creati schema e mapping automaticamente dal template.",
             COLORS["primary_600"], COLORS["primary_50"]),
            ("empty", "🧱  Modulo vuoto",
             "Parti da uno schema JSON minimo e un modulo vuoto privo di template. "
             "Potrai aggiungere documenti di riferimento successivamente.",
             COLORS["success_600"], COLORS["success_50"]),
        ]
        def _choose(mode, card):
            mode_var["value"] = mode
            for c in cards:
                try:
                    c.canvas.configure(bg=c._outer_bg)
                    c._border = COLORS["slate_200"]
                except Exception: pass
            try:
                card._border = (COLORS["primary_400"]
                                if "primary_400" in COLORS
                                else COLORS["primary_600"])
                card.canvas.configure(bg=lighten(
                    COLORS["primary_400"], 0.85))
            except Exception: pass
            card._redraw()

        for idx, (mode, title, desc, accent, accent50) in enumerate(modes):
            card = RoundedCard(mode_row, padding=18, radius=14, shadow=True)
            card.grid(row=0, column=idx, sticky="nsew", padx=6, pady=6)
            cards.append(card)
            banner = tk.Canvas(card.content, height=56, bg=accent50,
                               highlightthickness=0, bd=0)
            banner.pack(fill="x")
            try:
                banner.create_text(36, 28, text=title.split("  ", 1)[0],
                                   font=("Segoe UI", 20, "bold"), fill=accent)
            except Exception: pass
            tk.Label(card.content, text=title, bg=COLORS["white"],
                     fg=COLORS["slate_900"], font=FONTS["h3"]).pack(
                anchor="w", pady=(14, 4))
            tk.Label(card.content, text=desc, bg=COLORS["white"],
                     fg=COLORS["slate_500"], font=FONTS["body"],
                     wraplength=self._wp(320), justify="left").pack(anchor="w")
            card.bind_click(
                lambda e, m=mode, c=card: _choose(m, c))
            if idx == 0:
                self.root.after(40, lambda m=mode, c=card: _choose(m, c))

        tk.Label(inner_pad, text="Passo 2 · Nome e descrizione",
                 bg=COLORS["white"], fg=COLORS["slate_700"],
                 font=FONTS["h4"]).pack(anchor="w")
        form = tk.Frame(inner_pad, bg=COLORS["white"])
        form.pack(fill="both", expand=True, pady=(8, 16))
        form.columnconfigure(1, weight=1)
        tk.Label(form, text="Nome modulo *", bg=COLORS["white"],
                 fg=COLORS["slate_800"], font=FONTS["body_bold"]).grid(
            row=0, column=0, sticky="e", padx=(0, 10), pady=6)
        name_entry = tk.Entry(form, **_tk_text())
        name_entry.grid(row=0, column=1, sticky="ew", pady=6)
        name_entry.focus_set()

        tk.Label(form, text="Descrizione", bg=COLORS["white"],
                 fg=COLORS["slate_800"], font=FONTS["body_bold"]).grid(
            row=1, column=0, sticky="ne", padx=(0, 10), pady=6)
        desc_text = tk.Text(form, height=5, **_tk_text_multi())
        desc_text.grid(row=1, column=1, sticky="nsew", pady=6)
        form.rowconfigure(1, weight=1)

        tk.Label(form, text="Slug (opzionale)", bg=COLORS["white"],
                 fg=COLORS["slate_800"], font=FONTS["body_bold"]).grid(
            row=2, column=0, sticky="e", padx=(0, 10), pady=6)
        slug_entry = tk.Entry(form, **_tk_text())
        slug_entry.grid(row=2, column=1, sticky="ew", pady=6)

        file_row = tk.Frame(inner_pad, bg=COLORS["white"])
        file_row.pack(fill="x", pady=(0, 10))
        path_var = tk.StringVar(value="(nessun file selezionato)")
        picked: Dict[str, Any] = {"path": None}
        tk.Label(file_row, text="File template:", bg=COLORS["white"],
                 fg=COLORS["slate_800"],
                 font=FONTS["body_bold"]).pack(side="left")
        tk.Label(file_row, textvariable=path_var, bg=COLORS["white"],
                 fg=COLORS["slate_500"], wraplength=self._wp(420), justify="left",
                 font=FONTS["body_sm"]).pack(side="left", padx=10)
        def _pick():
            f = filedialog.askopenfilename(
                title="Scegli template DOCX/XLSX",
                filetypes=[("Template supportati", "*.docx *.xlsx"),
                           ("DOCX", "*.docx"), ("XLSX", "*.xlsx")])
            if f:
                picked["path"] = f
                path_var.set(Path(f).name)
                if not name_entry.get().strip():
                    name_entry.insert(0, Path(f).stem.replace("_", " ").title())
        ttk.Button(file_row, text="Scegli file…",
                   style="Subtle.TButton", command=_pick).pack(side="right")

        def _on_create():
            name = name_entry.get().strip()
            if not name:
                self._toast("Inserisci un nome per il modulo.",
                            "warning", "⚠️")
                name_entry.focus_set(); return
            mode = mode_var["value"]
            if not mode:
                self._toast("Scegli una modalità di creazione.",
                            "warning", "⚠️"); return
            if mode == "template" and not picked["path"]:
                self._toast("Scegli un file DOCX/XLSX come template.",
                            "warning", "⚠️"); return
            slug = slug_entry.get().strip() or None
            description = desc_text.get("1.0", "end-1c").strip() or None
            try:
                create_btn.configure(state="disabled")
                if mode == "template":
                    mod = self.mm.create_module_from_template(
                        name=name, template_file=Path(picked["path"]),
                        slug=slug, description=description)
                else:
                    mod = self.mm.create_module(
                        name=name, template_type="docx",
                        slug=slug, description=description)
            except Exception as e:
                self._toast(f"Errore creazione modulo: {e}",
                            "error", "❌")
                try: create_btn.configure(state="normal")
                except Exception: pass
                return
            self._refresh_modules()
            self._select_module(mod.slug)
            try: self._modules_tree.selection_set(mod.slug)
            except Exception: pass
            try: self._notebook.select(self._tab_module)
            except Exception: pass
            self._toast(f"Modulo creato: {mod.name}", "success", "✅")
            try:
                if wizard in self._toplevels_open:
                    self._toplevels_open.remove(wizard)
                wizard.destroy()
            except Exception: pass
        create_btn.configure(command=_on_create)
        wizard.bind("<Return>", lambda e: _on_create(), add="+")
        wizard.protocol("WM_DELETE_WINDOW", lambda: (
            self._toplevels_open.remove(wizard)
            if wizard in self._toplevels_open else None, wizard.destroy()))

    # ==================== Actions: import ====================

    def _on_import_module(self) -> None:
        path = filedialog.askopenfilename(
            title="Importa modulo (ZIP)",
            filetypes=[("Archivio modulo ZIP", "*.zip")])
        if not path: return
        try:
            mod = self.mm.import_module_zip(Path(path))
        except Exception as e:
            self._toast(f"Import fallito: {e}", "error", "❌")
            return
        self._refresh_modules()
        self._select_module(mod.slug)
        try: self._modules_tree.selection_set(mod.slug)
        except Exception: pass
        self._toast(f"Modulo importato: {mod.name}",
                    "success", "✅")

    # ==================== Actions: extract / pipeline ====================

    def _on_extract(self) -> None:
        mod = self._selected_module
        if mod is None:
            self._toast("Seleziona prima un modulo dal pannello laterale.",
                        "warning", "⚠️")
            try: self._notebook.select(self._tab_report)
            except Exception: pass
            return
        try:
            desc = self._desc_text.get("1.0", "end-1c").strip()
        except Exception:
            desc = ""
        if len(desc) < 10:
            self._toast(
                "Inserisci almeno 10 caratteri nella descrizione.",
                "warning", "⚠️")
            try: self._desc_text.focus_set()
            except Exception: pass
            return
        self._set_ai_state("busy", "Elaborazione…")
        self._start_extract_loading(
            "Lettura contesto e generazione JSON…")
        self._set_status(
            f"Estrazione in corso per il modulo «{mod.name}»…")
        self._unsaved_changes = True
        thread = threading.Thread(
            target=self._pipeline_worker,
            args=(mod, desc,
                  bool(self._var_refs.get()),
                  bool(self._var_hist.get()),
                  float(self._var_temp.get())),
            daemon=True, name="extract-ai")
        thread.start()

    def _pipeline_worker(self, mod: LoadedModule, desc: str,
                         use_refs: bool, use_hist: bool, temp: float):
        def _on_prog(step: int, total: int, msg: str) -> None:
            try:
                self.root.after(0, lambda s=step, t=total, m=msg:
                                self._on_create_draft_progress(s, t, m))
            except Exception:  # noqa: BLE001
                pass
        try:
            outcome: DraftOutcome = self.reports.create_draft(
                mod, desc, on_progress=_on_prog)
            self.root.after(0, lambda: self._after_extract(mod, outcome))
        except Exception as e:
            self.root.after(0, lambda: self._after_extract_error(e))

    def _on_create_draft_progress(self, step: int, total: int, msg: str) -> None:
        try:
            pct = 0 if total <= 0 else int(round(step * 100 / max(total, 1)))
            self._progress.configure(mode="determinate",
                                     maximum=100, value=pct)
        except Exception:  # noqa: BLE001
            pass
        try:
            self._set_status(f"[FASE {step}/{total}] {msg}")
        except Exception:  # noqa: BLE001
            pass

    def _after_extract(self, mod: LoadedModule, outcome: DraftOutcome) -> None:
        self._stop_extract_loading(ok=outcome.error is None,
                                   label=(None if outcome.error is None
                                          else str(outcome.error)[:48]))
        if outcome.error is not None or not outcome.success:
            self._set_ai_state("error", "Errore")
            self._unsaved_changes = False
            self._toast(
                f"Estrazione fallita: {outcome.error or 'dati non validi'}",
                "error", "❌")
            self._set_status(
                f"Errore durante l'estrazione: {outcome.error or 'dati non validi'}")
            return
        self._set_ai_state("ok", "OK")
        self._set_status(
            "Estrazione completata. Apertura finestra di revisione…")
        # Open review dialog, pass module_slug + DB for enum history
        try:
            approved = run_review(
                self.root, mod.schema,
                outcome.data or {},
                module_slug=mod.slug,
                db=self.db,
                title=f"Revisione bozza · {mod.name}"
            )
        except Exception as e:
            self._toast(f"Errore revisione: {e}", "error", "❌")
            self._unsaved_changes = False
            return
        if approved is None:
            self._unsaved_changes = False
            self._toast(
                "Revisione annullata. I dati non sono stati esportati.",
                "info", "ℹ️")
            return
        # Finalize
        self._unsaved_changes = True
        self._progress.configure(mode="determinate", value=30)
        self._start_extract_loading("Esportazione file (JSON/DOCX/XLSX/PDF)…")
        t2 = threading.Thread(
            target=self._finalize_worker,
            args=(mod, outcome.report_id, approved),
            daemon=True, name="finalize-export")
        t2.start()

    def _after_extract_error(self, error: BaseException) -> None:
        self._set_ai_state("error", "Errore")
        self._stop_extract_loading(ok=False, label=str(error)[:48])
        self._toast(f"Errore durante l'estrazione: {error}",
                    "error", "❌")
        self._set_status(f"Errore: {error}")

    def _finalize_worker(self, mod: LoadedModule, report_id: int,
                         approved: Dict[str, Any]):
        try:
            self.reports.approve_draft(report_id, approved)
            json_path, doc_path, pdf_path = self.reports.finalize_exports(
                report_id, mod)
            stamp = json_path.parent
            paths: Dict[str, Optional[Path]] = {
                "json": json_path,
                "pdf": pdf_path,
            }
            if doc_path is not None:
                if mod.template_type == "xlsx":
                    paths["xlsx"] = doc_path
                else:
                    paths["docx"] = doc_path
            self.root.after(0, lambda: self._after_finalize_ok(
                mod, approved, stamp, paths))
        except Exception as e:
            self.root.after(0, lambda: self._after_finalize_err(e))

    def _after_finalize_ok(self, mod: LoadedModule, approved,
                           stamp: Path, paths: Dict[str, Path]):
        self._unsaved_changes = False
        self._stop_extract_loading(
            ok=True, label="Esportazione completata")
        self._last_approved = (mod, approved, stamp)
        self._progress.configure(value=100)
        self._update_home_stats()
        self._refresh_history()
        # Show simple success dialog
        try:
            dlg = tk.Toplevel(self.root)
            self._toplevels_open.append(dlg)
            dlg.title("Esportazione completata")
            dlg.configure(bg=COLORS["white"])
            dlg.geometry("720x620")
            dlg.minsize(640, 560)
            center_window(dlg, 720, 620)
            try:
                try:
                    _sf = self.root.tk.call("tk", "scaling")
                    if _sf and float(_sf) > 0:
                        dlg.tk.call("tk", "scaling", float(_sf))
                except Exception:
                    pass
            except Exception:
                pass
            dlg.transient(self.root)
            dlg.grab_set()
            head = GradientCanvas(dlg, COLORS["success_600"],
                                  COLORS["primary_700"], height=110)
            head.pack(fill="x")
            hf = tk.Frame(dlg, bg=COLORS["success_600"])
            head.create_window((22, 18), anchor="nw", window=hf)
            tk.Label(hf, text="✅  Rapporto esportato",
                     bg=COLORS["success_600"], fg=COLORS["white"],
                     font=FONTS["h2"]).pack(anchor="w")
            tk.Label(hf,
                     text=f"{mod.name} · {stamp.name}",
                     bg=COLORS["success_600"], fg=COLORS["slate_100"],
                     wraplength=self._wp(640), justify="left",
                     font=FONTS["body"]).pack(anchor="w", pady=(4, 0))

            footer = tk.Frame(dlg, bg=COLORS["slate_50"], padx=22, pady=14)
            footer.pack(fill="x", side="bottom")
            def _close():
                try:
                    if dlg in self._toplevels_open:
                        self._toplevels_open.remove(dlg)
                    dlg.destroy()
                except Exception: pass
            ttk.Button(footer, text="Chiudi",
                       style="Subtle.TButton",
                       command=_close).pack(side="right", padx=(8, 0))
            ttk.Button(footer, text="Apri cartella",
                       style="Accent.TButton",
                       command=lambda: (_open_folder(stamp, self._toast),
                                        _close())).pack(side="right")
            ttk.Button(footer, text="Nuovo rapporto",
                       style="Success.TButton",
                       command=lambda: (_close(),
                                        self._desc_text.delete("1.0", "end"),
                                        self._update_quality(),
                                        self._notebook.select(
                                            self._tab_report))).pack(
                side="right", padx=(0, 8))

            scroll_wrap = make_scrollable_frame(dlg, bg=COLORS["white"],
                                                horizontal=False, vertical=True,
                                                show_scrollbars="always",
                                                min_inner_width=660)
            scroll_wrap.pack(fill="both", expand=True, padx=8, pady=(8, 12))
            body = scroll_wrap.inner
            body.configure(bg=COLORS["white"])
            inner_pad = tk.Frame(body, bg=COLORS["white"])
            inner_pad.pack(fill="both", expand=True, padx=20, pady=14)
            tk.Label(inner_pad, text="File prodotti",
                     bg=COLORS["white"], fg=COLORS["slate_700"],
                     font=FONTS["h3"]).pack(anchor="w")
            rows = [
                ("JSON dati approvati",    paths.get("json")),
                ("DOCX da template",       paths.get("docx")),
                ("XLSX da template",       paths.get("xlsx")),
                ("PDF layout MaintenanceAI", paths.get("pdf")),
                ("Cartella esportazione",  stamp),
            ]
            for title, pth in rows:
                if not pth: continue
                row = tk.Frame(inner_pad, bg=COLORS["white"])
                row.pack(fill="x", pady=6)
                left = tk.Frame(row, bg=COLORS["white"])
                left.pack(side="left", fill="x", expand=True)
                tk.Label(left, text=title, bg=COLORS["white"],
                         fg=COLORS["slate_500"], font=FONTS["body_sm"]
                         ).pack(anchor="w")
                tk.Label(left, text=str(pth), bg=COLORS["white"],
                         fg=COLORS["slate_900"], font=FONTS["body_bold"],
                         wraplength=self._wp(520), justify="left").pack(anchor="w")
                op = Path(pth)
                cmd = (lambda p=op: (
                    _open_folder(p if p.is_dir() else p.parent, self._toast),
                    self._toast(f"Aperto: {p.name}", "success", "📂")))
                ttk.Button(row, text="Apri",
                           style="Subtle.TButton",
                           command=cmd).pack(side="right", padx=4)
            dlg.protocol("WM_DELETE_WINDOW", _close)
            self._toast("Esportazione completata con successo.",
                        "success", "✅")
        except Exception as e:
            self._toast(f"Errore dialogo: {e}", "error", "❌")
        self._set_status(
            "Rapporto esportato. Cartella: " + str(stamp.name))

    # ==================== Documenti AI tab ====================

    def _build_documents_tab(self) -> None:
        parent = self._tab_documents
        hdr = tk.Frame(parent, bg=COLORS["white"])
        hdr.pack(fill="x", padx=28, pady=(22, 18))
        tk.Label(hdr, text="📂  Documenti AI",
                 font=FONTS["display"], fg=COLORS["slate_900"],
                 bg=COLORS["white"], anchor="w").pack(fill="x")
        tk.Label(hdr,
                 text=(
                     "Strumenti avanzati per la gestione documentale basata su AI locale. "
                     "Tutte le operazioni lasciano inalterati i file originali e richiedono "
                     "la tua conferma prima di salvare."
                 ),
                 font=FONTS["body"], fg=COLORS["slate_500"],
                 bg=COLORS["white"], anchor="w", justify="left",
                 wraplength=self._wp(900)).pack(fill="x", pady=(4, 0))

        # FR5 Drag&Drop zone (tkinterdnd2 optional, fallback click)
        try:
            allowed_input_exts = {".docx", ".xlsx"}
            blocked = {".docm", ".xlsm", ".exe", ".bat", ".ps1",
                       ".js", ".lnk", ".vbs"}
            self._dnd_frame = DragDropHandlerFrame(
                parent,
                allowed_extensions=allowed_input_exts,
                blocked_extensions=blocked,
                on_file_received=self._on_dragdrop_documents,
                title="📥  Importa documenti nel modulo corrente",
                prompt=("Trascina qui file DOCX o XLSX da importare come documenti "
                        "di riferimento, oppure clicca l'area per sfogliare…"),
            )
            self._dnd_frame.pack(fill="x", padx=28, pady=(6, 14))
        except Exception as exc:  # noqa: BLE001
            LOG.exception("DnD frame init error")
            try:
                lbl = tk.Label(parent, text="Errore DnD: %s" % exc,
                               bg=COLORS["white"], fg=COLORS["danger_700"])
                lbl.pack(fill="x", padx=28, pady=8)
            except Exception:  # noqa: BLE001
                pass

        cards = [
            ("📝", "Creazione documento",
             "Crea una bozza di documento (procedure, istruzioni, relazioni) "
             "leggendo da una cartella di riferimenti e da un eventuale template.",
             COLORS["primary_600"], "primary_50", self._on_doc_create),
            ("✏️", "Modifica documento",
             "Carica PDF, scansioni, immagini o DOCX e descrivi le modifiche. "
             "Verrà creata una NUOVA versione; l'originale non viene toccato.",
             COLORS["violet_600"], "violet_50", self._on_doc_edit),
            ("🔍", "Audit documenti",
             "Analizza una cartella di documenti: contraddizioni, revisioni, "
             "date incoerenti, tracciabilità, dati mancanti, domande aperte.",
             COLORS["warning_600"], "warning_50", self._on_doc_audit),
            ("🛡", "Regole AI",
             "Personalizza le regole per feature o per singolo modulo. "
             "L'AI può solo leggerle; SOLO tu puoi modificarle.",
             COLORS["slate_700"], "slate_100", self._on_doc_rules_picker),
        ]
        grid = tk.Frame(parent, bg=COLORS["white"])
        grid.pack(fill="both", expand=True, padx=28, pady=(6, 32))
        grid.columnconfigure(0, weight=1, uniform="c", minsize=520)
        grid.columnconfigure(1, weight=1, uniform="c", minsize=520)
        for idx, (icon, title, desc, accent, tint, cb) in enumerate(cards):
            r, c = divmod(idx, 2)
            grid.rowconfigure(r, weight=1, uniform="r", minsize=300)
            tint_bg = COLORS.get(tint, COLORS["slate_50"])
            wrap = RoundedCard(grid, padding=1, radius=16,
                               bg=tint_bg, accent=accent)
            wrap.grid(row=r, column=c, padx=10, pady=10, sticky="nsew")
            inner = wrap.content
            inner.configure(bg=COLORS["white"])
            # Make clickable
            for w in (wrap.canvas, inner):
                try:
                    w.bind("<Button-1>", lambda e, cb=cb: cb())
                    w.bind("<Enter>", lambda e, wref=w: wref.configure(cursor="hand2"))
                except Exception:  # noqa: BLE001
                    pass
            top_row = tk.Frame(inner, bg=COLORS["white"])
            top_row.pack(fill="x", padx=18, pady=(18, 8))
            circ = tk.Frame(top_row, width=56, height=56, bg=accent,
                            highlightthickness=0)
            circ.pack(side="left")
            try: circ.configure(width=56, height=56)
            except Exception: pass
            self._theme.hover.attach_circle(circ, accent)
            try:
                tk.Label(circ, text=icon, font=(FONT_FAMILY, 24, "bold"),
                         bg=accent, fg="white").place(relx=0.5, rely=0.5, anchor="center")
            except Exception:
                pass
            rightcol = tk.Frame(top_row, bg=COLORS["white"])
            rightcol.pack(side="left", fill="both", expand=True, padx=(14, 0))
            tk.Label(rightcol, text=title, font=FONTS["h3"],
                     fg=COLORS["slate_900"], bg=COLORS["white"],
                     anchor="w").pack(fill="x")
            tk.Label(rightcol, text=desc, font=FONTS["body_sm"],
                     fg=COLORS["slate_500"], bg=COLORS["white"],
                     anchor="w", justify="left",
                     wraplength=520).pack(fill="x", pady=(2, 0))
            btn_row = tk.Frame(inner, bg=COLORS["white"])
            btn_row.pack(fill="x", padx=18, pady=(10, 18))
            ttk.Button(btn_row, text="Apri strumento →",
                       style="Accent.TButton",
                       command=cb).pack(side="right", padx=(4, 0))

    # ==================== Documenti AI dialog handlers ====================

    def _open_toplevel(self, dlg: tk.Toplevel) -> None:
        self._toplevels_open.append(dlg)
        try:
            dlg.protocol("WM_DELETE_WINDOW",
                         lambda d=dlg: self._close_toplevel(d))
        except Exception:  # noqa: BLE001
            pass

    def _close_toplevel(self, dlg: tk.Toplevel) -> None:
        try:
            if dlg in self._toplevels_open:
                self._toplevels_open.remove(dlg)
            dlg.destroy()
        except Exception:  # noqa: BLE001
            pass

    def _on_doc_create(self) -> None:
        if self.doc_generator is None:
            messagebox.showwarning(
                "Non disponibile",
                "Il servizio di generazione documenti non è attivo.",
                parent=self.root)
            return
        try:
            dlg = DocumentCreationDialog(
                self.root, self.doc_generator, self.rules_manager,
                self.config.exports_root(), self.mm)
            self._open_toplevel(dlg)
            self._set_status("Aperto: Creazione documento.")
        except Exception as e:  # noqa: BLE001
            LOG.exception("Creazione documento UI error")
            self._toast(f"Errore: {e}", "error", "❌")

    def _on_doc_edit(self) -> None:
        if self.doc_modifier is None:
            messagebox.showwarning(
                "Non disponibile",
                "Il servizio di modifica documenti non è attivo.",
                parent=self.root)
            return
        try:
            dlg = DocumentModificationDialog(
                self.root, self.doc_modifier, self.doc_loader,
                self.config.exports_root())
            self._open_toplevel(dlg)
            self._set_status("Aperto: Modifica documento.")
        except Exception as e:  # noqa: BLE001
            LOG.exception("Modifica documento UI error")
            self._toast(f"Errore: {e}", "error", "❌")

    def _on_doc_audit(self) -> None:
        if self.audit_engine is None:
            messagebox.showwarning(
                "Non disponibile",
                "Il servizio di audit documenti non è attivo.",
                parent=self.root)
            return
        try:
            dlg = AuditDialog(self.root, self.audit_engine,
                              self.config.exports_root())
            self._open_toplevel(dlg)
            self._set_status("Aperto: Audit documenti.")
        except Exception as e:  # noqa: BLE001
            LOG.exception("Audit UI error")
            self._toast(f"Errore: {e}", "error", "❌")

    def _on_doc_smart_fill(self) -> None:
        if self.smart_fill_engine is None:
            messagebox.showwarning(
                "Non disponibile",
                "Il servizio di compilazione smart non è attivo.",
                parent=self.root)
            return
        try:
            dlg = SmartFillDialog(
                self.root, self.smart_fill_engine,
                self.rules_manager, self.mm,
                self.config.exports_root())
            self._open_toplevel(dlg)
            self._set_status("Aperto: Compilazione smart da documenti.")
        except Exception as e:  # noqa: BLE001
            LOG.exception("SmartFill UI error")
            self._toast(f"Errore: {e}", "error", "❌")

    def _on_doc_rules_picker(self) -> None:
        if self.rules_manager is None:
            messagebox.showwarning(
                "Non disponibile",
                "Il gestore delle regole AI non è attivo.",
                parent=self.root)
            return
        # Simple picker
        try:
            top = tk.Toplevel(self.root)
            top.title("Regole AI — Scegli")
            top.configure(bg=COLORS["bg"])
            top.geometry("560x520")
            center_window(top, 560, 520)
            top.transient(self.root)
            apply_theme(top)
            self._open_toplevel(top)

            body = tk.Frame(top, bg=COLORS["bg"])
            body.pack(fill="both", expand=True, padx=16, pady=14)
            tk.Label(body, text="Scegli una regola da modificare:",
                     font=FONTS["h2"], fg=COLORS["text"],
                     bg=COLORS["bg"], anchor="w").pack(fill="x")
            tk.Label(body,
                     text="L'AI legge questi file ma NON può modificarli. "
                          "Solo tu puoi salvarli. File vuoti = comportamento standard.",
                     font=FONTS["body_sm"], fg=COLORS["muted"],
                     bg=COLORS["bg"], justify="left",
                     wraplength=520).pack(fill="x", pady=(4, 12))

            nb = ttk.Notebook(body)
            nb.pack(fill="both", expand=True)

            # --- Feature rules tab ---
            ftab = tk.Frame(nb, bg=COLORS["card_bg"])
            nb.add(ftab, text=" Per feature ")
            card1 = RoundedCard(ftab, bg=COLORS["card_bg"])
            card1.pack(fill="both", expand=True, padx=6, pady=6)
            c1 = card1.content
            for key, label in FEATURE_LABELS_IT.items():
                r = tk.Frame(c1, bg=COLORS["card_bg"])
                r.pack(fill="x", pady=3)
                tk.Label(r, text=label, font=FONTS["body_bold"],
                         fg=COLORS["text"], bg=COLORS["card_bg"],
                         anchor="w").pack(side="left", fill="x", expand=True)
                ttk.Button(r, text="Modifica…",
                           style="Secondary.TButton",
                           command=lambda k=key, l=label: (
                               self._close_toplevel(top),
                               self._open_rules_dialog(feature_key=k),
                           )).pack(side="right")

            # --- Module rules tab ---
            mtab = tk.Frame(nb, bg=COLORS["card_bg"])
            nb.add(mtab, text=" Per modulo ")
            card2 = RoundedCard(mtab, bg=COLORS["card_bg"])
            card2.pack(fill="both", expand=True, padx=6, pady=6)
            c2 = card2.content
            try:
                mods = self.mm.list_modules()
            except Exception:  # noqa: BLE001
                mods = []
            if not mods:
                tk.Label(c2, text="(nessun modulo creato)",
                         font=FONTS["body"], fg=COLORS["muted"],
                         bg=COLORS["card_bg"]).pack(padx=10, pady=10)
            for m in mods:
                r = tk.Frame(c2, bg=COLORS["card_bg"])
                r.pack(fill="x", pady=3)
                try:
                    mn = m.name if hasattr(m, "name") else (m["name"] if isinstance(m, dict) else str(m))
                    ms = m.slug if hasattr(m, "slug") else (m["slug"] if isinstance(m, dict) else str(m))
                except Exception:  # noqa: BLE001
                    mn, ms = str(m), str(m)
                tk.Label(r, text=f"{mn}  ({ms})",
                         font=FONTS["body_bold"], fg=COLORS["text"],
                         bg=COLORS["card_bg"], anchor="w", justify="left",
                         wraplength=420).pack(
                             side="left", fill="x", expand=True, padx=(0, 8))
                ttk.Button(r, text="Modifica…",
                           style="Secondary.TButton",
                           command=lambda slug=ms, name=mn: (
                               self._open_rules_module(slug, name, top),
                           )).pack(side="right")
            top.transient(self.root)
        except Exception as e:  # noqa: BLE001
            LOG.exception("Rules picker error")
            self._toast(f"Errore: {e}", "error", "❌")

    def _open_rules_dialog(self, *, feature_key: str = None,
                           module_name: str = None,
                           module_folder: Path = None) -> None:
        try:
            dlg = RulesEditorDialog(
                self.root, self.rules_manager,
                feature_key=feature_key,
                module_name=module_name,
                module_folder=module_folder)
            self._open_toplevel(dlg)
        except Exception as e:  # noqa: BLE001
            self._toast(f"Errore: {e}", "error", "❌")

    def _open_rules_module(self, slug: str, name: str,
                           parent_toplevel: tk.Toplevel) -> None:
        try:
            mod = self.mm.load_module(slug)
        except Exception as e:  # noqa: BLE001
            self._toast(f"Impossibile caricare modulo: {e}", "error", "❌")
            return
        self._close_toplevel(parent_toplevel)
        self._open_rules_dialog(module_name=name or mod.name,
                                module_folder=mod.folder_path)

    def _after_finalize_err(self, err: BaseException) -> None:
        self._stop_extract_loading(ok=False, label=str(err)[:48])
        self._toast(f"Esportazione fallita: {err}", "error", "❌")

    def _on_export_quick(self) -> None:
        # Ctrl+S: open last exported folder if available, else prompt toast
        last = getattr(self, "_last_approved", None)
        if last is not None:
            mod, approved, stamp = last
            if _open_folder(stamp, self._toast):
                self._toast("Aperta ultima cartella esportazione.",
                            "success", "📂")
                return
        self._toast(
            "Nessuna esportazione recente. Avvia un'estrazione (Ctrl+E).",
            "info", "ℹ️")
