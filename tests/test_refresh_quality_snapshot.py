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
