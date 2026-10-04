"""DocumentRetriever: selezione deterministica dei chunk più pertinenti.

Base: keyword overlap + IDF approssimato (auditable, veloce su CPU limitate).
Se e' disponibile il modello di embedding locale il punteggio diventa ibrido
(meta' parole chiave, meta' similarita' semantica) e vengono recuperati anche
brani pertinenti che non condividono parole con la richiesta.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .document_indexer import Chunk, _tokens


@dataclass
class RetrievedChunk:
    chunk: Chunk
    score: float
    matched_keywords: List[str]

    @property
    def file_path(self) -> Path:
        return self.chunk.file_path

    @property
    def file_sha256(self) -> str:
        return self.chunk.file_sha256

    @property
    def text(self) -> str:
        return self.chunk.chunk_text


class DocumentRetriever:
    SEMANTIC_MIN = 0.55  # similarita' minima per un brano senza parole in comune

    def __init__(self, semantic=None):
        self.semantic = semantic  # llm.embeddings.SemanticSearch | None

    # --------------------------------------------------------------
    # Public: select top-N chunks given user description + schema fields hints
    # --------------------------------------------------------------
    def retrieve(
        self,
        all_chunks: Iterable[Chunk],
        query_text: str,
        *,
        extra_query_tokens: Optional[List[str]] = None,
        top_k: int = 12,
        max_total_chars: int = 8000,
    ) -> List[RetrievedChunk]:
        query_tokens = set(self._normalize_tokens(_tokens(query_text or "", limit=500)))
        if extra_query_tokens:
            query_tokens.update(self._normalize_tokens(extra_query_tokens))
        if not query_tokens:
            # No query: return first chunks by index (0,1,...) from each doc mixed
            chunks = list(all_chunks)
            chunks.sort(key=lambda c: (c.file_sha256, c.chunk_index))
            return [
                RetrievedChunk(chunk=c, score=0.0, matched_keywords=[])
                for c in chunks[:top_k]
            ]
        # IDF approx: token -> 1+log(1/(1+df))
        chunks_list = list(all_chunks)
        df: Dict[str, int] = {}
        for c in chunks_list:
            toks = set(self._normalize_tokens(c.keywords or _tokens(c.chunk_text)))
            for t in toks:
                df[t] = df.get(t, 0) + 1
        N = max(1, len(chunks_list))
        sims: Dict[int, float] = {}
        if self.semantic is not None and chunks_list:
            try:
                sims = self.semantic.similarities(query_text or " ".join(sorted(query_tokens)),
                                                  [c.chunk_text for c in chunks_list])
            except Exception:  # noqa: BLE001
                sims = {}
        scored: List[RetrievedChunk] = []
        sim_of: List[float] = []
        for i, c in enumerate(chunks_list):
            toks = set(self._normalize_tokens(c.keywords or _tokens(c.chunk_text)))
            matched = sorted(query_tokens & toks)
            sim = sims.get(i, 0.0)
            if not matched and sim < self.SEMANTIC_MIN:
                continue
            s = 0.0
            for t in matched:
                idf = 1.0 + math.log(N / (1.0 + df.get(t, 0)))
                s += idf
            scored.append(RetrievedChunk(chunk=c, score=s, matched_keywords=matched))
            sim_of.append(sim)
        if sims and scored:
            # punteggio ibrido: meta' parole chiave (normalizzate), meta' similarita'
            top_kw = max(r.score for r in scored) or 1.0
            for r, sim in zip(scored, sim_of):
                r.score = 0.5 * (r.score / top_kw) + 0.5 * sim
        scored.sort(key=lambda r: (r.score, len(r.matched_keywords)), reverse=True)
        picked: List[RetrievedChunk] = []
        total_chars = 0
        for r in scored:
            if len(picked) >= top_k:
                break
            size = len(r.text)
            if total_chars + size > max_total_chars and picked:
                continue
            picked.append(r)
            total_chars += size
        return picked

    # --------------------------------------------------------------
    @staticmethod
    def _normalize_tokens(tokens: Iterable[str]) -> List[str]:
        out: List[str] = []
        for t in tokens:
            if len(t) < 2:
                continue
            t = t.lower()
            if t in _STOPWORDS_IT:
                continue
            out.append(t)
        return out


# Italian + English common stopwords: exclude them from scoring
_STOPWORDS_IT = {
    "il", "lo", "la", "i", "gli", "le", "un", "uno", "una",
    "di", "a", "da", "in", "con", "su", "per", "tra", "fra",
    "del", "dello", "della", "dei", "degli", "delle",
    "al", "allo", "alla", "ai", "agli", "alle",
    "dal", "dallo", "dalla", "dai", "dagli", "dalle",
    "nel", "nello", "nella", "nei", "negli", "nelle",
    "sul", "sullo", "sulla", "sui", "sugli", "sulle",
    "che", "chi", "non", "più", "anche", "se", "ma", "e", "ed", "o",
    "sono", "è", "ho", "hai", "ha", "abbiamo", "avete", "hanno",
    "essere", "avere", "fare", "fatto", "perché", "questo", "questa",
    "del", "in", "con", "per", "come", "dove", "quando", "cosa",
    "the", "be", "to", "of", "and", "a", "in", "that", "have", "i",
    "it", "for", "not", "on", "with", "he", "as", "you", "do", "at",
    "this", "but", "his", "by", "from", "they", "we", "say", "her", "she",
    "or", "an", "will", "my", "one", "all", "would", "there", "their", "what",
    "so", "up", "out", "if", "about", "who", "get", "which", "go", "me",
    "dei", "delle", "nel", "nei", "etc", "etc.",
}
