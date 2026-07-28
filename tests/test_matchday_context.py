from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
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

import analyze_matchday
import matchday_snapshot
import refresh_matchday_snapshot


def snapshot() -> dict:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    payload = {
        "schema_version": 1,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": (
            now + timedelta(hours=12)
        ).isoformat().replace("+00:00", "Z"),
        "competition": "2. Bundesliga",
        "season": "2026/27",
        "quality_sha256": "quality",
        "status": "ok",
        "provider_error": "",
        "fixtures": [],
        "teams": {
            "Club A": {
                "opponent": "Club B",
                "venue": "home",
                "date": "2026-08-01T13:00:00Z",
                "round": "Regular Season - 1",
                "fixture_difficulty": 70,
                "opponent_attack": 80,
                "opponent_defense": 75,
            }
        },
    }
    payload["content_sha256"] = matchday_snapshot.canonical_sha256(payload)
    return payload


class MatchdayContextTests(unittest.TestCase):
    def test_provider_club_name_resolves_to_canonical_kicker_name(self) -> None:
        clubs = {"1. FC Nürnberg", "SV Wehen Wiesbaden", "VfL Bochum"}
        self.assertEqual(
            "1. FC Nürnberg",
            refresh_matchday_snapshot.resolve_quality_club(
                "FC Nurnberg",
                clubs,
            ),
        )
        self.assertEqual(
            "SV Wehen Wiesbaden",
            refresh_matchday_snapshot.resolve_quality_club(
                "Wehen Wiesbaden",
                clubs,
            ),
        )
        self.assertIsNone(
            refresh_matchday_snapshot.resolve_quality_club(
                "Unknown United",
                clubs,
            )
        )

    @patch.object(refresh_matchday_snapshot, "api_sports_pages")
    def test_fixture_feed_uses_canonical_kicker_club_names(
        self,
        api_sports_pages,
    ) -> None:
        api_sports_pages.return_value = [
            {
                "response": [
                    {
                        "fixture": {
                            "id": 1,
                            "date": "2026-08-01T13:00:00Z",
                        },
                        "league": {"round": "Regular Season - 1"},
                        "teams": {
                            "home": {"name": "FC Nurnberg"},
                            "away": {"name": "Wehen Wiesbaden"},
                        },
                    }
                ]
            }
        ]
        quality = {
            "competition": "2. Bundesliga",
            "season": "2026/27",
            "content_sha256": "quality",
            "annotations": {
                "p1": {
                    "club": "1. FC Nürnberg",
                    "advanced_signals": {
                        "team_projection": {
                            "attack_strength": 60,
                            "defense_strength": 55,
                            "chance_creation": 62,
                            "clean_sheet_outlook": 55,
                        }
                    },
                },
                "p2": {
                    "club": "SV Wehen Wiesbaden",
                    "advanced_signals": {
                        "team_projection": {
                            "attack_strength": 50,
                            "defense_strength": 48,
                            "chance_creation": 51,
                            "clean_sheet_outlook": 48,
                        }
                    },
                },
            },
        }
        payload = refresh_matchday_snapshot.build_snapshot(
            {"api_sports": {"league_id": 1, "season": 2026}},
            quality,
            token="secret",
        )

        self.assertIn("1. FC Nürnberg", payload["teams"])
        self.assertIn("SV Wehen Wiesbaden", payload["teams"])
        self.assertEqual(
            "SV Wehen Wiesbaden",
            payload["teams"]["1. FC Nürnberg"]["opponent"],
        )

    def test_opponent_context_is_separate_and_position_specific(self) -> None:
        payload = matchday_snapshot.validate_snapshot(snapshot())
        result = analyze_matchday.analyze(
            [
                {
                    "name": "Defender",
                    "club": "Club A",
                    "position": "DEFENDER",
                },
                {
                    "name": "Forward",
                    "club": "Club A",
                    "position": "FORWARD",
                },
            ],
            payload,
        )

        self.assertLess(result["players"][0]["matchday_adjustment"], 0)
        self.assertLess(result["players"][1]["matchday_adjustment"], 0)
        self.assertEqual("Club B", result["players"][0]["opponent_context"]["opponent"])


if __name__ == "__main__":
    unittest.main()
