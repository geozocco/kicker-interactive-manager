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
