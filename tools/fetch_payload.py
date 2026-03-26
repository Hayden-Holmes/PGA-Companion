"""
fetch_payload.py
----------------
Fetch and save the raw payload for any query.
Automatically detects and decodes compressed payloads.

Usage:
    python tools/fetch_payload.py <queryName> [key=value ...]

Examples:
    python tools/fetch_payload.py LeaderboardCompressedV3 leaderboardCompressedV3Id=R2026006
    python tools/fetch_payload.py CourseStats tournamentId=R2026006
    python tools/fetch_payload.py StatDetails tourCode=R statId=02675 year=2026
    python tools/fetch_payload.py TournamentDetails ids=R2026006
    python tools/fetch_payload.py Schedule tourCode=R year=2026
    python tools/fetch_payload.py PlayerProfileCourseResults playerId=59095 tourCode=R

Output saved to tools/payload_output/{queryName}_{args}.json
"""

import base64
import gzip
import json
import os
import sys
import requests

ENDPOINT = "https://orchestrator.pgatour.com/graphql"
HEADERS = {
    "Content-Type": "application/json",
    "x-api-key": "da2-gsrx5bibzbb4njvhl7t37wqyl4",
    "origin": "https://www.pgatour.com",
    "referer": "https://www.pgatour.com/",
    "x-pgat-platform": "web",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "payload_output")

# Known queries — maps query name to (graphql query string, root data key)
# Add new ones here as you discover them
QUERIES = {
    "LeaderboardCompressedV3": (
        """query LeaderboardCompressedV3($leaderboardCompressedV3Id: ID!) {
          leaderboardCompressedV3(id: $leaderboardCompressedV3Id) {
            id
            payload
          }
        }""",
        "leaderboardCompressedV3",
    ),
    "CourseStats": (
        """query CourseStats($tournamentId: ID!) {
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
        }""",
        "courseStats",
    ),
    "StatDetails": (
        """query StatDetails($tourCode: TourCode!, $statId: String!, $year: Int) {
          statDetails(tourCode: $tourCode, statId: $statId, year: $year) {
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
                rank
                rankDiff
                rankChangeTendency
                stats { statName statValue }
              }
              ... on StatDetailTourAvg {
                __typename
                displayName
                value
              }
            }
          }
        }""",
        "statDetails",
    ),
    "TournamentDetails": (
        """query TournamentDetails($ids: [ID!]!) {
          tournaments(ids: $ids) {
            id
            tournamentName
            seasonYear
            displayDate
            timezone
            city
            state
            country
            tournamentStatus
            courses { id courseName courseCode hostCourse }
            events { id }
          }
        }""",
        "tournaments",
    ),
    "Schedule": (
        """query Schedule($tourCode: String!, $year: String) {
          schedule(tourCode: $tourCode, year: $year) {
            completed {
              tournaments {
                id tournamentName startDate date city state country
                courseName champion championId purse tournamentStatus
              }
            }
            upcoming {
              tournaments {
                id tournamentName startDate date city state country
                courseName tournamentStatus
              }
            }
          }
        }""",
        "schedule",
    ),
    "PlayerProfileCourseResults": (
        """query PlayerProfileCourseResults($playerId: String!, $tourCode: TourCode) {
          playerProfileCourseResults(playerId: $playerId, tourCode: $tourCode) {
            playerId
            results {
              courseId
              courseName
              rounds
              scoring
              lastPlayed
            }
          }
        }""",
        "playerProfileCourseResults",
    ),
    "PlayerProfileTournamentResults": (
        """query PlayerProfileTournamentResults($playerId: ID!, $tourCode: TourCode) {
          playerProfileTournamentResults(playerId: $playerId, tourCode: $tourCode) {
            playerId
            results {
              tournamentId
              tournamentName
              seasonYear
              finishPosition
              score
            }
          }
        }""",
        "playerProfileTournamentResults",
    ),
    "TournamentHistory": (
        """query TournamentHistory($tournamentId: String!) {
          tournamentHistory(tournamentId: $tournamentId) {
            tournamentId
            results {
              year
              winnerId
              winnerName
              winnerScore
              courseId
              courseName
            }
          }
        }""",
        "tournamentHistory",
    ),
}


def parse_args(raw_args):
    """Parse key=value pairs from command line into a dict."""
    variables = {}
    for arg in raw_args:
        if "=" not in arg:
            print(f"Skipping malformed arg: {arg} (expected key=value)")
            continue
        key, value = arg.split("=", 1)
        # Convert to int if numeric
        if value.isdigit():
            value = int(value)
        # Convert list args (comma separated) e.g. ids=R2026006,R2026007
        elif "," in value:
            value = value.split(",")
        variables[key] = value
    return variables


def try_decode(payload_str):
    """Attempt base64 + gzip decode. Returns decoded dict or None."""
    try:
        raw = base64.b64decode(payload_str)
        decompressed = gzip.decompress(raw)
        return json.loads(decompressed)
    except Exception:
        return None


def deep_decode(obj):
    """
    Walk the response and decode any 'payload' fields that look compressed.
    Returns the object with payload fields replaced by decoded content.
    """
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            if k == "payload" and isinstance(v, str) and len(v) > 100:
                decoded = try_decode(v)
                result[k] = decoded if decoded is not None else v
            else:
                result[k] = deep_decode(v)
        return result
    elif isinstance(obj, list):
        return [deep_decode(item) for item in obj]
    return obj


def save(filename, data):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    query_name = sys.argv[1]
    raw_args = sys.argv[2:]

    if query_name not in QUERIES:
        print(f"Unknown query: {query_name}")
        print(f"Known queries: {list(QUERIES.keys())}")
        print("Add new queries to the QUERIES dict in this script.")
        sys.exit(1)

    query_str, data_key = QUERIES[query_name]
    variables = parse_args(raw_args)

    print(f"Fetching {query_name} with variables: {variables}")

    body = {"operationName": query_name, "variables": variables, "query": query_str}
    resp = requests.post(ENDPOINT, json=body, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    parsed = resp.json()

    errors = parsed.get("errors")
    if errors:
        print(f"GraphQL errors: {[e['message'] for e in errors]}")
        sys.exit(1)

    # Auto-decode any compressed payload fields
    data = deep_decode(parsed.get("data", {}))

    # Build output filename from query name and args
    arg_str = "_".join(f"{k}{v}" for k, v in variables.items())
    filename = f"{query_name}_{arg_str}.json".replace("/", "-")

    path = save(filename, data)
    print(f"Saved to: {path}")

    # Print top-level structure so you know what you got
    root = data.get(data_key)
    if root is None:
        print("Response data is null.")
    elif isinstance(root, list):
        print(f"Returned list of {len(root)} items.")
        if root:
            print(f"First item keys: {list(root[0].keys()) if isinstance(root[0], dict) else type(root[0])}")
    elif isinstance(root, dict):
        print(f"Returned object with keys: {list(root.keys())}")