"""Pull classified supernovae from the public TNS search CSV and write catalog files."""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import threading
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ingest.coordinates import ra_dec_to_deg
from ingest.manager import SUPERNOVAE_OUTPUT, atomic_write_json, get_target_repo_folder
from ingest.tns import build_event_dict

import time

ROOT = Path(__file__).resolve().parent.parent
# ``recent-events.json`` is mutable runtime data written on every ingest run and
# read by the homepage. It lives in the persistent runtime directory so a redeploy
# cannot reset it to its build-time snapshot. See serve/data_paths.py.
try:
    from serve.data_paths import runtime_write_path as _runtime_write_path
except ImportError:  # running as a script with ingest/ on sys.path
    import sys as _sys

    _sys.path.insert(0, str(ROOT))
    from serve.data_paths import runtime_write_path as _runtime_write_path

RECENT_PATH = _runtime_write_path("recent-events.json")


PAGE_SIZE = 100


def _atomic_write_text(path: Path, text: str) -> None:
    """Write text to ``path`` atomically so a crash cannot truncate a published file.

    ``RECENT_PATH`` and ``recent-catalog.min.json`` are read directly by the web
    server on every homepage request. A partial write during a deploy or OOM kill
    left the homepage serving a truncated JSON file. Write to a sibling temp file
    on the same filesystem and ``os.replace`` into position.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}.{threading.get_ident()}")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass
        raise


def _fetch_page(url: str) -> list[dict[str, str]]:
    """Fetch one TNS search page, honouring 429 reset headers."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (sne.space Ingestion)"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                text = resp.read().decode("utf-8", errors="replace")
            return list(csv.DictReader(io.StringIO(text)))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                try:
                    reset_sec = float(e.headers.get("x-rate-limit-reset", "20")) + 1.0
                except (ValueError, TypeError):
                    reset_sec = 20.0 * (attempt + 1)
                print(f"[TNS Search] Rate limit active. Sleeping {reset_sec:.1f}s for reset...", flush=True)
                time.sleep(reset_sec)
                continue
            raise
    return []


def fetch_classified(days: int = 40, max_pages: int = 40) -> list[dict[str, str]]:
    """Fetch every classified supernova in the trailing window.

    TNS returns results newest-first and caps a page at PAGE_SIZE rows. Reading
    only page 0 silently drops the oldest events in the window, and because the
    window slides forward each day those dropped events fall out of reach for
    good. Walk the pages until a short page is returned.
    """
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for page in range(max_pages):
        query = urllib.parse.urlencode({
            "classified_sne": "1",
            "date_start[date]": start.isoformat(),
            "date_end[date]": end.isoformat(),
            "format": "csv",
            "num_page": str(PAGE_SIZE),
            "page": str(page),
        })
        try:
            batch = _fetch_page(f"https://www.wis-tns.org/search?{query}")
        except Exception as exc:
            print(f"[TNS Search] page {page} failed: {exc}", flush=True)
            break
        for row in batch:
            key = (row.get("Name") or "").strip()
            if key and key not in seen:
                seen.add(key)
                rows.append(row)
        if len(batch) < PAGE_SIZE:
            break
        time.sleep(1.0)
    print(f"[TNS Search] {len(rows)} classified rows for {start} -> {end}", flush=True)
    return rows


def fetch_recent_discoveries(days: int = 7, max_pages: int = 5) -> list[dict[str, str]]:
    """Fetch every recent TNS transient, classified or not.

    ``classified_sne=1`` only surfaces objects that already have a public
    classification report. Those reports land days after discovery, so a
    classified-only feed has a built-in multi-day blind spot: brand-new real
    transients exist on TNS but stay invisible here until someone classifies
    them. This lane keeps the discovery list current so tomorrow's events show
    up tomorrow.
    """
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for page in range(max_pages):
        query = urllib.parse.urlencode({
            "date_start[date]": start.isoformat(),
            "date_end[date]": end.isoformat(),
            "format": "csv",
            "num_page": str(PAGE_SIZE),
            "page": str(page),
        })
        try:
            batch = _fetch_page(f"https://www.wis-tns.org/search?{query}")
        except Exception as exc:
            print(f"[TNS Discovery] page {page} failed: {exc}", flush=True)
            break
        for row in batch:
            key = (row.get("Name") or "").strip()
            if key and key not in seen:
                seen.add(key)
                rows.append(row)
        if len(batch) < PAGE_SIZE:
            break
        time.sleep(1.0)
    print(f"[TNS Discovery] {len(rows)} transients for {start} -> {end}", flush=True)
    return rows


