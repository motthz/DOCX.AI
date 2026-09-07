"""Module manager: creates, imports, exports, loads module structures.

Each module folder on disk looks like::

    <workspace>/<slug>/
      ├── module.json
      ├── schema.json
      ├── mapping.json
      ├── 01_modulo_vuoto/
      │   └── <template>.(docx|xlsx)
      ├── 02_documenti_riferimento/
      │   └── <docs>.(docx|xlsx)
      └── 03_storico/

All three subfolders are always present. The manager validates paths via security.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

from .security import (
    SecurityError,
    SecurityLimits,
    extract_zip_safe,
    pack_folder_to_zip,
    safe_resolve_name,
    safe_slug,
    sha256_file,
)
from .config import Config
from .db import Database


SUBFOLDERS = ("01_modulo_vuoto", "02_documenti_riferimento", "03_storico")

_PH_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_\.]*)\s*\}\}")


@dataclass
class LoadedModule:
    id: Optional[int]
    slug: str
    name: str
    version: str
    description: str
    folder_path: Path
    template_type: str  # "docx" / "xlsx"
    template_path: Path
    schema_path: Path
    mapping_path: Path
    module_json_path: Path
    schema: Dict[str, Any]
    mapping: Dict[str, Any]
    metadata: Dict[str, Any]

    def reference_folder(self) -> Path:
        return self.folder_path / SUBFOLDERS[1]

    def history_folder(self) -> Path:
        return self.folder_path / SUBFOLDERS[2]


class ModuleManager:
    def __init__(self, config: Config, db: Database, limits: Optional[SecurityLimits] = None):
        self.config = config
        self.db = db
        self.limits = limits or SecurityLimits()
        self.workspace = config.workspace_root()
        self.workspace.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Factory / disk creation
    # ------------------------------------------------------------------
    def create_module(
        self,
        name: str,
        template_type: str,
        *,
        slug: Optional[str] = None,
        description: str = "",
        schema: Optional[Dict[str, Any]] = None,
        mapping: Optional[Dict[str, Any]] = None,
    ) -> LoadedModule:
        slug = safe_slug(slug or name)
        folder = safe_resolve_name(self.workspace, slug, allow_subdirs=False)
        try:
            folder.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            raise SecurityError(f"Modulo già esistente: {slug}")
        for sub in SUBFOLDERS:
            try:
                (folder / sub).mkdir(exist_ok=False)
            except FileExistsError:
                pass

        # rules.txt del modulo: vuoto, persistente, SOLO utente può modificarlo
        try:
            rules_path = folder / "rules.txt"
            if not rules_path.exists():
                rules_path.write_text("", encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

        if template_type not in ("docx", "xlsx"):
            raise ValueError("template_type deve essere 'docx' oppure 'xlsx'")

        module_json = {
            "name": name,
            "slug": slug,
            "version": "1.0.0",
            "description": description or "",
            "template_type": template_type,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        schema = schema or self._minimal_schema(slug)
        mapping = mapping or {}

        module_json_path = folder / "module.json"
        schema_path = folder / "schema.json"
        mapping_path = folder / "mapping.json"
        module_json_path.write_text(json.dumps(module_json, indent=2, ensure_ascii=False), encoding="utf-8")
        schema_path.write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
        mapping_path.write_text(json.dumps(mapping, indent=2, ensure_ascii=False), encoding="utf-8")

        # Create an empty placeholder template file inside 01_modulo_vuoto
        template_name = f"template.{template_type}"
        template_path = folder / SUBFOLDERS[0] / template_name
        self._create_blank_template(template_path, template_type, schema)

        mid = self.db.upsert_module(
            slug=slug,
            name=name,
            version=module_json["version"],
            description=module_json["description"],
            template_type=template_type,
            template_path=str(template_path),
            schema_path=str(schema_path),
            mapping_path=str(mapping_path),
            module_json_path=str(module_json_path),
            folder_path=str(folder),
        )

        return self._build_loaded(mid, slug, name, module_json["version"], description,
                                  folder, template_type, template_path, schema_path,
                                  mapping_path, module_json_path, schema, mapping, module_json)

    # ------------------------------------------------------------------
    # Adaptive: create module FROM an existing DOCX/XLSX template file
    # (zero-code approach — user drops a file, app auto-generates schema)
    # ------------------------------------------------------------------
    def create_module_from_template(
        self,
        name: str,
        template_file: Path,
        *,
        slug: Optional[str] = None,
        description: str = "",
        force_type: Optional[str] = None,
    ) -> LoadedModule:
        """Create a module using an existing DOCX/XLSX as the blank template.

        - Copies ``template_file`` into 01_modulo_vuoto/
        - Scans the file for ``{{placeholder_name}}`` tokens
        - Builds a schema.json automatically: every placeholder is a string field
          (required + default NON_SPECIFICATO semantics applied downstream)
        - For XLSX: additionally builds a mapping.json pointing to each cell where
          a placeholder was found
        """
        template_file = Path(template_file)
        if not template_file.is_file():
            raise FileNotFoundError(f"Template non trovato: {template_file}")
        ext = force_type or template_file.suffix.lower().lstrip(".")
        if ext not in ("docx", "xlsx"):
            raise ValueError(f"Estensione template non supportata: .{ext} (usare .docx o .xlsx)")

        # 1. Extract placeholders and (for XLSX) cell locations
        phs: Set[str]
        xlsx_cell_map: Dict[str, Dict[str, Any]] = {}
        if ext == "docx":
            phs = self._scan_placeholders_docx(template_file)
        else:
            phs, xlsx_cell_map = self._scan_placeholders_xlsx(template_file)

        if not phs:
            raise ValueError(
                "Nessun placeholder {{nome_campo}} rilevato nel template. "
                "Inserire nel documento alcuni segnaposto nel formato {{nome_campo}} "
                "(es. {{data_intervento}}, {{operatore}}, ...) e riprovare."
            )

        # 2. Guess schema: arrays for placeholders whose label sounds plural (heuristic)
        #    and boolean for checkbox-style (prefix chk_ or suffix _si/_no)
        schema = self._guess_schema_from_placeholders(phs)

        # 3. Build mapping for XLSX (DOCX leaves empty {} mapping on purpose)
        mapping: Dict[str, Any] = {}
        if ext == "xlsx":
            for ph, cell_info in xlsx_cell_map.items():
                mapping[ph] = cell_info

        # 4. Create the module structure (no blank template creation since we provide it)
        slug_final = safe_slug(slug or name)
        folder = safe_resolve_name(self.workspace, slug_final, allow_subdirs=False)
        try:
            folder.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            raise SecurityError(f"Modulo già esistente: {slug_final}")
        for sub in SUBFOLDERS:
            try:
                (folder / sub).mkdir(exist_ok=False)
            except FileExistsError:
                pass

        # rules.txt del modulo: vuoto, persistente, SOLO utente può modificarlo
        try:
            rules_path = folder / "rules.txt"
            if not rules_path.exists():
                rules_path.write_text("", encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

        created_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        module_json = {
            "name": name,
            "slug": slug_final,
            "version": "1.0.0",
            "description": (
                description
                or f"Modulo creato da template {template_file.name} ({len(phs)} placeholder rilevati)"
            ),
            "template_type": ext,
            "created_at": created_at,
            "_adaptive": {
                "source_template": template_file.name,
                "placeholders_detected": sorted(phs),
            },
        }

        module_json_path = folder / "module.json"
        schema_path = folder / "schema.json"
        mapping_path = folder / "mapping.json"
        module_json_path.write_text(json.dumps(module_json, indent=2, ensure_ascii=False), encoding="utf-8")
        schema_path.write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
        mapping_path.write_text(json.dumps(mapping, indent=2, ensure_ascii=False), encoding="utf-8")

        # Copy the provided template file into 01_modulo_vuoto/ (keep original filename if possible)
        safe_template_name = safe_resolve_name(
            folder / SUBFOLDERS[0], template_file.name, allow_subdirs=False
        ).name
        template_path = folder / SUBFOLDERS[0] / safe_template_name
        if template_path.exists():
            template_path = folder / SUBFOLDERS[0] / f"template.{ext}"
        shutil.copyfile(template_file, template_path)

        mid = self.db.upsert_module(
            slug=slug_final,
            name=name,
            version=module_json["version"],
            description=module_json["description"],
            template_type=ext,
            template_path=str(template_path),
            schema_path=str(schema_path),
            mapping_path=str(mapping_path),
            module_json_path=str(module_json_path),
            folder_path=str(folder),
        )

        return self._build_loaded(
            mid, slug_final, name, module_json["version"], module_json["description"],
            folder, ext, template_path, schema_path, mapping_path, module_json_path,
            schema, mapping, module_json,
        )

    # ------------------------------------------------------------------
    # Placeholder scanners + schema guesser (adaptive / zero-code)
    # ------------------------------------------------------------------
    def _scan_placeholders_docx(self, path: Path) -> Set[str]:
        from .parsers.docx_parser import extract_text, load_document
        doc = load_document(path)
        ext = extract_text(doc)
        return set(ext.placeholders)

    def _scan_placeholders_xlsx(self, path: Path) -> Tuple[Set[str], Dict[str, Dict[str, Any]]]:
        from .parsers.xlsx_parser import extract_text as xlsx_extract, load_workbook_safe
        wb = load_workbook_safe(path)
        ext = xlsx_extract(wb)
        phs = set(ext.placeholders)
        mapping: Dict[str, Dict[str, Any]] = {}
        # Also record cell locations for auto-mapping
        from openpyxl.utils import get_column_letter
        for ws_name, rows in ext.sheets.items():
            for r_idx, row in enumerate(rows, start=1):
                for c_idx, val in enumerate(row, start=1):
                    if val is None:
                        continue
                    s = str(val)
                    for m in _PH_RE.finditer(s):
                        ph = m.group(1)
                        if ph in mapping:
                            continue
                        mapping[ph] = {
                            "type": "cell",
                            "sheet": ws_name,
                            "cell": f"{get_column_letter(c_idx)}{r_idx}",
                        }
        return phs, mapping

    def _guess_schema_from_placeholders(self, placeholders: Set[str]) -> Dict[str, Any]:
        """Heuristic adaptive schema generator.

        Rules (kept simple so llama.cpp grammar handles them):
        - Default: string (filled with NON_SPECIFICATO downstream)
        - Placeholder prefixed with ``chk_`` or ending with ``_si`` / ``_no`` → boolean
        - Placeholder ending in ``_list``, ``_items``, ``_pezzi`` or with plural ``_i`` / ``_s``
          (Italian) → array of strings
        - Otherwise just strings.

        All top-level properties are marked required.
        """
        props: Dict[str, Any] = {}
        ordered = sorted(placeholders)
        for ph in ordered:
            low = ph.lower()
            if low.startswith("chk_") or low.endswith("_si") or low.endswith("_no"):
                props[ph] = {"type": "boolean"}
            elif (low.endswith("_list") or low.endswith("_items")
                  or low.endswith("_s") or low.endswith("_i")
                  or low.endswith("_pezzi") or "pezzi" in low):
                # Default array of strings. Could be array of objects too, but for v1
                # keep strings — the user can edit schema.json manually afterwards.
                props[ph] = {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "descrizione": {"type": "string"},
                            "quantita": {"type": "string"},
                            "note": {"type": "string"},
                        },
                    },
                }
            else:
                props[ph] = {"type": "string"}

        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "ModuloAdattivo",
            "type": "object",
            "additionalProperties": False,
            "properties": props,
            "required": ordered,
        }

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------
    def load_module(self, slug: str) -> LoadedModule:
        folder = safe_resolve_name(self.workspace, slug, allow_subdirs=False)
        if not folder.exists():
            raise FileNotFoundError(f"Modulo non trovato: {slug}")
        module_json_path = folder / "module.json"
        schema_path = folder / "schema.json"
        mapping_path = folder / "mapping.json"
        for p, label in (
            (module_json_path, "module.json"),
            (schema_path, "schema.json"),
            (mapping_path, "mapping.json"),
        ):
            if not p.exists():
                raise FileNotFoundError(f"File {label} mancante nel modulo {slug}")
        module_json = json.loads(module_json_path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        mapping = json.loads(mapping_path.read_text(encoding="utf-8"))

        template_type = module_json.get("template_type", "")
        template_path = self._find_template(folder, template_type)
        if template_type not in ("docx", "xlsx"):
            template_type = template_path.suffix.lower().lstrip(".") or template_type

        row = self.db.get_module(slug)
        mid = int(row["id"]) if row else None
        if mid is None:
            mid = self.db.upsert_module(
                slug=slug,
                name=module_json.get("name", slug),
                version=module_json.get("version", "1.0.0"),
                description=module_json.get("description", ""),
                template_type=template_type,
                template_path=str(template_path),
                schema_path=str(schema_path),
                mapping_path=str(mapping_path),
                module_json_path=str(module_json_path),
                folder_path=str(folder),
            )
        return self._build_loaded(
            mid,
            module_json.get("slug", slug),
            module_json.get("name", slug),
            module_json.get("version", "1.0.0"),
            module_json.get("description", ""),
            folder,
            template_type,
            template_path,
            schema_path,
            mapping_path,
            module_json_path,
            schema,
            mapping,
            module_json,
        )

    def list_modules(self) -> List[LoadedModule]:
        rows = self.db.list_modules()
        out: List[LoadedModule] = []
        # First load ones on disk: slug dirs under workspace
        disk_slugs = {p.name for p in self.workspace.iterdir() if p.is_dir()}
        db_slugs = {r["slug"] for r in rows}
        for slug in sorted(disk_slugs | db_slugs):
            if slug.startswith("_"):
                continue
            if slug in disk_slugs:
                try:
                    out.append(self.load_module(slug))
                except Exception:
                    pass
        return out

    # ------------------------------------------------------------------
    # Duplicate / Archive / Restore
    # ------------------------------------------------------------------
    def duplicate_module(self, slug: str, *, suffix: str = "-copia") -> LoadedModule:
        mod = self.load_module(slug)
        base_slug = safe_slug(mod.slug + suffix)
        candidate = base_slug
        i = 2
        while True:
            target_dir = self.workspace / candidate
            if not target_dir.exists() and self.db.get_module(candidate) is None:
                break
            candidate = safe_slug(f"{base_slug}-{i}")
            i += 1
        dest = safe_resolve_name(self.workspace, candidate, allow_subdirs=False)
        shutil.copytree(mod.folder_path, dest, symlinks=False)
        # Update module.json name/slug/version
        mod_json_path = dest / "module.json"
        m = json.loads(mod_json_path.read_text(encoding="utf-8"))
        old_name = m.get("name", mod.name)
        m["name"] = f"{old_name} (Copia {time.strftime('%Y-%m-%d %H:%M')})"
        m["slug"] = candidate
        mod_json_path.write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
        schema_path = dest / "schema.json"
        mapping_path = dest / "mapping.json"
        template_path = self._find_template(dest, mod.template_type)
        mid = self.db.upsert_module(
            slug=candidate,
            name=m["name"],
            version=m.get("version", "1.0.0"),
            description=m.get("description", ""),
            template_type=mod.template_type,
            template_path=str(template_path),
            schema_path=str(schema_path),
            mapping_path=str(mapping_path),
            module_json_path=str(mod_json_path),
            folder_path=str(dest),
            archived=0,
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
        return self._build_loaded(
            mid, candidate, m["name"], m.get("version", "1.0.0"),
            m.get("description", ""), dest, mod.template_type, template_path,
            schema_path, mapping_path, mod_json_path, schema, mapping, m,
        )

    def archive_module(self, slug: str) -> None:
        mod = self.load_module(slug)
        archived_root = self.workspace / "_archived"
        archived_root.mkdir(parents=True, exist_ok=True)
        dest = safe_resolve_name(archived_root, slug, allow_subdirs=False)
        if dest.exists():
            ts = time.strftime("%Y%m%d-%H%M%S")
            dest = archived_root / f"{slug}-{ts}"
        shutil.move(str(mod.folder_path), str(dest))
        row = self.db.get_module(slug)
        if row is None:
            return
        self.db.upsert_module(
            slug=slug,
            name=row.get("name", slug),
            version=row.get("version", "1.0.0"),
            description=row.get("description", ""),
            template_type=row.get("template_type", "docx"),
            template_path=row.get("template_path", ""),
            schema_path=row.get("schema_path", ""),
            mapping_path=row.get("mapping_path", ""),
            module_json_path=row.get("module_json_path", ""),
            folder_path=str(dest),
            archived=1,
        )

    def restore_module(self, slug: str) -> LoadedModule:
        row = self.db.get_module(slug)
        folder: Optional[Path] = None
        if row is not None:
            folder = Path(row["folder_path"]) if row.get("folder_path") else None
        if folder is None or not folder.exists():
            # Try to find it in _archived
            archived_root = self.workspace / "_archived"
            for candidate in [
                archived_root / slug,
                *(sorted(archived_root.glob(f"{slug}-*"), reverse=True) if archived_root.exists() else []),
            ]:
                if candidate.exists() and candidate.is_dir():
                    folder = candidate
                    break
        if folder is None or not folder.exists():
            raise FileNotFoundError(f"Non riesco a trovare la cartella per il modulo archiviato: {slug}")
        dest = safe_resolve_name(self.workspace, slug, allow_subdirs=False)
        if dest.exists():
            ts = time.strftime("%Y%m%d-%H%M%S")
            dest = self.workspace / f"{slug}-{ts}"
        shutil.move(str(folder), str(dest))
        # Ripristinare eventuali paths
        schema_path = dest / "schema.json"
        mapping_path = dest / "mapping.json"
        module_json_path = dest / "module.json"
        m = json.loads(module_json_path.read_text(encoding="utf-8"))
        tt = m.get("template_type", "docx")
        template_path = self._find_template(dest, tt)
        mid = self.db.upsert_module(
            slug=slug,
            name=m.get("name", slug),
            version=m.get("version", "1.0.0"),
            description=m.get("description", ""),
            template_type=tt,
            template_path=str(template_path),
            schema_path=str(schema_path),
            mapping_path=str(mapping_path),
            module_json_path=str(module_json_path),
            folder_path=str(dest),
            archived=0,
        )
        return self.load_module(slug)

    # ------------------------------------------------------------------
    # Semantic versioning + snapshot retention
    # ------------------------------------------------------------------
    def bump_version(self, slug: str, *,
                     new_schema: Optional[Dict[str, Any]] = None,
                     new_mapping: Optional[Dict[str, Any]] = None,
                     force: Optional[str] = None) -> str:
        """Bump semver: force = 'major'|'minor'|'patch' or auto-detect diff."""
        mod = self.load_module(slug)
        old_schema = mod.schema
        old_mapping = mod.mapping
        curr = mod.version or "1.0.0"
        curr_m = _SEMVER_RE.match(curr)
        if curr_m is None:
            maj, mn, pt = 1, 0, 0
        else:
            maj = int(curr_m.group(1)); mn = int(curr_m.group(2)); pt = int(curr_m.group(3))

        if force:
            f = force.lower()
            if f == "major":
                maj += 1; mn = 0; pt = 0
            elif f == "minor":
                mn += 1; pt = 0
            else:
                pt += 1
        else:
            new_schema_eff = new_schema if new_schema is not None else old_schema
            new_mapping_eff = new_mapping if new_mapping is not None else old_mapping
            required_set_changed = False
            new_required = set((new_schema_eff or {}).get("required", []))
            old_required = set((old_schema or {}).get("required", []))
            if new_required != old_required:
                required_set_changed = True
            new_props_keys = set((new_schema_eff or {}).get("properties", {}).keys())
            old_props_keys = set((old_schema or {}).get("properties", {}).keys())
            added_optional = (new_props_keys - old_props_keys) - new_required
            # Major = required set changed (any added/removed required field)
            if required_set_changed:
                maj += 1; mn = 0; pt = 0
            elif added_optional:
                mn += 1; pt = 0
            else:
                # Any schema/mapping description-only or non-structural diff: patch
                unchanged = (
                    (new_schema_eff == old_schema) and (new_mapping_eff == old_mapping)
                )
                if unchanged:
                    return curr
                pt += 1
        new_version = f"{maj}.{mn}.{pt}"
        # Write snapshot
        version_dir = mod.folder_path / "_versions"
        snapshot_dir = version_dir / f"v{new_version}"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(mod.module_json_path, snapshot_dir / "module.json")
        shutil.copyfile(mod.schema_path, snapshot_dir / "schema.json")
        shutil.copyfile(mod.mapping_path, snapshot_dir / "mapping.json")
        self._prune_version_snapshots(version_dir)
        # Persist new version + updated files
        m = json.loads(mod.module_json_path.read_text(encoding="utf-8"))
        m["version"] = new_version
        if new_schema is not None:
            mod.schema_path.write_text(json.dumps(new_schema, indent=2, ensure_ascii=False), encoding="utf-8")
        if new_mapping is not None:
            mod.mapping_path.write_text(json.dumps(new_mapping, indent=2, ensure_ascii=False), encoding="utf-8")
        mod.module_json_path.write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
        self.db.upsert_module(
            slug=slug,
            name=m.get("name", mod.name),
            version=new_version,
            description=m.get("description", ""),
            template_type=mod.template_type,
            template_path=str(mod.template_path),
            schema_path=str(mod.schema_path),
            mapping_path=str(mod.mapping_path),
            module_json_path=str(mod.module_json_path),
            folder_path=str(mod.folder_path),
            archived=int(bool(row is not None and row.get("archived", 0)) if (row := self.db.get_module(slug)) else 0),
        )
        return new_version

    @staticmethod
    def _prune_version_snapshots(version_dir: Path, keep: int = 10) -> None:
        if not version_dir.exists():
            return
        try:
            dirs = sorted([d for d in version_dir.iterdir() if d.is_dir() and d.name.startswith("v")])
        except OSError:
            return
        if len(dirs) > keep:
            for d in dirs[:-keep]:
                shutil.rmtree(d, ignore_errors=True)

    # ------------------------------------------------------------------

    def delete_module(self, slug: str) -> None:
        """Delete a module: remove DB row (cascade documents; set null on reports)
        then remove the workspace folder. Raises ValueError if slug not known.
        """
        slug = safe_slug(slug)
        folder = safe_resolve_name(self.workspace, slug, allow_subdirs=False)
        if not folder.exists() and self.db.get_module(slug) is None:
            raise ValueError(f"Modulo sconosciuto: {slug}")
        self.db.delete_module(slug)
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)

    # ------------------------------------------------------------------
    # Import / export ZIP
    # ------------------------------------------------------------------
    def import_module_zip(self, zip_path: Path) -> LoadedModule:
        zip_path = Path(zip_path)
        # Use a temp folder inside workspace to allow a clean rename after validation
        tmp_dir = self.workspace / f"__import__{int(time.time()*1000)}"
        try:
            extract_zip_safe(zip_path, tmp_dir, self.limits)
            # Detect the actual module root: zip may contain module files directly or a wrapper folder
            module_root = self._find_module_root(tmp_dir)
            module_json = json.loads((module_root / "module.json").read_text(encoding="utf-8"))
            slug = safe_slug(module_json.get("slug") or module_json.get("name") or zip_path.stem)
            target = safe_resolve_name(self.workspace, slug, allow_subdirs=False)
            try:
                shutil.move(str(module_root), str(target))
            except FileExistsError:
                raise SecurityError(f"Modulo già esistente: {slug}")
        finally:
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)
        return self.load_module(slug)

    def export_module_zip(self, slug: str, zip_path: Path) -> Path:
        mod = self.load_module(slug)
        zip_path = Path(zip_path)
        pack_folder_to_zip(mod.folder_path, zip_path)
        return zip_path

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def scan_reference_documents(self, mod: LoadedModule) -> List[Path]:
        folder = mod.reference_folder()
        if not folder.exists():
            return []
        out: List[Path] = []
        allowed = set(self.limits.allowed_extensions_input)
        for p in sorted(folder.iterdir()):
            if p.is_file() and p.suffix.lower() in allowed:
                out.append(p)
        return out

    def scan_history_files(self, mod: LoadedModule) -> List[Path]:
        folder = mod.history_folder()
        if not folder.exists():
            return []
        out: List[Path] = []
        for p in sorted(folder.iterdir()):
            if p.is_file() and p.suffix.lower() in (".json",):
                out.append(p)
        return out

    # ------------------------------------------------------------------
    def _build_loaded(self, *args: Any, **kwargs: Any) -> LoadedModule:
        return LoadedModule(*args, **kwargs)

    def _find_template(self, folder: Path, template_type: str) -> Path:
        target_dir = folder / SUBFOLDERS[0]
        if not target_dir.exists():
            raise FileNotFoundError(f"Cartella template mancante: {target_dir}")
        if template_type:
            for p in target_dir.iterdir():
                if p.is_file() and p.suffix.lower() == f".{template_type}":
                    return p
        # Fallback: first file with allowed extension
        allowed = {".docx", ".xlsx"}
        for p in target_dir.iterdir():
            if p.is_file() and p.suffix.lower() in allowed:
                return p
        raise FileNotFoundError(f"Nessun template trovato in {target_dir}")

    def _find_module_root(self, extracted: Path) -> Path:
        if (extracted / "module.json").exists():
            return extracted
        for p in extracted.iterdir():
            if p.is_dir() and (p / "module.json").exists():
                return p
        raise FileNotFoundError("module.json non trovato nell'archivio ZIP del modulo")

    def _minimal_schema(self, slug: str) -> Dict[str, Any]:
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": slug,
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "tipo_intervento": {"type": "string", "const": slug},
                "note": {"type": "string"},
            },
            "required": ["tipo_intervento"],
        }

    def _create_blank_template(self, path: Path, template_type: str, schema: Dict[str, Any]) -> None:
        props = schema.get("properties", {})
        keys = list(props.keys())
        if template_type == "docx":
            import docx
            from docx.shared import Pt
            doc = docx.Document()
            title = doc.add_heading("Modello manutenzione", level=1)
            table = doc.add_table(rows=len(keys) + 1, cols=2, style="Table Grid")
            table.cell(0, 0).text = "Campo"
            table.cell(0, 1).text = "Valore"
            for i, key in enumerate(keys, start=1):
                table.cell(i, 0).text = str(key)
                table.cell(i, 1).text = "{{" + key + "}}"
            doc.add_paragraph("Note: {{note}}")
            doc.save(str(path))
        else:
            from openpyxl import Workbook as XlWb
            wb = XlWb()
            ws = wb.active
            ws.title = "Rapporto"
            ws["A1"] = "Campo"
            ws["B1"] = "Valore"
            for i, key in enumerate(keys, start=2):
                ws.cell(row=i, column=1, value=str(key))
                ws.cell(row=i, column=2, value="{{" + key + "}}")
            wb.save(str(path))
