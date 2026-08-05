from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
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

import news_snapshot

REFRESH_SPEC = importlib.util.spec_from_file_location(
    "refresh_news_snapshot",
    SCRIPT_DIRECTORY / "refresh_news_snapshot.py",
)
if REFRESH_SPEC is None or REFRESH_SPEC.loader is None:
    raise RuntimeError("could not load refresh_news_snapshot.py")
refresh = importlib.util.module_from_spec(REFRESH_SPEC)
sys.modules[REFRESH_SPEC.name] = refresh
REFRESH_SPEC.loader.exec_module(refresh)


def snapshot_payload() -> dict:
    payload = {
        "schema_version": 1,
        "generated_at": "2026-07-24T08:00:00Z",
        "expires_at": "2026-07-25T02:00:00Z",
        "competition": "2. Bundesliga",
        "season": "2026/27",
        "providers": {
            "api_sports": {
                "status": "ok",
                "fetched_at": "2026-07-24T08:00:00Z",
                "records": 1,
            }
        },
        "players": {
            "k1": {
                "name": "Test Player",
                "club": "Test Club",
                "mapping": {
                    "api_sports_player_id": 1,
                    "api_sports_team_id": 2,
                    "sportsmonks_player_id": None,
                    "sportsmonks_team_id": None,
                    "age": 19,
                    "confidence": "verified",
                },
                "signals": [
                    {
                        "kind": "injury",
                        "status": "questionable",
                        "severity": 40,
                        "source_provider": "api_sports",
                        "source_url": "https://example.com/injury",
                        "observed_at": "2026-07-24T08:00:00Z",
                        "provider_record_id": "1",
                        "detail": "minor doubt",
                    }
                ],
                "consensus": {
                    "injury": 40,
                    "transfer": 0,
                    "rotation": 0,
                    "fitness_cap": 60,
                    "exclude": False,
                    "confidence": "medium",
                    "conflicts": [],
                },
            }
        },
    }
    payload["content_sha256"] = news_snapshot.canonical_sha256(payload)
    return payload


class SnapshotValidationTests(unittest.TestCase):
    def test_inconclusive_role_research_is_a_valid_retryable_record(
        self,
    ) -> None:
        payload = snapshot_payload()
        payload["role_research_abstentions"] = {
            "k1": {
                "status": "research_inconclusive",
                "reason": "omitted_from_model_output",
                "model_version": "openai-role-web-v2",
                "research_model": "gpt-5.6-luna",
                "checked_at": "2026-07-24T08:00:00Z",
                "refresh_after": "2026-07-24T08:01:00Z",
                "expires_at": "2026-07-27T08:00:00Z",
            }
        }
        payload["content_sha256"] = news_snapshot.canonical_sha256(payload)

        news_snapshot.validate_snapshot(
            payload,
            now=datetime(2026, 7, 24, 12, tzinfo=timezone.utc),
        )

    def test_valid_snapshot_loads_from_local_file(self) -> None:
        payload = snapshot_payload()
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "snapshot.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded = news_snapshot.load_snapshot(
                path,
                now=datetime(2026, 7, 24, 12, tzinfo=timezone.utc),
            )
        self.assertEqual(payload, loaded)

    def test_expired_snapshot_fails_closed(self) -> None:
        payload = snapshot_payload()
        with self.assertRaisesRegex(news_snapshot.NewsSnapshotError, "expired"):
            news_snapshot.validate_snapshot(
                payload,
                now=datetime(2026, 7, 26, 12, tzinfo=timezone.utc),
            )

    def test_tampered_snapshot_hash_is_rejected(self) -> None:
        payload = snapshot_payload()
        payload["players"]["k1"]["consensus"]["injury"] = 80
        with self.assertRaisesRegex(
            news_snapshot.NewsSnapshotError,
            "content_sha256",
        ):
            news_snapshot.validate_snapshot(
                payload,
                now=datetime(2026, 7, 24, 12, tzinfo=timezone.utc),
            )


