# PGA Tour Ingestion Pipeline — Design Document

## Status: Written from verified payload inspection, not assumptions.

---

## Part 1: What each payload contains

### Schedule payload — `schedule(tourCode, year)`
**Type: `ScheduleTournament`**

This is the richest single payload for tournament metadata. Confirmed fields:

| Field | Example | Notes |
|-------|---------|-------|
| `id` | `R2026006` | Stable tournament ID. Used for ALL downstream queries. |
| `tournamentName` | `Sony Open in Hawaii` | |
| `startDate` | `1768435200000` | Unix ms timestamp |
| `date` | `Jan 15 - 18` | Human-readable, no year, no end timestamp |
| `city` | `Honolulu` | |
| `state` | `Hawaii` | Empty string for non-US (`Puerto Rico`) |
| `country` | `United States of America` | Long form |
| `courseName` | `Waialae Country Club` | String name only — no course ID here |
| `champion` | `Chris Gotterup` | Absent on upcoming tournaments |
| `championId` | `59095` | Player ID — matches leaderboard player.id |
| `purse` | `$9,100,000` | String with $ and commas |
| `tournamentStatus` | `COMPLETED` / `NOT_STARTED` | |

**Use for:** Tournament list, start dates, course names, champion IDs.
**Do not use for:** End dates (absent), course IDs (absent), round-level data.

### Tournament details payload — `tournaments(ids)`
**Type: `Tournament`**

