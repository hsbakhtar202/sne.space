"""Aged-out event recovery: keep events eligible for enrichment after they leave
the TNS recent window.

Scans the durable publication state (and, bounded, the on-disk corpus) for events
whose observations are not yet durably complete, and enqueues them into the
durable enrichment queue. Newest-first ordering is preserved by ``enqueued_at``;
this only *adds* older unfinished work, it never displaces fresh discoveries.

Safety: an event is only enqueued when its record is genuinely incomplete
(no usable detections AND no spectra), not merely because its store count is
low — a legitimately sparse historical event must not be re-enriched forever.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent


def _output_root() -> Path:
    from serve import data_paths

    return data_paths.resolve_output_dir()


def _usable(meta: dict) -> tuple[int, int]:
    import sys

    sys.path.insert(0, str(ROOT))
    try:
        from ingest.backfill_photometry import usable_outburst_detections

        det = len(usable_outburst_detections(meta))
    except Exception:
        phot = meta.get("photometry") or []
        det = sum(
            1
            for p in phot
            if isinstance(p, dict) and p.get("magnitude") is not None and not p.get("upperlimit")
        )
    spec = len(meta.get("spectra") or []) if isinstance(meta.get("spectra"), list) else 0
    return det, spec


def scan_and_enqueue(
    *,
    queue,
    limit: int = 200,
    include_disk_scan: bool = False,
    epochs: tuple[str, ...] = ("sne-2025-2029", "sne-2020-2024"),
) -> dict[str, Any]:
    """Enqueue genuinely incomplete events. Returns a small report."""
    from ingest import publication

    state = publication.load_state()
    events = state.get("events") or {}
    enq = 0
    considered = 0
    skipped_complete = 0
    names: list[str] = []

    # 1) durable state: not fully published
    for name, entry in sorted(events.items(), key=lambda kv: kv[1].get("ingested_at") or 0, reverse=True):
        if considered >= limit:
            break
        if entry.get("publish_status") == "published" and entry.get("ingest_status") == "committed":
            continue
        considered += 1
        if queue.enqueue(name):
            enq += 1
            names.append(name)

    # 2) optional bounded disk scan for never-registered sparse events
    if include_disk_scan and considered < limit:
        root = _output_root()
        for ep in epochs:
            d = root / ep
            if not d.is_dir():
                continue
            for p in sorted(d.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
                if considered >= limit:
                    break
                if publication.is_fully_published(p.stem):
                    continue
                try:
                    raw = json.loads(p.read_text(encoding="utf-8"))
                    meta = raw.get(p.stem) or next(iter(raw.values()))
                    if not isinstance(meta, dict):
                        continue
                    det, spec = _usable(meta)
                except Exception:
                    continue
                # Only genuinely incomplete (no detections and no spectra).
                if det == 0 and spec == 0:
                    considered += 1
                    if queue.enqueue(p.stem):
                        enq += 1
                        names.append(p.stem)
                else:
                    skipped_complete += 1

    return {
        "considered": considered,
        "enqueued": enq,
        "skipped_already_complete": skipped_complete,
        "sample": names[:25],
        "limit": limit,
    }


def main() -> int:
    from ingest.durable_enrich_queue import get_queue

    q = get_queue()
    rep = scan_and_enqueue(
        queue=q,
        limit=int(os.environ.get("SNE_AGED_OUT_LIMIT", "200")),
        include_disk_scan=(os.environ.get("SNE_AGED_OUT_DISK_SCAN") or "1").strip() in {"1", "true", "yes"},
    )
    print(json.dumps(rep, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
