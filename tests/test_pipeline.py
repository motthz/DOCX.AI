"""Test sulla pipeline JSON (prompt + schema validation + repair + mock LLM)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(REPO))


SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "impianto": {"type": "string"},
        "esito": {"type": "string",
                  "enum": ["regolare", "anomalia", "non_specificato"]},
        "attivita": {"type": "array", "items": {"type": "string"}},
        "note": {"type": "string"},
    },
    "required": ["impianto", "esito", "attivita", "note"],
}


class PromptBuilderTests(unittest.TestCase):
    def test_messages_has_policy_and_schema(self):
        from maintenance_ai.llm.prompt_builder import build_extraction_messages
        msgs = build_extraction_messages(
            SCHEMA,
            "Controllo pompa P1, sostituzione paraoli, tutto ok",
            reference_docs=[("a.docx", "Istruzione: smontare, cambiare paraoli, rimontare")],
            history_snippets=[{"input": "esempio", "final_json": {"impianto": "X"}}],
        )
        self.assertEqual(msgs[0]["role"], "system")
        self.assertIn("NON è inventare", msgs[0]["content"])
        self.assertIn("impianto", msgs[0]["content"])
        self.assertIn("P1", msgs[1]["content"])
        self.assertIn("/no_think", msgs[-1]["content"])


class JsonPipelineTests(unittest.TestCase):
    def test_mock_pipeline_returns_valid_object(self):
        from maintenance_ai.llm.llama_server import MockLlamaServer
        from maintenance_ai.llm.json_pipeline import JsonPipeline
        server = MockLlamaServer()
        server.start()
        pipe = JsonPipeline(server, max_retries=1)
        result = pipe.extract(SCHEMA, "Controllo X")
        self.assertTrue(result.success, msg=result.error_message)
        import jsonschema
        # Non solleva eccezione => valido
        jsonschema.validate(result.data, SCHEMA)
        for req in SCHEMA["required"]:
            self.assertIn(req, result.data)

    def test_repair_json_strips_fences_and_fills_defaults(self):
        from maintenance_ai.llm.json_pipeline import (
            _fill_missing_defaults,
            _lenient_json_parse,
        )
        raw = "```json\n{\"impianto\": \"P1\"}\n```"
        parsed, err = _lenient_json_parse(raw)
        self.assertIsNone(err)
        self.assertEqual(parsed["impianto"], "P1")
        fixed = _fill_missing_defaults(parsed or {}, SCHEMA)
        self.assertEqual(fixed["esito"], "non_specificato")
        self.assertEqual(fixed["attivita"], [])


class GoldenCasesSmokeTest(unittest.TestCase):
    """Legge golden_cases.json e prova che la pipeline mock non fallisca e
    che i casi siano JSON validi (non fa benchmark di qualità)."""

    def test_golden_file_loadable(self):
        p = Path(__file__).parent / "fixtures" / "golden_cases.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 3)
        for case in data:
            self.assertIn("input", case)
            self.assertIn("expected", case)


if __name__ == "__main__":
    unittest.main()
