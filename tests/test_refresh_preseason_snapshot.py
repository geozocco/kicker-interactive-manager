from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


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

import refresh_preseason_snapshot as refresh


def news_payload() -> dict:
    return {
        "competition": "3. Liga",
        "season": "2026/27",
        "players": {
            "api_sports:1": {
                "name": "Young Prospect",
                "club": "Example Club",
                "mapping": {
                    "confidence": "verified",
                    "api_sports_player_id": 1,
                    "api_sports_team_id": 10,
                    "age": 18,
                },
            }
        },
    }


def fixture() -> dict:
    return {
        "fixture": {
            "id": 99,
            "date": "2026-07-18T12:00:00+00:00",
        },
        "league": {
            "name": "Club Friendlies",
            "type": "Cup",
            "round": "Club Friendlies 3",
        },
        "teams": {
            "home": {"id": 10, "name": "Example Club"},
            "away": {"id": 20, "name": "Strong Opponent"},
        },
        "lineups": [
            {
                "team": {"id": 10},
                "startXI": [{"player": {"id": 1}}],
            }
        ],
        "players": [
            {
                "team": {"id": 10},
                "players": [
                    {
                        "player": {"id": 1, "name": "Young Prospect"},
                        "statistics": [
                            {
                                "games": {
                                    "minutes": 60,
                                    "position": "M",
                                },
                                "goals": {"total": 0, "assists": 0},
                            }
                        ],
                    }
                ],
            }
        ],
    }


def config() -> dict:
    return {
        "competition": "3. Liga",
        "season": "2026/27",
        "window": {
            "from": "2026-06-15",
            "to": "2026-08-31",
            "season_start": "2026-08-07",
            "decay_days": 28,
            "post_start_decay_days": 35,
        },
        "included_competition_patterns": ["friendly", "friendlies"],
        "players": {
            "api_sports:1": {
                "team_match_count": 2,
                "events": [
                    {
                        "date": "2026-07-14",
                        "opponent": "Other Opponent",
                        "appeared": True,
                        "started": False,
                        "minutes": 45,
                        "goals": 1,
                        "lineup_role": "mixed",
                        "training_status": "full",
                        "coach_signal": 65,
                        "opponent_score": 72,
                        "confidence": "high",
                        "claim": "Scored in an official club friendly.",
                        "source_provider": "official_club",
                        "source_url": "https://club.example/friendly",
                    }
                ],
            }
        },
    }


class RefreshPreseasonSnapshotTests(unittest.TestCase):
    def test_fixture_player_endpoint_supplies_stats_and_start_status(self) -> None:
        calls = []

        def pages(url, *, query, headers, paginate):
            calls.append((url, query))
            yield {
                "response": [
                    {
                        "team": {"id": 10},
                        "players": [
                            {
                                "player": {"id": 1},
                                "statistics": [
                                    {
                                        "games": {
                                            "minutes": 60,
                                            "position": "M",
                                            "substitute": False,
                                        },
                                        "goals": {"total": 0, "assists": 0},
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }

        base = fixture()
        base.pop("players")
        base.pop("lineups")
        with patch.object(refresh, "api_sports_pages", side_effect=pages):
            details, request_count, covered = refresh.fetch_fixture_details(
                {99: base},
                headers={"x-apisports-key": "secret"},
                request_delay=0,
            )

        observations = refresh.provider_observations(
            details[99],
            10,
            {1: "api_sports:1"},
        )
        self.assertEqual(
            "https://v3.football.api-sports.io/fixtures/players",
            calls[0][0],
        )
        self.assertEqual({"fixture": 99}, calls[0][1])
        self.assertEqual(1, request_count)
        self.assertEqual(1, covered)
        self.assertTrue(observations["api_sports:1"]["started"])

    def test_fixture_request_includes_provider_season(self) -> None:
        captured = []

        def pages(_url, *, query, headers, paginate):
            captured.append(query)
            yield {"response": []}

        with patch.object(refresh, "api_sports_pages", side_effect=pages):
            refresh.fetch_fixtures(
                [10],
                provider_season=2026,
                window_start=datetime(2026, 6, 15).date(),
                window_end=datetime(2026, 7, 25).date(),
                patterns=["friendlies"],
                headers={"x-apisports-key": "secret"},
                request_delay=0,
            )

        self.assertEqual(2026, captured[0]["season"])

    def test_provider_and_official_observations_form_bounded_signal(self) -> None:
        with (
            patch.object(
                refresh,
                "fetch_fixtures",
                return_value=({99: fixture()}, {10: {99}}, 1),
            ),
            patch.object(
                refresh,
                "fetch_fixture_details",
                return_value=({99: fixture()}, 1, 1),
            ),
        ):
            result = refresh.build_snapshot(
                news_payload(),
                config(),
                token="secret",
                request_delay=0,
                ttl_hours=18,
                now=datetime(2026, 7, 25, 12, tzinfo=timezone.utc),
            )

        player = result["players"]["api_sports:1"]
        summary = player["summary"]
        self.assertEqual(2, summary["appearances"])
        self.assertEqual(1, summary["starts"])
        self.assertEqual(105, summary["minutes"])
        self.assertEqual(1, summary["goals"])
        self.assertEqual("medium", summary["confidence"])
        self.assertIn(summary["classification"], {"positive", "strong"})
        self.assertLessEqual(summary["signal_score"], 100)
        self.assertEqual(2, result["providers"]["api_sports"]["requests"])

    def test_signal_decays_after_competitive_season_starts(self) -> None:
        observation = refresh.manual_observation(
            "p1",
            {
                "date": "2026-07-18",
                "opponent": "Opponent",
                "appeared": True,
                "started": True,
                "minutes": 90,
                "lineup_role": "first_group",
                "training_status": "full",
                "coach_signal": 90,
                "opponent_score": 70,
                "confidence": "high",
                "claim": "Started.",
                "source_url": "https://club.example/report",
            },
            0,
        )
        before = refresh.summarize(
            [observation],
            team_match_count=1,
            generated=datetime(2026, 8, 1, tzinfo=timezone.utc),
            season_start=datetime(2026, 8, 7).date(),
            decay_days=28,
            post_start_decay_days=35,
        )
        after = refresh.summarize(
            [observation],
            team_match_count=1,
            generated=datetime(2026, 9, 11, tzinfo=timezone.utc),
            season_start=datetime(2026, 8, 7).date(),
            decay_days=28,
            post_start_decay_days=35,
        )
        self.assertGreater(before["signal_score"], after["signal_score"])
        self.assertEqual(0.0, after["effective_factor"])
        self.assertEqual(50.0, after["signal_score"])

    def test_official_partial_training_is_a_recovery_signal_without_appearance(
        self,
    ) -> None:
        observation = refresh.manual_observation(
            "p1",
            {
                "date": "2026-07-20",
                "appeared": False,
                "training_status": "partial",
                "confidence": "high",
                "claim": "Works individually on his comeback.",
                "source_url": "https://club.example/comeback",
            },
            0,
        )
        summary = refresh.summarize(
            [observation],
            team_match_count=2,
            generated=datetime(2026, 7, 25, tzinfo=timezone.utc),
            season_start=datetime(2026, 8, 7).date(),
            decay_days=28,
            post_start_decay_days=35,
        )
        self.assertEqual("partial", summary["latest_training_status"])
        self.assertEqual("negative", summary["classification"])
        self.assertEqual(0, summary["appearances"])
        self.assertGreater(summary["official_source_count"], 0)


if __name__ == "__main__":
    unittest.main()