class ConsensusTests(unittest.TestCase):
    def test_editorial_evidence_loader_blocks_advanced_outbound_case(
        self,
    ) -> None:
        market = {
            "players": [
                {
                    "id": "p1",
                    "name": "Dimitrios Beispiel",
                    "club": "FC Augsburg",
                    "position": "DEFENDER",
                    "market_value": 1_600_000,
                }
            ]
        }
        evidence = {
            "schema_version": 1,
            "entries": [
                {
                    "competition": "Bundesliga",
                    "season": "2026/27",
                    "player_id": "p1",
                    "name": "Dimitrios Beispiel",
                    "club": "FC Augsburg",
                    "stage": "agreement",
                    "from_club": "FC Augsburg",
                    "to_club": "PAOK Thessaloniki",
                    "deal_type": "permanent",
                    "loan_intent": "unclear",
                    "parent_club_level": "unknown",
                    "probability": 88,
                    "contradiction": False,
                    "evidence": [
                        {
                            "claim": "Kicker berichtet vom Verkauf.",
                            "source_url": "https://www.kicker.de/transfer",
                            "observed_at": "2026-08-04T12:00:00Z",
                            "source_authority": "kicker",
                        }
                    ],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "editorial.json"
            path.write_text(json.dumps(evidence), encoding="utf-8")
            reports, audit = refresh.load_editorial_transfer_evidence(
                path,
                market=market,
                competition="Bundesliga",
                season="2026/27",
                now=datetime(2026, 8, 5, 12, tzinfo=timezone.utc),
                model="gpt-5.6-luna",
            )

        signal = refresh.transfer_report_signal(
            "p1",
            reports["p1"],
            observed_at="2026-08-05T12:00:00Z",
        )
        assert signal is not None
        consensus = refresh.consensus_for([signal])
        self.assertEqual(1, audit["records"])
        self.assertTrue(consensus["selection_blocked"])
        self.assertFalse(consensus["exclude"])

    def test_critical_inconclusive_research_is_not_zero_risk(self) -> None:
        consensus = refresh.apply_transfer_research_caution(
            refresh.consensus_for([]),
            {
                "status": "research_inconclusive",
                "research_priority": "critical",
                "verification_passes": 2,
            },
        )
        self.assertEqual(45, consensus["transfer"])
        self.assertTrue(consensus["selection_blocked"])

    @patch.dict("os.environ", {}, clear=True)
    def test_optional_sportsmonks_provider_never_blocks_primary_feed(self) -> None:
        payload = refresh.build_snapshot(
            {
                "competition": "2. Bundesliga",
                "season": "2026/27",
                "players": {},
            },
            providers=[],
            optional_providers=["sportsmonks"],
            ttl_hours=18,
        )
        self.assertEqual(
            "not_configured",
            payload["providers"]["sportsmonks"]["status"],
        )

    def test_rumour_never_auto_excludes(self) -> None:
        consensus = refresh.consensus_for(
            [
                refresh.signal(
                    kind="transfer_rumour",
                    status="rumour",
                    severity=95,
                    provider="sportsmonks",
                    observed_at="2026-07-24T08:00:00Z",
                    availability_impact="rumour",
                )
            ]
        )
        self.assertFalse(consensus["exclude"])
        self.assertEqual("low", consensus["confidence"])

    def test_two_confirmed_outbound_sources_can_exclude(self) -> None:
        signals = [
            refresh.signal(
                kind="transfer_confirmed",
                status="confirmed",
                severity=95,
                provider=provider,
                observed_at="2026-07-24T08:00:00Z",
                availability_impact="out",
            )
            for provider in ("api_sports", "sportsmonks")
        ]
        consensus = refresh.consensus_for(signals)
        self.assertTrue(consensus["exclude"])
        self.assertEqual("high", consensus["confidence"])

    def test_conflicting_confirmed_transfer_directions_are_reported(self) -> None:
        signals = [
            refresh.signal(
                kind="transfer_confirmed",
                status="confirmed",
                severity=severity,
                provider=provider,
                observed_at="2026-07-24T08:00:00Z",
                availability_impact=impact,
            )
            for provider, impact, severity in (
                ("api_sports", "out", 95),
                ("sportsmonks", "within_competition", 55),
            )
        ]
        consensus = refresh.consensus_for(signals)
        self.assertTrue(consensus["exclude"])
        self.assertEqual(1, len(consensus["conflicts"]))

    def test_later_confirmed_inbound_transfer_supersedes_loan_return(self) -> None:
        consensus = refresh.consensus_for(
            [
                refresh.signal(
                    kind="transfer_confirmed",
                    status="confirmed",
                    severity=95,
                    provider="api_sports",
                    observed_at="2026-07-28T08:00:00Z",
                    effective_from="2026-06-29",
                    availability_impact="out",
                ),
                refresh.signal(
                    kind="transfer_confirmed",
                    status="confirmed",
                    severity=10,
                    provider="api_sports",
                    observed_at="2026-07-28T08:00:00Z",
                    effective_from="2026-06-30",
                    availability_impact="in",
                ),
            ]
        )

        self.assertFalse(consensus["exclude"])
        self.assertEqual(10, consensus["transfer"])
        self.assertEqual([], consensus["conflicts"])

    def test_duplicate_provider_player_mapping_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "maps to both"):
            refresh.provider_id_map(
                {
                    "players": {
                        "k1": {"api_sports_player_id": 7},
                        "k2": {"api_sports_player_id": 7},
                    }
                },
                "api_sports",
            )

    def test_transfer_inside_competition_is_not_an_outbound_exclusion(self) -> None:
        self.assertEqual(
            ("within_competition", 55),
            refresh.classify_transfer_impact(
                current_team_id=1,
                from_team_id=1,
                to_team_id=2,
                league_team_ids={1, 2, 3},
                league_team_ids_complete=True,
            ),
        )

    def test_incomplete_team_map_cannot_prove_competition_exit(self) -> None:
        self.assertEqual(
            ("unknown_destination", 70),
            refresh.classify_transfer_impact(
                current_team_id=1,
                from_team_id=1,
                to_team_id=99,
                league_team_ids={1, 2, 3},
                league_team_ids_complete=False,
            ),
        )

    @patch.dict("os.environ", {}, clear=True)
    def test_market_only_player_and_confirmed_editorial_transfer_are_kept(
        self,
    ) -> None:
        report = {
            "model_version": "openai-transfer-watch-v1",
            "research_fingerprint": "transfer-1",
            "status": "confirmed",
            "stage": "official",
            "direction": "in",
            "from_club": "Bayer 04 Leverkusen",
            "to_club": "Energie Cottbus",
            "deal_type": "loan",
            "loan_intent": "development_minutes",
            "parent_club_level": "top_five_first_division",
            "probability": 100,
            "confidence": "high",
            "contradiction": False,
            "observed_at": "2026-07-28T12:00:00Z",
            "refresh_after": "2026-07-29T18:00:00Z",
            "expires_at": "2026-08-28T12:00:00Z",
            "fresh": True,
            "evidence": [
                {
                    "claim": "Offizielle Saisonleihe.",
                    "source_url": "https://example.com/loan",
                    "observed_at": "2026-07-28T12:00:00Z",
                    "source_authority": "official_destination_club",
                }
            ],
            "note": "",
        }
        payload = refresh.build_snapshot(
            {
                "competition": "2. Bundesliga",
                "season": "2026/27",
                "players": {},
            },
            providers=[],
            ttl_hours=18,
            researched_transfer_reports={"p1": report},
            market_players=[
                {
                    "id": "p1",
                    "name": "Luca Beispiel",
                    "club": "Energie Cottbus",
                    "position": "DEFENDER",
                }
            ],
        )
        self.assertIn("p1", payload["players"])
        self.assertEqual(
            "openai_transfer_watcher",
            payload["players"]["p1"]["signals"][0]["source_provider"],
        )
        self.assertFalse(payload["players"]["p1"]["consensus"]["exclude"])

    def test_advanced_editorial_report_never_auto_excludes(self) -> None:
        editorial = refresh.transfer_report_signal(
            "p1",
            {
                "status": "advanced",
                "stage": "medical",
                "direction": "out",
                "from_club": "A",
                "to_club": "B",
                "deal_type": "permanent",
                "research_fingerprint": "x",
                "evidence": [
                    {"source_url": "https://example.com/medical"}
                ],
            },
            observed_at="2026-07-29T08:00:00Z",
        )
        assert editorial is not None
        consensus = refresh.consensus_for([editorial])
        self.assertFalse(consensus["exclude"])
        self.assertEqual("low", consensus["confidence"])


class ProviderPagingTests(unittest.TestCase):
    @patch.object(refresh, "request_json")
    def test_api_sports_pagination_reads_every_page(self, request_json) -> None:
        request_json.side_effect = [
            {"paging": {"current": 1, "total": 2}, "response": [{"id": 1}]},
            {"paging": {"current": 2, "total": 2}, "response": [{"id": 2}]},
        ]

        pages = list(
            refresh.api_sports_pages(
                "https://provider.example/api",
                query={"league": 79},
                headers={"x-apisports-key": "secret"},
            )
        )

        self.assertEqual(2, len(pages))
        self.assertEqual(1, request_json.call_args_list[0].kwargs["query"]["page"])
        self.assertEqual(2, request_json.call_args_list[1].kwargs["query"]["page"])

    @patch.object(refresh, "request_json")
    def test_api_sports_surfaces_provider_errors(self, request_json) -> None:
        request_json.return_value = {
            "errors": {"plan": "Season is not available for this plan"},
            "paging": {"current": 1, "total": 1},
            "response": [],
        }

        with self.assertRaisesRegex(
            RuntimeError,
            "plan: Season is not available for this plan",
        ):
            list(
                refresh.api_sports_pages(
                    "https://provider.example/api",
                    query={"league": 79, "season": 2026},
                    headers={"x-apisports-key": "secret"},
                )
            )

    @patch.object(refresh, "request_json")
    def test_api_sports_non_paginated_endpoint_omits_page(
        self,
        request_json,
    ) -> None:
        request_json.return_value = {
            "errors": {},
            "paging": {"current": 1, "total": 1},
            "response": [],
        }

        pages = list(
            refresh.api_sports_pages(
                "https://provider.example/teams",
                query={"league": 79, "season": 2026},
                headers={"x-apisports-key": "secret"},
                paginate=False,
            )
        )

        self.assertEqual(1, len(pages))
        self.assertNotIn("page", request_json.call_args.kwargs["query"])

    @patch.object(refresh, "request_json")
    def test_sportsmonks_pagination_uses_header_auth(self, request_json) -> None:
        request_json.side_effect = [
            {
                "pagination": {"has_more": True},
                "data": [{"id": 1}],
            },
            {
                "pagination": {"has_more": False},
                "data": [{"id": 2}],
            },
        ]

        pages = list(
            refresh.sportsmonks_pages(
                "https://provider.example/api",
                query={"order": "desc"},
                headers={"Authorization": "secret"},
            )
        )

        self.assertEqual(2, len(pages))
        for call in request_json.call_args_list:
            self.assertNotIn("api_token", call.kwargs["query"])
            self.assertEqual(
                {"Authorization": "secret"},
                call.kwargs["headers"],
            )


class ApiSportsRosterDiscoveryTests(unittest.TestCase):
    @patch.object(refresh, "api_sports_pages")
    def test_discovers_verified_players_and_complete_team_set(
        self,
        api_sports_pages,
    ) -> None:
        api_sports_pages.side_effect = [
            iter(
                [
                    {
                        "response": [
                            {"team": {"id": 10, "name": "Club One"}},
                            {"team": {"id": 20, "name": "Club Two"}},
                        ]
                    }
                ]
            ),
            iter(
                [
                    {
                        "response": [
                            {
                                "team": {"id": 10, "name": "Club One"},
                                "players": [
                                    {
                                        "id": 101,
                                        "name": "Max Player",
                                        "age": 18,
                                    }
                                ],
                            }
                        ]
                    }
                ]
            ),
            iter(
                [
                    {
                        "response": [
                            {
                                "team": {"id": 20, "name": "Club Two"},
                                "players": [],
                            }
                        ]
                    }
                ]
            ),
        ]

        discovered, audit = refresh.discover_api_sports_roster(
            {
                "api_sports": {
                    "league_id": 79,
                    "season": 2026,
                    "expected_team_count": 2,
                    "auto_discover_players": True,
                },
                "players": {},
            },
            "secret",
        )

        self.assertEqual("discovered", audit["status"])
        self.assertEqual(2, audit["teams"])
        self.assertEqual(
            {
                "name": "Max Player",
                "club": "Club One",
                "api_sports_player_id": 101,
                "api_sports_team_id": 10,
                "mapping_confidence": "verified",
                "age": 18,
                "position": "",
            },
            discovered["players"]["api_sports:101"],
        )
        self.assertTrue(
            discovered["api_sports"]["competition_team_ids_complete"]
        )

    @patch.object(refresh, "api_sports_pages")
    def test_incomplete_team_discovery_fails_closed(
        self,
        api_sports_pages,
    ) -> None:
        api_sports_pages.return_value = iter(
            [{"response": [{"team": {"id": 10, "name": "Club One"}}]}]
        )
        with self.assertRaisesRegex(RuntimeError, "expected 2"):
            refresh.discover_api_sports_roster(
                {
                    "api_sports": {
                        "league_id": 79,
                        "season": 2026,
                        "expected_team_count": 2,
                        "auto_discover_players": True,
                    },
                    "players": {},
                },
                "secret",
            )


if __name__ == "__main__":
    unittest.main()
