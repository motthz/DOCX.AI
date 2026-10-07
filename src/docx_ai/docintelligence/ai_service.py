"""AIService: wrapper unificato per tutte le chiamate LLM.

Integra:
- Regole interne software (costante, non modificabile)
- Regole feature (RulesManager, file .txt)
- Regole modulo (RulesManager, file .txt)
- Richiesta utente + documenti di contesto + storico
- JsonPipeline esistente per parsing/validazione JSON
- Log operazioni su DB ai_operations
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config import Config
from ..db import Database
from ..llm.json_pipeline import ExtractionResult, JsonPipeline
from ..llm.llama_server import LlamaServer, LlamaServerOptions, MockLlamaServer
from ..llm.ollama_backend import OllamaBackend, OllamaBackendOptions
from ..llm.prompt_builder import (
    SYSTEM_POLICY as EXTRACTION_POLICY,
    _dates_line,
    _schema_semantics,
    _truncate,
    today_line,
)
from ..services.context_service import ContextService
from ..module_manager import LoadedModule
from .document_retriever import RetrievedChunk
from .rules_manager import RulesManager
from .source_tracker import SourceRef


LOG = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Regole INTERNE del software. Non modificabili dall'utente.
# Ogni feature può specificarne un sottoinsieme + il principio comune.
# ------------------------------------------------------------------
INTERNAL_SOFTWARE_RULES: Dict[str, str] = {
    "base": """PRINCIPI GENERICI DEL SOFTWARE (NON MODIFICABILI):
1. Non inventare MAI date, nomi, codici, numeri, quantità, valori, procedure o persone.
2. Se un'informazione non è disponibile nei documenti di contesto o nel testo dell'utente, usa [DA DEFINIRE] (o NON_SPECIFICATO per i campi JSON).
3. Non trasformare una possibilità ("potrebbe", "dovrebbe") in un fatto certo.
4. Cita SEMPRE la fonte quando l'AI produce testo strutturato.
5. Non modificare o "migliorare" arbitrariamente testo, firme, approvazioni.
6. Preserva la formattazione quando possibile. Avverti se non puoi.
7. Documenti di riferimento = contesto e istruzioni, NON prove di attività eseguite.
8. Storico = forma e terminologia, NON fatti da copiare.
9. Quando valori da fonti diverse sono in conflitto: NON scegliere. Segnala entrambi.
10. L'output non è definitivo: deve essere revisionato dall'utente.
""",
    "document_creation": """REGOLE SPECIFICHE CREAZIONE DOCUMENTO:
- Riprendi terminologia, struttura, stili e intestazioni dai documenti di riferimento.
- Non inventare codici documento, versioni, responsabili, frequenze, liste di controllo.
- Indica sempre [DA DEFINIRE] nelle sezioni in cui non ci sono informazioni sufficienti.
- Cita esplicitamente da quale documento di riferimento hai ripreso una struttura o una frase.
- Non copiare interi documenti: componi solo le parti pertinenti alla richiesta.
- Produci un testo strutturato con titoli, paragrafi, tabelle e passaggi ordinati.
""",
    "document_edit": """REGOLE SPECIFICHE MODIFICA DOCUMENTO:
- Modifica SOLAMENTE le parti esplicitamente richieste.
- Non riformattare, riorganizzare o riscrivere arbitrariamente parti non toccate.
- Se la formattazione non può essere preservata perfettamente, scrivi un avvertimento.
- Produci una NUOVA versione; l'originale non viene mai sovrascritto.
""",
    "document_audit": """REGOLE SPECIFICHE AUDIT DOCUMENTI:
- Agisci come auditor molto scrupoloso. Cerca attivamente anomalie.
- Non dichiarare "non conformità certa" senza prove sufficienti.
- Usa formule prudenziali: "Possibile criticità", "Da verificare", "Informazioni insufficienti".
- Per ogni criticità riporta SEMPRE: titolo, gravità, descrizione, file interessati, pagina/foglio/cella/sezione, evidenza (estratto), motivo della segnalazione, suggerimento di verifica.
- Non riassumere: cerca contraddizioni, dati mancanti, riferimenti inesistenti, date impossibili, versioni incompatibili, catene di tracciabilità interrotte.
""",
    "smart_fill": """REGOLE SPECIFICHE COMPILAZIONE SMART:
- Compila un campo SOLO se esiste evidenza testuale esplicita in almeno un documento.
- Non dedurre da pattern, esempi, o dati storici.
- Se due fonti riportano valori diversi NON scegliere: segnala "Conflitto rilevato" + entrambe le alternative + relative fonti.
- Lascia vuoto o inserisci [DA COMPILARE] in assenza di fonti.
- Per ogni valore prodotto, elenca la fonte (file, pagina, foglio, cella, sezione, estratto).
""",
    "report_compilation": """REGOLE SPECIFICHE REPORTISTICA (esistente):
