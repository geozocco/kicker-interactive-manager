from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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
    @mock.patch.object(
        transfermarkt,
        "discover_squads",
        side_effect=RuntimeError("blocked"),
    )
    @mock.patch.object(
        transfermarkt,
        "request_json",
        side_effect=RuntimeError("blocked"),
    )
    def test_runner_blockade_uses_validated_bootstraps(
        self,
        _request_json: mock.Mock,
        _discover_squads: mock.Mock,
    ) -> None:
        identity = {
            "player_id": 123,
            "name": "Example Player",
            "club": "Example Club",
            "profile_url": (
                "https://www.transfermarkt.co.uk/example/profil/spieler/123"
            ),
        }
        seeded_seasons, seeded_career = transfermarkt.aggregate_history(
            appearances("L2", season=2025),
            position="FORWARD",
            target_strength=0.8,
            strength_model=STRENGTH_MODEL,
            maximum_seasons=8,
        )
        payload = transfermarkt.build_snapshot(
            {
                "competition": "2. Bundesliga",
                "season": "2026/27",
                "players": [
                    {
                        "id": "p1",
                        "name": "Example Player",
                        "club": "Example Club",
                        "position": "FORWARD",
                        "market_value": 500000,
                    }
                ],
            },
            {
                "competition": "2. Bundesliga",
                "season": "2026/27",
                "target_strength": 0.8,
                "maximum_seasons": 8,
                "minimum_resolved_percent": 75,
                "transfermarkt_competition_id": "L2",
            },
            STRENGTH_MODEL,
            previous=None,
            identity_seed=[identity],
            performance_seed={
                123: {
                    "retrieved_at": "2026-07-24T12:00:00Z",
                    "seasons": seeded_seasons,
                    "career": seeded_career,
                }
            },
            ttl_hours=192,
            minimum_refresh_age_hours=144,
            request_delay=0,
            timeout=1,
            workers=1,
        )
        player = payload["players"]["p1"]
        self.assertEqual("verified", player["mapping"]["status"])
        self.assertEqual(
            seeded_career["confirmed_score"],
            player["career"]["confirmed_score"],
        )

    def test_versioned_performance_bootstrap_matches_strength_model(self) -> None:
        strength_sha = transfermarkt.strength_model_sha256(STRENGTH_MODEL)
        values = transfermarkt.load_performance_seed(
            REPOSITORY_ROOT
            / "config"
            / "history"
            / "performance"
            / "2-bundesliga.json.gz",
            competition="2. Bundesliga",
            season="2026/27",
            strength_sha256=strength_sha,
            target_strength=0.8,
        )
        self.assertGreaterEqual(len(values), 450)
        self.assertTrue(
            all("seasons" in value and "career" in value for value in values.values())
        )

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

    def test_austrian_and_swiss_top_flights_match_third_league_level(self) -> None:
        for competition_id in ("A1", "CH1"):
            with self.subTest(competition_id=competition_id):
                second_target_seasons, second_target_career = (
                    transfermarkt.aggregate_history(
                        appearances(competition_id, season=2025),
                        position="FORWARD",
                        target_strength=0.8,
                        strength_model=STRENGTH_MODEL,
                        maximum_seasons=8,
                    )
                )
                third_target_seasons, third_target_career = (
                    transfermarkt.aggregate_history(
                        appearances(competition_id, season=2025),
                        position="FORWARD",
                        target_strength=0.64,
                        strength_model=STRENGTH_MODEL,
                        maximum_seasons=8,
                    )
                )
                self.assertFalse(second_target_seasons[0]["proven"])
                self.assertEqual(0, second_target_career["proven_seasons"])
                self.assertTrue(third_target_seasons[0]["proven"])
                self.assertEqual(1, third_target_career["proven_seasons"])
                self.assertEqual(
                    1800.0,
                    third_target_career["comparable_minutes"],
                )

    def test_youth_production_only_increases_upside_signal(self) -> None:
        seasons, career = transfermarkt.aggregate_history(
            appearances("19YL", season=2025),
            position="FORWARD",
            target_strength=0.8,
            strength_model=STRENGTH_MODEL,
            maximum_seasons=8,
        )
        self.assertFalse(seasons[0]["proven"])
        self.assertEqual(0, career["proven_seasons"])
        self.assertEqual(0.0, career["level_adjusted_minutes"])
        self.assertGreater(career["youth_adjusted_minutes"], 0)
        self.assertGreater(career["youth_score"], 50)

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

    def test_unique_cross_competition_identity_survives_club_change(
        self,
    ) -> None:
        mapping = transfermarkt.match_market_player(
            {"name": "Luca Erlein", "club": "Energie Cottbus"},
            [
                {
                    "player_id": 1009442,
                    "name": "Luca Erlein",
                    "club": "TSG 1899 Hoffenheim II",
                    "profile_url": (
                        "https://www.transfermarkt.co.uk/luca-erlein/"
                        "profil/spieler/1009442"
                    ),
                }
            ],
        )
        self.assertEqual("probable", mapping["status"])
        self.assertEqual(
            "globally_unique_exact_name",
            mapping["match_method"],
        )

    def test_additional_identity_seed_allows_another_competition(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "identities.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "competition": "3. Liga",
                        "season": "2026/27",
                        "players": [
                            {
                                "player_id": 1009442,
                                "name": "Luca Erlein",
                                "club": "TSG 1899 Hoffenheim II",
                                "profile_url": (
                                    "https://www.transfermarkt.co.uk/"
                                    "luca-erlein/profil/spieler/1009442"
                                ),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            identities = transfermarkt.load_identity_seed(
                path,
                competition=None,
                season="2026/27",
            )
        self.assertEqual(1009442, identities[0]["player_id"])


if __name__ == "__main__":
    unittest.main()
