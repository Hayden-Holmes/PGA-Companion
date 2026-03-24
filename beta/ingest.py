import time
import sqlite3
from beta.scrape import get_tournament_ids, get_leaderboard
from beta.load_payload import load_tournament_data

DB_PATH    = "golf.db"
START_YEAR = 2015
END_YEAR   = 2026
DELAY_BETWEEN_TOURNAMENTS = 1.5
DELAY_BETWEEN_YEARS       = 3.0
MAX_RETRIES               = 3


def get_already_loaded(db_path: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT tournament_id FROM tournaments").fetchall()
        return set(row[0] for row in rows)
    except Exception:
        return set()
    finally:
        conn.close()


def fetch_with_retry(tournament_id: str, retries: int = MAX_RETRIES) -> dict | None:
    for attempt in range(1, retries + 1):
        result = get_leaderboard(tournament_id)
        if result is not None:
            return result
        if attempt < retries:
            wait = attempt * 2
            print(f"    Retry {attempt}/{retries - 1} for {tournament_id} in {wait}s...")
            time.sleep(wait)
    return None


def ingest_year(year: int, already_loaded: set[str]) -> tuple[int, int, int]:
    fetched = 0
    loaded  = 0
    skipped = 0

    print(f"\n{'=' * 40}")
    print(f"  Year: {year}")
    print(f"{'=' * 40}")

    tournaments = get_tournament_ids(year)

    if not tournaments:
        print(f"  No tournaments found for {year} — skipping")
        return fetched, loaded, skipped

    for t in tournaments:
        tid  = t["id"]
        name = t.get("name", "Unknown")
        start = t.get("start_date", "")

        if tid in already_loaded:
            print(f"  [SKIP]  {tid} — {name}")
            skipped += 1
            continue

        print(f"  [FETCH] {tid} — {name} ({start})")
        fetched += 1

        leaderboard = fetch_with_retry(tid)

        if leaderboard is None:
            print(f"  [FAIL]  {tid} — no data after retries")
            time.sleep(DELAY_BETWEEN_TOURNAMENTS)
            continue

        try:
            load_tournament_data(leaderboard, DB_PATH)
            already_loaded.add(tid)
            loaded += 1
            print(f"  [OK]    {tid} loaded")
        except Exception as e:
            print(f"  [FAIL]  {tid} — DB error: {e}")

        time.sleep(DELAY_BETWEEN_TOURNAMENTS)

    return fetched, loaded, skipped


def main():
    print(f"Starting ingest: {START_YEAR} to {END_YEAR}")
    print(f"Database: {DB_PATH}\n")

    already_loaded = get_already_loaded(DB_PATH)
    print(f"Already in DB: {len(already_loaded)} tournaments")

    total_fetched  = 0
    total_loaded   = 0
    total_skipped  = 0

    for year in range(START_YEAR, END_YEAR + 1):
        fetched, loaded, skipped = ingest_year(year, already_loaded)
        total_fetched  += fetched
        total_loaded   += loaded
        total_skipped  += skipped

        if year < END_YEAR:
            time.sleep(DELAY_BETWEEN_YEARS)

    print(f"\n{'=' * 40}")
    print(f"  Ingest complete")
    print(f"  Fetched:  {total_fetched}")
    print(f"  Loaded:   {total_loaded}")
    print(f"  Skipped:  {total_skipped}")
    print(f"  Failed:   {total_fetched - total_loaded}")
    print(f"{'=' * 40}")


if __name__ == "__main__":
    main()