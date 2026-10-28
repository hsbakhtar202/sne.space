#!/usr/bin/env bash
# Local production-equivalent E2E (isolated data dirs). Does not deploy.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ART="$ROOT/e2e/artifacts"
DATA="$ART/data"
RUNTIME="$ART/runtime"
mkdir -p "$ART" "$DATA/sne-2025-2029" "$RUNTIME" "$DATA/.index"

# Minimal empty catalog seed so CatalogStore can be built/upserted
python3 - <<PY
import json
from pathlib import Path
from serve.catalog_store import CatalogStore
seed = Path("$DATA") / "catalog.min.json"
seed.write_text("[]", encoding="utf-8")
db = Path("$DATA") / ".index" / "catalog.db"
if db.exists():
    db.unlink()
store = CatalogStore(db)
store.build([seed], force=True)
print("seeded catalog.db", db)
PY

# Mock providers
pkill -f 'e2e/mock_providers.py' 2>/dev/null || true
SNE_MOCK_PORT=18080 python3 "$ROOT/e2e/mock_providers.py" >"$ART/mock.log" 2>&1 &
MOCK_PID=$!
sleep 1

# Server
pkill -f 'serve/server.py' 2>/dev/null || true
export OSC_HOST=127.0.0.1 OSC_PORT=18081
export SNE_DATA_DIR="$DATA"
export SNE_RUNTIME_DIR="$RUNTIME"
export SNE_TNS_SEARCH_BASE="http://127.0.0.1:18080/search"
export SNE_ALERCE_BASE="http://127.0.0.1:18080/ztf/v1"
export SNE_TNS_POLL_SECONDS=3600
export SNE_SKIP_TNS_SPECTRA=1
export SNE_PAGE_CACHE_MB=32
cd "$ROOT"
python3 serve/server.py >"$ART/server.log" 2>&1 &
SRV_PID=$!

cleanup() {
  kill $SRV_PID $MOCK_PID 2>/dev/null || true
}
trap cleanup EXIT

for i in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:18081/healthz" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done
curl -fsS "http://127.0.0.1:18081/healthz"

export SNE_E2E_BASE="http://127.0.0.1:18081"
export SNE_MOCK_CONTROL="http://127.0.0.1:18080"
export SNE_E2E_ARTIFACTS="$ART"
python3 "$ROOT/e2e/run_e2e.py"
CODE=$?
exit $CODE
