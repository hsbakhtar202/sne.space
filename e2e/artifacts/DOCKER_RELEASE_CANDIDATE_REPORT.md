# sne.space Docker E2E — Release Candidate Report

**Status: READY FOR HUMAN DEPLOYMENT APPROVAL — NOT DEPLOYED**

Do not treat this as an automatic deploy. Production was not modified. Historical corpus was not synchronized.

## Gate result

| Item | Value |
|------|-------|
| Gate | **PASS (67/67)** inside `e2e-runner` container |
| Base URL | `http://sne-e2e:8080` (Compose network) / host `http://127.0.0.1:18081` |
| Fixture event | `AT2025e2everify` |
| Revision reported by `/healthz` | `e2e-local` |
| Image build | ~3 s (cached layers) |
| Startup → healthz | **8 s** |
| CatalogStore bootstrap | **110,222** events in **6.46 s**, DB **154.6 MB**, peak RSS delta ~**29 MB** |
| sne-e2e RSS (steady) | **163.4 MiB** / 1.465 GiB limit |
| mock-providers RSS | **14.2 MiB** |

Artifacts: `e2e/artifacts/` (`E2E_PASS_FAIL_REPORT.md/json`, `docker_e2e_runner_final.log`, `recreate_consistency.json`, `catalog_bootstrap.txt`, `docker_stats.txt`, `volume_state_*.txt`).

## Commands executed

```bash
# Docker daemon started; then:
docker compose -p sne-e2e -f docker-compose.e2e.yml build sne-e2e
docker compose -p sne-e2e -f docker-compose.e2e.yml up -d mock-providers sne-e2e
docker compose -p sne-e2e -f docker-compose.e2e.yml run --rm e2e-runner
# Volume retain recreate:
docker compose -p sne-e2e -f docker-compose.e2e.yml up -d --force-recreate --no-deps sne-e2e
# Full index bootstrap measured inside sne-e2e container
```

## What was verified (container-to-container)

### Automatic workflows
- **A New TNS event** — mock TNS → `pull_recent()` → durable JSON on volume → auto `catalog_publish` → homepage, catalog, event page agree (~1.3 s ingest lag). No manual publish.
- **B Enrichment** — re-pull merges ALeRCE dets/limits without candid duplicates.
- **C Reclassification** — fixture v2 → stored type **II**, aliases include `AT2025e2ealias`, event page + catalog show II.

### Publication durability
- Pending marker written **before** overlay/SQLite attempt (fsync’d `publication_state.json`).
- Crash after `publishing` → status stays `publishing`, **not** falsely `published` → `recover_pending` → `published`.
- Crash after `pending` → durable pending → recover → published.
- Injected SQLite failure after JSON commit → `failed`, JSON intact → automatic retry → published.
- UI may show prior published view while pending/failed; must not claim fully published for a partial generation.

### Spectra
- Fixture TNS object HTML + ascii ingested (`n_spectra=1`).
- Spectra HTTP 500 does **not** block photometry publication.

### Volume recreate
- Destroy/recreate `sne-e2e` container **keeping** `sne_e2e_data` + `sne_e2e_runtime`.
- After recreate: `publication_state=published`, event file present, healthz 200, event page 200 with II, catalog lists event (`recreate_consistency.json`).

### Scientific integrity (inside runner)
- `test_no_fabrication.py` 48/48
- `audit_data_integrity.py --limit 50` CLEAN
- Quarantine policy intact (no auto-promote)

### Performance (Compose HTTP, not TLS/CDN)

| Surface | p50 | p95 | max | Gate |
|---------|-----|-----|-----|------|
| Homepage cached | 0.6 ms | 0.7 ms | 0.8 ms | <300 ms PASS |
| Event cached | 1.4 ms | 1.7 ms | 3.5 ms | <500 ms PASS |
| Catalog | 13.9 ms | 20.8 ms | 1704 ms* | recorded |
| 20 concurrent during publish | 11.4 ms | 14.0 ms | 14.2 ms | <2 s PASS |
| HTTP 5xx | 0 | | | PASS |

\*Occasional cold catalog merge spike; warm p95 ~21 ms.

## Fixes applied during Docker gate (then retested)

1. Durable publication transitions + crash/SQLite injection hooks (`ingest/publication.py`)
2. Auto-publish already wired into `pull_recent`; pending before derived writes
3. TNS object/web base overrides for spectra fixtures
4. Python 3.11 f-string SyntaxError in `event_render.py` (nested quotes) — broke integrity imports in container
5. Workflow C forces spectra clear so reclassification re-enriches

## Remaining unverified (acceptable for RC approval, not silent)

- CDN / TLS / reverse-proxy production edge
- Browser client caching
- Host `sne-space` container (if running) was **not** used as the gate target; gate used `sne-e2e` project volumes only
- 2025 historical backfill continues on the developer host corpus independently

## Acceptance interpretation

Event JSON is the durable scientific record. SQLite + overlays are derived. Temporary prior-published UI during `pending`/`failed` is allowed; **silent divergence while claiming published is not**. Bounded lag + durable recovery demonstrated.

## Recommendation

**Release candidate: APPROVE for human deployment decision.**  
Do **not** auto-deploy. Do **not** sync historical 2025 corpus as part of this gate. If approved, deploy the application code/stability patch first; run production sync as a separate, reviewed step.
