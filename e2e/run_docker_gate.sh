#!/usr/bin/env bash
# Full Docker Compose E2E gate. Does NOT deploy or touch production volumes.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PROJECT=sne-e2e
COMPOSE=(docker compose -p "$PROJECT" -f docker-compose.e2e.yml)
ART="$ROOT/e2e/artifacts"
mkdir -p "$ART"
export SNE_E2E_ARTIFACTS="$ART"

echo "=== Docker E2E gate starting $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
docker version | tee "$ART/docker_version.txt"

# Fresh named volumes for this gate (destroy prior e2e volumes only)
${COMPOSE[@]} down -v --remove-orphans 2>/dev/null || true
START_BUILD=$(date +%s)
${COMPOSE[@]} build sne-e2e 2>&1 | tee "$ART/docker_build.log" | tail -20
END_BUILD=$(date +%s)
echo "build_seconds=$((END_BUILD-START_BUILD))" | tee "$ART/docker_timing.txt"

START_UP=$(date +%s)
${COMPOSE[@]} up -d mock-providers sne-e2e
# Wait healthy
for i in $(seq 1 60); do
  if ${COMPOSE[@]} ps | grep -q healthy; then
    st=$(curl -fsS http://127.0.0.1:18081/healthz || true)
    if echo "$st" | grep -q ok; then
      echo "sne-e2e healthy after ${i} attempts"
      break
    fi
  fi
  sleep 2
done
END_UP=$(date +%s)
echo "startup_to_healthz_s=$((END_UP-START_UP))" | tee -a "$ART/docker_timing.txt"
curl -fsS http://127.0.0.1:18081/healthz | tee "$ART/healthz_initial.json"
echo

# Seed empty catalog index if entrypoint left no .index (or use baked)
${COMPOSE[@]} exec -T sne-e2e python3 - <<'PY' || true
from pathlib import Path
import json, os
data = Path(os.environ["SNE_DATA_DIR"])
idx = data / ".index"
idx.mkdir(parents=True, exist_ok=True)
cat = data / "catalog.min.json"
if not cat.is_file():
    cat.write_text("[]", encoding="utf-8")
db = idx / "catalog.db"
if not db.is_file():
    from serve.catalog_store import CatalogStore
    CatalogStore(db).build([cat], force=True)
    print("seeded", db)
else:
    print("existing", db, "size", db.stat().st_size)
PY

# Run e2e-runner inside compose network (do not abort gate on FAIL — still do recreate checks)
set +e
${COMPOSE[@]} run --rm e2e-runner 2>&1 | tee "$ART/docker_e2e_runner.log"
RUNNER_CODE=${PIPESTATUS[0]}
set -e
echo "e2e-runner_exit=$RUNNER_CODE" | tee -a "$ART/docker_timing.txt"

# Capture pre-recreate state
curl -fsS http://127.0.0.1:18081/healthz > "$ART/healthz_before_recreate.json" || true
${COMPOSE[@]} exec -T sne-e2e sh -c 'ls -la /data/sne-runtime/publication_state.json /data/sne-runtime/published-updates.min.json 2>/dev/null; ls /data/astrocats/astrocats/supernovae/output/sne-2025-2029/AT2025e2everify.json 2>/dev/null; cat /data/sne-runtime/publication_state.json' > "$ART/volume_state_before_recreate.txt" || true

# Destroy and recreate app container; KEEP volumes
echo "=== Recreate sne-e2e container (volumes retained) ==="
${COMPOSE[@]} up -d --force-recreate --no-deps sne-e2e
for i in $(seq 1 40); do
  if curl -fsS http://127.0.0.1:18081/healthz >/dev/null 2>&1; then
    echo "recreated healthy after ${i}"
    break
  fi
  sleep 2
done
curl -fsS http://127.0.0.1:18081/healthz | tee "$ART/healthz_after_recreate.json"
${COMPOSE[@]} exec -T sne-e2e sh -c 'cat /data/sne-runtime/publication_state.json; test -f /data/astrocats/astrocats/supernovae/output/sne-2025-2029/AT2025e2everify.json && echo EVENT_OK' > "$ART/volume_state_after_recreate.txt" || true

# Consistency after recreate
python3 - <<'PY' | tee "$ART/recreate_consistency.json"
import json, urllib.request, os
base="http://127.0.0.1:18081"
ev="AT2025e2everify"
def get(u):
    try:
        with urllib.request.urlopen(u, timeout=20) as r:
            return r.status, r.read()
    except Exception as e:
        return 0, str(e).encode()
hs, hb = get(base+"/healthz")
ps, pb = get(base+f"/{ev}")
if ps==404: ps, pb = get(base+f"/{ev}.html")
cs, cb = get(base+"/catalog.json")
out={
  "healthz": hs,
  "event_page": ps,
  "event_mentions": ev.encode() in pb or b"e2everify" in pb,
  "catalog": cs,
  "catalog_mentions": ev.encode() in cb or b"e2everify" in cb,
}
print(json.dumps(out, indent=2))
open(os.environ.get("SNE_E2E_ARTIFACTS","e2e/artifacts")+"/recreate_consistency.json","w").write(json.dumps(out, indent=2))
PY

# Memory / stats snapshot
docker stats --no-stream --format '{{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}' | tee "$ART/docker_stats.txt" || true
${COMPOSE[@]} ps | tee "$ART/docker_ps.txt"

# Cold-cache catalog store bootstrap timing inside container (may use seeded/small or full baked)
${COMPOSE[@]} exec -T sne-e2e python3 - <<'PY' | tee "$ART/catalog_bootstrap.txt"
import os, time, resource, json
from pathlib import Path
from serve.catalog_store import CatalogStore
data = Path(os.environ["SNE_DATA_DIR"])
src = data / "catalog.min.json"
if not src.is_file():
    print("no catalog.min.json")
else:
    db = data / ".index" / "catalog_e2e_bootstrap.db"
    if db.exists():
        db.unlink()
    rss0 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    t0 = time.time()
    store = CatalogStore(db)
    store.build([src], force=True)
    dt = time.time() - t0
    rss1 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # ru_maxrss is KB on Linux, bytes on macOS — report raw + note
    print(json.dumps({
        "events": store.count(),
        "build_s": round(dt, 2),
        "db_bytes": db.stat().st_size if db.is_file() else 0,
        "ru_maxrss_raw": rss1,
        "ru_maxrss_delta": rss1 - rss0,
        "platform_note": "ru_maxrss is KB on Linux",
    }, indent=2))
PY

echo "=== Docker E2E runner exit code: $RUNNER_CODE ==="
# Keep stack up for inspection; comment next line to retain
# ${COMPOSE[@]} down
exit "$RUNNER_CODE"
