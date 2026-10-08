"""Regressioni trovate nell'audit da utente della 0.9.1 con il modello piu' leggero
(Qwen3 0.6B): ogni test riproduce una risposta vera del modello o un difetto dell'app."""

from __future__ import annotations

import json
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from docx_ai.llm import evidence as ev  # noqa: E402
from docx_ai.llm import fact_guard as fg  # noqa: E402

VERBALE = ("Oggi 7 ottobre 2026 alle 14:30 ci siamo riuniti nella sala riunioni del secondo piano della sede di "
           "Monza per parlare del nuovo gestionale magazzino. Erano presenti Laura Bianchi (responsabile "
           "logistica), Paolo Verdi (IT), Giulia Neri (acquisti) e io, Marco Ferri, che ho scritto il verbale. "
           "Abbiamo discusso dei tempi di migrazione dei dati e del budget per la formazione. Si è deciso di "
           "avviare la migrazione il 3 novembre e di approvare un budget di 4.500 euro per la formazione. Paolo "
           "prepara il piano di migrazione entro il 20 ottobre, Giulia chiede tre preventivi ai fornitori di "
           "formazione entro fine mese. Ci rivediamo il 21 ottobre alle 10.")
FERIE = ("Sono Andrea Colombo, matricola 40217, lavoro nel reparto Spedizioni. Chiedo 5 giorni di ferie dal 16 al "
         "20 novembre 2026 per il matrimonio di mia sorella. Durante la mia assenza mi sostituisce Elena Ricci. "
         "Il mio responsabile è il dott. Fabio Gatti.")
PC_TODAY = date(2026, 10, 8)  # il testo e' stato scritto il giorno dopo la riunione


def _verbale_schema():
    return json.loads((ROOT / "examples" / "modules" / "Verbale_di_riunione" / "schema.json")
                      .read_text(encoding="utf-8"))


def _check(data, proofs, schema, text, document=""):
    out, fixes = ev.apply(data, proofs, schema, [text], document=document)
    out, more = fg.verify(out, schema, [text], today=PC_TODAY)
    return out, [f.describe() for f in fixes] + [c.describe() for c in more]


class StatedTodayTests(unittest.TestCase):
    def test_today_followed_by_date_is_that_date(self):
        self.assertEqual(fg.stated_today("Oggi 7 ottobre 2026 ci siamo riuniti", PC_TODAY), date(2026, 10, 7))
        self.assertEqual(fg.stated_today("oggi, lunedì 05/10/2026 ho", PC_TODAY), date(2026, 10, 5))
        self.assertEqual(fg.stated_today("Oggi è il 2026-10-03.", PC_TODAY), date(2026, 10, 3))
        self.assertEqual(fg.stated_today("oggi siamo andati", PC_TODAY), PC_TODAY)

    def test_relative_words_follow_stated_today(self):
        text = "Oggi 7 ottobre 2026 riunione. Ieri abbiamo preparato i documenti."
        dates = fg.source_dates(text, PC_TODAY)
        self.assertIn(date(2026, 10, 6), dates)  # "ieri" rispetto al 7, non all'8
        self.assertNotIn(PC_TODAY, dates)

    def test_prompt_uses_stated_today(self):
        from docx_ai.llm.prompt_builder import build_extraction_messages
        msgs = build_extraction_messages(_verbale_schema(), VERBALE, today=PC_TODAY)
        self.assertIn("DATA DI OGGI: 2026-10-07", msgs[0]["content"])

    def test_date_context_crosses_time_colon(self):
        m = next(x for x in fg.date_mentions_ctx(VERBALE, PC_TODAY) if x.words == "7 ottobre 2026")
        self.assertIn("riuniti", m.context)


