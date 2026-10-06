"""Test: qualita' delle risposte AI (prompt, contesto, schema imposto al modello,
scelta del modello migliore installato)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(REPO))

from tests.test_ai_setup import _isolated_config  # noqa: E402

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "data_riunione": {"type": "string", "format": "date", "title": "Data",
                          "description": "Data della riunione"},
        "esito": {"type": "string", "enum": ["Approvato", "Respinto"]},
        "importo": {"type": "number"},
        "azioni": {"type": "array", "items": {"type": "object", "properties": {
            "scadenza": {"type": "string", "description": "Entro quando"}}}},
        "note": {"type": "string"},
    },
    "required": ["data_riunione", "esito", "importo", "azioni", "note"],
}


class PromptTests(unittest.TestCase):
    def test_user_description_survives_long_references(self):
        from docx_ai.llm.prompt_builder import build_extraction_messages
        desc = "Riunione con il cliente Rossi, importo 1.250,00 euro. " + "dettaglio " * 300 + "FINE_TESTO"
        refs = [(f"doc{i}.docx", "x" * 20000) for i in range(4)]
        msgs = build_extraction_messages(SCHEMA, desc, reference_docs=refs,
                                         history_snippets=[{"input": "a", "final_json": {"note": "b"}}],
                                         max_prompt_chars=8000)
        user = msgs[1]["content"]
        self.assertIn("FINE_TESTO", user)  # prima veniva tagliata proprio la richiesta
        self.assertTrue(user.rstrip().endswith("/no_think"))
        self.assertLessEqual(len(msgs[0]["content"]) + len(user), 8000)

    def test_today_and_field_semantics(self):
        from docx_ai.llm.prompt_builder import build_extraction_messages
        msgs = build_extraction_messages(SCHEMA, "ieri", today=date(2026, 10, 6))
        system = msgs[0]["content"]
        self.assertIn("DATA DI OGGI: 2026-10-06 (martedì)", system)
        self.assertIn("formato AAAA-MM-GG", system)
        self.assertIn("Data - Data della riunione", system)
        self.assertIn("scadenza", system)
        self.assertIn("Entro quando", system)


class ModelSchemaTests(unittest.TestCase):
    def test_model_can_say_unknown(self):
        from docx_ai.llm.json_pipeline import llm_schema
        relaxed = llm_schema(SCHEMA)
        self.assertIn("NON_SPECIFICATO", relaxed["properties"]["esito"]["enum"])
        self.assertEqual(relaxed["properties"]["importo"]["type"], ["number", "null"])
        self.assertEqual(SCHEMA["properties"]["esito"]["enum"], ["Approvato", "Respinto"])  # originale intatto

    def test_missing_values_are_not_invented(self):
        from docx_ai.llm.json_pipeline import _fill_missing_defaults
        out = _fill_missing_defaults({"importo": "n.d."}, SCHEMA)
        self.assertEqual(out["esito"], "NON_SPECIFICATO")  # prima: "Approvato" (prima opzione)
        self.assertIsNone(out["importo"])                  # prima: 0
        self.assertEqual(_fill_missing_defaults({"importo": "1.250,50"}, SCHEMA)["importo"], 1250.5)
        self.assertEqual(_fill_missing_defaults({"esito": " approvato"}, SCHEMA)["esito"], "Approvato")

    def test_pipeline_accepts_unknown_answers(self):
        from docx_ai.llm.json_pipeline import JsonPipeline
        from docx_ai.llm.llama_server import MockLlamaServer
        seen = {}

        def answer(messages, json_schema=None):
            seen["schema"] = json_schema
            return {"data_riunione": "2026-10-05", "esito": "NON_SPECIFICATO", "importo": None,
                    "azioni": [], "note": "Discussione sul budget"}
        res = JsonPipeline(MockLlamaServer(answer), max_retries=0).extract(SCHEMA, "riunione di ieri")
        self.assertTrue(res.success, res.error_message)
        self.assertEqual(res.attempts, 1)
        self.assertEqual(res.data["esito"], "NON_SPECIFICATO")
        self.assertIn("NON_SPECIFICATO", seen["schema"]["properties"]["esito"]["enum"])

    def test_prompt_budget_follows_context(self):
        from docx_ai.llm.json_pipeline import JsonPipeline, prompt_char_budget
        from docx_ai.llm.llama_server import LlamaServer, LlamaServerOptions
        small = LlamaServer(LlamaServerOptions(runtime_dir=Path("."), context_size=4096))
        big = LlamaServer(LlamaServerOptions(runtime_dir=Path("."), context_size=8192))
        self.assertLess(prompt_char_budget(small, 1500), prompt_char_budget(big, 1500))
        tokens = JsonPipeline._estimate_max_tokens(SCHEMA, small)
        self.assertLess(prompt_char_budget(small, tokens) / 2.8 + tokens, 4096)

    def test_thinking_disabled_in_payload(self):
        from docx_ai.llm.llama_server import LlamaServer, LlamaServerOptions
        srv = LlamaServer(LlamaServerOptions(runtime_dir=Path(".")))
        self.assertEqual(srv._thinking_params(), {"chat_template_kwargs": {"enable_thinking": False}})


def _wide_schema(n: int = 24) -> dict:
    props = {f"campo_{i:02d}": {"type": "string", "title": f"Campo {i}"} for i in range(n)}
    props["righe"] = {"type": "array", "items": {"type": "object", "properties": {
        "descrizione": {"type": "string"}, "quantita": {"type": "string"}}}}
    return {"type": "object", "additionalProperties": False, "properties": props, "required": list(props)}


class GroupedExtractionTests(unittest.TestCase):
    """Moduli lunghi compilati a gruppi di campi: un modello piccolo che deve scrivere
    tutti i campi in una sola risposta ne saltava molti."""

    def test_small_schema_single_call(self):
        from docx_ai.llm.json_pipeline import split_schema
        self.assertEqual(split_schema(SCHEMA), [SCHEMA])

    def test_wide_schema_split_in_order(self):
        from docx_ai.llm.json_pipeline import split_schema
        schema = _wide_schema()
        groups = split_schema(schema, 8)
        self.assertGreater(len(groups), 2)
        keys = [k for g in groups for k in g["properties"]]
        self.assertEqual(keys, list(schema["properties"]))  # nessun campo perso, stesso ordine
        for g in groups:
            self.assertEqual(g["required"], list(g["properties"]))
            self.assertFalse(g["additionalProperties"])
        self.assertEqual(split_schema(schema, 0), [schema])  # 0 = divisione disattivata

    def test_groups_merged_and_prompt_prefix_shared(self):
        from docx_ai.llm.json_pipeline import JsonPipeline
        from docx_ai.llm.llama_server import MockLlamaServer
        schema = _wide_schema()
        calls = []

        def answer(messages, json_schema=None):
            calls.append((messages, json_schema))
            return {k: ("riga" if k != "righe" else [{"descrizione": "x", "quantita": "1"}])
                    for k in json_schema["properties"]}
        res = JsonPipeline(MockLlamaServer(answer), max_retries=0).extract(schema, "testo dell'utente, 1 pezzo")
        self.assertTrue(res.success, res.error_message)
        self.assertGreater(len(calls), 2)
        self.assertEqual(set(res.data), set(schema["properties"]))
        self.assertEqual(res.data["righe"], [{"descrizione": "x", "quantita": "1"}])
        # system identico e messaggio utente che differisce solo in fondo (cache del prompt)
        systems = {c[0][0]["content"] for c in calls}
        self.assertEqual(len(systems), 1)
        first, second = calls[0][0][1]["content"], calls[1][0][1]["content"]
        head = first.index("=== CAMPI DA COMPILARE")
        self.assertEqual(first[:head], second[:head])
        self.assertIn("campo_00", first[head:])
        self.assertNotIn("campo_00", second[head:])

    def test_failed_group_keeps_other_fields(self):
        from docx_ai.llm.json_pipeline import JsonPipeline
        from docx_ai.llm.llama_server import MockLlamaServer
        schema = _wide_schema()

        class Flaky(MockLlamaServer):
            def chat_completions(self, messages, *, json_schema=None, **kw):
                if "campo_00" in json_schema["properties"]:
                    return {"choices": [{"message": {"content": "non è json"}}]}
                return super().chat_completions(messages, json_schema=json_schema, **kw)

        srv = Flaky(lambda m, json_schema=None: {k: "ok" for k in json_schema["properties"]})
        res = JsonPipeline(srv, max_retries=1).extract(schema, "testo")
        self.assertTrue(res.success)
        self.assertEqual(res.data["campo_00"], "NON_SPECIFICATO")  # da completare in revisione
        self.assertEqual(res.data["campo_20"], "ok")
        self.assertTrue(any("non ha compilato" in c and "Campo 0" in c for c in res.corrections))


class BestModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mai_q_"))
        self.cfg = _isolated_config(self.tmp)

    def _install(self, *names):
        for n in names:
            f = self.cfg.data_root / "models" / n
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(b"x")

    def test_best_installed_model_first(self):
        self._install("Qwen3-0.6B-Q8_0.gguf", "Qwen3-1.7B-Q8_0.gguf")
        self.assertEqual([p.name for p in self.cfg.installed_chat_models()],
                         ["Qwen3-1.7B-Q8_0.gguf", "Qwen3-0.6B-Q8_0.gguf"])
        self._install("Qwen3-4B-Q4_K_M.gguf")
        st = self.cfg.ai_components_status()
        self.assertEqual(st["model"].name, "Qwen3-4B-Q4_K_M.gguf")
        self.assertTrue(st["model_ok"])

    def test_compatibility_profile_keeps_light_model(self):
        self._install("Qwen3-0.6B-Q8_0.gguf", "Qwen3-4B-Q4_K_M.gguf")
        self.cfg.set_profile("compatibility")
        self.assertEqual(self.cfg.installed_chat_models()[0].name, "Qwen3-0.6B-Q8_0.gguf")
        # il modello veloce 1.7B (non il poco preciso 0.6B) e' quello del profilo
        self._install("Qwen3-1.7B-Q4_K_M.gguf")
        self.assertEqual(self.cfg.installed_chat_models()[0].name, "Qwen3-1.7B-Q4_K_M.gguf")
        self.cfg.set_profile("fastest")
        self.assertEqual(self.cfg.installed_chat_models()[0].name, "Qwen3-1.7B-Q4_K_M.gguf")
        self.cfg.set_profile("balanced")
        self.assertEqual(self.cfg.installed_chat_models()[0].name, "Qwen3-4B-Q4_K_M.gguf")

    def test_only_4b_installed_counts_as_ready(self):
        self._install("Qwen3-4B-Q4_K_M.gguf")
        self.assertTrue(self.cfg.ai_components_status()["model_ok"])

    def test_default_context_fits_prompt(self):
        self.assertGreaterEqual(int(self.cfg.llm_effective["context_size"]), 8192)
        self.assertEqual(json.loads((REPO / "config" / "default.json").read_text())["llm"]["context_size"], 8192)


class OllamaChoiceTests(unittest.TestCase):
    def test_prefers_larger_qwen(self):
        from docx_ai.docintelligence.ai_service import _params_b
        names = ["qwen3:0.6b", "qwen3:4b", "qwen3:1.7b", "qwen3:32b"]
        names.sort(key=lambda m: -_params_b(m))
        self.assertEqual(names[0], "qwen3:4b")


if __name__ == "__main__":
    unittest.main()