| Field | Example | Notes |
|-------|---------|-------|
| `id` | `R2026006` | Same ID as schedule |
| `tournamentName` | `Sony Open in Hawaii` | |
| `seasonYear` | `2026` | String |
| `displayDate` | `Jan 15 - 18, 2026` | Human-readable, includes year |
| `timezone` | `Pacific/Honolulu` | IANA timezone |
| `tournamentLocation` | `Honolulu` | Same as city |
| `city` | `Honolulu` | |
| `state` | `Hawaii` | |
| `country` | `USA` | Short form (differs from schedule's long form) |
| `currentRound` | `4` | Int |
| `tournamentStatus` | `COMPLETED` | |
| `roundStatus` | `OFFICIAL` | |
| `courses[].id` | `006` | Course ID (numeric string, no R-prefix) |
| `courses[].courseName` | `Waialae Country Club` | |
| `courses[].courseCode` | `WC` | |
| `courses[].hostCourse` | `true` | |
| `events[]` | `[]` | **Always empty** — confirmed on completed tournament. |

**Confirmed absent:** `startDate`, `endDate`, `par`, `yardage`.
**Use for:** Course ID (the only place it appears), timezone, seasonYear.
**Do not use for:** Dates (absent), course specs (absent).

### Leaderboard payload — `leaderboardCompressedV3(id)`

Returned as base64+gzip. After decoding, structure is:

**Top-level:**
- `id`, `timezone`, `tournamentId`, `tournamentStatus`
- `winner` — single winner object
- `winners[]` — list (same content)
- `players[]` — 121 entries for Sony Open
- `courses[]` — course objects (same fields as details)
- `rounds[]` — `[{roundNumber: 1, displayText: "R1"}, ...]`

**Each `players[]` entry:**
```
{
  id: "59095",                    # player ID (stable, matches schedule.championId)
  leaderboardSortOrder: 0,
  player: {
    id: "59095",
    firstName: "Chris",
    lastName: "Gotterup",
    displayName: "Chris Gotterup",
    country: "USA",
    countryFlag: "USA",
    amateur: false,
    ...
  },
  scoringData: {
    position: "1",
    total: "-16",                 # to-par total score (string)
    totalSort: -16,               # integer version
    totalStrokes: "264",          # gross stroke total
    totalStrokesSort: 264,
    rounds: ["63", "69", "68", "64"],  # gross score per round (strings)
    thru: "F",                    # holes completed ("F" = finished)
    score: "-6",                  # current round score
    playerState: "COMPLETE",
    courseId: "006",
    currentRound: 4,
    roundStatus: "R4 Completed"
  }
}
```

**Use for:** Players, per-round gross scores, final standings.
**`scoringData.rounds` is a flat array of 4 strings** — not objects with metadata.
**Round dates: absent.** There is no date field on any round object.

### leaderboardStats — not usable
`leaderboardStats` does not have a `payload` field. The field name is wrong on this type.
This endpoint needs separate introspection to find its real fields before it can be used.
**GIR, fairways, driving distance, putts, strokes gained are not available from current payloads.**

---

## Part 2: ID strategy — confirmed

| ID | Format | Source | Used for |
|----|--------|--------|---------|
| Tournament ID | `R2026006` | Schedule, Details, Leaderboard | All queries. One stable key. |
| Player ID | `59095` | Leaderboard `player.id` = schedule `championId` | Players table PK |
| Course ID | `006` | Details `courses[].id`, Leaderboard `courses[].id` | Courses table PK |

**`events[]` is always empty.** There is no separate event ID or leaderboard ID.
The schedule tournament ID is the correct ID for `leaderboardCompressedV3(id)`.

---

## Part 3: Schema mapping

### `tournaments` table

| Column | Source | Field path | Transform | Notes |
|--------|--------|-----------|-----------|-------|
| `tournament_id` | Schedule | `id` | none | `R2026006` |
| `event_id` | Schedule | `id` | none | Same as tournament_id — no separate event ID exists |
| `tournament_name` | Schedule | `tournamentName` | none | |
| `season_year` | Details | `seasonYear` | int() | String in API |
| `start_date` | Schedule | `startDate` | ms → date | `startDate / 1000` → `datetime.utcfromtimestamp` |
| `end_date` | Schedule | `date` string | parse end | `"Jan 15 - 18"` → derive end from start + days parsed |
| `course_id` | Details | `courses[hostCourse=true].id` | none | `"006"` |

**end_date derivation:** `date` field gives `"Jan 15 - 18"`. Parse the end day integer,
combine with month from startDate, combine with year from seasonYear.
This is the only source for end_date — it is a string parse, not a clean timestamp.

### `courses` table

| Column | Source | Field path | Notes |
|--------|--------|-----------|-------|
| `course_id` | Details / Leaderboard | `courses[].id` | `"006"` — numeric string |
| `course_name` | Schedule / Details | `courseName` / `courses[].courseName` | |
| `location` | Schedule | `city` + `state` + `country` | Concatenate or store separately |
| `par` | **NONE** | — | Not available in any payload |
| `yardage` | **NONE** | — | Not available in any payload |

### `players` table

| Column | Source | Field path | Notes |
|--------|--------|-----------|-------|
| `player_id` | Leaderboard | `players[].player.id` | String, treat as varchar |
| `player_name` | Leaderboard | `players[].player.displayName` | |
| `country` | Leaderboard | `players[].player.country` | `"USA"` short form |

### `raw_leaderboard_rows` table

| Column | Source | Field path | Transform |
|--------|--------|-----------|-----------|
| `event_id` | Leaderboard | `tournamentId` | = tournament_id |
| `season_year` | Details | `seasonYear` | int() |
| `player_id` | `players[].player.id` | | |
| `player_name` | `players[].player.displayName` | | |
| `round_1_score` | `players[].scoringData.rounds[0]` | str → int or null | |
| `round_2_score` | `players[].scoringData.rounds[1]` | str → int or null | |
| `round_3_score` | `players[].scoringData.rounds[2]` | str → int or null | |
| `round_4_score` | `players[].scoringData.rounds[3]` | str → int or null | |
| `total_score` | `players[].scoringData.totalStrokes` | str → int | Gross strokes |
| `source_url` | constructed | `leaderboardCompressedV3/{id}` | |

### `rounds` table

| Column | Available | Source | Notes |
|--------|-----------|--------|-------|
| `round_id` | ✓ | generated | `{tournament_id}_{player_id}_{round_number}` |
| `player_id` | ✓ | leaderboard | |
| `tournament_id` | ✓ | leaderboard | |
| `round_number` | ✓ | index 0–3 → 1–4 | |
| `round_date` | ✗ | absent | No date on any round object |
| `score` | ✓ | `scoringData.rounds[N]` | Gross score string → int |
| `gir` | ✗ | absent | Not in any available payload |
| `fairways_hit` | ✗ | absent | Not in any available payload |
| `driving_distance` | ✗ | absent | Not in any available payload |
| `putts` | ✗ | absent | Not in any available payload |
| `sg_total` | ✗ | absent | Not in any available payload |
| `sg_ott` | ✗ | absent | Not in any available payload |
| `sg_app` | ✗ | absent | Not in any available payload |
| `sg_arg` | ✗ | absent | Not in any available payload |
| `sg_putt` | ✗ | absent | Not in any available payload |

---

## Part 4: Missing data — explicit list

These schema columns **cannot be populated** from the currently known payloads:

1. `courses.par` — absent from Course type entirely
2. `courses.yardage` — absent from Course type entirely
3. `rounds.round_date` — no date field on any round object
4. `rounds.gir` — not in leaderboard payload
5. `rounds.fairways_hit` — not in leaderboard payload
6. `rounds.driving_distance` — not in leaderboard payload
7. `rounds.putts` — not in leaderboard payload
8. `rounds.sg_total` — not in leaderboard payload
9. `rounds.sg_app` — not in leaderboard payload
10. `rounds.sg_ott` — not in leaderboard payload
11. `rounds.sg_arg` — not in leaderboard payload
12. `rounds.sg_putt` — not in leaderboard payload
13. `tournaments.end_date` — no clean timestamp; must be derived by string-parsing `date` field

**Possible future sources:**
- `scorecardCompressedV3(tournamentId, playerId)` — per-player scorecard, may contain hole-level data including putts and GIR. Requires one call per player per tournament.
- `leaderboardStats` — needs correct field introspection; may contain strokes gained.
- `courseStats(tournamentId)` — may contain par/yardage.

---

## Part 5: Recommended folder structure

```
pga_pipeline/
├── config.json                 # endpoint, headers, db connection string
├── run.py                      # CLI entry point
├── pga_pipeline/
│   ├── __init__.py
│   ├── api_client.py           # post(), decode_compressed(), headers
│   ├── fetchers.py             # fetch_schedule(), fetch_details(), fetch_leaderboard()
│   ├── raw_store.py            # save raw JSON to disk with deterministic paths
│   ├── normalizers.py          # transform raw dicts → clean dicts matching schema
│   ├── loaders.py              # upsert functions for each table
│   └── orchestrator.py         # top-level: schedule → details → leaderboard → load
└── raw_data/
    ├── schedules/
    │   └── schedule_2026.json
    ├── details/
    │   └── R2026006.json
    └── leaderboards/
        └── R2026006_decoded.json
```
