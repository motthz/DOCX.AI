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
        self.assertGreaterEqual(len(svc.pipe.calls), 2)  # nuovo tentativo con la correzione
        self.assertTrue(any("6204" in w for w in warnings))

    def test_empty_field_written_from_sources(self):
        svc = self.service(["Rumore anomalo dalla pompa P-12."])
        out, warnings = svc.improve_text_checked("", "Descrizione anomalia",
                                                 sources=["Pompa P-12 rumorosa, sostituito cuscinetto"])
        self.assertEqual(out, "Rumore anomalo dalla pompa P-12.")
        self.assertIn("Informazioni:", svc.pipe.calls[0][0][1]["content"])

    def test_empty_field_without_sources(self):
        svc = self.service(["x"])
        with self.assertRaises(ValueError):
            svc.improve_text_checked("", "Note")


class ImproveTextCopyTests(unittest.TestCase):
    def test_copied_text_is_retried(self):
        svc = ImproveTextTests.service(None, ["sostituito cuscinetto 6204 pompa P-12, prova ok",
                                              "È stato sostituito il cuscinetto 6204 della pompa P-12; prova con "
                                              "esito positivo."])
        out, warnings = svc.improve_text_checked("sostituito cuscinetto 6204 pompa P-12 , prova ok", "Note")
        self.assertTrue(out.startswith("È stato sostituito"))
        self.assertEqual(warnings, [])

    def test_lost_content_reported(self):
        from docx_ai.docintelligence.ai_service import _lost_words
        orig = "la macchina perdeva olio dal raccordo, cambiato guarnizione e serrato i bulloni del carter"
        self.assertIn("perdeva", _lost_words(orig, "È stato sostituito il raccordo di olio del carter, con la "
                                                   "guarnizione e serrati i bulloni del carter."))
        self.assertEqual(_lost_words("sostituito cuscinetto 6204 pompa P-12 era rumorosa, prova ok",
                                     "È stato sostituito il cuscinetto 6204 della pompa P-12, che era rumorosa. "
                                     "La prova ha dato esito positivo."), [])


class InventedCauseTests(unittest.TestCase):
    def test_invented_cause_retried(self):
        svc = ImproveTextTests.service(None, ["La pompa P12 era rumorosa a causa della rottura del cuscinetto.",
                                              "La pompa P12 era rumorosa."])
        out, warnings = svc.improve_text_checked("", "Descrizione anomalia",
                                                 sources=["pompa P12 rumorosa, cambiato cuscinetto 6204"])
        self.assertEqual(out, "La pompa P12 era rumorosa.")
        self.assertEqual(warnings, [])


class StripCauseTests(unittest.TestCase):
    def test_persistent_cause_removed(self):
        svc = ImproveTextTests.service(None, ["La pompa P12 era rumorosa a causa della rottura del cuscinetto 6204. "
                                              "Il cuscinetto 6204 è stato sostituito."])
        out, warnings = svc.improve_text_checked("", "Descrizione anomalia",
                                                 sources=["pompa P12 rumorosa, cambiato cuscinetto 6204"])
        self.assertEqual(out, "La pompa P12 era rumorosa. Il cuscinetto 6204 è stato sostituito.")
        self.assertTrue(any("Tolta una causa" in w for w in warnings))


class DocumentDateFormatTests(unittest.TestCase):
    def test_iso_dates_written_italian_style(self):
        from docx_ai.services.report_service import _for_document
        out = _for_document({"data": "2026-10-05", "note": "rif. 2026-10-05 ok", "x": "NON_SPECIFICATO"})
        self.assertEqual(out, {"data": "05/10/2026", "note": "rif. 2026-10-05 ok", "x": ""})


