from __future__ import annotations

import importlib.util
import json
import subprocess
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

import market_snapshot


SPEC = importlib.util.spec_from_file_location(
    "refresh_market_snapshot",
    SCRIPT_DIRECTORY / "refresh_market_snapshot.py",
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load refresh_market_snapshot.py")
refresh = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(refresh)


CSV_BYTES = (
    "\ufeffID;Vorname;Nachname;Angezeigter Name (kurz);"
    "Angezeigter Name;Verein;Position;Marktwert;Punkte;"
    "Notendurchschnitt\n"
    "p1;Ada;Eins;A. Eins;Ada Eins;Club A;MIDFIELDER;"
    "100000;123;2.75\n"
    "p2;Bea;Zwei;B. Zwei;Bea Zwei;Club B;FORWARD;"
    "200000;45;3.25\n"
).encode("utf-8")


def config() -> dict:
    return {
        "competition": "2. Bundesliga",
        "season": "2026/27",
        "source_url": (
            "https://www.kicker-libero.de/api/sportsdata/v1/"
            "players-details/se-test.csv"
        ),
        "expected_team_count": 2,
        "minimum_player_count": 2,
        "maximum_player_count": 3,
    }


class MarketSnapshotTests(unittest.TestCase):
    def test_build_load_and_rows_preserve_official_market_fields(self) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        payload = refresh.build_snapshot(
            config(),
            CSV_BYTES,
            annotations={
                "p1": {
                    "components": {"role": 80},
                    "note": "Central factual review",
                }
            },
            ttl_hours=18,
            now=now,
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "market.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded = market_snapshot.load_snapshot(
                path,
                now=now + timedelta(hours=1),
            )

        rows = market_snapshot.csv_rows(loaded)
        self.assertEqual(2, len(rows))
        self.assertEqual("Ada Eins", rows[0]["Angezeigter Name"])
        self.assertEqual("100000", rows[0]["Marktwert"])
        self.assertEqual({"p1"}, set(loaded["annotations"]))
        self.assertEqual(2, market_snapshot.snapshot_audit(loaded)["club_count"])

    def test_expired_market_snapshot_fails_closed(self) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        payload = refresh.build_snapshot(
            config(),
            CSV_BYTES,
            ttl_hours=1,
            now=now,
        )
        with self.assertRaisesRegex(
            market_snapshot.MarketSnapshotError,
            "expired",
        ):
            market_snapshot.validate_snapshot(
                payload,
                now=now + timedelta(hours=2),
            )

    def test_tampered_market_snapshot_is_rejected(self) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        payload = refresh.build_snapshot(
            config(),
            CSV_BYTES,
            now=now,
        )
        payload["players"][0]["market_value"] += 1
        with self.assertRaisesRegex(
            market_snapshot.MarketSnapshotError,
            "content_sha256",
        ):
            market_snapshot.validate_snapshot(payload, now=now)

    def test_generator_rejects_non_kicker_source(self) -> None:
        with self.assertRaisesRegex(ValueError, "official Kicker"):
            refresh.fetch_official_csv(
                "https://example.org/players-details/test.csv"
            )

    def test_annotations_must_reference_current_market(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "outside the current market",
        ):
            refresh.build_snapshot(
                config(),
                CSV_BYTES,
                annotations={"missing": {"note": "stale"}},
            )

    def test_optimizer_shortlist_reads_market_snapshot_without_csv(self) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        payload = refresh.build_snapshot(
            config(),
            CSV_BYTES,
            now=now,
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "market.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIRECTORY / "optimize_squad.py"),
                    "--market-snapshot",
                    str(path),
                    "--budget",
                    "1000000",
                    "--shortlist-only",
                    "--format",
                    "json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(0, result.returncode, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual("fresh", output["market_audit"]["status"])
        self.assertEqual(2, output["market_audit"]["player_count"])

    def test_unavailable_kicker_sentinel_is_not_an_optimizable_player(self) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        source = CSV_BYTES.replace(
            b"200000;45;3.25",
            b"999000000;45;3.25",
        )
        value = refresh.build_snapshot(
            config(),
            source,
            now=now,
        )
        rows = market_snapshot.csv_rows(value)
        self.assertEqual(["p1"], [row["ID"] for row in rows])
        self.assertEqual(
            1,
            market_snapshot.snapshot_audit(value)["available_player_count"],
        )


if __name__ == "__main__":
    unittest.main()
