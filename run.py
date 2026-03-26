"""
run.py
------
CLI entry point for the PGA Tour ingestion pipeline.

Usage examples:

  # Run one year (completed tournaments only)
  python run.py --years 2026

  # Run multiple years
  python run.py --years 2024 2025 2026

  # Include upcoming tournaments in tournament/course tables (no leaderboard fetch)
  python run.py --years 2026 --include-upcoming

  # Custom DB and raw data directory
  python run.py --years 2026 --db "host=localhost dbname=golf user=postgres password=secret" --raw-dir ./raw_data

Configuration:
  Default DB connection string is read from config.json as "db_dsn".
  Override with --db flag.
"""

import argparse
import json
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)


def load_config(config_path: str) -> dict:
    if not os.path.exists(config_path):
        return {}
    with open(config_path) as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="PGA Tour ingestion pipeline")
    parser.add_argument(
        "--years",
        nargs="+",
        required=True,
        help="Season year(s) to process, e.g. 2024 2025 2026",
    )
    parser.add_argument(
        "--db",
        default=None,
        help=(
            "PostgreSQL DSN string. "
            'Example: "host=localhost dbname=golf user=postgres password=secret". '
            "Overrides config.json db_dsn."
        ),
    )
    parser.add_argument(
        "--raw-dir",
        default=None,
        help="Directory for raw JSON files. Default: ./raw_data",
    )
    parser.add_argument(
        "--include-upcoming",
        action="store_true",
        default=False,
        help=(
            "If set, insert tournament/course rows for upcoming tournaments too. "
            "Leaderboards are never fetched for upcoming tournaments regardless."
        ),
    )
    parser.add_argument(
        "--config",
        default="config.json",
        help="Path to config.json (default: ./config.json)",
    )

    args = parser.parse_args()

    config = load_config(args.config)

    db_dsn = args.db or config.get("db_dsn")
    if not db_dsn:
        logger.error(
            "No database connection string provided. "
            "Use --db flag or set 'db_dsn' in config.json."
        )
        sys.exit(1)

    raw_dir = args.raw_dir or config.get("raw_data_dir") or os.path.join(
        os.path.dirname(__file__), "raw_data"
    )

    completed_only = not args.include_upcoming

    logger.info("Years: %s", args.years)
    logger.info("Raw data dir: %s", raw_dir)
    logger.info("Completed only: %s", completed_only)

    # Import here so config errors above are reported cleanly
    from pga_pipeline.orchestrator import run

    run(
        db_dsn=db_dsn,
        raw_data_dir=raw_dir,
        years=args.years,
        completed_only=completed_only,
    )


if __name__ == "__main__":
    main()
