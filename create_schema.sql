-- WARNING: This schema is for context only and is not meant to be run.
-- Table order and constraints may not be valid for execution.

CREATE TABLE public.courses (
  course_id character varying NOT NULL,
  course_name text,
  location text,
  par integer,
  yardage integer,
  CONSTRAINT courses_pkey PRIMARY KEY (course_id)
);
CREATE TABLE public.player_season_stats (
  player_id character varying NOT NULL,
  season_year integer NOT NULL,
  stat_id character varying NOT NULL,
  stat_name text,
  stat_value text,
  stat_title text,
  tour_avg text,
  rank integer,
  CONSTRAINT player_season_stats_pkey PRIMARY KEY (player_id, season_year, stat_id),
  CONSTRAINT player_season_stats_player_id_fkey FOREIGN KEY (player_id) REFERENCES public.players(player_id)
);
CREATE TABLE public.player_stats_extended (
  player_id character varying NOT NULL,
  season_year integer NOT NULL,
  stat_id character varying NOT NULL,
  stat_name text,
  stat_value text,
  stat_title text,
  tour_avg text,
  rank integer,
  CONSTRAINT player_stats_extended_pkey PRIMARY KEY (player_id, season_year, stat_id),
  CONSTRAINT player_stats_extended_player_id_fkey FOREIGN KEY (player_id) REFERENCES public.players(player_id)
);
CREATE TABLE public.players (
  player_id character varying NOT NULL,
  player_name text,
  country character varying,
  CONSTRAINT players_pkey PRIMARY KEY (player_id)
);
CREATE TABLE public.raw_leaderboard_rows (
  event_id character varying NOT NULL,
  season_year integer,
  player_id character varying NOT NULL,
  player_name text,
  round_1_score integer,
  round_2_score integer,
  round_3_score integer,
  round_4_score integer,
  total_score integer,
  source_url text,
  position integer,
  purse numeric,
  status character varying,
  CONSTRAINT raw_leaderboard_rows_pkey PRIMARY KEY (event_id, player_id)
);
CREATE TABLE public.rounds (
  round_id character varying NOT NULL,
  player_id character varying,
  tournament_id character varying,
  round_number integer,
  round_date date,
  score integer,
  gir numeric,
  fairways_hit numeric,
  driving_distance numeric,
  putts numeric,
  sg_total numeric,
  sg_ott numeric,
  sg_app numeric,
  sg_arg numeric,
  sg_putt numeric,
  scrambling numeric,
  putts_per_gir numeric,
  birdies integer,
  pars integer,
  bogeys integer,
  double_bogeys integer,
  CONSTRAINT rounds_pkey PRIMARY KEY (round_id),
  CONSTRAINT rounds_player_id_fkey FOREIGN KEY (player_id) REFERENCES public.players(player_id),
  CONSTRAINT rounds_tournament_id_fkey FOREIGN KEY (tournament_id) REFERENCES public.tournaments(tournament_id)
);
CREATE TABLE public.tournaments (
  tournament_id character varying NOT NULL,
  event_id character varying,
  tournament_name text,
  season_year integer,
  start_date date,
  end_date date,
  course_id character varying,
  purse bigint,
  CONSTRAINT tournaments_pkey PRIMARY KEY (tournament_id),
  CONSTRAINT tournaments_course_id_fkey FOREIGN KEY (course_id) REFERENCES public.courses(course_id)
);
CREATE TABLE public.user_watchlist (
  user_id integer NOT NULL,
  player_id character varying NOT NULL,
  CONSTRAINT user_watchlist_pkey PRIMARY KEY (user_id, player_id),
  CONSTRAINT user_watchlist_player_id_fkey FOREIGN KEY (player_id) REFERENCES public.players(player_id),
  CONSTRAINT user_watchlist_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id)
);
CREATE TABLE public.users (
  user_id integer NOT NULL DEFAULT nextval('users_user_id_seq'::regclass),
  username text NOT NULL UNIQUE,
  email text NOT NULL UNIQUE,
  created_at timestamp with time zone DEFAULT now(),
  password character varying NOT NULL DEFAULT ''::character varying,
  CONSTRAINT users_pkey PRIMARY KEY (user_id)
);