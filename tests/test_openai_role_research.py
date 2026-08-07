from __future__ import annotations

import importlib.util
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

SPEC = importlib.util.spec_from_file_location(
    "openai_role_research",
    SCRIPT_DIRECTORY / "openai_role_research.py",
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load openai_role_research.py")
role = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = role
SPEC.loader.exec_module(role)


NOW = datetime(2026, 7, 28, 12, tzinfo=timezone.utc)


def target(player_id: str = "p1", position: str = "FORWARD") -> dict:
    return {
        "player_id": player_id,
        "name": "Test Spieler",
        "club": "Testverein",
        "position": position,
        "market_value": 900_000,
    }


def raw_profile(
    player_id: str = "p1",
    *,
    contradiction: bool = False,
    source_url: str = "https://testverein.de/news/rolle",
) -> dict:
    return {
        "player_id": player_id,
        "has_role_signal": True,
        "designation": "key_starter",
        "continuity": "confirmed",
        "expected_start_probability": 91,
        "external_signing_risk": 0,
        "responsibilities": {
            "aerial_set_piece_target": "none",
            "captain": "none",
            "corners": "shared",
            "direct_free_kicks": "primary",
            "offensive_focal_point": "primary",
            "penalties": "shared",
            "playmaker": "primary",
        },
        "role_environment": {
            "coach_trust": "high",
            "squad_status": "core",
            "tactical_fit": "strong",
            "positional_competition": "low",
            "expected_minutes_band": "2700_plus",
            "role_stability": "stable",
        },
        "recent_competitive_role": {
            "sample_matches": 6,
            "starts": 5,
            "decisive_match_preference": "player_preferred",
            "direct_competitor": "Direkter Konkurrent",
        },
        "availability_status": "available",
        "exit_status": "none",
        "confidence": "high",
        "contradiction": contradiction,
        "note": "Der Trainer plant mit ihm als zentraler Offensivkraft.",
        "evidence": [
            {
                "claim": "Der Trainer nennt ihn eine zentrale Offensivkraft.",
                "source_url": source_url,
                "observed_at": "2026-07-26",
                "source_authority": "head_coach",
            }
        ],
    }


def response_for(profiles: list[dict]) -> dict:
    urls = [
        item["source_url"]
        for profile in profiles
        for item in profile.get("evidence", [])
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
                        "text": json.dumps({"profiles": profiles}),
                    }
                ],
            },
        ]
    }


class TargetSelectionTests(unittest.TestCase):
    def test_zero_limit_selects_every_available_market_player(self) -> None:
        market = {
            "players": [
                {
                    "id": f"p{index}",
                    "name": f"Spieler {index}",
                    "club": f"Verein {index % 3}",
                    "position": (
                        "GOALKEEPER",
                        "DEFENDER",
                        "MIDFIELDER",
                        "FORWARD",
                    )[index % 4],
                    "market_value": 100_000 + index,
                    "available": True,
                }
                for index in range(25)
            ]
        }
        selected = role.select_role_targets(market, None, max_players=0)
        self.assertEqual(25, len(selected))
        self.assertEqual(
            {f"p{index}" for index in range(25)},
            {item["player_id"] for item in selected},
        )

    def test_priority_mix_includes_open_research_benchmarks_and_goalkeepers(
        self,
    ) -> None:
        market = {
            "players": [
                {
                    "id": "open",
                    "name": "Open",
                    "club": "A",
                    "position": "MIDFIELDER",
                    "market_value": 300_000,
                    "available": True,
                },
                {
                    "id": "benchmark",
                    "name": "Benchmark",
                    "club": "B",
                    "position": "FORWARD",
                    "market_value": 900_000,
                    "available": True,
                },
                {
                    "id": "keeper",
                    "name": "Keeper",
                    "club": "C",
                    "position": "GOALKEEPER",
                    "market_value": 500_000,
                    "available": True,
                },
            ]
        }
        quality = {
            "annotations": {
                "open": {"role_research": {"required": True}},
                "benchmark": {"benchmark": True},
            }
        }
        selected = role.select_role_targets(market, quality, max_players=3)
        self.assertEqual(
            {"open", "benchmark", "keeper"},
            {item["player_id"] for item in selected},
        )

    def test_target_mix_reserves_two_goalkeepers_and_offense_per_club(
        self,
    ) -> None:
        players = []
        annotations = {}
        for club in ("A", "B", "C"):
            for index, position in enumerate(
                (
                    "GOALKEEPER",
                    "GOALKEEPER",
                    "DEFENDER",
                    "MIDFIELDER",
                    "FORWARD",
                )
            ):
                player_id = f"{club}-{index}"
                players.append(
                    {
                        "id": player_id,
                        "name": player_id,
                        "club": club,
                        "position": position,
                        "market_value": 900_000 - index * 100_000,
                        "available": True,
                    }
                )
                if position == "DEFENDER":
                    annotations[player_id] = {"reliable_anchor": True}
        selected = role.select_role_targets(
            {"players": players},
            {"annotations": annotations},
            max_players=12,
        )
        selected_ids = {item["player_id"] for item in selected}
        for club in ("A", "B", "C"):
            self.assertTrue({f"{club}-0", f"{club}-1"} <= selected_ids)
            self.assertTrue(
                {f"{club}-3", f"{club}-4"} & selected_ids,
                f"missing offensive coverage for club {club}",
            )


