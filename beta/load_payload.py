import base64
import gzip
import json
import sqlite3
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "golf.db")


def load_tournament_data(json_data: dict, db_path: str = DB_PATH):
    tournament_id = json_data["tournamentId"]
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.cursor()

    cur.execute("""
        INSERT OR REPLACE INTO tournaments
            (tournament_id, timezone, format_type, leaderboard_round_header, tourcast_url, raw_payload, ingested_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        tournament_id,
        json_data.get("timezone"),
        json_data.get("formatType"),
        json_data.get("leaderboardRoundHeader"),
        json_data.get("tourcastURLWeb"),
        json.dumps(json_data),
        datetime.utcnow().isoformat(),
    ))

    player_rows = [p for p in json_data["players"] if p["__typename"] == "PlayerRowV3"]

    for entry in player_rows:
        p = entry["player"]
        s = entry["scoringData"]

        cur.execute("""
            INSERT OR IGNORE INTO players
                (player_id, first_name, last_name, display_name, short_name, country, country_flag, amateur)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            p["id"],
            p.get("firstName"),
            p.get("lastName"),
            p.get("displayName"),
            p.get("shortName"),
            p.get("country"),
            p.get("countryFlag"),
            1 if p.get("amateur") else 0,
        ))

        cur.execute("""
            INSERT OR REPLACE INTO leaderboard_entries (
                tournament_id, player_id, leaderboard_sort_order, position,
                total_score, total_sort, thru, thru_sort,
                round_score, round_score_sort, current_round, round_header,
                movement_direction, movement_amount, movement_sort,
                player_state, total_strokes, total_strokes_sort,
                official, official_sort, projected, projected_sort, round_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            tournament_id,
            p["id"],
            entry.get("leaderboardSortOrder"),
            s.get("position"),
            s.get("total"),
            s.get("totalSort"),
            s.get("thru"),
            s.get("thruSort"),
            s.get("score"),
            s.get("scoreSort"),
            s.get("currentRound"),
            s.get("roundHeader"),
            s.get("movementDirection"),
            str(s.get("movementAmount", "")),
            s.get("movementSort"),
            s.get("playerState"),
            s.get("totalStrokes"),
            s.get("totalStrokesSort"),
            s.get("official"),
            s.get("officialSort"),
            s.get("projected"),
            s.get("projectedSort"),
            s.get("roundStatus"),
        ))

        for i, strokes_raw in enumerate(s.get("rounds", []), start=1):
            if strokes_raw and strokes_raw != "-":
                try:
                    strokes = int(strokes_raw)
                except ValueError:
                    continue
                cur.execute("""
                    INSERT OR REPLACE INTO player_round_scores
                        (tournament_id, player_id, round_number, strokes)
                    VALUES (?, ?, ?, ?)
                """, (tournament_id, p["id"], i, strokes))

    conn.commit()
    conn.close()
    print(f"Loaded tournament {tournament_id} — {len(player_rows)} players.")


def decode_payload(encoded_payload: str) -> dict:
    decoded_bytes = base64.b64decode(encoded_payload)
    decompressed_bytes = gzip.decompress(decoded_bytes)
    return json.loads(decompressed_bytes)


if __name__ == "__main__":
    from config import URL, HEADERS, PAYLOAD
    import requests

    response = requests.post(URL, headers=HEADERS, json=PAYLOAD, timeout=30)
    response.raise_for_status()
    decoded = decode_payload(response.json()["data"]["leaderboardCompressedV3"]["payload"])

    output_dir = os.path.join(BASE_DIR, "output")
    os.makedirs(output_dir, exist_ok=True)
    with open(f"{output_dir}/payload.json", "w") as f:
        json.dump(decoded, f, indent=2)

    load_tournament_data(decoded, DB_PATH)