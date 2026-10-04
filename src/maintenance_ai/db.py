"""SQLite storage with deterministic migrations.

Tables:
  - schema_migrations
  - modules
  - documents
  - reports
  - settings
  - parsed_cache   (SHA-256 keyed cache of parsed text from templates/reference docs)
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterable, Iterator, List, Optional, Tuple


SCHEMA_VERSION = 4


_ALLOWED_MODULE_COLUMNS: FrozenSet[str] = frozenset({
    "id", "slug", "name", "version", "description", "template_type",
    "template_path", "schema_path", "mapping_path", "module_json_path",
    "folder_path", "created_at", "updated_at", "archived",
})

_ALLOWED_DOCUMENT_COLUMNS: FrozenSet[str] = frozenset({
    "id", "module_id", "kind", "path", "sha256", "size_bytes",
    "parsed_text", "created_at",
})

_ALLOWED_REPORT_COLUMNS: FrozenSet[str] = frozenset({
    "id", "module_id", "module_version", "status", "created_at",
    "approved_at", "input_description", "draft_json", "final_json",
    "model_filename", "model_sha256", "llama_build", "output_json_path",
    "output_document_path", "output_pdf_path", "source_document_hashes",
    "review_notes",
})

_ALLOWED_AIOPS_COLUMNS: FrozenSet[str] = frozenset({
    "id", "feature", "timestamp", "files_json", "operation",
    "sources_json", "model", "outcome", "error", "retry_count",
})

_ALLOWED_TAGS_COLUMNS: FrozenSet[str] = frozenset({
    "id", "name", "color",
})

_ALLOWED_REPORTTAGS_COLUMNS: FrozenSet[str] = frozenset({
    "report_id", "tag_id",
})

_ALLOWED_CHUNKS_COLUMNS: FrozenSet[str] = frozenset({
    "id", "file_sha256", "chunk_index", "page", "sheet",
    "cell_ref", "paragraph_index", "chunk_text", "keywords_json", "created_at",
})

_SQL_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _row_to_dict(row: Any) -> Dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    try:
        return {k: row[k] for k in row.keys()}
    except Exception:
        return dict(row)


def _assert_valid_columns(table: str, allowed: FrozenSet[str],
                          field_names: Iterable[str]) -> None:
    for name in field_names:
        if not isinstance(name, str):
            raise ValueError(f"Invalid column identifier type for table {table}: {type(name).__name__}")
        if not _SQL_IDENT_RE.match(name):
            raise ValueError(f"Invalid column identifier format for table {table}: {name!r}")
        if name not in allowed:
            raise ValueError(f"Unknown column {name!r} for table {table}")


_MIGRATIONS = [
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS modules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        slug TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        version TEXT NOT NULL DEFAULT '1.0.0',
        description TEXT DEFAULT '',
        template_type TEXT NOT NULL,   -- docx / xlsx
        template_path TEXT NOT NULL,
        schema_path TEXT NOT NULL,
        mapping_path TEXT NOT NULL,
        module_json_path TEXT NOT NULL,
        folder_path TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        module_id INTEGER,
        kind TEXT NOT NULL,              -- template / reference / history
        path TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        size_bytes INTEGER NOT NULL,
        parsed_text TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        FOREIGN KEY (module_id) REFERENCES modules(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_documents_module ON documents(module_id);
    CREATE INDEX IF NOT EXISTS idx_documents_sha ON documents(sha256);

    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        module_id INTEGER,
        module_version TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'draft',  -- draft / approved / exported
        created_at TEXT NOT NULL,
        approved_at TEXT,
        input_description TEXT NOT NULL,
        draft_json TEXT,
        final_json TEXT,
        model_filename TEXT,
        model_sha256 TEXT,
        llama_build TEXT,
        output_json_path TEXT,
        output_document_path TEXT,
        output_pdf_path TEXT,
        source_document_hashes TEXT,
        FOREIGN KEY (module_id) REFERENCES modules(id) ON DELETE SET NULL
    );
    CREATE INDEX IF NOT EXISTS idx_reports_module ON reports(module_id);
    CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status);
    CREATE INDEX IF NOT EXISTS idx_reports_created ON reports(created_at);

    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    );

    CREATE TABLE IF NOT EXISTS parsed_cache (
        sha256 TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        text TEXT NOT NULL,
        meta TEXT DEFAULT '{}',
        created_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_operations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        feature TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        files_json TEXT DEFAULT '[]',
        operation TEXT DEFAULT '',
        sources_json TEXT DEFAULT '[]',
        model TEXT DEFAULT '',
        outcome TEXT NOT NULL,
        error TEXT DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_aiops_feature ON ai_operations(feature);
    CREATE INDEX IF NOT EXISTS idx_aiops_ts ON ai_operations(timestamp);

    CREATE TABLE IF NOT EXISTS document_chunks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_sha256 TEXT NOT NULL,
        chunk_index INTEGER NOT NULL,
        page INTEGER,
        sheet TEXT,
        cell_ref TEXT,
        paragraph_index INTEGER,
        chunk_text TEXT NOT NULL,
        keywords_json TEXT DEFAULT '[]',
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_chunks_sha ON document_chunks(file_sha256);
    CREATE INDEX IF NOT EXISTS idx_chunks_page ON document_chunks(page);
    """,
    """
    -- Migration v3: tags, archived flag, review notes
    CREATE TABLE IF NOT EXISTS tags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        color TEXT NOT NULL DEFAULT '#60a5fa'
    );
    CREATE TABLE IF NOT EXISTS report_tags (
        report_id INTEGER NOT NULL,
        tag_id INTEGER NOT NULL,
        PRIMARY KEY (report_id, tag_id),
        FOREIGN KEY (report_id) REFERENCES reports(id) ON DELETE CASCADE,
        FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_reporttags_tag ON report_tags(tag_id);

    ALTER TABLE modules ADD COLUMN archived INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE reports ADD COLUMN review_notes TEXT DEFAULT '';
    """,
    """
    -- Migration v4: ai_operations.retry_count + FTS5 (se disponibile)
    ALTER TABLE ai_operations ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0;
    """,
]


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


