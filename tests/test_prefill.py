"""Campi compilati dal programma senza AI (llm/prefill.py) e campi automatici del modulo."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from docx_ai.llm import prefill  # noqa: E402

TODAY = date(2026, 10, 15)  # giovedi'

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "numero_rapporto": {"type": "string"},
        "tipologia_intervento": {"type": "string", "enum": [
            "manutenzione_ordinaria_programmata", "manutenzione_straordinaria", "non_specificato"]},
        "reparto": {"type": "string"},
        "data": {"type": "string"},
        "descrizione_anomalia": {"type": "string"},
        "pezzi_sostituiti": {"type": "array", "items": {"type": "string"}},
        "firma_operatore_manutenzione": {"type": "string"},
        "esito_verifica": {"type": "string", "enum": ["conforme", "non_conforme", "non_specificato"]},
        "firma_verifica": {"type": "string"},
    },
}
SCHEMA["required"] = list(SCHEMA["properties"])


def values(schema, text):
    return {k: v.value for k, v in prefill.from_text(schema, text, TODAY).items()}


class LabelValueTests(unittest.TestCase):
    def test_labelled_list(self):
        text = ("RAPPORTO 77. Data: 01/10/2026. Reparto: Cottura - Linea 1. Forno FT-2 guasto. "
                "Tipo: straordinaria. Pezzi cambiati: elettrodo EA-55. Operatore: Giorgio Mauri; "
                "verifica: Ing. Rossi")
        got = values(SCHEMA, text)
        self.assertEqual(got["reparto"], "Cottura - Linea 1")
        self.assertEqual(got["tipologia_intervento"], "manutenzione_straordinaria")
        self.assertEqual(got["firma_operatore_manutenzione"], "Giorgio Mauri")
        self.assertEqual(got["data"], "2026-10-01")
        self.assertNotIn("pezzi_sostituiti", got)  # gli elenchi restano all'AI
        # "verifica" puo' essere esito_verifica o firma_verifica: decide l'AI
        self.assertNotIn("firma_verifica", got)
        self.assertNotIn("esito_verifica", got)

    def test_title_abbreviation_does_not_cut_the_value(self):
        got = values(SCHEMA, "Firma verifica: Ing. Paolo Riva. Esito verifica: non conforme")
        self.assertEqual(got["firma_verifica"], "Ing. Paolo Riva")
        self.assertEqual(got["esito_verifica"], "non_conforme")

    def test_several_labels_on_one_line(self):
        got = values(SCHEMA, "Reparto: Affettati, N. rapporto: 245/26")
        self.assertEqual(got["reparto"], "Affettati")
        self.assertEqual(got["numero_rapporto"], "245/26")

    def test_form_written_with_labels(self):
        schema = {"type": "object", "properties": {
            "dipendente": {"type": "string"}, "dal": {"type": "string"}, "al": {"type": "string"},
            "giorni": {"type": "number"}, "approvato_responsabile": {"type": "boolean"}}}
        got = values(schema, "Dipendente: Chiara Moretti\nDal: 09/11/2026\nAl: 13/11/2026\nGiorni: 5\n"
                             "Approvato responsabile: no")
        self.assertEqual(got, {"dipendente": "Chiara Moretti", "dal": "2026-11-09", "al": "2026-11-13",
                               "giorni": 5, "approvato_responsabile": False})
        self.assertIsInstance(got["giorni"], int)

    def test_prose_and_times_are_not_labels(self):
        got = values(SCHEMA, "Ecco cosa e' successo: alle 14:30 il reparto si e' fermato")
        self.assertEqual(got, {})

    def test_same_field_twice_is_left_to_the_ai(self):
        got = values(SCHEMA, "Reparto: Cottura\nReparto: Affettati")
        self.assertNotIn("reparto", got)

    def test_values_that_do_not_fit_the_type(self):
        schema = {"type": "object", "properties": {
            "ore_lavoro": {"type": "number"}, "pulizia_eseguita": {"type": "boolean"},
            "urgenza": {"type": "string", "enum": ["bassa", "media", "alta"]},
            "ora_inizio": {"type": "string"}, "cliente": {"type": "string"}}}
        got = values(schema, "Ore lavoro: 3,5 ore\nPulizia eseguita: sì\nUrgenza: altissima\n"
                             "Ora inizio: 8.30\nCliente: -")
        self.assertEqual(got["ore_lavoro"], 3.5)
        self.assertIs(got["pulizia_eseguita"], True)
        self.assertEqual(got["ora_inizio"], "08:30")
        self.assertNotIn("urgenza", got)  # nessuna opzione corrisponde
        self.assertNotIn("cliente", got)  # "-" = non indicato
        got = values(schema, "Ore lavoro: tre o quattro\nPulizia eseguita: forse")
        self.assertEqual(got, {})


class DatesAndContactsTests(unittest.TestCase):
    def test_dates_in_speech_stay_with_the_ai(self):
        # senza il campo data da scrivere il modello piccolo la metteva in un altro campo
        self.assertEqual(values(SCHEMA, "Lunedì scorso nel reparto Affettati la lama vibrava"), {})

    def test_contacts(self):
        schema = {"type": "object", "properties": {
            "email": {"type": "string"}, "telefono": {"type": "string"}, "partita_iva": {"type": "string"}}}
        got = values(schema, "Scrivere a mario.rossi@ditta.it o chiamare il 333 1234567. P.IVA 01234567890")
        self.assertEqual(got["email"], "mario.rossi@ditta.it")
        self.assertEqual(got["telefono"], "333 1234567")
        self.assertEqual(got["partita_iva"], "01234567890")
        got = values(schema, "Tel 333 1234567 oppure 0371 456789")
        self.assertNotIn("telefono", got)  # due numeri: quale? decide l'AI


class AutoFieldTests(unittest.TestCase):
    SCHEMA = {"type": "object", "properties": {
        "data": {"type": "string", "format": "date", "x-auto": "today"},
        "azienda": {"type": "string", "x-auto": "fixed", "default": "Rossi Srl"},
        "reparto": {"type": "string", "x-auto": "last"},
        "ore": {"type": "number", "x-auto": "fixed", "default": "abc"},
        "note": {"type": "string"}}}

    def test_modes(self):
        got = prefill.auto_values(self.SCHEMA, {"reparto": "Cottura"}, TODAY)
        self.assertEqual({k: v.value for k, v in got.items()},
                         {"data": "2026-10-15", "azienda": "Rossi Srl", "reparto": "Cottura"})
        # senza documenti approvati (o con il valore vuoto) "ultimo valore" resta all'AI
        self.assertNotIn("reparto", prefill.auto_values(self.SCHEMA, None, TODAY))
        self.assertNotIn("reparto", prefill.auto_values(self.SCHEMA, {"reparto": "NON_SPECIFICATO"}, TODAY))

    def test_editor_settings(self):
        from docx_ai import template_tools as tt
        spec = tt.with_auto({"type": "number"}, "ore", "fixed", "2,5")
        self.assertEqual(spec, {"type": "number", "x-auto": "fixed", "default": 2.5})
        self.assertEqual(tt.auto_of(spec), ("fixed", "2.5"))
        with self.assertRaises(ValueError):
            tt.with_auto({"type": "boolean"}, "ok", "fixed", "forse")
        self.assertEqual(tt.with_auto({"type": "boolean"}, "ok", "fixed", "sì")["default"], True)
        # "Lo compila l'AI" toglie le impostazioni; "Data di oggi" solo per le date
        self.assertEqual(tt.with_auto(spec, "ore", ""), {"type": "number"})
        self.assertEqual(tt.with_auto({"type": "string"}, "nome", "today"), {"type": "string"})
        self.assertIn("today", tt.auto_modes("date"))
        self.assertNotIn("fixed", tt.auto_modes("list"))

    def test_grammar_ignores_auto_settings(self):
        from docx_ai.llm.json_pipeline import llm_schema
        spec = llm_schema(self.SCHEMA)["properties"]["azienda"]
        self.assertEqual(spec, {"type": "string"})


class PipelineTests(unittest.TestCase):
    def _pipe(self, answer):
        from docx_ai.llm.json_pipeline import JsonPipeline
        from docx_ai.llm.llama_server import MockLlamaServer
        calls = []

        def fn(messages, json_schema=None):
            calls.append(json_schema)
            return answer(json_schema)
        return JsonPipeline(MockLlamaServer(fn), max_retries=0), calls

    def test_known_fields_are_not_asked(self):
        def answer(js):
            return {k: {"evidenza": "", "valore": "NON_SPECIFICATO"} if k != "descrizione_anomalia"
                    else {"evidenza": "lama vibrava", "valore": "La lama vibrava"}
                    for k in js["properties"]}
        pipe, calls = self._pipe(answer)
        res = pipe.extract(SCHEMA, "Reparto: Affettati. Esito verifica: conforme. La lama vibrava.")
        self.assertTrue(res.success, res.error_message)
        asked = set().union(*(set(c["properties"]) for c in calls))
        self.assertNotIn("reparto", asked)
        self.assertNotIn("esito_verifica", asked)
        self.assertIn("descrizione_anomalia", asked)
        # le scelte senza prova dell'AI vengono tolte, quelle del programma restano
        self.assertEqual(res.data["esito_verifica"], "conforme")
        self.assertEqual(res.data["reparto"], "Affettati")
        self.assertEqual(res.evidence["reparto"], "Reparto: Affettati")
        self.assertFalse(any("Reparto" in c for c in res.corrections or []))

    def test_known_date_is_not_repeated_in_another_field(self):
        schema = {"type": "object", "additionalProperties": False, "properties": {
            "data_rilevazione": {"type": "string", "x-auto": "today"}, "rilevata_da": {"type": "string"},
            "difetto": {"type": "string"}}, "required": ["data_rilevazione", "rilevata_da", "difetto"]}
        today = date.today().isoformat()

        def fn(messages, json_schema=None):
            return {"rilevata_da": {"evidenza": "oggi", "valore": today},
                    "difetto": {"evidenza": "bordo deformato", "valore": "Bordo deformato"}}
        from docx_ai.llm.json_pipeline import JsonPipeline
        from docx_ai.llm.llama_server import MockLlamaServer
        res = JsonPipeline(MockLlamaServer(fn), max_retries=0).extract(
            schema, "NC aperta oggi: 120 vaschette con il bordo deformato",
            known=prefill.auto_values(schema))
        self.assertEqual(res.data["rilevata_da"], "NON_SPECIFICATO")
        self.assertEqual(res.data["data_rilevazione"], today)
        self.assertEqual(res.data["difetto"], "Bordo deformato")

    def test_same_date_in_two_date_fields_is_kept(self):
        schema = {"type": "object", "additionalProperties": False, "properties": {
            "data": {"type": "string"}, "data_intervento": {"type": "string"}, "note": {"type": "string"}},
            "required": ["data", "data_intervento", "note"]}

        from docx_ai.llm.fact_guard import date_mentions
        monday = date_mentions("Lunedì scorso")[0][1].isoformat()

        def fn(messages, json_schema=None):
            return {k: {"evidenza": "Lunedì scorso", "valore": monday} if k == "data_intervento"
                    else {"evidenza": "", "valore": "NON_SPECIFICATO"} for k in json_schema["properties"]}
        from docx_ai.llm.json_pipeline import JsonPipeline
        from docx_ai.llm.llama_server import MockLlamaServer
        res = JsonPipeline(MockLlamaServer(fn), max_retries=0).extract(
            schema, "Lunedì scorso la lama vibrava, sostituita.")
        self.assertEqual(res.data["data"], monday)  # compilata dal programma
        self.assertEqual(res.data["data_intervento"], monday)  # stessa data, campo data: resta

    def test_everything_known_skips_the_ai(self):
        from docx_ai.llm.json_pipeline import NO_AI_BACKEND
        schema = {"type": "object", "additionalProperties": False, "properties": {
            "reparto": {"type": "string"}, "data": {"type": "string", "x-auto": "today"},
            "esito": {"type": "string", "enum": ["conforme", "non_conforme"]}},
            "required": ["reparto", "data", "esito"]}
        pipe, calls = self._pipe(lambda js: {})
        res = pipe.extract(schema, "Reparto: Cottura\nEsito: conforme",
                           known=prefill.auto_values(schema, None, TODAY))
        self.assertTrue(res.success)
        self.assertEqual(calls, [])
        self.assertEqual(res.failover_used, NO_AI_BACKEND)
        self.assertEqual(res.data, {"reparto": "Cottura", "data": "2026-10-15", "esito": "conforme"})


if __name__ == "__main__":
    unittest.main()
