CREATE TABLE tournaments (
    tournament_id TEXT PRIMARY KEY,
    timezone TEXT,
    format_type TEXT,
    leaderboard_round_header TEXT,
    tourcast_url TEXT,
    raw_payload JSONB,
    ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE players (
    player_id TEXT PRIMARY KEY,
    first_name TEXT,
    last_name TEXT,
    display_name TEXT,
    short_name TEXT,
    country TEXT,
    country_flag TEXT,
    amateur BOOLEAN
);

CREATE TABLE leaderboard_entries (
    tournament_id TEXT REFERENCES tournaments(tournament_id),
    player_id TEXT REFERENCES players(player_id),
    leaderboard_sort_order INT,
    position TEXT,
    total_score TEXT,
    total_sort INT,
    thru TEXT,
    thru_sort INT,
    round_score TEXT,
    round_score_sort INT,
    current_round INT,
    round_header TEXT,
    movement_direction TEXT,
    movement_amount TEXT,
    movement_sort INT,
    player_state TEXT,
    total_strokes TEXT,
    total_strokes_sort INT,
    official TEXT,
    official_sort INT,
    projected TEXT,
    projected_sort INT,
    round_status TEXT,
    PRIMARY KEY (tournament_id, player_id)
);

CREATE TABLE player_round_scores (
    tournament_id TEXT REFERENCES tournaments(tournament_id),
    player_id TEXT REFERENCES players(player_id),
    round_number INT,
    strokes INT,
    PRIMARY KEY (tournament_id, player_id, round_number)
);

