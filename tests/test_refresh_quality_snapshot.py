from __future__ import annotations

import sys
import unittest
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

import refresh_quality_snapshot as quality


class QualityProviderRetryTests(unittest.TestCase):
    def test_matching_previous_quality_history_is_reused_by_season(
        self,
    ) -> None:
        history = {"season": 2025, "appearances": 20}
        previous = {
            "competition": "3. Liga",
            "season": "2026/27",
            "model_version": quality.MODEL_VERSION,
            "annotations": {
                "p1": {
                    "provider_news_id": "api_sports:123",
                    "api_sports_history": [history],
                }
            },
        }

        cached = quality.cached_api_histories(
            previous,
            competition="3. Liga",
            season="2026/27",
            player_id="p1",
            news_id="api_sports:123",
        )

        self.assertEqual({2025: history}, cached)
        self.assertEqual(
            {},
            quality.cached_api_histories(
                previous,
                competition="3. Liga",
                season="2026/27",
                player_id="p1",
                news_id="api_sports:999",
            ),
        )

    def test_previous_model_raw_history_is_reused_during_model_migration(
        self,
    ) -> None:
        previous = {
            "competition": "3. Liga",
            "season": "2026/27",
            "model_version": "multi-season-v6-goalkeeper-hierarchy",
            "annotations": {
                "p1": {
                    "provider_news_id": "api_sports:123",
                    "api_sports_history": [
                        {"season": 2025, "appearances": 20}
                    ],
                }
            },
        }

        self.assertEqual(
            {2025: {"season": 2025, "appearances": 20}},
            quality.cached_api_histories(
                previous,
                competition="3. Liga",
                season="2026/27",
                player_id="p1",
                news_id="api_sports:123",
            ),
        )

    def test_current_season_is_reused_only_during_model_migration(self) -> None:
        previous = {
            "competition": "3. Liga",
            "season": "2026/27",
            "model_version": "multi-season-v7-recency-form",
            "annotations": {
                "p1": {
                    "provider_news_id": "api_sports:123",
                    "api_sports_history": [
                        {"season": 2026, "appearances": 1}
                    ],
                }
            },
        }
        cached = quality.cached_api_histories(
            previous,
            competition="3. Liga",
            season="2026/27",
            player_id="p1",
            news_id="api_sports:123",
        )
        self.assertIn(2026, cached)

    def test_current_season_history_is_refreshed(self) -> None:
        previous = {
            "competition": "3. Liga",
            "season": "2026/27",
            "model_version": quality.MODEL_VERSION,
            "annotations": {
                "p1": {
                    "provider_news_id": "api_sports:123",
                    "api_sports_history": [
                        {"season": 2026, "appearances": 1},
                        {"season": 2025, "appearances": 20},
                    ],
                }
            },
        }

        cached = quality.cached_api_histories(
            previous,
            competition="3. Liga",
            season="2026/27",
            player_id="p1",
            news_id="api_sports:123",
        )

        self.assertEqual({2025}, set(cached))
        self.assertEqual(
            {2025, 2026},
            set(
                quality.cached_api_histories(
                    previous,
                    competition="3. Liga",
                    season="2026/27",
                    player_id="p1",
                    news_id="api_sports:123",
                    include_current=True,
                )
            ),
        )

    @patch.object(quality.time, "sleep")
    @patch.object(quality, "api_sports_pages")
    def test_player_history_waits_a_full_window_after_http_429(
        self,
        api_sports_pages,
        sleep,
    ) -> None:
        api_sports_pages.side_effect = [
            RuntimeError(
                "provider request failed: HTTP Error 429: Too Many Requests"
            ),
            [],
        ]

        result = quality.fetch_player_season(
            123,
            2025,
            headers={"x-apisports-key": "test"},
            request_delay=0.1,
        )

        self.assertEqual(0, result["appearances"])
        self.assertEqual(65, sleep.call_args_list[0].args[0])


class BenchmarkResilienceTests(unittest.TestCase):
    def test_quality_builder_keeps_four_benchmark_references_per_position(
        self,
    ) -> None:
        annotations = {}
        for position in ("DEFENDER", "MIDFIELDER", "FORWARD"):
            for index in range(6):
                annotations[f"{position}-{index}"] = {
                    "position": position,
                    "components": {
                        "confirmed_performance": float(100 - index)
                    },
                    "proven_seasons": 6 - index,
                    "benchmark": False,
                }

        quality.mark_benchmark_references(annotations)

        for position in ("DEFENDER", "MIDFIELDER", "FORWARD"):
            selected = [
                player_id
                for player_id, annotation in annotations.items()
                if annotation["position"] == position
                and annotation["benchmark"]
            ]
            self.assertEqual(4, len(selected))


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


def richer_api_history() -> list[dict]:
    histories = api_history()
    histories[0].update(
        {
            "shots_on": 42,
            "key_passes": 36,
            "passes_total": 850,
            "pass_accuracy": 81,
            "duels": 190,
            "duels_won": 105,
            "dribbles_attempted": 70,
            "dribbles_successful": 39,
            "tackles": 18,
            "blocks": 2,
            "interceptions": 9,
        }
    )
    return histories


