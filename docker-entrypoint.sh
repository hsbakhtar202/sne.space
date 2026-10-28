#!/bin/sh
# Seed the durable data volume on first start.
#
# The image bakes an event corpus at $SNE_DATA_DIR/../... but docker-compose
# mounts a named volume over that path. Docker copies image content into a *new*
# named volume automatically only when the volume is empty and the mount is a
# directory -- but it does that before our process runs, so the baked copy is
# already there on first boot. The dangerous case is an *existing* volume with a
# different (older) corpus, which silently hides the image's newer files.
#
# This script makes that explicit: if the volume looks empty/uninitialised, copy
# the baked corpus in; if it already has data, leave it alone and log the counts
# so a regression is visible in the deploy log.
set -eu

DATA_DIR="${SNE_DATA_DIR:-/data/astrocats/astrocats/supernovae/output}"
BAKED_DIR="/app/serve/www/astrocats/astrocats/supernovae/output"

count_json() {
    find "$1" -maxdepth 2 -name '*.json' -not -path '*/.index/*' 2>/dev/null | wc -l | tr -d ' '
}

mkdir -p "$DATA_DIR"

baked_count=$(count_json "$BAKED_DIR" 2>/dev/null || echo 0)
data_count=$(count_json "$DATA_DIR" 2>/dev/null || echo 0)

echo "[entrypoint] baked corpus: ${baked_count} event JSON files at ${BAKED_DIR}"
echo "[entrypoint] volume corpus: ${data_count} event JSON files at ${DATA_DIR}"

if [ "$data_count" -eq 0 ] && [ "$baked_count" -gt 0 ]; then
    echo "[entrypoint] volume is empty; seeding from the baked image (one time)"
    # Copy epoch directories and top-level catalog/name indexes. Skip .index
    # (derived, rebuilt on demand) and html mirrors (derived, regenerated).
    for d in "$BAKED_DIR"/sne-*/; do
        [ -d "$d" ] || continue
        cp -an "$d" "$DATA_DIR/" 2>/dev/null || cp -a "$d" "$DATA_DIR/" || true
    done
    for f in "$BAKED_DIR"/*.json; do
        [ -f "$f" ] || continue
        cp -an "$f" "$DATA_DIR/" 2>/dev/null || cp -a "$f" "$DATA_DIR/" || true
    done
    seeded=$(count_json "$DATA_DIR")
    echo "[entrypoint] seeded ${seeded} event JSON files"
elif [ "$data_count" -gt 0 ]; then
    echo "[entrypoint] using existing volume data (${data_count} files); not overwriting"
    # Still copy event JSON files that exist in the image but are absent on the
    # volume. cp -n never overwrites, so enriched volume copies stay authoritative;
    # brand-new designations baked into a redeploy stop 404'ing against an older volume.
    synced=0
    for d in "$BAKED_DIR"/sne-*/; do
        [ -d "$d" ] || continue
        base=$(basename "$d")
        mkdir -p "$DATA_DIR/$base"
        for f in "$d"*.json; do
            [ -f "$f" ] || continue
            dest="$DATA_DIR/$base/$(basename "$f")"
            if [ ! -f "$dest" ]; then
                cp -a "$f" "$dest" 2>/dev/null && synced=$((synced + 1)) || true
            fi
        done
    done
    echo "[entrypoint] synced ${synced} missing event JSON files from image into volume"
fi

