"""Durable publish_revision must be a serialized sequence across workers."""
from __future__ import annotations

import concurrent.futures
import os
import tempfile
import unittest
from pathlib import Path


class TestSerializedPublishRevision(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.runtime = Path(self._td.name) / "runtime"
        self.runtime.mkdir(parents=True, exist_ok=True)
        os.environ["SNE_RUNTIME_DIR"] = str(self.runtime)

    def tearDown(self) -> None:
        self._td.cleanup()
        os.environ.pop("SNE_RUNTIME_DIR", None)

    def test_next_revision_is_strictly_increasing_under_concurrency(self) -> None:
        from ingest.catalog_publish import next_publish_revision

        n = 40
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            got = list(ex.map(lambda _: next_publish_revision(), range(n)))
        self.assertEqual(len(got), n)
        self.assertEqual(len(set(got)), n, "revisions must be unique under concurrency")
        ordered = sorted(got)
        self.assertEqual(ordered, list(range(ordered[0], ordered[0] + n)))

    def test_event_to_catalog_item_uses_serialized_revision(self) -> None:
        from ingest.catalog_publish import event_to_catalog_item, next_publish_revision

        a = next_publish_revision()
        item = event_to_catalog_item(
            "AT2026rev",
            {
                "discoverdate": [{"value": "2026/10/01"}],
                "photometry": [{"time": "60000", "magnitude": "18.0"}],
            },
        )
        b = next_publish_revision()
        self.assertGreater(item["publish_revision"], a)
        self.assertGreater(b, item["publish_revision"])


if __name__ == "__main__":
    unittest.main()
