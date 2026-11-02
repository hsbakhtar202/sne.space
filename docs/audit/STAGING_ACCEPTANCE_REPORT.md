# Staging Acceptance Report — 2026-11-01 (rev 3)

**Scope:** P0A high-water-mark revision recovery; P0B case-collision dual preservation (Linux), malformed-record handling, merge dry-run with exact-name collision source.  
**Not claimed:** production remediation complete. Live API/JSON/archive still unreconciled on `https://sne.space`.

Original audit evidence preserved under `docs/audit/` and `prod_truth_evidence/`. Staging artifacts only under `staging/astrocats-restore/` (gitignored).

---

## Gate status (this revision)

| Gate | Result | Decision |
| --- | --- | --- |
| Rotate `SNE_HEALTH_AUTH` on production | **FAIL** — SSH denied; old secret still **200** | **P0A production deploy blocked** |
| P0A tests incl. high-water mark | **15/15 PASS** (local) | Code ready pending ops rotation + live smoke |
| P0A live agub + 10 events + restart + rollback | **NOT RUN** | Blocked on deploy |
| P0B 33 collisions preserved (Linux) | **PASS** — 66 files materialized; 33/33 groups verified | Staging-only |
| P0B two malformed records | **Flagged** — no invented timestamps | Excluded from time-series inference |
| P0B merge dry-run (local clone + collision source) | **PASS** — 99,623 add + 66 materialized; 0 held | Not a production-volume prediction |
| P0B merge vs **production volume clone** | **NOT RUN** — no host access | **Required before any production restore** |
| Enrichment queue | **UNFIXED** | Next ops priority after P0A |

---

## 1. Security

| Check | Result |
| --- | --- |
| Hardcoded ops password removed | **PASS** |
| Old credential fails on production | **FAIL** — still **200** at this revision |
| New credential verified | **NOT RUN** — no host/orchestrator access |

**Immediate ops action:** rotate `SNE_HEALTH_AUTH`; confirm old → **401**; do not place secrets in query strings.

---

## 2. P0A — publication / merge / high-water mark

### Code changes (rev 3)
- `next_publish_revision()` now requires:
  1. `cur + 1` (durable sequence file)
  2. `int(time.time())` (legacy numeric space)
  3. `authoritative_high_water + 1` from CatalogStore `meta_json.publish_revision`, `published-updates.min.json`, and `recent-catalog.min.json`
- Overlay/recent JSON re-read each allocation; CatalogStore `MAX()` cached briefly for batch throughput. Missing/reset sequence file forces a fresh store rescan.

### Automated tests (isolated temp dirs)

| Suite | Result |
| --- | --- |
| `test_publish_revision_serialized` | **2/2 PASS** |
| `test_api_recent_merge_p0a` | **3/3 PASS** |
| `test_p0a_staging_acceptance` | **3/3 PASS** |
| `test_p0a_rollback_compat` | **4/4 PASS** |
| `test_publish_revision_high_water` (seq absent w/ store future rev; seq reset below overlay; explicit > max committed) | **3/3 PASS** |

**Combined: 15/15 PASS.**

### Rollback compatibility (failed check preserved)

| Scenario | Result |
| --- | --- |
| Naive rollback to pre-P0A image (prefer-recent merge) | **FAIL by design** — stub wins again |

Deploy requires a **merge-aware rollback image**, not a tag-only revert.

### Production deploy checklist (still blocked)
1. Rotate credential; old → 401.
2. Deploy P0A-only image.
3. Live: agub + ≥10 prior `FAIL_phot_api=0` events; production JSON det == API `phot`.
4. Restart; no stale recent flash.
5. Rollback drill with merge-aware tag against new runtime state.

---

## 3. P0B — staging only (production archive untouched)

### 3.1 Case-collision resolution (33 groups)

**Tool:** `python3 -m ingest.astrocats_collision_materialize`  
**Evidence:** `COLLISION_MATERIALIZE_REPORT.json`

