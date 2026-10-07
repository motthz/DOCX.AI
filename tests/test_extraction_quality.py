"""Test: compilazione precisa anche con il modello piccolo.

- significato dei campi dedotto dal nome (data, firma, codice, caselle Sì/No a coppie)
- date riconosciute in tutte le forme e assegnate al campo giusto in base alle parole vicine
- risposta con prova ("evidenza"): deduzioni senza una frase del testo tolte
"""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

TODAY = date(2026, 10, 6)  # martedì


class FieldSemanticsTests(unittest.TestCase):
    def test_kinds_from_names(self):
        from docx_ai.llm.field_semantics import kind
        s = {"type": "string"}
        self.assertEqual(kind("data", s), "date")
        self.assertEqual(kind("data_intervento", s), "date")
        self.assertEqual(kind("dataRiunione", s), "date")
        self.assertEqual(kind("scadenza", s), "date")
        self.assertEqual(kind("dati_tecnici", s), "text")  # "dati" non e' "data"
        self.assertEqual(kind("firma_operatore_manutenzione", s), "person")
        self.assertEqual(kind("numero_rapporto", s), "code")
        self.assertEqual(kind("ora_inizio", s), "time")
        self.assertEqual(kind("apparecchiatura", s), "text")
        self.assertEqual(kind("x", {"type": "string", "title": "Data di consegna"}), "date")
        self.assertEqual(kind("esito", {"type": "string", "enum": ["a", "b"]}), "choice")

    def test_yes_no_pairs(self):
        from docx_ai.llm.field_semantics import pair_partner
        props = {"pulizia_si": {"type": "boolean"}, "pulizia_no": {"type": "boolean"},
                 "sanificazione_no": {"type": "boolean"}}
        self.assertEqual(pair_partner("pulizia_si", props), "pulizia_no")
        self.assertEqual(pair_partner("pulizia_no", props), "pulizia_si")
        self.assertIsNone(pair_partner("sanificazione_no", props))


class DateMentionTests(unittest.TestCase):
    def mentions(self, text):
        from docx_ai.llm.fact_guard import date_mentions_ctx
        return [(m.words, m.date.isoformat()) for m in date_mentions_ctx(text, TODAY)]

    def test_many_forms(self):
        cases = {
            "riunione del 2 ottobre": ("2 ottobre", "2026-10-02"),
            "il 1° ottobre": ("1° ottobre", "2026-10-01"),
            "il primo ottobre": ("primo ottobre", "2026-10-01"),
            "intervento lunedì scorso": ("lunedì scorso", "2026-10-05"),
            "consegna venerdì prossimo": ("venerdì prossimo", "2026-10-09"),
            "la scorsa settimana, giovedì scorso": ("giovedì scorso", "2026-10-01"),
            "preventivo entro il 30/11.": ("entro il 30/11", "2026-11-30"),
            "collaudo tra due settimane": ("tra due settimane", "2026-10-20"),
            "guasto 3 giorni fa": ("3 giorni fa", "2026-10-03"),
            "verbale del 05.10.26": ("05.10.26", "2026-10-05"),
            "l'altro ieri in sala A": ("l'altro ieri", "2026-10-04"),
        }
        for text, expected in cases.items():
            self.assertIn(expected, self.mentions(text), text)

    def test_day_only_takes_month_of_previous_date(self):
        found = self.mentions("Riunione del 2 novembre con Rossi: prossimo incontro il 15.")
        self.assertIn(("il 15", "2026-11-15"), found)

    def test_ranges(self):
        found = self.mentions("lavori dal 3 al 5 ottobre 2026")
        self.assertIn(("3 ottobre", "2026-10-03"), found)
        self.assertIn(("5 ottobre 2026", "2026-10-05"), found)

    def test_measures_are_not_dates(self):
        self.assertEqual(self.mentions("raccordo 3/4 pollice, sconto il 3.5 per cento, il 15 pezzi"), [])