class ConsistencyRuleTests(unittest.TestCase):
    """Errori tipici del modello 1.7B visti sul banco di prova (scripts/eval_ai.py)."""

    def apply(self, data, proofs, schema, text):
        from docx_ai.llm.evidence import apply
        return apply(data, proofs, schema, [text])

    def test_machine_code_is_not_report_number_department_or_line(self):
        schema = {"type": "object", "properties": {k: {"type": "string"} for k in
                                                   ("numero_rapporto", "reparto", "linea", "apparecchiatura")}}
        data = {"numero_rapporto": "P12", "reparto": "P12", "linea": "P12", "apparecchiatura": "P12"}
        out, _ = self.apply(data, dict.fromkeys(data, "pompa P12"), schema,
                            "pompa P12 rumorosa, cambiato cuscinetto 6204, prova ok")
        self.assertEqual(out, {"numero_rapporto": "NON_SPECIFICATO", "reparto": "NON_SPECIFICATO",
                               "linea": "NON_SPECIFICATO", "apparecchiatura": "P12"})

    def test_report_number_kept_when_introduced(self):
        schema = {"type": "object", "properties": {"numero_rapporto": {"type": "string"}}}
        out, fixes = self.apply({"numero_rapporto": "245/26"}, {"numero_rapporto": "Rapporto n. 245/26"},
                                schema, "Rapporto n. 245/26. Sostituita la cinghia.")
        self.assertEqual(out["numero_rapporto"], "245/26")
        self.assertEqual(fixes, [])

    def test_technician_not_copied_into_other_signatures(self):
        schema = {"type": "object", "properties": {k: {"type": "string"} for k in
                                                   ("firma_operatore_manutenzione", "firma_esecutore_pulizia",
                                                    "firma_verifica")}}
        text = "Esito della verifica non conforme: il sensore va ricontrollato domani. Tecnico: Luca Ferri."
        out, _ = self.apply(dict.fromkeys(schema["properties"], "Luca Ferri"),
                            dict.fromkeys(schema["properties"], "Tecnico: Luca Ferri"), schema, text)
        self.assertEqual(out["firma_operatore_manutenzione"], "Luca Ferri")
        self.assertEqual(out["firma_esecutore_pulizia"], "NON_SPECIFICATO")
        self.assertEqual(out["firma_verifica"], "NON_SPECIFICATO")

    def test_field_name_is_not_a_value(self):
        schema = {"type": "object", "properties": {"oggetto": {"type": "string",
                                                               "description": "Titolo o oggetto della riunione"}}}
        out, _ = self.apply({"oggetto": "Oggetto della riunione"}, {"oggetto": ""}, schema,
                            "ieri ci siamo visti per parlare dei ritardi nelle consegne")
        self.assertEqual(out["oggetto"], "NON_SPECIFICATO")

    def test_choice_confirmed_by_words(self):
        schema = {"type": "object", "properties": {"tipologia": {"type": "string", "enum": [
            "manutenzione_ordinaria_programmata", "manutenzione_straordinaria"]}}}
        out, _ = self.apply({"tipologia": "manutenzione_ordinaria_programmata"},
                            {"tipologia": "manutenzione ordinaria programmata"}, schema,
                            "Oggi controllo programmato sulla confezionatrice CF-12")
        self.assertEqual(out["tipologia"], "manutenzione_ordinaria_programmata")

    def test_negated_yes_sets_no(self):
        schema = {"type": "object", "properties": {"pulizia_sanificazione_si": {"type": "boolean"},
                                                   "pulizia_sanificazione_no": {"type": "boolean"}}}
        out, _ = self.apply({"pulizia_sanificazione_si": False, "pulizia_sanificazione_no": False},
                            {"pulizia_sanificazione_si": "Non è stata necessaria pulizia né sanificazione",
                             "pulizia_sanificazione_no": ""}, schema,
                            "Non è stata necessaria pulizia né sanificazione.")
        self.assertTrue(out["pulizia_sanificazione_no"])
        self.assertFalse(out["pulizia_sanificazione_si"])

    def test_next_meeting_after_meeting(self):
        from docx_ai.llm.fact_guard import verify
        schema = {"type": "object", "properties": {"data_riunione": {"type": "string"},
                                                   "prossimo_incontro": {"type": "string", "format": "date"}}}
        out, _ = verify({"data_riunione": "2026-10-05", "prossimo_incontro": "2026-10-05"}, schema,
                        ["ieri pomeriggio riunione su Teams"], today=TODAY)
        self.assertEqual(out["prossimo_incontro"], "NON_SPECIFICATO")


class AntivirusFriendlyTests(unittest.TestCase):
    def test_powershell_without_suspicious_flags(self):
        from docx_ai import winshell
        args = winshell.powershell_args("Get-Date")
        joined = " ".join(args).lower()
        self.assertNotIn("-encodedcommand", joined)
        self.assertNotIn("bypass", joined)
        self.assertEqual(args[-2:], ["-Command", "Get-Date"])

    def test_no_suspicious_powershell_in_sources(self):
        src = REPO / "src" / "docx_ai"
        for path in src.rglob("*.py"):
            text = path.read_text(encoding="utf-8").lower()
            self.assertNotIn('"-encodedcommand"', text, path)
            self.assertNotIn('"bypass"', text, path)
            if path.name != "winshell.py":
                self.assertNotIn('["powershell"', text, path)


