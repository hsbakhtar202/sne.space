#!/usr/bin/env python3
"""Catalog table must surface host, redshift, and magnitude from event metadata."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestEventToCatalogItemFields(unittest.TestCase):
    def test_includes_redshift_host_and_mag_with_discovery_fallback(self) -> None:
        from ingest.catalog_publish import event_to_catalog_item, publish_catalog_items
        from serve.catalog_store import CatalogStore

        meta = {
            "discoverdate": [{"value": "2026/10/05"}],
            "claimedtype": [{"value": "Ia-91T-like"}],
            "ra": [{"value": "03:16:41.828"}],
            "dec": [{"value": "+80:48:09.12"}],
            "redshift": [{"value": "0.0077", "kind": "spectroscopic"}],
            "host": [{"value": "NGC 1184"}],
            # Peak not established — only discovery magnitude present.
            "discoverymag": [{"value": "19.08", "kind": "discovery", "band": "wide-ATLAS"}],
            "photometry": [
                {
                    "time": "61318.11693",
                    "magnitude": "19.08",
                    "band": "wide-ATLAS",
                    "u_time": "MJD",
                }
            ],
            "spectra": [{"data": [[1, 2]]}],
        }
        item = event_to_catalog_item("SN2026aeiv", meta)
        self.assertEqual(item["redshift"][0]["value"], "0.0077")
        self.assertEqual(item["host"][0]["value"], "NGC 1184")
        self.assertEqual(item["maxappmag"][0]["value"], "19.08")
        self.assertEqual(item["maxappmag"][0].get("kind"), "discovery")
        self.assertTrue(str(item["photolink"]).startswith("1"))

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            db = td_path / "catalog.db"
            seed = td_path / "seed.min.json"
            seed.write_text("[]", encoding="utf-8")
            # empty array build may fail — seed with stub then upsert
            seed.write_text(
                json.dumps(
                    [
                        {
                            "name": "PLACEHOLDER",
                            "discoverdate": [{"value": "2000/01/01"}],
                            "claimedtype": [{"value": "Ia"}],
                            "photolink": "0,0",
                            "spectralink": "0",
                        }
                    ],
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            store = CatalogStore(db)
            self.assertTrue(store.build([seed], force=True))
            publish_catalog_items([item], catalog_db=db, write_overlay=False)
            store.load_existing()
            q = store.query(q="SN2026aeiv", limit=5)
            self.assertEqual(q["total"], 1)
            row = q["items"][0]
            self.assertEqual(row["name"], "SN2026aeiv")
            self.assertAlmostEqual(float(row["z"]), 0.0077, places=4)
            self.assertAlmostEqual(float(row["mag"]), 19.08, places=2)
            self.assertEqual(row["host"], "NGC 1184")


if __name__ == "__main__":
    unittest.main()
