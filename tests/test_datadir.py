"""Test cartella dati configurabile e lock tra postazioni."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


class DataDirTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mai_dd_"))
        self.env = mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.tmp / "local")})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_pointer_roundtrip(self):
        from docx_ai import datadir
        self.assertIsNone(datadir.configured_data_dir())
        datadir.set_configured_data_dir(self.tmp / "nas")
        self.assertEqual(datadir.configured_data_dir(), self.tmp / "nas")
        datadir.set_configured_data_dir(None)
        self.assertIsNone(datadir.configured_data_dir())

    def test_config_uses_pointer(self):
        from docx_ai import datadir
        from docx_ai.config import _default_data_dir
        datadir.set_configured_data_dir(self.tmp / "shared")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DOCX_AI_DATA_DIR", None)
            self.assertEqual(_default_data_dir("DOCX.AI"), self.tmp / "shared")

    def test_unc_is_network(self):
        from docx_ai.datadir import is_network_path
        self.assertTrue(is_network_path(Path("//server/share/mai")))
        self.assertFalse(is_network_path(self.tmp))

    def test_lock_blocks_other_active_host(self):
        from docx_ai.datadir import LOCK_NAME, DataDirLock, DataDirLocked
        root = self.tmp / "data"
        root.mkdir()
        (root / LOCK_NAME).write_text(json.dumps(
            {"host": "ALTRO-PC", "user": "mario", "pid": 1, "heartbeat": time.time()}))
        lock = DataDirLock(root)
        with self.assertRaises(DataDirLocked) as ctx:
            lock.acquire()
        self.assertEqual(ctx.exception.info.host, "ALTRO-PC")
        lock.acquire(force=True)
        self.assertEqual(lock.read().host, lock.me.host)
        lock.release()
        self.assertFalse((root / LOCK_NAME).exists())

    def test_stale_lock_is_taken_over(self):
        from docx_ai.datadir import LOCK_NAME, DataDirLock
        root = self.tmp / "data"
        root.mkdir()
        (root / LOCK_NAME).write_text(json.dumps(
            {"host": "ALTRO-PC", "user": "mario", "pid": 1, "heartbeat": time.time() - 3600}))
        lock = DataDirLock(root)
        lock.acquire()
        lock.release()


if __name__ == "__main__":
    unittest.main()


class LegacyMigrationTests(unittest.TestCase):
    """Dati della v0.3 (MaintenanceAI) spostati in DOCX.AI al primo avvio."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mai_mig_"))
        self.env = mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.tmp)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_legacy_folder_and_db_are_migrated(self):
        from docx_ai import datadir
        old = self.tmp / "MaintenanceAI"
        (old / "workspace" / "modules" / "m").mkdir(parents=True)
        (old / "maintenance_ai.db").write_bytes(b"db")
        (old / "maintenance_ai.db-wal").write_bytes(b"wal")
        msg = datadir.migrate_legacy_data()
        new = self.tmp / "DOCX.AI"
        self.assertIsNotNone(msg)
        self.assertFalse(old.exists())
        self.assertEqual((new / "docx_ai.db").read_bytes(), b"db")
        self.assertTrue((new / "docx_ai.db-wal").exists())
        self.assertTrue((new / "workspace" / "modules" / "m").is_dir())

    def test_existing_new_folder_is_not_touched(self):
        from docx_ai import datadir
        (self.tmp / "MaintenanceAI").mkdir()
        (self.tmp / "MaintenanceAI" / "maintenance_ai.db").write_bytes(b"old")
        new = self.tmp / "DOCX.AI"
        new.mkdir()
        (new / "docx_ai.db").write_bytes(b"new")
        self.assertIsNone(datadir.migrate_legacy_data())
        self.assertEqual((new / "docx_ai.db").read_bytes(), b"new")

    def test_only_logs_in_new_folder_still_migrates(self):
        from docx_ai import datadir
        (self.tmp / "MaintenanceAI").mkdir()
        (self.tmp / "MaintenanceAI" / "maintenance_ai.db").write_bytes(b"old")
        (self.tmp / "DOCX.AI" / "logs").mkdir(parents=True)
        datadir.migrate_legacy_data()
        self.assertEqual((self.tmp / "DOCX.AI" / "docx_ai.db").read_bytes(), b"old")

    def test_legacy_backup_is_accepted(self):
        import zipfile
        from docx_ai.services import backup_service
        z = self.tmp / "old_backup.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("maintenanceai_backup.json", json.dumps({"app": "MaintenanceAI", "version": "0.3.0"}))
            zf.writestr("maintenance_ai.db", "db")
        info = backup_service.validate_backup(z)
        self.assertEqual(info["version"], "0.3.0")
        target = self.tmp / "data"
        target.mkdir()
        shutil.copy2(z, target / backup_service.PENDING)
        backup_service.apply_pending_restore(target)
        self.assertEqual((target / "docx_ai.db").read_text(), "db")