def _row(item: dict[str, str]) -> dict[str, str] | None:
    full = item.get("Name", "").strip()
    if not full or not item.get("RA") or not item.get("DEC") or not item.get("Discovery Date (UT)"):
        return None
    prefix, bare = full.split(" ", 1) if " " in full else ("SN", full)
    try:
        ra_deg, dec_deg = ra_dec_to_deg(item.get("RA", ""), item.get("DEC", ""))
    except Exception:
        return None
    return {
        "name_prefix": prefix,
        "name": bare,
        "ra": f"{ra_deg:.8f}",
        "declination": f"{dec_deg:.8f}",
        "type": item.get("Obj. Type", ""),
        "redshift": item.get("Redshift", ""),
        "reporters": item.get("Sender", "") or item.get("Reporting Group/s", ""),
        "reporting_group": item.get("Reporting Group/s", ""),
        "internal_names": item.get("Disc. Internal Name", ""),
        "Discovery_ADS_bibcode": item.get("Discovery Bibcode", ""),
        "discoverydate": item.get("Discovery Date (UT)", ""),
        "discoverymag": item.get("Discovery Mag/Flux", ""),
        "filter": item.get("Discovery Filter", ""),
    }


def _publish(written: list[dict]) -> None:
    """Replace the homepage recent list. Never publish an empty pull over a good file."""
    if not written:
        print("TNS pull returned no rows; leaving the existing recent list in place", flush=True)
        return
    written.sort(key=lambda r: r["sort"], reverse=True)
    cards = [{k: v for k, v in row.items() if k != "sort"} for row in written[:8]]
    _atomic_write_text(RECENT_PATH, json.dumps(cards, indent=2) + "\n")
    catalog_rows = []
    for row in written:
        day = row["date"].replace("-", "/")
        s_count = row.get("spectra_count", 0)
        p_count = row.get("photo_count", 1)
        catalog_rows.append({
            "name": row["name"],
            "alias": [{"value": row["name"]}],
            "discoverer": [{"value": row["discoverer"]}],
            "discoverdate": [{"value": day}],
            "maxdate": [{"value": day}],
            "maxappmag": [],
            "ra": [{"value": row.get("ra", "")}],
            "dec": [{"value": row.get("dec", "")}],
            "claimedtype": [{"value": row["type"]}],
            "photolink": f"{p_count},0",
            "spectralink": f"{s_count}" if s_count > 0 else "0",
        })
    # Explicit rather than derived from RECENT_PATH.parent so the intent is clear
    # and a future move of one file cannot silently desynchronise the pair.
    catalog_path = _runtime_write_path("recent-catalog.min.json")
    _atomic_write_text(catalog_path, json.dumps(catalog_rows, separators=(",", ":")))
    classified = sum(1 for r in written if r.get("type") and r["type"] != "unclassified")
    print(
        f"Published {len(written)} transients ({classified} classified); "
        f"newest {cards[0]['name']} {cards[0]['date']}",
        flush=True,
    )