class GroundingTests(unittest.TestCase):
    def test_ungrounded_model_url_is_rejected(self) -> None:
        normalized = role.normalize_profile(
            raw_profile(),
            target=target(),
            grounded_urls={"https://other.example/news"},
            now=NOW,
            model="gpt-5.6-luna",
        )
        self.assertIsNone(normalized)

    def test_current_official_evidence_builds_bounded_profile(self) -> None:
        normalized = role.normalize_profile(
            raw_profile(),
            target=target(),
            grounded_urls={"https://testverein.de/news/rolle"},
            now=NOW,
            model="gpt-5.6-luna",
        )
        assert normalized is not None
        self.assertEqual("key_starter", normalized["designation"])
        self.assertEqual(91, normalized["expected_start_probability"])
        self.assertEqual("high", normalized["confidence"])
        self.assertEqual("primary", normalized["responsibilities"]["playmaker"])
        self.assertEqual(
            "strong",
            normalized["role_environment"]["tactical_fit"],
        )
        self.assertEqual(
            "player_preferred",
            normalized["recent_competitive_role"][
                "decisive_match_preference"
            ],
        )
        self.assertEqual("available", normalized["availability_status"])
        self.assertEqual("none", normalized["exit_status"])

    def test_contradiction_fails_closed_to_open_competition(self) -> None:
        normalized = role.normalize_profile(
            raw_profile(contradiction=True),
            target=target(),
            grounded_urls={"https://testverein.de/news/rolle"},
            now=NOW,
            model="gpt-5.6-luna",
        )
        assert normalized is not None
        self.assertEqual("open_competition", normalized["designation"])
        self.assertLessEqual(normalized["expected_start_probability"], 55)
        self.assertEqual("low", normalized["confidence"])

    def test_goalkeeper_external_signing_risk_is_preserved(self) -> None:
        profile = raw_profile()
        profile["external_signing_risk"] = 72
        normalized = role.normalize_profile(
            profile,
            target=target(position="GOALKEEPER"),
            grounded_urls={"https://testverein.de/news/rolle"},
            now=NOW,
            model="gpt-5.6-luna",
        )
        assert normalized is not None
        self.assertEqual(72, normalized["external_signing_risk"])


