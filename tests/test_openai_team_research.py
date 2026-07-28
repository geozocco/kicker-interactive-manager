from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
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

import openai_team_research as team


NOW = datetime(2026, 7, 28, 12, tzinfo=timezone.utc)
URL = "https://club.example/coach-plan"


def response() -> dict:
    profile = {
        "club": "Club A",
        "has_signal": True,
        "coach_name": "Trainer A",
        "preferred_systems": ["4-2-3-1"],
        "youth_usage": "high",
        "rotation_tendency": "medium",
        "system_stability": "high",
        "attacking_outlook": "high",
        "defensive_outlook": "medium",
        "note": "Aktueller Plan.",
        "evidence": [
            {
                "claim": "The coach explained the current plan.",
                "source_url": URL,
                "observed_at": "2026-07-27",
            }
        ],
    }
    return {
        "output": [
            {
                "type": "web_search_call",
                "action": {
                    "sources": [{"type": "url", "url": URL}],
                },
            },
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps({"profiles": [profile]}),
                    }
                ],
            },
        ]
    }


class TeamResearchTests(unittest.TestCase):
    def test_grounded_team_profile_is_cached_per_club(self) -> None:
        calls = []

        def requester(payload, *, api_key):
            calls.append(payload)
            return response()

        profiles, audit = team.research_team_profiles(
            ["Club A"],
            competition="2. Bundesliga",
            season="2026/27",
            previous_profiles={},
            api_key="secret",
            now=NOW,
            requester=requester,
        )

        self.assertEqual("Trainer A", profiles["Club A"]["coach_name"])
        self.assertEqual("high", profiles["Club A"]["youth_usage"])
        self.assertEqual(1, audit["requests"])
        self.assertEqual(1, len(calls))

        reused, audit = team.research_team_profiles(
            ["Club A"],
            competition="2. Bundesliga",
            season="2026/27",
            previous_profiles=profiles,
            api_key="secret",
            now=NOW,
            requester=lambda *args, **kwargs: self.fail("cache missed"),
        )
        self.assertIn("Club A", reused)
        self.assertEqual(1, audit["cache_hits"])


if __name__ == "__main__":
    unittest.main()
