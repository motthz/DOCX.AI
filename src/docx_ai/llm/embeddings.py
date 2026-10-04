"""Ricerca semantica locale: embedding con Qwen3-Embedding (llama-server --embedding).

Il server di embedding parte solo quando serve e si spegne dopo inattivita'.
I vettori sono memorizzati nel DB indicizzati per hash del testo, quindi ogni
brano viene calcolato una sola volta.
"""

from __future__ import annotations

import array
import hashlib
import logging
import math
import threading
import time
from typing import Dict, List, Optional, Sequence

from ..config import Config
from ..db import Database
from .llama_server import LlamaServer, LlamaServerOptions

LOG = logging.getLogger(__name__)

EMBED_MODEL = "Qwen3-Embedding-0.6B-Q8_0.gguf"
EMBED_MODEL_PATH = f"models/{EMBED_MODEL}"


def text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _pack(vec: Sequence[float]) -> bytes:
    return array.array("f", vec).tobytes()


def _unpack(blob: bytes) -> List[float]:
    a = array.array("f")
    a.frombytes(blob)
    return a.tolist()


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class SemanticSearch:
    def __init__(self, config: Config, db: Database, *, enabled: bool = True):
        self.config = config
        self.db = db
        self.enabled = enabled
        self._server: Optional[LlamaServer] = None
        self._lock = threading.Lock()
        self._last_used = 0.0
        self._failed = False

    @property
    def model_path(self):
        return self.config.resolve_ai_path(EMBED_MODEL_PATH)

    def available(self) -> bool:
        st = self.config.ai_components_status()
        return bool(self.enabled and not self._failed and st["runtime_ok"] and self.model_path.is_file())

    def _ensure_server(self) -> LlamaServer:
        if self._server is not None and self._server.is_running:
            return self._server
        eff = self.config.llm_effective
        opts = LlamaServerOptions(
            runtime_dir=self.config.resolve_ai_path(eff["runtime_dir"]),
            runtime_exe=eff.get("runtime_exe", "llama-server.exe"),
            model_path=self.model_path, context_size=2048,
            port_min=int(eff.get("port_min", 39280)), port_max=int(eff.get("port_max", 39299)),
            embedding=True, thread_override=eff.get("thread_override"))
        srv = LlamaServer(opts)
        srv.start(timeout=120)
        self._server = srv
        return srv

    def embed(self, texts: List[str]) -> List[List[float]]:
        """Vettori per i testi (cache su DB). Lista vuota se non disponibile."""
        if not texts or not self.available():
            return []
        shas = [text_sha(t) for t in texts]
        cached = self.db.get_embeddings(shas, EMBED_MODEL)
        missing = [(i, t) for i, (t, s) in enumerate(zip(texts, shas)) if s not in cached]
        if missing:
            with self._lock:
                try:
                    srv = self._ensure_server()
                    new_items = []
                    for start in range(0, len(missing), 16):
                        batch = missing[start:start + 16]
                        vecs = srv.embeddings([t[:2000] for _, t in batch])
                        for (i, _), vec in zip(batch, vecs):
                            blob = _pack(vec)
                            cached[shas[i]] = blob
                            new_items.append((shas[i], blob, len(vec)))
                    self.db.store_embeddings(new_items, EMBED_MODEL)
                except Exception as exc:  # noqa: BLE001
                    LOG.warning("Embedding non disponibili (ricerca solo per parole chiave): %s", exc)
                    self._failed = True
                    self.stop()
                    return []
                finally:
                    self._last_used = time.time()
        return [_unpack(cached[s]) for s in shas]

    def similarities(self, query: str, texts: List[str]) -> Dict[int, float]:
        vecs = self.embed([query] + list(texts))
        if not vecs:
            return {}
        q = vecs[0]
        return {i: cosine(q, v) for i, v in enumerate(vecs[1:])}

    def idle_seconds(self) -> float:
        return time.time() - self._last_used if self._last_used else 0.0

    def stop(self) -> None:
        srv, self._server = self._server, None
        if srv is not None:
            try:
                srv.stop()
            except Exception:  # noqa: BLE001
                pass
