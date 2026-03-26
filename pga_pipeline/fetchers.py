"""
pga_pipeline/fetchers.py

One function per API call. Each function returns the raw API response dict as is

All query strings use only field names confirmed by introspection and
live payload inspection. No guessed field names.
"""

import logging
from typing import Optional

from .api_client import decode_compressed, gql_post

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schedule
#
# Confirmed args:  tourCode: String!,  year: String
# Confirmed type:  ScheduleTournament
# Confirmed fields used: id, tournamentName, startDate, date, city, state,
#                        country, courseName, champion, championId, purse,
#                        tournamentStatus
# NOT requested:   endDate (absent), courseId (absent on this type)
# ---------------------------------------------------------------------------

_SCHEDULE_QUERY = """
query Schedule($tourCode: String!, $year: String) {
  schedule(tourCode: $tourCode, year: $year) {
    completed {
      tournaments {
        id
        tournamentName
        startDate
        date
        city
        state
        country
        courseName
        champion
        championId
        purse
        tournamentStatus
      }
    }
    upcoming {
      tournaments {
        id
        tournamentName
        startDate
        date
        city
        state
        country
        courseName
        tournamentStatus
      }
    }
  }
}
"""


def fetch_schedule(year: str) -> dict:
    """
    Returns the raw schedule response for a given year string (e.g. "2026").
    Response structure: data.schedule.completed[].tournaments[] and
                        data.schedule.upcoming[].tournaments[]
    """
    logger.info("Fetching schedule for year=%s", year)
    return gql_post("Schedule", {"tourCode": "R", "year": year}, _SCHEDULE_QUERY)


# ---------------------------------------------------------------------------
# Tournament details
#
# Confirmed args:  ids: [ID!]!
# Confirmed type:  Tournament
# Confirmed fields used: id, tournamentName, seasonYear, displayDate,
#                        timezone, tournamentLocation, city, state, country,
#                        currentRound, tournamentStatus, roundStatus,
#                        courses[].{id, courseName, courseCode, hostCourse},
#                        events[]
# NOT requested:   startDate (absent on Tournament type),
#                  endDate   (absent on Tournament type),
#                  par       (absent on Course type),
#                  yardage   (absent on Course type)
# ---------------------------------------------------------------------------

_DETAILS_QUERY = """
query TournamentDetails($ids: [ID!]!) {
  tournaments(ids: $ids) {
    id
    tournamentName
    seasonYear
    displayDate
    timezone
    tournamentLocation
    city
    state
    country
    currentRound
    tournamentStatus
    roundStatus
    courses {
      id
      courseName
      courseCode
      hostCourse
    }
    events {
      id
    }
  }
}
"""


def fetch_details(tournament_ids: list[str]) -> dict:
    """
    Fetch tournament details for a list of tournament IDs.
    Batching is supported by the API (ids is a list).
    Returns raw response: data.tournaments[]
    """
    logger.info("Fetching details for %d tournament(s)", len(tournament_ids))
    return gql_post("TournamentDetails", {"ids": tournament_ids}, _DETAILS_QUERY)


# ---------------------------------------------------------------------------
# Stat details (full per-player season rankings)
#
# Confirmed from DevTools. Returns full ranked list for one stat at a time.
# statOverview only returns top 3 — this is the correct endpoint.
#
# Confirmed row structure:
#   rows[] is a union of StatDetailsPlayer | StatDetailTourAvg
#   StatDetailsPlayer fields: playerId, playerName, country, countryFlag,
#                             rank, rankDiff, rankChangeTendency,
#                             stats[{statName, statValue, color}]
#   Primary value is stats[0].statValue (the "Avg" entry)
#
# year=null returns current season. Pass int year for historical.
# eventQuery=null returns full season stats.
# ---------------------------------------------------------------------------

# Stat IDs confirmed from statDetails payload inspection
STAT_IDS = {
    # Strokes Gained
    "02675": "SG: Total",
    "02674": "SG: Tee-to-Green",
    "02567": "SG: Off-the-Tee",
    "02568": "SG: Approach the Green",
    "02569": "SG: Around-the-Green",
    "02564": "SG: Putting",

    # Driving
    "101":   "Driving Distance",
    "102":   "Driving Accuracy Percentage",
    "317":   "Driving Distance - All Drives",

    # Approach
    "103":   "Greens in Regulation Percentage",
    "331":   "Proximity to Hole",
    "158":   "Ball Striking",

    # Around the Green
    "130":   "Scrambling",
    "111":   "Sand Save Percentage",

    # Putting
    "104":   "Putting Average",
    "119":   "Putts Per Round",
    "426":   "3-Putt Avoidance",
    "413":   "One-Putt Percentage",

    # Scoring
    "120":   "Scoring Average (Adjusted)",
    "156":   "Birdie Average",
    "160":   "Bounce Back",
    "352":   "Birdie or Better Percentage",
    "142":   "Par 3 Scoring Average",
    "143":   "Par 4 Scoring Average",
    "144":   "Par 5 Scoring Average",
    "118":   "Final Round Scoring Average",

    # Rankings / Money
    "186":   "Official World Golf Ranking",
    "109":   "Official Money",
    "138":   "Top 10 Finishes",
    "02671": "FedExCup Standings",
}

