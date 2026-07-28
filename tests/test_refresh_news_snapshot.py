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

    def test_daily_limit_fallback_keeps_provider_age_and_refreshes_roles(
        self,
    ) -> None:
        previous = {
            "generated_at": "2026-07-28T12:00:00Z",
            "expires_at": "2026-07-29T06:00:00Z",
            "players": {"old-player": {"signals": []}},
            "role_profiles": {"old-player": {"designation": "rotation"}},
            "role_research_abstentions": {},
            "role_research": {"targets": 48},
            "content_sha256": "old-checksum",
        }
        roles = {"new-player": {"designation": "key_starter"}}
        abstentions = {"empty-player": {"status": "no_grounded_signal"}}
        audit = {"targets": 96, "target_clubs": 18}

        merged = refresh.merge_role_research_into_previous_snapshot(
            previous,
            role_profiles=roles,
            role_research_abstentions=abstentions,
            role_research_audit=audit,
        )

        self.assertEqual(previous["generated_at"], merged["generated_at"])
        self.assertEqual(previous["expires_at"], merged["expires_at"])
        self.assertEqual(previous["players"], merged["players"])
        self.assertEqual(roles, merged["role_profiles"])
        self.assertEqual(
            abstentions,
            merged["role_research_abstentions"],
        )
        self.assertEqual(audit, merged["role_research"])
        self.assertEqual(
            refresh.canonical_sha256(merged),
            merged["content_sha256"],
        )
        self.assertEqual("old-checksum", previous["content_sha256"])

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