def form_season(
    season: int,
    *,
    minutes: int,
    lineups: int,
    rating: float,
    goals: int,
    assists: int,
    club: str = "Example Club",
) -> dict:
    return {
        **quality.empty_season_stats(season, 24),
        "appearances": 30,
        "minutes": minutes,
        "lineups": lineups,
        "rating": rating,
        "goals": goals,
        "assists": assists,
        "shots_on": goals * 3,
        "key_passes": assists * 5,
        "clubs": [
            {
                "name": club,
                "appearances": 30,
                "minutes": minutes,
            }
        ],
    }


def transfermarkt_history(
    *,
    proven_seasons: int,
    youth_score: float = 0,
) -> dict:
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
            "youth_adjusted_minutes": 2400.0 if youth_score else 0.0,
            "youth_adjusted_contributions": 22.0 if youth_score else 0.0,
            "youth_score": youth_score,
        },
    }


def exceptional_goalkeeper_history() -> dict:
    return {
        "mapping": {
            "status": "verified",
            "confidence": "high",
            "transfermarkt_player_id": 1009438,
            "profile_url": (
                "https://www.transfermarkt.de/florian-hellstern/"
                "profil/spieler/1009438"
            ),
        },
        "career": {
            "proven_seasons": 0,
            "confirmed_score": 28.12,
            "recent_minutes_score": 69.04,
            "role_score": 90.0,
            "comparable_minutes": 0.0,
            "level_adjusted_minutes": 1872.0,
            "youth_adjusted_minutes": 8845.0,
            "youth_adjusted_contributions": 0.0,
            "youth_score": 55.0,
        },
        "seasons": [
            {
                "season": 2025,
                "competitions": [
                    {
                        "competition_id": "L3",
                        "label": "3. Liga",
                        "kind": "domestic_league",
                        "strength_factor": 0.64,
                        "minutes": 2340,
                    },
                    {
                        "competition_id": "U19Q",
                        "label": "U19-Nationalmannschaft",
                        "kind": "youth",
                        "strength_factor": 0.55,
                        "minutes": 630,
                    },
                ],
            },
            {
                "season": 2024,
                "competitions": [
                    {
                        "competition_id": "U18",
                        "label": "U18-Nationalmannschaft",
                        "kind": "youth",
                        "strength_factor": 0.52,
                        "minutes": 360,
                    },
                    {
                        "competition_id": "19YL",
                        "label": "UEFA Youth League",
                        "kind": "youth",
                        "strength_factor": 0.48,
                        "minutes": 450,
                    },
                ],
            },
        ],
    }


