from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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

import preseason_snapshot


def payload(now: datetime) -> dict:
    value = {
        "schema_version": preseason_snapshot.SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=18)).isoformat(),
        "competition": "3. Liga",
        "season": "2026/27",
        "window": {
            "from": "2026-06-15",
            "to": "2026-08-31",
            "season_start": "2026-08-07",
            "decay_days": 28,
            "post_start_decay_days": 35,
        },
        "providers": {"api_sports": {"status": "ok"}},
        "players": {
            "api_sports:1": {
                "name": "Prospect",
                "club": "Club",
                "mapping_confidence": "verified",
                "observations": [
                    {
                        "event_key": "manual:1",
                        "date": "2026-07-18",
                        "opponent": "Opponent",
                        "confidence": "high",
                        "source_url": "https://club.example/match",
                    }
                ],
                "summary": {
                    "team_match_count": 2,
                    "appearances": 2,
                    "starts": 1,
                    "minutes": 105,
                    "goals": 1,
                    "assists": 0,
                    "official_source_count": 1,
                    "availability_score": 80.0,
                    "role_score": 68.0,
                    "performance_score": 62.0,
                    "opponent_score": 70.0,
                    "signal_score": 71.0,
                    "effective_factor": 100.0,
                    "confidence": "medium",
                    "classification": "positive",
                },
            }
        },
    }
    value["content_sha256"] = preseason_snapshot.canonical_sha256(value)
    return value


class PreseasonSnapshotTests(unittest.TestCase):
    def test_loads_fresh_snapshot_and_rejects_tampering(self) -> None:
        now = datetime(2026, 7, 25, 12, tzinfo=timezone.utc)
        value = payload(now)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preseason.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            loaded = preseason_snapshot.load_snapshot(path, now=now)
        self.assertEqual(2, loaded["players"]["api_sports:1"]["summary"]["appearances"])

        value["players"]["api_sports:1"]["summary"]["signal_score"] = 99
        with self.assertRaisesRegex(
            preseason_snapshot.PreseasonSnapshotError,
            "content_sha256",
        ):
            preseason_snapshot.validate_snapshot(value, now=now)

    def test_expired_snapshot_fails_closed(self) -> None:
        now = datetime(2026, 7, 25, 12, tzinfo=timezone.utc)
        with self.assertRaisesRegex(
            preseason_snapshot.PreseasonSnapshotError,
            "expired",
        ):
            preseason_snapshot.validate_snapshot(
                payload(now),
                now=now + timedelta(days=1),
            )


if __name__ == "__main__":
    unittest.main()
