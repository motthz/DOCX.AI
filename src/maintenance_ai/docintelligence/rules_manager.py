"""RulesManager: gestione file .txt di regole.

Ogni feature AI e ogni modulo hanno un proprio rules.txt associato:
- Regole interne software (hardcoded, NON modificabili dall'utente)
- Regole feature (leggibili/scrivibili solo dall'utente in <data_root>/rules/<feature>_rules.txt)
- Regole modulo (leggibili/scrivibili solo dall'utente in <module_folder>/rules.txt)
- Richiesta utente (input testuale)

Ordine di priorità (dal più generale al più specifico, l'ultimo vince per
in caso di conflitto semantico):
1. regole interne software
2. regole feature
3. regole modulo
4. richiesta utente

Garantisce:
- file creato vuoto la prima volta (no default)
- persistenti (salvati su disco)
- AI può solo leggere, non modificare MAI
- solo l'utente (via UI) può salvarli
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..security import safe_resolve_name, SecurityError


LEGACY_FEATURE_FILES: Dict[str, str] = {
    "document_creation":  "document_creation_rules.txt",
    "document_edit":      "document_edit_rules.txt",
    "document_audit":     "document_audit_rules.txt",
    "smart_fill":         "smart_fill_rules.txt",
    "report_compilation": "report_compilation_rules.txt",
}

FEATURE_RULES_FILES: Dict[str, str] = {
    "global": "global_ai_rules.txt",
}

GLOBAL_FEATURE_KEY = "global"

FEATURE_LABELS_V2: Dict[str, str] = {
    "global": "Regole AI globali",
}


LOG = logging.getLogger(__name__)


@dataclass
class CombinedRules:
    """Regole combinate a cui si accoda in ordine."""

    internal: str
    feature: str
    module: str

    def all_text(self, separator: str = "\n\n") -> str:
        parts: List[str] = []
        if self.internal.strip():
            parts.append("=== REGOLE INTERNE SOFTWARE ===")
            parts.append(self.internal.strip())
        if self.feature.strip():
            parts.append("=== REGOLE DELLA FEATURE ===")
            parts.append(self.feature.strip())
        if self.module.strip():
            parts.append("=== REGOLE DEL MODULO ===")
            parts.append(self.module.strip())
        return separator.join(parts) if parts else ""


class RulesManager:
    def __init__(self, config_or_root: Any, *, db: Any = None):
        """Accetta: oggetto Config (con resolve_data_path) oppure un Path/str cartella data.
        Il parametro opzionale `db` (Database) serve per la migrazione automatica al
        formato v2 (1 file globale + 1 per modulo) e per il flag `rules_migrated_v2`.
        """
        self.db = db
        if hasattr(config_or_root, "resolve_data_path") and callable(config_or_root.resolve_data_path):
            self.config = config_or_root
            try:
                self.rules_root = Path(config_or_root.resolve_data_path("rules"))
            except Exception:  # noqa: BLE001
                self.rules_root = Path(config_or_root.data_root) / "rules"
        else:
            self.config = None
            self.rules_root = Path(config_or_root) / "rules"
        try:
            self.rules_root.mkdir(parents=True, exist_ok=True)
        except Exception:  # noqa: BLE001
            pass
        self.ensure_feature_rules_exist()
        self._run_migration_v2()

    def _run_migration_v2(self) -> None:
        """Migra i vecchi 5 file feature in `global_ai_rules.txt`.

        Passi:
        1. Se DB disponibile e settings `rules_migrated_v2` == "1" → skip.
        2. Altrimenti: leggi LEGACY_FEATURE_FILES (5), appendi a global con header
           `# ==== MIGRATO DA: <name> ====`; rinomina i legacy in `.rules.bak`.
        3. Salva flag DB = 1 (se DB disponibile); altrimenti scrivo un file
           sentinella `.rules_migrated_v2.marker` nella rules_root.
        """
        try:
            already = False
            try:
                if self.db is not None and hasattr(self.db, "get_setting"):
                    already = (self.db.get_setting("rules_migrated_v2", "0") == "1")
            except Exception:  # noqa: BLE001
                already = False
            if not already:
                sentinel = self.rules_root / ".rules_migrated_v2.marker"
                already = sentinel.is_file()

            if already:
                return

            global_path = self.feature_rules_path(GLOBAL_FEATURE_KEY)
            if global_path is None:
                return

            to_migrate: List[Tuple[str, Path]] = []
            for _k, legacy_fname in LEGACY_FEATURE_FILES.items():
                try:
                    lp = safe_resolve_name(self.rules_root, legacy_fname, allow_subdirs=False)
                except (SecurityError, Exception):
                    lp = self.rules_root / legacy_fname
                if lp.is_file():
                    try:
                        c = lp.read_text(encoding="utf-8") or ""
                    except Exception:  # noqa: BLE001
                        c = ""
                    if c.strip():
                        to_migrate.append((legacy_fname, lp))
            if to_migrate:
                existing_global = ""
                try:
                    if global_path.is_file():
                        existing_global = global_path.read_text(encoding="utf-8") or ""
                except Exception:  # noqa: BLE001
                    existing_global = ""
                chunks: List[str] = []
                if existing_global.strip():
                    chunks.append(existing_global.rstrip())
                for legacy_name, legacy_path in to_migrate:
                    try:
                        content = legacy_path.read_text(encoding="utf-8") or ""
                    except Exception:  # noqa: BLE001
                        content = ""
                    if not content.strip():
                        continue
                    chunks.append("")
                    chunks.append(f"# ==== MIGRATO DA: {legacy_name} ====")
                    chunks.append(content.rstrip())
                merged = "\n".join(chunks).rstrip() + "\n"
                try:
                    tmp = global_path.with_suffix(global_path.suffix + ".tmp")
                    tmp.write_text(merged, encoding="utf-8")
                    tmp.replace(global_path)
                except Exception as exc:  # noqa: BLE001
                    LOG.warning("Scrittura global rules migrato fallita: %s", exc)

                for legacy_name, legacy_path in to_migrate:
                    try:
                        bak = self.rules_root / (legacy_name + ".bak")
                        i = 1
                        while bak.is_file():
                            bak = self.rules_root / f"{legacy_name}.{i}.bak"
                            i += 1
                        legacy_path.rename(bak)
                        LOG.info("Migrated rules backup: %s → %s", legacy_name, bak.name)
                    except Exception as exc:  # noqa: BLE001
                        LOG.warning("Rinomina backup legacy %s fallita: %s", legacy_name, exc)

            try:
                if self.db is not None and hasattr(self.db, "set_setting"):
                    self.db.set_setting("rules_migrated_v2", "1")
            except Exception:  # noqa: BLE001
                pass
            try:
                sentinel = self.rules_root / ".rules_migrated_v2.marker"
                sentinel.write_text(
                    "Rules v2 migration done. 1 file globale + 1 per modulo.\n",
                    encoding="utf-8",
                )
            except Exception:  # noqa: BLE001
                pass
            LOG.info("Regole AI v2 migration completata.")
        except Exception as exc:  # noqa: BLE001
            LOG.warning("Migration v2 rules saltata per errore: %s", exc)

    # --------------------------------------------------------------
    # Bootstrap: crea file vuoti al primo avvio
    # --------------------------------------------------------------
    def ensure_feature_rules_exist(self) -> None:
        for fname in FEATURE_RULES_FILES.values():
            try:
                p = safe_resolve_name(self.rules_root, fname, allow_subdirs=False)
            except (SecurityError, Exception):
                p = self.rules_root / fname
            try:
                if not p.is_file():
                    p.write_text("", encoding="utf-8")
                    LOG.info("Creato file regole vuoto: %s", p)
            except Exception as exc:  # noqa: BLE001
                LOG.warning("Impossibile creare %s: %s", fname, exc)

    def ensure_module_rules_exist(self, module_folder: Path) -> Path:
        """Crea rules.txt vuoto nella cartella del modulo se non esiste.
        Ritorna il path del file.
        """
        folder = Path(module_folder)
        rules_path = folder / "rules.txt"
        try:
            safe_rules = safe_resolve_name(folder, "rules.txt", allow_subdirs=False)
            rules_path = safe_rules
        except (SecurityError, Exception):
            pass
        try:
            if not rules_path.is_file():
                folder.mkdir(parents=True, exist_ok=True)
                rules_path.write_text("", encoding="utf-8")
                LOG.info("Creato rules.txt vuoto nel modulo %s", folder.name)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("Impossibile creare rules.txt nel modulo: %s", exc)
        return rules_path

    # --------------------------------------------------------------
    # Read: usata dall'AI (sola lettura, MAI scrittura
    # --------------------------------------------------------------
    def read_feature_rules(self, feature_key: str) -> str:
        """Legge regole feature.

        Le feature legacy (document_creation/edit/audit/smart_fill/report_compilation)
        vengono redirette al file globale unico (`global_ai_rules.txt`).
        """
        fkey = feature_key if feature_key in FEATURE_RULES_FILES else GLOBAL_FEATURE_KEY
        fname = FEATURE_RULES_FILES.get(fkey, FEATURE_RULES_FILES[GLOBAL_FEATURE_KEY])
        try:
            p = safe_resolve_name(self.rules_root, fname, allow_subdirs=False)
        except (SecurityError, Exception):
            p = self.rules_root / fname
        try:
            if p.is_file():
                return p.read_text(encoding="utf-8") or ""
        except Exception as exc:  # noqa: BLE001
            LOG.warning("Lettura rules fallita %s: %s", fname, exc)
        return ""

    def read_module_rules(self, module_folder: Path) -> str:
        folder = Path(module_folder)
        rules_path = folder / "rules.txt"
        try:
            safe_rules = safe_resolve_name(folder, "rules.txt", allow_subdirs=False)
            rules_path = safe_rules
        except (SecurityError, Exception):
            pass
        try:
            if rules_path.is_file():
                return rules_path.read_text(encoding="utf-8") or ""
        except Exception as exc:  # noqa: BLE001
            LOG.warning("Lettura rules modulo fallita: %s", exc)
        return ""

    def get_combined_rules(
        self,
        feature_key: str,
        module_folder: Optional[Path] = None,
        internal_rules: Optional[str] = None,
    ) -> CombinedRules:
        """Ritorna il blocco regole combinato.
        L'AI chiama questo metodo in SOLA LETTURA. Non salva MAI su file.
        """
        internal = (internal_rules or "").strip()
        feature = self.read_feature_rules(feature_key).strip()
        module = (
            self.read_module_rules(module_folder).strip()
            if module_folder is not None
            else ""
        )
        return CombinedRules(internal=internal, feature=feature, module=module)

    # --------------------------------------------------------------
    # Path lookup (per UI) – mostra percorso file regole corrente
    # --------------------------------------------------------------
    def feature_rules_path(self, feature_key: str) -> Optional[Path]:
        fkey = feature_key if feature_key in FEATURE_RULES_FILES else GLOBAL_FEATURE_KEY
        fname = FEATURE_RULES_FILES.get(fkey, FEATURE_RULES_FILES[GLOBAL_FEATURE_KEY])
        try:
            return safe_resolve_name(self.rules_root, fname, allow_subdirs=False)
        except (SecurityError, Exception):
            return self.rules_root / fname

    def module_rules_path(self, module_folder: Path) -> Path:
        return self.ensure_module_rules_exist(module_folder)

    # --------------------------------------------------------------
    # Write: solo UI-only ( chiamata SOLO dall'utente tramite UI
    # after explicit button).
    # AI CODE MUST NEVER call these methods.
    # They are marked _user_ prefixed to make them grep' for audit).
    # --------------------------------------------------------------
    def user_save_feature_rules(self, feature_key: str, content: str, *, _from_ui: bool = False) -> bool:
        """Solo UI: salva regole feature.

        Audit lock: se `_from_ui=False` l'operazione viene BLOCCATA e loggata
        (l'AI non puo' modificare file regole).
        """
        if not _from_ui:
            LOG.critical(
                "BLOCCATO salvataggio rules feature_key=%s — tentativo non autorizzato "
                "(solo UI puo' salvare; passa _from_ui=True).", feature_key)
            raise PermissionError(
                "Salvataggio regole non consentito al di fuori dell'interfaccia utente."
            )
        fkey = feature_key if feature_key in FEATURE_RULES_FILES else GLOBAL_FEATURE_KEY
        fname = FEATURE_RULES_FILES.get(fkey, FEATURE_RULES_FILES[GLOBAL_FEATURE_KEY])
        try:
            p = safe_resolve_name(self.rules_root, fname, allow_subdirs=False)
        except (SecurityError, Exception):
            p = self.rules_root / fname
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(p.suffix + ".tmp")
            tmp.write_text(content or "", encoding="utf-8")
            tmp.replace(p)
            return True
        except PermissionError:
            raise
        except Exception as exc:  # noqa: BLE001
            LOG.error("Salvataggio rules fallito %s: %s", fname, exc)
            return False

    def user_save_module_rules(self, module_folder: Path, content: str, *, _from_ui: bool = False) -> bool:
        """Solo UI: salva rules.txt del modulo.

        Audit lock: se `_from_ui=False` l'operazione viene BLOCCATA e loggata.
        """
        if not _from_ui:
            LOG.critical(
                "BLOCCATO salvataggio rules modulo=%s — tentativo non autorizzato "
                "(solo UI puo' salvare; passa _from_ui=True).", module_folder)
            raise PermissionError(
                "Salvataggio regole non consentito al di fuori dell'interfaccia utente."
            )
        try:
            rules_path = self.ensure_module_rules_exist(module_folder)
            tmp = rules_path.with_suffix(rules_path.suffix + ".tmp")
            tmp.write_text(content or "", encoding="utf-8")
            tmp.replace(rules_path)
            return True
        except PermissionError:
            raise
        except Exception as exc:  # noqa: BLE001
            LOG.error("Salvataggio rules modulo fallito: %s", exc)
            return False
