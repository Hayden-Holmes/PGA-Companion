-- schema.sql
-- PostgreSQL schema for PGA Tour golf analysis app

-- Drop child tables first if you want to recreate everything
DROP TABLE IF EXISTS rounds CASCADE;
DROP TABLE IF EXISTS tournaments CASCADE;
DROP TABLE IF EXISTS courses CASCADE;
DROP TABLE IF EXISTS players CASCADE;

-- 1. Players
CREATE TABLE players (
    player_id BIGINT PRIMARY KEY,
    player_name VARCHAR(150) NOT NULL,
    country VARCHAR(80)
);

-- 2. Courses
CREATE TABLE courses (
    course_id BIGSERIAL PRIMARY KEY,
    course_name VARCHAR(150) NOT NULL,
    location VARCHAR(150),
    par INTEGER,
    yardage INTEGER,
    CONSTRAINT uq_courses_name_location UNIQUE (course_name, location)
);

-- 3. Tournaments
CREATE TABLE tournaments (
    tournament_id BIGSERIAL PRIMARY KEY,
    event_id BIGINT NOT NULL,
    tournament_name VARCHAR(150) NOT NULL,
    season_year INTEGER NOT NULL,
    start_date DATE,
    end_date DATE,
    course_id BIGINT REFERENCES courses(course_id) ON DELETE SET NULL,
    CONSTRAINT uq_tournament_event_year UNIQUE (event_id, season_year)
);

-- 4. Rounds
CREATE TABLE rounds (
    round_id BIGSERIAL PRIMARY KEY,
    player_id BIGINT NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
    tournament_id BIGINT NOT NULL REFERENCES tournaments(tournament_id) ON DELETE CASCADE,
    round_number INTEGER NOT NULL CHECK (round_number BETWEEN 1 AND 4),
    round_date DATE,
    score INTEGER,
    gir NUMERIC(5,2),
    fairways_hit NUMERIC(5,2),
    driving_distance NUMERIC(6,2),
    putts NUMERIC(5,2),
    sg_total NUMERIC(6,3),
    sg_ott NUMERIC(6,3),
    sg_app NUMERIC(6,3),
    sg_arg NUMERIC(6,3),
    sg_putt NUMERIC(6,3),

    CONSTRAINT uq_round_player_tournament_round
        UNIQUE (player_id, tournament_id, round_number)
);

-- 5. Users
CREATE TABLE users (
    user_id BIGSERIAL PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    email VARCHAR(120) UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 6. User Watchlist
-- One row per user-player watchlist entry, with an optional note
CREATE TABLE user_watchlist (
    watchlist_id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    player_id BIGINT NOT NULL,
    note_text TEXT,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_user_watchlist_user
        FOREIGN KEY (user_id)
        REFERENCES users(user_id)
        ON DELETE CASCADE,

    CONSTRAINT fk_user_watchlist_player
        FOREIGN KEY (player_id)
        REFERENCES players(player_id)
        ON DELETE CASCADE,

    CONSTRAINT uq_user_watchlist_user_player
        UNIQUE (user_id, player_id)
);


-- Raw leaderboard data table to store scraped data before processing
CREATE TABLE raw_leaderboard_rows (
    raw_id BIGSERIAL PRIMARY KEY,
    event_id BIGINT NOT NULL,
    season_year INTEGER NOT NULL,
    player_id BIGINT,
    player_name VARCHAR(150),
    round_1_score INTEGER,
    round_2_score INTEGER,
    round_3_score INTEGER,
    round_4_score INTEGER,
    total_score INTEGER,
    source_url TEXT
);