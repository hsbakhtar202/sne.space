"""publish_revision must exceed authoritative committed high-water marks."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path


def _write_min_catalog_db(db_path: Path, revisions: list[tuple[str, int]]) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE events ("
        "name TEXT PRIMARY KEY, aliases_json TEXT, type TEXT, type_badge TEXT, "
        "date TEXT, age TEXT, mag REAL, z REAL, ra TEXT, dec TEXT, host TEXT, "
        "disc TEXT, spec INTEGER, phot INTEGER, search_blob TEXT, meta_json TEXT)"
    )
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    for name, rev in revisions:
        meta = json.dumps({"name": name, "publish_revision": rev, "photolink": "1,0"})
        conn.execute(
            "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                name,
                "[]",
                "unclassified",
                "other",
                "—",
                "—",
                None,
                None,
                "—",
                "—",
                "—",
                "—",
                0,
                1,
                name.lower(),
                meta,
            ),
        )
    conn.execute("INSERT INTO meta VALUES ('schema_version', '1')")
    conn.execute("INSERT INTO meta VALUES ('event_count', ?)", (str(len(revisions)),))
    conn.commit()
    conn.close()


class TestPublishRevisionHighWater(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        root = Path(self._td.name)
        self.runtime = root / "runtime"
        self.data = root / "data"
        self.runtime.mkdir(parents=True)
        self.data.mkdir(parents=True)
        os.environ["SNE_RUNTIME_DIR"] = str(self.runtime)
        os.environ["SNE_DATA_DIR"] = str(self.data)
        # Reset process cache between tests
        import ingest.catalog_publish as cp

        cp._STORE_HWM_CACHE["value"] = 0.0
        cp._STORE_HWM_CACHE["checked_at"] = 0.0

    def tearDown(self) -> None:
        self._td.cleanup()
        os.environ.pop("SNE_RUNTIME_DIR", None)
        os.environ.pop("SNE_DATA_DIR", None)

    def test_recovers_when_sequence_file_absent_but_store_has_high_revision(self) -> None:
        from ingest.catalog_publish import REVISION_NAME, next_publish_revision

        future = int(time.time()) + 50_000
        db = self.data / ".index" / "catalog.db"
        _write_min_catalog_db(db, [("AT2026hwm", future)])
        seq = self.runtime / REVISION_NAME
        self.assertFalse(seq.exists())
        got = next_publish_revision(catalog_db=db)
        self.assertGreater(got, future)
        self.assertTrue(seq.is_file())

    def test_recovers_when_sequence_file_reset_below_overlay(self) -> None:
        from ingest.catalog_publish import (
            OVERLAY_NAME,
            REVISION_NAME,
            next_publish_revision,
        )

        high = int(time.time()) + 80_000
        (self.runtime / OVERLAY_NAME).write_text(
            json.dumps([{"name": "AT2026ov", "publish_revision": high}]),
            encoding="utf-8",
        )
        (self.runtime / REVISION_NAME).write_text("3", encoding="utf-8")
        got = next_publish_revision()
        self.assertGreater(got, high)

    def test_acceptance_new_revision_exceeds_staging_persisted_state(self) -> None:
        """Explicit acceptance: after seeding store+overlay, allocate > max committed."""
        from ingest.catalog_publish import (
            authoritative_publish_revision_high_water,
            next_publish_revision,
        )

        a = int(time.time()) + 10_000
        b = a + 5
        db = self.data / ".index" / "catalog.db"
        _write_min_catalog_db(db, [("A", a), ("B", b)])
        (self.runtime / "published-updates.min.json").write_text(
            json.dumps([{"name": "C", "publish_revision": b - 1}]),
            encoding="utf-8",
        )
        (self.runtime / "recent-catalog.min.json").write_text(
            json.dumps([{"name": "D", "publish_revision": a + 1}]),
            encoding="utf-8",
        )
        hwm = authoritative_publish_revision_high_water(catalog_db=db, force=True)
        self.assertEqual(hwm, b)
        nxt = next_publish_revision(catalog_db=db)
        self.assertGreater(nxt, hwm)


if __name__ == "__main__":
    unittest.main()
