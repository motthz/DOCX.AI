"""Test su core: config, db, security, path safety."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(REPO))


class ConfigTests(unittest.TestCase):
    def test_load_default(self):
        from docx_ai.config import Config
        cfg = Config.load()
        self.assertTrue(cfg.app_root.exists())
        self.assertTrue(cfg.data_root.exists())
        self.assertTrue(cfg.db_path().parent.exists())

    def test_available_profiles_known(self):
        from docx_ai.config import Config
        cfg = Config.load()
        profs = cfg.available_profiles()
        self.assertIn("compatibility", profs)
        self.assertIn("balanced", profs)
        self.assertIn("fastest", profs)


class DbTests(unittest.TestCase):
    def setUp(self):
        from docx_ai.db import Database
        td = Path(tempfile.mkdtemp(prefix="mai_db_"))
        self.db_path = td / "t.db"
        self.db = Database(self.db_path)

    def tearDown(self):
        self.db.close()

    def test_settings_get_set(self):
        self.db.set_setting("k", "v")
        self.assertEqual(self.db.get_setting("k"), "v")
        self.assertIsNone(self.db.get_setting("nope"))

    def test_modules_upsert_and_list(self):
        mid = self.db.upsert_module(
            slug="mod_a", name="Mod A", version="1.0",
            template_type="docx", template_path="x", schema_path="y",
            mapping_path="z", module_json_path="w", folder_path="f",
        )
        self.assertIsInstance(mid, int)
        rows = self.db.list_modules()
        self.assertEqual(len([r for r in rows if r["slug"] == "mod_a"]), 1)

    def test_report_flow(self):
        mid = self.db.upsert_module(
            slug="m", name="M", template_type="docx", version="1.0",
            template_path="t", schema_path="s", mapping_path="m",
            module_json_path="j", folder_path="f",
        )
        rid = self.db.create_report(
            module_id=mid, module_version="1.0", status="draft",
            input_description="Ciao", draft_json=json.dumps({"a": 1}),
        )
        self.db.update_report(rid, final_json=json.dumps({"a": 2}), status="approved")
        row = self.db.get_report(rid)
        self.assertEqual(row["status"], "approved")
        self.assertEqual(json.loads(row["final_json"])["a"], 2)


class SecurityTests(unittest.TestCase):
    def test_safe_resolve_no_escape(self):
        from docx_ai.security import safe_resolve_name, SecurityError
        root = Path(tempfile.mkdtemp(prefix="mai_sec_"))
        ok = safe_resolve_name(root, "hello/world.txt")
        self.assertTrue(str(ok.resolve()).startswith(str(root.resolve())))
        with self.assertRaises(SecurityError):
            safe_resolve_name(root, "../etc/passwd")
        with self.assertRaises(SecurityError):
            safe_resolve_name(root, "C:\\Windows")
        with self.assertRaises(SecurityError):
            safe_resolve_name(root, "")

    def test_safe_slug_sanitizes(self):
        from docx_ai.security import safe_slug
        self.assertNotIn("?", safe_slug("a?b"))
        self.assertNotIn("\\", safe_slug("a\\b"))
        self.assertEqual(safe_slug(""), "module")

    def test_sha256_bytes_deterministic(self):
        from docx_ai.security import sha256_bytes
        self.assertEqual(sha256_bytes(b"abc"),
                         "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


if __name__ == "__main__":
    unittest.main()
