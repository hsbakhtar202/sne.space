"""Pull classified supernovae from the public TNS search CSV and write catalog files."""
from __future__ import annotations

import csv
import io
import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ingest.coordinates import ra_dec_to_deg
from ingest.manager import SUPERNOVAE_OUTPUT, atomic_write_json, get_target_repo_folder
from ingest.tns import build_event_dict

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
    req = urllib.request.Request(url, headers={"User-Agent": "sne.space/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        text = resp.read().decode("utf-8", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def _row(item: dict[str, str]) -> dict[str, str]:
    full = item.get("Name", "").strip()
    prefix, bare = full.split(" ", 1) if " " in full else ("SN", full)
    ra_deg, dec_deg = ra_dec_to_deg(item.get("RA", ""), item.get("DEC", ""))
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


def main() -> None:
    items = fetch_classified()
    written = []
    for item in items:
        if not item.get("Name"):
            continue
        row = _row(item)
        cname, event = build_event_dict(row, enrich_alerce=False, enrich_wiserep=False)
        year = int(row["discoverydate"][:4]) if row["discoverydate"][:4].isdigit() else 2026
        dest = get_target_repo_folder(year)
        dest.mkdir(parents=True, exist_ok=True)
        atomic_write_json(dest / f"{cname}.json", event)
        written.append({
            "name": cname,
            "date": row["discoverydate"][:10],
            "type": event[cname].get("claimedtype", [{"value": ""}])[0].get("value", ""),
            "discoverer": (row["reporters"] or "")[:48],
            "sort": row["discoverydate"],
        })
    written.sort(key=lambda r: r["sort"], reverse=True)
    cards = [{k: v for k, v in row.items() if k != "sort"} for row in written[:8]]
    RECENT_PATH.write_text(json.dumps(cards, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(written)} events into {SUPERNOVAE_OUTPUT}")
    for card in cards:
        print(card["date"], card["name"], card["type"])


if __name__ == "__main__":
    main()
