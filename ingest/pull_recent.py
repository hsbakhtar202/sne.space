"""Pull classified supernovae from the public TNS search CSV and write catalog files."""
from __future__ import annotations

import csv
import io
import json
import sys
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
RECENT_PATH = ROOT / "serve/www/assets/recent-events.json"


def fetch_classified(days: int = 40) -> list[dict[str, str]]:
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)
    query = urllib.parse.urlencode({
        "classified_sne": "1",
        "date_start[date]": start.isoformat(),
        "date_end[date]": end.isoformat(),
        "format": "csv",
        "num_page": "100",
        "page": "0",
    })
    url = f"https://www.wis-tns.org/search?{query}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (sne.space Ingestion)"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                text = resp.read().decode("utf-8", errors="replace")
            return list(csv.DictReader(io.StringIO(text)))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                reset_sec = float(e.headers.get("x-rate-limit-reset", "20")) + 1.0
                print(f"[TNS Search] Rate limit active. Sleeping {reset_sec:.1f}s for reset...", flush=True)
                time.sleep(reset_sec)
                continue
            raise
    return []


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


def pull_recent(days: int = 40) -> int:
    """Download the newest classified TNS supernovae and refresh the homepage list."""
    items = fetch_classified(days=days)
    written = []
    for item in items:
        row = _row(item)
        if row is None:
            continue

        cname_raw = f"{row.get('name_prefix', 'SN')}{row['name']}"
        year = int(row["discoverydate"][:4]) if row["discoverydate"][:4].isdigit() else 2026
        dest = get_target_repo_folder(year)
        dest.mkdir(parents=True, exist_ok=True)
        dest_file = dest / f"{cname_raw}.json"

        event = None
        if dest_file.is_file():
            try:
                ex_data = json.loads(dest_file.read_text(encoding="utf-8"))
                ex_key = list(ex_data.keys())[0] if ex_data else cname_raw
                if len(ex_data.get(ex_key, {}).get("spectra", [])) > 0:
                    cname = ex_key
                    event = ex_data
            except Exception:
                pass

        if event is None:
            cname, event = build_event_dict(
                row,
                enrich_alerce=True,
                enrich_wiserep=False,
                enrich_tns_spectra=True
            )
            time.sleep(0.5)  # Respectful cadence to prevent TNS rate-limiting
            atomic_write_json(dest / f"{cname}.json", event)

        n_spectra = len(event[cname].get("spectra", []))
        n_photo = len(event[cname].get("photometry", []))

        written.append({
            "name": cname,
            "date": row["discoverydate"][:10],
            "type": event[cname].get("claimedtype", [{"value": ""}])[0].get("value", ""),
            "discoverer": (row["reporters"] or "")[:48],
            "ra": event[cname].get("ra", [{"value": ""}])[0].get("value", ""),
            "dec": event[cname].get("dec", [{"value": ""}])[0].get("value", ""),
            "spectra_count": n_spectra,
            "photo_count": n_photo,
            "sort": row["discoverydate"],
        })
    written.sort(key=lambda r: r["sort"], reverse=True)
    cards = [{k: v for k, v in row.items() if k != "sort"} for row in written[:8]]
    RECENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RECENT_PATH.write_text(json.dumps(cards, indent=2) + "\n", encoding="utf-8")
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
    catalog_path = RECENT_PATH.parent / "recent-catalog.min.json"
    catalog_path.write_text(json.dumps(catalog_rows, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {len(written)} events into {SUPERNOVAE_OUTPUT}", flush=True)
    return len(written)


def main() -> None:
    n = pull_recent()
    print(f"TNS recent pull complete: {n} events", flush=True)


if __name__ == "__main__":
    main()