class RefreshQualitySnapshotTests(unittest.TestCase):
    def test_recovery_preserves_healthy_quality_but_caps_readiness(self) -> None:
        histories = [
            form_season(
                2025,
                minutes=350,
                lineups=2,
                rating=6.4,
                goals=0,
                assists=0,
            ),
            form_season(
                2024,
                minutes=2500,
                lineups=28,
                rating=7.0,
                goals=8,
                assists=6,
            ),
        ]
        profile = quality.historical_form_profile(
            position="MIDFIELDER",
            histories=histories,
            history_player={"seasons": []},
            market_club="Example Club",
            news_player=news_player(),
            age=27,
        )
        self.assertEqual("recent_availability_drop", profile["recovery_status"])
        self.assertGreaterEqual(
            profile["adjustments"]["confirmed_performance"],
            0,
        )

        adjustment = quality.preseason_adjustment(
            {
                "summary": {
                    "appearances": 0,
                    "starts": 0,
                    "minutes": 0,
                    "goals": 0,
                    "assists": 0,
                    "official_source_count": 1,
                    "availability_score": 28,
                    "role_score": 35,
                    "performance_score": 45,
                    "opponent_score": 50,
                    "training_score": 55,
                    "latest_training_status": "partial",
                    "signal_score": 37,
                    "effective_factor": 100,
                    "confidence": "medium",
                    "classification": "negative",
                }
            },
            age=27,
            proven_seasons=3,
            comparable_minutes=6000,
            youth_score=0,
            talent_score=40,
            minutes=82,
            role=78,
            upside=45,
            value=77,
            unknown_role=20,
            fitness=90,
            injury_risk=0,
        )
        self.assertTrue(adjustment["available"])
        self.assertEqual(45, adjustment["injury_risk"])
        self.assertLessEqual(adjustment["components"]["fitness"], 68)

    def test_strong_third_tier_season_gets_bounded_translation_not_anchor_proof(
        self,
    ) -> None:
        history = transfermarkt_history(proven_seasons=0)
        history["seasons"] = [
            {
                "season": 2025,
                "competitions": [
                    {
                        "label": "3. Liga",
                        "kind": "domestic_league",
                        "strength_factor": 0.64,
                        "appearances": 34,
                        "starts": 31,
                        "minutes": 2700,
                        "goals": 12,
                        "assists": 10,
                    }
                ],
            }
        ]
        profile = quality.lower_league_translation_profile(
            history,
            position="MIDFIELDER",
            target_strength=0.8,
            age=22,
        )
        self.assertEqual("standout_lower_league", profile["status"])
        self.assertGreater(profile["value_bonus"], 0)
        self.assertLessEqual(profile["value_bonus"], 8)
        self.assertEqual(0, history["career"]["proven_seasons"])
    def test_recent_form_outweighs_older_form(self) -> None:
        strong = form_season(
            2025,
            minutes=2500,
            lineups=28,
            rating=7.2,
            goals=15,
            assists=7,
        )
        weak = form_season(
            2024,
            minutes=900,
            lineups=7,
            rating=6.1,
            goals=2,
            assists=1,
        )
        current_strong = quality.historical_form_profile(
            position="FORWARD",
            histories=[strong, weak],
            history_player={"seasons": []},
            market_club="Example Club",
            news_player=news_player(),
            age=26,
        )
        current_weak = quality.historical_form_profile(
            position="FORWARD",
            histories=[
                {**weak, "season": 2025},
                {**strong, "season": 2024},
            ],
            history_player={"seasons": []},
            market_club="Example Club",
            news_player=news_player(),
            age=26,
        )

        self.assertGreater(
            current_strong["score"],
            current_weak["score"],
        )
        self.assertEqual(1.0, current_strong["seasons"][0]["recency_weight"])
        self.assertEqual(0.62, current_strong["seasons"][1]["recency_weight"])

    def test_form_respects_historical_competition_level(self) -> None:
        provider = form_season(
            2025,
            minutes=2400,
            lineups=27,
            rating=7.2,
            goals=15,
            assists=7,
        )
        season = {
            "season": 2025,
            "appearances": 30,
            "starts": 27,
            "minutes": 2400,
            "goals": 15,
            "assists": 7,
        }
        target_level = quality.historical_form_profile(
            position="FORWARD",
            histories=[provider],
            history_player={
                "seasons": [
                    {
                        **season,
                        "level_adjusted_minutes": 2400,
                    }
                ]
            },
            market_club="Example Club",
            news_player=news_player(),
            age=25,
        )
        lower_level = quality.historical_form_profile(
            position="FORWARD",
            histories=[provider],
            history_player={
                "seasons": [
                    {
                        **season,
                        "level_adjusted_minutes": 960,
                    }
                ]
            },
            market_club="Example Club",
            news_player=news_player(),
            age=25,
        )

        self.assertGreater(target_level["score"], lower_level["score"])
        self.assertEqual(
            0.4,
            lower_level["seasons"][0]["competition_context_factor"],
        )

    def test_empty_current_season_does_not_hide_previous_form(self) -> None:
        previous = form_season(
            2025,
            minutes=2300,
            lineups=25,
            rating=7.0,
            goals=11,
            assists=6,
        )
        profile = quality.historical_form_profile(
            position="FORWARD",
            histories=[
                quality.empty_season_stats(2026, 25),
                previous,
            ],
            history_player={"seasons": []},
            market_club="Example Club",
            news_player=news_player(),
            age=25,
        )

        self.assertEqual(1, profile["season_count"])
        self.assertEqual(2025, profile["seasons"][0]["season"])

    def test_young_positive_trajectory_gets_development_adjustment(self) -> None:
        strong = form_season(
            2025,
            minutes=1800,
            lineups=20,
            rating=7.0,
            goals=8,
            assists=6,
        )
        weak = form_season(
            2024,
            minutes=700,
            lineups=5,
            rating=6.2,
            goals=1,
            assists=1,
        )
        young = quality.historical_form_profile(
            position="MIDFIELDER",
            histories=[strong, weak],
            history_player={"seasons": []},
            market_club="Example Club",
            news_player=news_player(),
            age=19,
        )
        established = quality.historical_form_profile(
            position="MIDFIELDER",
            histories=[strong, weak],
            history_player={"seasons": []},
            market_club="Example Club",
            news_player=news_player(),
            age=27,
        )

        self.assertGreater(young["development_adjustment"], 0)
        self.assertEqual(0, established["development_adjustment"])
        self.assertGreater(
            young["adjustments"]["upside"],
            established["adjustments"]["upside"],
        )

    def test_club_change_reduces_form_transferability_not_form_score(
        self,
    ) -> None:
        history = [
            form_season(
                2025,
                minutes=2300,
                lineups=25,
                rating=7.0,
                goals=10,
                assists=5,
                club="Old Club",
            ),
            form_season(
                2024,
                minutes=2100,
                lineups=23,
                rating=6.9,
                goals=9,
                assists=5,
                club="Old Club",
            ),
        ]
        stable = quality.historical_form_profile(
            position="FORWARD",
            histories=history,
            history_player={"seasons": []},
            market_club="Old Club",
            news_player=news_player(),
            age=25,
        )
        transferred = quality.historical_form_profile(
            position="FORWARD",
            histories=history,
            history_player={"seasons": []},
            market_club="New Club",
            news_player=news_player(),
            age=25,
        )

        self.assertEqual(stable["score"], transferred["score"])
        self.assertFalse(stable["club_changed"])
        self.assertTrue(transferred["club_changed"])
        self.assertEqual(1.0, stable["context_transfer_factor"])
        self.assertEqual(0.58, transferred["context_transfer_factor"])
        self.assertGreater(
            transferred["adjustments"]["unknown_role_risk"],
            stable["adjustments"]["unknown_role_risk"],
        )

    def test_confirmed_new_club_role_removes_blanket_transfer_malus(
        self,
    ) -> None:
        history = [
            form_season(
                2025,
                minutes=2300,
                lineups=25,
                rating=7.0,
                goals=10,
                assists=5,
                club="Old Club",
            )
        ]
        history[0]["penalties_scored"] = 3
        role_evidence = {
            "continuity": "confirmed",
            "confidence": "high",
            "expected_start_probability": 92,
            "team_quality_delta": 14,
            "responsibilities": {
                "direct_free_kicks": "shared",
                "corners": "shared",
                "playmaker": "shared",
                "offensive_focal_point": "primary",
            },
            "evidence": [
                {
                    "claim": "Signed for the same leading attacking role",
                    "source_url": "https://example.com/role",
                    "checked_at": "2026-07-28T10:00:00Z",
                }
            ],
        }

        unconfirmed = quality.historical_form_profile(
            position="FORWARD",
            histories=history,
            history_player={"seasons": []},
            market_club="New Club",
            news_player=news_player(),
            age=25,
        )
        confirmed = quality.historical_form_profile(
            position="FORWARD",
            histories=history,
            history_player={"seasons": []},
            market_club="New Club",
            news_player=news_player(),
            age=25,
            role_evidence=role_evidence,
        )
        role = quality.expected_role_profile(
            position="FORWARD",
            histories=history,
            role_evidence=role_evidence,
            club_changed=True,
        )

        self.assertEqual(0.58, unconfirmed["context_transfer_factor"])
        self.assertEqual(1.0, confirmed["context_transfer_factor"])
        self.assertEqual("confirmed", confirmed["role_continuity"])
        self.assertLess(
            confirmed["adjustments"]["unknown_role_risk"],
            unconfirmed["adjustments"]["unknown_role_risk"],
        )
        self.assertGreater(role["adjustments"]["context"], 0)
        self.assertEqual(
            "primary",
            role["responsibilities"]["offensive_focal_point"],
        )
        self.assertEqual("none", role["responsibilities"]["penalties"])

    def test_defender_set_piece_target_receives_role_credit(self) -> None:
        role = quality.expected_role_profile(
            position="DEFENDER",
            histories=[],
            club_changed=False,
            role_evidence={
                "continuity": "confirmed",
                "confidence": "high",
                "expected_start_probability": 96,
                "team_quality_delta": 5,
                "responsibilities": {
                    "aerial_set_piece_target": "primary",
                    "captain": "primary",
                },
                "evidence": [
                    {
                        "claim": "Captain and primary aerial target",
                        "source_url": "https://example.com/set-piece-role",
                        "checked_at": "2026-07-28T10:00:00Z",
                    }
                ],
            },
        )

        self.assertEqual(
            "primary",
            role["responsibilities"]["aerial_set_piece_target"],
        )
        self.assertGreater(role["adjustments"]["role"], 0)
        self.assertLessEqual(role["adjustments"]["rotation_risk_cap"], 4)

    def test_unknown_training_status_does_not_reduce_fitness(self) -> None:
        adjustment = quality.preseason_adjustment(
            {
                "summary": {
                    "appearances": 2,
                    "starts": 2,
                    "minutes": 150,
                    "goals": 1,
                    "assists": 1,
                    "official_source_count": 2,
                    "availability_score": 90,
                    "role_score": 88,
                    "performance_score": 82,
                    "opponent_score": 70,
                    "training_score": 50,
                    "latest_training_status": "unknown",
                    "signal_score": 84,
                    "effective_factor": 100,
                    "confidence": "high",
                    "classification": "positive",
                }
            },
            age=22,
            proven_seasons=1,
            comparable_minutes=1500,
            youth_score=70,
            talent_score=75,
            minutes=80,
            role=78,
            upside=72,
            value=74,
            unknown_role=22,
            fitness=92,
            injury_risk=5,
        )

        self.assertEqual(92, adjustment["components"]["fitness"])

    def test_availability_drop_and_current_injury_are_visible(self) -> None:
        histories = [
            form_season(
                2025,
                minutes=400,
                lineups=3,
                rating=6.4,
                goals=1,
                assists=0,
            ),
            form_season(
                2024,
                minutes=2400,
                lineups=27,
                rating=6.9,
                goals=10,
                assists=6,
            ),
        ]
        availability_drop = quality.historical_form_profile(
            position="FORWARD",
            histories=histories,
            history_player={"seasons": []},
            market_club="Example Club",
            news_player=news_player(),
            age=27,
        )
        injured_news = news_player()
        injured_news["consensus"]["injury"] = 60
        current_injury = quality.historical_form_profile(
            position="FORWARD",
            histories=histories,
            history_player={"seasons": []},
            market_club="Example Club",
            news_player=injured_news,
            age=27,
        )

        self.assertEqual(
            "recent_availability_drop",
            availability_drop["recovery_status"],
        )
        self.assertEqual(
            "current_injury_or_recovery",
            current_injury["recovery_status"],
        )

    def test_goalkeeper_shortlist_keeps_every_keeper_in_every_complete_club(
        self,
    ) -> None:
        market_players = [
            {
                "id": f"{club}-{index}",
                "name": f"{club} Keeper {index}",
                "club": club,
                "position": "GOALKEEPER",
                "market_value": 100_000 * index,
                "points": 0,
                "available": True,
            }
            for club in ("Club A", "Club B")
            for index in range(1, 5)
        ]
        news_players = {
            f"api_sports:{provider_id}": {
                "name": player["name"],
                "club": player["club"],
                "mapping": {
                    "confidence": "verified",
                    "api_sports_player_id": provider_id,
                },
            }
            for provider_id, player in enumerate(
                market_players,
                start=1,
            )
        }
        history = {
            "players": {
                player["id"]: {
                    "mapping": {"status": "unmatched"},
                    "career": {"confirmed_score": 0, "proven_seasons": 0},
                }
                for player in market_players
            }
        }

        selected = quality.select_candidates(
            {"players": market_players},
            {"players": news_players},
            history,
            {
                "GOALKEEPER": 3,
                "DEFENDER": 0,
                "MIDFIELDER": 0,
                "FORWARD": 0,
            },
        )

        self.assertEqual(8, len(selected))
        self.assertEqual(
            {"Club A", "Club B"},
            {player["club"] for player, _, _ in selected},
        )

    def test_goalkeeper_hierarchy_uses_club_gap_and_price_share(self) -> None:
        market = {
            "players": [
                {
                    "id": "g1",
                    "name": "Clear Number One",
                    "club": "Example Club",
                    "position": "GOALKEEPER",
                    "market_value": 800_000,
                    "available": True,
                },
                {
                    "id": "g2",
                    "name": "Second Keeper",
                    "club": "Example Club",
                    "position": "GOALKEEPER",
                    "market_value": 100_000,
                    "available": True,
                },
                {
                    "id": "g3",
                    "name": "Third Keeper",
                    "club": "Example Club",
                    "position": "GOALKEEPER",
                    "market_value": 100_000,
                    "available": True,
                },
            ]
        }
        news = {
            "players": {
                f"api_sports:{index}": {
                    "name": player["name"],
                    "club": "Example Club",
                    "mapping": {
                        "position": "Goalkeeper",
                        "api_sports_team_id": 10,
                        "api_sports_player_id": index,
                        "confidence": "verified",
                    },
                    "signals": [],
                }
                for index, player in enumerate(
                    market["players"],
                    start=1,
                )
            }
        }
        annotations = {}
        for index, player in enumerate(market["players"], start=1):
            primary = index == 1
            annotations[player["id"]] = {
                "position": "GOALKEEPER",
                "club": "Example Club",
                "components": {
                    "confirmed_performance": 86 if primary else 35,
                    "minutes": 92 if primary else 35,
                    "role": 90 if primary else 32,
                    "stability": 80,
                    "context": 70,
                    "fitness": 85,
                    "upside": 75 if primary else 45,
                    "value": 60,
                },
                "risks": {
                    "transfer": 5,
                    "injury": 5,
                    "rotation": 5 if primary else 60,
                    "outlier": 10,
                    "unknown_role": 5 if primary else 50,
                },
                "proven_seasons": 2 if primary else 0,
                "evidence": [],
                "note": "",
            }

        quality.apply_goalkeeper_hierarchy(
            annotations,
            market,
            news,
            {},
        )

        leader = annotations["g1"]["goalkeeper_outlook"]
        self.assertEqual(1, leader["club_rank"])
        self.assertEqual("high", leader["confidence"])
        self.assertEqual("clear_favourite", leader["status"])
        self.assertGreaterEqual(leader["starter_probability"], 80)
        self.assertEqual(80.0, leader["club_price_share"])

    def test_unpriced_incoming_keeper_blocks_false_starter_certainty(self) -> None:
        market = {
            "players": [
                {
                    "id": f"g{index}",
                    "name": f"Keeper {index}",
                    "club": "Example Club",
                    "position": "GOALKEEPER",
                    "market_value": value,
                    "available": True,
                }
                for index, value in enumerate(
                    (800_000, 100_000, 100_000),
                    start=1,
                )
            ]
        }
        news_players = {
            f"api_sports:{index}": {
                "name": player["name"],
                "club": "Example Club",
                "mapping": {
                    "position": "Goalkeeper",
                    "api_sports_team_id": 10,
                    "api_sports_player_id": index,
                    "confidence": "verified",
                },
                "signals": [],
            }
            for index, player in enumerate(market["players"], start=1)
        }
        news_players["api_sports:99"] = {
            "name": "New Goalkeeper",
            "club": "Example Club",
            "mapping": {
                "position": "Goalkeeper",
                "api_sports_team_id": 10,
                "api_sports_player_id": 99,
                "confidence": "verified",
            },
            "signals": [
                {
                    "kind": "transfer_confirmed",
                    "availability_impact": "in",
                }
            ],
        }
        annotations = {
            player["id"]: {
                "position": "GOALKEEPER",
                "club": "Example Club",
                "components": {
                    key: (
                        90
                        if player["id"] == "g1"
                        and key in {"minutes", "role"}
                        else 70
                        if player["id"] == "g1"
                        else 35
                    )
                    for key in (
                        "confirmed_performance",
                        "minutes",
                        "role",
                        "stability",
                        "context",
                        "fitness",
                        "upside",
                        "value",
                    )
                },
                "risks": {
                    key: 5 if player["id"] == "g1" else 45
                    for key in (
                        "transfer",
                        "injury",
                        "rotation",
                        "outlier",
                        "unknown_role",
                    )
                },
                "proven_seasons": 2 if player["id"] == "g1" else 0,
                "evidence": [],
                "note": "",
            }
            for player in market["players"]
        }

        quality.apply_goalkeeper_hierarchy(
            annotations,
            market,
            {"players": news_players},
            {},
        )

        leader = annotations["g1"]["goalkeeper_outlook"]
        self.assertEqual("external_signing_risk", leader["status"])
        self.assertGreaterEqual(leader["external_signing_risk"], 55)
        self.assertEqual(1, leader["incoming_unpriced_goalkeeper_count"])

    @patch.object(quality.time, "sleep")
    @patch.object(quality, "api_sports_pages")
    def test_fetch_player_season_normalizes_rich_provider_statistics(
        self,
        api_sports_pages,
        _sleep,
    ) -> None:
        api_sports_pages.return_value = [
            {
                "response": [
                    {
                        "player": {"age": 27},
                        "statistics": [
                            {
                                "team": {"name": "Example Club"},
                                "games": {
                                    "appearences": 20,
                                    "minutes": 1500,
                                    "lineups": 17,
                                    "rating": "7.1",
                                },
                                "substitutes": {
                                    "in": 3,
                                    "out": 7,
                                    "bench": 5,
                                },
                                "shots": {"total": 40, "on": 19},
                                "goals": {
                                    "total": 8,
                                    "conceded": 0,
                                    "assists": 6,
                                    "saves": 0,
                                },
                                "passes": {
                                    "total": 700,
                                    "key": 31,
                                    "accuracy": "82%",
                                },
                                "tackles": {
                                    "total": 24,
                                    "blocks": 3,
                                    "interceptions": 17,
                                },
                                "duels": {"total": 160, "won": 91},
                                "dribbles": {
                                    "attempts": 44,
                                    "success": 26,
                                },
                                "fouls": {"drawn": 30, "committed": 18},
                                "cards": {
                                    "yellow": 4,
                                    "yellowred": 1,
                                    "red": 0,
                                },
                                "penalty": {
                                    "scored": 2,
                                    "missed": 1,
                                    "saved": 0,
                                },
                            }
                        ],
                    }
                ]
            }
        ]
        result = quality.fetch_player_season(
            123,
            2025,
            headers={"x-apisports-key": "not-a-real-key"},
            request_delay=0,
        )
        self.assertEqual(31, result["key_passes"])
        self.assertEqual(19, result["shots_on"])
        self.assertEqual(41, result["tackles"] + result["interceptions"])
        self.assertEqual(82.0, result["pass_accuracy"])
        self.assertEqual(5, result["yellow_cards"])
        self.assertEqual(
            [
                {
                    "name": "Example Club",
                    "appearances": 20,
                    "minutes": 1500,
                }
            ],
            result["clubs"],
        )

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

    def test_verified_club_change_resets_anchor_role_confidence(self) -> None:
        stable_history = api_history()
        changed_history = api_history()
        for stable, changed in zip(stable_history, changed_history):
            stable["clubs"] = [
                {
                    "name": "Example Club",
                    "appearances": stable["appearances"],
                    "minutes": stable["minutes"],
                }
            ]
            changed["clubs"] = [
                {
                    "name": "Previous Club",
                    "appearances": changed["appearances"],
                    "minutes": changed["minutes"],
                }
            ]
        stable = quality.build_annotation(
            market_player(),
            "news-1",
            news_player(),
            stable_history,
            transfermarkt_history(proven_seasons=3),
            competition="2. Bundesliga",
            points_pct=90,
            price_pct=70,
            generated_at="2026-07-24T12:00:00Z",
        )
        transferred = quality.build_annotation(
            market_player(),
            "news-1",
            news_player(),
            changed_history,
            transfermarkt_history(proven_seasons=3),
            competition="2. Bundesliga",
            points_pct=90,
            price_pct=70,
            generated_at="2026-07-24T12:00:00Z",
        )

        self.assertTrue(stable["reliable_anchor"])
        self.assertFalse(transferred["reliable_anchor"])
        self.assertTrue(transferred["form_summary"]["club_changed"])
        self.assertGreater(
            transferred["risks"]["unknown_role"],
            stable["risks"]["unknown_role"],
        )

    def test_confirmed_transfer_role_keeps_quality_but_not_news_rotation(
        self,
    ) -> None:
        changed_history = api_history()
        for season in changed_history:
            season["clubs"] = [
                {
                    "name": "Previous Club",
                    "appearances": season["appearances"],
                    "minutes": season["minutes"],
                }
            ]
        current_news = news_player()
        current_news["consensus"]["rotation"] = 55
        current_news["consensus"]["transfer"] = 10
        current_news["signals"] = [
            {
                "kind": "transfer_confirmed",
                "status": "confirmed",
                "availability_impact": "in",
            }
        ]
        annotation = quality.build_annotation(
            market_player(),
            "news-1",
            current_news,
            changed_history,
            transfermarkt_history(proven_seasons=3),
            role_evidence={
                "continuity": "confirmed",
                "confidence": "high",
                "expected_start_probability": 92,
                "team_quality_delta": 12,
                "responsibilities": {
                    "offensive_focal_point": "primary",
                },
                "evidence": [
                    {
                        "claim": "Current club confirms a leading role",
                        "source_url": "https://example.com/current-role",
                        "checked_at": "2026-07-28",
                    }
                ],
            },
            competition="2. Bundesliga",
            points_pct=90,
            price_pct=70,
            generated_at="2026-07-28T12:00:00Z",
        )

        self.assertEqual(
            1.0,
            annotation["form_summary"]["context_transfer_factor"],
        )
        self.assertEqual(
            "confirmed",
            annotation["role_context"]["continuity"],
        )
        self.assertGreaterEqual(annotation["risks"]["rotation"], 55)
        self.assertEqual(0, annotation["risks"]["transfer"])

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

    def test_youth_history_raises_upside_but_never_creates_anchor(self) -> None:
        young_history = api_history()
        for index, season in enumerate(young_history):
            season["age"] = 20 - index
        annotation = quality.build_annotation(
            market_player(points=20),
            "news-1",
            news_player(),
            young_history,
            transfermarkt_history(
                proven_seasons=0,
                youth_score=92,
            ),
            competition="2. Bundesliga",
            points_pct=15,
            price_pct=20,
            generated_at="2026-07-24T12:00:00Z",
        )
        self.assertGreaterEqual(annotation["components"]["upside"], 90)
        self.assertFalse(annotation["reliable_anchor"])
        self.assertEqual(0, annotation["proven_seasons"])
        self.assertEqual(92, annotation["history_summary"]["youth_score"])

    def test_candidate_rank_uses_strong_youth_signal_for_shortlisting(self) -> None:
        points = {"FORWARD": [0, 50, 100, 150]}
        prices = {"FORWARD": [400000, 800000, 1200000]}
        youth_prospect = quality.candidate_rank(
            market_player(points=20),
            points,
            prices,
            transfermarkt_history(
                proven_seasons=0,
                youth_score=92,
            ),
        )
        unresolved = quality.candidate_rank(
            market_player(points=20),
            points,
            prices,
            {
                "mapping": {"status": "unmatched"},
                "career": {"confirmed_score": 0, "youth_score": 0},
            },
        )
        self.assertGreater(youth_prospect, unresolved)

    def test_exceptional_talent_uses_age_adjusted_senior_and_youth_pathway(self) -> None:
        profile = quality.youth_talent_profile(
            exceptional_goalkeeper_history(),
            18,
        )
        self.assertEqual("exceptional", profile["talent_tier"])
        self.assertEqual("exceptional_early", profile["breakthrough_phase"])
        self.assertGreaterEqual(profile["talent_score"], 80)
        self.assertGreaterEqual(profile["early_senior_weighted_minutes"], 3000)
        self.assertEqual([18, 19], profile["national_team_levels"])

    def test_young_goalkeeper_price_is_only_a_confirming_talent_signal(self) -> None:
        goalkeeper = {
            **market_player(points=0),
            "position": "GOALKEEPER",
            "market_value": 800000,
        }
        points = {"GOALKEEPER": [0, 20, 60, 100]}
        prices = {"GOALKEEPER": [100000, 300000, 500000, 800000]}
        exceptional = quality.candidate_rank(
            goalkeeper,
            points,
            prices,
            exceptional_goalkeeper_history(),
            age=18,
        )
        price_only = quality.candidate_rank(
            goalkeeper,
            points,
            prices,
            {
                "mapping": {"status": "verified"},
                "career": {
                    "confirmed_score": 0,
                    "youth_score": 0,
                },
            },
            age=18,
        )
        self.assertGreater(exceptional, price_only)

    def test_talent_evidence_raises_readiness_but_never_creates_anchor(self) -> None:
        goalkeeper = {
            **market_player(points=0),
            "name": "Florian Hellstern",
            "position": "GOALKEEPER",
        }
        mapped_news = news_player()
        mapped_news["mapping"]["age"] = 18
        annotation = quality.build_annotation(
            goalkeeper,
            "news-1",
            mapped_news,
            [],
            exceptional_goalkeeper_history(),
            talent_evidence={
                "benchmark": True,
                "note": "Ausnahmetalent mit früher Herrenreife.",
                "evidence": [
                    {
                        "claim": "Offizielle Talent- und Leihbestätigung",
                        "source_url": "https://example.com/talent",
                        "checked_at": "2026-07-25",
                    }
                ],
            },
            competition="2. Bundesliga",
            points_pct=50,
            price_pct=95,
            generated_at="2026-07-25T12:00:00Z",
        )
        self.assertGreaterEqual(annotation["components"]["confirmed_performance"], 52)
        self.assertGreaterEqual(annotation["components"]["minutes"], 82)
        self.assertGreaterEqual(annotation["components"]["role"], 80)
        self.assertGreaterEqual(annotation["components"]["upside"], 90)
        self.assertGreaterEqual(annotation["components"]["value"], 70)
        self.assertEqual(0, annotation["proven_seasons"])
        self.assertFalse(annotation["reliable_anchor"])
        self.assertTrue(annotation["benchmark"])

    def test_preseason_evidence_promotes_high_upside_status_not_senior_proof(
        self,
    ) -> None:
        young_history = api_history()
        for index, season in enumerate(young_history):
            season["age"] = 18 - index
            season["appearances"] = 4
            season["minutes"] = 120
            season["lineups"] = 0
            season["goals"] = 1 if index == 0 else 0
            season["assists"] = 0
        mapped_news = news_player()
        mapped_news["mapping"]["age"] = 18
        preseason = {
            "observations": [
                {
                    "date": "2026-07-14",
                    "claim": "Scored in the first friendly.",
                    "source_url": "https://club.example/first",
                },
                {
                    "date": "2026-07-18",
                    "claim": "Started the next friendly.",
                    "source_url": "https://club.example/second",
                },
            ],
            "summary": {
                "appearances": 2,
                "starts": 1,
                "minutes": 105,
                "goals": 1,
                "assists": 0,
                "availability_score": 82,
                "role_score": 68,
                "performance_score": 64,
                "opponent_score": 70,
                "signal_score": 60,
                "effective_factor": 100,
                "confidence": "medium",
                "classification": "neutral",
            },
        }
        annotation = quality.build_annotation(
            market_player(points=20),
            "news-1",
            mapped_news,
            young_history,
            transfermarkt_history(
                proven_seasons=0,
                youth_score=95,
            ),
            preseason_player=preseason,
            competition="3. Liga",
            points_pct=15,
            price_pct=20,
            generated_at="2026-07-25T12:00:00Z",
        )

        self.assertEqual(
            "high_upside_pre_breakthrough",
            annotation["preseason_summary"]["talent_status"],
        )
        self.assertGreater(
            annotation["preseason_summary"]["readiness_delta"],
            0,
        )
        self.assertLessEqual(
            annotation["preseason_summary"]["applied_weight"],
            0.25,
        )
        self.assertEqual(0, annotation["proven_seasons"])
        self.assertFalse(annotation["reliable_anchor"])
        self.assertGreaterEqual(annotation["risks"]["unknown_role"], 18)

    def test_single_preseason_goal_cannot_create_high_upside_status(self) -> None:
        adjustment = quality.preseason_adjustment(
            {
                "summary": {
                    "appearances": 1,
                    "starts": 0,
                    "minutes": 20,
                    "goals": 1,
                    "assists": 0,
                    "availability_score": 55,
                    "role_score": 45,
                    "performance_score": 80,
                    "opponent_score": 60,
                    "signal_score": 64,
                    "effective_factor": 100,
                    "confidence": "medium",
                    "classification": "positive",
                }
            },
            age=18,
            proven_seasons=0,
            comparable_minutes=60,
            youth_score=95,
            talent_score=62,
            minutes=40,
            role=50,
            upside=95,
            value=60,
            unknown_role=42,
        )
        self.assertNotEqual(
            "high_upside_pre_breakthrough",
            adjustment["talent_status"],
        )
        self.assertLessEqual(adjustment["applied_weight"], 0.1)

    def test_role_events_reward_repeatable_actions_not_only_provider_rating(self) -> None:
        rich = quality.build_annotation(
            market_player(),
            "news-1",
            news_player(),
            richer_api_history(),
            transfermarkt_history(proven_seasons=3),
            competition="2. Bundesliga",
            points_pct=75,
            price_pct=70,
            generated_at="2026-07-24T12:00:00Z",
        )
        plain_history = api_history()
        plain_history[0]["rating"] = 8.8
        rating_only = quality.build_annotation(
            market_player(),
            "news-1",
            news_player(),
            plain_history,
            transfermarkt_history(proven_seasons=3),
            competition="2. Bundesliga",
            points_pct=75,
            price_pct=70,
            generated_at="2026-07-24T12:00:00Z",
        )
        self.assertGreater(
            rich["api_sports_role_metrics"]["latest_event_score"],
            rating_only["api_sports_role_metrics"]["latest_event_score"],
        )
        self.assertEqual(
            0.08,
            rich["api_sports_role_metrics"][
                "rating_weight_in_api_confirmation"
            ],
        )

    def test_kicker_longitudinal_form_is_bounded_and_modestly_influential(self) -> None:
        trend = {
            "observations": [
                {
                    "observed_on": "2026-08-01",
                    "market_value": 800000,
                    "points": 0,
                    "average_grade": 0,
                },
                {
                    "observed_on": "2026-08-15",
                    "market_value": 900000,
                    "points": 24,
                    "average_grade": 2.5,
                },
            ]
        }
        annotation = quality.build_annotation(
            market_player(),
            "news-1",
            news_player(),
            richer_api_history(),
            transfermarkt_history(proven_seasons=3),
            trend,
            competition="2. Bundesliga",
            points_pct=75,
            price_pct=70,
            generated_at="2026-08-15T12:00:00Z",
        )
        self.assertEqual(2, annotation["kicker_trend"]["observation_count"])
        self.assertGreater(annotation["kicker_trend"]["trend_score"], 50)
        self.assertLessEqual(
            annotation["components"]["confirmed_performance"],
            100,
        )


if __name__ == "__main__":
    unittest.main()