class HeldOutRuleTests(unittest.TestCase):
    """Casi del banco di prova non usati per scrivere le prime regole."""

    def apply(self, data, proofs, schema, text):
        from docx_ai.llm.evidence import apply
        return apply(data, proofs, schema, [text])

    TEXT = ("RAPPORTO 77. Data 01/10/2026. Reparto: Cottura - Linea 1. Pulizia non necessaria. Esito conforme. "
            "Operatore: Giorgio Mauri; verifica: Ing. Laura Sala.")
    SCHEMA = {"type": "object", "properties": {
        "numero_rapporto": {"type": "string"}, "pulizia_sanificazione_si": {"type": "boolean"},
        "pulizia_sanificazione_no": {"type": "boolean"}, "firma_operatore_manutenzione": {"type": "string"},
        "firma_esecutore_pulizia": {"type": "string"}, "firma_verifica": {"type": "string"}}}

    def test_report_number_with_label_word(self):
        out, _ = self.apply({"numero_rapporto": "RAPPORTO 77"}, {"numero_rapporto": "RAPPORTO 77"},
                            self.SCHEMA, self.TEXT)
        self.assertEqual(out["numero_rapporto"], "77")

    def test_negation_after_subject(self):
        out, fixes = self.apply({"pulizia_sanificazione_si": False, "pulizia_sanificazione_no": True},
                                {"pulizia_sanificazione_si": "", "pulizia_sanificazione_no": ""},
                                self.SCHEMA, self.TEXT)
        self.assertTrue(out["pulizia_sanificazione_no"])
        self.assertFalse(any(f.old is True for f in fixes))

    def test_name_of_another_role(self):
        out, _ = self.apply({"firma_operatore_manutenzione": "Giorgio Mauri",
                             "firma_esecutore_pulizia": "Ing. Laura Sala", "firma_verifica": "Ing. Laura Sala"},
                            {"firma_operatore_manutenzione": "Operatore: Giorgio Mauri",
                             "firma_esecutore_pulizia": "verifica: Ing. Laura Sala",
                             "firma_verifica": "verifica: Ing. Laura Sala"}, self.SCHEMA, self.TEXT)
        self.assertEqual(out["firma_operatore_manutenzione"], "Giorgio Mauri")
        self.assertEqual(out["firma_esecutore_pulizia"], "NON_SPECIFICATO")
        self.assertEqual(out["firma_verifica"], "Ing. Laura Sala")

    def test_quantity_is_not_amount(self):
        schema = {"type": "object", "properties": {"importo_stimato": {"type": "string"},
                                                   "cauzione_euro": {"type": "number"}}}
        out, _ = self.apply({"importo_stimato": "10", "cauzione_euro": 20}, {"importo_stimato": "10 risme"}, schema,
                            "Servono 10 risme di carta A4. Cauzione 20 euro.")
        self.assertEqual(out["importo_stimato"], "NON_SPECIFICATO")
        self.assertEqual(out["cauzione_euro"], 20)

    def test_label_words_reordered(self):
        schema = {"type": "object", "properties": {"oggetto": {"type": "string",
                                                               "description": "Titolo o oggetto della riunione"}}}
        out, _ = self.apply({"oggetto": "Oggetto riunione"}, {"oggetto": ""}, schema, "riunione sui ritardi")
        self.assertEqual(out["oggetto"], "NON_SPECIFICATO")


class AbbreviationTests(unittest.TestCase):
    def test_abbreviated_label_keeps_code(self):
        from docx_ai.llm.evidence import apply
        schema = {"type": "object", "properties": {"matricola": {"type": "string"}, "reparto": {"type": "string"}}}
        out, fixes = apply({"matricola": "10457", "reparto": "magazzino"}, {"matricola": "matr. 10457"}, schema,
                           ["Chiara Moretti (matr. 10457) del magazzino chiede ferie"])
        self.assertEqual(out["matricola"], "10457")
        self.assertEqual(fixes, [])


class PlacementVerificationTests(unittest.TestCase):
    """Informazione vera ma nel campo sbagliato: tolta solo se il valore e' lontano dalle
    parole del campo E il modello, interrogato solo su quel campo, dice che non c'e'."""

    SCHEMA = {"type": "object", "properties": {
        "redattore": {"type": "string", "description": "Chi redige il verbale"},
        "luogo": {"type": "string"}, "oggetto": {"type": "string"}}}
    TEXT = "Riunione sicurezza del 28/09 in mensa con RSPP Bruno Sala e i capireparto."

    def run_with(self, answer):
        import json as _json
        from docx_ai.llm.json_pipeline import JsonPipeline
        asked = []

        class Fake:
            def chat_completions(self, messages, **kw):
                q = messages[-1]["content"]
                asked.append(q)
                reply = answer if "redige" in q else "mensa"
                return {"choices": [{"message": {"content": _json.dumps({"risposta": reply})}}]}
        pipe = JsonPipeline(Fake(), max_retries=0)
        data = {"redattore": "Bruno Sala", "luogo": "mensa", "oggetto": "sicurezza"}
        return pipe._verify_placement(Fake(), self.SCHEMA, data, self.TEXT, [self.TEXT]), asked

    def test_misplaced_value_removed(self):
        (out, fixes), asked = self.run_with("NON INDICATO")
        self.assertEqual(out["redattore"], "NON_SPECIFICATO")
        self.assertEqual(out["luogo"], "mensa")  # confermato dalla domanda separata
        self.assertEqual(out["oggetto"], "sicurezza")  # vicino alle parole del campo: non verificato
        self.assertTrue(any("Chi redige il verbale" in q for q in asked))
        self.assertFalse(any("Oggetto" in q for q in asked))
        self.assertEqual(len(fixes), 1)

    def test_confirmed_value_kept(self):
        (out, fixes), _ = self.run_with("Bruno Sala")
        self.assertEqual(out["redattore"], "Bruno Sala")
        self.assertEqual(fixes, [])
