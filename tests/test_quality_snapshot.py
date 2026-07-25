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

import quality_snapshot


def annotation(position: str, *, anchor: bool = False) -> dict:
    return {
        "position": position,
        "club": "Club A",
        "components": {
            key: 75.0 for key in quality_snapshot.COMPONENTS
        },
        "risks": {
            key: 10.0 for key in quality_snapshot.RISKS
        },
        "proven_seasons": 2 if anchor else 1,
        "reliable_anchor": anchor,
        "anchor_reason": "Two proven seasons" if anchor else "",
        "benchmark": False,
        "history_summary": {
            "mapping_status": "verified",
            "confidence": "high",
            "transfermarkt_player_id": 123,
            "profile_url": (
                "https://www.transfermarkt.co.uk/example/profil/spieler/123"
            ),
            "proven_seasons": 2,
            "comparable_minutes": 3000.0,
            "level_adjusted_minutes": 3200.0,
            "youth_adjusted_minutes": 900.0,
            "youth_adjusted_contributions": 8.0,
            "youth_score": 26.0,
        },
        "api_sports_role_metrics": {
            "latest_event_score": 72.0,
            "multi_season_event_score": 70.0,
            "provider_rating_score": 68.0,
            "rating_weight_in_api_confirmation": 0.08,
        },
        "kicker_trend": {
            "observation_count": 2,
            "trend_score": 55.0,
        },
        "evidence": [
            {
                "claim": "Current role",
                "source_url": "https://example.com/player",
                "checked_at": "2026-07-24",
            }
        ],
    }


def payload(now: datetime) -> dict:
    value = {
        "schema_version": quality_snapshot.SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=18)).isoformat(),
        "competition": "2. Bundesliga",
        "season": "2026/27",
        "market_sha256": "market",
        "news_sha256": "news",
        "history_sha256": "history",
        "kicker_history_sha256": "kicker-history",
        "model_version": "test-v1",
        "requirements": {
            "candidate_count": 3,
            "anchor_count": 2,
            "attacking_anchor_count": 1,
            "goalkeeper_block_count": 0,
            "history_resolved_percent": 100,
        },
        "annotations": {
            "d1": annotation("DEFENDER", anchor=True),
            "m1": annotation("MIDFIELDER", anchor=True),
            "f1": annotation("FORWARD"),
        },
    }
    value["content_sha256"] = quality_snapshot.canonical_sha256(value)
    return value


class QualitySnapshotTests(unittest.TestCase):
    def test_goalkeeper_requirement_counts_only_stable_hierarchy_blocks(
        self,
    ) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        value = payload(now)
        for rank in range(1, 4):
            goalkeeper = annotation("GOALKEEPER")
            goalkeeper["goalkeeper_outlook"] = {
                "status": "clear_favourite" if rank == 1 else "backup",
                "starter_probability": 86 if rank == 1 else 7,
                "current_hierarchy_probability": 91 if rank == 1 else 10,
                "confidence": "high",
                "club_rank": rank,
                "hierarchy_score": 90 - rank * 10,
                "hierarchy_gap": 15 if rank == 1 else rank * 15,
                "club_price_share": 80 if rank == 1 else 10,
                "global_price_percentile": 90 if rank == 1 else 15,
                "external_signing_risk": 12,
                "market_goalkeeper_count": 3,
                "provider_goalkeeper_count": 3,
                "unpriced_provider_goalkeeper_count": 0,
                "incoming_unpriced_goalkeeper_count": 0,
                "basis": ["club hierarchy"],
            }
            value["annotations"][f"g{rank}"] = goalkeeper
        value["requirements"]["candidate_count"] = 6
        value["requirements"]["goalkeeper_block_count"] = 1
        value["content_sha256"] = quality_snapshot.canonical_sha256(value)

        quality_snapshot.validate_snapshot(value, now=now)

        for rank in range(1, 4):
            value["annotations"][f"g{rank}"]["goalkeeper_outlook"][
                "external_signing_risk"
            ] = 60
        value["content_sha256"] = quality_snapshot.canonical_sha256(value)
        with self.assertRaisesRegex(
            quality_snapshot.QualitySnapshotError,
            "goalkeeper_block_count",
        ):
            quality_snapshot.validate_snapshot(value, now=now)

    def test_loads_complete_fresh_pool_and_reports_audit(self) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        value = payload(now)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quality.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            loaded = quality_snapshot.load_snapshot(path, now=now)
        audit = quality_snapshot.snapshot_audit(loaded)
        self.assertEqual(3, audit["candidate_count"])
        self.assertEqual(2, audit["anchor_count"])
        self.assertEqual(1, audit["attacking_anchor_count"])

    def test_fails_when_anchor_floor_is_not_met(self) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        value = payload(now)
        value["annotations"]["d1"]["reliable_anchor"] = False
        value["content_sha256"] = quality_snapshot.canonical_sha256(value)
        with self.assertRaisesRegex(
            quality_snapshot.QualitySnapshotError,
            "anchor_count",
        ):
            quality_snapshot.validate_snapshot(value, now=now)

    def test_tampering_and_expiry_fail_closed(self) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        value = payload(now)
        value["annotations"]["m1"]["components"]["role"] = 1
        with self.assertRaisesRegex(
            quality_snapshot.QualitySnapshotError,
            "content_sha256",
        ):
            quality_snapshot.validate_snapshot(value, now=now)
        with self.assertRaisesRegex(
            quality_snapshot.QualitySnapshotError,
            "expired",
        ):
            quality_snapshot.validate_snapshot(
                payload(now),
                now=now + timedelta(days=1),
            )


if __name__ == "__main__":
    unittest.main()