class SmallModelAnswerTests(unittest.TestCase):
    """Risposte vere di Qwen3 0.6B sul verbale di riunione di esempio."""

    def test_meeting_date_and_subject(self):
        data = {"oggetto": "2026-10-08", "data_riunione": "2026-10-08", "prossimo_incontro": "2026-10-21"}
        proofs = {"oggetto": "Verbale di riunione", "data_riunione": "Oggi [7 ottobre 2026] alle 14",
                  "prossimo_incontro": "21 ottobre"}
        out, _ = _check(data, proofs, _verbale_schema(), VERBALE)
        self.assertEqual(out["data_riunione"], "2026-10-07")
        self.assertEqual(out["oggetto"], "NON_SPECIFICATO")
        self.assertEqual(out["prossimo_incontro"], "2026-10-21")

    def test_empty_value_with_quoted_sentence_is_filled(self):
        data = {"argomenti": "", "decisioni": ""}
        proofs = {"argomenti": "tempi di migrazione dei dati e del budget per la formazione",
                  # "e approvare" invece di "e di approvare": solo parole vuote diverse
                  "decisioni": "avviare la migrazione il 3 novembre e approvare un budget di 4.500 euro per la "
                               "formazione"}
        out, _ = _check(data, proofs, _verbale_schema(), VERBALE)
        self.assertEqual(out["argomenti"], "Tempi di migrazione dei dati e del budget per la formazione")
        self.assertTrue(out["decisioni"].startswith("Avviare la migrazione il 3 novembre"))

    def test_altered_quote_is_not_used(self):
        checker = ev.EvidenceChecker([VERBALE])
        self.assertFalse(checker._verbatim("si è deciso di non avviare la migrazione"))
        self.assertFalse(checker._verbatim("Paolo prepara il piano di migrazione entro il 30 ottobre"))
        self.assertTrue(checker._verbatim("Giulia chiede tre preventivi"))

    def test_field_name_answer_not_refilled_with_other_field_sentence(self):
        schema = {"type": "object", "properties": {"richiedente": {"type": "string"},
                                                   "motivazione": {"type": "string"}}}
        text = "Servono 10 risme di carta A4 per l'amministrazione. Lo chiede Paolo Gatti."
        out, _ = _check({"richiedente": "Paolo Gatti", "motivazione": "Motivazione"},
                        {"richiedente": "Paolo Gatti", "motivazione": "Lo chiede Paolo Gatti"}, schema, text)
        self.assertEqual(out["motivazione"], "NON_SPECIFICATO")

    def test_module_name_is_not_the_subject(self):
        doc = "Verbale di riunione · tipo: verbale di riunione · Verbale di una riunione: partecipanti, argomenti."
        out, _ = _check({"oggetto": "Verbale di riunione"}, {"oggetto": doc}, _verbale_schema(), VERBALE,
                        document=doc)
        self.assertEqual(out["oggetto"], "NON_SPECIFICATO")

    def test_leave_request(self):
        keys = ["nome_dipendente", "tipo_assenza", "data_inizio", "data_fine", "motivazione", "data_richiesta",
                "anomalie"]
        schema = {"type": "object", "properties": {k: {"type": "string"} for k in keys}}
        data = {"nome_dipendente": "Andrea Colombo", "tipo_assenza": "Sì", "data_inizio": "2026-11-16",
                "data_fine": "2026-11-20", "motivazione": "motivazione", "data_richiesta": "2026-11-16",
                "anomalie": "No"}
        proofs = {"nome_dipendente": "Sono Andrea Colombo", "tipo_assenza": "ferie", "data_inizio": "16 novembre",
                  "data_fine": "2026-11-20", "motivazione": "per il matrimonio di mia sorella",
                  "data_richiesta": "2026-11-16", "anomalie": "Nessuna anomalia"}
        out, _ = _check(data, proofs, schema, FERIE + " Nessuna anomalia.")
        self.assertEqual(out["tipo_assenza"], "Ferie")
        self.assertEqual(out["motivazione"], "Per il matrimonio di mia sorella")
        self.assertEqual(out["data_inizio"], "2026-11-16")
        self.assertEqual(out["data_richiesta"], "NON_SPECIFICATO")  # copiata dalla data di inizio
        self.assertEqual(out["anomalie"], "No")  # la prova dice proprio "nessuna"


class ImproveTextTests(unittest.TestCase):
    def test_label_echo_removed(self):
        from docx_ai.docintelligence.ai_service import _strip_label_echo
        self.assertEqual(_strip_label_echo("Argomenti (Argomenti discussi, in forma sintetica): Il budget.",
                                           "Argomenti", "Argomenti discussi, in forma sintetica"), "Il budget.")
        self.assertEqual(_strip_label_echo("Campo: Decisioni - si è deciso", "Decisioni"), "Si è deciso")
        self.assertEqual(_strip_label_echo("Argomenti tecnici trattati", "Argomenti"), "Argomenti tecnici trattati")


class DocumentOutputTests(unittest.TestCase):
    def test_object_rows_are_readable(self):
        from docx_ai.parsers.docx_parser import _to_display_line
        line = _to_display_line({"attivita": "Preparare il piano", "responsabile": "Paolo Verdi",
                                 "scadenza": "20/10/2026"})
        self.assertEqual(line, "Preparare il piano (responsabile: Paolo Verdi, scadenza: 20/10/2026)")
        self.assertNotIn("=", line)

    def test_summary_excel_lists_are_not_json(self):
        from docx_ai.exporters.summary_xlsx import _cell
        self.assertEqual(_cell(["Laura Bianchi", "Paolo Verdi"]), "Laura Bianchi; Paolo Verdi")

    def test_table_import_maps_short_headers(self):
        from docx_ai.services.import_service import suggest_mapping
        keys = ["nome_dipendente", "data_inizio", "data_fine", "giorni_lavorativi", "data_richiesta"]
        m = suggest_mapping(["Dipendente", "Dal", "Al", "Giorni", "Data richiesta"],
                            {"properties": {k: {"type": "string"} for k in keys}})
        self.assertEqual(m, {"nome_dipendente": "Dipendente", "data_inizio": "Dal", "data_fine": "Al",
                             "giorni_lavorativi": "Giorni", "data_richiesta": "Data richiesta"})
        # ambiguo: nessun abbinamento
        m = suggest_mapping(["Giorni"], {"properties": {"giorni_ferie": {}, "giorni_permesso": {}}})
        self.assertEqual(m, {"giorni_ferie": None, "giorni_permesso": None})


class LastExportTimeTests(unittest.TestCase):
    def test_uses_approval_time(self):
        import tempfile
        from datetime import datetime
        from docx_ai.db import Database
        tmp = Path(tempfile.mkdtemp())
        db = Database(tmp / "t.sqlite3")
        try:
            rid =db.create_report(module_id=None, module_version="1", status="draft", input_description="x",
                                   draft_json="{}")
            db.update_report(rid, status="exported", created_at="2026-10-08T18:26:00",
                             approved_at="2026-10-08T18:32:00")
            ts = db.last_report_timestamp(status="exported")
            self.assertEqual(datetime.fromtimestamp(ts).strftime("%H:%M"), "18:32")
        finally:
            db.close()


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
