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

import advanced_signals


def annotation(
    *,
    position: str,
    club: str = "Club A",
    start_probability: float = 70,
    age: int = 24,
) -> dict:
    return {
        "position": position,
        "club": club,
        "provider_news_id": f"news-{position}-{start_probability}",
        "components": {
            "confirmed_performance": 70.0,
            "minutes": 72.0,
            "role": 68.0,
            "stability": 70.0,
            "context": 65.0,
            "fitness": 80.0,
            "upside": 60.0,
            "value": 65.0,
        },
        "risks": {
            "transfer": 5.0,
            "injury": 5.0,
            "rotation": 10.0,
            "outlier": 10.0,
            "unknown_role": 10.0,
        },
        "api_sports_history": [
            {
                "minutes": 1800,
                "yellow_cards": 8,
                "red_cards": 1,
                "appearances": 24,
                "lineups": 18,
                "positions": [position],
            }
        ],
        "scorer_profile": {
            "contributions_per_90": 0.42,
            "responsibilities": {"playmaker": "shared"},
        },
        "role_context": {
            "expected_start_probability": start_probability,
            "role_environment": {
                "coach_trust": "high",
                "tactical_fit": "good",
            },
        },
        "history_summary": {"talent_profile": {"age": age}},
        "reliable_anchor": True,
    }


class AdvancedSignalsTests(unittest.TestCase):
    def test_all_signal_families_are_attached_and_bounded(self) -> None:
        annotations = {
            "m1": annotation(
                position="MIDFIELDER",
                start_probability=82,
                age=21,
            ),
            "m2": annotation(
                position="MIDFIELDER",
                start_probability=78,
            ),
            "f1": annotation(position="FORWARD"),
            "d1": annotation(position="DEFENDER"),
            "g1": annotation(position="GOALKEEPER"),
        }
        preseason = {
            "players": {
                "news-MIDFIELDER-82": {
                    "observations": [
                        {
                            "date": "2026-07-01",
                            "appeared": True,
                            "started": False,
                            "position": "M",
                        },
                        {
                            "date": "2026-07-20",
                            "appeared": True,
                            "started": True,
                            "position": "F",
                        },
                    ]
                }
            }
        }

        advanced_signals.apply_advanced_signals(
            annotations,
            preseason,
            {
                "team_profiles": {
                    "Club A": {
                        "coach_name": "Coach A",
                        "preferred_systems": ["4-2-3-1"],
                        "youth_usage": "high",
                        "rotation_tendency": "low",
                        "system_stability": "high",
                        "attacking_outlook": "high",
                        "defensive_outlook": "medium",
                    }
                }
            },
        )

        signals = annotations["m1"]["advanced_signals"]
        self.assertEqual("advanced-context-v1", signals["model_version"])
        self.assertEqual(
            ["FORWARD", "MIDFIELDER"],
            signals["positional_flexibility"]["positions_observed"],
        )
        self.assertEqual("rising", signals["usage_trajectory"]["status"])
        self.assertEqual(
            1,
            signals["competition_graph"]["direct_competitor_count"],
        )
        self.assertEqual(
            "high",
            signals["coach_usage"]["youth_usage_signal"],
        )
        self.assertEqual("Coach A", signals["coach_usage"]["coach_name"])
        self.assertEqual(
            "high",
            signals["coach_usage"]["historical_youth_usage"],
        )
        self.assertEqual(62.0, annotations["m1"]["components"]["upside"])
        self.assertGreater(
            signals["discipline"]["suspension_risk"],
            50,
        )
        self.assertEqual(8, signals["discipline"]["current_yellow_cards"])
        self.assertFalse(
            signals["discipline"]["one_card_from_suspension"]
        )
        for value in signals["team_projection"].values():
            self.assertGreaterEqual(value, 0)
            self.assertLessEqual(value, 100)


if __name__ == "__main__":
    unittest.main()
