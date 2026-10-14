"""Controlli deterministici dell'audit, pulizia dei testi scritti di fretta, scelta del
modello con poca RAM e lettura avanzata della scrittura a mano."""

from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import List
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from docx_ai.docintelligence.audit_checks import run_checks  # noqa: E402
from docx_ai.llm.text_cleanup import clean_user_text  # noqa: E402


@dataclass
class Doc:
    path: Path
    full_text: str
    spans: List = field(default_factory=list)


def _docs(**files: str) -> List[Doc]:
    return [Doc(Path(name), text) for name, text in files.items()]


PACKAGE = _docs(**{
    "RdM_245-26.docx": "Rapporto di manutenzione n. 245/26\nData intervento: 05/10/2026\nMacchina: AF-300\n"
                       "Rif. ordine di lavoro: OdL-1182\nTecnico: Marco Galli\n"
                       "Attività: cuscinetti sostituiti secondo procedura PR-07 rev. 3.\n"
                       "Misure eseguite con calibro CAL-12.\nEsito: positivo (vedi Verbale_collaudo_245-26).",
    "OdL-1182.xlsx": "[Sheet: OdL]\nCampo | Valore\nNumero OdL | OdL-1182\nData apertura | 07/10/2026\n"
                     "Macchina | AF-350\nResponsabile |\nRapporto collegato | Rapporto 245/26",
    "PR-07_rev2.pdf": "Procedura PR-07 - Sostituzione cuscinetti\nRevisione: rev. 2 del 12/01/2025\n"
                      "Approvato da: Responsabile Manutenzione L. Sala",
    "Verbale_collaudo_245-26.txt": "VERBALE DI COLLAUDO\nRapporto collegato: 245/26\nMacchina: AF-300\n"
                                   "Data collaudo: 03/10/2026\nEsito: positivo. Firmato: Paolo Riva",
    "NC_2026-031.docx": "Non conformità NC 2026/031\nData apertura: 11/10/2026\nData chiusura: 01/10/2026\n"
                        "Azione correttiva: vedi rapporto 8D n. 8D-044 richiesto al fornitore.\n"
                        "Responsabile qualità: Elena Bassi",
    "Registro_tarature.xlsx": "[Sheet: Tarature]\nStrumento | Codice | Ultima taratura | Scadenza\n"
                              "Calibro digitale | CAL-11 | 15/03/2026 | 15/03/2027\n"
                              "Calibro digitale | CAL-12 | 30/09/2025 | 30/09/2026",
    "nota_scansionata.png": "Nota per il rapporto 245/26:\nApprovato da Responsabile Qualità:\nfirma:\n(manca)",
})


class AuditChecksTest(unittest.TestCase):
    def test_every_planted_problem_is_found(self):
        issues = run_checks(PACKAGE)
        kinds = sorted(i.kind for i in issues)
        text = " ".join(i.title + " " + i.description for i in issues)
        self.assertIn("chiusura (01/10/2026) è precedente", text)
        self.assertIn("aperto il 07/10/2026", text)                      # ordine dopo l'intervento
        self.assertIn("collaudo/verifica il 03/10/2026", text)           # collaudo prima dell'intervento
        self.assertIn("8D-044", text)                                    # documento citato assente
        self.assertIn("PR-07 rev. 3, ma nel pacchetto c'è la rev. 2", text)
        self.assertIn("CAL-12", text)                                    # taratura scaduta
        self.assertIn("AF-300 / AF-350", text)
        self.assertEqual(kinds.count("firma"), 2)                        # OdL e nota scansionata

    def test_no_false_alarms_on_correct_documents(self):
        docs = _docs(**{
            "RdM_100-26.docx": "Rapporto n. 100/26\nData intervento: 05/10/2026\nMacchina: AF-300\n"
                               "Secondo procedura PR-07 rev. 2.\nFirmato: Marco Galli\nVedi allegato A.",
            "Verbale_100-26.txt": "Verbale di collaudo\nRapporto collegato: 100/26\nMacchina: AF-300\n"
                                  "Data collaudo: 06/10/2026\nFirmato:\nPaolo Riva",
            "PR-07_rev2.pdf": "Procedura PR-07\nRevisione: rev. 2\nApprovato da: L. Sala",
        })
        self.assertEqual([i.title for i in run_checks(docs)], [])

    def test_purchase_chain(self):
        docs = _docs(**{
            "Offerta_OFF-2291.pdf": "Offerta OFF-2291\nData offerta: 28/08/2026\nScadenza offerta: 15/09/2026",
            "Ordine_ODA-1120.xlsx": "[Sheet: Ordine]\nCampo | Valore\nData emissione | 20/09/2026\n"
                                    "Rif. offerta | OFF-2291\nApprovato da | Marta Neri",
            "DDT_778-26.txt": "DOCUMENTO DI TRASPORTO DDT 778/26\nRif. ordine: ODA-1120\nData consegna: 18/09/2026",
        })
        titles = " ".join(i.title for i in run_checks(docs))
        self.assertIn("successivo alla scadenza di Offerta_OFF-2291.pdf", titles)
        self.assertIn("Consegna precedente all'ordine", titles)


