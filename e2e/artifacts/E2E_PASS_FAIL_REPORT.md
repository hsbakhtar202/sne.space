# sne.space E2E gate: **PASS**

- Generated: `2026-10-28T05:37:18.266566+00:00`
- Base URL: `http://sne-e2e:8080`
- Fixture event: `AT2025e2everify`
- Score: 67/67 passed

## Results

- **PASS** `stack healthz` — {"status": "ok", "uptime_seconds": 40.5, "revision": "e2e-local"}
- **PASS** `A scheduler pull_recent ran` — returned=1
- **PASS** `A event JSON persisted` — /data/astrocats/astrocats/supernovae/output/sne-2025-2029/AT2025e2everify.json
- **PASS** `A has claimedtype` — [{'value': 'Ia', 'source': '1'}]
- **PASS** `A photometry detections from ALeRCE` — dets=4 lims=1
- **PASS** `A no duplicate candids` — 
- **PASS** `A publication_state published` — {'error': None, 'fingerprint': {'mtime_ns': 1793165808992832002, 'path': '/data/astrocats/astrocats/supernovae/output/sne-2025-2029/AT2025e2everify.json', 'sha1': 'f4b0316d6275d9b4ebe89e48120fc6d177c72042', 'size': 4188}, 'generation': 52, 'ingest_status': 'committed', 'ingested_at': 1793165809.0827703, 'name': 'AT2025e2everify', 'publish_details': {'upserted': 1}, 'publish_status': 'published', 'published_at': 1793165809.1369216, 'updated_at': 1793165809.136989}
- **PASS** `A recent-events contains event` — 
- **PASS** `A overlay/recent-catalog contains event` — 
- **PASS** `A homepage HTTP 200` — 200
- **PASS** `A homepage lists event` — 
- **PASS** `A catalog HTTP 200` — 200
- **PASS** `A catalog lists event` — 
- **PASS** `A event page HTTP 200` — status=200 ttfb_ms=4.7
- **PASS** `A event page shows type/photometry` — 
- **PASS** `A publication lag within 60s of commit` — {'provider_to_file_s': 1.3, 'file_to_publish_s': 0.0, 'provider_to_ui_s': 1.3, 'within_60s_of_commit': True}
- **PASS** `B second pull_recent ran` — returned=1
- **PASS** `B no candid duplicates after re-enrich` — n=3
- **PASS** `B photometry not wiped` — before=5 after=5
- **PASS** `B upper limits retained as non-detections` — lims=1
- **PASS** `B event page still 200` — 200
- **PASS** `C pull after classification fixture` — returned=1
- **PASS** `C claimedtype updated to SN II` — II
- **PASS** `C claimedtype is II-family` — II
- **PASS** `C alias list present` — ['2025e2everify', 'AT2025e2ealias', 'ZTF25e2everify', 'AT2025e2everify', 'SN2025e2everify', 'AT 2025e2everify']
- **PASS** `C alias AT2025e2ealias resolves` — ['2025e2everify', 'AT2025e2ealias', 'ZTF25e2everify', 'AT2025e2everify', 'SN2025e2everify', 'AT 2025e2everify']
- **PASS** `C event page HTTP 200` — 200
- **PASS** `C event page shows II` — 
- **PASS** `C homepage still serves` — 
- **PASS** `C catalog still serves` — 
- **PASS** `C catalog lists II for event` — 
- **PASS** `F 429 then recover returns rows` — n=1 elapsed=5.0s
- **PASS** `F pending detectable` — ['AT2025e2everify']
- **PASS** `F recover_pending republishes` — {'items': 1, 'overlay_path': '/data/sne-runtime/published-updates.min.json', 'upserted': 1, 'overlay_size': 1, 'published_names': ['AT2025e2everify'], 'state': 'published', 'recovered': 1}
- **PASS** `F discovery priority held during ingest` — 
- **PASS** `F backfill waited for discovery` — waited=2.02s
- **PASS** `F failed publish remains explicit` — failed
- **PASS** `T crash-at-publishing raises` — SNE_PUBLISH_CRASH_AFTER=publishing
- **PASS** `T after publishing-crash status is publishing/pending/failed` — publishing
- **PASS** `T after publishing-crash not falsely published` — 
- **PASS** `T recover after publishing-crash → published` — {'items': 1, 'overlay_path': '/data/sne-runtime/published-updates.min.json', 'upserted': 1, 'overlay_size': 1, 'published_names': ['AT2025e2everify'], 'state': 'published', 'recovered': 1}
- **PASS** `T sqlite-fail returns failed state` — injected SQLite/catalog publication failure
- **PASS** `T sqlite-fail leaves publish_status=failed` — failed
- **PASS** `T sqlite-fail does not claim published` — 
- **PASS** `T event JSON intact after sqlite-fail` — 
- **PASS** `T automatic retry after sqlite-fail → published` — {'items': 1, 'overlay_path': '/data/sne-runtime/published-updates.min.json', 'upserted': 1, 'overlay_size': 1, 'published_names': ['AT2025e2everify'], 'state': 'published', 'recovered': 1}
- **PASS** `T crash-at-pending raises` — SNE_PUBLISH_CRASH_AFTER=pending
- **PASS** `T pending marker durable after crash` — pending
- **PASS** `T recover after pending-crash` — {'error': None, 'fingerprint': {'mtime_ns': 1793165813197832004, 'path': '/data/astrocats/astrocats/supernovae/output/sne-2025-2029/AT2025e2everify.json', 'sha1': '39bec0700f5dcedf8cd19612e9e961eaf4829477', 'size': 4262}, 'generation': 66, 'ingest_status': 'committed', 'ingested_at': 1793165822.7390053, 'name': 'AT2025e2everify', 'publish_details': {'upserted': 1}, 'publish_status': 'published', 'published_at': 1793165822.8320138, 'updated_at': 1793165822.8320813}
- **PASS** `S pull with spectra enabled` — returned=1
- **PASS** `S spectra ingested from fixture` — n_spectra=1
- **PASS** `S still published after spectra enrich` — published
- **PASS** `S pull survives spectra provider failure` — returned=1
- **PASS** `S photometry present despite spectra failure` — n_photo=5
- **PASS** `S publication not blocked by spectra failure` — published
- **PASS** `I test_no_fabrication` —  m_current equals fitted value: got 16.2
  [PASS] event fit: magnitude_kind is event_fit_predicted: got 'event_fit_predicted'
  [PASS] ancient Ia: m_current is None (past 300d domain): got None t_rest=5522.6
  [PASS] ancient Ia: notice states no reliable current brightness estimate
  [PASS] 1-point stub needs enrich
  [PASS] empty photo needs enrich
  [PASS] rich multi-epoch with spectra does not need enrich
  [PASS] multi-epoch without spectra still needs enrich

