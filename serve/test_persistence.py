#!/usr/bin/env python3
"""Acceptance test: ingested event JSON survives container/process replacement.

Simulates a deploy the way Docker actually does it:

  1. Start the server against a data directory (the "volume").
  2. Write a brand-new event JSON into that directory, as the ingest pipeline would.
  3. Kill the server process (the "container").
  4. Start a *new* server process against the same directory.
  5. Assert the new process serves the event and still reports the same corpus.

The point is to prove persistence does not depend on process memory or on the
image's baked snapshot. Exits non-zero on failure.

Usage:
    python3 serve/test_persistence.py [--data-dir DIR] [--port 8093]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BAKED = REPO / "serve" / "www" / "astrocats" / "astrocats" / "supernovae" / "output"

TEST_EVENT = "AT2026persisttest"
TEST_EPOCH = "sne-2025-2029"


def get(url: str, timeout: float = 60.0):
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() or b""
    except Exception as e:  # noqa: BLE001
        return -1, repr(e).encode()


def wait_up(port: int, tries: int = 60) -> bool:
    for _ in range(tries):
        code, _ = get(f"http://127.0.0.1:{port}/healthz", timeout=2)
        if code == 200:
            return True
        time.sleep(0.5)
    return False


def start_server(port: int, data_dir: Path, log: Path,
                 runtime_dir: Path | None = None) -> subprocess.Popen:
    env = os.environ.copy()
    env.update(
        SNE_DATA_DIR=str(data_dir),
        OSC_PORT=str(port),
        OSC_HOST="127.0.0.1",
        PYTHONUNBUFFERED="1",
    )
    if runtime_dir is not None:
        env["SNE_RUNTIME_DIR"] = str(runtime_dir)
    lf = open(log, "ab")
    p = subprocess.Popen(
        [sys.executable, "serve/server.py"],
        cwd=str(REPO),
        env=env,
        stdout=lf,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    return p


def stop_server(p: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(p.pid), signal.SIGTERM)
    except Exception:  # noqa: BLE001
        try:
            p.terminate()
        except Exception:  # noqa: BLE001
            pass
    try:
        p.wait(timeout=15)
    except Exception:  # noqa: BLE001
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except Exception:  # noqa: BLE001
            pass


def count_json(root: Path) -> int:
    return sum(1 for _ in root.rglob("*.json") if ".index" not in str(_))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="", help="reuse a dir instead of a temp copy")
    ap.add_argument("--runtime-dir", default="",
                    help="reuse a runtime-JSON dir instead of a temp copy")
    ap.add_argument("--port", type=int, default=8093)
    ap.add_argument("--keep", action="store_true", help="do not delete the temp volume")
    args = ap.parse_args()

    failures: list[str] = []

    def check(label: str, ok: bool, detail: str) -> None:
        print(f"[{'PASS' if ok else 'FAIL'}] {label}: {detail}", flush=True)
        if not ok:
            failures.append(label)

    if args.data_dir:
        data_dir = Path(args.data_dir)
        temp_owned = False
        runtime_dir = Path(args.runtime_dir) if args.runtime_dir else None
    else:
        data_dir = Path(tempfile.mkdtemp(prefix="sne_volume_"))
        temp_owned = True
        # A second directory stands in for the sne_runtime volume. It starts EMPTY,
        # so the test proves the boot-time seed path works, not just the read path.
        runtime_dir = Path(tempfile.mkdtemp(prefix="sne_runtime_"))
        print(f"[setup] simulating a fresh named volume at {data_dir}", flush=True)
        # Copy the baked corpus the way the entrypoint seeds an empty volume.
        for src_dir in sorted(BAKED.glob("sne-*/")):
            shutil.copytree(src_dir, data_dir / src_dir.name, dirs_exist_ok=True)
        for f in BAKED.glob("*.json"):
            shutil.copy2(f, data_dir / f.name)
        print(f"[setup] seeded {count_json(data_dir)} event JSON files", flush=True)

    log = Path(tempfile.mkstemp(prefix="sne_persist_", suffix=".log")[1])
    port = args.port
    server = None
    try:
        # ---- Boot 1 -------------------------------------------------------
        server = start_server(port, data_dir, log, runtime_dir)
        check("boot_1_starts", wait_up(port), f"server listening on {port}")

        # Baseline: the corpus is served from the volume.
        code, _ = get(f"http://127.0.0.1:{port}/sne/SN2011fe/")
        check("boot_1_serves_baked_event", code == 200, f"/sne/SN2011fe/ -> {code}")

        # ---- Write a new event, as ingest would ----------------------------
        epoch_dir = data_dir / TEST_EPOCH
        epoch_dir.mkdir(parents=True, exist_ok=True)
        event_path = epoch_dir / f"{TEST_EVENT}.json"
        payload = {
            TEST_EVENT: {
                "name": {"value": TEST_EVENT},
                "ra": {"value": "150.1234"},
                "dec": {"value": "22.5678"},
                "discoverdate": {"value": "2026-10-20"},
                "maxdate": {"value": "2026-10-22"},
                "maxappmag": {"value": "18.4"},
                "claimedtype": [{"value": "SN Ia"}],
                "host": {"value": "Test Host Galaxy"},
                "sources": [{"name": "Persistence Acceptance Test"}],
                "photometry": [
                    {
                        "time": "60000.1", "magnitude": "18.4", "band": "V",
                        "instrument": "test", "source": "Persistence Test",
                        "telescope": "test",
                    }
                ],
            }
        }
        # Atomic write, matching ingest/pull_recent.py's contract.
        tmp = event_path.with_name(f".{event_path.name}.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, event_path)
        check("event_written", event_path.is_file(),
              f"{event_path} ({event_path.stat().st_size} B)")

        # Boot 1 should serve it too (path cache TTL is short, but a new file
        # resolves on a miss; give the direct lookup a chance).
        code1, body1 = get(f"http://127.0.0.1:{port}/sne/{TEST_EVENT}/")
        check("boot_1_serves_new_event", code1 == 200 and len(body1) > 500,
              f"/sne/{TEST_EVENT}/ -> {code1}, {len(body1)} B")

        # ---- Runtime JSON: mutate the persistent copies, as ingest would ----
        # These files drive the homepage's "newest transients" block. Before this
        # change they lived in serve/www/assets/, inside the image, so every
        # redeploy silently reset them. Write a recognisable marker and prove it
        # survives process replacement.
        runtime_marker = "AT2026runtimemarker"
        runtime_ok = False
        runtime_path = runtime_dir / "recent-events.json"
        catalog_path = runtime_dir / "recent-catalog.min.json"
        try:
            cards = [{
                "name": runtime_marker, "date": "2026-10-26", "type": "unclassified",
                "discoverer": "PersistenceTest", "ra": "11:22:36.528",
                "dec": "+80:48:09.12", "spectra_count": 0, "photo_count": 1,
            }]
            # Atomic writes, matching the producer contract.
            for target, payload in (
                (runtime_path, json.dumps(cards, indent=2) + "\n"),
                (catalog_path, json.dumps([{
                    "name": runtime_marker,
                    "alias": [{"value": runtime_marker}],
                    "discoverer": [{"value": "PersistenceTest"}],
                    "discoverdate": [{"value": "2026/10/26"}],
                    "maxdate": [{"value": "2026/10/26"}],
                    "maxappmag": [], "ra": [{"value": "11:22:36.528"}],
                    "dec": [{"value": "+80:48:09.12"}],
                    "claimedtype": [{"value": "unclassified"}],
                    "photolink": "1,0", "spectralink": "0",
                }], separators=(",", ":"))),
            ):
                t = target.with_name(f".{target.name}.tmp")
                t.write_text(payload, encoding="utf-8")
                os.replace(t, target)
            runtime_ok = runtime_path.is_file() and catalog_path.is_file()
            check("runtime_json_written", runtime_ok,
                  f"{runtime_path.name} ({runtime_path.stat().st_size} B), "
                  f"{catalog_path.name} ({catalog_path.stat().st_size} B)")
        except Exception as exc:  # noqa: BLE001
            check("runtime_json_written", False, f"write failed: {exc}")

        # The homepage must reflect the new marker before the restart.
        code_h1, body_h1 = get(f"http://127.0.0.1:{port}/")
        check("homepage_shows_runtime_marker", code_h1 == 200 and runtime_marker.encode() in body_h1,
              f"/ -> {code_h1}, marker_present={runtime_marker.encode() in body_h1}")

        # ---- Kill and replace ---------------------------------------------
        stop_server(server)
        server = None
        time.sleep(1.0)
        code_dead, _ = get(f"http://127.0.0.1:{port}/healthz", timeout=2)
        check("boot_1_stopped", code_dead != 200, f"old process gone (code={code_dead})")

        # ---- Boot 2 against the same directory -----------------------------
        server = start_server(port, data_dir, log, runtime_dir)
        check("boot_2_starts", wait_up(port), f"new process listening on {port}")

        # The decisive assertion: the event written before the restart is served.
        code2, body2 = get(f"http://127.0.0.1:{port}/sne/{TEST_EVENT}/")
        check("event_survives_replacement",
              code2 == 200 and len(body2) > 500 and TEST_EVENT.encode() in body2,
              f"/sne/{TEST_EVENT}/ -> {code2}, {len(body2)} B after restart")

        # JSON endpoint too, so an API client sees it.
        code3, body3 = get(f"http://127.0.0.1:{port}/api/{TEST_EVENT}.json")
        served = False
        try:
            served = json.loads(body3).get(TEST_EVENT, {}).get("name", {}).get("value") == TEST_EVENT
        except Exception:  # noqa: BLE001
            served = False
        check("json_survives_replacement", code3 == 200 and served,
              f"/api/{TEST_EVENT}.json -> {code3}, parsed={served}")

        # Boot 2 must not have re-seeded or clobbered the volume.
        total = count_json(data_dir)
        check("volume_not_clobbered", total >= 3000,
              f"{total} event JSON files still present on the volume")

        # Health endpoint should still report the volume as the data dir.
        code4, body4 = get(f"http://127.0.0.1:{port}/api/internal/health?auth=monster104")
        data_dir_ok = False
        try:
            data_dir_ok = str(data_dir) in json.loads(body4).get("data_dir", "")
        except Exception:  # noqa: BLE001
            pass
        check("health_reports_volume", code4 == 200 and data_dir_ok,
              f"/api/internal/health data_dir points at {data_dir}")

        # ---- Runtime JSON must survive the replacement ---------------------
        # This is the regression guard for the redeploy data-loss defect: the
        # marker written before the restart must still be served afterwards.
        code_r1, body_r1 = get(f"http://127.0.0.1:{port}/api/recent")
        marker_served = False
        try:
            marker_served = runtime_marker in json.loads(body_r1).__str__()
        except Exception:  # noqa: BLE001
            marker_served = runtime_marker.encode() in body_r1
        check("runtime_json_survives_replacement", code_r1 == 200 and marker_served,
              f"/api/recent -> {code_r1}, marker_present={marker_served}")

        code_r2, body_r2 = get(f"http://127.0.0.1:{port}/")
        check("homepage_survives_replacement", code_r2 == 200 and runtime_marker.encode() in body_r2,
              f"/ -> {code_r2}, marker_present={runtime_marker.encode() in body_r2}")

        # The runtime files must still be on disk in the persistent dir, not the image.
        check("runtime_files_on_persistent_volume",
              runtime_path.is_file() and catalog_path.is_file(),
              f"{runtime_path} exists={runtime_path.is_file()}, "
              f"{catalog_path.name} exists={catalog_path.is_file()}")

    finally:
        if server is not None:
            stop_server(server)
        try:
            event_path.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        if temp_owned and not args.keep:
            shutil.rmtree(data_dir, ignore_errors=True)
            if runtime_dir is not None:
                shutil.rmtree(runtime_dir, ignore_errors=True)
            log.unlink(missing_ok=True)
        else:
            print(f"[cleanup] kept volume at {data_dir} and log at {log}", flush=True)

    print(f"\n=== {len(failures)} failure(s)" if failures else "\n=== all persistence checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