class ResearchCacheTests(unittest.TestCase):
    def test_fresh_matching_profile_avoids_openai_request(self) -> None:
        cached = role.normalize_profile(
            raw_profile(),
            target=target(),
            grounded_urls={"https://testverein.de/news/rolle"},
            now=NOW,
            model="gpt-5.6-luna",
        )
        assert cached is not None
        calls = []

        def requester(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("requester should not be called")

        profiles, abstentions, audit = role.research_role_profiles(
            [target()],
            competition="2. Bundesliga",
            season="2026/27",
            previous_profiles={"p1": cached},
            api_key="not-a-real-key",
            model="gpt-5.6-luna",
            now=NOW + timedelta(hours=1),
            requester=requester,
        )
        self.assertEqual([], calls)
        self.assertEqual(1, audit["cache_hits"])
        self.assertIn("p1", profiles)
        self.assertEqual({}, abstentions)

    def test_changed_or_missing_profile_is_researched_and_grounded(self) -> None:
        captured = {}

        def requester(payload, *, api_key):
            captured["payload"] = payload
            captured["api_key"] = api_key
            return response_for([raw_profile()])

        profiles, abstentions, audit = role.research_role_profiles(
            [target()],
            competition="2. Bundesliga",
            season="2026/27",
            previous_profiles={},
            api_key="secret-value",
            model="gpt-5.6-luna",
            now=NOW,
            requester=requester,
        )
        self.assertIn("p1", profiles)
        self.assertEqual({}, abstentions)
        self.assertEqual(1, audit["requests"])
        self.assertEqual(1, audit["researched_profiles"])
        self.assertEqual(
            [{"type": "web_search"}],
            captured["payload"]["tools"],
        )
        self.assertTrue(captured["payload"]["text"]["format"]["strict"])
        self.assertFalse(captured["payload"]["store"])
        self.assertNotIn(
            "secret-value",
            json.dumps(captured["payload"]),
        )

    def test_no_signal_is_cached_without_inventing_a_profile(self) -> None:
        no_signal = raw_profile()
        no_signal["has_role_signal"] = False
        no_signal["evidence"] = []
        calls = []

        def first_requester(payload, *, api_key):
            calls.append(payload)
            return response_for([no_signal])

        profiles, abstentions, audit = role.research_role_profiles(
            [target()],
            competition="2. Bundesliga",
            season="2026/27",
            previous_profiles={},
            api_key="secret-value",
            model="gpt-5.6-luna",
            now=NOW,
            requester=first_requester,
        )
        self.assertEqual({}, profiles)
        self.assertIn("p1", abstentions)
        self.assertEqual(1, audit["researched_abstentions"])

        def forbidden_requester(*args, **kwargs):
            raise AssertionError("negative cache should prevent a new request")

        profiles, reused, audit = role.research_role_profiles(
            [target()],
            competition="2. Bundesliga",
            season="2026/27",
            previous_profiles={},
            previous_abstentions=abstentions,
            api_key="secret-value",
            model="gpt-5.6-luna",
            now=NOW + timedelta(hours=1),
            requester=forbidden_requester,
        )
        self.assertEqual({}, profiles)
        self.assertIn("p1", reused)
        self.assertEqual(1, audit["cache_hits"])
        self.assertEqual(0, audit["requests"])

    def test_required_role_forces_retry_despite_fresh_abstention(
        self,
    ) -> None:
        forced_target = target()
        forced_target["force_refresh"] = True
        cached_abstention = role.abstention_record(
            target(),
            now=NOW,
            model="gpt-5.6-luna",
        )
        calls = []

        def requester(payload, *, api_key):
            calls.append(payload)
            return response_for([raw_profile()])

        profiles, abstentions, audit = role.research_role_profiles(
            [forced_target],
            competition="2. Bundesliga",
            season="2026/27",
            previous_profiles={},
            previous_abstentions={"p1": cached_abstention},
            api_key="secret-value",
            model="gpt-5.6-luna",
            now=NOW + timedelta(hours=1),
            requester=requester,
        )

        self.assertEqual(1, len(calls))
        self.assertIn("p1", profiles)
        self.assertEqual({}, abstentions)
        self.assertEqual(0, audit["cache_hits"])
        self.assertEqual(1, audit["forced_refreshes"])

    def test_forced_abstention_is_not_retried_until_refresh_window(
        self,
    ) -> None:
        forced_target = target()
        forced_target["force_refresh"] = True
        forced_abstention = role.abstention_record(
            forced_target,
            now=NOW,
            model="gpt-5.6-luna",
        )

        profiles, abstentions, audit = role.research_role_profiles(
            [forced_target],
            competition="2. Bundesliga",
            season="2026/27",
            previous_profiles={},
            previous_abstentions={"p1": forced_abstention},
            api_key="secret-value",
            model="gpt-5.6-luna",
            now=NOW + timedelta(hours=1),
            requester=lambda *args, **kwargs: self.fail(
                "forced negative cache should be reused"
            ),
        )

        self.assertEqual({}, profiles)
        self.assertIn("p1", abstentions)
        self.assertEqual(1, audit["cache_hits"])
        self.assertEqual(0, audit["forced_refreshes"])

    def test_omitted_target_is_explicitly_inconclusive_and_retried(
        self,
    ) -> None:
        calls = []

        def requester(payload, *, api_key):
            calls.append(payload)
            return response_for([])

        profiles, abstentions, audit = role.research_role_profiles(
            [target()],
            competition="2. Bundesliga",
            season="2026/27",
            previous_profiles={},
            api_key="secret-value",
            model="gpt-5.6-luna",
            now=NOW,
            requester=requester,
        )

        self.assertEqual({}, profiles)
        self.assertEqual(
            "research_inconclusive",
            abstentions["p1"]["status"],
        )
        self.assertEqual(
            "omitted_from_model_output",
            abstentions["p1"]["reason"],
        )
        self.assertEqual(1, audit["researched_inconclusive"])
        self.assertEqual("partial", audit["status"])

        role.research_role_profiles(
            [target()],
            competition="2. Bundesliga",
            season="2026/27",
            previous_profiles={},
            previous_abstentions=abstentions,
            api_key="secret-value",
            model="gpt-5.6-luna",
            now=NOW + timedelta(minutes=1),
            requester=requester,
        )
        self.assertEqual(2, len(calls))

    def test_changed_club_invalidates_matching_cache(self) -> None:
        cached = role.normalize_profile(
            raw_profile(),
            target=target(),
            grounded_urls={"https://testverein.de/news/rolle"},
            now=NOW,
            model="gpt-5.6-luna",
        )
        assert cached is not None
        moved = target()
        moved["club"] = "Neuer Verein"
        profiles, _, audit = role.research_role_profiles(
            [moved],
            competition="2. Bundesliga",
            season="2026/27",
            previous_profiles={"p1": cached},
            api_key="secret-value",
            model="gpt-5.6-luna",
            now=NOW + timedelta(hours=1),
            requester=lambda *_args, **_kwargs: response_for([raw_profile()]),
        )
        self.assertEqual(0, audit["cache_hits"])
        self.assertEqual(1, audit["requests"])
        self.assertIn("p1", profiles)


if __name__ == "__main__":
    unittest.main()
