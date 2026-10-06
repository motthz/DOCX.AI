"""Configuration loader for DOCX.AI.

Loads default.json, resolves paths (relative to application root or %LOCALAPPDATA%),
exposes LLM profile selector. The loader works both when running from source and
when packaged via PyInstaller.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import __version__


APP_DIR_ENV_VAR = "DOCX_AI_APP_DIR"
DATA_DIR_ENV_VAR = "DOCX_AI_DATA_DIR"


def _app_root() -> Path:
    """Return the application root directory.

    Search strategy:
    1. APP_DIR_ENV_VAR override if set.
    2. Frozen (PyInstaller): parent of sys.executable.
    3. Walk up from __file__ looking for a folder that contains
       ``config/default.json`` or a ``VERSION.txt`` sibling/ancestor.
    4. Fall back to 3 levels up from this file (standard layout).
    """
    env = os.environ.get(APP_DIR_ENV_VAR)
    if env:
        return Path(env).resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # Walk upward from this file
    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / "config" / "default.json").is_file() or (
            candidate / "VERSION.txt"
        ).is_file():
            return candidate
    return Path(__file__).resolve().parents[3]


def _default_data_dir(app_name: str) -> Path:
    env = os.environ.get(DATA_DIR_ENV_VAR) or os.environ.get("MAINTENANCE_AI_DATA_DIR")
    if env:
        return Path(env).resolve()
    from .datadir import configured_data_dir
    chosen = configured_data_dir()
    if chosen is not None:
        return chosen
    localapp = os.environ.get("LOCALAPPDATA")
    if localapp:
        return Path(localapp) / app_name
    return _app_root() / "user_data"


@dataclass
class Config:
    raw: Dict[str, Any]
    app_root: Path
    data_root: Path

    # Frequently accessed, cached
    app_name: str = "DOCX.AI"
    language: str = "it-IT"
    version: str = __version__

    llm_profile: str = "balanced"
    llm_effective: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, config_path: Optional[Path] = None) -> "Config":
        root = _app_root()
        if config_path is None:
            candidate = root / "config" / "default.json"
            if not candidate.is_file() and getattr(sys, "frozen", False):
                # PyInstaller onedir puts data files into <exe_dir>/_internal/* by
                # default. We keep `root` pointing at <exe_dir> so resolve_app_path
                # still points at user-visible models/ and runtime/ folders.
                alt = root / "_internal" / "config" / "default.json"
                if alt.is_file():
                    candidate = alt
            config_path = candidate
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        with open(config_path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)

        app_cfg = raw.get("app", {})
        app_name = app_cfg.get("name", "DOCX.AI")
        data_root = _default_data_dir(app_name)
        data_root.mkdir(parents=True, exist_ok=True)
        for sub in ("logs", "exports", "backups", "workspace", "workspace/modules"):
            (data_root / sub).mkdir(parents=True, exist_ok=True)

        cfg = cls(
            raw=raw,
            app_root=root,
            data_root=data_root,
            app_name=app_name,
            language=app_cfg.get("language", "it-IT"),
            version=__version__,  # unica fonte: docx_ai/__init__.py
        )
        cfg._recompute_llm_profile()
        return cfg

    # ---- Path resolvers ----
    def resolve_app_path(self, relative: str) -> Path:
        if not relative:
            return self.app_root
        p = Path(relative)
        if p.is_absolute():
            return p
        return self.app_root / p

    def resolve_ai_path(self, relative: str) -> Path:
        """Resolve runtime/model paths.

        AI components downloaded from inside the app live in the (writable)
        data dir, while a portable/dev layout may ship them next to the exe.
        The data dir wins; if nothing exists yet, the data dir path is returned
        so that error messages and the installer point to the writable place.
        """
        if not relative:
            return self.data_root
        p = Path(relative)
        if p.is_absolute():
            return p
        for base in (self.data_root, self.app_root):
            cand = base / p
            if cand.exists():
                return cand
        return self.data_root / p

    def ai_components_status(self) -> Dict[str, Any]:
        """Return which local AI components are present on disk."""
        eff = self.llm_effective
        runtime = self.resolve_ai_path(eff.get("runtime_dir", "runtime/llama")) / eff.get(
            "runtime_exe", "llama-server.exe")
        model = self.resolve_ai_path(eff["model"]) if eff.get("model") else None
        fallback = self.resolve_ai_path(eff["fallback_model"]) if eff.get("fallback_model") else None
        installed = self.installed_chat_models()
        if installed:  # mostra i modelli che verranno usati davvero
            model = installed[0]
            fallback = installed[1] if len(installed) > 1 else fallback
        return {
            "runtime": runtime,
            "runtime_ok": runtime.is_file(),
            "model": model,
            "model_ok": bool(model and model.is_file()),
            "fallback": fallback,
            "fallback_ok": bool(fallback and fallback.is_file()),
        }

    def installed_chat_models(self) -> List[Path]:
        """Modelli di chat installati, in ordine di preferenza.

        Prima un eventuale modello personalizzato indicato nella configurazione, poi
        quelli noti dal piu' capace al piu' leggero: installando il 4B l'app lo usa
        al posto dell'1.7B senza altre impostazioni. Il profilo "compatibility"
        mantiene il proprio modello (leggero) per primo.
        """
        from .llm.ai_installer import MODELS

        eff = self.llm_effective
        model_dir = eff.get("model_dir", "models")
        configured = [eff[k] for k in ("model", "fallback_model") if eff.get(k)]
        known = [f"{model_dir}/{name}" for name in MODELS]
        if self.llm_profile in ("compatibility", "fastest"):  # modello veloce per primo
            order = configured + known
        else:
            custom = [m for m in configured if Path(m).name not in MODELS]
            order = custom + known + configured
        out: List[Path] = []
        for rel in order:
            path = self.resolve_ai_path(rel)
            if path.is_file() and path not in out:
                out.append(path)
        return out

    def resolve_data_path(self, relative: str) -> Path:
        if not relative:
            return self.data_root
        p = Path(relative)
        if p.is_absolute():
            return p
        return self.data_root / p

    def workspace_root(self) -> Path:
        return self.data_root / "workspace" / "modules"

    def db_path(self) -> Path:
        return self.data_root / self.raw.get("db", {}).get("filename", "docx_ai.db")

    def exports_root(self) -> Path:
        return self.data_root / "exports"

    def logs_root(self) -> Path:
        return self.data_root / "logs"

    # ---- LLM profile handling ----
    def _recompute_llm_profile(self) -> None:
        llm = self.raw.get("llm", {})
        self.llm_profile = llm.get("profile", "balanced")
        profiles = llm.get("profiles", {})
        base: Dict[str, Any] = {
            "backend": llm.get("backend", "llama_server"),
            "ollama_url": llm.get("ollama_url", "http://127.0.0.1:11434"),
            "ollama_model": llm.get("ollama_model", "qwen3:4b"),
            "runtime_dir": llm.get("runtime_dir", "runtime/llama"),
            "runtime_exe": llm.get("runtime_exe", "llama-server.exe"),
            "model_dir": llm.get("model_dir", "models"),
            "model": llm.get("model"),
            "fallback_model": llm.get("fallback_model"),
            "context_size": llm.get("context_size", 8192),
            "host": llm.get("host", "127.0.0.1"),
            "port_min": llm.get("port_min", 39280),
            "port_max": llm.get("port_max", 39299),
            "no_webui": llm.get("no_webui", True),
            "no_think": llm.get("no_think", True),
            "max_retries": llm.get("max_retries", 3),
            "debug": llm.get("debug", False),
            "thread_override": None,
        }
        profile = profiles.get(self.llm_profile, {})
        for key, value in profile.items():
            if value is not None:
                base[key] = value
        self.llm_effective = base

    def set_profile(self, name: str) -> None:
        profiles = self.raw.get("llm", {}).get("profiles", {})
        if name not in profiles:
            raise ValueError(f"Unknown LLM profile: {name}")
        self.raw["llm"]["profile"] = name
        self._recompute_llm_profile()

    @property
    def llm_profiles(self) -> Dict[str, Dict[str, Any]]:
        return self.available_profiles()

    def available_profiles(self) -> Dict[str, Dict[str, Any]]:
        return dict(self.raw.get("llm", {}).get("profiles", {}))

    # ---- Security thresholds ----
    def security_limits(self) -> Dict[str, Any]:
        sec = self.raw.get("security", {})
        return {
            "max_input_file_mb": sec.get("max_input_file_mb", 25),
            "max_archive_uncompressed_mb": sec.get("max_archive_uncompressed_mb", 100),
            "max_archive_entries": sec.get("max_archive_entries", 5000),
            "allowed_extensions_input": list(sec.get("allowed_extensions_input", [".docx", ".xlsx"])),
            "blocked_extensions": list(sec.get("blocked_extensions", [])),
        }

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Generic top-level key lookup into raw config (name matches DB.settings
        so the UI can interchange `cfg` entries with the config layer)."""
        for path in (("app", key), ("llm", key), ("build", key), ("build_info", key)):
            cur: Any = self.raw
            ok = True
            for part in path:
                if isinstance(cur, dict) and part in cur:
                    cur = cur[part]
                else:
                    ok = False
                    break
            if ok:
                return cur
        return self.raw.get(key, default)

    # ---- UI ----
    def ui_config(self) -> Dict[str, Any]:
        return dict(self.raw.get("ui", {}))
