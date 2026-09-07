"""File and archive security hardening.

Goals:
- Path traversal prevention when resolving user-provided names against a root.
- Size and extension validation for imported files.
- Safe ZIP import (defused limits, no absolute/escape paths, blocklisted names).
- SHA-256 hashing utilities.
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


_BLOCKED_NAME_TOKENS: Tuple[str, ...] = (
    "..",
    "<script",
    "<iframe",
    "eval(",
    "javascript:",
)


@dataclass
class SecurityLimits:
    max_input_file_mb: int = 25
    max_archive_uncompressed_mb: int = 100
    max_archive_entries: int = 5000
    allowed_extensions_input: Tuple[str, ...] = (".docx", ".xlsx")
    blocked_extensions: Tuple[str, ...] = (
        ".docm", ".xlsm", ".exe", ".bat", ".ps1", ".js", ".lnk", ".vbs",
    )

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SecurityLimits":
        return cls(
            max_input_file_mb=int(d.get("max_input_file_mb", 25)),
            max_archive_uncompressed_mb=int(d.get("max_archive_uncompressed_mb", 100)),
            max_archive_entries=int(d.get("max_archive_entries", 5000)),
            allowed_extensions_input=tuple(d.get("allowed_extensions_input", [".docx", ".xlsx"])),
            blocked_extensions=tuple(d.get("blocked_extensions", [])),
        )


class SecurityError(Exception):
    """Raised when a validation fails."""


# ----- Path safety -----
def safe_resolve_name(root: Path, relative_name: str, allow_subdirs: bool = True) -> Path:
    """Resolve ``relative_name`` inside ``root`` without escaping the root.

    Returns an absolute, resolved Path guaranteed to be under ``root``.
    Raises SecurityError on path traversal / absolute paths / reserved names.
    """
    root_resolved = Path(root).resolve()
    if not root_resolved.exists():
        root_resolved.mkdir(parents=True, exist_ok=True)
    if not relative_name:
        raise SecurityError("Nome vuoto non consentito")

    # Reject absolute paths and drive letters (Windows)
    p = Path(relative_name)
    if p.is_absolute() or relative_name.startswith(("\\", "/")):
        raise SecurityError("Percorsi assoluti non consentiti")
    # Reject backslash-as-root / drive letter
    if len(relative_name) >= 2 and relative_name[1] == ":":
        raise SecurityError("Percorsi con lettera di unità non consentiti")
    # Token checks
    lowered = relative_name.lower()
    for tok in _BLOCKED_NAME_TOKENS:
        if tok in lowered:
            raise SecurityError(f"Nome non consentito: {relative_name!r}")

    # Construct and resolve
    candidate = (root_resolved / relative_name).resolve()
    # Ensure it lives under the root
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise SecurityError("Tentativo di path traversal rilevato") from exc
    if not allow_subdirs and candidate.parent != root_resolved:
        raise SecurityError("Sottocartelle non consentite per questo percorso")
    return candidate


def safe_slug(name: str, fallback: str = "module") -> str:
    """Produce a filesystem-safe slug, keeping unicode chars but stripping separators."""
    cleaned = name.strip()
    if not cleaned:
        return fallback
    for bad in '<>:"/\\|?*':
        cleaned = cleaned.replace(bad, "_")
    cleaned = cleaned.replace(" ", "_")
    cleaned = cleaned.rstrip(". ")
    return cleaned or fallback


# ----- File validation -----
def validate_file_size(path: Path, limits: SecurityLimits) -> None:
    size = path.stat().st_size
    max_bytes = limits.max_input_file_mb * 1024 * 1024
    if size > max_bytes:
        raise SecurityError(
            f"File {path.name} troppo grande: {size} bytes > {max_bytes} bytes"
        )


def validate_extension(path: Path, limits: SecurityLimits) -> str:
    ext = path.suffix.lower()
    if ext in limits.blocked_extensions:
        raise SecurityError(f"Estensione proibita: {ext}")
    if limits.allowed_extensions_input and ext not in limits.allowed_extensions_input:
        raise SecurityError(
            f"Estensione non consentita: {ext}. Consentite: {limits.allowed_extensions_input}"
        )
    return ext


# ----- Hashing -----
def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            buf = fh.read(chunk_size)
            if not buf:
                break
            hasher.update(buf)
    return hasher.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ----- ZIP import / module bundle -----
@dataclass
class ZipInfo:
    entries: int
    uncompressed_bytes: int
    files: List[zipfile.ZipInfo]


def validate_zip(zip_path: Path, limits: SecurityLimits) -> ZipInfo:
    validate_file_size(zip_path, limits)
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise SecurityError("Archivio ZIP non valido o corrotto") from exc
    with zf:
        infos = zf.infolist()
        if len(infos) > limits.max_archive_entries:
            raise SecurityError(
                f"ZIP con troppe entry: {len(infos)} > {limits.max_archive_entries}"
            )
        total = 0
        max_bytes = limits.max_archive_uncompressed_mb * 1024 * 1024
        for info in infos:
            # Reject DOS/absolute/escape paths inside ZIP
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or (len(name) >= 2 and name[1] == ":"):
                raise SecurityError(f"Percorso non valido nello ZIP: {info.filename!r}")
            parts = name.split("/")
            if ".." in parts:
                raise SecurityError(f"Path traversal nello ZIP: {info.filename!r}")
            # Block blocked extensions even inside ZIP
            ext = Path(info.filename).suffix.lower()
            if ext in limits.blocked_extensions:
                raise SecurityError(f"File proibito nello ZIP: {info.filename}")
            total += info.file_size
            if total > max_bytes:
                raise SecurityError(
                    f"Dimensione decompressa ZIP eccessiva: > {max_bytes} bytes"
                )
        return ZipInfo(entries=len(infos), uncompressed_bytes=total, files=infos)


def extract_zip_safe(zip_path: Path, dest_root: Path, limits: SecurityLimits) -> ZipInfo:
    info = validate_zip(zip_path, limits)
    dest_root = Path(dest_root).resolve()
    dest_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for member in info.files:
            out_path = safe_resolve_name(dest_root, member.filename, allow_subdirs=True)
            if member.is_dir():
                out_path.mkdir(parents=True, exist_ok=True)
                continue
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(out_path, "wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
    return info


def pack_folder_to_zip(source_dir: Path, zip_path: Path) -> None:
    source_dir = Path(source_dir).resolve()
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(source_dir):
            for name in files:
                file_path = Path(root) / name
                arcname = str(file_path.relative_to(source_dir))
                zf.write(file_path, arcname=arcname)
