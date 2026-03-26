"""
pga_pipeline/loaders.py

Idempotent upserts into PostgreSQL.

Rules:
  - Every insert uses ON CONFLICT DO UPDATE so reruns are safe.
  - No data is silently dropped — conflicts update all non-key columns.
  - Each function takes a list of dicts and a psycopg2 connection.
  - Caller commits; these functions do not commit.
"""

import logging
from typing import Any

import psycopg2.extras

logger = logging.getLogger(__name__)


def _upsert(conn, table: str, rows: list[dict], conflict_cols: list[str]):
    """
    Generic upsert: INSERT ... ON CONFLICT (conflict_cols) DO UPDATE SET ...

    All columns in the row dict are included. Conflict columns are excluded
    from the SET clause (they're the key — no point updating them).
    """
    if not rows:
        return

    columns = list(rows[0].keys())
    update_cols = [c for c in columns if c not in conflict_cols]

    col_str = ", ".join(columns)
    val_placeholders = ", ".join(f"%({c})s" for c in columns)
    conflict_str = ", ".join(conflict_cols)

    if update_cols:
        set_str = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
        sql = (
            f"INSERT INTO {table} ({col_str}) "
            f"VALUES ({val_placeholders}) "
            f"ON CONFLICT ({conflict_str}) DO UPDATE SET {set_str}"
        )
    else:
        # All columns are conflict columns — just skip on conflict
        sql = (
            f"INSERT INTO {table} ({col_str}) "
            f"VALUES ({val_placeholders}) "
            f"ON CONFLICT ({conflict_str}) DO NOTHING"
        )

    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, sql, rows, page_size=500)

    logger.info("Upserted %d rows into %s", len(rows), table)


# ---------------------------------------------------------------------------
# Per-table upsert functions
# ---------------------------------------------------------------------------

def upsert_player_season_stats(conn, rows: list[dict]):
    """
    player_season_stats: PK is (player_id, season_year, stat_id).
    """
    _upsert(conn, "player_season_stats", rows, ["player_id", "season_year", "stat_id"])


def upsert_courses(conn, rows: list[dict]):
    """
    courses: PK is course_id.
    Note: par and yardage will be None — not available from API.
    """
    _upsert(conn, "courses", rows, ["course_id"])


def upsert_players(conn, rows: list[dict]):
    """
    players: PK is player_id.
    """
    _upsert(conn, "players", rows, ["player_id"])


def upsert_tournaments(conn, rows: list[dict]):
    """
    tournaments: PK is tournament_id.
    """
    _upsert(conn, "tournaments", rows, ["tournament_id"])


def upsert_rounds(conn, rows: list[dict]):
    """
    rounds: PK is round_id (composite: tournament_id + player_id + round_number).
    """
    _upsert(conn, "rounds", rows, ["round_id"])


def upsert_raw_leaderboard_rows(conn, rows: list[dict]):
    """
    raw_leaderboard_rows: conflict on (event_id, player_id).
    Assumes the schema has a unique constraint on these two columns.
    """
    _upsert(conn, "raw_leaderboard_rows", rows, ["event_id", "player_id"])