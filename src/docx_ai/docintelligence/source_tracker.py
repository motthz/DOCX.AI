"""SourceTracker: tracciabilità per-valore → sorgente.

Usato da Smart Fill e Audit per associare ogni campo / asserzione a:
- file sorgente,
- pagina / foglio / cella / paragrafo,
- estratto del testo sorgente,
- confidence (se OCR o inference),
- conflitti (stesso campo, valori diversi da fonti diverse).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class SourceRef:
    """Un riferimento puntuale a un pezzo di informazione nel documento."""

    file_name: str
    file_path: Optional[Path] = None
    file_sha256: str = ""
    page: Optional[int] = None
    sheet: Optional[str] = None
    cell: Optional[str] = None
    paragraph_index: Optional[int] = None
    section: Optional[str] = None
    excerpt: str = ""
    confidence: Optional[float] = None
    source_kind: str = ""   # "native" | "ocr" | "inferred"

    def to_dict(self) -> Dict[str, Any]:
        """Forma serializzabile in JSON (salvataggio dei dati approvati)."""
        return {"file": self.file_name, "path": str(self.file_path) if self.file_path else None,
                "sha256": self.file_sha256, "page": self.page, "sheet": self.sheet, "cell": self.cell,
                "paragraph": self.paragraph_index, "section": self.section, "excerpt": self.excerpt[:400],
                "confidence": self.confidence, "kind": self.source_kind}

    def to_display(self) -> str:
        parts: List[str] = []
        parts.append(self.file_name)
        if self.page is not None:
            parts.append(f"pagina {self.page+1}")
        if self.sheet:
            parts.append(f"foglio {self.sheet}")
        if self.cell:
            parts.append(f"cella {self.cell}")
        if self.section:
            parts.append(self.section)
        return ", ".join(parts)


@dataclass
class Conflict:
    """Valori diversi riportati da fonti diverse per lo stesso campo."""

    field: str
    alternatives: List[Tuple[str, List[SourceRef]]]   # (value, refs)

    def values(self) -> List[str]:
        return [v for v, _ in self.alternatives]

    def to_dict(self) -> Dict[str, Any]:
        return {"field": self.field,
                "alternatives": [{"value": v, "sources": [r.to_dict() for r in refs]}
                                 for v, refs in self.alternatives]}


@dataclass
class FieldWithSources:
    """Campo + valore + fonti + conflitti opzionali."""

    field: str
    value: Any = None
    sources: List[SourceRef] = field(default_factory=list)
    conflict: Optional[Conflict] = None
    filled: bool = False           # True se c'è un valore (anche vuoto = NON_SPECIFICATO)
    is_conflict: bool = False
    needs_review: bool = False     # AI non convinta, bassa confidence

    def primary_source(self) -> Optional[SourceRef]:
        return self.sources[0] if self.sources else None

    def sources_display(self) -> List[str]:
        return [s.to_display() for s in self.sources]


class SourceTracker:
    """Accumula SourceRef per campo e produce FieldWithSources finali
    con rilevamento automatico dei conflitti."""

    def __init__(self) -> None:
        self._refs: Dict[str, List[Tuple[Any, SourceRef]]] = {}

    # --------------------------------------------------------------
    def add(self, field: str, value: Any, ref: SourceRef) -> None:
        bucket = self._refs.setdefault(field, [])
        bucket.append((value, ref))

    # --------------------------------------------------------------
    def build_fields(
        self,
        all_field_names: List[str],
        *,
        tiebreaker: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, FieldWithSources], List[Conflict]]:
        """Dato l'elenco di tutti i campi dello schema, restituisce
        (fields_by_name, conflicts)."""
        fields: Dict[str, FieldWithSources] = {}
        conflicts: List[Conflict] = []
        tie = tiebreaker or {}
        for f in all_field_names:
            entries = self._refs.get(f) or []
            # Group by value
            groups: Dict[str, List[SourceRef]] = {}
            for val, ref in entries:
                key = "" if val is None else str(val)
                groups.setdefault(key, []).append(ref)
            fw = FieldWithSources(field=f)
            if not groups:
                fields[f] = fw
                continue
            # Unique value?
            if len(groups) == 1:
                unique_value = next(iter(groups.keys()))
                refs = groups[unique_value]
                fw.value = self._cast_to_original(entries, unique_value)
                fw.sources = refs
                fw.filled = True
            else:
                # Conflict detected
                alts: List[Tuple[str, List[SourceRef]]] = [
                    (v, groups[v]) for v in groups
                ]
                # Sort by number of sources descending
                alts.sort(key=lambda t: len(t[1]), reverse=True)
                conflict = Conflict(field=f, alternatives=alts)
                conflicts.append(conflict)
                fw.conflict = conflict
                fw.is_conflict = True
                fw.needs_review = True
                # Tentative: tiebreaker if present, else most-supported
                if f in tie:
                    chosen = str(tie[f])
                    fw.value = chosen
                    fw.sources = groups.get(chosen, []) or alts[0][1]
                else:
                    fw.value = alts[0][0]
                    fw.sources = alts[0][1]
                fw.filled = True
            fields[f] = fw
        return fields, conflicts

    # --------------------------------------------------------------
    @staticmethod
    def _cast_to_original(entries: List[Tuple[Any, SourceRef]], key: str) -> Any:
        """Preserve the original type (e.g. integer vs string)."""
        for orig, _ref in entries:
            if ("" if orig is None else str(orig)) == key:
                return orig
        return key
