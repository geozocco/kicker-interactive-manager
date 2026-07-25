from __future__ import annotations

import json
import sys
import tempfile
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

import kicker_history_snapshot
import market_snapshot
import refresh_kicker_history_snapshot


def market(*, points: float = 0, value: int = 800000) -> dict:
    payload = {
        "schema_version": market_snapshot.SCHEMA_VERSION,
        "generated_at": "2026-08-01T10:00:00Z",
        "expires_at": "2026-08-02T04:00:00Z",
        "competition": "2. Bundesliga",
        "season": "2026/27",
        "expected_team_count": 1,
        "source": {
            "provider": "kicker",
            "url": (
                "https://www.kicker-libero.de/api/sportsdata/v1/"
                "players-details/se-test.csv"
            ),
            "csv_sha256": "a" * 64,
        },
        "players": [
            {
                "id": "p1",
                "short_name": "Player",
                "name": "Example Player",
                "club": "Example Club",
                "position": "FORWARD",
                "market_value": value,
                "available": True,
                "points": points,
                "average_grade": 0.0,
            }
        ],
        "annotations": {},
    }
    payload["content_sha256"] = market_snapshot.canonical_sha256(payload)
    return market_snapshot.validate_snapshot(
        payload,
        now=datetime(2026, 8, 1, 10, tzinfo=timezone.utc),
    )


class KickerHistorySnapshotTests(unittest.TestCase):
    def test_same_day_is_replaced_and_new_day_is_appended(self) -> None:
        first = refresh_kicker_history_snapshot.build_snapshot(
            market(),
            now=datetime(2026, 8, 1, 10, tzinfo=timezone.utc),
        )
        replacement = refresh_kicker_history_snapshot.build_snapshot(
            market(points=5, value=850000),
            first,
            now=datetime(2026, 8, 1, 20, tzinfo=timezone.utc),
        )
        self.assertEqual(
            1,
            len(replacement["players"]["p1"]["observations"]),
        )
        second = refresh_kicker_history_snapshot.build_snapshot(
            market(points=14, value=900000),
            replacement,
            now=datetime(2026, 8, 8, 10, tzinfo=timezone.utc),
        )
        observations = second["players"]["p1"]["observations"]
        self.assertEqual(2, len(observations))
        self.assertEqual(5, observations[0]["points"])
        self.assertEqual(14, observations[1]["points"])

    def test_round_trip_and_hash_tampering(self) -> None:
        payload = refresh_kicker_history_snapshot.build_snapshot(
            market(),
            now=datetime(2026, 8, 1, 10, tzinfo=timezone.utc),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded = kicker_history_snapshot.load_snapshot(path)
        self.assertEqual("2. Bundesliga", loaded["competition"])
        payload["players"]["p1"]["observations"][0]["points"] = 99
        with self.assertRaisesRegex(
            kicker_history_snapshot.KickerHistorySnapshotError,
            "content_sha256",
        ):
            kicker_history_snapshot.validate_snapshot(payload)


if __name__ == "__main__":
    unittest.main()
