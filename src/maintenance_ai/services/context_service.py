"""Context selection service.

- Parse DOCX/XLSX reference documents and store plaintext in parsed_cache keyed
  by SHA-256, so re-parsing is avoided when files haven't changed.
- Build a deterministic, keyword-based selection of past reports (from SQLite)
  whose terminology / module kind / keywords match the current description.
  No embeddings, no vector DB: cheap, deterministic, auditable.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config import Config
from ..db import Database
from ..module_manager import LoadedModule, ModuleManager
from ..parsers.docx_parser import extract_text as docx_extract, load_document as docx_load
from ..parsers.xlsx_parser import extract_text as xlsx_extract, load_workbook_safe as xlsx_load
from ..security import sha256_file


TOKEN_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9][\w\-]*", re.UNICODE)


def _tokens(text: str) -> List[str]:
    return [t.lower() for t in TOKEN_RE.findall(text or "")]


_SHA_MEMO: Dict[Tuple[str, int, int], str] = {}


class ContextService:
    def __init__(self, config: Config, db: Database, module_manager: ModuleManager):
        self.config = config
        self.db = db
        self.mm = module_manager

    # ---- Reference documents ------------------------------------------------
    def parse_reference_documents(
        self, mod: LoadedModule
    ) -> List[Tuple[str, str]]:
        """Return list of (filename, extracted_text) for each reference doc."""
        files = self.mm.scan_reference_documents(mod)
        out: List[Tuple[str, str]] = []
        for p in files:
            text, _meta = self._parse_with_cache(p, mod.id)
            if text:
                out.append((p.name, text))
        return out

    def parse_template_text(self, mod: LoadedModule) -> Tuple[str, str]:
        p = mod.template_path
        text, meta = self._parse_with_cache(p, mod.id, kind="template")
        return p.name, text

    def _parse_with_cache(
        self, path: Path, module_id: Optional[int], kind: str = "reference"
    ) -> Tuple[str, Dict[str, Any]]:
        path = Path(path)
        if not path.exists():
            return "", {}
        st = path.stat()
        size = st.st_size
        # hash ricalcolato solo se il file e' cambiato (dimensione o data di modifica)
        memo_key = (str(path), size, st.st_mtime_ns)
        sha = _SHA_MEMO.get(memo_key)
        if sha is None:
            sha = sha256_file(path)
            _SHA_MEMO[memo_key] = sha
        cached = self.db.cache_get(sha)
        if cached is not None:
            text, meta = cached
            # Refresh documents table row if applicable
            if module_id is not None:
                self.db.upsert_document(
                    module_id=module_id,
                    kind=kind,
                    path=str(path),
                    sha256=sha,
                    size_bytes=size,
                    parsed_text=text[:200000],
                )
            return text, meta
        ext = path.suffix.lower()
        if ext == ".docx":
            doc = docx_load(path)
            data = docx_extract(doc)
            text = data.full_text
            meta = {"placeholders": data.placeholders, "meta": data.meta}
        elif ext == ".xlsx":
            wb = xlsx_load(path)
            data = xlsx_extract(wb)  # type: ignore[assignment]
            try:
                wb.close()
            except Exception:  # noqa: BLE001
                pass
            text = data.full_text
            meta = {"placeholders": data.placeholders, "meta": data.meta}
        else:
            loader = getattr(self, "doc_loader", None)
            if loader is None:
                return "", {}
            try:  # PDF, TXT, immagini: DocumentLoader (cache + OCR per le scansioni)
                loaded = loader.load_file(path, run_ocr=True)
            except Exception:  # noqa: BLE001
                return "", {}
            text = getattr(loaded, "full_text", "") or ""
            meta = {"loader": True}
        text = text[:500000]
        self.db.cache_store(sha, kind, text, meta)
        if module_id is not None:
            self.db.upsert_document(
                module_id=module_id,
                kind=kind,
                path=str(path),
                sha256=sha,
                size_bytes=size,
                parsed_text=text[:200000],
            )
        return text, meta

    # ---- Historical context selection --------------------------------------
    def select_history_snippets(
        self,
        mod: LoadedModule,
        operator_description: str,
        *,
        max_snippets: int = 4,
        max_age_days: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Deterministically pick a few approved past reports from SQLite.

        Scoring: keyword overlap (description tokens vs stored input_description
        tokens) + recency tiebreaker. The picked items are formatted for the
        prompt: {input, final_json} dicts.
        """
        if not operator_description:
            return []
        rows = self.db.list_reports(module_id=mod.id, status="approved", limit=400)
        if not rows:
            return []
        query_tokens = set(_tokens(operator_description))
        # Augment with tokens extracted from reference docs (terminology boost)
        try:
            ref = self.parse_reference_documents(mod)
            for _, txt in ref:
                query_tokens.update(_tokens(txt)[:200])
        except Exception:  # noqa: BLE001
            pass
        now = time.time()
        scored: List[Tuple[int, float, Any]] = []
        for row in rows:
            inp = row["input_description"] or ""
            if max_age_days is not None and row["created_at"]:
                try:
                    t = time.mktime(time.strptime(row["created_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                    age_days = (now - t) / 86400.0
                    if age_days > max_age_days:
                        continue
                except Exception:  # noqa: BLE001
                    pass
            overlap = query_tokens & set(_tokens(inp))
            score = len(overlap)
            if score <= 0:
                continue
            # Minor recency boost: newer row slightly higher
            try:
                created = row["created_at"] or ""
                created_order = created[:10]
                recency = (time.mktime(time.strptime(created_order, "%Y-%m-%d")) if created_order else 0) / 1e12
            except Exception:  # noqa: BLE001
                recency = 0
            scored.append((score, recency, row))
        scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
        picked = scored[:max_snippets]
        out: List[Dict[str, Any]] = []
        for _s, _r, row in picked:
            try:
                final_json = row["final_json"] or "{}"
                if isinstance(final_json, str):
                    data = json.loads(final_json)
                else:
                    data = dict(final_json or {})
            except Exception:  # noqa: BLE001
                data = {}
            out.append({"input": row["input_description"] or "", "final_json": data})
        return out
