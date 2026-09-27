"""Command-line interface for Open Supernova Catalog Ingestion Pipeline."""
import argparse
import glob
import json
import os
import sys
from pathlib import Path

from ingest.manager import (
    enrich_event,
    find_existing_event_file,
    ingest_tns_batch,
    run_webcat_rebuild,
    SUPERNOVAE_OUTPUT,
)


def cmd_status(args: argparse.Namespace) -> None:
    """Print current catalog status and repository file counts."""
    print("=" * 60)
    print("  Open Supernova Catalog (sne.space) — Catalog Status")
    print("=" * 60)

    folders = [
        "sne-pre-1990",
        "sne-1990-1999",
        "sne-2000-2004",
        "sne-2005-2009",
        "sne-2010-2014",
        "sne-2015-2019",
        "sne-2020-2024",
        "sne-2025-2029",
        "sne-boneyard",
    ]

    total_events = 0
    non_boneyard = 0

    for f in folders:
        p = SUPERNOVAE_OUTPUT / f
        cnt = len(list(p.glob("*.json"))) if p.is_dir() else 0
        total_events += cnt
        if f != "sne-boneyard":
            non_boneyard += cnt
        print(f"  {f:<18}: {cnt:>8,} JSON event files")

    print("-" * 60)
    print(f"  Total Catalog (non-boneyard): {non_boneyard:>8,} events")
    print(f"  Total Files (with boneyard) : {total_events:>8,} events")

    # Aggregate status
    cat_min = SUPERNOVAE_OUTPUT / "catalog.min.json"
    names_min = SUPERNOVAE_OUTPUT / "names.min.json"

    if cat_min.is_file():
        sz = cat_min.stat().st_size / (1024 * 1024)
        print(f"  catalog.min.json            : {sz:.1f} MB")
    if names_min.is_file():
        sz = names_min.stat().st_size / (1024 * 1024)
        print(f"  names.min.json              : {sz:.1f} MB")

    # Check famous sample modern events
    print("-" * 60)
    print("  Sample Modern Supernovae Verification:")
    sample_events = ["SN2023ixf", "SN2024ggi", "SN2021aefx", "SN2022jli", "SN2025pht", "SN2026cev"]
    for s in sample_events:
        fp = find_existing_event_file(s)
        if fp:
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
                k = list(data.keys())[0]
                ev = data[k]
                claimed = ev.get("claimedtype", [{}])[0].get("value", "?")
                pts = len(ev.get("photometry", []))
                specs = len(ev.get("spectra", []))
                print(f"    ✓ {s:<12}: Type {claimed:<6} | {pts:>3} photo | {specs:>2} spec | in {fp.parent.name}")
            except Exception as e:
                print(f"    ✓ {s:<12}: exists ({fp.parent.name}) [read err: {e}]")
        else:
            print(f"    ✗ {s:<12}: not in catalog yet")
    print("=" * 60)


def cmd_ingest_tns(args: argparse.Namespace) -> None:
    """Run TNS batch ingestion."""
    years = {y.strip() for y in args.years.split(",") if y.strip()}
    classified_only = not args.include_ats
    print(f"[Ingest] Ingesting TNS events for years: {sorted(years)}")
    print(f"[Ingest] Classified only: {classified_only}, Enrich brokers: {args.enrich_brokers}")

    created, merged, skipped = ingest_tns_batch(
        target_years=years,
        classified_only=classified_only,
        overwrite=args.overwrite,
        enrich_brokers=args.enrich_brokers,
        limit=args.limit,
    )

    if args.rebuild:
        print("[Ingest] Rebuilding catalog aggregates...")
        run_webcat_rebuild()


def cmd_enrich(args: argparse.Namespace) -> None:
    """Enrich a single event with ALeRCE and WISeREP data."""
    object_name = args.object_name
    print(f"[Enrich] Enriching {object_name}...")
    success = enrich_event(
        object_name,
        fetch_lightcurve=not args.no_photometry,
        fetch_spectra=not args.no_spectra,
    )
    if success and args.rebuild:
        print("[Enrich] Rebuilding catalog aggregates...")
        run_webcat_rebuild()


def cmd_rebuild(args: argparse.Namespace) -> None:
    """Run webcat rebuild."""
    ret = run_webcat_rebuild()
    sys.exit(ret)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ingest",
        description="Open Supernova Catalog Ingest Pipeline (TNS 2.0, ALeRCE, WISeREP)"
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # status
    p_status = subparsers.add_parser("status", help="Show current catalog status and counts")
    p_status.set_defaults(func=cmd_status)

    # ingest-tns
    p_ingest = subparsers.add_parser("ingest-tns", help="Ingest events from IAU TNS database")
    p_ingest.add_argument(
        "--years",
        default="2022,2023,2024,2025,2026",
        help="Comma-separated list of discovery years (default: 2022,2023,2024,2025,2026)"
    )
    p_ingest.add_argument(
        "--include-ats",
        action="store_true",
        help="Also ingest unclassified Astronomical Transients (ATs) in addition to confirmed SNe"
    )
    p_ingest.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of events to process"
    )
    p_ingest.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing event JSON files"
    )
    p_ingest.add_argument(
        "--enrich-brokers",
        action="store_true",
        help="Query ALeRCE and WISeREP on the fly for each ingested event"
    )
    p_ingest.add_argument(
        "--rebuild",
        action="store_true",
        help="Trigger webcat rebuild immediately after ingestion"
    )
    p_ingest.set_defaults(func=cmd_ingest_tns)

    # enrich
    p_enrich = subparsers.add_parser("enrich", help="Enrich a single event with ALeRCE and WISeREP data")
    p_enrich.add_argument("object_name", help="Event name (e.g. SN2023ixf, SN2024ggi)")
    p_enrich.add_argument("--no-photometry", action="store_true", help="Skip ALeRCE ZTF photometry")
    p_enrich.add_argument("--no-spectra", action="store_true", help="Skip WISeREP spectra")
    p_enrich.add_argument("--rebuild", action="store_true", help="Trigger webcat rebuild after enrichment")
    p_enrich.set_defaults(func=cmd_enrich)

    # rebuild
    p_rebuild = subparsers.add_parser("rebuild", help="Run webcat to regenerate catalog aggregates")
    p_rebuild.set_defaults(func=cmd_rebuild)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
