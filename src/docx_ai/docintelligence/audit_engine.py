"""AuditEngine: feature "Audit documenti".

Analizza una cartella (ricorsiva) di documenti e produce un report strutturato
con criticità, incoerenze, dati mancanti, problemi di tracciabilità.

Nessuna checklist fissa: genera dinamicamente domande incrociando tutti gli
identificatori comuni (numero rapporto, macchina, lotto, fornitore, data,
codice documento, revisione, responsabile, ecc.).

Gravità: CRITICO / ALTO / MEDIO / BASSO / OSSERVAZIONE
Tono: "Possibile criticità", "Da verificare", "Informazioni insufficienti"
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..config import Config
from .ai_service import AIService
from .document_indexer import Chunk, DocumentIndexer
from .document_loader import DocumentLoader, LoadedDocument
from .document_retriever import DocumentRetriever
from .source_tracker import SourceRef


def export_pdf(*args, **kwargs):  # ReportLab importato solo quando serve (avvio piu' rapido)
    from ..exporters.pdf_exporter import export_pdf as _export_pdf
    return _export_pdf(*args, **kwargs)


LOG = logging.getLogger(__name__)


SEVERITY_LEVELS = ["CRITICO", "ALTO", "MEDIO", "BASSO", "OSSERVAZIONE"]


_CHECK_REASONS = {
    "cronologia": "La sequenza delle date non è possibile.",
    "riferimento": "Un documento citato deve essere disponibile per la tracciabilità.",
    "revisione": "Va applicata la revisione in vigore del documento.",
    "taratura": "Uno strumento con taratura scaduta non garantisce le misure.",
    "scadenza": "Il documento di riferimento non era più valido.",
    "codice": "Documenti dello stesso lavoro devono riportare lo stesso codice.",
    "firma": "Responsabile e firma sono necessari per la validità del documento.",
}

_DOC_AUDIT_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["problemi"],
    "properties": {"problemi": {"type": "array", "maxItems": 3, "items": {
        "type": "object", "additionalProperties": False, "required": ["titolo", "evidenza", "descrizione"],
        "properties": {"titolo": {"type": "string", "maxLength": 80},
                       "evidenza": {"type": "string", "maxLength": 160},
                       "descrizione": {"type": "string", "maxLength": 220}}}}},
}


def _quote_in(quote: str, text: str) -> bool:
    """La frase citata compare nel testo (spazi, maiuscole e punteggiatura a parte)."""
    q = re.sub(r"[^a-z0-9]+", " ", (quote or "").lower()).strip()
    t = re.sub(r"[^a-z0-9]+", " ", (text or "").lower())
    if len(q) < 6:
        return False
    if q in t:
        return True
    words = [w for w in q.split() if len(w) >= 3]
    return bool(words) and sum(w in t.split() for w in words) / len(words) >= 0.8


IDENTIFIER_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("numero_rapporto", re.compile(r"\b(?:rapporto|rpt|report)\s*(?:n\.?|nr\.?|num\.?)?\s*[:#]?\s*"
                                    r"((?=[A-Za-z0-9_\-/]*\d)[A-Za-z0-9_\-/]{3,30})", re.I)),
    ("ticket", re.compile(r"\b(?:ticket|tk)\s*[:#]?\s*([A-Za-z0-9_\-]{3,30})", re.I)),
    ("macchina", re.compile(r"\b(?:macchina|impianto|macchinario)\s*[:#]?\s*([A-Za-z0-9_\-]{2,30})", re.I)),
    ("codice_macchina", re.compile(r"\b([A-Z]{1,4}[\-_]?\d{2,6}[A-Za-z0-9\-_]{0,6})\b")),
    ("lotto", re.compile(r"\b(?:lotto|batch|lot)\s*[:#]?\s*([A-Za-z0-9_\-]{3,30})", re.I)),
    ("prodotto", re.compile(r"\b(?:prodotto|product|articolo)\s*[:#]?\s*([A-Za-z0-9_\- ]{3,40})", re.I)),
    ("fornitore", re.compile(r"\b(?:fornitore|supplier|vendor)\s*[:#]?\s*([A-Za-z0-9&' \-]{2,60})", re.I)),
    ("cliente", re.compile(r"\b(?:cliente|customer|committente)\s*[:#]?\s*([A-Za-z0-9&' \-]{2,60})", re.I)),
    ("data", re.compile(r"\b(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})\b")),
    ("data_iso", re.compile(r"\b(\d{4}[\-]\d{2}[\-]\d{2})\b")),
    ("codice_documento", re.compile(r"\b(?:doc\.?|documento|cod\.?|codice)\s*[:#]?\s*([A-Za-z]{0,5}[\-_]?\d{2,6}[A-Za-z0-9\-_]{0,8})", re.I)),
    ("revisione", re.compile(r"\b(?:rev\.?|revisione|version|ver\.?)\s*[:#]?\s*([0-9A-Za-z\.]{1,10})", re.I)),
    ("responsabile", re.compile(r"\b(?:responsabile|operator|tecnico|firmatario|approvato da)\s*[:#]?\s*([A-Za-zÀ-ÖØ-öø-ÿ \.']{3,50})", re.I)),
]


def _as_list(value: Any) -> List[str]:
    """Il modello a volte restituisce una stringa al posto di un elenco (es. un solo file):
    iterarla darebbe i singoli caratteri."""
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        value = [value]
    return [str(x).strip() for x in value if str(x).strip() and str(x).strip() != "NON_SPECIFICATO"]


@dataclass
class AuditFinding:
    """Singola criticità / osservazione."""

    title: str
    severity: str = "MEDIO"                          # CRITICO / ALTO / MEDIO / BASSO / OSSERVAZIONE
    description: str = ""
    files: List[str] = field(default_factory=list)   # nomi file
    locations: List[str] = field(default_factory=list) # "file: pagina X, foglio Y, cella Z"
    evidence: str = ""                              # estratto testuale
    reason: str = ""                                # perché è una criticità
    suggestion: str = ""                            # suggerimento verifica
    confidence: str = "Possibile criticità"         # Formule prudenziali

    def to_row(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "severity": self.severity,
            "description": self.description,
            "files": self.files,
            "locations": self.locations,
            "evidence": self.evidence,
            "reason": self.reason,
            "suggestion": self.suggestion,
            "confidence": self.confidence,
        }


@dataclass
class AuditReport:
    """Report strutturato completo."""

    summary: str = ""
    total_documents: int = 0
    total_pages_scanned: int = 0
    files: List[str] = field(default_factory=list)
    criticalities_by_severity: Dict[str, int] = field(default_factory=dict)
    findings: List[AuditFinding] = field(default_factory=list)
    open_questions: List[str] = field(default_factory=list)
    inconsistencies: List[str] = field(default_factory=list)
    missing_data: List[str] = field(default_factory=list)
    traceability_issues: List[str] = field(default_factory=list)
    potentially_missing_documents: List[str] = field(default_factory=list)
    links_between_documents: List[str] = field(default_factory=list)
    controls_executed: List[str] = field(default_factory=list)
    sources_used: List[SourceRef] = field(default_factory=list)

    def severity_counts(self) -> Dict[str, int]:
        c = self.criticalities_by_severity.copy()
        for sev in SEVERITY_LEVELS:
            c.setdefault(sev, 0)
        return c


class AuditEngine:
    def __init__(
        self,
        config: Config,
        loader: DocumentLoader,
        indexer: DocumentIndexer,
        retriever: DocumentRetriever,
        ai: AIService,
    ):
        self.config = config
        self.loader = loader
        self.indexer = indexer
        self.retriever = retriever
        self.ai = ai

    # --------------------------------------------------------------
    # Public: esegui audit di una cartella
    # --------------------------------------------------------------
    def audit_folder(
        self,
        folder: Path,
        *,
        extra_user_notes: str = "",
        progress_cb: Optional[Callable[[str], None]] = None,
        use_mock: bool = False,
    ) -> Tuple[AuditReport, List[LoadedDocument]]:
        step = lambda m: progress_cb(m) if progress_cb else None
        folder = Path(folder)
        # 1) Scan documents
        step("Scansione ricorsiva documenti…")
        docs = self.loader.scan_folder(
            folder, recursive=True,
            progress_cb=lambda i, n, p: step(f"Caricamento {i}/{n}: {p.name}"),
        )
        report = AuditReport(
            total_documents=len(docs),
            files=[str(d.path.name) for d in docs],
        )

        # 2) Index chunks
        step("Indicizzazione contenuti…")
        all_chunks: List[Chunk] = []
        for d in docs:
            try:
                chunks = self.indexer.index_document(d)
                all_chunks.extend(chunks)
                if d.pages_count:
                    report.total_pages_scanned += d.pages_count
            except Exception:  # noqa: BLE001
                pass
        # 3) Extract all identifiers across every document (cross-doc heuristics)
        step("Ricerca identificatori e collegamenti incrociati…")
        identifiers, per_doc_ids, doc_refs_between_docs = (
            self._cross_extract_identifiers(docs, all_chunks)
        )
        # Build cross-doc heuristic findings
        heuristic_findings = self._heuristic_findings(
            docs, identifiers, per_doc_ids, doc_refs_between_docs, report
        )
        # 4) Controlli deterministici: cronologia, documenti citati, revisioni, scadenze,
        #    codici incoerenti, firme vuote (il modello piccolo non li faceva)
        step("Controllo di date, riferimenti, revisioni e firme…")
        from .audit_checks import run_checks
        checks = run_checks(docs)
        check_findings = [AuditFinding(
            title=i.title, severity=i.severity, description=i.description, files=list(i.files),
            locations=list(i.files), evidence=i.evidence, reason=_CHECK_REASONS.get(i.kind, ""),
            suggestion=i.suggestion, confidence="Possibile criticità") for i in checks]
        for i in checks:
            target = {"cronologia": report.inconsistencies, "codice": report.inconsistencies,
                      "revisione": report.inconsistencies, "riferimento": report.potentially_missing_documents,
                      "firma": report.missing_data, "taratura": report.traceability_issues,
                      "scadenza": report.traceability_issues}.get(i.kind)
            if target is not None:
                target.append(i.description)

        # 5) AI: domande brevi su un documento alla volta; tenute solo le segnalazioni con una
        #    frase citata che esiste davvero nel documento (prima un'unica richiesta enorme:
        #    il modello piccolo ripeteva le euristiche o inventava documenti "mancanti")
        ai_findings = self._ai_per_document(docs, extra_user_notes, step, use_mock=use_mock)

        step("Assemblaggio report…")
        names = {d.path.name.lower() for d in docs} | {d.path.stem.lower() for d in docs}
        report.potentially_missing_documents = [
            x for x in dict.fromkeys(report.potentially_missing_documents)
            if x.strip().lower() not in names]
        # i controlli precisi prima; poi euristiche e AI senza doppioni
        all_findings: List[AuditFinding] = []
        seen: set = set()
        for f in check_findings + heuristic_findings + ai_findings:
            key = f.title.strip().lower()
            ev = (f.evidence or "").strip().lower()
            if not key or key in seen or (ev and any(ev == (g.evidence or "").strip().lower() for g in all_findings)):
                continue
            seen.add(key)
            all_findings.append(f)
        report.findings = all_findings
        for f in all_findings:
            sev = f.severity if f.severity in SEVERITY_LEVELS else "MEDIO"
            report.criticalities_by_severity[sev] = report.criticalities_by_severity.get(sev, 0) + 1
        report.summary = (
            f"Audit di {report.total_documents} documenti. "
            f"Criticità: "
            + ", ".join(
                f"{sev}={report.criticalities_by_severity.get(sev, 0)}"
                for sev in SEVERITY_LEVELS
            )
            + "."
        )
        report.controls_executed = [
            "Estrazione testo nativa + OCR ove disponibile",
            "Cronologia: apertura/chiusura, ordine → intervento → collaudo, ordine → consegna",
            "Documenti citati ma assenti dal pacchetto e revisioni diverse da quella presente",
            "Strumenti e documenti usati dopo la scadenza (tarature, offerte, certificati)",
            "Codici di macchine/strumenti diversi tra documenti collegati",
            "Firme e responsabili lasciati vuoti",
            "Analisi AI documento per documento con i modelli da 4B in su (segnalazioni con prova nel testo)",
        ]
        return report, docs

    # --------------------------------------------------------------
    # AI: un documento alla volta
    # --------------------------------------------------------------
    def _ai_per_document(self, docs: List[LoadedDocument], notes: str,
                         step: Callable[[str], Any], *, use_mock: bool = False) -> List[AuditFinding]:
        if use_mock or not docs:
            return []
        try:
            pipeline = self.ai.pipeline(use_mock=False)
        except Exception:  # noqa: BLE001
            return []
        from ..llm.json_pipeline import is_small_model
        from ..llm.llama_server import MockLlamaServer
        real = [s for s in getattr(pipeline, "server_chain", []) if not isinstance(s, MockLlamaServer)]
        if not real:
            return []  # nessuna AI installata: restano i controlli deterministici
        if is_small_model(real[0]):
            # Qwen3 0.6B e 1.7B, provati su due pacchetti con problemi noti: segnalazioni quasi
            # tutte sbagliate ("campo vuoto" su campi compilati, date corrette "impossibili") e
            # nessun problema in piu' rispetto ai controlli deterministici. Solo rumore.
            LOG.info("Audit: analisi AI per documento saltata con un modello piccolo")
            return []
        from ..llm.json_pipeline import _lenient_json_parse
        user_rules = ""
        try:
            user_rules = (self.ai.rules.read_feature_rules("document_audit") or "").strip()[:1500]
        except Exception:  # noqa: BLE001
            pass
        system = (
            "Sei un auditor che controlla UN documento alla volta. Segnala solo problemi che si vedono nel "
            "testo del documento: campi obbligatori vuoti, valori contraddittori, date impossibili, "
            "quantità o importi incoerenti. Per ogni problema copia in \"evidenza\" la frase esatta del "
            "documento. Non inventare documenti mancanti e non ripetere cose corrette. Se non ci sono "
            "problemi rispondi con un elenco vuoto."
            + (f"\nREGOLE DELL'UTENTE:\n{user_rules}" if user_rules else ""))
        others = ", ".join(d.path.name for d in docs)[:800]
        # i documenti con piu' testo sono quelli che contano; limite per le cartelle grandi
        chosen = sorted((d for d in docs if (d.full_text or "").strip()),
                        key=lambda d: -len(d.full_text or ""))[:10]
        out: List[AuditFinding] = []
        for i, d in enumerate(chosen, 1):
            step(f"Analisi AI {i}/{len(chosen)}: {d.path.name}")
            text = (d.full_text or "")[:3000]
            user = (f"DOCUMENTO: {d.path.name}\n{text}\n\nAltri documenti del pacchetto: {others}\n"
                    + (f"Note dell'utente: {notes}\n" if notes else "")
                    + "Elenca al massimo 3 problemi di questo documento.\n/no_think")
            try:
                resp = pipeline.chat(messages=[{"role": "system", "content": system},
                                               {"role": "user", "content": user}],
                                     temperature=0.1, max_tokens=420, json_schema=_DOC_AUDIT_SCHEMA)
                raw = ((resp.get("choices") or [{}])[0].get("message") or {}).get("content", "")
                parsed, _err = _lenient_json_parse(raw)
            except Exception as exc:  # noqa: BLE001
                LOG.info("Analisi AI di %s non riuscita: %s", d.path.name, exc)
                continue
            for item in (parsed or {}).get("problemi", []) if isinstance(parsed, dict) else []:
                if not isinstance(item, dict):
                    continue
                ev = str(item.get("evidenza") or "").strip()
                title = str(item.get("titolo") or "").strip()
                if not title or not _quote_in(ev, d.full_text or ""):
                    continue  # senza una frase vera del documento: probabilmente inventato
                out.append(AuditFinding(
                    title=f"{d.path.name}: {title}"[:160], severity="MEDIO",
                    description=str(item.get("descrizione") or title), files=[d.path.name],
                    locations=[d.path.name], evidence=ev, reason="Segnalato dall'AI con prova nel testo.",
                    suggestion="Verifica il punto citato nel documento.", confidence="Da verificare"))
        return out

    # --------------------------------------------------------------
    # Cross-doc heuristic identifier extraction
    # --------------------------------------------------------------
    def _cross_extract_identifiers(
        self,
        docs: List[LoadedDocument],
        chunks: List[Chunk],
    ) -> Tuple[
        Dict[str, set],
        Dict[str, Dict[str, set]],
        Dict[str, Dict[str, List[str]]],
    ]:
        # per-type values across all docs
        all_ids: Dict[str, set] = {name: set() for name, _ in IDENTIFIER_PATTERNS}
        # per-doc → per-type values
        per_doc: Dict[str, Dict[str, set]] = {}
        # per-doc: mentions of OTHER documents → list of reference text
        cross_refs: Dict[str, Dict[str, List[str]]] = {}
        for d in docs:
            doc_ids: Dict[str, set] = {name: set() for name, _ in IDENTIFIER_PATTERNS}
            for span in d.spans:
                for name, rx in IDENTIFIER_PATTERNS:
                    for m in rx.finditer(span.text or ""):
                        val = m.group(1).strip()
                        if len(val) >= 2:
                            doc_ids[name].add(val)
                            all_ids[name].add(val)
            per_doc[d.path.name] = doc_ids
            # Cross references between files (doc name mentions)
            mentions: Dict[str, List[str]] = {}
            text = d.full_text or ""
            for other in docs:
                if other.path.name == d.path.name:
                    continue
                stem = other.path.stem
                # Remove common noise suffixes
                for needle in [other.path.name, stem, stem.lower()]:
                    if len(needle) < 4:
                        continue
                    if needle in text or needle.lower() in text.lower():
                        mentions.setdefault(other.path.name, []).append(
                            f"menzione di '{needle}'"
                        )
                        break
            cross_refs[d.path.name] = mentions
        return all_ids, per_doc, cross_refs

    # --------------------------------------------------------------
    # Heuristic-only findings (no LLM call)
    # --------------------------------------------------------------
    def _heuristic_findings(
        self,
        docs: List[LoadedDocument],
        identifiers: Dict[str, set],
        per_doc_ids: Dict[str, Dict[str, set]],
        cross_refs: Dict[str, Dict[str, List[str]]],
        report: AuditReport,
    ) -> List[AuditFinding]:
        findings: List[AuditFinding] = []
        # (le date tra documenti collegati sono confrontate per ruolo in audit_checks:
        #  "date diverse" scattava per qualsiasi coppia di documenti sulla stessa macchina)
        # 2) Referenced document missing (mentions but no file present)
        doc_names = {d.path.name for d in docs}
        for dname, mentions_dict in cross_refs.items():
            for other_name, where in mentions_dict.items():
                if other_name not in doc_names:
                    findings.append(AuditFinding(
                        title=f"Documento citato non trovato: {other_name}",
                        severity="MEDIO",
                        description=f"Il documento {dname} menziona '{other_name}' ma il file non è presente nella cartella.",
                        files=[dname],
                        locations=[f"{dname}: {', '.join(where[:3])}"],
                        evidence=f"Menzione: {where[:2]}",
                        reason="La catena di tracciabilità richiede che i documenti citati siano disponibili.",
                        suggestion=f"Verificare se '{other_name}' esiste nella cartella o allegarlo al pacchetto.",
                        confidence="Da verificare",
                    ))
                    report.potentially_missing_documents.append(other_name)
        # 3) Missing required fields per document
        for d in docs:
            dname = d.path.name
            ids = per_doc_ids.get(dname, {})
            missing: List[str] = []
            for must_have in ["data"]:
                if not ids.get(must_have):
                    missing.append(must_have)
            if missing:
                findings.append(AuditFinding(
                    title=f"Dati fondamentali mancanti in {dname}",
                    severity="MEDIO",
                    description=f"Il documento {dname} non mostra alcuni campi tipicamente obbligatori: {', '.join(missing)}.",
                    files=[dname],
                    locations=[f"{dname}: {', '.join(missing)}"],
                    evidence="Identificatori chiave non rilevati tramite regex.",
                    reason="Responsabile e data sono generalmente obbligatori per tracciabilità.",
                    suggestion=f"Verificare che {dname} riporti {', '.join(missing)} in forma leggibile.",
                    confidence="Informazioni insufficienti",
                ))
                report.missing_data.append(f"{dname}: manca {', '.join(missing)}")
        # 4) Revision conflicts: same codice_documento + rev different
        cod_to_rev: Dict[str, Dict[str, List[str]]] = {}
        for dname, ids in per_doc_ids.items():
            for cod in ids["codice_documento"]:
                revs = sorted(ids["revisione"]) or ["(nessuna rev)"]
                cod_to_rev.setdefault(cod, {})[dname] = revs
        for cod, docs_map in cod_to_rev.items():
            if len(docs_map) > 1 and len({tuple(r) for r in docs_map.values()}) > 1:
                findings.append(AuditFinding(
                    title=f"Versioni/revisioni incompatibili per documento {cod}",
                    severity="ALTO",
                    files=list(docs_map.keys()),
                    locations=[f"{d}: rev={revs}" for d, revs in docs_map.items()],
                    evidence=f"codice_documento={cod}, revisioni per doc={docs_map}",
                    description="Stesso codice documento ma revisioni/versioni diverse in file diversi.",
                    reason="Uno stesso documento in revisioni diverse indica potenziale obsolescenza.",
                    suggestion=f"Confermare quale revisione di {cod} è quella in vigore e archiviare le altre.",
                    confidence="Possibile criticità",
                ))
        # 5) Traceability chain gaps
        for id_type in ["numero_rapporto", "ticket", "lotto"]:
            for value in list(identifiers[id_type]):
                docs_with = []
                has_registrazione = False
                has_approvazione = False
                has_chiusura = False
                for dname, per_doc in per_doc_ids.items():
                    if value in per_doc[id_type]:
                        docs_with.append(dname)
                        tl = (dname + " " + "\n".join(
                            [t for t in _text_of_doc(docs, dname)]
                        )).lower()
                        if any(k in tl for k in ["registraz", "creato", "apertura", "data inizio", "inizio"]):
                            has_registrazione = True
                        if any(k in tl for k in ["approv", "firmat", "verificat", "conforme"]):
                            has_approvazione = True
                        if any(k in tl for k in ["chius", "fine", "conclus", "completat"]):
                            has_chiusura = True
                if len(docs_with) >= 1 and not (has_registrazione and has_approvazione and has_chiusura):
                    mancano = []
                    if not has_registrazione: mancano.append("registrazione")
                    if not has_approvazione: mancano.append("approvazione")
                    if not has_chiusura: mancano.append("chiusura")
                    if mancano and len(docs_with) >= 1:
                        findings.append(AuditFinding(
                            title=f"Anelli mancanti catena tracciabilità per {id_type} {value}",
                            severity="OSSERVAZIONE",
                            description="Evento→registrazione→documento→responsabile→data→approvazione→azione successiva→chiusura: alcuni passaggi non sono documentati.",
                            files=docs_with,
                            locations=docs_with,
                            evidence=f"Anelli mancanti: {', '.join(mancano)}",
                            reason="Normativa e buona prassi richiedono tracciabilità completa.",
                            suggestion=f"Produrre/recuperare le prove relative a: {', '.join(mancano)}.",
                            confidence="Da verificare",
                        ))
                        report.traceability_issues.append(f"{id_type} {value}: manca {', '.join(mancano)}")
        # 6) Duplicates: same identifier value, multiple documents of same type
        for id_type in ["numero_rapporto", "ticket"]:
            for value in list(identifiers[id_type]):
                # numero proprio del documento nel titolo ("Rapporto n. 245/26"), non una citazione
                # ("Nota per il rapporto 245/26")
                own_no = re.compile(r"(?:\bn\.?|n°|\bnr\.?|\bnumero)\s*" + re.escape(value), re.I)
                docs_with = [d.path.name for d in docs
                             if own_no.search(((d.full_text or "").strip().splitlines() or [""])[0])]
                if len(docs_with) >= 2:
                    findings.append(AuditFinding(
                        title=f"Possibile duplicato {id_type} {value}",
                        severity="MEDIO",
                        description=f"{id_type} {value} compare in più di un file. Potrebbero essere duplicati o revisioni.",
                        files=docs_with,
                        locations=docs_with,
                        evidence=f"{id_type}={value}, files={docs_with}",
                        reason="Uno stesso numero di rapporto/ticket in documenti diversi segnala potenziale duplicazione.",
                        suggestion="Verificare che non si tratti di duplicati; se revisioni, assicurarsi che siano chiare le versioni.",
                        confidence="Possibile criticità",
                    ))
        # 7) Empty pages / no text found (OCR may be needed)
        for d in docs:
            if d.needs_ocr and not d.used_ocr:
                findings.append(AuditFinding(
                    title=f"{d.path.name}: testo non estraibile (PDF scannerizzato?)",
                    severity="OSSERVAZIONE",
                    description="Il documento non contiene testo nativo; l'AI non ha potuto analizzare il contenuto in profondità.",
                    files=[d.path.name],
                    evidence=f"needs_ocr=True, ocr_ran={d.used_ocr}, ocr_available={d.ocr_available}",
                    reason="Documenti scannerizzati senza OCR non possono essere verificati automaticamente.",
                    suggestion="Abilitare un motore OCR (Windows 10+ o Tesseract portatile) per analizzare le scansioni.",
                    confidence="Informazioni insufficienti",
                ))
        return findings

    # --------------------------------------------------------------
    # Public: salva report dopo conferma
    # --------------------------------------------------------------
    def save_report(
        self,
        report: AuditReport,
        output_dir: Path,
    ) -> Dict[str, Path]:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        base = f"Audit_{stamp}"
        result: Dict[str, Path] = {}
        data = {
            "summary": report.summary,
            "total_documents": report.total_documents,
            "files": report.files,
            "criticalities_by_severity": report.severity_counts(),
            "findings": [f.to_row() for f in report.findings],
            "open_questions": report.open_questions,
            "inconsistencies": report.inconsistencies,
            "missing_data": report.missing_data,
            "traceability_issues": report.traceability_issues,
            "potentially_missing_documents": report.potentially_missing_documents,
            "links_between_documents": report.links_between_documents,
            "controls_executed": report.controls_executed,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        json_path = output_dir / f"{base}.json"
        json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        result["json"] = json_path

        # TXT report
        lines = ["# REPORT AUDIT DOCUMENTALE", "", report.summary, ""]
        lines.append(f"Documenti analizzati: {report.total_documents}")
        lines.append(f"Pagine/passaggi: {report.total_pages_scanned}")
        lines.append("")
        for sev in SEVERITY_LEVELS:
            lines.append(f"## {sev}: {report.criticalities_by_severity.get(sev, 0)}")
        lines.append("")
        lines.append("## CRITICITÀ")
        for f in sorted(report.findings, key=lambda f: (
            SEVERITY_LEVELS.index(f.severity) if f.severity in SEVERITY_LEVELS else 99,
            f.title,
        )):
            lines.append(f"### [{f.severity}] {f.title} ({f.confidence})")
            if f.description:
                lines.append(f"Descrizione: {f.description}")
            if f.files:
                lines.append(f"File: {', '.join(f.files)}")
            if f.locations:
                lines.append(f"Posizioni: {'; '.join(f.locations)}")
            if f.evidence:
                lines.append(f"Evidenza: {f.evidence}")
            if f.reason:
                lines.append(f"Motivo: {f.reason}")
            if f.suggestion:
                lines.append(f"Suggerimento verifica: {f.suggestion}")
            lines.append("")
        for title, items in [
            ("DOMANDE APERTE", report.open_questions),
            ("INCOERENZE", report.inconsistencies),
            ("DATI MANCANTI", report.missing_data),
            ("PROBLEMI DI TRACCIABILITÀ", report.traceability_issues),
            ("DOCUMENTI POTENZIALMENTE MANCANTI", report.potentially_missing_documents),
            ("COLLEGAMENTI TRA DOCUMENTI", report.links_between_documents),
            ("CONTROLLI EFFETTUATI", report.controls_executed),
        ]:
            if items:
                lines.append(f"## {title}")
                for i in items:
                    lines.append(f"- {i}")
                lines.append("")
        txt_path = output_dir / f"{base}.txt"
        txt_path.write_text("\n".join(lines), encoding="utf-8")
        result["txt"] = txt_path

        # PDF
        try:
            pdf_path = output_dir / f"{base}.pdf"
            schema = {
                "type": "object",
                "properties": {
                    "Report": {"type": "string"},
                    "Criticità": {"type": "string"},
                },
            }
            pdf_data = {
                "Report": report.summary,
                "Criticità": "\n".join(
                    f"[{f.severity}] {f.title} - {f.description}" for f in report.findings
                ) or "(nessuna)",
            }
            export_pdf(
                pdf_path, pdf_data, schema,
                report_id=base, module_name="Audit Documenti",
            )
            result["pdf"] = pdf_path
        except Exception as exc:  # noqa: BLE001
            LOG.warning("Salvataggio PDF audit fallito: %s", exc)
        return result


def _text_of_doc(docs: List[LoadedDocument], name: str) -> List[str]:
    for d in docs:
        if d.path.name == name:
            return [d.full_text or ""]
    return []