=== 48/48 passed, 0 failed ===

- **PASS** `I audit_data_integrity sample` — === DATA INTEGRITY AUDIT ===
events audited      : 50
parse errors        : 0
events with issues  : 0
events clean        : 50

RESULT: CLEAN - no fabricated claims detected

- **PASS** `I rendered page has no obvious fabrication phrases` — 200
- **PASS** `I quarantine policy importable / no silent promote required` — candidate_pts=0
- **PASS** `P cold-ish homepage samples recorded` — {'n': 5, 'p50': 0.6, 'p95': 0.7, 'max': 7.2}
- **PASS** `P homepage cached p95 < 300ms` — {'n': 30, 'p50': 0.6, 'p95': 0.7, 'max': 0.8}
- **PASS** `P event cached p95 < 500ms` — {'n': 20, 'p50': 1.4, 'p95': 1.7, 'max': 3.5}
- **PASS** `P catalog p95 recorded` — {'n': 15, 'p50': 13.9, 'p95': 20.8, 'max': 1704.4}
- **PASS** `P background publish during load` — 
- **PASS** `P 20 concurrent homepage during publish p95 < 2000ms` — {'n': 20, 'p50': 11.4, 'p95': 14.0, 'max': 14.2}
- **PASS** `P zero HTTP 5xx in sample` — [200, 200, 200, 200]
- **PASS** `P healthz revision captured` — {'status': 'ok', 'uptime_seconds': 70.9, 'revision': 'e2e-local'}

## Unverified assumptions

- CDN / TLS / reverse-proxy production edge not simulated in Compose
- Browser client caching not measured (server TTFB only)
- Historical 2025 backfill corpus is independent of this E2E fixture volume
