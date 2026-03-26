-- golf_v1_schema.sql
-- PostgreSQL schema for PGA Tour pipeline.
--
-- Notes on what cannot be populated from the current API:
--   courses.par           — absent from Course type
--   courses.yardage       — absent from Course type
--   rounds.round_date     — no round date in any payload
--   rounds.gir            — not in leaderboard payload
--   rounds.fairways_hit   — not in leaderboard payload
--   rounds.driving_distance — not in leaderboard payload
--   rounds.putts          — not in leaderboard payload
--   rounds.sg_*           — not in leaderboard payload
--
-- These columns are nullable so rows can be inserted without them.
-- Populate them later when a stats endpoint is identified.

CREATE TABLE IF NOT EXISTS players (
    player_id       VARCHAR(20) PRIMARY KEY,
    player_name     TEXT,
    country         VARCHAR(10)
);

CREATE TABLE IF NOT EXISTS courses (
    course_id       VARCHAR(20) PRIMARY KEY,
    course_name     TEXT,
    location        TEXT,
    par             INTEGER,        -- NULL: not available from API
    yardage         INTEGER         -- NULL: not available from API
);

CREATE TABLE IF NOT EXISTS tournaments (
    tournament_id   VARCHAR(20) PRIMARY KEY,
    event_id        VARCHAR(20),    -- same as tournament_id (no separate event ID exists)
    tournament_name TEXT,
    season_year     INTEGER,
    start_date      DATE,
    end_date        DATE,           -- derived from schedule.date string, not a clean timestamp
    course_id       VARCHAR(20) REFERENCES courses(course_id)
);

CREATE TABLE IF NOT EXISTS rounds (
    round_id            VARCHAR(60) PRIMARY KEY,  -- {tournament_id}_{player_id}_{round_number}
    player_id           VARCHAR(20) REFERENCES players(player_id),
    tournament_id       VARCHAR(20) REFERENCES tournaments(tournament_id),
    round_number        INTEGER,
    round_date          DATE,           -- NULL: not available from any payload
    score               INTEGER,        -- gross strokes for this round
    gir                 NUMERIC(5,2),   -- NULL: requires separate stats endpoint
    fairways_hit        NUMERIC(5,2),   -- NULL: requires separate stats endpoint
    driving_distance    NUMERIC(6,2),   -- NULL: requires separate stats endpoint
    putts               NUMERIC(5,2),   -- NULL: requires separate stats endpoint
    sg_total            NUMERIC(6,3),   -- NULL: requires separate stats endpoint
    sg_ott              NUMERIC(6,3),   -- NULL: requires separate stats endpoint
    sg_app              NUMERIC(6,3),   -- NULL: requires separate stats endpoint
    sg_arg              NUMERIC(6,3),   -- NULL: requires separate stats endpoint
    sg_putt             NUMERIC(6,3)    -- NULL: requires separate stats endpoint
);

CREATE TABLE IF NOT EXISTS users (
    user_id         SERIAL PRIMARY KEY,
    username        TEXT UNIQUE NOT NULL,
    email           TEXT UNIQUE NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_watchlist (
    user_id         INTEGER REFERENCES users(user_id),
    player_id       VARCHAR(20) REFERENCES players(player_id),
    PRIMARY KEY (user_id, player_id)
);

-- raw_leaderboard_rows: one row per player per tournament.
-- Unique constraint on (event_id, player_id) enables idempotent upserts.
CREATE TABLE IF NOT EXISTS raw_leaderboard_rows (
    event_id        VARCHAR(20),
    season_year     INTEGER,
    player_id       VARCHAR(20),
    player_name     TEXT,
    round_1_score   INTEGER,
    round_2_score   INTEGER,
    round_3_score   INTEGER,
    round_4_score   INTEGER,
    total_score     INTEGER,        -- gross strokes total
    source_url      TEXT,
    PRIMARY KEY (event_id, player_id)
);
