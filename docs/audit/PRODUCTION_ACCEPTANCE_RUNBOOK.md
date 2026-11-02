# Production Deploy + Acceptance Runbook (Reliability Increments)

**Status: NOT production-proven.** Local tests pass (25/25), but no live service has
run this code. Deploy only after rollback capability and a persistent-volume backup
are confirmed, then run the live acceptance gates below.

Commits under test:
- `ad16061` — durable SQLite enrichment queue + auto-reconcile + aged-out recovery
- `77208f7` — hardening (readiness fail-closed, eligibility, starvation, discrepancy tracking) + homepage parity + staging test
- `1bf8312` — weighted-fair scheduling + aging promotion

---

## Step 0 — Pre-deploy: backup + rollback (mandatory)

In the Easypanel application terminal:

```sh
# 0a. Capture the rollback target (current deployed commit)
git rev-parse HEAD | tee /tmp/rollback_sha.txt

# 0b. Back up the persistent runtime volume (queue db, catalog index, overlays)
echo "SNE_RUNTIME_DIR=${SNE_RUNTIME_DIR:-unset}"
echo "SNE_DATA_DIR=${SNE_DATA_DIR:-unset}"
TS=$(date +%Y%m%dT%H%M%S)
mkdir -p /data/backups/$TS
cp -a "${SNE_RUNTIME_DIR:-/data/runtime}/enrich_queue.db"* /data/backups/$TS/ 2>/dev/null || true
cp -a "${SNE_RUNTIME_DIR:-/data/runtime}/catalog-stats.json" /data/backups/$TS/ 2>/dev/null || true
cp -a "${SNE_DATA_DIR:-/data/astrocats}/.index/catalog.db"* /data/backups/$TS/ 2>/dev/null || true
ls -la /data/backups/$TS/
```

**Rollback plan:** redeploy the commit in `/tmp/rollback_sha.txt`. The new code is
additive-only (new `enrich_queue.db`, new `catalog-stats.json`, new
`reconciliation_discrepancies` table, new `priority` column) — no destructive
schema change — so rolling back does not corrupt prior state. The queue's
`ALTER TABLE ... ADD COLUMN priority` is guarded and idempotent.

---

## Step 1 — Verify which volume the audit saw (P0B provenance)

```sh
echo "SNE_DATA_DIR=${SNE_DATA_DIR:-unset}"
echo "SNE_RUNTIME_DIR=${SNE_RUNTIME_DIR:-unset}"
pwd
find /data/astrocats -type f -name '*.json' | wc -l
df -h /data
```

The audit's **99,676** files came from the **staging restore corpus**
(`staging/astrocats-restore`), **not** this production volume. This `find` count is
a sanity check on the real production corpus; reconcile the two before treating
P0B (full archive restore) as installed.

---

## Step 2 — Deploy

Redeploy the service at `1bf8312` (or merge to your release branch first).
Confirm the process starts and the durable queue initialises:

```sh
# Expect: durable-sqlite backend, enrich_subsystem.ready = true
curl -s -H "Authorization: Bearer $SNE_HEALTH_AUTH" https://sne.space/api/internal/health \
  | python3 -c "import sys,json; h=json.load(sys.stdin); print(json.dumps(h.get('enrich_subsystem'),indent=2)); print(json.dumps(h.get('enrich_queue'),indent=2))"
```

If `enrich_subsystem.ready` is `false`, the durable store is unavailable — **do not
proceed**; the service is correctly refusing to lose jobs. Fix the runtime volume
first.

---

## Step 3 — Run the acceptance harness

```sh
# In the Easypanel terminal (sees the real persistent volume) or against the public URL:
python3 scripts/production_acceptance.py --base https://sne.space --token "$SNE_HEALTH_AUTH"
```

It prints a JSON scorecard and exits non-zero if any checkable gate fails.

### Live gates to confirm (no manual intervention)

| Gate | What proves it | How to observe |
|------|----------------|----------------|
| **G1** queue intake | new transient present in `enrich_queue.db` | `enrich_queue.queued/leased` increments after a new TNS discovery |
| **G2** live enrichment | TNS/ALeRCE/WISeREP data lands in event JSON | the event's `photometry`/`spectra` arrays grow |
| **G3** publication → API | searchable via `/api/transients` | `?q=<name>` returns the event with the new obs |
| **G4** restart survival | pending+done preserved, work resumes | run harness before/after an Easypanel restart; counts preserved, pending drains |
| **G5** durable retry | 429/transient → `retry` w/ backoff, not lost/false-acked | `enrich_queue.retry` rises then drains; `failed` stays 0 for transient errors |
| **G6** stats parity | homepage == `/api/transients` | `catalog_stats_total == transients_total` in the harness |
| **G7** readiness/discrepancy | failures + open mismatches reported | `enrich_subsystem.ready`, `reconciliation_discrepancies` open count |
| **G8** no starvation | both fresh and aged drain under sustained traffic | `oldest_pending_age_s` bounded; neither `queued` class grows unbounded |

**G8 procedure (sustained traffic):** while normal TNS discovery is arriving, also
enqueue a batch of aged-out events (`python3 -m ingest.aged_out_recovery`), then
watch `enrich_queue` over ~15–30 min. Both the fresh stream and the aged backlog
must move to `done`; `oldest_pending_age_s` must stay bounded.

---

## Step 4 — Verdict

- **PASS** = all checkable gates green on the live service. Only then treat
  automatic durable ingestion/enrichment as production-proven.
- **INCOMPLETE / FAIL** = capture the scorecard, the relevant `enrich_queue` and
  `reconciliation_discrepancies` rows, and the service logs; do not declare success.

## Milestone truth table (keep current)

| Milestone | Status |
|-----------|--------|
| Correct publication of existing event JSON | Demonstrated in production (manual reconcile) |
| Automatic, durable ingestion and enrichment | **Implemented + hardened locally; awaiting live acceptance** |
| Full historical archive restoration (P0B) | Staged; production corpus count unverified (see Step 1) |

## AdSense note
These reliability changes improve completeness/accessibility/consistency of the
scientific records. They do **not**, by themselves, resolve Google's publisher
content-policy concerns — that is a separate evaluation.
