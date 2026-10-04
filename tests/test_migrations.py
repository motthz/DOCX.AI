"""Test migrazioni DB: un database creato dalla v0.1.0 deve aprirsi con la
versione corrente senza perdere dati, e ogni stato intermedio deve migrare."""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

FIXTURE = REPO / "tests" / "fixtures" / "db_v0_1_0.fixture"


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mai_mig_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_v010_database_upgrades_and_keeps_data(self):
        from docx_ai.db import _MIGRATIONS, Database
        path = self.tmp / "old.db"
        shutil.copy(FIXTURE, path)
        db = Database(path)
        try:
            ver = db._conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()["v"]
            self.assertEqual(ver, len(_MIGRATIONS))
            mods = db.list_modules()
            self.assertEqual([m["slug"] for m in mods], ["rapporto_test"])
            reports = db.list_reports(limit=50)
            self.assertEqual(len(reports), 3)
            self.assertEqual(db.count_reports(status="exported"), 2)
            self.assertEqual(db.get_setting("ui.theme"), "dark")
            exported = [r for r in reports if r["status"] == "exported"]
            self.assertEqual(json.loads(exported[0]["final_json"])["esito"], "conforme")
            # the upgraded DB must stay writable
            db.set_setting("k", "v")
            self.assertEqual(db.get_setting("k"), "v")
        finally:
            db.close()

    def test_every_intermediate_schema_migrates(self):
        from docx_ai.db import _MIGRATIONS, Database
        for applied in range(len(_MIGRATIONS) + 1):
            with self.subTest(applied=applied):
                path = self.tmp / f"step{applied}.db"
                conn = sqlite3.connect(path)
                conn.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
                for i, sql in enumerate(_MIGRATIONS[:applied], start=1):
                    conn.executescript(sql)
                    conn.execute("INSERT INTO schema_migrations VALUES (?, 'x')", (i,))
                conn.commit()
                conn.close()
                db = Database(path)
                try:
                    ver = db._conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()["v"]
                    self.assertEqual(ver, len(_MIGRATIONS))
                finally:
                    db.close()

    def test_reopen_is_idempotent(self):
        from docx_ai.db import Database
        path = self.tmp / "twice.db"
        Database(path).close()
        db = Database(path)
        db.close()


if __name__ == "__main__":
    unittest.main()