# The master catalog ships as catalog.min.json.gz because .dockerignore excludes
# the 53 MB plain copy. Seeding only copied "*.json", so a fresh volume had no
# catalog at all and the index built with 312 overlay events instead of 110k.
# Result: historical events 404'd in the container while working locally. Copy
# the archive too; the server decompresses it into DATA_DIR on first start.
for f in "$BAKED_DIR"/*.json.gz; do
    [ -f "$f" ] || continue
    if [ ! -f "$DATA_DIR/$(basename "$f")" ]; then
        echo "[entrypoint] copying catalog archive $(basename "$f") into the volume"
        cp -a "$f" "$DATA_DIR/" 2>/dev/null || true
    fi
done

if [ -f "$DATA_DIR/catalog.min.json" ]; then
    echo "[entrypoint] volume catalog: catalog.min.json ($(wc -c < "$DATA_DIR/catalog.min.json") bytes)"
elif [ -f "$DATA_DIR/catalog.min.json.gz" ]; then
    echo "[entrypoint] volume catalog: catalog.min.json.gz (will be decompressed on start)"
else
    echo "[entrypoint] WARNING: no catalog archive on the volume; only recently"
    echo "[entrypoint]          discovered events will be searchable until ingest runs"
fi

# Derived index lives beside the data but is safe to rebuild. Leave it if present
# so the first request after a restart skips the multi-second build.
if [ -f "$DATA_DIR/.index/catalog.db" ]; then
    echo "[entrypoint] existing catalog index found; reusing"
else
    echo "[entrypoint] no catalog index; it will be built in the background on start"
fi

# ---------------------------------------------------------------------------
# Runtime JSON: recent-events.json and recent-catalog.min.json
# ---------------------------------------------------------------------------
# These two files are written by ingest and read by the homepage. They used to
# live in serve/www/assets/, which is part of the image, so every redeploy reset
# them and the homepage served a stale recent-list until ingest ran again.
#
# They now live in a dedicated runtime directory on a volume. Only these two
# mutable files move — CSS/JS/images stay in the image so a stale volume can never
# shadow version-controlled frontend assets.
RUNTIME_DIR="${SNE_RUNTIME_DIR:-/data/sne-runtime}"
BAKED_ASSETS="/app/serve/www/assets"
mkdir -p "$RUNTIME_DIR"

runtime_count=0
for name in recent-events.json recent-catalog.min.json; do
    src="$BAKED_ASSETS/$name"
    dst="$RUNTIME_DIR/$name"
    if [ -f "$dst" ]; then
        # Existing data is authoritative: it reflects real ingest, not a build snapshot.
        runtime_count=$((runtime_count + 1))
        echo "[entrypoint] runtime asset present, keeping: $name ($(wc -c < "$dst") bytes)"
    elif [ -f "$src" ]; then
        # Seed once, atomically, so a crash mid-copy cannot leave a truncated file.
        tmp="$RUNTIME_DIR/.$name.seed.$$"
        if cp -a "$src" "$tmp" 2>/dev/null; then
            mv -f "$tmp" "$dst" 2>/dev/null && echo "[entrypoint] seeded runtime asset: $name"
        else
            rm -f "$tmp" 2>/dev/null || true
            echo "[entrypoint] WARNING: could not seed $name from the image"
        fi
    else
        echo "[entrypoint] WARNING: no baked $name to seed; ingest will create it"
    fi
done
echo "[entrypoint] runtime JSON directory: $RUNTIME_DIR (${runtime_count}/2 already present)"

# TNS public-objects ZIP: EnrichQueue needs this file to materialise missing
# event JSON from the real TNS dump. Prefer a volume copy (ops can refresh it
# without rebuild); seed once from the image when the volume has none.
TNS_ZIP_NAME="tns_public_objects.csv.zip"
TNS_ZIP_DST="$RUNTIME_DIR/$TNS_ZIP_NAME"
TNS_ZIP_SRC="/app/ingest/cache/$TNS_ZIP_NAME"
if [ -f "$TNS_ZIP_DST" ]; then
    echo "[entrypoint] TNS public ZIP present: $TNS_ZIP_DST ($(wc -c < "$TNS_ZIP_DST") bytes)"
elif [ -f "$TNS_ZIP_SRC" ]; then
    tmp="$RUNTIME_DIR/.$TNS_ZIP_NAME.seed.$$"
    if cp -a "$TNS_ZIP_SRC" "$tmp" 2>/dev/null && mv -f "$tmp" "$TNS_ZIP_DST" 2>/dev/null; then
        echo "[entrypoint] seeded TNS public ZIP into runtime ($(wc -c < "$TNS_ZIP_DST") bytes)"
    else
        rm -f "$tmp" 2>/dev/null || true
        echo "[entrypoint] WARNING: could not seed $TNS_ZIP_NAME into runtime"
    fi
else
    echo "[entrypoint] WARNING: $TNS_ZIP_NAME missing from image and runtime — EnrichQueue cannot create events from TNS"
fi

exec "$@"
