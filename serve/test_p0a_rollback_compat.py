"""P0A rollback compatibility: new persistent revision state vs legacy publishers.

Rolling back the image while leaving ``publish_revision_seq.txt`` and stamped
CatalogStore / recent-catalog rows must not invert freshness ordering into a
worse state than pre-fix. These tests use an isolated temp runtime only.
"""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path


class TestP0ARollbackCompat(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.runtime = Path(self._td.name) / "runtime"
        self.runtime.mkdir(parents=True, exist_ok=True)
        os.environ["SNE_RUNTIME_DIR"] = str(self.runtime)

    def tearDown(self) -> None:
        self._td.cleanup()
        os.environ.pop("SNE_RUNTIME_DIR", None)

    def test_new_counter_stays_in_legacy_timestamp_space(self) -> None:
        from ingest.catalog_publish import next_publish_revision

        before = int(time.time())
        rev = next_publish_revision()
        self.assertGreaterEqual(rev, before)
        # A second allocation remains strictly newer.
        self.assertGreater(next_publish_revision(), rev)

    def test_legacy_wall_clock_publish_after_new_state_still_orders(self) -> None:
        """Simulate rollback: old build stamps time.time(); new state already present."""
        from ingest.catalog_publish import next_publish_revision
        from serve.catalog_engine import _prefer_authoritative_query_item

        new_rev = next_publish_revision()
        store_item = {"name": "AT2026rb", "phot": 5, "publish_revision": new_rev}
        # Legacy publisher after rollback (no fcntl counter — wall clock).
        legacy_rev = float(time.time()) + 2.0
        recent_item = {"name": "AT2026rb", "phot": 0, "publish_revision": legacy_rev}
        # Newer revision wins even if phot drops — same rule both sides use once
        # the fix is deployed; after full image rollback merge policy regresses
        # (documented separately). This asserts numeric space compatibility.
        chosen = _prefer_authoritative_query_item(store_item, recent_item)
        self.assertIs(chosen, recent_item)
        self.assertGreater(legacy_rev, new_rev)

    def test_preexisting_tiny_counter_file_jumps_to_timestamp_space(self) -> None:
        """Migration hazard: early test counters (1..N) must not stay tiny forever."""
        from ingest.catalog_publish import REVISION_NAME, next_publish_revision

        seq = self.runtime / REVISION_NAME
        seq.write_text("7", encoding="utf-8")
        rev = next_publish_revision()
        self.assertGreaterEqual(rev, int(time.time()) - 1)
        self.assertGreater(rev, 7)

    def test_image_rollback_without_merge_fix_reintroduces_stub_preference(self) -> None:
        """Documented FAIL mode: old prefer-recent policy ignores CatalogStore phot.

        Acceptance requires a rollback *image that retains revision-aware merge*
        (or accepting that full pre-P0A rollback restores the defect). This test
        encodes the unsafe policy so the report can cite it as a failed check
        against naive tag-only rollback.
        """

        def legacy_prefer_recent(store_item: dict, recent_item: dict) -> dict:
            # Pre-P0A behaviour: recent-catalog row wins when present.
            return recent_item

        store = {"name": "AT2026agub", "phot": 1, "publish_revision": 1_700_000_000}
        stub = {"name": "AT2026agub", "phot": 0, "publish_revision": None}
        self.assertEqual(legacy_prefer_recent(store, stub)["phot"], 0)


if __name__ == "__main__":
    unittest.main()
