"""
pga_pipeline/raw_store.py

Saves raw API responses to disk as JSON files with deterministic paths.

This layer exists so that:
  - raw data is preserved regardless of downstream failures
  - reruns can be debugged by diffing raw files
  - the pipeline can be re-run from disk without re-fetching

All paths are relative to a configurable base directory.
"""

import json
import logging
import os

logger = logging.getLogger(__name__)


class RawStore:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self._ensure(base_dir)
        self._ensure(os.path.join(base_dir, "schedules"))
        self._ensure(os.path.join(base_dir, "details"))
        self._ensure(os.path.join(base_dir, "leaderboards"))

    @staticmethod
    def _ensure(path: str):
        os.makedirs(path, exist_ok=True)

    def _write(self, path: str, data: dict):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.debug("Saved raw file: %s", path)

    def _read(self, path: str) -> dict | None:
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    # ------------------------------------------------------------------
    # Schedule
    # ------------------------------------------------------------------

    def schedule_path(self, year: str) -> str:
        return os.path.join(self.base_dir, "schedules", f"schedule_{year}.json")

    def save_schedule(self, year: str, data: dict):
        self._write(self.schedule_path(year), data)

    def load_schedule(self, year: str) -> dict | None:
        return self._read(self.schedule_path(year))

    # ------------------------------------------------------------------
    # Details
    # ------------------------------------------------------------------

    def details_path(self, tournament_id: str) -> str:
        return os.path.join(self.base_dir, "details", f"{tournament_id}.json")

    def save_details(self, tournament_id: str, data: dict):
        self._write(self.details_path(tournament_id), data)

    def load_details(self, tournament_id: str) -> dict | None:
        return self._read(self.details_path(tournament_id))

    # ------------------------------------------------------------------
    # Leaderboard (decoded payload)
    # ------------------------------------------------------------------

    def leaderboard_path(self, tournament_id: str) -> str:
        return os.path.join(
            self.base_dir, "leaderboards", f"{tournament_id}_decoded.json"
        )

    def save_leaderboard(self, tournament_id: str, data: dict):
        self._write(self.leaderboard_path(tournament_id), data)

    def load_leaderboard(self, tournament_id: str) -> dict | None:
        return self._read(self.leaderboard_path(tournament_id))

    def leaderboard_exists(self, tournament_id: str) -> bool:
        return os.path.exists(self.leaderboard_path(tournament_id))