class DateAssignmentTests(unittest.TestCase):
    SCHEMA = {"type": "object", "properties": {
        "data_riunione": {"type": "string"},
        "data_prossimo_incontro": {"type": "string"},
        "argomenti": {"type": "string"},
    }}
    TEXT = "Riunione del 2 ottobre con Rossi e Bianchi: approvato il budget. Prossimo incontro il 15."

    def run_guard(self, data, schema=None, text=None):
        from docx_ai.llm.fact_guard import verify
        return verify(data, schema or self.SCHEMA, [text or self.TEXT], today=TODAY)

    def test_empty_date_fields_filled_from_context(self):
        out, fixes = self.run_guard({"data_riunione": "NON_SPECIFICATO", "data_prossimo_incontro": "NON_SPECIFICATO",
                                     "argomenti": "budget"})
        self.assertEqual(out["data_riunione"], "2026-10-02")
        self.assertEqual(out["data_prossimo_incontro"], "2026-10-15")
        self.assertEqual(len(fixes), 2)

    def test_date_of_another_field_is_moved(self):
        # il modello piccolo mette la data del prossimo incontro nella data della riunione
        out, fixes = self.run_guard({"data_riunione": "2026-10-15", "data_prossimo_incontro": "2026-10-15"})
        self.assertEqual(out["data_riunione"], "2026-10-02")
        self.assertEqual(out["data_prossimo_incontro"], "2026-10-15")

    def test_date_written_in_words_converted(self):
        schema = {"type": "object", "properties": {"data": {"type": "string"}}}
        out, _ = self.run_guard({"data": "ieri"}, schema, "intervento eseguito ieri sulla pompa")
        self.assertEqual(out["data"], "2026-10-05")

    def test_single_date_single_field(self):
        schema = {"type": "object", "properties": {"data": {"type": "string"}, "note": {"type": "string"}}}
        out, _ = self.run_guard({"data": "NON_SPECIFICATO", "note": "x"}, schema,
                                "Lunedì scorso sostituito il cuscinetto della pompa P12")
        self.assertEqual(out["data"], "2026-10-05")

    def test_invented_date_removed_when_no_context(self):
        schema = {"type": "object", "properties": {"data": {"type": "string"}}}
        out, fixes = self.run_guard({"data": "2026-10-06"}, schema, "sostituito il cuscinetto della pompa")
        self.assertEqual(out["data"], "NON_SPECIFICATO")
        self.assertEqual(len(fixes), 1)


