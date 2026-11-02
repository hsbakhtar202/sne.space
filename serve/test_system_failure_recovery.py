"""Phase 5: controlled failure/recovery against the durable publication machine.

Isolated temp dirs only — never production. Each test injects a fault class and
asserts accepted work is not silently lost and recovery restores consistency.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path


class _Env:
    def __init__(self, tc: unittest.TestCase) -> None:
        self.tc = tc
        self._td = tempfile.TemporaryDirectory()
        root = Path(self._td.name)
        self.runtime = root / "runtime"
        self.data = root / "data"
        self.epoch = self.data / "sne-2025-2029"
        self.runtime.mkdir(parents=True)
        self.epoch.mkdir(parents=True)
        os.environ["SNE_RUNTIME_DIR"] = str(self.runtime)
        import ingest.manager as mgr
        import ingest.catalog_publish as cp

        self._old_out = mgr.SUPERNOVAE_OUTPUT
        mgr.SUPERNOVAE_OUTPUT = self.data
        cp.SUPERNOVAE_OUTPUT = self.data

    def cleanup(self) -> None:
        import ingest.manager as mgr
        import ingest.catalog_publish as cp

        mgr.SUPERNOVAE_OUTPUT = self._old_out
        cp.SUPERNOVAE_OUTPUT = self._old_out
        os.environ.pop("SNE_RUNTIME_DIR", None)
        for k in ("SNE_PUBLISH_FAIL_SQLITE", "SNE_PUBLISH_CRASH_AFTER"):
            os.environ.pop(k, None)
        self._td.cleanup()

    def write_event(self, name: str, n_det: int, n_lim: int = 0) -> Path:
        base = 61338.0
        phot = [
            {"time": str(base - 1 - i), "magnitude": "20", "upperlimit": True, "kind": "non_detection"}
            for i in range(n_lim)
        ] + [
            {"time": str(base + i), "magnitude": str(19 - 0.1 * i), "upperlimit": False}
            for i in range(n_det)
        ]
        body = {name: {"name": name, "discoverdate": [{"value": "2026/10/25"}],
                       "claimedtype": [{"value": "unclassified"}], "photometry": phot}}
        p = self.epoch / f"{name}.json"
        p.write_text(json.dumps(body), encoding="utf-8")
        return p

    def build_db(self) -> Path:
        from serve.catalog_store import CatalogStore

        db = self.data / ".index" / "catalog.db"
        db.parent.mkdir(parents=True, exist_ok=True)
        CatalogStore(db).build([self.epoch])
        return db


class TestFailureRecovery(unittest.TestCase):
    def setUp(self) -> None:
        self.env = _Env(self)

    def tearDown(self) -> None:
        self.env.cleanup()

    def build_db(self) -> Path:
        return self.env.build_db()

    def _row(self, db: Path, name: str):
        import sqlite3

        conn = sqlite3.connect(str(db))
        r = conn.execute(
            "SELECT phot, json_extract(meta_json,'$.publish_revision') FROM events WHERE name=?",
            (name,),
        ).fetchone()
        conn.close()
        return r

    def test_sqlite_failure_marks_failed_and_recovers(self) -> None:
        from ingest.publication import (
            is_fully_published,
            pending_names,
            publish_event_paths,
            recover_pending,
        )

        db = self.build_db()
        p = self.env.write_event("AT2026fr1", 2)
        os.environ["SNE_PUBLISH_FAIL_SQLITE"] = "1"
        res = publish_event_paths([p], catalog_db=db)
        self.assertEqual(res.get("state"), "failed")
        self.assertIn("AT2026fr1", pending_names())
        self.assertFalse(is_fully_published("AT2026fr1"))
        os.environ.pop("SNE_PUBLISH_FAIL_SQLITE")
        rec = recover_pending(catalog_db=db)
        self.assertGreaterEqual(rec.get("recovered", 0), 1)
        self.assertTrue(is_fully_published("AT2026fr1"))
        self.assertEqual(self._row(db, "AT2026fr1")[0], 2)

    def test_crash_before_sqlite_recovers_pending(self) -> None:
        from ingest.publication import pending_names, publish_event_paths, recover_pending

        db = self.build_db()
        p = self.env.write_event("AT2026fr2", 1)
        os.environ["SNE_PUBLISH_CRASH_AFTER"] = "overlay"
        with self.assertRaises(SystemExit):
            publish_event_paths([p], catalog_db=db)
        os.environ.pop("SNE_PUBLISH_CRASH_AFTER")
        self.assertIn("AT2026fr2", pending_names())
        recover_pending(catalog_db=db)
        self.assertIsNotNone(self._row(db, "AT2026fr2"))

    def test_duplicate_publish_is_idempotent(self) -> None:
        from ingest.publication import publish_event_paths

        db = self.build_db()
        p = self.env.write_event("AT2026fr3", 3)
        r1 = publish_event_paths([p], catalog_db=db)
        r2 = publish_event_paths([p], catalog_db=db)
        self.assertEqual(r1.get("upserted"), r2.get("upserted"))
        self.assertEqual(self._row(db, "AT2026fr3")[0], 3)

    def test_downward_correction_republishes_lower_count(self) -> None:
        from ingest.publication import publish_event_paths

        db = self.build_db()
        p = self.env.write_event("AT2026fr4", 5)
        publish_event_paths([p], catalog_db=db)
        self.assertEqual(self._row(db, "AT2026fr4")[0], 5)
        # legitimate correction removes 4 points
        self.env.write_event("AT2026fr4", 1)
        publish_event_paths([p], catalog_db=db)
        row = self._row(db, "AT2026fr4")
        self.assertEqual(row[0], 1)

    def test_restart_recovers_pending_without_manual_state(self) -> None:
        """Container-restart analogue: state file persists; in-memory queue does not."""
        from ingest.publication import mark_ingested, pending_names, recover_pending

        db = self.build_db()
        p = self.env.write_event("AT2026fr5", 1)
        mark_ingested("AT2026fr5", p)  # durable pending; simulate crash before publish
        self.assertIn("AT2026fr5", pending_names())
        rec = recover_pending(catalog_db=db)  # what pull_recent runs at boot
        self.assertGreaterEqual(rec.get("recovered", 0), 1)
        self.assertIsNotNone(self._row(db, "AT2026fr5"))


if __name__ == "__main__":
    unittest.main()
