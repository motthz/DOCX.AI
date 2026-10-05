"""Test: risoluzione percorsi AI, catena backend con fallback, installer AI."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(REPO))


def _isolated_config(tmp: Path):
    from docx_ai.config import Config
    with mock.patch.dict(os.environ, {"DOCX_AI_DATA_DIR": str(tmp / "data")}):
        cfg = Config.load()
    cfg.app_root = tmp / "app"
    cfg.app_root.mkdir(parents=True, exist_ok=True)
    # Unreachable Ollama so auto-detect never finds a real local service.
    cfg.raw["llm"]["ollama_url"] = "http://127.0.0.1:9"
    cfg._recompute_llm_profile()
    return cfg


class ResolveAiPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mai_ai_"))
        self.cfg = _isolated_config(self.tmp)

    def test_defaults_to_data_dir(self):
        p = self.cfg.resolve_ai_path("models/x.gguf")
        self.assertEqual(p, self.cfg.data_root / "models" / "x.gguf")

    def test_falls_back_to_app_dir(self):
        f = self.cfg.app_root / "models" / "x.gguf"
        f.parent.mkdir(parents=True)
        f.write_bytes(b"x")
        self.assertEqual(self.cfg.resolve_ai_path("models/x.gguf"), f)

    def test_data_dir_wins(self):
        for base in (self.cfg.app_root, self.cfg.data_root):
            f = base / "models" / "x.gguf"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(b"x")
        self.assertEqual(self.cfg.resolve_ai_path("models/x.gguf"),
                         self.cfg.data_root / "models" / "x.gguf")

    def test_status_reports_missing_components(self):
        st = self.cfg.ai_components_status()
        self.assertFalse(st["runtime_ok"])
        self.assertFalse(st["model_ok"])


class AiChainTests(unittest.TestCase):
    def setUp(self):
        from docx_ai.db import Database
        from docx_ai.docintelligence.ai_service import AIService
        from docx_ai.docintelligence.rules_manager import RulesManager
        self.tmp = Path(tempfile.mkdtemp(prefix="mai_chain_"))
        self.cfg = _isolated_config(self.tmp)
        self.db = Database(self.tmp / "t.db")
        self.svc = AIService(self.cfg, self.db, RulesManager(self.cfg, db=self.db))

    def tearDown(self):
        self.svc.shutdown()
        self.db.close()

    def test_falls_back_to_mock_without_components(self):
        from docx_ai.llm.llama_server import MockLlamaServer
        pipe = self.svc.pipeline()
        self.assertFalse(self.svc.is_real_ai)
        self.assertIsInstance(pipe.server_chain[-1], MockLlamaServer)
        self.assertIs(self.svc.pipeline(), pipe, "pipeline must be shared")

    def test_report_service_reuses_ai_service(self):
        from docx_ai.services.report_service import ReportService
        rs = ReportService(self.cfg, self.db, None, None, ai_service=self.svc)
        self.assertIs(rs.pipeline(), self.svc.pipeline())

    def test_reset_forces_redetection(self):
        first = self.svc.pipeline()
        self.svc.reset()
        self.assertIsNot(self.svc.pipeline(), first)


class InstallerTests(unittest.TestCase):
    def test_bad_checksum_is_rejected(self):
        from docx_ai.llm import ai_installer
        tmp = Path(tempfile.mkdtemp(prefix="mai_inst_"))
        src = tmp / "fake.gguf"
        src.write_bytes(b"not a model")
        fake = {"fake.gguf": {"url": src.as_uri(), "sha256": "0" * 64, "label": "x"}}
        inst = ai_installer.AIInstaller(tmp / "data")
        with mock.patch.dict(ai_installer.MODELS, fake, clear=True):
            with self.assertRaises(RuntimeError):
                inst.install_model("fake.gguf", lambda f, m: None)
        self.assertFalse((tmp / "data" / "models" / "fake.gguf").exists())

    def test_model_download_ok(self):
        import hashlib
        from docx_ai.llm import ai_installer
        tmp = Path(tempfile.mkdtemp(prefix="mai_inst_"))
        src = tmp / "fake.gguf"
        src.write_bytes(b"model-bytes" * 1000)
        sha = hashlib.sha256(src.read_bytes()).hexdigest()
        fake = {"fake.gguf": {"url": src.as_uri(), "sha256": sha, "label": "x"}}
        inst = ai_installer.AIInstaller(tmp / "data")
        with mock.patch.dict(ai_installer.MODELS, fake, clear=True):
            out = inst.install_model("fake.gguf", lambda f, m: None)
        self.assertEqual(out.read_bytes(), src.read_bytes())

    def test_runtime_install_extracts_into_runtime_dir(self):
        import zipfile
        from docx_ai.llm import ai_installer
        tmp = Path(tempfile.mkdtemp(prefix="mai_inst_"))
        zpath = tmp / "llama-b1-bin-win-cpu-x64.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("llama-server.exe", b"exe")
            zf.writestr("ggml.dll", b"dll")
            zf.writestr("LICENSE", b"mit")
        asset = {"name": zpath.name, "browser_download_url": zpath.as_uri(),
                 "size": zpath.stat().st_size}
        inst = ai_installer.AIInstaller(tmp / "data")
        with mock.patch.object(inst, "_find_llama_asset", return_value=asset):
            out = inst.install_runtime(lambda f, m: None)
        self.assertEqual(out, tmp / "data" / "runtime" / "llama")
        self.assertEqual((out / "llama-server.exe").read_bytes(), b"exe")
        self.assertTrue((out / "ggml.dll").is_file())


if __name__ == "__main__":
    unittest.main()