class EvidenceTests(unittest.TestCase):
    SCHEMA = {"type": "object", "properties": {
        "fermo_impianto": {"type": "boolean"},
        "prova_superata": {"type": "boolean"},
        "pulizia_si": {"type": "boolean"},
        "pulizia_no": {"type": "boolean"},
        "esito": {"type": "string", "enum": ["conforme", "non_conforme"]},
        "tecnico": {"type": "string"},
        "descrizione": {"type": "string"},
        "materiali": {"type": "array", "items": {"type": "string"}},
    }}
    TEXT = ("Pompa P12 rumorosa, sostituito il cuscinetto 6204 e la guarnizione. Nessun fermo macchina. "
            "Prova finale superata, nessun problema.")

    def apply(self, data, proofs):
        from docx_ai.llm.evidence import apply
        return apply(data, proofs, self.SCHEMA, [self.TEXT])

    def test_deductions_without_evidence_removed(self):
        out, fixes = self.apply({"pulizia_si": True, "esito": "conforme", "tecnico": "Mario Rossi"},
                                {"pulizia_si": "", "esito": "", "tecnico": ""})
        self.assertFalse(out["pulizia_si"])
        self.assertEqual(out["esito"], "NON_SPECIFICATO")
        self.assertEqual(out["tecnico"], "NON_SPECIFICATO")
        self.assertEqual(len(fixes), 3)

    def test_invented_quote_does_not_count(self):
        out, _ = self.apply({"pulizia_si": True}, {"pulizia_si": "eseguita la pulizia e sanificazione"})
        self.assertFalse(out["pulizia_si"])

    def test_negated_evidence(self):
        out, fixes = self.apply({"fermo_impianto": True, "prova_superata": True},
                                {"fermo_impianto": "Nessun fermo macchina", "prova_superata": "Prova finale superata"})
        self.assertFalse(out["fermo_impianto"])  # "nessun fermo" esclude il fermo
        self.assertTrue(out["prova_superata"])
        self.assertEqual(len(fixes), 1)

    def test_double_negative_kept(self):
        out, _ = self.apply({"prova_superata": True}, {"prova_superata": "nessun problema"})
        self.assertTrue(out["prova_superata"])

    def test_both_yes_and_no(self):
        out, fixes = self.apply({"pulizia_si": True, "pulizia_no": True}, {"pulizia_si": None, "pulizia_no": None})
        self.assertFalse(out["pulizia_si"])
        self.assertFalse(out["pulizia_no"])
        self.assertEqual(len(fixes), 2)

    def test_grounded_values_kept(self):
        data = {"descrizione": "Pompa P12 rumorosa: sostituiti cuscinetto 6204 e guarnizione.",
                "materiali": ["cuscinetto 6204", "guarnizione"], "esito": "conforme"}
        out, fixes = self.apply(data, {"descrizione": "", "materiali": "", "esito": "Prova finale superata"})
        self.assertEqual(out, data)
        self.assertEqual(fixes, [])

    def test_invented_list_items_removed(self):
        out, _ = self.apply({"materiali": ["cuscinetto 6204", "olio idraulico"]}, {"materiali": ""})
        self.assertEqual(out["materiali"], ["cuscinetto 6204"])

    def test_flat_answers_untouched(self):
        # backend senza grammatica (risposta senza prove): nessuna regola applicata
        out, fixes = self.apply({"pulizia_si": True}, {"pulizia_si": None})
        self.assertTrue(out["pulizia_si"])
        self.assertEqual(fixes, [])

    def test_wrap_unwrap(self):
        from docx_ai.llm.evidence import unwrap, wrap_schema
        wrapped = wrap_schema({"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "boolean"}},
                               "required": ["a"]})
        self.assertEqual(wrapped["required"], ["a", "b"])  # tutti obbligatori: nessun campo saltato
        self.assertEqual(list(wrapped["properties"]["a"]["properties"]), ["evidenza", "valore"])
        values, proofs = unwrap({"a": {"evidenza": "x", "valore": "y"}, "b": {}, "z": 1},
                                {"a": {"type": "string"}, "b": {"type": "boolean"}})
        self.assertEqual(values, {"a": "y"})
        self.assertEqual(proofs, {"a": "x"})


class PipelineEvidenceTests(unittest.TestCase):
    def test_end_to_end(self):
        from docx_ai.llm.json_pipeline import JsonPipeline
        from docx_ai.llm.llama_server import MockLlamaServer
        schema = {"type": "object", "additionalProperties": False, "properties": {
            "data": {"type": "string"}, "tecnico": {"type": "string"}, "pulizia_eseguita": {"type": "boolean"},
            "esito": {"type": "string", "enum": ["conforme", "non_conforme"]}},
            "required": ["data", "tecnico", "pulizia_eseguita", "esito"]}
        prompts = []

        def answer(messages, json_schema=None):
            prompts.append(messages)
            return {"data": {"evidenza": "", "valore": "NON_SPECIFICATO"},
                    "tecnico": {"evidenza": "il tecnico Rossi", "valore": "Rossi"},
                    "pulizia_eseguita": {"evidenza": "", "valore": True},
                    "esito": {"evidenza": "verifica conforme", "valore": "conforme"}}
        text = "Ieri il tecnico Rossi ha sostituito la cinghia, verifica conforme."
        res = JsonPipeline(MockLlamaServer(answer), max_retries=0).extract(schema, text)
        self.assertTrue(res.success, res.error_message)
        self.assertEqual(res.data["tecnico"], "Rossi")
        self.assertFalse(res.data["pulizia_eseguita"])  # deduzione senza prova
        self.assertEqual(res.data["esito"], "conforme")
        self.assertRegex(res.data["data"], r"^\d{4}-\d{2}-\d{2}$")  # "ieri" assegnato al solo campo data
        self.assertEqual(res.evidence["tecnico"], "il tecnico Rossi")
        user = prompts[0][1]["content"]
        self.assertIn("DATE NEL TESTO", user)
        self.assertIn("«Ieri»", user)
        self.assertIn("data = Data (data, scrivi AAAA-MM-GG)", user)
        self.assertIn("evidenza", prompts[0][0]["content"])

    def test_small_models_use_smaller_groups(self):
        from docx_ai.llm.json_pipeline import is_small_model
        from docx_ai.llm.llama_server import LlamaServer, LlamaServerOptions
        small = LlamaServer(LlamaServerOptions(runtime_dir=Path("."), model_path=Path("m/Qwen3-1.7B-Q4_K_M.gguf")))
        big = LlamaServer(LlamaServerOptions(runtime_dir=Path("."),
                                             model_path=Path("m/Qwen3-4B-Instruct-2507-Q4_K_M.gguf")))
        self.assertTrue(is_small_model(small))
        self.assertFalse(is_small_model(big))


