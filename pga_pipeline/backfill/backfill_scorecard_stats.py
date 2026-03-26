"""
backfill_scorecard_stats.py
---------------------------
Backfills round-level SG splits, driving, GIR, scrambling, and putting
stats for any rounds currently missing sg_total.

Finds all (tournament_id, player_id) pairs whose rounds have NULL sg_total,
groups them by tournament, then fetches the whole field concurrently per
tournament using a thread pool.

Safe to re-run — skips pairs where the API returns no data, and uses
ON CONFLICT DO UPDATE so partial runs can be resumed cleanly.

Run:
    python backfill_scorecard_stats.py
"""

import json
import logging
import os
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from time import time
from typing import Optional

import psycopg2
import psycopg2.extras
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pga_pipeline.api_client import gql_post

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")

with open(CONFIG_PATH) as f:
    config = json.load(f)

DB_DSN = config["db_dsn"]

# Concurrent API calls per tournament field.
# 10 workers = ~70 player field fetched in ~3s instead of ~35s.
# Increase to 20 if no 429s appear in logs.
MAX_WORKERS = 10

# ---------------------------------------------------------------------------
# GraphQL query — only request fields we actually store
# ---------------------------------------------------------------------------

SCORECARD_STATS_QUERY = """
query ScorecardStatsV3($id: ID!, $playerId: ID!) {
  scorecardStatsV3(id: $id, playerId: $playerId) {
    id
    rounds {
      round
      roundStatus
      strokesGained {
        statId
        total
      }
      performance {
        statId
        total
      }
      scoring {
        statId
        total
      }
    }
  }
}
"""

# Stat IDs confirmed from live payload inspection
SG_OFF_TEE          = "02567"
SG_APPROACH         = "02568"
SG_ARG              = "02569"
SG_PUTTING          = "02564"
SG_TOTAL            = "02675"

PERF_DRIVING_DIST   = "101"
PERF_DRIVING_ACC    = "102"
PERF_GIR            = "103"
PERF_SCRAMBLING     = "130"
PERF_PUTTS_PER_GIR  = "104"

SCORING_BIRDIES     = "107"
SCORING_PARS        = "1005"
SCORING_BOGEYS      = "1002"
SCORING_DOUBLES     = "1003"

# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_scorecard_stats(tournament_id: str, player_id: str) -> Optional[dict]:
    """
    Fetch ScorecardStatsV3 for one player in one tournament.
    Returns the scorecardStatsV3 dict, or None on error/no data.
    Thread-safe — gql_post creates a new requests session per call.
    """
    try:
        data = gql_post(
            "ScorecardStatsV3",
            {"id": tournament_id, "playerId": player_id},
            SCORECARD_STATS_QUERY,
        )
        return data.get("data", {}).get("scorecardStatsV3")
    except requests.exceptions.HTTPError as e:
                logger.warning("HTTP error for %s/%s: %s", tournament_id, player_id, e)
                errors += 1
                time.sleep(2)  # back off on HTTP errors
    except ValueError as e:
        logger.warning("%s/%s: GraphQL error — %s", tournament_id, player_id, e)
        return None
    except Exception as e:
        logger.error("%s/%s: unexpected fetch error — %s", tournament_id, player_id, e)
        return None


# ---------------------------------------------------------------------------
# Parse helpers
# ---------------------------------------------------------------------------

def _sg_num(strokes_gained: list, stat_id: str) -> Optional[float]:
    for sg in strokes_gained:
        if sg.get("statId") == stat_id:
            try:
                return float(sg.get("total", ""))
            except (ValueError, TypeError):
                return None
    return None


def _perf_str(performance: list, stat_id: str) -> Optional[str]:
    for p in performance:
        if p.get("statId") == stat_id:
            return p.get("total")
    return None


def _score_int(scoring: list, stat_id: str) -> Optional[int]:
    for s in scoring:
        if s.get("statId") == stat_id:
            try:
                return int(s.get("total", ""))
            except (ValueError, TypeError):
                return None
    return None


def _parse_leading_float(val: Optional[str]) -> Optional[float]:
    """'284.20 yds' -> 284.2   '65.00% (39/60)' -> 65.0   '1.76' -> 1.76"""
    if not val:
        return None
    try:
        return float(re.search(r"[\d.]+", val).group())
    except (AttributeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Normalize
# ---------------------------------------------------------------------------

def normalize_scorecard_rounds(
    scorecard: dict,
    tournament_id: str,
    player_id: str,
) -> list[dict]:
    """
    Convert a scorecardStatsV3 response into round update dicts.

    round "-1" is the API aggregate row — skipped entirely.
    We compute tournament totals from rounds 1-4 in queries.

    Only OFFICIAL and COMPLETE rounds are included. UPCOMING rounds
    have empty stat arrays and are skipped to avoid overwriting good
    data with NULLs on a re-run.

    round_id mirrors normalize_rounds format: {tournament_id}_{player_id}_{round_number}
    score is excluded — already set by the leaderboard pipeline.
    """
    rows = []
    for r in scorecard.get("rounds") or []:

        # Skip aggregate row — not a real round
        if r.get("round") == "-1":
            continue

        # Skip rounds with no data yet
        if r.get("roundStatus") not in ("OFFICIAL", "COMPLETE"):
            continue

        try:
            round_number = int(r.get("round", ""))
        except (ValueError, TypeError):
            logger.warning(
                "%s/%s: unexpected round value %r — skipping",
                tournament_id, player_id, r.get("round"),
            )
            continue

        sg      = r.get("strokesGained") or []
        perf    = r.get("performance") or []
        scoring = r.get("scoring") or []

        rows.append({
            "round_id":         f"{tournament_id}_{player_id}_{round_number}",
            "player_id":        player_id,
            "tournament_id":    tournament_id,
            "round_number":     round_number,
            "sg_total":         _sg_num(sg, SG_TOTAL),
            "sg_ott":           _sg_num(sg, SG_OFF_TEE),
            "sg_app":           _sg_num(sg, SG_APPROACH),
            "sg_arg":           _sg_num(sg, SG_ARG),
            "sg_putt":          _sg_num(sg, SG_PUTTING),
            "driving_distance": _parse_leading_float(_perf_str(perf, PERF_DRIVING_DIST)),
            "fairways_hit":     _parse_leading_float(_perf_str(perf, PERF_DRIVING_ACC)),
            "gir":              _parse_leading_float(_perf_str(perf, PERF_GIR)),
            "scrambling":       _parse_leading_float(_perf_str(perf, PERF_SCRAMBLING)),
            "putts_per_gir":    _parse_leading_float(_perf_str(perf, PERF_PUTTS_PER_GIR)),
            "birdies":          _score_int(scoring, SCORING_BIRDIES),
            "pars":             _score_int(scoring, SCORING_PARS),
            "bogeys":           _score_int(scoring, SCORING_BOGEYS),
            "double_bogeys":    _score_int(scoring, SCORING_DOUBLES),
        })

    return rows


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------

def get_missing_pairs(conn) -> dict:
    """
    Return missing (tournament_id, player_id) pairs grouped by tournament.
    Only includes rounds where sg_total IS NULL and round_number > 0.
    Ordered by tournament_id so progress logs are easy to follow.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT tournament_id, player_id
            FROM rounds
            WHERE sg_total IS NULL
              AND round_number > 0
            ORDER BY tournament_id, player_id
        """)
        rows = cur.fetchall()

    grouped = defaultdict(list)
    for tournament_id, player_id in rows:
        grouped[tournament_id].append(player_id)
    return dict(grouped)


def upsert_round_stats(conn, rows: list[dict]):
    """
    Upsert SG and performance columns onto existing round rows.
    Never overwrites score or round_date set by the leaderboard pipeline.
    """
    if not rows:
        return

    sql = """
        INSERT INTO rounds (
            round_id, player_id, tournament_id, round_number,
            sg_total, sg_ott, sg_app, sg_arg, sg_putt,
            driving_distance, fairways_hit, gir,
            scrambling, putts_per_gir,
            birdies, pars, bogeys, double_bogeys
        )
        VALUES (
            %(round_id)s, %(player_id)s, %(tournament_id)s, %(round_number)s,
            %(sg_total)s, %(sg_ott)s, %(sg_app)s, %(sg_arg)s, %(sg_putt)s,
            %(driving_distance)s, %(fairways_hit)s, %(gir)s,
            %(scrambling)s, %(putts_per_gir)s,
            %(birdies)s, %(pars)s, %(bogeys)s, %(double_bogeys)s
        )
        ON CONFLICT (round_id) DO UPDATE SET
            sg_total         = EXCLUDED.sg_total,
            sg_ott           = EXCLUDED.sg_ott,
            sg_app           = EXCLUDED.sg_app,
            sg_arg           = EXCLUDED.sg_arg,
            sg_putt          = EXCLUDED.sg_putt,
            driving_distance = EXCLUDED.driving_distance,
            fairways_hit     = EXCLUDED.fairways_hit,
            gir              = EXCLUDED.gir,
            scrambling       = EXCLUDED.scrambling,
            putts_per_gir    = EXCLUDED.putts_per_gir,
            birdies          = EXCLUDED.birdies,
            pars             = EXCLUDED.pars,
            bogeys           = EXCLUDED.bogeys,
            double_bogeys    = EXCLUDED.double_bogeys
    """
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, sql, rows, page_size=200)


# ---------------------------------------------------------------------------
# Worker — called from thread pool
# ---------------------------------------------------------------------------

def _fetch_player(tournament_id: str, player_id: str) -> tuple:
    """
    Fetch and normalize one player's scorecard stats.
    Returns (tournament_id, player_id, rows) — rows is [] on failure.
    """
    scorecard = fetch_scorecard_stats(tournament_id, player_id)
    if not scorecard:
        return tournament_id, player_id, []
    rows = normalize_scorecard_rounds(scorecard, tournament_id, player_id)
    return tournament_id, player_id, rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    conn = psycopg2.connect(DB_DSN)
    conn.autocommit = False

    by_tournament = get_missing_pairs(conn)
    total_pairs = sum(len(v) for v in by_tournament.values())

    logger.info(
        "Found %d tournaments, %d (tournament, player) pairs with missing SG stats",
        len(by_tournament), total_pairs,
    )

    total_updated = 0
    total_skipped = 0
    total_errors  = 0

    for t_idx, (tournament_id, player_ids) in enumerate(by_tournament.items(), 1):
        logger.info(
            "[%d/%d] %s — fetching %d players (max_workers=%d)",
            t_idx, len(by_tournament), tournament_id, len(player_ids), MAX_WORKERS,
        )

        all_rows = []
        skipped  = 0

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(_fetch_player, tournament_id, pid): pid
                for pid in player_ids
            }
            for future in as_completed(futures):
                try:
                    _, player_id, rows = future.result()
                    if rows:
                        all_rows.extend(rows)
                    else:
                        logger.warning(
                            "%s/%s: no usable rounds returned",
                            tournament_id, futures[future],
                        )
                        skipped += 1
                except Exception as e:
                    logger.error("%s: worker error — %s", tournament_id, e)
                    skipped += 1

        # Write all rows for this tournament in one transaction
        if all_rows:
            try:
                upsert_round_stats(conn, all_rows)
                conn.commit()
                total_updated += len(all_rows)
                logger.info(
                    "%s: committed %d round rows (%d players skipped)",
                    tournament_id, len(all_rows), skipped,
                )
            except Exception as e:
                logger.error("%s: DB error — %s", tournament_id, e)
                conn.rollback()
                total_errors += len(all_rows)
        else:
            logger.warning("%s: no rows to commit", tournament_id)

        total_skipped += skipped

    conn.close()

    logger.info(
        "Done. Rounds updated=%d  Players skipped=%d  Errors=%d",
        total_updated, total_skipped, total_errors,
    )
    logger.info(
        "Check: SELECT COUNT(*) FROM rounds "
        "WHERE sg_total IS NOT NULL AND round_number > 0;"
    )


if __name__ == "__main__":
    main()