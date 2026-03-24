import base64
import gzip
import json
import copy
import os
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(BASE_DIR, "config.json")) as f:
    config = json.load(f)

URL     = config["url"]
HEADERS = config["headers"]


# ── Payload builders ──────────────────────────────────────────────────────────

def get_schedule_payload(year: int) -> dict:
    payload = copy.deepcopy(config["schedule_payload"])
    payload["variables"]["year"] = str(year)
    return payload


def get_leaderboard_payload(tournament_id: str) -> dict:
    payload = copy.deepcopy(config["leaderboard_payload"])
    payload["variables"]["leaderboardCompressedV3Id"] = tournament_id
    return payload


def get_tournament_detail_payload(tournament_ids: list[str]) -> dict:
    payload = copy.deepcopy(config["tournament_detail_payload"])
    payload["variables"]["ids"] = tournament_ids
    return payload


# ── Helpers ───────────────────────────────────────────────────────────────────

def decode_payload(encoded_payload: str) -> dict:
    decoded_bytes = base64.b64decode(encoded_payload)
    decompressed_bytes = gzip.decompress(decoded_bytes)
    return json.loads(decompressed_bytes)


def save_payload(data: dict, filename: str, output_dir: str = None):
    if output_dir is None:
        output_dir = os.path.join(BASE_DIR, "output")
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Saved: {filepath}")


def parse_section(section_data) -> list[dict]:
    """
    Handles both shapes the API returns:
      - list of groups: [{"tournaments": [...]}, ...]
      - dict:           {"tournaments": [...]}
    """
    tournaments = []

    if isinstance(section_data, list):
        for group in section_data:
            if isinstance(group, dict):
                for t in group.get("tournaments") or []:
                    if t.get("id"):
                        tournaments.append(t)
    elif isinstance(section_data, dict):
        for t in section_data.get("tournaments") or []:
            if t.get("id"):
                tournaments.append(t)

    return tournaments


# ── Schedule ──────────────────────────────────────────────────────────────────

def get_tournament_ids(year: int, save: bool = False) -> list[dict]:
    payload = get_schedule_payload(year)

    try:
        r = requests.post(URL, headers=HEADERS, json=payload, timeout=15)
        r.raise_for_status()
        data = r.json()

        if data.get("errors"):
            print(f"  GraphQL errors for {year}:")
            for e in data["errors"]:
                print(f"    - {e.get('message')}")
            return []

        schedule = data.get("data", {}).get("schedule")

        if schedule is None:
            print(f"  schedule returned null for {year} — skipping")
            return []

        tournaments = []
        for section in ["completed", "upcoming"]:
            for t in parse_section(schedule.get(section) or []):
                tournaments.append({
                    "id": t["id"],
                    "name": t.get("tournamentName"),
                    "start_date": t.get("startDate"),
                    "year": year
                })

        if save and tournaments:
            save_payload(
                {"year": year, "tournaments": tournaments},
                f"schedule_{year}.json"
            )

        print(f"  Found {len(tournaments)} tournaments in {year}")
        return tournaments

    except requests.exceptions.Timeout:
        print(f"  Timeout fetching schedule for {year}")
        return []
    except requests.exceptions.HTTPError as e:
        print(f"  HTTP error fetching schedule for {year}: {e}")
        return []
    except Exception as e:
        print(f"  Unexpected error fetching schedule for {year}: {e}")
        return []


# ── Leaderboard ───────────────────────────────────────────────────────────────

def get_leaderboard(tournament_id: str, save: bool = False) -> dict | None:
    payload = get_leaderboard_payload(tournament_id)

    try:
        r = requests.post(URL, headers=HEADERS, json=payload, timeout=15)
        r.raise_for_status()
        data = r.json()

        if data.get("errors"):
            print(f"  GraphQL errors for {tournament_id}:")
            for e in data["errors"]:
                print(f"    - {e.get('message')}")
            return None

        raw = (
            data
            .get("data", {})
            .get("leaderboardCompressedV3", {})
            .get("payload")
        )

        if not raw:
            print(f"  No payload returned for {tournament_id}")
            return None

        decoded = decode_payload(raw)

        if save:
            save_payload(decoded, f"{tournament_id}.json")

        return decoded

    except requests.exceptions.Timeout:
        print(f"  Timeout fetching {tournament_id}")
        return None
    except requests.exceptions.HTTPError as e:
        print(f"  HTTP error fetching {tournament_id}: {e}")
        return None
    except (gzip.BadGzipFile, base64.binascii.Error) as e:
        print(f"  Decode error for {tournament_id}: {e}")
        return None
    except Exception as e:
        print(f"  Unexpected error fetching {tournament_id}: {e}")
        return None


# ── Tournament detail ─────────────────────────────────────────────────────────

def get_tournament_details(tournament_ids: list[str], save: bool = False) -> list[dict]:
    payload = get_tournament_detail_payload(tournament_ids)

    try:
        r = requests.post(URL, headers=HEADERS, json=payload, timeout=15)
        r.raise_for_status()
        data = r.json()

        if data.get("errors"):
            print(f"  GraphQL errors fetching tournament details:")
            for e in data["errors"]:
                print(f"    - {e.get('message')}")
            return []

        tournaments = data.get("data", {}).get("tournaments") or []

        if not tournaments:
            print(f"  No tournament details returned for {tournament_ids}")
            return []

        if save:
            for t in tournaments:
                save_payload(t, f"tournament_detail_{t['id']}.json")

        return tournaments

    except requests.exceptions.Timeout:
        print(f"  Timeout fetching tournament details")
        return []
    except requests.exceptions.HTTPError as e:
        print(f"  HTTP error fetching tournament details: {e}")
        return []
    except Exception as e:
        print(f"  Unexpected error fetching tournament details: {e}")
        return []


# ── Quick test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    for year in [2026, 2025, 2024, 2020, 2016]:
        get_tournament_ids(year, save=True)