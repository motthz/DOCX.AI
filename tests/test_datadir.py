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
        from maintenance_ai import datadir
        self.assertIsNone(datadir.configured_data_dir())
        datadir.set_configured_data_dir(self.tmp / "nas")
        self.assertEqual(datadir.configured_data_dir(), self.tmp / "nas")
        datadir.set_configured_data_dir(None)
        self.assertIsNone(datadir.configured_data_dir())

    def test_config_uses_pointer(self):
        from maintenance_ai import datadir
        from maintenance_ai.config import _default_data_dir
        datadir.set_configured_data_dir(self.tmp / "shared")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MAINTENANCE_AI_DATA_DIR", None)
            self.assertEqual(_default_data_dir("MaintenanceAI"), self.tmp / "shared")

    def test_unc_is_network(self):
        from maintenance_ai.datadir import is_network_path
        self.assertTrue(is_network_path(Path("//server/share/mai")))
        self.assertFalse(is_network_path(self.tmp))

    def test_lock_blocks_other_active_host(self):
        from maintenance_ai.datadir import LOCK_NAME, DataDirLock, DataDirLocked
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
        from maintenance_ai.datadir import LOCK_NAME, DataDirLock
        root = self.tmp / "data"
        root.mkdir()
        (root / LOCK_NAME).write_text(json.dumps(
            {"host": "ALTRO-PC", "user": "mario", "pid": 1, "heartbeat": time.time() - 3600}))
        lock = DataDirLock(root)
        lock.acquire()
        lock.release()


if __name__ == "__main__":
    unittest.main()