if __name__ == "__main__":
    unittest.main()


class ImproveTextTests(unittest.TestCase):
    def service(self, answers):
        import json as _json
        from docx_ai.docintelligence.ai_service import AIService

        class Pipe:
            def __init__(self):
                self.calls = []

            def chat(self, messages, **kw):
                self.calls.append((messages, kw))
                out = answers[min(len(self.calls), len(answers)) - 1]
                return {"choices": [{"message": {"content": _json.dumps({"testo": out}, ensure_ascii=False)}}]}

        svc = AIService.__new__(AIService)
        svc._last_used = 0.0
        svc.backend_label = "llama:test"
        svc.pipe = Pipe()
        svc.pipeline = lambda **kw: svc.pipe
        return svc

    def test_clean_rewrite(self):
        svc = self.service(["Sostituito il cuscinetto 6204 della pompa P-12; prova superata."])
        out, warnings = svc.improve_text_checked("sostituito cuscinetto 6204 pompa P-12 prova ok", "Note")
        self.assertIn("6204", out)
        self.assertEqual(warnings, [])
        self.assertEqual(len(svc.pipe.calls), 1)
        self.assertEqual(svc.pipe.calls[0][1]["json_schema"]["required"], ["testo"])  # niente preamboli

    def test_added_or_lost_data_retried_and_reported(self):
        svc = self.service(["Sostituito il cuscinetto 6205 della pompa.", "Sostituito il cuscinetto della pompa."])
        out, warnings = svc.improve_text_checked("sostituito cuscinetto 6204 pompa P-12", "Note")
        self.assertEqual(len(svc.pipe.calls), 2)  # secondo tentativo con la correzione
        self.assertTrue(any("6204" in w for w in warnings))

    def test_empty_field_written_from_sources(self):
        svc = self.service(["Rumore anomalo dalla pompa P-12."])
        out, warnings = svc.improve_text_checked("", "Descrizione anomalia",
                                                 sources=["Pompa P-12 rumorosa, sostituito cuscinetto"])
        self.assertEqual(out, "Rumore anomalo dalla pompa P-12.")
        self.assertIn("Testo dell'utente", svc.pipe.calls[0][0][1]["content"])

    def test_empty_field_without_sources(self):
        svc = self.service(["x"])
        with self.assertRaises(ValueError):
            svc.improve_text_checked("", "Note")


class DocumentDateFormatTests(unittest.TestCase):
    def test_iso_dates_written_italian_style(self):
        from docx_ai.services.report_service import _for_document
        out = _for_document({"data": "2026-10-05", "note": "rif. 2026-10-05 ok", "x": "NON_SPECIFICATO"})
        self.assertEqual(out, {"data": "05/10/2026", "note": "rif. 2026-10-05 ok", "x": ""})
