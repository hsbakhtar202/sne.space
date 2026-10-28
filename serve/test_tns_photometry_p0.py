"""P0: TNS photometry ingestion + magnitude semantics (AT2026agub fixture)."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURE = ROOT / "e2e" / "fixtures" / "tns_photometry_AT2026agub_table.html"


class TestTnsPhotometryParse(unittest.TestCase):
    def test_fixture_exists(self) -> None:
        self.assertTrue(FIXTURE.is_file(), f"missing fixture {FIXTURE}")

    def test_parse_detections_and_limits(self) -> None:
        from ingest.tns_photometry import parse_tns_photometry_html

        html = FIXTURE.read_text(encoding="utf-8")
        rows = parse_tns_photometry_html(html)
        dets = [r for r in rows if not r.get("upperlimit")]
        lims = [r for r in rows if r.get("upperlimit")]
        self.assertEqual(len(dets), 1, f"expected 1 unique detection, got {len(dets)}: {dets}")
        self.assertEqual(len(lims), 1, f"expected 1 upper limit, got {len(lims)}")
        det = dets[0]
        self.assertAlmostEqual(float(det["magnitude"]), 19.4603, places=4)
        self.assertAlmostEqual(float(det["e_magnitude"]), 0.209386, places=4)
        self.assertEqual(det["band"], "r-ZTF")
        self.assertFalse(det.get("upperlimit"))
        lim = lims[0]
        self.assertAlmostEqual(float(lim["magnitude"]), 20.2546, places=4)
        self.assertTrue(lim.get("upperlimit"))
        self.assertEqual(lim.get("kind"), "non_detection")

    def test_dedupe_identical_tns_rows(self) -> None:
        from ingest.tns_photometry import parse_tns_photometry_html, photometry_merge

        html = FIXTURE.read_text(encoding="utf-8")
        rows = parse_tns_photometry_html(html)
        # Fixture HTML lists the same detection twice (IDs 629884/629885); merge must keep one.
        merged = photometry_merge([], rows)
        dets = [r for r in merged if not r.get("upperlimit")]
        self.assertEqual(len(dets), 1)
        self.assertEqual(sum(1 for r in merged if r.get("upperlimit")), 1)

    def test_merge_preserves_alerce_and_is_idempotent(self) -> None:
        from ingest.tns_photometry import parse_tns_photometry_html, photometry_merge

        existing = [
            {
                "time": "61338.40000",
                "magnitude": "19.50",
                "band": "g",
                "u_time": "MJD",
                "source": "A",
                "candid": "alerce-unique-1",
            }
        ]
        rows = parse_tns_photometry_html(FIXTURE.read_text(encoding="utf-8"))
        once = photometry_merge(existing, rows)
        twice = photometry_merge(once, rows)
        self.assertEqual(len(once), len(twice))
        self.assertTrue(any(p.get("candid") == "alerce-unique-1" for p in twice))
        self.assertEqual(sum(1 for p in twice if not p.get("upperlimit")), 2)


class TestAgubEndToEndSemantics(unittest.TestCase):
    def test_build_event_fetches_tns_photometry_when_alerce_empty(self) -> None:
        from ingest.tns import build_event_dict
        from ingest import tns_photometry

        html = FIXTURE.read_text(encoding="utf-8")

        def _fake_fetch(name: str, **kwargs):
            rows = tns_photometry.parse_tns_photometry_html(html)
            return {
                "status": "ok",
                "n_detections": sum(1 for r in rows if not r.get("upperlimit")),
                "n_limits": sum(1 for r in rows if r.get("upperlimit")),
                "rows": rows,
                "ztf_oid": "ZTF26accvezn",
                "source": "tns_html",
            }

        orig = tns_photometry.fetch_tns_photometry
        tns_photometry.fetch_tns_photometry = _fake_fetch  # type: ignore
        try:
            row = {
                "name_prefix": "AT",
                "name": "2026agub",
                "ra": "28.092005",
                "declination": "35.789931",
                "type": "",
                "redshift": "",
                "reporters": "Fritz",
                "reporting_group": "ZTF",
                "internal_names": "ZTF26accvezn",
                "Discovery_ADS_bibcode": "",
                "discoverydate": "2026-10-25 09:54:09",
                "discoverymag": "19.4603",
                "filter": "r-ZTF",
            }
            cname, event = build_event_dict(row, enrich_alerce=False, enrich_wiserep=False, enrich_tns_spectra=False)
            self.assertEqual(cname, "AT2026agub")
            body = event["AT2026agub"]
            ph = body.get("photometry") or []
            dets = [p for p in ph if not p.get("upperlimit")]
            lims = [p for p in ph if p.get("upperlimit")]
            self.assertEqual(len(dets), 1)
            self.assertEqual(len(lims), 1)
            self.assertAlmostEqual(float(dets[0]["magnitude"]), 19.4603, places=4)
            self.assertAlmostEqual(float(dets[0]["e_magnitude"]), 0.209386, places=4)
            self.assertAlmostEqual(float(lims[0]["magnitude"]), 20.2546, places=4)
            aliases = [a.get("value") for a in body.get("alias") or [] if isinstance(a, dict)]
            self.assertIn("ZTF26accvezn", aliases)
            cov = (body.get("photometry_ingest") or {}).get("tns") or {}
            self.assertEqual(cov.get("status"), "ok")
            # Discovery mag field may exist; fitted peak must not be claimed from one detection.
            self.assertTrue(body.get("discoverymag") or body.get("discovery_mag"))
            maxapp = body.get("maxappmag") or []
            if maxapp and isinstance(maxapp[0], dict):
                self.assertNotEqual(maxapp[0].get("kind"), "fitted_peak")
        finally:
            tns_photometry.fetch_tns_photometry = orig  # type: ignore

    def test_lifecycle_one_detection_peak_not_established(self) -> None:
        from serve.event_render import get_transient_lifecycle, render_pro_cockpit

        meta = {
            "name": "AT2026agub",
            "alias": [{"value": "AT2026agub"}, {"value": "ZTF26accvezn"}],
            "discoverdate": [{"value": "2026/10/25"}],
            "discoverymag": [{"value": "19.4603", "e_value": "0.209386", "band": "r-ZTF"}],
            "maxappmag": [{"value": "19.4603"}],  # orphan scalar — must not become fitted peak
            "ra": [{"value": "01:52:22.081"}],
            "dec": [{"value": "+35:47:23.75"}],
            "claimedtype": [{"value": "unclassified"}],
            "photometry": [
                {
                    "time": "61338.41260",
                    "magnitude": "19.4603",
                    "e_magnitude": "0.209386",
                    "band": "r-ZTF",
                    "u_time": "MJD",
                    "telescope": "P48_ZTF-Cam",
                    "source": "1",
                },
                {
                    "time": "61334.75944",
                    "magnitude": "20.2546",
                    "band": "r-ZTF",
                    "u_time": "MJD",
                    "telescope": "P48_ZTF-Cam",
                    "upperlimit": True,
                    "kind": "non_detection",
                    "source": "1",
                },
            ],
            "sources": [{"name": "Transient Name Server", "alias": "1"}],
        }
        lc = get_transient_lifecycle(copy.deepcopy(meta), claimedtype="unclassified", event_name="AT2026agub")
        self.assertFalse(lc.get("peak_confirmed"))
        self.assertEqual(lc.get("measured_points"), 1)
        html = render_pro_cockpit("AT2026agub", copy.deepcopy(meta), None, legacy_html_exists=False)
        low = html.lower()
        self.assertIn("discovery", low)
        self.assertNotIn("cataloged/observed peak", low)
        self.assertIn("not established", low)
        # Upper limit must appear as limit, not as a normal detection in plot data
        self.assertIn("20.2546", html)
        self.assertTrue(re.search(r'"uplim":\s*true', html, re.I))
        # Observations row distinguishes detections from upper limits
        self.assertTrue(re.search(r"1 detection", html, re.I))
        self.assertTrue(re.search(r"1 upper limit", html, re.I))


# late import for regex in assertion helper
import re  # noqa: E402


class TestPhotolinkHonesty(unittest.TestCase):
    def test_catalog_item_photolink_from_persisted_points(self) -> None:
        from ingest.catalog_publish import event_to_catalog_item

        meta = {
            "discoverdate": [{"value": "2026/10/25"}],
            "maxappmag": [{"value": "19.4603"}],
            "photometry": [],
            "claimedtype": [{"value": "unclassified"}],
        }
        item = event_to_catalog_item("AT2026agub", meta)
        self.assertEqual(item["photolink"], "0,0")

    def test_pull_recent_default_photo_count_is_zero(self) -> None:
        src = (ROOT / "ingest" / "pull_recent.py").read_text(encoding="utf-8")
        # Guard: the old default photo_count: 1 manufactured false availability.
        self.assertNotRegex(src, r'"photo_count":\s*1')


if __name__ == "__main__":
    unittest.main()
