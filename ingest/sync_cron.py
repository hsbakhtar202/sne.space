"""Automated Daily Sync Cron for sne.space.

Fetches newly discovered and classified transients from IAU TNS (last 3-7 days),
enriches them with ALeRCE alert photometry and WISeREP classification spectra,
and incrementally updates the local event records and catalog aggregates.
"""
from __future__ import annotations

import argparse
import datetime
import logging
import sys
import time
from pathlib import Path

# Ensure ingest and serve modules are importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ingest.manager import (
    enrich_event,
    find_existing_event_file,
    ingest_tns_batch,
    run_webcat_rebuild,
)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("sync_cron")


def run_sync(
    days_back: int = 7,
    limit: int = 50,
    rebuild: bool = True,
    enrich_brokers: bool = True,
) -> int:
    """Execute nightly sync pipeline."""
    start_time = time.time()
    now = datetime.date.today()
    years = {str(now.year), str(now.year - 1)} if now.month == 1 else {str(now.year)}
    logger.info("Starting sne.space automated sync cron...")
    logger.info("Target years: %s | Days back: %d | Limit: %d", sorted(years), days_back, limit)

    # 1. Ingest from TNS
    try:
        created, merged, skipped = ingest_tns_batch(
            target_years=years,
            classified_only=True,
            overwrite=False,
            enrich_brokers=enrich_brokers,
            limit=limit,
        )
        logger.info(
            "TNS Ingestion complete: %d created, %d merged, %d skipped",
            created,
            merged,
            skipped,
        )
    except Exception as e:
        logger.error("Error during TNS ingestion: %s", e, exc_info=True)
        return 1

    # 2. Rebuild catalog aggregates if new data was incorporated
    if rebuild and (created > 0 or merged > 0):
        logger.info("Rebuilding catalog aggregates (webcat)...")
        try:
            rc = run_webcat_rebuild()
            logger.info("Webcat rebuild exited with code %d", rc)
        except Exception as e:
            logger.warning("Webcat rebuild encountered non-fatal error: %s", e)

    elapsed = time.time() - start_time
    logger.info("Sync cron finished successfully in %.2f seconds.", elapsed)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="sync_cron",
        description="Daily automated ingestion delta cron for sne.space"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days back to sync (default: 7)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of new events to fetch (default: 50)"
    )
    parser.add_argument(
        "--no-rebuild",
        action="store_true",
        help="Skip rebuilding webcat aggregates"
    )
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        help="Skip broker enrichment (ALeRCE/WISeREP)"
    )
    args = parser.parse_args()

    exit_code = run_sync(
        days_back=args.days,
        limit=args.limit,
        rebuild=not args.no_rebuild,
        enrich_brokers=not args.no_enrich,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