class TextCleanupTest(unittest.TestCase):
    def test_self_corrections_keep_the_last_value(self):
        out, notes = clean_user_text(
            "elena bassi, reparto produzione anzi no scusate reparto qualità. servono 2 calibri dalla ditta "
            "Utensilmarket, no aspetta, da Tecnoutensili srl. costo 500 euro, anzi no 680.")
        self.assertIn("reparto qualità", out)
        self.assertNotIn("produzione", out)
        self.assertIn("da Tecnoutensili srl", out)
        self.assertNotIn("Utensilmarket", out)
        self.assertIn("costo 680 euro", out)
        self.assertIn("autocorrezioni applicate", notes)
        self.assertEqual(clean_user_text("pressione 3 bar, anzi no 3,5 bar.")[0], "pressione 3,5 bar.")

    def test_abbreviations(self):
        out, _ = clean_user_text("rapp 245/26 rep affettati manut straordinaria, matr 10457, 5 gg xke urgente")
        self.assertEqual(out, "rapporto 245/26 reparto affettati manutenzione straordinaria, matricola 10457, "
                              "5 giorni perché urgente")

    def test_names_measures_and_normal_text_untouched(self):
        for text in ("Il tecnico Rep Marco ha lavorato 3 ore", "tolleranza 2 x 3 mm",
                     "In realtà la macchina era già ferma.", "La macchina AF-300 è ferma."):
            self.assertEqual(clean_user_text(text)[0], text)


class LowRamModelChoiceTest(unittest.TestCase):
    def test_reduced_context_before_smaller_model(self):
        from docx_ai.docintelligence.ai_service import AIService
        from docx_ai.llm import hardware
        tmp = Path(tempfile.mkdtemp())
        big, small = tmp / "Qwen3-1.7B-Q4_K_M.gguf", tmp / "Qwen3-0.6B-Q8_0.gguf"
        big.write_bytes(b"x")
        small.write_bytes(b"x")
        svc = AIService.__new__(AIService)
        svc.config = mock.Mock()
        svc.config.installed_chat_models.return_value = [big, small]
        svc._setting = lambda key, default: 0
        svc.ram_warning = ""
        need = {(big, 8192): 2400, (big, 4096): 1900, (small, 8192): 1500, (small, 4096): 1000}
        with mock.patch.object(hardware, "refresh_memory", return_value=mock.Mock(ram_available=2000,
                                                                                  ram_available_gb=2.0)), \
                mock.patch.object(hardware, "model_ram_need", side_effect=lambda p, c: need[(p, c)]):
            cands = svc._model_candidates({"context_size": 8192})
        self.assertEqual(cands[0], (big, 4096))  # stesso modello preciso, contesto ridotto
        self.assertEqual(svc.ram_warning, "")


class HandwritingReaderTest(unittest.TestCase):
    def test_reads_image_with_vision_server_and_stops(self):
        from PIL import Image
        from docx_ai.llm import vision
        tmp = Path(tempfile.mkdtemp())
        (tmp / "runtime").mkdir()
        (tmp / "runtime" / "llama-server.exe").write_bytes(b"x")
        (tmp / "models").mkdir()
        for name in (vision.VISION_MODEL_FILE, vision.VISION_MMPROJ_FILE):
            (tmp / "models" / name).write_bytes(b"x")
        Image.new("RGB", (3000, 1000), "white").save(tmp / "foto.png")
        cfg = mock.Mock()
        cfg.llm_effective = {"runtime_dir": "runtime", "model_dir": "models"}
        cfg.resolve_ai_path = lambda rel: tmp / rel
        sent = {}

        class FakeServer:
            def __init__(self, options):
                sent["options"] = options
                self.is_running = False

            def start(self, timeout=0):
                self.is_running = True

            def chat_completions(self, messages, **kw):
                sent["messages"] = messages
                return {"choices": [{"message": {"content": " Rapporto 245/26 \n"}}]}

            def stop(self):
                sent["stopped"] = True

        reader = vision.HandwritingReader(cfg)
        self.assertTrue(reader.available())
        with mock.patch.object(vision, "LlamaServer", FakeServer):
            self.assertEqual(reader.read(tmp / "foto.png"), "Rapporto 245/26")
            reader.stop()
        self.assertEqual(sent["options"].mmproj, tmp / "models" / vision.VISION_MMPROJ_FILE)
        self.assertFalse(sent["options"].speculative)
        uri = sent["messages"][0]["content"][0]["image_url"]["url"]
        self.assertTrue(uri.startswith("data:image/jpeg;base64,"))
        self.assertTrue(sent.get("stopped"))

    def test_not_available_without_model(self):
        from docx_ai.llm import vision
        cfg = mock.Mock()
        cfg.llm_effective = {}
        cfg.resolve_ai_path = lambda rel: Path(tempfile.mkdtemp()) / rel
        reader = vision.HandwritingReader(cfg)
        self.assertFalse(reader.available())
        with self.assertRaises(RuntimeError):
            reader.read(Path("x.png"))


if __name__ == "__main__":
    unittest.main()
