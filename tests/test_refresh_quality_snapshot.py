from __future__ import annotations

import sys
import unittest
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

import refresh_quality_snapshot as quality


def market_player(*, points: float = 100) -> dict:
    return {
        "id": "p1",
        "name": "Example Player",
        "club": "Example Club",
        "position": "FORWARD",
        "market_value": 800000,
        "points": points,
        "average_grade": 3.0,
        "source_url": "https://www.kicker.de/managerspiel/interactive",
    }


def news_player() -> dict:
    return {
        "mapping": {"api_sports_player_id": 123},
        "consensus": {
            "transfer": 0,
            "injury": 0,
            "rotation": 0,
            "fitness_cap": 100,
        },
    }


def api_history() -> list[dict]:
    return [
        {
            "season": 2025,
            "appearances": 30,
            "minutes": 2400,
            "lineups": 27,
            "rating": 7.0,
            "goals": 15,
            "assists": 5,
            "age": 28,
        },
        {
            "season": 2024,
            "appearances": 29,
            "minutes": 2300,
            "lineups": 25,
            "rating": 6.9,
            "goals": 12,
            "assists": 6,
            "age": 27,
        },
    ]


def transfermarkt_history(*, proven_seasons: int) -> dict:
    return {
        "mapping": {
            "status": "verified",
            "confidence": "high",
            "transfermarkt_player_id": 456,
            "profile_url": (
                "https://www.transfermarkt.co.uk/example/profil/spieler/456"
            ),
        },
        "career": {
            "proven_seasons": proven_seasons,
            "confirmed_score": 94.0 if proven_seasons >= 2 else 52.0,
            "recent_minutes_score": 92.0,
            "role_score": 86.0,
            "comparable_minutes": 6200.0 if proven_seasons >= 2 else 0.0,
            "level_adjusted_minutes": 6500.0,
        },
    }


class RefreshQualitySnapshotTests(unittest.TestCase):
    def test_reliable_anchor_requires_transfermarkt_target_level_history(self) -> None:
        annotation = quality.build_annotation(
            market_player(),
            "news-1",
            news_player(),
            api_history(),
            transfermarkt_history(proven_seasons=3),
            competition="2. Bundesliga",
            points_pct=90,
            price_pct=70,
            generated_at="2026-07-24T12:00:00Z",
        )
        self.assertTrue(annotation["reliable_anchor"])
        self.assertEqual(3, annotation["proven_seasons"])
        self.assertEqual(
            456,
            annotation["history_summary"]["transfermarkt_player_id"],
        )

        lower_level_only = quality.build_annotation(
            market_player(),
            "news-1",
            news_player(),
            api_history(),
            transfermarkt_history(proven_seasons=0),
            competition="2. Bundesliga",
            points_pct=90,
            price_pct=70,
            generated_at="2026-07-24T12:00:00Z",
        )
        self.assertFalse(lower_level_only["reliable_anchor"])
        self.assertEqual(0, lower_level_only["proven_seasons"])

    def test_candidate_rank_uses_history_not_only_previous_kicker_points(self) -> None:
        points = {"FORWARD": [0, 50, 100, 150]}
        prices = {"FORWARD": [400000, 800000, 1200000]}
        historically_proven = quality.candidate_rank(
            market_player(points=20),
            points,
            prices,
            transfermarkt_history(proven_seasons=3),
        )
        one_year_signal = quality.candidate_rank(
            market_player(points=130),
            points,
            prices,
            {
                "mapping": {"status": "unmatched"},
                "career": {"confirmed_score": 0},
            },
        )
        self.assertGreater(historically_proven, one_year_signal)


if __name__ == "__main__":
    unittest.main()
