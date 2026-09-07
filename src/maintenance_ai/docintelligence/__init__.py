"""Document Intelligence package.

Centralized, reusable services shared by all new AI document features:
- RulesManager (per-feature and per-module .txt rules files)
- OCRService (Windows OCR first, portable Tesseract fallback)
- PDFParser (pypdf native text extraction + page image preparation)
- DocumentLoader (recursive folder scan, all supported formats)
- DocumentIndexer (chunking + SQLite storage)
- DocumentRetriever (keyword-overlap scoring of chunks)
- SourceTracker (per-value provenance records)
- AIService (4-level prompt assembly: sw-rules → feature-rules → module-rules → user)

Plus feature-level orchestration:
- DocumentGenerator  (crea documento)
- DocumentModifier   (modifica documento)
- AuditEngine        (audit documenti)
- SmartFillEngine    (compilazione smart da documenti)
"""

from .rules_manager import RulesManager, FEATURE_RULES_FILES, GLOBAL_FEATURE_KEY, FEATURE_LABELS_V2
from .ocr_service import OCRService, OCRExtraction
from .pdf_parser import PDFParser, PDFExtraction
from .document_loader import (
    DocumentLoader,
    LoadedDocument,
    SUPPORTED_EXTENSIONS,
    IMAGE_EXTENSIONS,
)
from .document_indexer import DocumentIndexer, Chunk
from .document_retriever import DocumentRetriever, RetrievedChunk
from .source_tracker import SourceTracker, SourceRef, FieldWithSources, Conflict
from .ai_service import (
    AIService,
    AIResult,
    INTERNAL_SOFTWARE_RULES,
)
from .document_generator import DocumentGenerator, GeneratedDocument
from .document_modifier import DocumentModifier, ModifiedDocument, ModificationRequest, TextSelection
from .audit_engine import AuditEngine, AuditFinding, AuditReport, SEVERITY_LEVELS
from .smart_fill_engine import SmartFillEngine, SmartFillResult

__all__ = [
    "RulesManager", "FEATURE_RULES_FILES", "GLOBAL_FEATURE_KEY", "FEATURE_LABELS_V2",
    "OCRService", "OCRExtraction",
    "PDFParser", "PDFExtraction",
    "DocumentLoader", "LoadedDocument", "SUPPORTED_EXTENSIONS", "IMAGE_EXTENSIONS",
    "DocumentIndexer", "Chunk",
    "DocumentRetriever", "RetrievedChunk",
    "SourceTracker", "SourceRef", "FieldWithSources", "Conflict",
    "AIService", "AIResult", "INTERNAL_SOFTWARE_RULES",
    "DocumentGenerator", "GeneratedDocument",
    "DocumentModifier", "ModifiedDocument", "ModificationRequest", "TextSelection",
    "AuditEngine", "AuditFinding", "AuditReport", "SEVERITY_LEVELS",
    "SmartFillEngine", "SmartFillResult",
]