- Vedi EXTRACTION_POLICY.
- Estrazione strutturata JSON. NON testo libero.
""",
}


def _params_b(model: str) -> float:
    """Miliardi di parametri dal nome Ollama ("qwen3:4b" -> 4); oltre 14B conta 0
    (troppo lento su un PC d'ufficio)."""
    import re
    m = re.search(r"(\d+(?:\.\d+)?)b\b", model.lower())
    size = float(m.group(1)) if m else 0.0
    return size if size <= 14 else 0.0


def _key_tokens(text: str) -> List[str]:
    """Codici, numeri e date di un testo (da non perdere riscrivendolo)."""
    import re
    return list(dict.fromkeys(re.findall(r"\b(?=[\w\-/.,]*\d)[\w][\w\-/.,]*\w|\b\d\b", text or "")))


def _norm_tokens(text: str) -> str:
    import re
    return re.sub(r"[\s\-/.,]", "", (text or "").lower())


def _lost_tokens(tokens: List[str], out: str) -> List[str]:
    """Codici/numeri/date dell'originale assenti nel testo riscritto (una data o un numero
    scritti in altra forma, "05/10/2026" -> "5 ottobre 2026", "2" -> "due", non sono persi)."""
    from ..llm.fact_guard import parse_date_value, source_dates, source_numbers, _number_readings
    norm_out = _norm_tokens(out)
    dates = numbers = None
    lost = []
    for tok in tokens:
        if _norm_tokens(tok) in norm_out:
            continue
        d = parse_date_value(tok)
        if d is not None:
            dates = source_dates(out) if dates is None else dates
            if d in dates:
                continue
        elif any(ch.isdigit() for ch in tok) and not any(ch.isalpha() for ch in tok):
            numbers = source_numbers(out) if numbers is None else numbers
            if any(abs(r - n) < 1e-6 for r in _number_readings(tok) for n in numbers):
                continue
        lost.append(tok)
    return lost


def _improved_text(raw: str) -> str:
    """Testo dalla risposta {"testo": ...}; tollera risposte non JSON (backend senza grammatica)."""
    import re
    raw = (raw or "").strip()
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            raw = str(obj.get("testo") or "")
        elif isinstance(obj, str):
            raw = obj
    except ValueError:
        if raw.startswith("{"):  # JSON troncato (limite di token): il testo fin dove arriva
            m = re.search(r'"testo"\s*:\s*"(.*)', raw, re.S)
            body = re.sub(r'"\s*}?\s*$', "", m.group(1)) if m else ""
            try:
                raw = json.loads('"' + body.rstrip("\\") + '"')
            except ValueError:
                raw = body.replace('\\n', "\n").replace('\\"', '"')
    raw = re.sub(r"^(?:ecco (?:il )?testo[^:\n]*|testo (?:riscritto|migliorato)[^:\n]*):\s*", "", raw.strip(),
                 flags=re.I)
    return raw.strip().strip('"').strip()


@dataclass
class AIResult:
    """Wrapper unificato risultato generico AI."""

    success: bool
    data: Optional[Dict[str, Any]] = None
    error: str = ""
    attempts: int = 0
    raw_text: str = ""
    # Free-text output (for document generation / modification / audit markdown)
    text_output: str = ""
    # References collected from context (for display in UI)
    sources_used: List[SourceRef] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.sources_used is None:
            self.sources_used = []


class AIService:
    def __init__(
        self,
        config: Config,
        db: Database,
        rules: RulesManager,
        *,
        context: Optional[ContextService] = None,
        mock: bool = False,
    ):
        self.config = config
        self.db = db
        self.rules = rules
        self.context = context
        self._pipeline: Optional[JsonPipeline] = None
        self._server_chain: List[Any] = []  # all non-mock servers we started
        self._mock = mock
        self._pipeline_lock = threading.Lock()
        self.backend_label = "non avviato"
        self.ram_warning = ""
        self._last_used = 0.0
        self._idle_stop = threading.Event()
        self._idle_thread: Optional[threading.Thread] = None
        self.semantic = None  # llm.embeddings.SemanticSearch (impostato dall'App)

    # --------------------------------------------------------------
    # LLM pipeline: lazy-init + failover chain + debug artifacts
    # --------------------------------------------------------------
    def pipeline(self, *, use_mock: Optional[bool] = None) -> JsonPipeline:
        if use_mock is None:
            use_mock = self._mock
        if use_mock:
            return JsonPipeline(MockLlamaServer(), max_retries=1)
        # Thread-safe: report extraction and document features run in worker
        # threads and must share ONE llama-server (each one loads ~2 GB of RAM).
        with self._pipeline_lock:
            self._last_used = time.time()
            if self._pipeline is not None:
                return self._pipeline
            self._pipeline = self._build_pipeline()
            return self._pipeline

    # ---- impostazioni (tabella settings) ----
    def _setting(self, key: str, default):
        try:
            from ..services.settings import Settings
            return Settings(self.db).get(key)
        except Exception:  # noqa: BLE001
            return default

    def _runtime_dirs(self, eff: Dict[str, Any]) -> List[Tuple[Path, int]]:
        """Runtime da provare: (cartella, layer GPU). GPU (Vulkan) prima se abilitata."""
        cpu_dir = self.config.resolve_ai_path(eff["runtime_dir"])
        out: List[Tuple[Path, int]] = []
        gpu_pref = str(self._setting("ai.gpu", "auto")).lower()
        if gpu_pref == "auto":
            # solo con una scheda video dedicata: sulla grafica integrata il modello
            # caricato in GPU puo' essere piu' lento che sulla CPU
            from ..llm import hardware
            use_gpu = hardware.detect().gpu_accel
        else:
            use_gpu = gpu_pref == "on"
        if use_gpu:
            gpu_dir = self.config.resolve_ai_path("runtime/llama-vulkan")
            if (gpu_dir / eff.get("runtime_exe", "llama-server.exe")).is_file():
                out.append((gpu_dir, 99))
        out.append((cpu_dir, 0))
        return out

    def _llama_options(self, eff: Dict[str, Any], model_path: Path,
                       context_size: int, runtime_dir: Optional[Path] = None,
                       gpu_layers: int = 0) -> LlamaServerOptions:
        threads = int(self._setting("ai.threads", 0) or 0) or eff.get("thread_override")
        return LlamaServerOptions(
            runtime_dir=runtime_dir or self.config.resolve_ai_path(eff["runtime_dir"]),
            runtime_exe=eff.get("runtime_exe", "llama-server.exe"),
            model_path=model_path,
            context_size=context_size,
            host=eff.get("host", "127.0.0.1"),
            port_min=int(eff.get("port_min", 39280)),
            port_max=int(eff.get("port_max", 39299)),
            no_webui=bool(eff.get("no_webui", True)),
            no_think=bool(eff.get("no_think", True)),
            thread_override=threads,
            gpu_layers=gpu_layers,
        )

    def _try_ollama(self, eff: Dict[str, Any], *, explicit: bool) -> Optional[OllamaBackend]:
        url = str(eff.get("ollama_url", "http://127.0.0.1:11434"))
        model = str(eff.get("ollama_model", "qwen3:0.6b-instruct-q8_0"))
        srv = OllamaBackend(OllamaBackendOptions(url=url, model=model))
        if not srv.health_check(timeout=1.5):
            if explicit:
                LOG.warning("Ollama backend non raggiungibile su %s", url)
            return None
        if not explicit:
            # Auto-detect: use an installed model, preferring Qwen.
            # solo modelli di chat: i modelli di embedding non generano testo
            installed = [m for m in srv.list_models() if "embed" not in m.lower()]
            if not installed:
                return None
            if model not in installed:
                qwen = [m for m in installed if m.lower().startswith("qwen")]
                # il piu' capace (piu' parametri) fino a 14B; a parita' i modelli solo testo
                qwen.sort(key=lambda m: ("vl" in m.lower(), -_params_b(m)))
                srv.options.model = (qwen or installed)[0]
        srv.start(timeout=2.0)
        return srv

    def _model_candidates(self, eff: Dict[str, Any]) -> List[Tuple[Path, int]]:
        """Modelli installati in ordine di preferenza (dal piu' capace), tenendo conto
        della RAM: i modelli che non entrano nella RAM libera passano in fondo, cosi'
        si parte dal migliore che il PC regge senza andare in swap."""
        from ..llm import hardware
        ctx_size = int(self._setting("ai.context", 0) or 0) or int(eff.get("context_size", 8192))
        cands: List[Tuple[Path, int]] = [(p, ctx_size) for p in self.config.installed_chat_models()]
        if len(cands) < 2:
            return cands
        hw = hardware.refresh_memory()
        if not hw.ram_available:
            return cands
        fits = [c for c in cands if hardware.model_ram_need(c[0], c[1]) <= hw.ram_available]
        if not fits:
            self.ram_warning = (f"RAM libera {hw.ram_available_gb} GB: l'AI potrebbe essere lenta. "
                                "Chiudi altri programmi o usa il profilo 'compatibility'.")
            LOG.warning(self.ram_warning)
            return cands
        if fits[0] != cands[0]:
            self.ram_warning = (f"RAM libera {hw.ram_available_gb} GB insufficiente per "
                                f"{cands[0][0].name}: uso {fits[0][0].name}.")
            LOG.warning(self.ram_warning)
        return fits + [c for c in cands if c not in fits]

    def _build_pipeline(self) -> JsonPipeline:
        eff = self.config.llm_effective
        chain: List[Any] = []
        max_retries = max(0, int(eff.get("max_retries", 3)))
        backend = str(eff.get("backend", "llama_server")).lower()
        self.backend_label = "mock"
        self.ram_warning = ""

        # 1) Ollama, if explicitly selected in the config
        if backend == "ollama":
            try:
                srv = self._try_ollama(eff, explicit=True)
                if srv is not None:
                    chain.append(srv)
                    self._server_chain.append(srv)
                    self.backend_label = f"ollama:{srv.options.model}"
            except Exception as exc:  # noqa: BLE001
                LOG.warning(f"Ollama backend non disponibile (procedo con fallback): {exc}")

        # 2) llama.cpp: modello principale o leggero (uno solo in RAM), GPU se disponibile
        if not chain:
            for model_path, csize in self._model_candidates(eff):
                for runtime_dir, gpu_layers in self._runtime_dirs(eff):
                    try:
                        srv = LlamaServer(self._llama_options(eff, model_path, csize, runtime_dir, gpu_layers))
                        srv.start()
                        chain.append(srv)
                        self._server_chain.append(srv)
                        self.backend_label = f"llama:{model_path.name}" + (" (GPU)" if gpu_layers else "")
                        break
                    except Exception as exc:  # noqa: BLE001
                        LOG.warning(f"Llama ({model_path.name}, gpu={gpu_layers}) non disponibile: {exc}")
                if chain:
                    break

        # 3) Auto-detect a locally running Ollama as a last real backend
        if not chain and backend != "ollama":
            try:
                srv = self._try_ollama(eff, explicit=False)
                if srv is not None:
                    chain.append(srv)
                    self._server_chain.append(srv)
                    self.backend_label = f"ollama:{srv.options.model}"
            except Exception as exc:  # noqa: BLE001
                LOG.info(f"Ollama auto-detect fallito: {exc}")

        # 4) Mock deterministico always-on fallback (per sicurezza)
        chain.append(MockLlamaServer())
        if self.backend_label == "mock":
            LOG.warning("Nessun backend AI locale disponibile: uso modalita' manuale (mock).")

        debug_root = None
        if bool(eff.get("debug", False)):
            debug_root = self.config.logs_root() / "llm_debug"

        if len(chain) == 1:
            return JsonPipeline(chain[0], max_retries=max_retries, debug_root=debug_root)
        return JsonPipeline(chain[0], max_retries=max_retries, debug_root=debug_root,
                            server_chain=chain)

    # ---- precaricamento e spegnimento per inattivita' ----
    def touch(self) -> None:
        self._last_used = time.time()

    def preload_async(self) -> None:
        """Avvia il motore AI in background (la prima richiesta e' subito pronta)."""
        def _run():
            try:
                self.pipeline()
                self.touch()
            except Exception as exc:  # noqa: BLE001
                LOG.info("Precaricamento AI fallito: %s", exc)
        threading.Thread(target=_run, daemon=True, name="ai-preload").start()

    def start_idle_watch(self, minutes_fn) -> None:
        """Spegne llama-server dopo N minuti senza richieste (libera la RAM)."""
        if self._idle_thread is not None:
            return

        def _loop():
            while not self._idle_stop.wait(30):
                try:
                    minutes = int(minutes_fn() or 0)
                except Exception:  # noqa: BLE001
                    minutes = 0
                if minutes <= 0:
                    continue
                busy = self._pipeline_lock.locked()
                if (self._pipeline is not None and not busy and self._last_used
                        and time.time() - self._last_used > minutes * 60):
                    LOG.info("Motore AI inattivo da %s minuti: spengo llama-server.", minutes)
                    self.shutdown()
                if self.semantic is not None and self.semantic.idle_seconds() > minutes * 60:
                    self.semantic.stop()
        self._idle_thread = threading.Thread(target=_loop, daemon=True, name="ai-idle")
        self._idle_thread.start()

    @property
    def is_running(self) -> bool:
        return self._pipeline is not None and self.is_real_ai

    # ---- migliora testo (revisione) ----
    def improve_text(self, text: str, field_label: str = "", *, on_delta=None, document: str = "") -> str:
        """Riscrive un testo in forma chiara SENZA aggiungere fatti (solo il testo)."""
        return self.improve_text_checked(text, field_label, document=document)[0]

    def improve_text_checked(self, text: str, field_label: str = "", *, document: str = "",
                             sources: Optional[List[str]] = None, field_description: str = "",
                             ) -> Tuple[str, List[str]]:
        """Riscrive il testo di un campo (o, se il campo e' vuoto, lo scrive dalle
        informazioni fornite) e controlla il risultato: ritorna (testo, avvisi).

        Prima il modello piccolo rispondeva con preamboli ("Ecco il testo:"), cambiava
        lingua, perdeva numeri e codici o ne aggiungeva di nuovi. Ora la risposta e'
        imposta come JSON {"testo": ...} (niente testo di contorno) e confrontata con
        l'originale: codici, numeri, date e nomi aggiunti o persi vengono segnalati e
        provocano un secondo tentativo."""
        import re as _re
        from ..llm.grounding import GroundingChecker

        text = (text or "").strip()
        sources = [s for s in (sources or []) if s and s.strip()]
        compose = len(text) < 5
        if compose and not sources:
            raise ValueError("Il campo è vuoto: scrivi prima qualcosa o fornisci le informazioni da cui partire.")
        field = field_label or "campo"
        if compose:
            system = (
                "Sei un redattore professionale di documenti. Scrivi il contenuto di UN campo di un modulo "
                "usando SOLO le informazioni del testo dell'utente che riguardano quel campo.\n"
                "REGOLE: non aggiungere fatti, numeri, date, nomi, codici o cause che non sono nel testo; "
                "riporta codici, numeri e nomi esattamente come scritti; frasi chiare e complete, tono "
                "professionale; stessa lingua del testo dell'utente. Se il testo non contiene nulla su "
                "questo campo rispondi con testo vuoto.")
            user = ((f"Documento: {document}\n" if document else "")
                    + f"Campo da scrivere: {field}" + (f" ({field_description})" if field_description else "")
                    + "\n\nTesto dell'utente:\n" + _truncate("\n\n".join(sources), 6000, "fonti")
                    + "\n\n/no_think")
            reference = "\n".join(sources)
        else:
            system = (
                "Sei un redattore professionale di documenti aziendali. Migliora la forma del testo di un "
                "campo di un modulo.\n"
                "REGOLE: mantieni TUTTE le informazioni; non aggiungere fatti, numeri, date, nomi, codici, "
                "cause o conclusioni che non sono nel testo; riporta codici, numeri, misure e nomi "
                "ESATTAMENTE come scritti; correggi grammatica, punteggiatura e terminologia tecnica; frasi "
                "brevi e chiare, tono professionale e impersonale; stessa lingua del testo originale; "
                "lunghezza simile all'originale.")
            user = ((f"Documento: {document}\n" if document else "")
                    + f"Campo: {field}" + (f" ({field_description})" if field_description else "")
                    + f"\n\nTesto originale:\n{text}\n\n/no_think")
            reference = "\n".join([text] + sources)
        schema = {"type": "object", "properties": {"testo": {"type": "string"}}, "required": ["testo"],
                  "additionalProperties": False}
        pipe = self.pipeline()
        checker = GroundingChecker([reference])
        must_keep = [] if compose else _key_tokens(text)
        best: Tuple[str, List[str]] = ("", [])
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        max_tokens = min(1500, max(300, int(len(reference if compose else text) / 2.5) + 200))
        for attempt in range(2):
            self.touch()
            resp = pipe.chat(messages, temperature=0.2 if attempt == 0 else 0.1, max_tokens=max_tokens,
                             json_schema=schema)
            self.touch()
            raw = ((resp.get("choices") or [{}])[0].get("message") or {}).get("content", "")
            if not self.is_real_ai:
                raise RuntimeError("Motore AI non disponibile: installa i componenti AI.")
            raw = _re.sub(r"<think>.*?</think>", "", raw or "", flags=_re.S).strip()
            out = _improved_text(raw)
            if not out:
                if compose:
                    raise ValueError("Le informazioni fornite non contengono dati per questo campo.")
                continue
            warnings: List[str] = []
            check = checker.check_value(out)
            if check.status == "missing":
                warnings.append("Dati non presenti nel testo originale: " + ", ".join(check.missing[:5]))
            lost = _lost_tokens(must_keep, out)
            if lost:
                warnings.append("Dati del testo originale che mancano: " + ", ".join(lost[:5]))
            if not compose and len(out) < len(text) * 0.4:
                warnings.append("Il testo riscritto è molto più corto dell'originale.")
            if not best[0] or len(warnings) < len(best[1]):
                best = (out, warnings)
            if not warnings:
                break
            messages = messages + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": "Correggi: " + " ".join(warnings)
                 + ". Riscrivi rispettando le REGOLE, senza aggiungere né togliere dati.\n/no_think"}]
        if not best[0]:
            raise RuntimeError("L'AI non ha restituito un testo valido. Riprova.")
        return best

    @property
    def is_real_ai(self) -> bool:
        return self.backend_label != "mock"

    def reset(self) -> None:
        """Stop running backends so the next call re-detects them (e.g. after
        the AI components were installed or the LLM profile changed)."""
        self.shutdown()

    def close(self) -> None:
        """Chiusura dell'app: ferma anche il controllo di inattivita'."""
        self._idle_stop.set()
        self.shutdown()

    def shutdown(self) -> None:
        excs: List[str] = []
        chain = self._server_chain or []
        for srv in reversed(chain):
            try:
                srv.stop()
            except Exception as exc:  # noqa: BLE001
                excs.append(str(exc))
        if excs:
            LOG.warning(f"Errori durante stop LLM: {excs}")
        self._server_chain = []
        self._pipeline = None
        self.backend_label = "non avviato"

    # --------------------------------------------------------------
    # Log operation to DB
    # --------------------------------------------------------------
    def _log_op(self, feature: str, operation: str, files: List[str],
                sources: List[str], outcome: str, error: str = "") -> int:
        try:
            return self.db.log_ai_operation(
                feature=feature,
                operation=operation[:5000],
                files_json=json.dumps(files, ensure_ascii=False)[:20000],
                sources_json=json.dumps(sources, ensure_ascii=False)[:20000],
                model=Path(self.config.llm_effective.get("model", "")).name,
                outcome=outcome,
                error=error[:5000],
            )
        except Exception as exc:  # noqa: BLE001
            LOG.warning("log ai operation fallito: %s", exc)
            return 0

    # --------------------------------------------------------------
    # 1) JSON extraction (usato da Smart Fill + report esistente)
    # --------------------------------------------------------------
    def extract_structured(
        self,
        feature_key: str,
        schema: Dict[str, Any],
        user_request: str,
        *,
        module: Optional[LoadedModule] = None,
        retrieved_chunks: Optional[List[RetrievedChunk]] = None,
        reference_docs: Optional[List[Tuple[str, str]]] = None,
        history_snippets: Optional[List[Dict[str, Any]]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        use_mock: Optional[bool] = None,
    ) -> AIResult:
        module_folder = module.folder_path if module is not None else None
        internal_block = (
            INTERNAL_SOFTWARE_RULES["base"] + "\n" +
            INTERNAL_SOFTWARE_RULES.get(feature_key, "")
        )
        combined = self.rules.get_combined_rules(
            feature_key, module_folder, internal_rules=internal_block
        )
        system_text = (
            combined.all_text() + "\n\n"
            + EXTRACTION_POLICY + "\n"
            + today_line() + "\n\n"
            + _schema_semantics(schema)
        )
        user_parts: List[str] = []
        if retrieved_chunks:
            user_parts.append("=== BRANI PIÙ PERTINENTI DEI DOCUMENTI (fonti) ===")
            srcs_used: List[SourceRef] = []
            for idx, rc in enumerate(retrieved_chunks, 1):
                fname = rc.file_path.name
                ref = SourceRef(
                    file_name=fname,
                    file_path=rc.file_path,
                    file_sha256=rc.file_sha256,
                    page=rc.chunk.page,
                    sheet=rc.chunk.sheet,
                    cell=rc.chunk.cell_ref,
                    paragraph_index=rc.chunk.paragraph_index,
                    excerpt=_truncate(rc.text, 600, fname),
                    source_kind=rc.chunk.span_source_kind or "native",
                )
                srcs_used.append(ref)
                loc = []
                if ref.page is not None:
                    loc.append(f"pagina={ref.page+1}")
                if ref.sheet:
                    loc.append(f"foglio={ref.sheet}")
                if ref.cell:
                    loc.append(f"cella={ref.cell}")
                loc_str = " ".join(loc)
                user_parts.append(f"--- Fonte #{idx}: {fname} {loc_str} ---\n{ref.excerpt}")
        if reference_docs:
            user_parts.append("=== DOCUMENTI AGGIUNTIVI ===")
            for fname, text in reference_docs:
                user_parts.append(f"--- {fname} ---\n{_truncate(text, 4000, fname)}")
        if history_snippets:
            user_parts.append("=== ESEMPI STORICI (solo forma) ===")
            for snip in history_snippets[:4]:
                inp = snip.get("input", "")
                out = snip.get("final_json") or ""
                if isinstance(out, dict):
                    out = json.dumps(out, ensure_ascii=False)
                user_parts.append(f"I: {inp}\nO: {_truncate(str(out), 1500, 'esempio')}")
        user_parts.append("=== RICHIESTA UTENTE ===")
        user_parts.append(user_request or "(nessuna)")
        dates = _dates_line(user_request or "")
        if dates:
            user_parts.append(dates)
        user_parts.append(
            "\nRestituisci ESCLUSIVAMENTE un JSON valido conforme allo schema. "
            "Nessun testo fuori dall'oggetto JSON."
        )
        user_parts.append("\n/no_think")
        user_text = "\n\n".join(user_parts)

        pipeline = self.pipeline(use_mock=use_mock)
        # Chiamata diretta con il prompt costruito qui (regole, brani delle fonti, richiesta).
        # Prima si usava pipeline.extract(schema, "") che NON riceveva questi messaggi:
        # l'AI vedeva una richiesta vuota e restituiva solo "NON_SPECIFICATO".
        messages = [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ]
        self.touch()
        extraction = self._direct_structured_call(pipeline, schema, messages)
        self.touch()
        if extraction.success and extraction.data:
            from ..llm.fact_guard import verify as _verify_facts
            sources = [user_request or ""] + [rc.text for rc in (retrieved_chunks or [])] \
                + [t for _n, t in (reference_docs or [])]
            extraction.data, fixes = _verify_facts(extraction.data, schema, sources)
            for fix in fixes:
                LOG.info("Controllo dei fatti (%s): %s", feature_key, fix.describe())
        files_list = []
        sources_list = []
        if retrieved_chunks:
            for rc in retrieved_chunks:
                if str(rc.file_path) not in files_list:
                    files_list.append(str(rc.file_path))
            for s in srcs_used:
                sources_list.append(s.to_display())
        outcome = "success" if extraction.success else "error"
        self._log_op(feature_key, user_request, files_list, sources_list,
                     outcome, extraction.error_message)
        return AIResult(
            success=extraction.success,
            data=extraction.data,
            error=extraction.error_message,
            attempts=extraction.attempts,
            raw_text=extraction.raw or "",
            sources_used=srcs_used if retrieved_chunks else [],
        )

    # --------------------------------------------------------------
    # 2) Free-text generation (Creazione / Modifica / Audit testuali)
    # --------------------------------------------------------------
    def generate_free_text(
        self,
        feature_key: str,
        user_request: str,
        *,
        output_schema_hints: Optional[Dict[str, Any]] = None,
        module: Optional[LoadedModule] = None,
        retrieved_chunks: Optional[List[RetrievedChunk]] = None,
        reference_docs: Optional[List[Tuple[str, str]]] = None,
        extra_instructions: str = "",
        max_tokens: int = 2500,
        use_mock: Optional[bool] = None,
    ) -> AIResult:
        module_folder = module.folder_path if module is not None else None
        internal_block = (
            INTERNAL_SOFTWARE_RULES["base"] + "\n" +
            INTERNAL_SOFTWARE_RULES.get(feature_key, "")
        )
        combined = self.rules.get_combined_rules(
            feature_key, module_folder, internal_rules=internal_block
        )
        system_text = combined.all_text() + "\n" + today_line() + "\n\n" + (extra_instructions or "")
        if output_schema_hints:
            system_text += "\n\n" + _schema_semantics(output_schema_hints)
        user_parts: List[str] = []
        srcs_used: List[SourceRef] = []
        if retrieved_chunks:
            user_parts.append("=== BRANI PIÙ PERTINENTI (fonti) ===")
            for idx, rc in enumerate(retrieved_chunks, 1):
                fname = rc.file_path.name
                ref = SourceRef(
                    file_name=fname, file_path=rc.file_path,
                    file_sha256=rc.file_sha256,
                    page=rc.chunk.page, sheet=rc.chunk.sheet, cell=rc.chunk.cell_ref,
                    paragraph_index=rc.chunk.paragraph_index,
                    excerpt=_truncate(rc.text, 800, fname),
                    source_kind=rc.chunk.span_source_kind or "native",
                )
                srcs_used.append(ref)
                loc = []
                if ref.page is not None:
                    loc.append(f"pagina={ref.page+1}")
                if ref.sheet:
                    loc.append(f"foglio={ref.sheet}")
                if ref.cell:
                    loc.append(f"cella={ref.cell}")
                loc_str = " ".join(loc)
                user_parts.append(f"--- Fonte #{idx}: {fname} {loc_str} ---\n{ref.excerpt}")
        if reference_docs:
            user_parts.append("=== DOCUMENTI RIFERIMENTO ===")
            for fname, text in reference_docs:
                user_parts.append(f"--- {fname} ---\n{_truncate(text, 3000, fname)}")
        user_parts.append("=== RICHIESTA UTENTE ===")
        user_parts.append(user_request or "(nessuna)")
        user_parts.append("\n/no_think")
        user_text = "\n\n".join(user_parts)

        pipeline = self.pipeline(use_mock=use_mock)
        try:
            resp = pipeline.chat(
                messages=[
                    {"role": "system", "content": system_text},
                    {"role": "user", "content": user_text},
                ],
                temperature=0.1,
                max_tokens=max_tokens,
                json_schema=output_schema_hints,
                timeout=1200,
            )
            choices = resp.get("choices") or []
            content = (choices[0].get("message") or {}).get("content", "") if choices else ""
            import re as _re
            content = _re.sub(r"<think>.*?</think>", "", content or "", flags=_re.S).strip()
            # Validate JSON if schema requested
            data = None
            if output_schema_hints and content:
                import jsonschema as _js
                try:
                    data = json.loads(content)
                    try:
                        _js.validate(data, output_schema_hints)
                    except _js.ValidationError:
                        data = None
                except Exception:  # noqa: BLE001
                    data = None
            ok = bool(content)
            err = "" if ok else "LLM ha restituito testo vuoto"
            files_list = []
            if retrieved_chunks:
                for rc in retrieved_chunks:
                    if str(rc.file_path) not in files_list:
                        files_list.append(str(rc.file_path))
            self._log_op(feature_key, user_request, files_list,
                         [s.to_display() for s in srcs_used],
                         "success" if ok else "error", err)
            return AIResult(
                success=ok,
                data=data,
                error=err,
                attempts=1,
                raw_text=content,
                text_output=content,
                sources_used=srcs_used,
            )
        except Exception as exc:  # noqa: BLE001
            self._log_op(feature_key, user_request, [], [], "error", str(exc))
            return AIResult(success=False, error=str(exc), attempts=0)

    @staticmethod
    def _fit_messages(messages: List[Dict[str, str]], budget: int) -> List[Dict[str, str]]:
        """Accorcia i brani delle fonti (inizio del messaggio utente) quando il prompt
        supera il contesto del modello, conservando la richiesta in fondo."""
        total = sum(len(m.get("content", "")) for m in messages)
        if total <= budget or not messages or messages[-1].get("role") != "user":
            return messages
        user = messages[-1]["content"]
        marker = user.rfind("=== RICHIESTA UTENTE ===")
        if marker <= 0:
            return messages
        head, tail = user[:marker], user[marker:]
        keep = max(0, len(head) - (total - budget))
        head = head[:keep] + ("\n...[fonti accorciate per il limite di contesto]...\n\n" if keep < len(head) else "")
        return messages[:-1] + [{"role": "user", "content": head + tail}]

    # --------------------------------------------------------------
    # Helper: bypass structured extraction fallback via direct call
    # --------------------------------------------------------------
    def _direct_structured_call(
        self,
        pipeline: JsonPipeline,
        schema: Dict[str, Any],
        messages: List[Dict[str, str]],
    ) -> ExtractionResult:
        from ..llm.json_pipeline import (
            _fill_missing_defaults, _lenient_json_parse, llm_schema, prompt_char_budget,
        )
        model_schema = llm_schema(schema)
        max_tokens = pipeline._estimate_max_tokens(schema, pipeline.server)
        messages = self._fit_messages(messages, prompt_char_budget(pipeline.server, max_tokens))
        last_error = ""
        attempts = 0
        for attempt in range(pipeline.max_retries + 1):
            attempts = attempt + 1
            try:
                resp = pipeline.chat(
                    messages=messages,
                    temperature=0.05 if attempt == 0 else 0.2,
                    max_tokens=max_tokens,
                    json_schema=model_schema,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = f"Chiamata LLM fallita: {exc}"
                continue
            choices = resp.get("choices") or []
            if not choices:
                last_error = "Risposta LLM vuota"
                continue
            raw = (choices[0].get("message") or {}).get("content", "")
            parsed, err = _lenient_json_parse(raw)
            if parsed is None:
                last_error = f"Parsing JSON fallito: {err}"
                messages = pipeline._append_repair_messages(messages, raw, last_error)
                continue
            if not isinstance(parsed, dict):
                parsed = {"value": parsed}
            repaired = _fill_missing_defaults(parsed, schema)
            import jsonschema
            try:
                jsonschema.validate(repaired, model_schema)
            except jsonschema.ValidationError as exc:
                last_error = f"Schema validation fallito: {exc.message}"
                messages = pipeline._append_repair_messages(messages, raw, last_error)
                continue
            return ExtractionResult(
                success=True, data=repaired, error_message="",
                attempts=attempts, raw=raw,
            )
        return ExtractionResult(
            success=False, data=None, error_message=last_error or "Fallimento",
            attempts=attempts, raw=None,
        )