_STAT_DETAILS_QUERY = """
query StatDetails($tourCode: TourCode!, $statId: String!, $year: Int, $eventQuery: StatDetailEventQuery) {
  statDetails(
    tourCode: $tourCode
    statId: $statId
    year: $year
    eventQuery: $eventQuery
  ) {
    tourCode
    year
    statId
    statTitle
    tourAvg
    lastProcessed
    rows {
      ... on StatDetailsPlayer {
        __typename
        playerId
        playerName
        country
        countryFlag
        rank
        stats {
          statName
          statValue
        }
      }
      ... on StatDetailTourAvg {
        __typename
      }
    }
  }
}
"""


def fetch_stat_details(stat_id: str, year: str) -> Optional[dict]:
    """
    Fetch full player rankings for one stat in one season year.
    Returns the statDetails dict, or None if unavailable.

    Makes one API call per stat_id. Call once per stat per year.
    year is passed as int (confirmed from DevTools — null means current season).
    """
    logger.info("Fetching statDetails for statId=%s year=%s", stat_id, year)
    try:
        data = gql_post(
            "StatDetails",
            {
                "tourCode": "R",
                "statId": stat_id,
                "year": int(year),
                "eventQuery": None,
            },
            _STAT_DETAILS_QUERY,
        )
        result = data.get("data", {}).get("statDetails")
        if result is None:
            logger.warning(
                "statDetails returned null for statId=%s year=%s", stat_id, year
            )
            return None
        return result
    except ValueError as e:
        logger.warning(
            "statDetails failed for statId=%s year=%s: %s", stat_id, year, e
        )
        return None


def fetch_all_stat_details(year: str) -> list[dict]:
    """
    Fetch statDetails for all known stat IDs for a given year.
    Returns a list of statDetails dicts (one per stat).
    Makes 8 API calls total.
    """
    results = []
    for stat_id in STAT_IDS:
        result = fetch_stat_details(stat_id, year)
        if result:
            results.append(result)
    return results


# ---------------------------------------------------------------------------
# Season stat overview (DEPRECATED — only returns top 3 per stat)
# Kept for reference. Use fetch_all_stat_details instead.
# ---------------------------------------------------------------------------

_STAT_OVERVIEW_QUERY = """
query StatOverview($tourCode: TourCode!, $year: Int) {
  statOverview(tourCode: $tourCode, year: $year) {
    tourCode
    year
    stats {
      statId
      statName
      tourAvg
      players {
        statId
        playerId
        statTitle
        statValue
        playerName
        rank
        country
        countryFlag
      }
    }
  }
}
"""


def fetch_stat_overview(year: str) -> Optional[dict]:
    """Deprecated — only returns top 3 players per stat. Use fetch_all_stat_details."""
    logger.warning(
        "fetch_stat_overview is deprecated and returns only top 3 players. "
        "Use fetch_all_stat_details instead."
    )
    logger.info("Fetching stat overview for year=%s", year)
    try:
        data = gql_post(
            "StatOverview",
            {"tourCode": "R", "year": int(year)},
            _STAT_OVERVIEW_QUERY,
        )
        result = data.get("data", {}).get("statOverview")
        if result is None:
            logger.warning("statOverview returned null for year=%s", year)
            return None
        return result
    except ValueError as e:
        logger.warning("statOverview failed for year=%s: %s", year, e)
        return None


# ---------------------------------------------------------------------------
# Course stats
#
# Confirmed from DevTools on Valspar Championship page.
# Returns par (int) and yardage (string e.g. "7,352") per course.
# courseId matches the id field from details/leaderboard payloads.
# Multi-course tournaments return multiple courses[] entries.
#
# Returns None if courseStats is null (e.g. older tournaments without data).
# ---------------------------------------------------------------------------

_COURSE_STATS_QUERY = """
query CourseStats($tournamentId: ID!) {
  courseStats(tournamentId: $tournamentId) {
    tournamentId
    courses {
      courseId
      courseName
      courseCode
      par
      yardage
      hostCourse
    }
  }
}
"""


