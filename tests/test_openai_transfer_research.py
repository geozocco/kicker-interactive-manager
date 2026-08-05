from __future__ import annotations

import json
import sys
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

import openai_transfer_research as transfer


NOW = datetime(2026, 7, 29, 10, tzinfo=timezone.utc)


def target() -> dict:
    return {
        "player_id": "p1",
        "name": "Luca Beispiel",
        "club": "Energie Cottbus",
        "position": "DEFENDER",
        "market_value": 400_000,
    }


def raw_report(
    *,
    stage: str = "official",
    authority: str = "official_destination_club",
    source_url: str = "https://www.fcenergie.de/news/leihe",
) -> dict:
    return {
        "player_id": "p1",
        "has_transfer_signal": True,
        "stage": stage,
        "from_club": "Bayer 04 Leverkusen",
        "to_club": "Energie Cottbus",
        "deal_type": "loan",
        "loan_intent": "development_minutes",
        "parent_club_level": "top_five_first_division",
        "probability": 100,
        "contradiction": False,
        "note": "Saisonleihe.",
        "evidence": [
            {
                "claim": "Der Spieler wird für eine Saison ausgeliehen.",
                "source_url": source_url,
                "observed_at": "2026-07-28",
                "source_authority": authority,
            }
        ],
    }


def response_for(reports: list[dict]) -> dict:
    urls = [
        evidence["source_url"]
        for report in reports
        for evidence in report.get("evidence", [])
    ]
    return {
        "output": [
            {
                "type": "web_search_call",
                "action": {
                    "sources": [{"type": "url", "url": url} for url in urls]
                },
            },
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps({"reports": reports}),
                    }
                ],
            },
        ]
    }


class TransferNormalizationTests(unittest.TestCase):
    def test_date_only_evidence_never_refreshes_before_observation(self) -> None:
        current = datetime(2026, 8, 5, 5, 20, tzinfo=timezone.utc)
        report_data = raw_report(stage="agreement", authority="transfermarkt")
        report_data["evidence"][0]["observed_at"] = "2026-08-05"
        report = transfer.normalize_report(
            report_data,
            target=target(),
            competition_clubs={"Energie Cottbus"},
            grounded_urls={"https://www.fcenergie.de/news/leihe"},
            now=current,
            model="gpt-5.6-luna",
        )
        assert report is not None
        self.assertGreaterEqual(
            transfer.parsed_timestamp(report["refresh_after"]),
            transfer.parsed_timestamp(report["observed_at"]),
        )

    def test_club_matching_does_not_confuse_two_eintracht_clubs(self) -> None:
        self.assertFalse(
            transfer._same_club(
                "Eintracht Frankfurt",
                "Eintracht Braunschweig",
            )
        )
        self.assertTrue(
            transfer._same_club(
                "FC Energie Cottbus",
                "Energie Cottbus",
            )
        )

    def test_official_inbound_loan_is_grounded_and_confirmed(self) -> None:
        report = transfer.normalize_report(
            raw_report(),
            target=target(),
            competition_clubs={"Energie Cottbus", "VfL Bochum"},
            grounded_urls={"https://www.fcenergie.de/news/leihe"},
            now=NOW,
            model="gpt-5.6-luna",
        )
        assert report is not None
        self.assertEqual("confirmed", report["status"])
        self.assertEqual("in", report["direction"])
        self.assertEqual("loan", report["deal_type"])
        self.assertEqual(
            "top_five_first_division",
            report["parent_club_level"],
        )

    def test_editorial_transfer_fix_is_advanced_not_confirmed(self) -> None:
        report = transfer.normalize_report(
            raw_report(
                authority="transfermarkt",
                source_url="https://www.transfermarkt.de/news/transfer-fix",
            ),
            target=target(),
            competition_clubs={"Energie Cottbus"},
            grounded_urls={
                "https://www.transfermarkt.de/news/transfer-fix"
            },
            now=NOW,
            model="gpt-5.6-luna",
        )
        assert report is not None
        self.assertEqual("advanced", report["status"])
        self.assertEqual("agreement", report["stage"])

    def test_ungrounded_transfer_report_is_rejected(self) -> None:
        report = transfer.normalize_report(
            raw_report(),
            target=target(),
            competition_clubs={"Energie Cottbus"},
            grounded_urls={"https://example.com/other"},
            now=NOW,
            model="gpt-5.6-luna",
        )
        self.assertIsNone(report)

    def test_historical_move_not_involving_current_club_is_rejected(
        self,
    ) -> None:
        historical = raw_report()
        historical["from_club"] = "TSG Hoffenheim"
        historical["to_club"] = "Bayer 04 Leverkusen"
        historical["deal_type"] = "permanent"
        report = transfer.normalize_report(
            historical,
            target=target(),
            competition_clubs={"Energie Cottbus"},
            grounded_urls={"https://www.fcenergie.de/news/leihe"},
            now=NOW,
            model="gpt-5.6-luna",
        )
        self.assertIsNone(report)

    def test_official_transfer_centre_parses_chained_inbound_loan(
        self,
    ) -> None:
        market = {
            "players": [
                {
                    "id": "p1",
                    "name": "Luca Beispiel",
                    "club": "FC Energie Cottbus",
                    "position": "DEFENDER",
                    "market_value": 400_000,
                    "available": True,
                }
            ]
        }
        reports = transfer.parse_bundesliga_transfer_centre(
            (
                "Intro\\nEnergie Cottbus\\n"
                "In: Luca Beispiel (Bayer Leverkusen, loan), "
                "Anderer Spieler (Verein)\\n"
                "Out: Abgang (Zielverein)\\n"
                "Greuther Fürth\\nIn: Neuzugang (Verein)\\n"
                "Out: Abgang Zwei (Zielverein)"
            ),
            market=market,
            source_url="https://www.bundesliga.com/transfer-centre",
            now=NOW,
            model="gpt-5.6-luna",
        )
        report = reports["p1"]
        self.assertEqual("confirmed", report["status"])
        self.assertEqual("in", report["direction"])
        self.assertEqual("loan", report["deal_type"])
        self.assertEqual("Bayer Leverkusen", report["from_club"])
        self.assertEqual("FC Energie Cottbus", report["to_club"])

    def test_official_register_does_not_read_embedded_duplicate_as_outbound(
        self,
    ) -> None:
        market = {
            "players": [
                {
                    "id": "p1",
                    "name": "Robert Beispiel",
                    "club": "VfL Wolfsburg",
                    "position": "FORWARD",
                    "market_value": 900_000,
                    "available": True,
                }
            ]
        }
        reports = transfer.parse_bundesliga_transfer_centre(
            (
                "Wolfsburg\n"
                "In: Robert Beispiel (Hamburg), Zugang Zwei (Berlin)\n"
                "Out: Abgang Eins (London)\n"
                "<html>embedded article copy Robert Beispiel (Hamburg)</html>\n"
                "Wolfsburg\n"
                "In: Zugang Drei (Mainz)\n"
                "Out: Abgang Zwei (Paris)"
            ),
            market=market,
            source_url="https://www.bundesliga.com/transfer-centre",
            now=NOW,
            model="gpt-5.6-luna",
        )

        report = reports["p1"]
        self.assertEqual("in", report["direction"])
        self.assertEqual("Hamburg", report["from_club"])
        self.assertEqual("VfL Wolfsburg", report["to_club"])


