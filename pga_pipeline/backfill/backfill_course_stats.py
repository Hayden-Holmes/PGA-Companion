"""
backfill_course_stats.py
------------------------
Backfills par and yardage for any course currently missing them.

Finds all tournament IDs whose courses have NULL par, fetches courseStats
for each, and updates the courses table.

Safe to re-run — skips tournaments where courseStats returns null.

Run:
    python backfill_course_stats.py
"""

import json
import logging
import os
import sys

import psycopg2
import psycopg2.extras
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

with open(CONFIG_PATH) as f:
    config = json.load(f)

DB_DSN = config["db_dsn"]

ENDPOINT = "https://orchestrator.pgatour.com/graphql"
HEADERS = {
    "Content-Type": "application/json",
    "x-api-key": "da2-gsrx5bibzbb4njvhl7t37wqyl4",
    "origin": "https://www.pgatour.com",
    "referer": "https://www.pgatour.com/",
    "x-pgat-platform": "web",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/146.0.0.0 Safari/537.36"
    ),
}

COURSE_STATS_QUERY = """
query CourseStats($tournamentId: ID!) {
  courseStats(tournamentId: $tournamentId) {
    tournamentId
    courses {
      courseId
      courseName
      par
      yardage
    }
  }
}
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def post(tournament_id):
    body = {
        "operationName": "CourseStats",
        "variables": {"tournamentId": tournament_id},
        "query": COURSE_STATS_QUERY,
    }
    resp = requests.post(ENDPOINT, json=body, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    parsed = resp.json()
    errors = parsed.get("errors")
    if errors:
        raise ValueError([e["message"] for e in errors])
    return parsed.get("data", {}).get("courseStats")


def parse_yardage(yardage_str):
    if not yardage_str:
        return None
    try:
        return int("".join(c for c in yardage_str if c.isdigit()))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    conn = psycopg2.connect(DB_DSN)
    conn.autocommit = False

    with conn.cursor() as cur:
        # Find all tournament_ids where at least one course has NULL par
        cur.execute("""
            SELECT DISTINCT t.tournament_id
            FROM tournaments t
            JOIN courses c ON c.course_id = t.course_id
            WHERE c.par IS NULL
            AND t.tournament_id IS NOT NULL
            ORDER BY t.tournament_id
        """)
        rows = cur.fetchall()

    tournament_ids = [r[0] for r in rows]
    logger.info("Found %d tournaments with courses missing par/yardage", len(tournament_ids))

    updated = 0
    skipped = 0
    errors = 0

    for tid in tournament_ids:
        try:
            result = post(tid)
            if result is None:
                logger.warning("%s: courseStats returned null — skipping", tid)
                skipped += 1
                continue

            courses = result.get("courses") or []
            if not courses:
                logger.warning("%s: courseStats returned empty courses[]", tid)
                skipped += 1
                continue

            with conn.cursor() as cur:
                for c in courses:
                    course_id = c.get("courseId")
                    par = c.get("par")
                    yardage = parse_yardage(c.get("yardage"))

                    if course_id is None:
                        continue

                    cur.execute("""
                        UPDATE courses
                        SET par = %s, yardage = %s
                        WHERE course_id = %s
                        AND par IS NULL
                    """, (par, yardage, course_id))

            conn.commit()
            filled = [c for c in courses if c.get("par") is not None]
            logger.info("%s: updated %d course(s)", tid, len(filled))
            updated += len(filled)

        except ValueError as e:
            logger.warning("%s: GraphQL error — %s", tid, e)
            errors += 1
        except Exception as e:
            logger.error("%s: unexpected error — %s", tid, e)
            conn.rollback()
            errors += 1

    conn.close()

    logger.info("Done. Updated=%d  Skipped=%d  Errors=%d", updated, skipped, errors)
    logger.info("Run this to check: SELECT COUNT(*) FROM courses WHERE par IS NOT NULL;")


if __name__ == "__main__":
    main()
