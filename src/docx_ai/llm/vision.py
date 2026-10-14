"""Lettura avanzata della scrittura a mano con un modello che "vede" le immagini.

L'OCR di Windows non legge il corsivo (oltre il 50% dei caratteri sbagliati nelle prove
con la scrittura corsiva); Qwen3-VL lo trascrive quasi senza errori. Il modello e'
facoltativo (~1,5 GB, da "Componenti AI") e viene caricato solo quando l'utente chiede
la lettura avanzata: sulla CPU richiede da qualche secondo a un paio di minuti a
pagina, poi si spegne da solo per liberare la RAM.
"""

from __future__ import annotations

import base64
import io
import logging
import threading
from pathlib import Path
from typing import Any, Optional

from .llama_server import LlamaServer, LlamaServerOptions

LOG = logging.getLogger(__name__)

VISION_MODEL_FILE = "Qwen3VL-2B-Instruct-Q4_K_M.gguf"
VISION_MMPROJ_FILE = "mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf"
# lato lungo massimo dell'immagine inviata: piu' pixel = piu' "parole visive" da leggere
# (tempo sulla CPU), oltre questa misura la scrittura resta leggibile lo stesso
MAX_SIDE = 1280
IDLE_SECONDS = 120

PROMPT = ("Trascrivi esattamente il testo scritto (anche a mano) nell'immagine, riga per riga, "
          "nella lingua originale. Copia numeri, codici e date come sono scritti. Scrivi solo il testo, "
          "senza commenti. Se una parola è illeggibile scrivi [?].")


class HandwritingReader:
    def __init__(self, config: Any, *, thread_override: Optional[int] = None):
        self.config = config
        self.thread_override = thread_override
        self._server: Optional[LlamaServer] = None
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None

    # ------------------------------------------------------------------
    def _paths(self):
        eff = self.config.llm_effective
        runtime = self.config.resolve_ai_path(eff.get("runtime_dir", "runtime/llama"))
        models = self.config.resolve_ai_path(eff.get("model_dir", "models"))
        return runtime, models / VISION_MODEL_FILE, models / VISION_MMPROJ_FILE

    def available(self) -> bool:
        runtime, model, mmproj = self._paths()
        exe = runtime / self.config.llm_effective.get("runtime_exe", "llama-server.exe")
        return exe.is_file() and model.is_file() and mmproj.is_file()

    @staticmethod
    def _image_data_uri(path: Path) -> str:
        from PIL import Image, ImageOps
        img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")  # foto del telefono ruotate
        if max(img.size) > MAX_SIDE:
            img.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

    def read(self, image_path: Path, *, timeout: float = 900.0) -> str:
        """Testo dell'immagine (avvia il modello se serve; puo' richiedere minuti)."""
        if not self.available():
            raise RuntimeError("Modello per la lettura avanzata non installato (Componenti AI).")
        uri = self._image_data_uri(Path(image_path))
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            if self._server is None or not self._server.is_running:
                runtime, model, mmproj = self._paths()
                eff = self.config.llm_effective
                self._server = LlamaServer(LlamaServerOptions(
                    runtime_dir=runtime, runtime_exe=eff.get("runtime_exe", "llama-server.exe"),
                    model_path=model, mmproj=mmproj, context_size=8192, speculative=False,
                    thread_override=self.thread_override or eff.get("thread_override")))
                self._server.start(timeout=300)
            try:
                resp = self._server.chat_completions(
                    [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": uri}},
                                                  {"type": "text", "text": PROMPT}]}],
                    temperature=0.0, max_tokens=1500, timeout=timeout)
            finally:
                self._timer = threading.Timer(IDLE_SECONDS, self.stop)
                self._timer.daemon = True
                self._timer.start()
        text = ((resp.get("choices") or [{}])[0].get("message") or {}).get("content", "")
        return (text or "").strip()

    def stop(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            srv, self._server = self._server, None
        if srv is not None:
            try:
                srv.stop()
            except Exception as exc:  # noqa: BLE001
                LOG.info("Arresto lettura avanzata: %s", exc)
