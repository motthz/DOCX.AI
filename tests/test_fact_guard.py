"""Test del controllo deterministico dei fatti (date, numeri, codici, nomi)."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

TODAY = date(2026, 10, 6)  # martedì

SCHEMA = {
    "type": "object",
    "properties": {
        "data_riunione": {"type": "string", "format": "date"},
        "prossimo_incontro": {"type": "string", "format": "date"},
        "importo": {"type": ["number", "null"]},
        "ore": {"type": ["number", "null"]},
        "matricola": {"type": "string"},
        "redattore": {"type": "string"},
        "partecipanti": {"type": "array", "items": {"type": "string"}},
        "esito": {"type": "string", "enum": ["Regolare", "Anomalia"]},
        "note": {"type": "string"},
        "azioni": {"type": "array", "items": {"type": "object", "properties": {
            "attivita": {"type": "string"}, "scadenza": {"type": "string", "format": "date"}}}},
    },
}


def run(data, text):
    from docx_ai.llm.fact_guard import verify
    return verify(data, SCHEMA, [text], today=TODAY)


class DateTests(unittest.TestCase):
    def test_explicit_formats(self):
        for text in ("riunione del 05/10/2026", "riunione del 5.10.26", "riunione del 5 ottobre 2026",
                     "riunione del 5 ottobre", "riunione del 5 ott", "riunione 2026-10-05", "lunedì 5/10"):
            out, fixes = run({"data_riunione": "2026-10-05"}, text)
            self.assertEqual(out["data_riunione"], "2026-10-05", text)
            self.assertEqual(fixes, [], text)

    def test_relative_dates(self):
        cases = {"ieri": "2026-10-05", "oggi": "2026-10-06", "l'altro ieri": "2026-10-04",
                 "domani": "2026-10-07", "lunedì scorso": "2026-10-05", "venerdì prossimo": "2026-10-09",
                 "tra due settimane": "2026-10-20", "3 giorni fa": "2026-10-03", "giovedì": "2026-10-08"}
        for text, expected in cases.items():
            out, fixes = run({"data_riunione": expected}, f"riunione {text} in sala A")
            self.assertEqual(fixes, [], text)

    def test_invented_date_removed(self):
        out, fixes = run({"data_riunione": "2025-03-14"}, "riunione con il cliente, nessuna data")
        self.assertEqual(out["data_riunione"], "NON_SPECIFICATO")
        self.assertEqual(len(fixes), 1)

    def test_swapped_day_month_fixed(self):
        out, fixes = run({"data_riunione": "2026-10-05"}, "intervento del 10/05/2026")
        self.assertEqual(out["data_riunione"], "2026-05-10")
        self.assertIn("scambiati", fixes[0].reason)

    def test_wrong_year_fixed(self):
        out, _ = run({"data_riunione": "2024-10-05"}, "intervento del 5 ottobre 2026")
        self.assertEqual(out["data_riunione"], "2026-10-05")

    def test_nested_and_format_kept(self):
        out, fixes = run({"azioni": [{"attivita": "preventivo", "scadenza": "30/10/2026"},
                                     {"attivita": "ordine", "scadenza": "2026-12-01"}]},
                         "preventivo entro il 30 ottobre, poi l'ordine")
        self.assertEqual(out["azioni"][0]["scadenza"], "30/10/2026")
        self.assertEqual(out["azioni"][1]["scadenza"], "NON_SPECIFICATO")
        self.assertEqual(len(fixes), 1)


class NumberTests(unittest.TestCase):
    def test_numbers_found_in_any_format(self):
        for text, val in (("importo 1.250,50 euro", 1250.5), ("costo 1250.50", 1250.5),
                          ("due ore di lavoro", 2), ("4 ore", 4), ("1.200 euro", 1200)):
            out, fixes = run({"importo": val}, text)
            self.assertEqual(fixes, [], text)

    def test_invented_number_removed(self):
        out, fixes = run({"importo": 0, "ore": 3.5}, "sostituito il filtro, 2 ore")
        self.assertIsNone(out["importo"])
        self.assertIsNone(out["ore"])
        self.assertEqual(len(fixes), 2)


class CodeAndNameTests(unittest.TestCase):
    def test_codes(self):
        out, _ = run({"matricola": "SN-4471"}, "pompa matricola sn 4471")
        self.assertEqual(out["matricola"], "SN-4471")
        out, fixes = run({"matricola": "AB123"}, "pompa senza targhetta")
        self.assertEqual(out["matricola"], "NON_SPECIFICATO")

    def test_names(self):
        text = "presenti Rossi e la dott.ssa Bianchi, verbale di Verdi"
        out, fixes = run({"redattore": "Mario Verdi", "partecipanti": ["Luca Rossi", "Bianchi", "Giorgio Neri"]},
                         text)
        self.assertEqual(out["redattore"], "Mario Verdi")
        self.assertEqual(out["partecipanti"], ["Luca Rossi", "Bianchi"])  # Neri inventato: tolto
        self.assertEqual(len(fixes), 1)

    def test_text_and_enums_untouched(self):
        data = {"esito": "Regolare", "note": "Intervento concluso senza anomalie, impianto ripristinato."}
        out, fixes = run(data, "tutto ok, impianto ripartito")
        self.assertEqual(out, data)
        self.assertEqual(fixes, [])


class PipelineIntegrationTests(unittest.TestCase):
    def test_pipeline_removes_invented_values(self):
        from docx_ai.llm.json_pipeline import JsonPipeline
        from docx_ai.llm.llama_server import MockLlamaServer
        schema = {"type": "object", "additionalProperties": False,
                  "properties": {"data": {"type": "string", "format": "date"}, "ore": {"type": "number"}},
                  "required": ["data", "ore"]}
        srv = MockLlamaServer(lambda m, json_schema=None: {"data": "2023-01-01", "ore": 8})
        res = JsonPipeline(srv, max_retries=0).extract(schema, "intervento di 3 ore")
        self.assertTrue(res.success)
        self.assertEqual(res.data, {"data": "NON_SPECIFICATO", "ore": None})
        self.assertEqual(len(res.corrections), 2)


if __name__ == "__main__":
    unittest.main()
