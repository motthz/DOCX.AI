"""Test: aggiornamento automatico da GitHub Releases."""

from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def _release(tag: str, data: bytes = b"setup", **extra) -> dict:
    ver = tag.lstrip("v")
    return {
        "tag_name": tag, "html_url": f"https://example/{tag}", "body": "note",
        "draft": False, "prerelease": False,
        "assets": [
            {"name": f"DOCX.AI-{ver}-portable-win64.zip", "browser_download_url": "x", "size": 1},
            {"name": f"DOCX.AI-Setup-{ver}.exe", "browser_download_url": "https://example/setup.exe",
             "size": len(data), "digest": "sha256:" + hashlib.sha256(data).hexdigest()},
        ],
        **extra,
    }


class _Resp(io.BytesIO):
    headers: dict = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        from docx_ai.services import updater
        self.up = updater
        self.tmp = Path(tempfile.mkdtemp(prefix="mai_upd_"))

    def test_version_compare(self):
        self.assertTrue(self.up.is_newer("v0.4.10", "0.4.9"))
        self.assertTrue(self.up.is_newer("1.0", "0.9.9"))
        self.assertFalse(self.up.is_newer("v0.4.1", "0.4.1"))
        self.assertFalse(self.up.is_newer("garbage", "0.4.1"))

    def test_parse_release_picks_installer(self):
        info = self.up.parse_release(_release("v0.5.0"))
        self.assertEqual(info.version, "0.5.0")
        self.assertEqual(info.asset_name, "DOCX.AI-Setup-0.5.0.exe")
        self.assertEqual(len(info.sha256), 64)
        self.assertIsNone(self.up.parse_release(_release("v0.5.0", prerelease=True)))

    def test_check_only_reports_newer(self):
        def fake_open(rel):
            return mock.patch.object(self.up, "_open", return_value=_Resp(json.dumps(rel).encode()))
        with fake_open(_release("v9.0.0")):
            self.assertEqual(self.up.check("0.4.1").version, "9.0.0")
        with fake_open(_release("v0.4.1")):
            self.assertIsNone(self.up.check("0.4.1"))
        with mock.patch.object(self.up, "_open", side_effect=OSError("404 privato")):
            self.assertIsNone(self.up.check("0.4.1"))

    def test_download_verifies_checksum(self):
        data = b"installer-bytes" * 100
        info = self.up.parse_release(_release("v9.0.0", data))
        with mock.patch.object(self.up, "_open", return_value=_Resp(data)):
            out = self.up.download(info, dest_dir=self.tmp)
        self.assertEqual(out.read_bytes(), data)
        # gia' scaricato: nessun nuovo download
        with mock.patch.object(self.up, "_open", side_effect=AssertionError("non deve scaricare")):
            self.assertEqual(self.up.download(info, dest_dir=self.tmp), out)

    def test_download_rejects_corrupted_file(self):
        info = self.up.parse_release(_release("v9.0.0", b"original"))
        with mock.patch.object(self.up, "_open", return_value=_Resp(b"tampered")):
            with self.assertRaises(RuntimeError):
                self.up.download(info, dest_dir=self.tmp)
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_cleanup_removes_installed_versions(self):
        for name in ("DOCX.AI-Setup-0.4.0.exe", "DOCX.AI-Setup-0.4.1.exe", "DOCX.AI-Setup-0.5.0.exe",
                     "DOCX.AI-Setup-0.5.1.part"):
            (self.tmp / name).write_bytes(b"x")
        self.up.cleanup("0.4.1", dest_dir=self.tmp)
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["DOCX.AI-Setup-0.5.0.exe"])

    def test_installer_command_is_silent(self):
        cmd = self.up.installer_command(Path("setup.exe"), relaunch=True)
        self.assertIn("/SILENT", cmd)
        self.assertIn("/AIMODEL=none", cmd)
        self.assertIn("/RELAUNCH=1", cmd)

    def test_self_install_only_for_installed_exe(self):
        self.assertFalse(self.up.can_self_install(self.tmp))  # sorgenti / portable

    def test_policy_env(self):
        with mock.patch.dict("os.environ", {"DOCX_AI_NO_UPDATE": "1"}):
            self.assertTrue(self.up.disabled_by_policy())


if __name__ == "__main__":
    unittest.main()
