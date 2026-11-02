"""P0A: recent-catalog stubs must not hide CatalogStore photometry.

Regression for production AT2026agub-class failures where event JSON and
CatalogStore held detections but /api/transients page-1 reported phot=0
because the merge preferred a stale recent-catalog row.
"""
from __future__ import annotations

import unittest
import unittest.mock

from serve import catalog_engine as ce


class TestRecentMergeProvenance(unittest.TestCase):
    def test_unrevisioned_recent_stub_loses_to_store(self) -> None:
        store_result = {
            "total": 1,
            "page": 1,
            "limit": 50,
            "pages": 1,
            "has_next": False,
            "has_prev": False,
            "items": [
                {
                    "name": "AT2026agub",
                    "aliases": [],
                    "type": "unclassified",
                    "type_badge": "badge-other",
                    "date": "2026/10/25",
                    "age": "6d ago",
                    "mag": 19.46,
                    "z": None,
                    "ra": "01:52:22.081",
                    "dec": "+35:47:23.75",
                    "host": "—",
                    "disc": "Fritz",
                    "spec": 0,
                    "phot": 1,
                    "search_blob": "at2026agub",
                    "publish_revision": 100.0,
                }
            ],
        }
        recent = [
            {
                "name": "AT2026agub",
                "aliases": [],
                "type": "unclassified",
                "type_badge": "badge-other",
                "date": "2026/10/25",
                "age": "6d ago",
                "mag": 19.46,
                "z": None,
                "ra": "01:52:22.081",
                "dec": "+35:47:23.75",
                "host": "—",
                "disc": "Fritz",
                "spec": 0,
                "phot": 0,
                "search_blob": "at2026agub",
                # no publish_revision → stale stub
            }
        ]
        with unittest.mock.patch.object(ce, "_load_recent_query_items", return_value=recent):
            out = ce._merge_recent_into_query_result(store_result, sort="discoverdate", order="desc")
        hit = next(i for i in out["items"] if i["name"] == "AT2026agub")
        self.assertEqual(hit["phot"], 1)

    def test_newer_revision_may_lower_phot_counts(self) -> None:
        """Counts are not a versioning system — a correction can reduce phot."""
        store_result = {
            "total": 1,
            "page": 1,
            "limit": 50,
            "pages": 1,
            "has_next": False,
            "has_prev": False,
            "items": [
                {
                    "name": "AT2026fix",
                    "aliases": [],
                    "type": "unclassified",
                    "type_badge": "badge-other",
                    "date": "2026/10/01",
                    "age": "30d ago",
                    "mag": 18.0,
                    "z": None,
                    "ra": "01:00:00",
                    "dec": "+00:00:00",
                    "host": "—",
                    "disc": "X",
                    "spec": 0,
                    "phot": 10,
                    "search_blob": "at2026fix",
                    "publish_revision": 50.0,
                }
            ],
        }
        recent = [
            {
                "name": "AT2026fix",
                "aliases": [],
                "type": "unclassified",
                "type_badge": "badge-other",
                "date": "2026/10/01",
                "age": "30d ago",
                "mag": 18.0,
                "z": None,
                "ra": "01:00:00",
                "dec": "+00:00:00",
                "host": "—",
                "disc": "X",
                "spec": 0,
                "phot": 9,
                "search_blob": "at2026fix",
                "publish_revision": 60.0,
            }
        ]
        with unittest.mock.patch.object(ce, "_load_recent_query_items", return_value=recent):
            out = ce._merge_recent_into_query_result(store_result, sort="discoverdate", order="desc")
        hit = next(i for i in out["items"] if i["name"] == "AT2026fix")
        self.assertEqual(hit["phot"], 9)

    def test_event_to_catalog_item_stamps_revision_and_limits(self) -> None:
        from ingest.catalog_publish import event_to_catalog_item

        meta = {
            "discoverdate": [{"value": "2026/10/25"}],
            "photometry": [
                {"time": "61334.0", "magnitude": "20.2", "upperlimit": True, "kind": "non_detection"},
                {"time": "61338.0", "magnitude": "19.46", "upperlimit": False},
            ],
        }
        item = event_to_catalog_item("AT2026agub", meta)
        self.assertEqual(item["photolink"], "1,1")
        self.assertIn("publish_revision", item)
        self.assertGreater(float(item["publish_revision"]), 0)


if __name__ == "__main__":
    unittest.main()
