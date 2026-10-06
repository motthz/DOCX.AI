"""llama-server.exe process lifecycle + lightweight HTTP client.

Design goals:
- Start llama-server.exe on a free loopback port (range configurable).
- Generate a per-launch random API key, never expose the server on the LAN.
- Disable web UI, use CPU-only profile.
- Gracefully terminate on application close.
- Provide synchronous HTTP client using only standard library (urllib) so we
  do not add another third-party dependency.
"""

from __future__ import annotations

import json
import os
import random
import secrets
import socket
import string
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


def _cpu_threads(override: Optional[int]) -> int:
    """Thread di generazione: un thread per core fisico. La generazione e' limitata
    dalla banda della memoria, i core logici in piu' (hyper-threading) la rallentano;
    prima il limite fisso a 6 lasciava inutilizzata meta' delle CPU da 8+ core."""
    logical = os.cpu_count() or 2
    if override:
        return max(1, int(override))
    if logical >= 8:
        return min(16, logical // 2)
    return max(1, logical - 1)


def _batch_threads(override: Optional[int]) -> int:
    """Thread per leggere il prompt (calcolo puro): tutti i core logici."""
    if override:
        return max(1, int(override))
    return max(1, os.cpu_count() or 2)


def _random_api_key(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
        except OSError:
            return True
        return False


def _pick_free_port(host: str, port_min: int, port_max: int) -> int:
    # Shuffle to reduce colliding across restarts
    candidates = list(range(port_min, port_max + 1))
    random.shuffle(candidates)
    for port in candidates:
        if not _port_in_use(host, port):
            return port
    raise RuntimeError(f"Nessuna porta libera tra {port_min} e {port_max}")


@dataclass
class LlamaServerOptions:
    runtime_dir: Path
    runtime_exe: str = "llama-server.exe"
    model_path: Path = field(default_factory=lambda: Path("models/Qwen3-1.7B-Q8_0.gguf"))
    context_size: int = 4096
    host: str = "127.0.0.1"
    port_min: int = 39280
    port_max: int = 39299
    no_webui: bool = True
    no_think: bool = True
    thread_override: Optional[int] = None
    # Used for stdout/stderr redirection when --log-disable is not available
    capture_logs: bool = True
    # Layer del modello da caricare in GPU (runtime Vulkan/CUDA); 0 = solo CPU
    gpu_layers: int = 0
    # Server di embedding (ricerca semantica) invece che di chat
    embedding: bool = False
    # slot del server (0 = predefinito di llama.cpp)
    parallel: int = 1

    def executable_path(self) -> Path:
        return Path(self.runtime_dir) / self.runtime_exe


class LlamaServer:
    """Manages a single llama-server.exe process used exclusively by this app."""

    def __init__(self, options: LlamaServerOptions):
        self.options = options
        self._process: Optional[subprocess.Popen] = None
        self._api_key: str = _random_api_key()
        self._port: int = 0
        self._stop_lock = threading.Lock()
        self._watchdog: Optional[threading.Thread] = None
        self._stdout_drain_thread: Optional[threading.Thread] = None
        self._stdout_buffer: bytes = b""

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def base_url(self) -> str:
        if not self._port:
            raise RuntimeError("llama-server non ancora avviato")
        return f"http://{self.options.host}:{self._port}"

    @property
    def api_key(self) -> str:
        return self._api_key

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self, timeout: float = 180.0) -> None:
        if self.is_running:
            return
        opts = self.options
        exe = opts.executable_path()
        model = Path(opts.model_path)
        if not exe.exists():
            raise FileNotFoundError(
                f"Runtime llama.cpp non trovato: {exe}. "
                "Copiare la build ufficiale in runtime/llama/."
            )
        if not model.exists():
            raise FileNotFoundError(
                f"Modello GGUF non trovato: {model}. "
                "Posizionare il file nella cartella models/."
            )
        self._port = _pick_free_port(opts.host, opts.port_min, opts.port_max)
        cmd = [
            str(exe),
            "-m", str(model),
            "--host", opts.host,
            "--port", str(self._port),
            "--api-key", self._api_key,
            "--ctx-size", str(max(512, int(opts.context_size))),
            "--threads", str(_cpu_threads(opts.thread_override)),
            "--threads-batch", str(_batch_threads(opts.thread_override)),
        ]
        if opts.parallel:
            # un solo utente: un solo slot con tutto il contesto e la cache del prompt
            # (con piu' slot la richiesta successiva puo' finire in uno slot "freddo")
            cmd += ["--parallel", str(int(opts.parallel))]
        if opts.gpu_layers:
            cmd += ["--n-gpu-layers", str(int(opts.gpu_layers))]
        if opts.embedding:
            cmd += ["--embedding", "--pooling", "last"]
        if opts.no_webui:
            cmd.append("--no-webui")
        if not opts.embedding:
            # template di chat del modello (Qwen3): necessario perche' enable_thinking=false
            # disattivi davvero il ragionamento invece di affidarsi al solo "/no_think"
            cmd.append("--jinja")
            if opts.no_think:
                # blocco anche lato server: alcuni prompt facevano comunque "ragionare"
                # Qwen3, che esauriva i token e restituiva una risposta vuota (minuti persi)
                cmd += ["--reasoning-budget", "0"]
        # Disable MMAP/MLock where not applicable: keep defaults, they work on CPU
        creationflags = 0
        if os.name == "nt":
            # DETACHED_PROCESS would lose stdio; CREATE_NO_WINDOW hides the console.
            creationflags = 0x08000000  # CREATE_NO_WINDOW
        stdout = subprocess.PIPE if opts.capture_logs else subprocess.DEVNULL
        stderr = subprocess.STDOUT if opts.capture_logs else subprocess.DEVNULL
        try:
            self._process = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                creationflags=creationflags,
                cwd=str(Path(exe).resolve().parent),
            )
        except OSError as exc:
            raise RuntimeError(f"Impossibile avviare llama-server.exe: {exc}") from exc

        if opts.capture_logs and self._process.stdout is not None:
            def _drain() -> None:
                try:
                    proc = self._process
                    if proc is None or proc.stdout is None:
                        return
                    buf: List[bytes] = []
                    while True:
                        chunk = proc.stdout.read(4096)
                        if not chunk:
                            break
                        buf.append(chunk)
                    try:
                        self._stdout_buffer = b"".join(buf)
                    except Exception:
                        pass
                except Exception:
                    pass
            self._stdout_drain_thread = threading.Thread(
                target=_drain, name="llama-stdout-drain", daemon=True
            )
            self._stdout_drain_thread.start()

        deadline = time.monotonic() + timeout
        last_err: Optional[str] = None
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                rc = self._process.returncode
                extra = ""
                try:
                    if self._stdout_drain_thread is not None:
                        self._stdout_drain_thread.join(timeout=2.0)
                    if self._stdout_buffer:
                        extra = self._stdout_buffer.decode("utf-8", errors="replace")
                    elif opts.capture_logs and self._process.stdout is not None:
                        extra = self._process.stdout.read(4096).decode("utf-8", errors="replace")
                except Exception:
                    pass
                raise RuntimeError(
                    f"llama-server.exe terminato all'avvio (exit={rc}). "
                    f"Output: {extra[:1500]}"
                )
            try:
                if self.health_check():
                    self._start_watchdog()
                    self._warmup_ping()
                    return
            except Exception as exc:  # noqa: BLE001
                last_err = str(exc)
            time.sleep(1.5)
        # Timeout
        self.stop()
        raise TimeoutError(
            f"llama-server non ha risposto entro {timeout}s. Ultimo errore: {last_err}"
        )

    def stop(self) -> None:
        with self._stop_lock:
            if self._process is None:
                return
            process = self._process
            self._process = None
        try:
            if process.poll() is None:
                try:
                    process.terminate()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    try:
                        process.kill()
                    except Exception:  # noqa: BLE001
                        pass
        finally:
            try:
                if self._stdout_drain_thread is not None:
                    self._stdout_drain_thread.join(timeout=2.0)
                    self._stdout_drain_thread = None
            except Exception:  # noqa: BLE001
                pass
            try:
                if process.stdout:
                    process.stdout.close()
            except Exception:  # noqa: BLE001
                pass

    def _start_watchdog(self) -> None:
        def loop() -> None:
            while True:
                time.sleep(2)
                with self._stop_lock:
                    if self._process is None:
                        return
                if self._process.poll() is not None:
                    return

        self._watchdog = threading.Thread(target=loop, name="llama-watchdog", daemon=True)
        self._watchdog.start()

    def _warmup_ping(self) -> None:
        """Load model fully into RAM with a minimal call; non-fatal on failure."""
        schema = {
            "type": "object",
            "properties": {"ping": {"type": "string"}},
            "required": [],
        }
        messages = [
            {"role": "system", "content": "Rispondi esclusivamente con JSON."},
            {"role": "user", "content": "ping\n\n/no_think"},
        ]
        import logging as _lg
        try:
            self.chat_completions(
                messages, temperature=0.0, max_tokens=24,
                json_schema=schema, timeout=30.0,
            )
            _lg.getLogger(__name__).info("LLM warm-up ping completato.")
        except Exception as exc:  # noqa: BLE001
            _lg.getLogger(__name__).info(f"LLM warm-up ping saltato: {exc}")

    # ------------------------------------------------------------------
    # Client helpers
    # ------------------------------------------------------------------
    def _headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        h = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if extra:
            h.update(extra)
        return h

    def health_check(self, timeout: float = 5.0) -> bool:
        req = urllib.request.Request(f"{self.base_url}/health", headers=self._headers(), method="GET")
        try:
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
        """POST /v1/chat/completions with optional response_format JSON Schema.

        llama.cpp supports ``response_format = {"type": "json_object",
        "schema": <jsonschema>}`` as well as the short ``json_schema: {...}``.
        We emit both keys for broader compatibility across pinned builds.
        """
        payload: Dict[str, Any] = {
            "messages": messages,
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
            "stream": False,
        }
        if json_schema:
            payload["response_format"] = {"type": "json_object", "schema": json_schema}
            payload["json_schema"] = json_schema
        payload.update(self._thinking_params())
        if extra:
            payload.update(extra)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=body,
            headers=self._headers({"Content-Length": str(len(body))}),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
            raise RuntimeError(
                f"LLM HTTP {exc.code}: {detail[:1200]}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"LLM non raggiungibile: {exc}") from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Risposta LLM non è JSON valido: {exc}. Testo: {raw[:800]}"
            ) from exc


    def _thinking_params(self) -> Dict[str, Any]:
        """Qwen3 senza ragionamento: risposte dirette (il "pensiero" consumava i token
        della risposta e, con lo schema JSON, finiva troncato)."""
        if not self.options.no_think:
            return {}
        return {"chat_template_kwargs": {"enable_thinking": False}}

    def chat_completions_stream(self, messages: list, *, on_delta, temperature: float = 0.1,
                                max_tokens: int = 1200, json_schema: Optional[Dict[str, Any]] = None,
                                timeout: float = 600.0, extra: Optional[Dict[str, Any]] = None
                                ) -> Dict[str, Any]:
        """Come chat_completions ma in streaming (SSE): ``on_delta(testo)`` riceve
        ogni frammento generato. Ritorna una risposta nello stesso formato."""
        payload: Dict[str, Any] = {"messages": messages, "temperature": float(temperature),
                                   "max_tokens": int(max_tokens), "stream": True}
        model_name = getattr(getattr(self, "options", None), "model", None)
        if isinstance(model_name, str):  # Ollama richiede il nome del modello
            payload["model"] = model_name
        if json_schema:
            payload["response_format"] = {"type": "json_object", "schema": json_schema}
            payload["json_schema"] = json_schema
        thinking = getattr(self, "_thinking_params", None)
        if callable(thinking):
            payload.update(thinking())
        if extra:
            payload.update(extra)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(f"{self.base_url}/v1/chat/completions", data=body,
                                     headers=self._headers({"Content-Length": str(len(body))}), method="POST")
        parts: list = []
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    for ch in chunk.get("choices") or []:
                        delta = (ch.get("delta") or {}).get("content")
                        if delta:
                            parts.append(delta)
                            try:
                                on_delta(delta)
                            except Exception:  # noqa: BLE001
                                pass
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
            raise RuntimeError(f"LLM HTTP {exc.code}: {detail[:1200]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"LLM non raggiungibile: {exc}") from exc
        return {"choices": [{"message": {"content": "".join(parts)}}], "usage": {}}

    def embeddings(self, texts: list, *, timeout: float = 300.0) -> list:
        """POST /v1/embeddings: un vettore per testo (server avviato con embedding=True)."""
        body = json.dumps({"input": texts}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(f"{self.base_url}/v1/embeddings", data=body,
                                     headers=self._headers({"Content-Length": str(len(body))}), method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        items = sorted(payload.get("data", []), key=lambda d: d.get("index", 0))
        return [d["embedding"] for d in items]


# Exposed for tests: an in-process mock
class MockLlamaServer:
    """Drop-in stub returning deterministic JSON responses for tests/self-test."""

    def __init__(self, response_fn=None):
        self._response_fn = response_fn
        self._running = False

    @property
    def base_url(self) -> str:
        return "http://mock.local"

    @property
    def api_key(self) -> str:
        return "mock-key"

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self, timeout: float = 1.0) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def health_check(self, timeout: float = 0.1) -> bool:
        return self._running

    def chat_completions(self, messages, *, temperature=0.1, max_tokens=1200,
                         json_schema=None, timeout=5.0, extra=None):
        if self._response_fn is not None:
            out = self._response_fn(messages, json_schema=json_schema)
        else:
            import copy
            props = (json_schema or {}).get("properties", {})
            obj: Dict[str, Any] = {}
            for k, spec in props.items():
                t = spec.get("type")
                enum = spec.get("enum")
                const = spec.get("const")
                if const is not None:
                    obj[k] = copy.deepcopy(const)
                elif enum:
                    obj[k] = next((e for e in enum if "specificato" in str(e).lower()), enum[0])
                elif t == "array":
                    obj[k] = []
                elif t == "object":
                    obj[k] = {}
                else:
                    obj[k] = "NON_SPECIFICATO"
            out = obj
        return {
            "id": "mock",
            "choices": [{"message": {"content": json.dumps(out, ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }
