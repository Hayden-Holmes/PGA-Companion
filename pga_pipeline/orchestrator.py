"""
pga_pipeline/orchestrator.py

Top-level pipeline: schedule → details → leaderboard → normalize → load.

Design:
  - Processes one year at a time.
  - Skips upcoming tournaments for leaderboard fetch (no data exists yet).
  - Saves raw files before any DB work so data is never lost on failure.
  - Each tournament is processed independently; one failure doesn't abort the run.
  - All DB writes happen in a single transaction per tournament.
"""

import logging
from typing import Optional

import psycopg2

from .fetchers import (
    fetch_all_stat_details,
    fetch_course_stats,
    fetch_details,
    fetch_leaderboard,
    fetch_schedule,
    fetch_scorecard_stats,          
)
 
from .normalizers import (
    extract_courses_from_course_stats,
    extract_courses_from_leaderboard,
    extract_players_from_leaderboard,
    extract_raw_rows_from_leaderboard,
    extract_rounds_from_leaderboard,
    extract_scorecard_stats,        
    extract_season_stats,
    flatten_schedule,
    normalize_course,
    normalize_tournament,
)
from .loaders import (
    upsert_courses,
    upsert_player_season_stats,
    upsert_players,
    upsert_raw_leaderboard_rows,
    upsert_rounds,
    upsert_tournaments,
)

from .raw_store import RawStore

import time
_SCORECARD_RATE_LIMIT = 0.3  

logger = logging.getLogger(__name__)


class Pipeline:
    def __init__(self, db_conn, raw_store: RawStore):
        self.conn = db_conn
        self.store = raw_store

    # ------------------------------------------------------------------
    # Step 1: Fetch and store schedule
    # ------------------------------------------------------------------

    def fetch_and_store_schedule(self, year: str) -> list[dict]:
        """
        Fetch the schedule for a year, save to disk, return flat list
        of ScheduleTournament dicts.
        """
        raw = fetch_schedule(year)
        self.store.save_schedule(year, raw)
        flat = flatten_schedule(raw)
        logger.info("Schedule year=%s: %d total tournaments", year, len(flat))
        return flat

    # ------------------------------------------------------------------
    # Step 2: Fetch and store tournament details (batched)
    # ------------------------------------------------------------------

    def fetch_and_store_details(self, tournament_ids: list[str]) -> dict[str, dict]:
        """
        Fetch details for a list of IDs (batched), save each to disk,
        return a dict keyed by tournament_id.
        """
        # Fetch all at once — API supports list of IDs
        raw = fetch_details(tournament_ids)
        self.store.save_details("batch_" + "_".join(tournament_ids[:3]), raw)

        details_by_id = {}
        for t in raw.get("data", {}).get("tournaments") or []:
            tid = t.get("id")
            if tid:
                details_by_id[tid] = t
                self.store.save_details(tid, {"data": {"tournaments": [t]}})

        missing = [tid for tid in tournament_ids if tid not in details_by_id]
        if missing:
            logger.warning("Details missing for tournament IDs: %s", missing)

        return details_by_id

    # ------------------------------------------------------------------
    # Step 3: Process one completed tournament end-to-end
    # ------------------------------------------------------------------

    def process_tournament(
        self,
        schedule_row: dict,
        details_row,
        season_year: str,
    ):
        """
        For one tournament:
          1. Normalize tournament row and upsert.
          2. Normalize and upsert course (from details if available).
          3. Fetch course stats (par, yardage).
          4. Fetch leaderboard (skip if not COMPLETED).
          5. Normalize and upsert players, rounds, raw_leaderboard_rows.
          6. Fetch scorecard stats per player and upsert SG/performance
             columns onto the rounds rows inserted in step 5.
 
        All DB writes commit per-entity so a scorecard fetch failure
        for one player never rolls back the whole tournament.
        """
        tid = schedule_row["id"]
        status = schedule_row.get("tournamentStatus", "")
 
        logger.info(
            "Processing tournament %s (%s) status=%s",
            tid, schedule_row.get("tournamentName"), status,
        )
 
        # --- Tournament row ---
        tournament_row = normalize_tournament(schedule_row, details_row)
 
        # --- Course rows ---
        course_rows = []
        if details_row:
            courses = details_row.get("courses") or []
            location = ", ".join(filter(None, [
                schedule_row.get("city"),
                schedule_row.get("state"),
                schedule_row.get("country"),
            ]))
            for c in courses:
                course_rows.append(normalize_course(c, location))
        else:
            logger.warning(
                "tournament_id=%s: no details available, course row will be incomplete",
                tid,
            )
 
        # --- DB: tournament and courses ---
        location = ", ".join(filter(None, [
            schedule_row.get("city"),
            schedule_row.get("state"),
            schedule_row.get("country"),
        ]))
 
        with self.conn:
            if course_rows:
                upsert_courses(self.conn, course_rows)
            upsert_tournaments(self.conn, [tournament_row])
 
        # --- Course stats: par and yardage ---
        course_stats = fetch_course_stats(tid)
        if course_stats:
            cs_courses = extract_courses_from_course_stats(course_stats, location)
            if cs_courses:
                with self.conn:
                    upsert_courses(self.conn, cs_courses)
                logger.info(
                    "Updated par/yardage for %d course(s) from courseStats for %s",
                    len(cs_courses), tid,
                )
 
        # --- Leaderboard: only for completed tournaments ---
        if status != "COMPLETED":
            logger.info("Skipping leaderboard for %s (status=%s)", tid, status)
            return
 
        decoded_lb = self.store.load_leaderboard(tid)
        if decoded_lb is None:
            decoded_lb = fetch_leaderboard(tid)
            if decoded_lb is None:
                logger.warning(
                    "No leaderboard available for completed tournament %s", tid
                )
                return
            self.store.save_leaderboard(tid, decoded_lb)
        else:
            logger.info("Loaded leaderboard from disk for %s", tid)
 
        # --- Normalize and load leaderboard data ---
        season_year_int = int(season_year)
        lb_courses = extract_courses_from_leaderboard(decoded_lb, location)
        players    = extract_players_from_leaderboard(decoded_lb)
        rounds     = extract_rounds_from_leaderboard(decoded_lb, tid)
        raw_rows   = extract_raw_rows_from_leaderboard(decoded_lb, tid, season_year_int)
 
        with self.conn:
            if lb_courses:
                upsert_courses(self.conn, lb_courses)
            if players:
                upsert_players(self.conn, players)
            if rounds:
                upsert_rounds(self.conn, rounds)
            if raw_rows:
                upsert_raw_leaderboard_rows(self.conn, raw_rows)
 
        logger.info(
            "Loaded %s: %d players, %d rounds, %d raw rows",
            tid, len(players), len(rounds), len(raw_rows),
        )
 
        # --- Scorecard stats: one call per player ---
        # Rounds are now in the DB. We fetch SG splits and performance stats
        # for each player and upsert them onto the existing round rows.
        # A failure for one player is logged and skipped — never aborts
        # the rest of the field.
        if not players:
            logger.info("%s: no players found, skipping scorecard stats", tid)
            return
 
        logger.info(
            "%s: fetching scorecard stats for %d players", tid, len(players)
        )
 
        sc_updated = 0
        sc_skipped = 0
        sc_errors  = 0
 
        for player in players:
            player_id = player.get("player_id")
            if not player_id:
                continue
 
            scorecard = fetch_scorecard_stats(tid, player_id)
 
            if scorecard is None:
                sc_skipped += 1
                time.sleep(_SCORECARD_RATE_LIMIT)
                continue
 
            stat_rows = extract_scorecard_stats(scorecard, tid, player_id)
 
            if not stat_rows:
                sc_skipped += 1
                time.sleep(_SCORECARD_RATE_LIMIT)
                continue
 
            try:
                with self.conn:
                    upsert_rounds(self.conn, stat_rows)
                sc_updated += len(stat_rows)
            except Exception as e:
                logger.error(
                    "%s/player %s: scorecard DB error — %s", tid, player_id, e
                )
                try:
                    self.conn.rollback()
                except Exception:
                    pass
                sc_errors += 1
 
            time.sleep(_SCORECARD_RATE_LIMIT)
 
        logger.info(
            "%s scorecard stats: %d rounds updated, %d skipped, %d errors",
            tid, sc_updated, sc_skipped, sc_errors,
        )

    # ------------------------------------------------------------------
    # Top-level: run one year
    # ------------------------------------------------------------------

    def run_year(self, year: str, completed_only: bool = True):
        """
        Run the full pipeline for one season year.

        completed_only=True (default): only fetch leaderboards for completed
        tournaments. Tournament/course rows are still inserted for all.
        """
        logger.info("=== Starting pipeline for year=%s ===", year)

        schedule = self.fetch_and_store_schedule(year)

        all_ids = [t["id"] for t in schedule]

        # Fetch details in one batched call
        # Split into chunks if needed (API may have limits — 50 is conservative)
        details_by_id = {}
        chunk_size = 50
        for i in range(0, len(all_ids), chunk_size):
            chunk = all_ids[i : i + chunk_size]
            chunk_details = self.fetch_and_store_details(chunk)
            details_by_id.update(chunk_details)

        # Process each tournament
        errors = []
        for sched_row in schedule:
            tid = sched_row["id"]
            details_row = details_by_id.get(tid)

            # Determine season_year for this row
            sy = None
            if details_row:
                sy = details_row.get("seasonYear", year)
            else:
                sy = year

            try:
                self.process_tournament(sched_row, details_row, sy)
            except Exception as e:
                logger.error("Failed processing tournament %s: %s", tid, e, exc_info=True)
                errors.append((tid, str(e)))
                # Roll back any partial transaction for this tournament
                try:
                    self.conn.rollback()
                except Exception:
                    pass

        logger.info(
            "=== Year=%s complete. %d tournaments processed, %d errors ===",
            year, len(schedule), len(errors),
        )
        if errors:
            logger.warning("Errors: %s", errors)

        # Fetch and load season stats once per year.
        # Makes 8 API calls (one per stat ID) — statDetails returns full
        # player rankings unlike statOverview which only returns top 3.
        logger.info("Fetching season stat details for year=%s", year)
        stat_details_list = fetch_all_stat_details(year)
        if stat_details_list:
            stat_rows = extract_season_stats(stat_details_list)

            # Upsert any new players found in stat data into players table
            stat_players = {}
            for detail in stat_details_list:
                for row in detail.get("rows") or []:
                    if row.get("__typename") != "StatDetailsPlayer":
                        continue
                    pid = row.get("playerId")
                    if pid and pid not in stat_players:
                        stat_players[pid] = {
                            "player_id": pid,
                            "player_name": row.get("playerName"),
                            "country": row.get("country"),
                        }

            if stat_players:
                with self.conn:
                    upsert_players(self.conn, list(stat_players.values()))
                logger.info(
                    "Upserted %d players from stat details for year=%s",
                    len(stat_players), year,
                )

            if stat_rows:
                with self.conn:
                    upsert_player_season_stats(self.conn, stat_rows)
                logger.info(
                    "Loaded %d season stat rows for year=%s", len(stat_rows), year
                )


def run(db_dsn: str, raw_data_dir: str, years: list[str], completed_only: bool = True):
    """
    Entry point called by run.py.

    db_dsn: PostgreSQL connection string, e.g.
            "host=localhost dbname=golf user=postgres password=secret"
    raw_data_dir: directory for raw JSON files
    years: list of year strings, e.g. ["2024", "2025", "2026"]
    """
    store = RawStore(raw_data_dir)

    conn = psycopg2.connect(db_dsn)
    conn.autocommit = False

    try:
        pipeline = Pipeline(conn, store)
        for year in years:
            pipeline.run_year(year, completed_only=completed_only)
    finally:
        conn.close()