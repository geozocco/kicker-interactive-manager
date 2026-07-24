from __future__ import annotations

import json
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

import refresh_transfermarkt_history as transfermarkt


STRENGTH_MODEL = json.loads(
    (
        REPOSITORY_ROOT
        / "config"
        / "history"
        / "competition-strength.json"
    ).read_text(encoding="utf-8")
)


def appearances(competition_id: str, *, season: int) -> list[dict]:
    return [
        {
            "season": season,
            "competition_id": competition_id,
            "starts": 1,
            "minutes": 90,
            "goals": 1 if index % 7 == 0 else 0,
            "assists": 1 if index % 9 == 0 else 0,
        }
        for index in range(20)
    ]


class TransfermarktHistoryTests(unittest.TestCase):
    def test_same_output_is_weighted_by_league_level(self) -> None:
        second_seasons, second_career = transfermarkt.aggregate_history(
            appearances("L2", season=2025),
            position="FORWARD",
            target_strength=0.8,
            strength_model=STRENGTH_MODEL,
            maximum_seasons=8,
        )
        third_seasons, third_career = transfermarkt.aggregate_history(
            appearances("L3", season=2025),
            position="FORWARD",
            target_strength=0.8,
            strength_model=STRENGTH_MODEL,
            maximum_seasons=8,
        )
        self.assertTrue(second_seasons[0]["proven"])
        self.assertFalse(third_seasons[0]["proven"])
        self.assertGreater(
            second_career["level_adjusted_minutes"],
            third_career["level_adjusted_minutes"],
        )
        self.assertGreater(
            second_career["confirmed_score"],
            third_career["confirmed_score"],
        )

    def test_third_league_counts_as_comparable_for_third_league_target(self) -> None:
        seasons, career = transfermarkt.aggregate_history(
            appearances("L3", season=2025),
            position="FORWARD",
            target_strength=0.64,
            strength_model=STRENGTH_MODEL,
            maximum_seasons=8,
        )
        self.assertTrue(seasons[0]["proven"])
        self.assertEqual(1, career["proven_seasons"])

    def test_unrated_competition_is_recorded_without_score_credit(self) -> None:
        seasons, career = transfermarkt.aggregate_history(
            appearances("UNKNOWN", season=2025),
            position="MIDFIELDER",
            target_strength=0.8,
            strength_model=STRENGTH_MODEL,
            maximum_seasons=8,
        )
        self.assertFalse(seasons[0]["competitions"][0]["rated"])
        self.assertEqual(0.0, career["level_adjusted_minutes"])
        self.assertEqual(0, career["proven_seasons"])

    def test_exact_name_and_club_mapping_is_verified(self) -> None:
        mapping = transfermarkt.match_market_player(
            {"name": "Maximilian Arnold", "club": "VfL Wolfsburg"},
            [
                {
                    "player_id": 100,
                    "name": "Maximilian Arnold",
                    "club": "VfL Wolfsburg",
                    "club_id": 82,
                    "profile_url": "https://example.com/100",
                }
            ],
        )
        self.assertEqual("verified", mapping["status"])
        self.assertEqual(100, mapping["player_id"])


if __name__ == "__main__":
    unittest.main()
