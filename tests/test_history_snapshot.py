from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIRECTORY = (
    REPOSITORY_ROOT
    / "plugins"
    / "kicker-interactive-manager"
    / "skills"
    / "build-kicker-interactive-squad"
    / "scripts"
)
sys.path.insert(0, str(SCRIPT_DIRECTORY))

import history_snapshot


def career(*, proven_seasons: int = 2) -> dict:
    return {
        "appearances": 50,
        "starts": 44,
        "minutes": 3900,
        "goals": 8,
        "assists": 6,
        "level_adjusted_minutes": 3900.0,
        "comparable_minutes": 3900.0,
        "proven_seasons": proven_seasons,
        "youth_adjusted_minutes": 0.0,
        "youth_adjusted_contributions": 0.0,
        "youth_score": 0.0,
        "confirmed_score": 82.0,
        "recent_minutes_score": 78.0,
        "role_score": 74.0,
    }


def resolved_player() -> dict:
    return {
        "name": "Example Player",
        "club": "Example Club",
        "position": "MIDFIELDER",
        "mapping": {
            "status": "verified",
            "confidence": "high",
            "transfermarkt_player_id": 123,
            "transfermarkt_name": "Example Player",
            "transfermarkt_club": "Example Club",
            "profile_url": (
                "https://www.transfermarkt.co.uk/example/profil/spieler/123"
            ),
            "match_method": "exact_name_and_club",
        },
        "retrieved_at": "2026-07-24T12:00:00Z",
        "career": career(),
        "seasons": [
            {
                "season": 2025,
                "appearances": 25,
                "starts": 22,
                "minutes": 1950,
                "goals": 4,
                "assists": 3,
                "level_adjusted_minutes": 1950.0,
                "comparable_minutes": 1950.0,
                "youth_adjusted_minutes": 0.0,
                "youth_adjusted_contributions": 0.0,
                "proven": True,
                "competitions": [
                    {
                        "competition_id": "L2",
                        "label": "2. Bundesliga",
                        "kind": "domestic_league",
                        "strength_factor": 0.8,
                        "rated": True,
                        "appearances": 25,
                        "starts": 22,
                        "minutes": 1950,
                        "goals": 4,
                        "assists": 3,
                    }
                ],
            }
        ],
    }


def unresolved_player() -> dict:
    return {
        "name": "Unknown Player",
        "club": "Example Club",
        "position": "DEFENDER",
        "mapping": {
            "status": "unmatched",
            "confidence": "none",
            "transfermarkt_player_id": None,
            "reason": "no_current_squad_match",
        },
        "retrieved_at": None,
        "career": {
            key: 0.0 if "score" in key or "minutes" in key else 0
            for key in career(proven_seasons=0)
        },
        "seasons": [],
    }


def payload(now: datetime) -> dict:
    value = {
        "schema_version": history_snapshot.SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "expires_at": (now + timedelta(days=7)).isoformat(),
        "competition": "2. Bundesliga",
        "season": "2026/27",
        "market_sha256": "market",
        "model_version": "test-v1",
        "strength_model_sha256": "strength",
        "target_strength": 0.8,
        "source": {"provider": "Transfermarkt"},
        "requirements": {
            "player_count": 2,
            "minimum_resolved_percent": 50,
        },
        "players": {
            "p1": resolved_player(),
            "p2": unresolved_player(),
        },
    }
    value["content_sha256"] = history_snapshot.canonical_sha256(value)
    return value


class HistorySnapshotTests(unittest.TestCase):
    def test_validates_complete_market_inventory_and_audit(self) -> None:
        now = datetime(2026, 7, 24, 13, tzinfo=timezone.utc)
        value = payload(now)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            loaded = history_snapshot.load_snapshot(path, now=now)
        audit = history_snapshot.snapshot_audit(loaded)
        self.assertEqual(2, audit["player_count"])
        self.assertEqual(1, audit["resolved_player_count"])
        self.assertEqual(50.0, audit["resolved_percent"])
        self.assertEqual(1, audit["proven_player_count"])

    def test_rejects_silent_inventory_gap(self) -> None:
        now = datetime(2026, 7, 24, 13, tzinfo=timezone.utc)
        value = payload(now)
        value["requirements"]["player_count"] = 3
        value["content_sha256"] = history_snapshot.canonical_sha256(value)
        with self.assertRaisesRegex(
            history_snapshot.HistorySnapshotError,
            "player_count",
        ):
            history_snapshot.validate_snapshot(value, now=now)

    def test_rejects_unresolved_player_with_performance_data(self) -> None:
        now = datetime(2026, 7, 24, 13, tzinfo=timezone.utc)
        value = payload(now)
        value["players"]["p2"]["seasons"] = resolved_player()["seasons"]
        value["content_sha256"] = history_snapshot.canonical_sha256(value)
        with self.assertRaisesRegex(
            history_snapshot.HistorySnapshotError,
            "unresolved history player",
        ):
            history_snapshot.validate_snapshot(value, now=now)


if __name__ == "__main__":
    unittest.main()