_FTS5_AVAILABLE: Optional[bool] = None


def _is_fts5_available(conn: sqlite3.Connection) -> bool:
    global _FTS5_AVAILABLE
    if _FTS5_AVAILABLE is not None:
        return _FTS5_AVAILABLE
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_probe USING fts5(x)")
        conn.execute("DROP TABLE IF EXISTS _fts5_probe")
        _FTS5_AVAILABLE = True
    except sqlite3.Error:
        _FTS5_AVAILABLE = False
    return _FTS5_AVAILABLE


class Database:
    recovery_message: Optional[str] = None

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._txn_depth = 0
        self._conn = self._safe_connect()
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON")
            # WAL non funziona su condivisioni di rete (SMB): li' usa DELETE.
            from .datadir import is_network_path
            mode = "DELETE" if is_network_path(self.db_path) else "WAL"
            try:
                self._conn.execute(f"PRAGMA journal_mode = {mode}")
            except sqlite3.Error:
                pass
            if mode == "DELETE":
                try:
                    self._conn.execute("PRAGMA mmap_size = 0")
                except sqlite3.Error:
                    pass
            try:
                self._conn.execute("PRAGMA synchronous = NORMAL")
            except sqlite3.Error:
                pass
            try:
                self._conn.execute("PRAGMA busy_timeout = 30000")
            except sqlite3.Error:
                pass
            try:
                self._conn.execute("PRAGMA cache_size = -64000")
            except sqlite3.Error:
                pass
            try:
                self._conn.execute("PRAGMA temp_store = MEMORY")
            except sqlite3.Error:
                pass
            if mode == "WAL":
                try:
                    self._conn.execute("PRAGMA mmap_size = 1073741824")
                except sqlite3.Error:
                    pass
            self._ensure_migrations()
            self._ensure_fts5()

    def _safe_connect(self) -> sqlite3.Connection:
        """Try sqlite3.connect; on DatabaseError, backup corrupted file + rebuild + restore last backup."""
        try:
            return sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=30,
            )
        except (sqlite3.DatabaseError, sqlite3.Error) as initial_exc:
            bad_msg = str(initial_exc).lower()
            is_malformed = ("malformed" in bad_msg) or (self.db_path.exists() and self.db_path.stat().st_size == 0)
            if not is_malformed:
                raise
            import logging
            LOG = logging.getLogger(__name__)
            LOG.critical("Database corrotto: %s (%s). Avvio recovery.", self.db_path, initial_exc)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            try:
                bad_backup = self.db_path.parent / f"{self.db_path.name}.CORRUPTED-{stamp}.bak"
                if self.db_path.exists():
                    self.db_path.replace(bad_backup)
                LOG.critical("Corrotto salvato come: %s", bad_backup)
            except Exception as rename_err:  # noqa: BLE001
                LOG.critical("Impossibile rinominare DB: %s", rename_err)
            try:
                backups_dir = self.db_path.parent / "backups"
                latest_backup: Optional[Path] = None
                if backups_dir.is_dir():
                    cands = sorted([p for p in backups_dir.iterdir() if p.is_file() and p.suffix in (".db", ".bak")], reverse=True)
                    if cands:
                        latest_backup = cands[0]
                if latest_backup is not None:
                    import shutil
                    shutil.copy2(latest_backup, self.db_path)
                    LOG.critical("Recovery: ripristinato backup %s", latest_backup)
                    Database.recovery_message = f"Database corrotto e ripristinato da backup. File originale: {bad_backup if 'bad_backup' in dir() else latest_backup}."
                else:
                    Database.recovery_message = f"Database ricreato vuoto. Copia corrotta: {bad_backup if 'bad_backup' in dir() else 'sconosciuto'}."
                    LOG.critical("Recovery: nuovo DB vuoto creato (nessun backup trovato).")
            except Exception as restore_err:  # noqa: BLE001
                LOG.critical("Recovery fallita: %s. Forzo nuovo DB.", restore_err)
                Database.recovery_message = "Recovery DB fallito, nuovo DB vuoto forzato."
                try:
                    if self.db_path.exists():
                        self.db_path.unlink()
                except Exception:
                    pass
            return sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=30,
            )

    # ----- Lifecycle -----
    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            outer = self._txn_depth == 0
            savepoint = f"sp_{self._txn_depth}_{id(self)}"
            try:
                if not outer:
                    self._conn.execute(f"SAVEPOINT {savepoint}")
                self._txn_depth += 1
                yield self._conn
                self._txn_depth -= 1
                if outer:
                    self._conn.commit()
                else:
                    self._conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            except Exception:
                self._txn_depth -= 1
                try:
                    if outer:
                        self._conn.rollback()
                    else:
                        self._conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                        self._conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                except sqlite3.Error:
                    pass
                raise

    # ----- Migrations + FTS5 -----
    def _ensure_migrations(self) -> None:
        with self.transaction() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            cur = conn.execute("SELECT MAX(version) AS v FROM schema_migrations")
            row = cur.fetchone()
            current = (row["v"] if row and row["v"] is not None else 0)
            for step_idx, sql in enumerate(_MIGRATIONS, start=1):
                if step_idx > current:
                    conn.executescript(sql)
                    conn.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                        (step_idx, _now_iso()),
                    )

    # ----- Settings -----
    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._lock:
            cur = self._conn.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cur.fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO settings(key, value) VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    # ----- Modules -----
    def upsert_module(self, **fields: Any) -> int:
        _assert_valid_columns("modules", _ALLOWED_MODULE_COLUMNS, fields.keys())
        fields.setdefault("created_at", _now_iso())
        fields["updated_at"] = _now_iso()
        with self.transaction() as conn:
            cur = conn.execute("SELECT id FROM modules WHERE slug = ?", (fields["slug"],))
            row = cur.fetchone()
            if row:
                sets = ", ".join(f"{k} = ?" for k in fields.keys() if k != "slug")
                values = [fields[k] for k in fields.keys() if k != "slug"] + [fields["slug"]]
                conn.execute(f"UPDATE modules SET {sets} WHERE slug = ?", values)
                return row["id"]
            keys = ", ".join(fields.keys())
            placeholders = ", ".join("?" for _ in fields)
            cur = conn.execute(
                f"INSERT INTO modules({keys}) VALUES({placeholders})",
                list(fields.values()),
            )
            return int(cur.lastrowid)

    def get_module(self, slug: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute("SELECT * FROM modules WHERE slug = ?", (slug,))
            row = cur.fetchone()
            return _row_to_dict(row) if row is not None else None

    def delete_module(self, slug: str) -> int:
        """Remove a module row (and cascade-fks via schema). Returns rows deleted."""
        with self.transaction() as conn:
            cur = conn.execute("DELETE FROM modules WHERE slug = ?", (slug,))
            return int(cur.rowcount or 0)

    # ----- Documents -----
    def upsert_document(self, **fields: Any) -> int:
        _assert_valid_columns("documents", _ALLOWED_DOCUMENT_COLUMNS, fields.keys())
        fields.setdefault("created_at", _now_iso())
        with self.transaction() as conn:
            cur = conn.execute(
                "SELECT id FROM documents WHERE module_id IS ? AND kind = ? AND path = ?",
                (fields.get("module_id"), fields["kind"], fields["path"]),
            )
            row = cur.fetchone()
            if row:
                sets = ", ".join(
                    f"{k} = ?" for k in fields.keys() if k not in ("module_id", "kind", "path")
                )
                values = (
                    [fields[k] for k in fields.keys() if k not in ("module_id", "kind", "path")]
                    + [fields.get("module_id"), fields["kind"], fields["path"]]
                )
                conn.execute(
                    f"UPDATE documents SET {sets} WHERE module_id IS ? AND kind = ? AND path = ?",
                    values,
                )
                return row["id"]
            keys = ", ".join(fields.keys())
            placeholders = ", ".join("?" for _ in fields)
            cur = conn.execute(
                f"INSERT INTO documents({keys}) VALUES({placeholders})",
                list(fields.values()),
            )
            return int(cur.lastrowid)

    def list_documents(self, module_id: int, kind: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            if kind:
                cur = self._conn.execute(
                    "SELECT * FROM documents WHERE module_id = ? AND kind = ? ORDER BY path ASC",
                    (module_id, kind),
                )
            else:
                cur = self._conn.execute(
                    "SELECT * FROM documents WHERE module_id = ? ORDER BY kind, path ASC",
                    (module_id,),
                )
            return [_row_to_dict(r) for r in cur.fetchall()]

    # ----- Reports -----
    def create_report(self, **fields: Any) -> int:
        _assert_valid_columns("reports", _ALLOWED_REPORT_COLUMNS, fields.keys())
        fields.setdefault("created_at", _now_iso())
        keys = ", ".join(fields.keys())
        placeholders = ", ".join("?" for _ in fields)
        with self.transaction() as conn:
            cur = conn.execute(
                f"INSERT INTO reports({keys}) VALUES({placeholders})",
                list(fields.values()),
            )
            return int(cur.lastrowid)

    def update_report(self, report_id: int, **fields: Any) -> None:
        if not fields:
            return
        _assert_valid_columns("reports", _ALLOWED_REPORT_COLUMNS, fields.keys())
        sets = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [report_id]
        with self.transaction() as conn:
            conn.execute(f"UPDATE reports SET {sets} WHERE id = ?", values)

    def get_report(self, report_id: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT r.*, "
                "COALESCE(m.name, m.slug, 'Modulo sconosciuto') AS module, "
                "COALESCE(r.output_json_path, r.output_pdf_path, '') AS stamp, "
                "r.created_at AS created "
                "FROM reports r "
                "LEFT JOIN modules m ON m.id = r.module_id "
                "WHERE r.id = ?",
                (report_id,),
            )
            row = cur.fetchone()
            return _row_to_dict(row) if row is not None else None

    def count_reports(self, status: Optional[str] = None,
                      module_id: Optional[int] = None) -> int:
        clauses: List[str] = []
        params: List[Any] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if module_id is not None:
            clauses.append("module_id = ?")
            params.append(module_id)
        sql = "SELECT COUNT(*) FROM reports"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        with self._lock:
            cur = self._conn.execute(sql, params)
            row = cur.fetchone()
            try:
                return int(row[0]) if row is not None else 0
            except Exception:
                return 0

    def last_report_timestamp(self, *, status: Optional[str] = None) -> Optional[float]:
        clauses: List[str] = []
        params: List[Any] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        sql = "SELECT created_at FROM reports"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT 1"
        with self._lock:
            cur = self._conn.execute(sql, params)
            row = cur.fetchone()
            if row is None:
                return None
            try:
                ts = row["created_at"]
                if ts is None:
                    return None
                try:
                    from datetime import datetime
                    return datetime.fromisoformat(str(ts)).timestamp()
                except Exception:
                    import time as _time
                    return _time.mktime(_time.strptime(str(ts)[:19], "%Y-%m-%dT%H:%M:%S"))
            except Exception:
                return None

    # ----- Parsed cache -----
    def cache_get(self, sha256: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT text, meta FROM parsed_cache WHERE sha256 = ?", (sha256,)
            )
            row = cur.fetchone()
            if not row:
                return None
            try:
                meta = json.loads(row["meta"] or "{}")
            except json.JSONDecodeError:
                meta = {}
            return row["text"], meta

    def cache_store(self, sha256: str, kind: str, text: str, meta: Optional[Dict[str, Any]] = None) -> None:
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO parsed_cache(sha256, kind, text, meta, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(sha256) DO UPDATE SET
                    kind = excluded.kind,
                    text = excluded.text,
                    meta = excluded.meta
                """,
                (sha256, kind, text, json.dumps(meta or {}, ensure_ascii=False), _now_iso()),
            )

    # ----- AI Operations (audit log) -----
    def log_ai_operation(self, **fields: Any) -> int:
        _assert_valid_columns("ai_operations", _ALLOWED_AIOPS_COLUMNS, fields.keys())
        fields.setdefault("timestamp", _now_iso())
        keys = ", ".join(fields.keys())
        placeholders = ", ".join("?" for _ in fields)
        with self.transaction() as conn:
            cur = conn.execute(
                f"INSERT INTO ai_operations({keys}) VALUES({placeholders})",
                list(fields.values()),
            )
            return int(cur.lastrowid)

    def list_ai_operations(self, feature: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
        clauses: List[str] = []
        params: List[Any] = []
        if feature:
            clauses.append("feature = ?")
            params.append(feature)
        sql = "SELECT * FROM ai_operations"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            cur = self._conn.execute(sql, params)
            return [_row_to_dict(r) for r in cur.fetchall()]

    # ----- Document Chunks -----
    def store_chunks(self, file_sha256: str, chunks: List[Dict[str, Any]]) -> None:
        if not chunks:
            return
        with self.transaction() as conn:
            conn.execute("DELETE FROM document_chunks WHERE file_sha256 = ?", (file_sha256,))
            for idx, chunk in enumerate(chunks):
                _assert_valid_columns(
                    "document_chunks",
                    _ALLOWED_CHUNKS_COLUMNS,
                    chunk.keys(),
                )
                kwds = chunk.get("keywords_json")
                if isinstance(kwds, list):
                    kwds = json.dumps(kwds, ensure_ascii=False)
                conn.execute(
                    """
                    INSERT INTO document_chunks(
                        file_sha256, chunk_index, page, sheet, cell_ref,
                        paragraph_index, chunk_text, keywords_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        file_sha256,
                        int(chunk.get("chunk_index", idx)),
                        chunk.get("page"),
                        chunk.get("sheet"),
                        chunk.get("cell_ref"),
                        chunk.get("paragraph_index"),
                        str(chunk.get("chunk_text", "")),
                        kwds or "[]",
                        _now_iso(),
                    ),
                )

    def list_chunks(self, file_sha256: str) -> List[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM document_chunks WHERE file_sha256 = ? ORDER BY chunk_index ASC",
                (file_sha256,),
            )
            return [_row_to_dict(r) for r in cur.fetchall()]

    def search_chunks(self, keywords: List[str], limit: int = 50) -> List[Dict[str, Any]]:
        if not keywords:
            return []
        like_clauses = " OR ".join(["chunk_text LIKE ?" for _ in keywords])
        params: List[Any] = [f"%{k}%" for k in keywords]
        params.append(limit)
        with self._lock:
            cur = self._conn.execute(
                f"SELECT * FROM document_chunks WHERE {like_clauses} ORDER BY id DESC LIMIT ?",
                params,
            )
            return [_row_to_dict(r) for r in cur.fetchall()]

    # ----- FTS5 setup + search -----
    def _ensure_fts5(self) -> None:
        if not _is_fts5_available(self._conn):
            import logging as _logging
            _logging.getLogger(__name__).warning("FTS5 non disponibile in questo sqlite3, uso fallback LIKE per la ricerca report.")
            return
        with self.transaction() as conn:
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS reports_fts USING fts5(
                    input_description,
                    final_json UNINDEXED,
                    content='reports',
                    content_rowid='id'
                )
                """
            )
            conn.executescript(
                """
                CREATE TRIGGER IF NOT EXISTS reports_fts_ai AFTER INSERT ON reports BEGIN
                    INSERT INTO reports_fts(rowid, input_description, final_json)
                    VALUES (new.id, new.input_description, COALESCE(new.final_json, ''));
                END;
                CREATE TRIGGER IF NOT EXISTS reports_fts_ad AFTER DELETE ON reports BEGIN
                    INSERT INTO reports_fts(reports_fts, rowid, input_description, final_json)
                    VALUES ('delete', old.id, old.input_description, COALESCE(old.final_json, ''));
                END;
                CREATE TRIGGER IF NOT EXISTS reports_fts_au AFTER UPDATE ON reports BEGIN
                    INSERT INTO reports_fts(reports_fts, rowid, input_description, final_json)
                    VALUES ('delete', old.id, old.input_description, COALESCE(old.final_json, ''));
                    INSERT INTO reports_fts(rowid, input_description, final_json)
                    VALUES (new.id, new.input_description, COALESCE(new.final_json, ''));
                END;
                """
            )

    def search_reports_fts(self, keyword: str, limit: int = 50) -> List[Dict[str, Any]]:
        keyword = (keyword or "").strip()
        if not keyword:
            return []
        if not _is_fts5_available(self._conn):
            terms = keyword.split()
            params: List[Any] = []
            clauses = []
            for t in terms:
                clauses.append("(r.input_description LIKE ? OR COALESCE(r.final_json,'') LIKE ?)")
                params.extend([f"%{t}%", f"%{t}%"])
            sql = (
                "SELECT r.* FROM reports r WHERE " + " AND ".join(clauses) +
                " ORDER BY r.created_at DESC LIMIT ?"
            )
            params.append(limit)
            with self._lock:
                cur = self._conn.execute(sql, params)
                return [_row_to_dict(r) for r in cur.fetchall()]
        sql = (
            "SELECT r.* FROM reports r "
            "JOIN reports_fts f ON f.rowid = r.id "
            "WHERE reports_fts MATCH ? "
            "ORDER BY rank, r.created_at DESC LIMIT ?"
        )
        with self._lock:
            cur = self._conn.execute(sql, (keyword, limit))
            return [_row_to_dict(r) for r in cur.fetchall()]

    # ----- Modules (extended: show_archived) -----
    def list_modules(self, *, show_archived: bool = False) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM modules"
        params: List[Any] = []
        if not show_archived:
            sql += " WHERE archived = 0"
        sql += " ORDER BY name ASC"
        with self._lock:
            cur = self._conn.execute(sql, params)
            return [_row_to_dict(r) for r in cur.fetchall()]

    # ----- Reports (extended filters: date_from, date_to, keyword) -----
    def list_reports(
        self,
        module_id: Optional[int] = None,
        status: Optional[str] = None,
        limit: int = 200,
        *,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        keyword: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        clauses: List[str] = []
        params: List[Any] = []
        if module_id is not None:
            clauses.append("r.module_id = ?")
            params.append(module_id)
        if status:
            clauses.append("r.status = ?")
            params.append(status)
        if date_from:
            clauses.append("r.created_at >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("r.created_at <= ?")
            params.append(date_to)
        if keyword:
            kws = keyword.split()
            kw_clauses = []
            for kw in kws:
                kw_clauses.append("(r.input_description LIKE ? OR COALESCE(r.final_json,'') LIKE ?)")
                params.extend([f"%{kw}%", f"%{kw}%"])
            clauses.append("(" + " AND ".join(kw_clauses) + ")")
        sql = (
            "SELECT r.*, "
            "COALESCE(m.name, m.slug, 'Modulo sconosciuto') AS module, "
            "COALESCE(r.output_json_path, r.output_pdf_path, '') AS stamp, "
            "r.created_at AS created "
            "FROM reports r "
            "LEFT JOIN modules m ON m.id = r.module_id"
        )
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY r.created_at DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            cur = self._conn.execute(sql, params)
            return [_row_to_dict(r) for r in cur.fetchall()]

    # ----- Tags many-to-many -----
    def add_tag(self, name: str, color: str = "#60a5fa") -> int:
        with self.transaction() as conn:
            cur = conn.execute("SELECT id FROM tags WHERE name = ?", (name,))
            row = cur.fetchone()
            if row:
                conn.execute("UPDATE tags SET color = ? WHERE id = ?", (color, row["id"]))
                return int(row["id"])
            cur = conn.execute(
                "INSERT INTO tags(name, color) VALUES (?, ?)",
                (name, color),
            )
            return int(cur.lastrowid)

    def list_tags(self) -> List[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute("SELECT * FROM tags ORDER BY name ASC")
            return [_row_to_dict(r) for r in cur.fetchall()]

    def tag_report(self, report_id: int, tag_id: int) -> None:
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO report_tags(report_id, tag_id) VALUES (?, ?)
                """,
                (report_id, tag_id),
            )

    def untag_report(self, report_id: int, tag_id: int) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM report_tags WHERE report_id = ? AND tag_id = ?", (report_id, tag_id))

    def tags_of_report(self, report_id: int) -> List[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT t.* FROM tags t
                JOIN report_tags rt ON rt.tag_id = t.id
                WHERE rt.report_id = ?
                ORDER BY t.name ASC
                """,
                (report_id,),
            )
            return [_row_to_dict(r) for r in cur.fetchall()]
