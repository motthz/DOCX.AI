"""Ollama backend adapter — same protocol as LlamaServer, but targets an
already-running external Ollama service.

Ollama is OPTIONAL: MaintenanceAI does NOT install or start Ollama for the user;
it simply speaks to an existing Ollama listening on 127.0.0.1:11434 if the
config selects `backend = "ollama"`. No network calls outside localhost.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class OllamaBackendOptions:
    url: str = "http://127.0.0.1:11434"
    model: str = "qwen3:0.6b-instruct-q8_0"
    connect_timeout: float = 5.0


class OllamaBackend:
    """Drop-in replacement for LlamaServer. Lifecycle start/stop are no-ops."""

    def __init__(self, options: OllamaBackendOptions):
        self.options = options
        self._running = False

    @property
    def base_url(self) -> str:
        return self.options.url.rstrip("/")

    @property
    def api_key(self) -> str:
        return ""

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Lifecycle: Ollama è esterno — start/stop sono no-op.
    # ------------------------------------------------------------------
    def start(self, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + max(1.0, timeout)
        while time.monotonic() < deadline:
            if self.health_check(timeout=2.0):
                self._running = True
                return
            time.sleep(1.0)
        # Timeout: lancia errore ma non è bloccante come llama — la chain
        # passerà al prossimo fallback.
        raise TimeoutError(
            f"Ollama non raggiungibile su {self.options.url} entro {timeout}s. "
            "Avviare Ollama o selezionare il backend llama_server."
        )

    def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------
    # Health + API
    # ------------------------------------------------------------------
    def health_check(self, timeout: float = 2.0) -> bool:
        # Ollama endpoint root / restituisce "Ollama is running"; usiamo /api/tags
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return 200 <= resp.status < 300
        except Exception:  # noqa: BLE001
            return False

    def chat_completions(
        self,
        messages: list,
        *,
        temperature: float = 0.1,
        max_tokens: int = 1200,
        json_schema: Optional[Dict[str, Any]] = None,
        timeout: float = 600.0,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """POST /v1/chat/completions compatibile Ollama OpenAI layer."""
        payload: Dict[str, Any] = {
            "model": self.options.model,
            "messages": messages,
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
            "stream": False,
        }
        if json_schema:
            payload["response_format"] = {"type": "json_object", "schema": json_schema}
            payload["json_schema"] = json_schema
        if extra:
            payload.update(extra)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        url = f"{self.base_url}/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Content-Length": str(len(body)),
        }
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
            raise RuntimeError(f"Ollama HTTP {exc.code}: {detail[:1200]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Ollama non raggiungibile: {exc}") from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Risposta Ollama non è JSON valido: {exc}. Testo: {raw[:800]}"
            ) from exc
