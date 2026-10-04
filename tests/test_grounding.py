"""Test del controllo anti-allucinazione."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maintenance_ai.llm.grounding import GroundingChecker, summarize  # noqa: E402

DESC = ("Il 2 ottobre 2026 il tecnico Mario Rossi ha sostituito la cinghia del compressore C-12 "
        "nell'impianto di Lecco. Esito positivo.")


class GroundingTests(unittest.TestCase):
    def setUp(self):
        self.g = GroundingChecker([DESC])

    def test_invented_number_is_flagged(self):
        c = self.g.check_value("123456")
        self.assertEqual(c.status, "missing")
        self.assertIn("123456", c.missing)

    def test_code_with_different_separators_is_found(self):
        self.assertEqual(self.g.check_value("C12").status, "ok")
        self.assertEqual(self.g.check_value("C-12").status, "ok")

    def test_date_in_any_format(self):
        self.assertEqual(self.g.check_value("2026-10-02").status, "ok")
        self.assertEqual(self.g.check_value("02/10/2026").status, "ok")
        self.assertEqual(self.g.check_value("2026-10-03").status, "missing")

    def test_names(self):
        self.assertEqual(self.g.check_value("Mario Rossi").status, "ok")
        self.assertEqual(self.g.check_value("Luca Bianchi").status, "missing")

    def test_empty_bool_enum(self):
        self.assertEqual(self.g.check_value("NON_SPECIFICATO").status, "empty")
        self.assertEqual(self.g.check_value(True).status, "inferred")
        spec = {"enum": ["conforme", "non_conforme"]}
        self.assertEqual(self.g.check_value("conforme", spec).status, "inferred")

    def test_nested_list(self):
        val = [{"tipologia_pezzo": "cinghia", "numero_pz": "1", "codice_misure": "123456"}]
        c = self.g.check_value(val)
        self.assertEqual(c.status, "missing")

    def test_full_record_summary(self):
        data = {"apparecchiatura": "C-12", "numero_rapporto": "123456", "note": "NON_SPECIFICATO",
                "firma": "Mario Rossi", "pulizia": True}
        s = summarize(self.g.check(data))
        self.assertEqual(s["missing"], 1)
        self.assertEqual(s["ok"], 2)


if __name__ == "__main__":
    unittest.main()
