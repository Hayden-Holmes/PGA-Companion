CREATE OR REPLACE VIEW tournament_leaderboard AS
WITH round_counts AS (
    SELECT tournament_id, player_id, COUNT(*) AS rounds_played
    FROM rounds
    GROUP BY tournament_id, player_id
),
max_rounds AS (
    SELECT tournament_id, MAX(rounds_played) AS field_max
    FROM round_counts
    GROUP BY tournament_id
)
SELECT
    r.tournament_id,
    r.player_id,
    p.player_name,
    SUM(r.score)        AS total_strokes,
    rc.rounds_played,
    RANK() OVER (
        PARTITION BY r.tournament_id
        ORDER BY
            rc.rounds_played = mr.field_max DESC,  -- made cut first
            SUM(r.score) ASC
    ) AS position
FROM rounds r
JOIN players p USING (player_id)
JOIN round_counts rc USING (tournament_id, player_id)
JOIN max_rounds mr USING (tournament_id)
GROUP BY r.tournament_id, r.player_id, p.player_name, rc.rounds_played, mr.field_max
ORDER BY r.tournament_id, position;