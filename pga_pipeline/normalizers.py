"""
pga_pipeline/normalizers.py

Transforms raw API response dicts into clean dicts that match
the target PostgreSQL schema columns exactly.

Rules:
  - Every field mapping is explicit. Nothing is guessed.
  - If a field is absent from the source, it is set to None and logged.
  - No DB calls happen here — pure data transformation.
  - Functions return lists of dicts ready for loaders.py to insert.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def ms_to_date(ms_timestamp: int) -> Optional[datetime.date]:
    """Convert Unix millisecond timestamp to a date object (UTC)."""
    if ms_timestamp is None:
        return None
    return datetime.fromtimestamp(ms_timestamp / 1000, tz=timezone.utc).date()


def parse_end_date(date_str: str, start_ms: int, season_year: str) -> Optional[datetime.date]:
    """
    Derive end date from schedule's `date` string field.

    The `date` field looks like: "Jan 15 - 18" or "Feb 26 - Mar 1"
    There is no clean end timestamp anywhere in the API.

    Strategy:
      - Parse the end day from the string.
      - If the end part contains a month name, use that month.
      - Otherwise use the same month as startDate.
      - Combine with season_year as the year.

    Returns None and logs a warning if parsing fails.
    """
    if not date_str or not start_ms:
        return None

    try:
        year = int(season_year)
        start_date = ms_to_date(start_ms)

        # Normalise: "Jan 15 - 18"  or  "Feb 26 - Mar 1"
        parts = date_str.strip().split("-")
        if len(parts) != 2:
            logger.warning("Unexpected date format, cannot parse end date: %r", date_str)
            return None

        end_part = parts[1].strip()  # e.g. "18" or "Mar 1"
        end_tokens = end_part.split()

        month_abbrs = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        }

        if len(end_tokens) == 1:
            # Same month as start, e.g. "18"
            end_day = int(end_tokens[0])
            end_month = start_date.month
        elif len(end_tokens) == 2:
            # Different month, e.g. "Mar 1"
            end_month = month_abbrs.get(end_tokens[0].lower())
            if end_month is None:
                logger.warning("Unrecognised month in date string: %r", date_str)
                return None
            end_day = int(end_tokens[1])
        else:
            logger.warning("Cannot parse end date from: %r", date_str)
            return None

        return datetime(year, end_month, end_day).date()

    except Exception as e:
        logger.warning("parse_end_date failed for %r: %s", date_str, e)
        return None


def parse_yardage(yardage_str: Optional[str]) -> Optional[int]:
    """'7,352' -> 7352. Returns None if absent or unparseable."""
    if not yardage_str:
        return None
    try:
        return int(re.sub(r"[^\d]", "", yardage_str))
    except ValueError:
        logger.warning("Could not parse yardage string: %r", yardage_str)
        return None


def parse_purse(purse_str: Optional[str]) -> Optional[int]:
    """'$9,100,000' -> 9100000. Returns None if absent or unparseable."""
    if not purse_str:
        return None
    try:
        return int(re.sub(r"[^\d]", "", purse_str))
    except ValueError:
        logger.warning("Could not parse purse string: %r", purse_str)
        return None


# ---------------------------------------------------------------------------
# Flatten schedule groups
# ---------------------------------------------------------------------------

def flatten_schedule(schedule_response: dict) -> list[dict]:
    """
    The schedule response nests tournaments inside groups:
      data.schedule.completed[].tournaments[]
      data.schedule.upcoming[].tournaments[]

    Returns a flat list of raw ScheduleTournament dicts with a
    `_section` key added ("completed" or "upcoming").
    """
    result = []
    sched = schedule_response.get("data", {}).get("schedule", {})

    for section in ("completed", "upcoming"):
        for group in sched.get(section) or []:
            for t in group.get("tournaments") or []:
                t["_section"] = section
                result.append(t)

    return result


# ---------------------------------------------------------------------------
# Tournaments
# ---------------------------------------------------------------------------

def normalize_tournament(
    schedule_row: dict,
    details_row: Optional[dict],
) -> dict:
    """
    Build a tournaments table row from a schedule tournament entry
    and its corresponding details entry (may be None for upcoming).

    Field sources:
      tournament_id  <- schedule.id
      event_id       <- schedule.id  (no separate event ID exists)
      tournament_name <- schedule.tournamentName
      season_year    <- details.seasonYear  (fallback: parse from schedule.startDate year)
      start_date     <- schedule.startDate  (ms timestamp)
      end_date       <- derived from schedule.date string
      course_id      <- details.courses[hostCourse=true].id  (None if details absent)
    """
    tid = schedule_row.get("id")
    start_ms = schedule_row.get("startDate")
    date_str = schedule_row.get("date")

    # season_year: prefer details, fall back to parsing year from startDate
    season_year = None
    if details_row:
        season_year = details_row.get("seasonYear")
    if season_year is None and start_ms:
        season_year = str(datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).year)

    if season_year is None:
        logger.warning("tournament_id=%s: cannot determine season_year", tid)

    # course_id from details (the only place it appears)
    course_id = None
    if details_row:
        courses = details_row.get("courses") or []
        host = next((c for c in courses if c.get("hostCourse")), None)
        if host is None and courses:
            host = courses[0]
            logger.warning(
                "tournament_id=%s: no hostCourse=true, using first course %s",
                tid, host.get("id"),
            )
        if host:
            course_id = host.get("id")
    if course_id is None:
        logger.warning("tournament_id=%s: course_id is None (details absent or no courses)", tid)

    return {
        "tournament_id": tid,
        "event_id": tid,  # same ID — no separate event ID exists
        "tournament_name": schedule_row.get("tournamentName"),
        "season_year": int(season_year) if season_year else None,
        "start_date": ms_to_date(start_ms),
        "end_date": parse_end_date(date_str, start_ms, season_year) if season_year else None,
        "course_id": course_id,
    }


# ---------------------------------------------------------------------------
# Courses
# ---------------------------------------------------------------------------

def normalize_course(course_dict: dict, location_str: Optional[str] = None) -> dict:
    """
    Build a courses table row.
    course_dict is from details.courses[] or leaderboard.courses[].

    par and yardage are absent from the API — both set to None.
    """
    cid = course_dict.get("id")
    if cid is None:
        logger.warning("Course dict missing id: %s", course_dict)

    return {
        "course_id": cid,
        "course_name": course_dict.get("courseName"),
        "location": location_str,  # passed in from schedule city/state/country
        "par": None,       # NOT AVAILABLE in any payload
        "yardage": None,   # NOT AVAILABLE in any payload
    }


# ---------------------------------------------------------------------------
# Players
# ---------------------------------------------------------------------------

def normalize_player(player_dict: dict) -> dict:
    """
    Build a players table row from a leaderboard player.player dict.
    """
    pid = player_dict.get("id")
    if pid is None:
        logger.warning("Player dict missing id: %s", player_dict)

    return {
        "player_id": pid,
        "player_name": player_dict.get("displayName"),
        "country": player_dict.get("country"),
    }


# ---------------------------------------------------------------------------
# Rounds
# ---------------------------------------------------------------------------

def normalize_rounds(player_entry: dict, tournament_id: str) -> list[dict]:
    """
    Build round table rows for one player entry from the leaderboard.

    scoringData.rounds is a flat list of up to 4 gross score strings:
      ["63", "69", "68", "64"]

    One row is created per round that has a score.

    Fields that are NOT available from this payload (all set to None):
      round_date, gir, fairways_hit, driving_distance, putts,
      sg_total, sg_ott, sg_app, sg_arg, sg_putt
    """
    player_id = player_entry.get("id")
    scoring = player_entry.get("scoringData", {})
    round_scores = scoring.get("rounds") or []

    rows = []
    for i, score_str in enumerate(round_scores):
        round_number = i + 1  # API is 0-indexed, schema is 1-indexed

        # Score is a string like "63" — convert to int, handle non-numeric
        # (e.g. "--" for rounds not yet played)
        try:
            score_int = int(score_str)
        except (ValueError, TypeError):
            logger.debug(
                "tournament=%s player=%s round=%d: score %r is not numeric, skipping",
                tournament_id, player_id, round_number, score_str,
            )
            continue

        rows.append({
            "round_id": f"{tournament_id}_{player_id}_{round_number}",
            "player_id": player_id,
            "tournament_id": tournament_id,
            "round_number": round_number,
            "round_date": None,        # NOT AVAILABLE in any payload
            "score": score_int,
            "gir": None,               # NOT AVAILABLE — requires separate stats endpoint
            "fairways_hit": None,      # NOT AVAILABLE — requires separate stats endpoint
            "driving_distance": None,  # NOT AVAILABLE — requires separate stats endpoint
            "putts": None,             # NOT AVAILABLE — requires separate stats endpoint
            "sg_total": None,          # NOT AVAILABLE — requires separate stats endpoint
            "sg_ott": None,            # NOT AVAILABLE — requires separate stats endpoint
            "sg_app": None,            # NOT AVAILABLE — requires separate stats endpoint
            "sg_arg": None,            # NOT AVAILABLE — requires separate stats endpoint
            "sg_putt": None,           # NOT AVAILABLE — requires separate stats endpoint
        })

    return rows


# ---------------------------------------------------------------------------
# Raw leaderboard rows
# ---------------------------------------------------------------------------

def normalize_raw_leaderboard_row(
    player_entry: dict,
    tournament_id: str,
    season_year: int,
) -> dict:
    """
    Build a raw_leaderboard_rows table row for one player.

    round_N_score: gross stroke score per round (int), or None if not played.
    total_score: total gross strokes (int).
    """
    player_id = player_entry.get("id")
    player = player_entry.get("player", {})
    scoring = player_entry.get("scoringData", {})
    rounds = scoring.get("rounds") or []

    def safe_round_score(index: int) -> Optional[int]:
        if index >= len(rounds):
            return None
        try:
            return int(rounds[index])
        except (ValueError, TypeError):
            return None

    total_strokes_str = scoring.get("totalStrokes")
    try:
        total_score = int(total_strokes_str) if total_strokes_str else None
    except (ValueError, TypeError):
        total_score = None

    return {
        "event_id": tournament_id,
        "season_year": season_year,
        "player_id": player_id,
        "player_name": player.get("displayName"),
        "round_1_score": safe_round_score(0),
        "round_2_score": safe_round_score(1),
        "round_3_score": safe_round_score(2),
        "round_4_score": safe_round_score(3),
        "total_score": total_score,
        "source_url": (
            f"https://orchestrator.pgatour.com/graphql"
            f"?op=LeaderboardCompressedV3&id={tournament_id}"
        ),
    }


# ---------------------------------------------------------------------------
# Top-level normalize functions that process a whole leaderboard payload
# ---------------------------------------------------------------------------

def extract_season_stats(stat_details_list: list[dict]) -> list[dict]:
    """
    Flatten a list of statDetails responses into player_season_stats rows.

    Each statDetails response covers one stat for all players in a season.
    rows[] is a union — we only process StatDetailsPlayer entries.
    The primary stat value is stats[0].statValue (the "Avg" entry).

    Returns one row per (player_id, season_year, stat_id).
    """
    rows = []
    for detail in stat_details_list:
        stat_id = detail.get("statId")
        stat_title = detail.get("statTitle")
        tour_avg = detail.get("tourAvg")
        year = detail.get("year")

        if year is None:
            logger.warning("statDetails missing year for statId=%s", stat_id)
            continue

        for row in detail.get("rows") or []:
            # Skip StatDetailTourAvg rows — only process StatDetailsPlayer
            if row.get("__typename") != "StatDetailsPlayer":
                continue

            player_id = row.get("playerId")
            if not player_id:
                continue

            # Primary value is stats[0] — the "Avg" entry
            stats = row.get("stats") or []
            stat_value = stats[0].get("statValue") if stats else None

            rank_val = row.get("rank")
            try:
                rank_int = int(rank_val) if rank_val is not None else None
            except (ValueError, TypeError):
                rank_int = None

            rows.append({
                "player_id": player_id,
                "season_year": int(year),
                "stat_id": stat_id,
                "stat_name": stat_title,
                "stat_value": stat_value,
                "stat_title": stats[0].get("statName") if stats else None,
                "tour_avg": tour_avg,
                "rank": rank_int,
            })

    return rows


def extract_courses_from_course_stats(
    course_stats: dict, location: Optional[str]
) -> list[dict]:
    """
    Build course rows from a courseStats response.
    courseId here matches courses[].id from details/leaderboard payloads.
    yardage arrives as a string e.g. "7,352" — parsed to int.
    par arrives as an int.
    """
    rows = []
    for c in course_stats.get("courses") or []:
        cid = c.get("courseId")
        if cid is None:
            logger.warning("courseStats course missing courseId: %s", c)
            continue
        rows.append({
            "course_id": cid,
            "course_name": c.get("courseName"),
            "location": location,
            "par": c.get("par"),
            "yardage": parse_yardage(c.get("yardage")),
        })
    return rows


def extract_players_from_leaderboard(decoded_lb: dict) -> list[dict]:
    """Return list of normalized player dicts from a decoded leaderboard."""
    players = decoded_lb.get("players") or []
    return [normalize_player(p["player"]) for p in players if p.get("player")]


def extract_courses_from_leaderboard(decoded_lb: dict, location: Optional[str]) -> list[dict]:
    """Return list of normalized course dicts from a decoded leaderboard."""
    courses = decoded_lb.get("courses") or []
    return [normalize_course(c, location) for c in courses]


def extract_rounds_from_leaderboard(decoded_lb: dict, tournament_id: str) -> list[dict]:
    """Return list of normalized round dicts from a decoded leaderboard."""
    rows = []
    for player_entry in decoded_lb.get("players") or []:
        rows.extend(normalize_rounds(player_entry, tournament_id))
    return rows


def extract_raw_rows_from_leaderboard(
    decoded_lb: dict, tournament_id: str, season_year: int
) -> list[dict]:
    """Return list of raw_leaderboard_rows dicts from a decoded leaderboard."""
    return [
        normalize_raw_leaderboard_row(p, tournament_id, season_year)
        for p in decoded_lb.get("players") or []
    ]

# ---------------------------------------------------------------------------
# Scorecard stats normalizer
#
# Confirmed stat IDs from live payload inspection:
#   02567 = SG Off The Tee
#   02568 = SG Approach to Green
#   02569 = SG Around The Green
#   02564 = SG Putting
#   02675 = SG Total
#   101   = Driving Distance
#   102   = Driving Accuracy
#   103   = Greens in Regulation
#   130   = Scrambling
#   104   = Putts per GIR
#   107   = Birdies
#   1005  = Pars
#   1002  = Bogeys
#   1003  = Double Bogeys
# ---------------------------------------------------------------------------

_SG_OFF_TEE  = "02567"
_SG_APPROACH = "02568"
_SG_ARG      = "02569"
_SG_PUTTING  = "02564"
_SG_TOTAL    = "02675"

_PERF_DRIVING_DIST  = "101"
_PERF_DRIVING_ACC   = "102"
_PERF_GIR           = "103"
_PERF_SCRAMBLING    = "130"
_PERF_PUTTS_PER_GIR = "104"

_SCORING_BIRDIES = "107"
_SCORING_PARS    = "1005"
_SCORING_BOGEYS  = "1002"
_SCORING_DOUBLES = "1003"


def _sg_num(strokes_gained: list, stat_id: str) -> Optional[float]:
    """Extract totalNum for a statId from strokesGained[]."""
    for sg in strokes_gained:
        if sg.get("statId") == stat_id:
            val = sg.get("totalNum")
            return float(val) if val is not None else None
    return None


def _perf_str(performance: list, stat_id: str) -> Optional[str]:
    """Extract raw total string for a statId from performance[]."""
    for p in performance:
        if p.get("statId") == stat_id:
            return p.get("total")
    return None


def _score_int(scoring: list, stat_id: str) -> Optional[int]:
    """Extract total as int for a statId from scoring[]."""
    for s in scoring:
        if s.get("statId") == stat_id:
            try:
                return int(s.get("total", ""))
            except (ValueError, TypeError):
                return None
    return None


def _parse_leading_float(val: Optional[str]) -> Optional[float]:
    """
    Extract the first float from a stat string.
    '284.20 yds' -> 284.2
    '65.00% (39/60)' -> 65.0
    '1.76' -> 1.76
    """
    if not val:
        return None
    try:
        return float(re.search(r"[\d.]+", val).group())
    except (AttributeError, ValueError):
        return None


def normalize_scorecard_stats(
    scorecard: dict,
    tournament_id: str,
    player_id: str,
) -> list[dict]:
    """
    Convert a scorecardStatsV3 response into round update dicts.

    round "-1" is a pre-computed API aggregate ("All") — skipped entirely.
    We compute tournament totals ourselves from rounds 1-4 in queries.
    Rounds "1"-"4" map directly to round_number 1-4.

    Only OFFICIAL rounds are included. UPCOMING rounds have empty stat
    arrays and are skipped to avoid overwriting good data on a re-run.

    round_id format matches normalize_rounds: {tournament_id}_{player_id}_{round_number}
    Score is intentionally excluded — already set by the leaderboard pipeline.
    """
    rows = []

    for r in scorecard.get("rounds") or []:
        # Skip the API aggregate row — not a real round
        if r.get("round") == "-1":
            continue

        # Skip rounds with no data yet
        if r.get("roundStatus") not in ("OFFICIAL", "COMPLETE"):
            continue

        try:
            round_number = int(r.get("round", ""))
        except (ValueError, TypeError):
            logger.warning(
                "normalize_scorecard_stats: unexpected round value %r for %s/%s — skipping",
                r.get("round"), tournament_id, player_id,
            )
            continue

        sg      = r.get("strokesGained") or []
        perf    = r.get("performance") or []
        scoring = r.get("scoring") or []

        rows.append({
            "round_id":          f"{tournament_id}_{player_id}_{round_number}",
            "player_id":         player_id,
            "tournament_id":     tournament_id,
            "round_number":      round_number,
            "sg_total":          _sg_num(sg, _SG_TOTAL),
            "sg_ott":            _sg_num(sg, _SG_OFF_TEE),
            "sg_app":            _sg_num(sg, _SG_APPROACH),
            "sg_arg":            _sg_num(sg, _SG_ARG),
            "sg_putt":           _sg_num(sg, _SG_PUTTING),
            "driving_distance":  _parse_leading_float(_perf_str(perf, _PERF_DRIVING_DIST)),
            "fairways_hit":      _parse_leading_float(_perf_str(perf, _PERF_DRIVING_ACC)),
            "gir":               _parse_leading_float(_perf_str(perf, _PERF_GIR)),
            "scrambling":        _parse_leading_float(_perf_str(perf, _PERF_SCRAMBLING)),
            "putts_per_gir":     _parse_leading_float(_perf_str(perf, _PERF_PUTTS_PER_GIR)),
            "birdies":           _score_int(scoring, _SCORING_BIRDIES),
            "pars":              _score_int(scoring, _SCORING_PARS),
            "bogeys":            _score_int(scoring, _SCORING_BOGEYS),
            "double_bogeys":     _score_int(scoring, _SCORING_DOUBLES),
        })

    return rows


def extract_scorecard_stats(
    scorecard: dict,
    tournament_id: str,
    player_id: str,
) -> list[dict]:
    """
    Top-level wrapper matching the extract_* pattern used elsewhere.
    Returns normalized round stat dicts ready for upsert_rounds().
    """
    if not scorecard:
        return []
    return normalize_scorecard_stats(scorecard, tournament_id, player_id)