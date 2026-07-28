from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import call, patch


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

import refresh_news_snapshot as refresh


class RefreshNewsSnapshotTests(unittest.TestCase):
    def test_role_news_is_cached_with_source_age_not_refresh_age(self) -> None:
        profiles = refresh.cached_role_profiles(
            {
                "role_evidence": {
                    "player-1": {
                        "continuity": "confirmed",
                        "confidence": "high",
                        "expected_start_probability": 92,
                        "responsibilities": {
                            "offensive_focal_point": "primary",
                        },
                        "evidence": [
                            {
                                "claim": "Trainer names him as a key starter.",
                                "source_url": "https://club.example/news",
                                "checked_at": "2026-07-27",
                                "source_authority": "head_coach",
                            }
                        ],
                    }
                }
            },
            generated_at="2026-07-28T12:00:00Z",
        )

        self.assertEqual("key_starter", profiles["player-1"]["designation"])
        self.assertTrue(profiles["player-1"]["fresh"])
        self.assertEqual(
            "head_coach",
            profiles["player-1"]["evidence"][0]["source_authority"],
        )

    def test_old_role_quote_stays_expired_after_new_refresh(self) -> None:
        profiles = refresh.cached_role_profiles(
            {
                "role_evidence": {
                    "player-1": {
                        "continuity": "confirmed",
                        "confidence": "high",
                        "expected_start_probability": 95,
                        "evidence": [
                            {
                                "claim": "Old starter statement.",
                                "source_url": "https://club.example/old",
                                "checked_at": "2026-05-01",
                            }
                        ],
                    }
                }
            },
            generated_at="2026-07-28T12:00:00Z",
        )

        self.assertFalse(profiles["player-1"]["fresh"])

    def test_goalkeeper_number_one_statement_becomes_confirmed_starter(
        self,
    ) -> None:
        profiles = refresh.cached_role_profiles(
            {
                "goalkeeper_evidence": {
                    "players": {
                        "keeper-1": {
                            "status": "confirmed_starter",
                            "starter_probability": 97,
                            "confidence": "high",
                            "evidence": [
                                {
                                    "claim": "Coach publicly names the number one.",
                                    "source_url": "https://club.example/keeper",
                                    "checked_at": "2026-07-28",
                                }
                            ],
                        }
                    }
                }
            },
            generated_at="2026-07-28T12:00:00Z",
        )

        self.assertEqual(
            "confirmed_starter",
            profiles["keeper-1"]["designation"],
        )
        self.assertEqual(
            97,
            profiles["keeper-1"]["expected_start_probability"],
        )

    def test_rate_limit_detection_covers_payload_and_http_forms(self) -> None:
        self.assertTrue(
            refresh.is_api_sports_rate_limit(
                "rateLimit: Too many requests."
            )
        )
        self.assertTrue(
            refresh.is_api_sports_rate_limit(
                "provider request failed: HTTP Error 429"
            )
        )
        self.assertFalse(
            refresh.is_api_sports_rate_limit(
                "season: The Season field is required."
            )
        )
        self.assertTrue(
            refresh.is_api_sports_daily_limit(
                "You have reached the request limit for the day"
            )
        )
        self.assertFalse(
            refresh.is_api_sports_daily_limit(
                "Too many requests per minute"
            )
        )

    @patch.object(refresh.time, "sleep")
    @patch.object(refresh, "request_json")
    def test_api_sports_rate_limit_payload_is_retried(
        self,
        request_json,
        sleep,
    ) -> None:
        request_json.side_effect = [
            {
                "errors": {
                    "rateLimit": (
                        "Too many requests. You have exceeded the limit "
                        "of requests per minute of your subscription."
                    )
                }
            },
            {
                "errors": [],
                "response": [{"id": 1}],
                "paging": {"current": 1, "total": 1},
            },
        ]

        pages = list(
            refresh.api_sports_pages(
                "https://example.test",
                query={"team": 1},
                headers={"x-apisports-key": "test"},
                rate_limit_delay=2,
            )
        )

        self.assertEqual([{"id": 1}], pages[0]["response"])
        self.assertEqual(2, request_json.call_count)
        sleep.assert_called_once_with(2)

    @patch.object(refresh.time, "sleep")
    @patch.object(refresh, "request_json")
    def test_api_sports_non_rate_limit_error_is_not_retried(
        self,
        request_json,
        sleep,
    ) -> None:
        request_json.return_value = {
            "errors": {"season": "The Season field is required."}
        }

        with self.assertRaisesRegex(RuntimeError, "Season field"):
            list(
                refresh.api_sports_pages(
                    "https://example.test",
                    query={"team": 1},
                    headers={"x-apisports-key": "test"},
                )
            )

        self.assertEqual(1, request_json.call_count)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
