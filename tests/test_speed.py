"""Velocita' (motore AI sulla CPU, pre-lettura del prompt) e testi scritti male o a mano."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from docx_ai.docintelligence import ocr_service  # noqa: E402
from docx_ai.llm import fact_guard as fg  # noqa: E402
from docx_ai.llm import llama_server as ls  # noqa: E402
from docx_ai.llm.json_pipeline import JsonPipeline  # noqa: E402
from docx_ai.llm.llama_server import MockLlamaServer  # noqa: E402


def _schema():
    return json.loads((ROOT / "examples" / "modules" / "Verbale_di_riunione" / "schema.json")
                      .read_text(encoding="utf-8"))


class _Recorder(MockLlamaServer):
    def __init__(self):
        super().__init__()
        self.calls = []

    def chat_completions(self, messages, **kw):
        self.calls.append((messages, kw))
        return super().chat_completions(messages, **kw)


class PrewarmTest(unittest.TestCase):
    def test_prewarm_sends_the_same_system_prompt_as_the_extraction(self):
        # MockLlamaServer viene saltato dalla pre-lettura: sottoclasse "vera" per il test
        class Real(_Recorder):
            pass
        srv = Real()
        with mock.patch("docx_ai.llm.json_pipeline.MockLlamaServer", type("X", (), {})):
            pipe = JsonPipeline(srv, max_retries=0)
            self.assertTrue(pipe.prewarm(_schema(), document_context="Verbale"))
            pipe.verify_placement = False
            pipe.extract(_schema(), "Riunione del 2 ottobre in sala B con Giulia Neri.", document_context="Verbale")
        warm_system = srv.calls[0][0][0]["content"]
        first_system = srv.calls[1][0][0]["content"]
        self.assertEqual(warm_system, first_system)  # stesso prefisso: llama-server lo riusa dalla cache
        self.assertEqual(srv.calls[0][1].get("max_tokens"), 1)

    def test_prewarm_without_real_ai_does_nothing(self):
        srv = _Recorder()
        self.assertFalse(JsonPipeline(srv).prewarm(_schema()))
        self.assertEqual(srv.calls, [])


class EngineOptionsTest(unittest.TestCase):
    def _cmd_env(self, help_text: str, gpu_layers: int = 0):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "llama-server.exe").write_bytes(b"x")
        (tmp / "m.gguf").write_bytes(b"x")
        opts = ls.LlamaServerOptions(runtime_dir=tmp, model_path=tmp / "m.gguf", gpu_layers=gpu_layers)
        seen = {}

        class Stop(Exception):
            pass

        def fake_popen(cmd, **kw):
            seen["cmd"], seen["env"] = cmd, kw.get("env") or {}
            raise Stop

        with mock.patch.object(ls, "_runtime_help", return_value=help_text), \
                mock.patch.object(ls.subprocess, "Popen", side_effect=fake_popen):
            with self.assertRaises(Stop):
                ls.LlamaServer(opts).start(timeout=1)
        return seen["cmd"], seen["env"]

    def test_cpu_runtime_disables_flash_attention_via_environment(self):
        cmd, env = self._cmd_env("")
        self.assertEqual(env.get("LLAMA_ARG_FLASH_ATTN"), "off")
        self.assertNotIn("-fa", cmd)  # le build vecchie non conoscono "-fa off"

    def test_gpu_runtime_keeps_flash_attention(self):
        _cmd, env = self._cmd_env("", gpu_layers=99)
        self.assertNotEqual(env.get("LLAMA_ARG_FLASH_ATTN"), "off")

    def test_speculative_decoding_only_when_supported(self):
        cmd, _ = self._cmd_env("--spec-type ... --spec-ngram-map-k-size-n N")
        self.assertIn("ngram-map-k", cmd)
        cmd, _ = self._cmd_env("vecchia build senza decodifica speculativa")
        self.assertNotIn("--spec-type", cmd)

    def test_runtime_help_failure_is_harmless(self):
        with mock.patch.object(ls.subprocess, "run", side_effect=OSError("bloccato")):
            tmp = Path(tempfile.mkdtemp()) / "llama-server.exe"
            tmp.write_bytes(b"x")
            self.assertEqual(ls._runtime_help(tmp), "")


class MessyDatesTest(unittest.TestCase):
    TODAY = date(2026, 10, 12)

    def _dates(self, text):
        return [(m.words, m.date) for m in fg.date_mentions_ctx(text, self.TODAY)]

    def test_short_dates_written_in_a_hurry(self):
        self.assertIn(("entro 31/10", date(2026, 10, 31)), self._dates("restituz entro 31/10. cauz 20"))
        self.assertEqual(self._dates("ferie dal 9 al 13/11 5 gg"),
                         [("dal 9", date(2026, 11, 9)), ("al 13/11", date(2026, 11, 13))])
        self.assertEqual(self._dates("stamatina consegnate"), [("stamatina", self.TODAY)])

    def test_fractions_are_not_dates(self):
        self.assertEqual(self._dates("tolleranza entro 2/3 della corsa"), [])
        self.assertEqual(self._dates("tolleranza entro 3/4 mm"), [])


class OcrReadingChoiceTest(unittest.TestCase):
    def test_clearly_better_variant_wins(self):
        bad = "Rapporto n. 245/26. nelupepartoAffettatiAinea e la lama dentata HTD 8 M -1200. %ermivue"
        good = ("Rapporto n. 245/26. Lunedì scorso nel reparto Affettati, linea 2, l'affettatrice AF-300 "
                "faceva un rumore metallico e la lama vibrava.")
        self.assertEqual(ocr_service._best_reading([bad, good]), good)

    def test_original_kept_when_variants_are_not_clearly_better(self):
        orig = "Sos+i+oti+i 2 cuscinetti e la cinghia del motore"
        similar = "Sostituiti 2 cuscinetti e la cinghia del motore"
        self.assertEqual(ocr_service._best_reading([orig, similar]), orig)
        self.assertEqual(ocr_service._best_reading([]), "")

    def test_variants_are_created_for_images(self):
        from PIL import Image
        tmp = Path(tempfile.mkdtemp())
        Image.new("RGB", (200, 80), "white").save(tmp / "p.png")
        out = ocr_service._ocr_variants(tmp / "p.png", tmp)
        self.assertEqual(len(out), 3)
        self.assertTrue(all(p.is_file() for p in out))
        (tmp / "x.pdf").write_bytes(b"%PDF")
        self.assertEqual(ocr_service._ocr_variants(tmp / "x.pdf", tmp), [])


if __name__ == "__main__":
    unittest.main()