def fetch_course_stats(tournament_id: str) -> Optional[dict]:
    """
    Fetch par and yardage for all courses in a tournament.
    Returns the raw courseStats dict, or None if no data is available.

    courseId in this response matches courses[].id from details/leaderboard.
    yardage is returned as a string with commas e.g. "7,352" — parse in normalizer.
    """
    logger.info("Fetching course stats for tournament_id=%s", tournament_id)
    try:
        data = gql_post(
            "CourseStats",
            {"tournamentId": tournament_id},
            _COURSE_STATS_QUERY,
        )
        result = data.get("data", {}).get("courseStats")
        if result is None:
            logger.warning(
                "courseStats returned null for tournament_id=%s", tournament_id
            )
            return None
        return result
    except ValueError as e:
        logger.warning(
            "courseStats failed for tournament_id=%s: %s", tournament_id, e
        )
        return None


# ---------------------------------------------------------------------------
# Leaderboard (compressed)
#
# Confirmed operation: LeaderboardCompressedV3
# Confirmed arg:       leaderboardCompressedV3Id: ID!
#                      (NOT "tournamentId" — that is a different variable name)
# Confirmed: schedule ID (R2026006) works directly as leaderboard ID.
# Confirmed: events[] is always empty — there is no separate leaderboard ID.
# ---------------------------------------------------------------------------

_LEADERBOARD_QUERY = """
query LeaderboardCompressedV3($leaderboardCompressedV3Id: ID!) {
  leaderboardCompressedV3(id: $leaderboardCompressedV3Id) {
    id
    payload
  }
}
"""


def fetch_leaderboard_raw(tournament_id: str) -> dict:
    """
    Fetch the raw (encoded) leaderboard response for a tournament.
    Returns the full response dict including the encoded payload string.
    Caller must call decode_leaderboard_payload() to get usable data.
    """
    logger.info("Fetching leaderboard for tournament_id=%s", tournament_id)
    return gql_post(
        "LeaderboardCompressedV3",
        {"leaderboardCompressedV3Id": tournament_id},
        _LEADERBOARD_QUERY,
    )


def fetch_leaderboard(tournament_id: str) -> Optional[dict]:
    """
    Fetch and decode the leaderboard for a tournament.
    Returns the decoded payload dict, or None if the leaderboard is unavailable.

    Logs a warning (not an exception) if the leaderboard is null —
    this is expected for upcoming tournaments.
    """
    raw_response = fetch_leaderboard_raw(tournament_id)

    lb_wrapper = raw_response.get("data", {}).get("leaderboardCompressedV3")

    if lb_wrapper is None:
        logger.warning(
            "leaderboardCompressedV3 returned null for tournament_id=%s "
            "(expected for upcoming/future tournaments)",
            tournament_id,
        )
        return None

    payload_str = lb_wrapper.get("payload")
    if not payload_str:
        logger.warning(
            "Leaderboard payload is null/empty for tournament_id=%s",
            tournament_id,
        )
        return None

    return decode_compressed(payload_str)

# ---------------------------------------------------------------------------
# Scorecard stats (round-level SG splits + performance stats)
#
# Confirmed from live payload inspection on R2025016.
# Returns one entry per round including round "-1" (tournament aggregate).
# round "-1" = tournament total, rounds "1"-"4" = individual rounds.
# UPCOMING rounds return empty stat arrays — skip them in normalizer.
#
# Called once per player per completed tournament.
# ---------------------------------------------------------------------------

_SCORECARD_STATS_QUERY = """
query ScorecardStatsV3($id: ID!, $playerId: ID!) {
  scorecardStatsV3(id: $id, playerId: $playerId) {
    id
    rounds {
      round
      displayName
      roundStatus
      strokesGained {
        statId
        totalNum
        rank
      }
      performance {
        statId
        total
        rank
      }
      scoring {
        statId
        total
      }
    }
  }
}
"""


def fetch_scorecard_stats(tournament_id: str, player_id: str) -> Optional[dict]:
    """
    Fetch round-level SG splits and performance stats for one player
    in one completed tournament.

    Returns the scorecardStatsV3 dict (with rounds[]), or None if
    unavailable (player withdrew, data not yet official, API error).

    Called after leaderboard is loaded so player_id is guaranteed to exist.
    """
    logger.info(
        "Fetching scorecard stats for tournament_id=%s player_id=%s",
        tournament_id, player_id,
    )
    try:
        data = gql_post(
            "ScorecardStatsV3",
            {"id": tournament_id, "playerId": player_id},
            _SCORECARD_STATS_QUERY,
        )
        result = data.get("data", {}).get("scorecardStatsV3")
        if result is None:
            logger.warning(
                "scorecardStatsV3 returned null for tournament_id=%s player_id=%s",
                tournament_id, player_id,
            )
        return result
    except ValueError as e:
        logger.warning(
            "scorecardStatsV3 failed for tournament_id=%s player_id=%s: %s",
            tournament_id, player_id, e,
        )
        return None