class TransferResearchTests(unittest.TestCase):
    def test_routine_no_signal_is_cached_for_three_days(self) -> None:
        no_signal = raw_report()
        no_signal["has_transfer_signal"] = False
        no_signal["evidence"] = []
        calls = []

        def requester(payload, *, api_key):
            calls.append(payload)
            return response_for([no_signal])

        reports, abstentions, audit = transfer.research_transfer_reports(
            [target()],
            competition="2. Bundesliga",
            season="2026/27",
            competition_clubs={"Energie Cottbus"},
            previous_reports={},
            previous_abstentions={},
            api_key="secret",
            now=NOW,
            requester=requester,
        )
        self.assertEqual({}, reports)
        self.assertEqual(
            "no_grounded_transfer_signal",
            abstentions["p1"]["status"],
        )
        self.assertEqual(
            "2026-08-01T10:00:00Z",
            abstentions["p1"]["refresh_after"],
        )
        self.assertEqual(1, audit["requests"])

        _, _, cached_audit = transfer.research_transfer_reports(
            [target()],
            competition="2. Bundesliga",
            season="2026/27",
            competition_clubs={"Energie Cottbus"},
            previous_reports={},
            previous_abstentions=abstentions,
            api_key="secret",
            now=NOW + timedelta(hours=1),
            requester=lambda *_args, **_kwargs: self.fail(
                "cached target was researched again"
            ),
        )
        self.assertEqual(1, cached_audit["cache_hits"])

    def test_old_prompt_cache_is_researched_again(self) -> None:
        cached = {
            "p1": {
                "status": "no_grounded_transfer_signal",
                "model_version": transfer.MODEL_VERSION,
                "prompt_version": "older-prompt",
                "research_model": "gpt-5.6-luna",
                "refresh_after": "2026-07-30T10:00:00Z",
                "expires_at": "2026-08-05T10:00:00Z",
            }
        }
        no_signal = raw_report()
        no_signal["has_transfer_signal"] = False
        no_signal["evidence"] = []
        _, _, audit = transfer.research_transfer_reports(
            [target()],
            competition="2. Bundesliga",
            season="2026/27",
            competition_clubs={"Energie Cottbus"},
            previous_reports={},
            previous_abstentions=cached,
            api_key="secret",
            now=NOW,
            requester=lambda *_args, **_kwargs: response_for([no_signal]),
        )
        self.assertEqual(0, audit["cache_hits"])
        self.assertEqual(1, audit["requests"])

    def test_new_market_player_is_prioritized(self) -> None:
        market = {
            "players": [
                {
                    "id": "old",
                    "name": "Alt",
                    "club": "A",
                    "position": "MIDFIELDER",
                    "market_value": 1_000_000,
                },
                {
                    "id": "new",
                    "name": "Neu",
                    "club": "B",
                    "position": "DEFENDER",
                    "market_value": 400_000,
                },
            ]
        }
        quality = {"annotations": {"old": {"risks": {"transfer": 0}}}}
        selected = transfer.select_transfer_targets(
            market,
            quality,
            None,
            max_players=1,
        )
        self.assertEqual("new", selected[0]["player_id"])

    def test_open_role_competition_becomes_critical_transfer_target(
        self,
    ) -> None:
        market = {
            "players": [
                {
                    "id": "incumbent",
                    "name": "Dimitrios Beispiel",
                    "club": "FC Beispiel",
                    "position": "DEFENDER",
                    "market_value": 1_600_000,
                }
            ]
        }
        quality = {
            "annotations": {
                "incumbent": {
                    "reliable_anchor": True,
                    "risks": {"transfer": 0},
                }
            }
        }
        news = {
            "players": {},
            "role_profiles": {
                "incumbent": {
                    "designation": "open_competition",
                    "external_signing_risk": 0,
                }
            },
        }

        selected = transfer.select_transfer_targets(market, quality, news)

        self.assertEqual("critical", selected[0]["research_priority"])

    def test_critical_targets_are_researched_individually(self) -> None:
        targets = []
        observed_batch_sizes: list[int] = []
        for index in range(3):
            item = target()
            item["player_id"] = f"critical-{index}"
            item["name"] = f"Critical {index}"
            item["research_priority"] = "critical"
            targets.append(item)

        def requester(payload, *, api_key):
            requested = json.loads(payload["input"][1]["content"])["players"]
            observed_batch_sizes.append(len(requested))
            reports = []
            for item in requested:
                no_signal = raw_report()
                no_signal["player_id"] = item["player_id"]
                no_signal["has_transfer_signal"] = False
                no_signal["evidence"] = []
                reports.append(no_signal)
            return response_for(reports)

        transfer.research_transfer_reports(
            targets,
            competition="2. Bundesliga",
            season="2026/27",
            competition_clubs={"Energie Cottbus"},
            previous_reports={},
            previous_abstentions={},
            api_key="secret",
            now=NOW,
            batch_size=8,
            requester=requester,
        )

        self.assertEqual([1, 1, 1], sorted(observed_batch_sizes))

    def test_multiple_batches_use_bounded_workers(self) -> None:
        targets = []
        for index in range(4):
            player = target()
            player["player_id"] = f"p{index}"
            player["name"] = f"Spieler {index}"
            targets.append(player)

        def requester(payload, *, api_key):
            requested = json.loads(
                payload["input"][1]["content"]
            )
            requested = requested["players"]
            items = []
            for item in requested:
                no_signal = raw_report()
                no_signal["player_id"] = item["player_id"]
                no_signal["has_transfer_signal"] = False
                no_signal["evidence"] = []
                items.append(no_signal)
            return response_for(items)

        reports, abstentions, audit = transfer.research_transfer_reports(
            targets,
            competition="2. Bundesliga",
            season="2026/27",
            competition_clubs={"Energie Cottbus"},
            previous_reports={},
            previous_abstentions={},
            api_key="secret",
            now=NOW,
            batch_size=2,
            max_workers=8,
            requester=requester,
        )
        self.assertEqual({}, reports)
        self.assertEqual(4, len(abstentions))
        self.assertEqual(2, audit["requests"])
        self.assertEqual(2, audit["workers"])

    def test_urgent_mode_defers_routine_expired_cache(self) -> None:
        routine = target()
        routine["research_priority"] = "routine"
        cached = transfer._cache_record(
            routine,
            now=NOW - timedelta(days=4),
            model="gpt-5.6-luna",
            status="no_grounded_transfer_signal",
        )
        _, abstentions, audit = transfer.research_transfer_reports(
            [routine],
            competition="2. Bundesliga",
            season="2026/27",
            competition_clubs={"Energie Cottbus"},
            previous_reports={},
            previous_abstentions={"p1": cached},
            api_key="secret",
            now=NOW,
            refresh_mode="urgent",
            requester=lambda *_args, **_kwargs: self.fail(
                "routine target should be deferred"
            ),
        )
        self.assertIn("p1", abstentions)
        self.assertEqual(1, audit["deferred_targets"])
        self.assertEqual(0, audit["requests"])


if __name__ == "__main__":
    unittest.main()