| Metric | Value |
| --- | ---: |
| Groups | **33** |
| Kind | **33 × distinct_objects** (different blob SHA256 — not duplicates) |
| Linux case-sensitive volume | `sne-p0b-case-sensitive` |
| Files written | **66** (both casings per group) |
| Groups verified (both filenames listed) | **33/33** |
| Host export (case-escaped) | `collision-materialize/exported/` + `manifest.json` |

Identity policy: exact filename stems are object identity here; no casefold merge. Alias analysis (e.g. whether `asassn-15bd` is an alias of a survey ID) is **not** auto-inferred — both files are preserved for astronomical review.

### 3.2 Malformed records (2)

**Tool:** `python3 -m ingest.astrocats_malformed_photometry`  
**Evidence:** `MALFORMED_PHOTOMETRY_REPORT.json`

| Record | Issue | Action |
| --- | --- | --- |
| `MLS180112:023607+270428` | `phot[0]` missing `time` | Preserved; flagged; exclude from time-series |
| `MLS190104:122254+341818` | `phot[0]` missing `time` | Same |

No timestamps invented. Structural audit ≠ scientific measurement audit.

### 3.3 Merge dry-run (staging clone + collision source)

**Tool:** `python3 -m ingest.astrocats_staging_merge --collision-source …`  
**Evidence:** `MERGE_DRY_RUN_REPORT.json`  
**Target:** local laptop event clone (2,718 files) — **not production volume**.

| Metric | Value |
| --- | ---: |
| Before | 2,718 |
| After (projected) | 102,341 |
| Add-only | 99,623 |
| Case collisions materialized (both exact names) | **66** |
| Case collisions held | **0** |
| Fingerprint conflicts | 0 |
| Live production modified | **No** |

### 3.4 Still required for production authorization

1. Consistent production-volume snapshot/clone (SSH/host access) — **NOT OBTAINED**.
2. Re-run identity + merge dry-run against that production clone.
3. Before/after reconciliation: exact additions, conflicts, skips, valid phot/spec counts, expected `X-Catalog-Stub` reduction.
4. CatalogStore rebuild verification: newer published/enriched rows must not be discarded.

---

## 4. Production deployment / rollback plan (unchanged shape)

### Phase A — P0A only (blocked on credential rotation)
1. Rotate `SNE_HEALTH_AUTH`.
2. Deploy P0A; retain merge-aware rollback tag.
3. Live acceptance as §2 checklist.

### Phase B — P0B (staging verification continues)
1. Production volume clone → dry-run → review.
2. Snapshot → apply → CatalogStore rebuild → reconcile.
3. Rollback = volume snapshot.

**Do not** combine A and B.

### Strategic (post-P0A)
Repair enrichment-queue durability (durable retry, drop metrics) before nonessential UI work. Then enforce the invariant: advertised observations == retrievable persisted observations across JSON, CatalogStore, API, and downloads.

---

## 5. Explicit non-claims

- Production API defects remain until Phase A deploys.
- Production historical archive is **not** restored.
- Production-volume merge dry-run has **not** been executed.
- 198/200 structural sample pass does not establish 99% measurement accuracy.
- Old credential still works; not rotated.
- Enrichment queue still drops work.

---

## 6. Artifact index

| Artifact | Path |
| --- | --- |
| This report | `docs/audit/STAGING_ACCEPTANCE_REPORT.md` |
| Status mirror | `docs/audit/P0_REMEDIATION_STATUS.md` |
| Staging sync | `staging/astrocats-restore/STAGING_SYNC_REPORT.json` |
| Identity audit | `staging/astrocats-restore/IDENTITY_AUDIT_REPORT.json` |
| Collision materialize | `staging/astrocats-restore/COLLISION_MATERIALIZE_REPORT.json` |
| Malformed records | `staging/astrocats-restore/MALFORMED_PHOTOMETRY_REPORT.json` |
| Merge dry-run | `staging/astrocats-restore/MERGE_DRY_RUN_REPORT.json` |