def pull_recent(days: int = 40) -> int:
    """Download the newest classified TNS supernovae and refresh the homepage list.

    The homepage file is written from the TNS search rows first. Spectra and
    photometry enrichment happens afterward, so a slow or stuck enrich cannot
    leave the previous pull on disk.
    """
    items = fetch_classified(days=days)

    # Second lane: recent discoveries regardless of classification, so objects
    # found in the last few days are not invisible while waiting for a report.
    try:
        discoveries = fetch_recent_discoveries(days=7)
    except Exception as exc:
        print(f"[TNS Discovery] lane skipped: {exc}", flush=True)
        discoveries = []
    known = {(i.get("Name") or "").strip() for i in items}
    for d in discoveries:
        key = (d.get("Name") or "").strip()
        if key and key not in known:
            items.append(d)
            known.add(key)
    print(f"[TNS Recent] {len(items)} rows total ({len(discoveries)} discovery lane)", flush=True)

    written = []
    pending = []
    for item in items:
        row = _row(item)
        if row is None:
            continue
        cname_raw = f"{row.get('name_prefix', 'SN')}{row['name']}"
        written.append({
            "name": cname_raw,
            "date": row["discoverydate"][:10],
            # An unclassified transient must not render as a blank type; say so.
            "type": row.get("type") or "unclassified",
            "discoverer": (row.get("reporters") or "")[:48],
            "ra": item.get("RA", ""),
            "dec": item.get("DEC", ""),
            "spectra_count": 0,
            "photo_count": 1,
            "sort": row["discoverydate"],
        })
        pending.append((cname_raw, row, item))
    _publish(written)
    if not written:
        return 0

    by_name = {row["name"]: row for row in written}

    # Load whatever is already on disk first. Enrichment is the expensive part and
    # TNS throttles hard, so only events that are genuinely missing or still have
    # no spectra get another attempt. Without this the loop re-enriches the whole
    # window every cycle and spends its entire budget waiting out 429s, which
    # leaves the newest events (the ones users actually open) unenriched.
    on_disk: dict[str, tuple[Path, dict]] = {}
    for cname_raw, row, item in pending:
        year = int(row["discoverydate"][:4]) if row["discoverydate"][:4].isdigit() else 2026
        dest = get_target_repo_folder(year)
        dest_file = dest / f"{cname_raw}.json"
        if dest_file.is_file():
            try:
                ex_data = json.loads(dest_file.read_text(encoding="utf-8"))
                if ex_data:
                    on_disk[cname_raw] = (dest_file, ex_data)
            except Exception:
                pass

    def _needs_enrich(cname_raw: str) -> bool:
        hit = on_disk.get(cname_raw)
        if hit is None:
            return True
        _path, ex_data = hit
        key = next(iter(ex_data), cname_raw)
        return len(ex_data.get(key, {}).get("spectra", [])) == 0

    # Newest first so fresh discoveries are enriched before anything else.
    pending.sort(key=lambda p: p[1]["discoverydate"], reverse=True)
    todo = [p for p in pending if _needs_enrich(p[0])]
    skipped = len(pending) - len(todo)
    print(f"[TNS Enrich] {len(todo)} need enrichment, {skipped} already enriched", flush=True)

    for cname_raw, row, item in todo:
        year = int(row["discoverydate"][:4]) if row["discoverydate"][:4].isdigit() else 2026
        dest = get_target_repo_folder(year)
        dest.mkdir(parents=True, exist_ok=True)
        dest_file = dest / f"{cname_raw}.json"
        event = None
        cname = cname_raw
        try:
            hit = on_disk.get(cname_raw)
            if hit is not None:
                _path, ex_data = hit
                cname = next(iter(ex_data), cname_raw)
                event = ex_data
            if event is None:
                cname, event = build_event_dict(
                    row,
                    enrich_alerce=True,
                    enrich_wiserep=False,
                    enrich_tns_spectra=True,
                )
                time.sleep(0.5)
                atomic_write_json(dest / f"{cname}.json", event)
            card = by_name.get(cname_raw)
            if card is not None and event is not None:
                body = event.get(cname, {})
                card["spectra_count"] = len(body.get("spectra", []))
                card["photo_count"] = len(body.get("photometry", [])) or 1
                card["type"] = body.get("claimedtype", [{"value": card["type"]}])[0].get("value", card["type"])
                card["ra"] = body.get("ra", [{"value": card["ra"]}])[0].get("value", card["ra"])
                card["dec"] = body.get("dec", [{"value": card["dec"]}])[0].get("value", card["dec"])
        except Exception as exc:
            print(f"TNS enrich failed for {cname_raw}: {exc}", flush=True)
            continue

    # Carry the enrichment counts for events we skipped back onto the cards.
    for cname_raw, row, item in pending:
        hit = on_disk.get(cname_raw)
        card = by_name.get(cname_raw)
        if hit is None or card is None:
            continue
        _path, ex_data = hit
        key = next(iter(ex_data), cname_raw)
        body = ex_data.get(key, {})
        card["spectra_count"] = len(body.get("spectra", []))
        card["photo_count"] = len(body.get("photometry", [])) or 1
        ct = body.get("claimedtype") or []
        if ct and ct[0].get("value"):
            card["type"] = ct[0]["value"]
        ra = body.get("ra") or []
        dec = body.get("dec") or []
        if ra and ra[0].get("value"):
            card["ra"] = ra[0]["value"]
        if dec and dec[0].get("value"):
            card["dec"] = dec[0]["value"]

    _publish(written)
    print(f"Wrote {len(written)} events into {SUPERNOVAE_OUTPUT}", flush=True)
    return len(written)


def main() -> None:
    n = pull_recent()
    print(f"TNS recent pull complete: {n} events", flush=True)


if __name__ == "__main__":
    main()
