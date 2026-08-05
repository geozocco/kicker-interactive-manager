from __future__ import annotations

import importlib.util
import itertools
import json
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    REPOSITORY_ROOT
    / "plugins"
    / "kicker-interactive-manager"
    / "skills"
    / "build-kicker-interactive-squad"
    / "scripts"
    / "optimize_squad.py"
)
SPEC = importlib.util.spec_from_file_location("optimize_squad", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load optimize_squad.py")
optimizer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = optimizer
SPEC.loader.exec_module(optimizer)
import news_snapshot


def player(
    player_id: str,
    club: str,
    position: str,
    cost: int,
    *,
    reliable_anchor: bool = False,
    benchmark: bool = False,
    role_context: dict[str, object] | None = None,
    role_research: dict[str, object] | None = None,
) -> optimizer.Player:
    return optimizer.Player(
        player_id=player_id,
        name=f"Player {player_id}",
        short_name=player_id,
        club=club,
        position=position,
        cost=cost,
        points=0.0,
        grade=0.0,
        components={key: 70.0 for key in optimizer.COMPONENTS},
        risks={key: 10.0 for key in optimizer.RISKS},
        researched=True,
        reliable_anchor=reliable_anchor,
        anchor_basis="explicit" if reliable_anchor else "none",
        anchor_reason="Repeated performance and stable role" if reliable_anchor else "",
        benchmark=benchmark,
        evidence=(
            {
                "claim": "Current role checked",
                "source_url": "https://example.com/player",
                "checked_at": "2026-07-24",
            },
        ),
        proven_seasons=3 if reliable_anchor else 0,
        role_context=role_context or {},
        role_research=role_research or {},
    )


def premium_scorer_profile() -> dict[str, object]:
    return {
        "sample_minutes": 6_000,
        "proven_seasons": 5,
        "goals_per_90": 0.24,
        "contributions_per_90": 0.43,
    }


def varied_pool() -> tuple[list[optimizer.Player], dict[str, float]]:
    players: list[optimizer.Player] = []
    scores: dict[str, float] = {}
    for club_index, club in enumerate(("GKA", "GKB", "GKC")):
        for keeper_index in range(3):
            player_id = f"G{club_index}{keeper_index}"
            players.append(player(player_id, club, "GOALKEEPER", 100))
            scores[player_id] = 15.0 - 0.10 * (club_index + keeper_index)
    for position, prefix in (
        ("DEFENDER", "D"),
        ("MIDFIELDER", "M"),
        ("FORWARD", "F"),
    ):
        for index in range(6):
            player_id = f"{prefix}{index}"
            players.append(
                player(
                    player_id,
                    f"{prefix}Club{index}",
                    position,
                    100,
                )
            )
            scores[player_id] = 10.0 - 0.08 * index
    return players, scores


class DistanceOptimizerTests(unittest.TestCase):
    def test_unresolved_transfer_role_excludes_only_affected_player(
        self,
    ) -> None:
        open_role = player(
            "OPEN",
            "New Club",
            "FORWARD",
            700_000,
            benchmark=True,
            role_research={
                "required": True,
                "priority": "high",
            },
        )
        cleared = player("CLEAR", "Other Club", "FORWARD", 600_000)

        filtered, exclusions = (
            optimizer.exclude_unresolved_role_research(
                [open_role, cleared]
            )
        )

        self.assertEqual(["CLEAR"], [item.player_id for item in filtered])
        self.assertEqual("OPEN", exclusions[0]["annotation_key"])
        self.assertTrue(
            exclusions[0]["temporary_role_research_exclusion"]
        )
        self.assertTrue(exclusions[0]["benchmark"])

    def test_shortlist_surfaces_evidence_backed_attacking_role_winner(
        self,
    ) -> None:
        candidates = [
            player(
                f"M{index}",
                f"Club {index}",
                "MIDFIELDER",
                100 + index,
            )
            for index in range(10)
        ]
        role_winner = player(
            "ROLE",
            "New Club",
            "MIDFIELDER",
            95,
            role_context={
                "continuity": "confirmed",
                "expected_start_probability": 85,
                "responsibilities": {
                    "direct_free_kicks": "shared",
                    "playmaker": "shared",
                },
            },
        )
        candidates.append(role_winner)
        scores = {
            candidate.player_id: 100.0 - index
            for index, candidate in enumerate(candidates)
        }
        scores["ROLE"] = 20.0

        payload = optimizer.shortlist_payload(
            candidates,
            scores,
            "reliable",
            {"MIDFIELDER": 7},
        )

        premium_ids = {
            item["id"]
            for item in payload["shortlist"]["MIDFIELDER"][
                "premium_review"
            ]
        }
        self.assertIn("ROLE", premium_ids)

    def test_competition_budgets_default_to_fixed_kicker_limits(self) -> None:
        for competition, expected_budget in (
            ("Bundesliga", 42_500_000),
            ("2. Bundesliga", 10_000_000),
            ("3. Liga", 6_000_000),
        ):
            with self.subTest(competition=competition), mock.patch.object(
                sys,
                "argv",
                [
                    str(SCRIPT_PATH),
                    "--competition",
                    competition,
                    "--season",
                    "2026/27",
                    "--players",
                    "players.csv",
                ],
            ):
                args = optimizer.parse_args()
                self.assertEqual(expected_budget, args.budget)

    def test_final_recommendation_rejects_wrong_competition_budget(
        self,
    ) -> None:
        with mock.patch.object(
            sys,
            "argv",
            [
                str(SCRIPT_PATH),
                "--competition",
                "3. Liga",
                "--season",
                "2026/27",
                "--players",
                "players.csv",
                "--budget",
                "10000000",
            ],
        ):
            with self.assertRaises(SystemExit):
                optimizer.parse_args()

    def test_reliable_low_maintenance_defaults_fund_the_starting_core(self) -> None:
        with mock.patch.object(
            sys,
            "argv",
            [
                str(SCRIPT_PATH),
                "--players",
                "players.csv",
                "--profile",
                "reliable",
                "--maintenance",
                "low",
                "--budget",
                "10000000",
            ],
        ):
            args = optimizer.parse_args()

        self.assertEqual(0.55, args.min_core_budget_share)
        self.assertEqual(0.80, args.target_core_budget_share)
        self.assertEqual(1.0, args.min_spend_ratio)
        self.assertEqual(1, args.min_offensive_premium_anchors)
        self.assertEqual(1, args.min_qualified_potential_core)
        self.assertEqual(2, args.target_qualified_potential_core)

    def test_final_recommendation_rejects_partial_budget_override(self) -> None:
        with mock.patch.object(
            sys,
            "argv",
            [
                str(SCRIPT_PATH),
                "--players",
                "players.csv",
                "--profile",
                "reliable",
                "--maintenance",
                "low",
                "--budget",
                "10000000",
                "--min-spend-ratio",
                "0.70",
            ],
        ):
            with self.assertRaises(SystemExit):
                optimizer.parse_args()

    def test_market_adjusts_core_target_to_positional_price_ceiling(self) -> None:
        players = [
            player(f"g{index}", "Goalkeeper Club", "GOALKEEPER", 600)
            for index in range(3)
        ]
        for position, prefix, count in (
            ("DEFENDER", "d", 7),
            ("MIDFIELDER", "m", 7),
            ("FORWARD", "f", 5),
        ):
            players.extend(
                player(
                    f"{prefix}{index}",
                    f"Club {prefix}{index}",
                    position,
                    600,
                )
                for index in range(count)
            )

        target = optimizer.market_core_budget_share_target(
            players,
            10_000,
            0.80,
        )

        self.assertAlmostEqual(0.66, target)

    def test_starting_lineup_can_require_an_evidence_derived_premium_anchor(
        self,
    ) -> None:
        players: list[optimizer.Player] = [
            player(f"g{index}", "Goalkeeper Club", "GOALKEEPER", 100)
            for index in range(3)
        ]
        for position, prefix, count in (
            ("DEFENDER", "d", 7),
            ("MIDFIELDER", "m", 7),
            ("FORWARD", "f", 5),
        ):
            for index in range(count):
                players.append(
                    player(
                        f"{prefix}{index}",
                        f"{prefix.upper()} Club {index}",
                        position,
                        100,
                        reliable_anchor=index < 4,
                    )
                )
        premium = next(
            item for item in players if item.player_id == "m6"
        )
        premium_components = dict(premium.components)
        premium_components.update(
            {
                "confirmed_performance": 99.0,
                "minutes": 90.0,
                "role": 95.0,
                "stability": 85.0,
            }
        )
        premium = optimizer.replace(
            premium,
            components=premium_components,
            reliable_anchor=True,
            proven_seasons=7,
            scorer_profile=premium_scorer_profile(),
        )
        players = [
            premium if item.player_id == premium.player_id else item
            for item in players
        ]
        scores = {
            item.player_id: 100.0 - index
            for index, item in enumerate(players)
        }
        scores[premium.player_id] = 1.0

        _, unconstrained_ids = optimizer.best_starting_lineup(
            players,
            scores,
        )
        _, constrained_ids = optimizer.best_starting_lineup(
            players,
            scores,
            min_offensive_premium_anchors=1,
        )

        self.assertTrue(optimizer.is_offensive_premium_anchor(premium))
        self.assertNotIn(premium.player_id, unconstrained_ids)
        self.assertIn(premium.player_id, constrained_ids)

    def test_starting_lineup_can_require_a_qualified_u23_prospect(
        self,
    ) -> None:
        players: list[optimizer.Player] = [
            player(f"g{index}", "Goalkeeper Club", "GOALKEEPER", 100)
            for index in range(3)
        ]
        for position, prefix, count in (
            ("DEFENDER", "d", 7),
            ("MIDFIELDER", "m", 7),
            ("FORWARD", "f", 5),
        ):
            for index in range(count):
                players.append(
                    player(
                        f"{prefix}{index}",
                        f"{prefix.upper()} Club {index}",
                        position,
                        100,
                    )
                )
        prospect_id = "m6"
        scores = {
            item.player_id: 100.0 - index
            for index, item in enumerate(players)
        }
        scores[prospect_id] = 1.0

        _, unconstrained_ids = optimizer.best_starting_lineup(
            players,
            scores,
        )
        _, constrained_ids = optimizer.best_starting_lineup(
            players,
            scores,
            qualified_potential_ids=frozenset({prospect_id}),
            min_qualified_potential_starters=1,
        )

        self.assertNotIn(prospect_id, unconstrained_ids)
        self.assertIn(prospect_id, constrained_ids)

    def test_postprocessing_variation_corridor_is_narrow(self) -> None:
        self.assertTrue(optimizer.variation_distance_met("medium", 4))
        self.assertTrue(optimizer.variation_distance_met("medium", 5))
        self.assertTrue(optimizer.variation_distance_met("medium", 6))
        self.assertFalse(optimizer.variation_distance_met("medium", 7))
        self.assertFalse(optimizer.variation_distance_met("medium", 8))
        self.assertTrue(optimizer.variation_distance_met("none", 0))
        self.assertFalse(optimizer.variation_distance_met("none", 1))

    def test_technical_variation_pool_preserves_optimum_and_goalkeeper_blocks(
        self,
    ) -> None:
        candidates: list[optimizer.Player] = []
        for index in range(48):
            candidates.append(
                player(
                    f"g{index}",
                    f"GK Club {index // 3}",
                    "GOALKEEPER",
                    100 + index,
                )
            )
        for position, prefix in (
            ("DEFENDER", "d"),
            ("MIDFIELDER", "m"),
            ("FORWARD", "f"),
        ):
            for index in range(60):
                candidates.append(
                    player(
                        f"{prefix}{index}",
                        f"Club {prefix}{index}",
                        position,
                        100 + index,
                    )
                )
        scores = {
            candidate.player_id: float(index)
            for index, candidate in enumerate(candidates)
        }
        optimum_ids = {
            "g45", "g46", "g47",
            "d59", "d58", "d57", "d56", "d55", "d54", "d53",
            "m59", "m58", "m57", "m56", "m55", "m54", "m53",
            "f59", "f58", "f57", "f56", "f55",
        }
        optimum_players = [
            candidate
            for candidate in candidates
            if candidate.player_id in optimum_ids
        ]

        bounded = optimizer.technical_variation_pool(
            candidates,
            scores,
            optimizer.Squad(optimum_players, 0.0),
            {
                "GOALKEEPER": 3,
                "DEFENDER": 7,
                "MIDFIELDER": 7,
                "FORWARD": 5,
            },
        )

        bounded_ids = {candidate.player_id for candidate in bounded}
        self.assertTrue(optimum_ids <= bounded_ids)
        self.assertEqual(
            {"g45", "g46", "g47"},
            {
                candidate.player_id
                for candidate in bounded
                if candidate.club == "GK Club 15"
            },
        )
        self.assertLess(len(bounded), len(candidates))

    def test_exact_distance_pool_keeps_enough_pareto_layers(self) -> None:
        candidates = [
            player("g1", "GK", "GOALKEEPER", 100),
            player("reference", "Club", "DEFENDER", 100),
        ]
        candidates.extend(
            player(f"d{index}", "Club", "DEFENDER", 100)
            for index in range(1, 7)
        )
        scores = {
            candidate.player_id: (
                100.0
                if candidate.player_id in {"g1", "reference"}
                else 100.0 - int(candidate.player_id[1:])
            )
            for candidate in candidates
        }

        bounded = optimizer.exact_distance_candidate_pool(
            candidates,
            scores,
            {
                "GOALKEEPER": 3,
                "DEFENDER": 7,
                "MIDFIELDER": 7,
                "FORWARD": 5,
            },
            club_cap=4,
            reference_ids=frozenset({"reference"}),
            distance_cap=2,
        )

        self.assertEqual(
            {"g1", "reference", "d1", "d2"},
            {candidate.player_id for candidate in bounded},
        )

    def test_exact_distance_pool_does_not_cross_anchor_classes(self) -> None:
        weak_anchor = player(
            "anchor",
            "Club",
            "MIDFIELDER",
            200,
            reliable_anchor=True,
        )
        cheaper_non_anchor = player(
            "non-anchor",
            "Club",
            "MIDFIELDER",
            100,
        )

        bounded = optimizer.exact_distance_candidate_pool(
            [weak_anchor, cheaper_non_anchor],
            {"anchor": 10.0, "non-anchor": 20.0},
            {
                "GOALKEEPER": 3,
                "DEFENDER": 7,
                "MIDFIELDER": 7,
                "FORWARD": 5,
            },
            club_cap=4,
            reference_ids=frozenset(),
            distance_cap=1,
        )

        self.assertEqual(
            {"anchor", "non-anchor"},
            {candidate.player_id for candidate in bounded},
        )

    def test_exact_distance_pool_preserves_spend_options(self) -> None:
        cheaper = player("cheap", "Club", "FORWARD", 100)
        expensive = player("expensive", "Club", "FORWARD", 200)

        bounded = optimizer.exact_distance_candidate_pool(
            [cheaper, expensive],
            {"cheap": 20.0, "expensive": 10.0},
            {
                "GOALKEEPER": 3,
                "DEFENDER": 7,
                "MIDFIELDER": 7,
                "FORWARD": 5,
            },
            club_cap=4,
            reference_ids=frozenset(),
            distance_cap=1,
        )

        self.assertEqual(
            {"cheap", "expensive"},
            {candidate.player_id for candidate in bounded},
        )

    def test_seed_independent_optimum_is_reused_from_validated_cache(self) -> None:
        slots = {
            "GOALKEEPER": 2,
            "DEFENDER": 1,
            "MIDFIELDER": 1,
            "FORWARD": 1,
        }
        players = [
            player("g1", "GK", "GOALKEEPER", 10),
            player("g2", "GK", "GOALKEEPER", 10),
            player("g3", "GK", "GOALKEEPER", 10),
            player("d1", "D", "DEFENDER", 10),
            player("m1", "M", "MIDFIELDER", 10),
            player("f1", "F", "FORWARD", 10),
        ]
        scores = {
            candidate.player_id: 20.0 - index
            for index, candidate in enumerate(players)
        }

        with tempfile.TemporaryDirectory() as directory:
            cache_directory = Path(directory)
            first = optimizer.optimize(
                players,
                50,
                scores,
                1,
                50,
                slots,
                cache_directory=cache_directory,
            )
            with mock.patch.object(
                optimizer,
                "outfield_options",
                side_effect=AssertionError("cache miss"),
            ):
                second = optimizer.optimize(
                    players,
                    50,
                    scores,
                    1,
                    50,
                    slots,
                    cache_directory=cache_directory,
                )

        self.assertEqual(first.ids, second.ids)
        self.assertEqual(first.objective_score, second.objective_score)

    def test_distance_buckets_match_brute_force_oracle(self) -> None:
        slots = {
            "GOALKEEPER": 2,
            "DEFENDER": 1,
            "MIDFIELDER": 1,
            "FORWARD": 1,
        }
        players = [
            player("ga1", "GKA", "GOALKEEPER", 10),
            player("ga2", "GKA", "GOALKEEPER", 11),
            player("ga3", "GKA", "GOALKEEPER", 12),
            player("gb1", "GKB", "GOALKEEPER", 10),
            player("gb2", "GKB", "GOALKEEPER", 12),
            player("gb3", "GKB", "GOALKEEPER", 14),
            player("d1", "D1", "DEFENDER", 9, reliable_anchor=True),
            player("d2", "D2", "DEFENDER", 13),
            player("m1", "M1", "MIDFIELDER", 9, reliable_anchor=True),
            player("m2", "M2", "MIDFIELDER", 12),
            player("f1", "F1", "FORWARD", 10, reliable_anchor=True),
            player("f2", "F2", "FORWARD", 13, reliable_anchor=True),
        ]
        scores = {
            item.player_id: 30.0 - index * 0.37
            for index, item in enumerate(players)
        }
        budget = 60
        minimum_spend = 47
        club_cap = 1
        optimum = optimizer.optimize(
            players,
            budget,
            scores,
            club_cap,
            minimum_spend,
            slots,
            min_reliable_anchors=2,
        )
        distance_cap = 3
        actual = optimizer.optimize_distance_buckets(
            players,
            budget,
            scores,
            club_cap,
            minimum_spend,
            slots,
            optimum.ids,
            distance_cap,
            min_reliable_anchors=2,
        )

        by_position = {
            position: [item for item in players if item.position == position]
            for position in slots
        }
        goalkeeper_groups: list[tuple[optimizer.Player, ...]] = []
        for club in ("GKA", "GKB"):
            club_players = [
                item for item in by_position["GOALKEEPER"] if item.club == club
            ]
            expected_primary = optimizer.expected_primary_goalkeeper(
                club_players,
                scores,
            )
            goalkeeper_groups.extend(
                combination
                for combination in itertools.combinations(
                    club_players,
                    slots["GOALKEEPER"],
                )
                if expected_primary in combination
            )
        expected: dict[int, float] = {}
        for goalkeepers in goalkeeper_groups:
            for defenders in itertools.combinations(
                by_position["DEFENDER"],
                slots["DEFENDER"],
            ):
                for midfielders in itertools.combinations(
                    by_position["MIDFIELDER"],
                    slots["MIDFIELDER"],
                ):
                    for forwards in itertools.combinations(
                        by_position["FORWARD"],
                        slots["FORWARD"],
                    ):
                        squad = (*goalkeepers, *defenders, *midfielders, *forwards)
                        cost = sum(item.cost for item in squad)
                        if not minimum_spend <= cost <= budget:
                            continue
                        outfield_counts = Counter(
                            item.club
                            for item in squad
                            if item.position != "GOALKEEPER"
                        )
                        if any(count > club_cap for count in outfield_counts.values()):
                            continue
                        if sum(item.reliable_anchor for item in squad) < 2:
                            continue
                        distance = sum(
                            item.player_id not in optimum.ids for item in squad
                        )
                        if distance > distance_cap:
                            continue
                        score = sum(scores[item.player_id] for item in squad)
                        expected[distance] = max(expected.get(distance, -float("inf")), score)

        self.assertEqual(set(expected), set(actual))
        for distance, expected_score in expected.items():
            self.assertAlmostEqual(
                expected_score,
                actual[distance].objective_score,
                places=10,
            )

    def test_none_returns_the_unchanged_optimum(self) -> None:
        players, scores = varied_pool()
        slots = {
            "GOALKEEPER": 3,
            "DEFENDER": 2,
            "MIDFIELDER": 2,
            "FORWARD": 2,
        }
        optimum = optimizer.optimize(players, 900, scores, 1, 900, slots)
        squad, reference, distance, target_met = optimizer.varied_squad(
            players,
            900,
            scores,
            "reliable",
            "none",
            12345,
            1,
            900,
            slots,
            set(),
        )
        self.assertEqual(optimum.ids, squad.ids)
        self.assertEqual(optimum.ids, reference.ids)
        self.assertEqual(0, distance)
        self.assertTrue(target_met)

    def test_same_club_goalkeeper_block_must_include_expected_starter(self) -> None:
        keepers = [
            player("starter", "GK Club", "GOALKEEPER", 800),
            player("backup-a", "GK Club", "GOALKEEPER", 100),
            player("backup-b", "GK Club", "GOALKEEPER", 100),
            player("backup-c", "GK Club", "GOALKEEPER", 100),
        ]
        keepers[0] = optimizer.Player(
            **{
                **keepers[0].__dict__,
                "components": {
                    **keepers[0].components,
                    "minutes": 90.0,
                    "role": 90.0,
                    "upside": 96.0,
                },
            }
        )
        scores = {
            "starter": 75.0,
            "backup-a": 76.0,
            "backup-b": 74.0,
            "backup-c": 73.0,
        }

        options = optimizer.goalkeeper_options(
            keepers,
            3,
            2000,
            scores,
            True,
        )

        self.assertTrue(options)
        self.assertTrue(
            all(
                "starter" in {item.player_id for item in combination}
                for _, combination in options.values()
            )
        )

    def test_goalkeeper_hierarchy_overrides_generic_player_score(self) -> None:
        keepers = [
            player("model-favourite", "GK Club", "GOALKEEPER", 800),
            player("actual-favourite", "GK Club", "GOALKEEPER", 700),
            player("backup", "GK Club", "GOALKEEPER", 100),
        ]
        outlooks = {
            "model-favourite": {
                "status": "challenger",
                "starter_probability": 25,
                "current_hierarchy_probability": 30,
                "confidence": "high",
                "club_rank": 2,
                "hierarchy_score": 70,
                "hierarchy_gap": 8,
                "club_price_share": 50,
                "global_price_percentile": 80,
                "external_signing_risk": 10,
            },
            "actual-favourite": {
                "status": "likely_starter",
                "starter_probability": 78,
                "current_hierarchy_probability": 86,
                "confidence": "medium",
                "club_rank": 1,
                "hierarchy_score": 78,
                "hierarchy_gap": 8,
                "club_price_share": 44,
                "global_price_percentile": 75,
                "external_signing_risk": 20,
            },
            "backup": {
                "status": "backup",
                "starter_probability": 5,
                "current_hierarchy_probability": 8,
                "confidence": "medium",
                "club_rank": 3,
                "hierarchy_score": 45,
                "hierarchy_gap": 33,
                "club_price_share": 6,
                "global_price_percentile": 10,
                "external_signing_risk": 20,
            },
        }
        keepers = [
            optimizer.Player(
                **{
                    **keeper.__dict__,
                    "goalkeeper_outlook": outlooks[keeper.player_id],
                }
            )
            for keeper in keepers
        ]
        scores = {
            "model-favourite": 99,
            "actual-favourite": 70,
            "backup": 20,
        }

        primary = optimizer.expected_primary_goalkeeper(keepers, scores)

        self.assertEqual("actual-favourite", primary.player_id)

    def test_low_maintenance_rejects_open_goalkeeper_competition(self) -> None:
        keepers = [
            player("open-one", "Open Club", "GOALKEEPER", 500),
            player("open-two", "Open Club", "GOALKEEPER", 400),
            player("open-three", "Open Club", "GOALKEEPER", 100),
        ]
        keepers = [
            optimizer.Player(
                **{
                    **keeper.__dict__,
                    "goalkeeper_outlook": {
                        "status": (
                            "open_competition"
                            if index == 1
                            else "challenger"
                        ),
                        "starter_probability": 58 if index == 1 else 25,
                        "current_hierarchy_probability": (
                            68 if index == 1 else 30
                        ),
                        "confidence": "low",
                        "club_rank": index,
                        "hierarchy_score": 70 - index,
                        "hierarchy_gap": 3 if index == 1 else 5 * index,
                        "club_price_share": 60 - 20 * index,
                        "global_price_percentile": 70 - 10 * index,
                        "external_signing_risk": 45,
                    },
                }
            )
            for index, keeper in enumerate(keepers, start=1)
        ]
        scores = {keeper.player_id: 70 for keeper in keepers}

        filtered, exclusions, block_count = (
            optimizer.filter_goalkeeper_blocks_by_hierarchy(
                keepers,
                scores,
                count=3,
                maintenance="low",
                require_hierarchy=True,
            )
        )

        self.assertEqual([], filtered)
        self.assertEqual(0, block_count)
        self.assertEqual("Player open-one", exclusions[0]["expected_primary"])

    def test_seeded_variation_is_reproducible_and_constraint_safe(self) -> None:
        players, scores = varied_pool()
        slots = {
            "GOALKEEPER": 3,
            "DEFENDER": 2,
            "MIDFIELDER": 2,
            "FORWARD": 2,
        }
        first = optimizer.varied_squad(
            players,
            900,
            scores,
            "reliable",
            "medium",
            8675309,
            1,
            900,
            slots,
            set(),
        )
        second = optimizer.varied_squad(
            players,
            900,
            scores,
            "reliable",
            "medium",
            8675309,
            1,
            900,
            slots,
            set(),
        )
        squad, optimum, distance, target_met = first
        self.assertEqual(squad.ids, second[0].ids)
        self.assertEqual(distance, second[2])
        self.assertTrue(target_met)
        self.assertEqual(5, distance)
        self.assertEqual(900, squad.cost)
        self.assertEqual(
            slots,
            Counter(item.position for item in squad.players),
        )
        goalkeeper_clubs = {
            item.club for item in squad.players if item.position == "GOALKEEPER"
        }
        self.assertEqual(1, len(goalkeeper_clubs))
        outfield_counts = Counter(
            item.club for item in squad.players if item.position != "GOALKEEPER"
        )
        self.assertLessEqual(max(outfield_counts.values()), 1)
        optimum_score = sum(scores[item.player_id] for item in optimum.players)
        squad_score = sum(scores[item.player_id] for item in squad.players)
        self.assertGreaterEqual(squad_score, optimum_score * (1.0 - 0.05 * 0.75))

    def test_multiple_seeds_create_controlled_alternatives(self) -> None:
        players, scores = varied_pool()
        slots = {
            "GOALKEEPER": 3,
            "DEFENDER": 2,
            "MIDFIELDER": 2,
            "FORWARD": 2,
        }
        squads = {
            optimizer.varied_squad(
                players,
                900,
                scores,
                "balanced",
                "medium",
                seed,
                1,
                900,
                slots,
                set(),
            )[0].ids
            for seed in range(8)
        }
        self.assertGreater(len(squads), 1)

    def test_reliable_variation_retains_protected_premium_anchor(self) -> None:
        players, scores = varied_pool()
        incumbent = next(
            item for item in players if item.player_id == "M0"
        )
        premium = optimizer.replace(
            incumbent,
            reliable_anchor=True,
            anchor_basis="explicit",
            anchor_reason="Seven stable seasons and a repeatable key role",
            proven_seasons=7,
            scorer_profile=premium_scorer_profile(),
            components={
                **incumbent.components,
                "confirmed_performance": 99.0,
                "minutes": 92.0,
                "role": 95.0,
                "stability": 86.0,
                "fitness": 90.0,
            },
        )
        players = [
            premium if item.player_id == premium.player_id else item
            for item in players
        ]
        scores[premium.player_id] = 20.0
        slots = {
            "GOALKEEPER": 3,
            "DEFENDER": 2,
            "MIDFIELDER": 2,
            "FORWARD": 2,
        }
        context = optimizer.prepare_variation_context(
            players=players,
            budget=900,
            base_scores=scores,
            profile="reliable",
            variation="medium",
            club_cap=1,
            minimum_spend=900,
            slots=slots,
            same_club_goalkeepers=True,
            min_reliable_anchors=0,
            technical_smoke=False,
        )
        protected = optimizer.protected_reliable_premium_anchor_ids(
            players,
            scores,
            context["optimum"].ids,
        )

        self.assertEqual(frozenset({premium.player_id}), protected)
        for seed in range(8):
            squad, _, _, _ = optimizer.varied_squad(
                players,
                900,
                scores,
                "reliable",
                "medium",
                seed,
                1,
                900,
                slots,
                set(),
                prepared_context=context,
                protected_ids=protected,
            )
            self.assertIn(premium.player_id, squad.ids)

    def test_strategic_pool_keeps_anchors_benchmarks_and_prospects(
        self,
    ) -> None:
        players = [
            player(
                f"pool-g{index}",
                "Pool Goalkeeper Club",
                "GOALKEEPER",
                100,
            )
            for index in range(3)
        ]
        for position, prefix in (
            ("DEFENDER", "pool-d"),
            ("MIDFIELDER", "pool-m"),
            ("FORWARD", "pool-f"),
        ):
            players.extend(
                player(
                    f"{prefix}{index}",
                    f"Pool Club {prefix}{index % 18}",
                    position,
                    100 + 100 * (index % 8),
                )
                for index in range(60)
            )
        benchmark = optimizer.replace(
            players[10],
            benchmark=True,
        )
        anchor = optimizer.replace(
            players[70],
            reliable_anchor=True,
        )
        prospect_base = players[135]
        prospect = optimizer.replace(
            prospect_base,
            cost=max(200, prospect_base.cost),
            components={
                **prospect_base.components,
                "minutes": 80,
                "role": 75,
                "fitness": 85,
            },
            risks={
                "injury": 10,
                "transfer": 10,
                "rotation": 15,
                "outlier": 10,
                "unknown_role": 15,
            },
            history_summary={
                "talent_profile": {
                    "age": 20,
                    "talent_score": 85,
                    "readiness_score": 82,
                }
            },
        )
        players = [
            (
                benchmark
                if item.player_id == benchmark.player_id
                else anchor
                if item.player_id == anchor.player_id
                else prospect
                if item.player_id == prospect.player_id
                else item
            )
            for item in players
        ]
        scores = {
            item.player_id: float(index % 40)
            for index, item in enumerate(players)
        }

        bounded = optimizer.strategic_optimization_pool(
            players,
            scores,
            {
                "GOALKEEPER": 3,
                "DEFENDER": 7,
                "MIDFIELDER": 7,
                "FORWARD": 5,
            },
        )
        bounded_ids = {item.player_id for item in bounded}

        self.assertLess(len(bounded), len(players))
        self.assertIn(benchmark.player_id, bounded_ids)
        self.assertIn(anchor.player_id, bounded_ids)
        self.assertIn(prospect.player_id, bounded_ids)
        self.assertTrue(
            all(
                item.player_id in bounded_ids
                for item in players
                if item.position == "GOALKEEPER"
            )
        )

    def test_five_member_portfolio_is_reproducible_and_balances_exposure(
        self,
    ) -> None:
        players, scores = varied_pool()
        slots = {
            "GOALKEEPER": 3,
            "DEFENDER": 2,
            "MIDFIELDER": 2,
            "FORWARD": 2,
        }

        first = optimizer.varied_portfolio(
            players=players,
            budget=900,
            base_scores=scores,
            profile="balanced",
            variation="medium",
            seed=20260724,
            club_cap=1,
            minimum_spend=900,
            slots=slots,
            avoid_exposure=Counter(),
            portfolio_size=5,
            portfolio_index=3,
        )
        second = optimizer.varied_portfolio(
            players=players,
            budget=900,
            base_scores=scores,
            profile="balanced",
            variation="medium",
            seed=20260724,
            club_cap=1,
            minimum_spend=900,
            slots=slots,
            avoid_exposure=Counter(),
            portfolio_size=5,
            portfolio_index=3,
        )

        squad, optimum, distance, target_met, audit = first
        self.assertEqual(squad.ids, second[0].ids)
        self.assertEqual(audit, second[4])
        self.assertEqual(5, audit["size"])
        self.assertEqual(3, audit["index"])
        self.assertEqual(5, audit["unique_rosters"])
        self.assertLessEqual(audit["common_player_count"], 2)
        self.assertLess(audit["max_player_exposure"], audit["size"])
        self.assertIn("common_starting_player_count", audit)
        self.assertIn("common_reliable_anchor_ids", audit)
        self.assertIn("common_benchmark_ids", audit)
        self.assertEqual(5, distance)
        self.assertTrue(target_met)
        for slot in audit["slots"]:
            self.assertEqual(5, slot["distance_from_optimum"])
            self.assertTrue(slot["variation_target_met"])

    def test_group_portfolio_uses_disjoint_league_wide_anchor_cores(
        self,
    ) -> None:
        players, scores = varied_pool()
        players = [
            item
            for item in players
            if item.position != "MIDFIELDER"
        ]
        scores = {
            player_id: score
            for player_id, score in scores.items()
            if not player_id.startswith("M")
        }
        for index in range(10):
            player_id = f"A{index}"
            anchor = player(
                player_id,
                f"Anchor Club {index}",
                "MIDFIELDER",
                100,
                reliable_anchor=True,
            )
            if index < 5:
                premium_components = dict(anchor.components)
                premium_components.update(
                    {
                        "confirmed_performance": 99.0,
                        "minutes": 90.0,
                        "role": 95.0,
                        "stability": 85.0,
                    }
                )
                anchor = optimizer.replace(
                    anchor,
                    components=premium_components,
                    proven_seasons=7,
                    scorer_profile=premium_scorer_profile(),
                )
            players.append(anchor)
            scores[player_id] = 10.0 - 0.01 * index

        _, _, _, _, audit = optimizer.varied_portfolio(
            players=players,
            budget=900,
            base_scores=scores,
            profile="balanced",
            variation="medium",
            seed=20260724,
            club_cap=1,
            minimum_spend=900,
            slots={
                "GOALKEEPER": 3,
                "DEFENDER": 2,
                "MIDFIELDER": 2,
                "FORWARD": 2,
            },
            avoid_exposure=Counter(),
            portfolio_size=5,
            portfolio_index=1,
            min_reliable_anchors=2,
            min_attacking_anchors=2,
            min_offensive_premium_anchors=1,
        )

        anchor_sets = [
            set(slot["reliable_anchor_ids"])
            for slot in audit["slots"]
        ]
        self.assertTrue(
            all(
                left.isdisjoint(right)
                for index, left in enumerate(anchor_sets)
                for right in anchor_sets[index + 1 :]
            )
        )
        self.assertEqual([], audit["common_reliable_anchor_ids"])
        self.assertEqual(1, audit["max_reliable_anchor_exposure"])
        self.assertTrue(audit["anchor_diversity_target_met"])
        self.assertEqual(
            [2, 2, 2, 2, 2],
            [len(group) for group in audit["assigned_anchor_groups"]],
        )
        by_id = {item.player_id: item for item in players}
        self.assertTrue(
            all(
                sum(
                    optimizer.is_offensive_premium_anchor(by_id[player_id])
                    for player_id in group
                )
                == 1
                for group in audit["assigned_anchor_groups"]
            )
        )

    def test_group_portfolio_rejects_too_small_anchor_pool(self) -> None:
        players, scores = varied_pool()
        anchor_count = 0
        for index, item in enumerate(players):
            if item.position == "MIDFIELDER" and anchor_count < 5:
                players[index] = optimizer.replace(
                    item,
                    reliable_anchor=True,
                    anchor_basis="explicit",
                    anchor_reason="Repeated performance and stable role",
                    proven_seasons=3,
                )
                anchor_count += 1

        with self.assertRaisesRegex(
            ValueError,
            "Broaden the league-wide anchor research",
        ):
            optimizer.varied_portfolio(
                players=players,
                budget=900,
                base_scores=scores,
                profile="balanced",
                variation="medium",
                seed=20260724,
                club_cap=1,
                minimum_spend=900,
                slots={
                    "GOALKEEPER": 3,
                    "DEFENDER": 2,
                    "MIDFIELDER": 2,
                    "FORWARD": 2,
                },
                avoid_exposure=Counter(),
                portfolio_size=5,
                portfolio_index=1,
                min_reliable_anchors=2,
            )

    def test_benchmark_flag_does_not_increase_player_score(self) -> None:
        baseline = player("m1", "Club A", "MIDFIELDER", 100)
        benchmark = optimizer.Player(
            **{**baseline.__dict__, "player_id": "m2", "benchmark": True}
        )

        scores = optimizer.score_players(
            [baseline, benchmark],
            "reliable",
            "low",
        )

        self.assertEqual(scores["m1"], scores["m2"])

    def test_avoid_rosters_count_repeated_player_exposure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.json"
            second = Path(directory) / "second.json"
            first.write_text(
                json.dumps({"squad": [{"id": "m1"}, {"id": "m2"}]}),
                encoding="utf-8",
            )
            second.write_text(
                json.dumps({"squad": [{"id": "m1"}, {"id": "m3"}]}),
                encoding="utf-8",
            )

            exposure = optimizer.load_avoid_exposure([first, second])

        self.assertEqual(2, exposure["m1"])
        self.assertEqual(1, exposure["m2"])
        self.assertEqual(1, exposure["m3"])

    def test_repeated_ordinary_player_is_rotated_inside_quality_corridor(
        self,
    ) -> None:
        players, scores = varied_pool()
        slots = {
            "GOALKEEPER": 3,
            "DEFENDER": 2,
            "MIDFIELDER": 2,
            "FORWARD": 2,
        }
        first, optimum, first_distance, _ = optimizer.varied_squad(
            players,
            900,
            scores,
            "balanced",
            "medium",
            12345,
            1,
            900,
            slots,
            set(),
        )
        repeated_id = "D2"
        self.assertIn(repeated_id, first.ids)

        rerolled, _, rerolled_distance, _ = optimizer.varied_squad(
            players,
            900,
            scores,
            "balanced",
            "medium",
            12345,
            1,
            900,
            slots,
            Counter({repeated_id: 5}),
        )

        self.assertNotIn(repeated_id, rerolled.ids)
        self.assertEqual(first_distance, rerolled_distance)
        quality_floor = sum(
            scores[item.player_id] for item in optimum.players
        ) * (1.0 - 0.05)
        self.assertGreaterEqual(
            sum(scores[item.player_id] for item in rerolled.players),
            quality_floor,
        )

    def test_unreachable_quality_distance_falls_back_inside_corridor(self) -> None:
        players, scores = varied_pool()
        slots = {
            "GOALKEEPER": 3,
            "DEFENDER": 2,
            "MIDFIELDER": 2,
            "FORWARD": 2,
        }
        for player_id in list(scores):
            suffix = player_id[-1]
            if suffix.isdigit() and int(suffix) > 1:
                scores[player_id] -= 20.0
        squad, optimum, distance, target_met = optimizer.varied_squad(
            players,
            900,
            scores,
            "reliable",
            "medium",
            99,
            1,
            900,
            slots,
            set(),
        )
        optimum_score = sum(scores[item.player_id] for item in optimum.players)
        squad_score = sum(scores[item.player_id] for item in squad.players)
        self.assertFalse(target_met)
        self.assertLess(distance, 5)
        self.assertGreaterEqual(
            squad_score,
            optimum_score * (1.0 - 0.07),
        )

    def test_seed_is_emitted_on_stderr_without_polluting_json_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            csv_path = Path(temporary_directory) / "players.csv"
            csv_path.write_text(
                "ID;Angezeigter Name;Angezeigter Name (kurz);Verein;"
                "Position;Marktwert;Punkte;Notendurchschnitt\n"
                "g;Goalkeeper;GK;Club G;GOALKEEPER;100;0;0\n"
                "d;Defender;D;Club D;DEFENDER;100;0;0\n"
                "m;Midfielder;M;Club M;MIDFIELDER;100;0;0\n"
                "f;Forward;F;Club F;FORWARD;100;0;0\n",
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--players",
                    str(csv_path),
                    "--budget",
                    "1000",
                    "--seed",
                    "424242",
                    "--shortlist-only",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        json.loads(completed.stdout)
        self.assertIn("Variation seed: 424242", completed.stderr)
        self.assertNotIn("Variation seed", completed.stdout)

    def test_automatic_variation_is_stable_private_and_rerollable(self) -> None:
        slots = {
            "GOALKEEPER": 3,
            "DEFENDER": 7,
            "MIDFIELDER": 7,
            "FORWARD": 5,
        }
        with tempfile.TemporaryDirectory() as directory:
            first_state = Path(directory) / "first" / "variation.json"
            second_state = Path(directory) / "second" / "variation.json"
            arguments = {
                "competition": "2. Bundesliga",
                "season": "2026/27",
                "profile": "reliable",
                "maintenance": "low",
                "variation": "medium",
                "budget": 10_000_000,
                "slots": slots,
            }

            first_seed, first_generation = optimizer.automatic_variation_seed(
                state_path=first_state,
                **arguments,
            )
            repeated_seed, repeated_generation = optimizer.automatic_variation_seed(
                state_path=first_state,
                **arguments,
            )
            rerolled_seed, rerolled_generation = optimizer.automatic_variation_seed(
                state_path=first_state,
                new_variant=True,
                **arguments,
            )
            colleague_seed, _ = optimizer.automatic_variation_seed(
                state_path=second_state,
                **arguments,
            )

            stored = json.loads(first_state.read_text(encoding="utf-8"))

        self.assertEqual(first_seed, repeated_seed)
        self.assertEqual((0, 0, 1), (
            first_generation,
            repeated_generation,
            rerolled_generation,
        ))
        self.assertNotEqual(first_seed, rerolled_seed)
        self.assertNotEqual(first_seed, colleague_seed)
        self.assertRegex(stored["installation_id"], r"^[0-9a-f]{48}$")
        self.assertNotIn(stored["installation_id"], str(first_seed))

    def test_malformed_automatic_variation_state_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "variation.json"
            state_path.write_text("not-json", encoding="utf-8")
            with self.assertRaises(optimizer.VariationStateError):
                optimizer.automatic_variation_seed(
                    state_path=state_path,
                    competition="3. Liga",
                    season="2026/27",
                    profile="balanced",
                    maintenance="normal",
                    variation="medium",
                    budget=10_000_000,
                    slots={
                        "GOALKEEPER": 3,
                        "DEFENDER": 7,
                        "MIDFIELDER": 7,
                        "FORWARD": 5,
                    },
                )
            self.assertEqual("not-json", state_path.read_text(encoding="utf-8"))

    def test_new_local_variant_deemphasizes_only_completed_earlier_squads(
        self,
    ) -> None:
        slots = {
            "GOALKEEPER": 3,
            "DEFENDER": 7,
            "MIDFIELDER": 7,
            "FORWARD": 5,
        }
        arguments = {
            "competition": "3. Liga",
            "season": "2026/27",
            "profile": "reliable",
            "maintenance": "low",
            "variation": "medium",
            "budget": 6_000_000,
            "slots": slots,
        }
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "variation.json"
            _, first_generation = optimizer.automatic_variation_seed(
                state_path=state_path,
                **arguments,
            )
            optimizer.record_automatic_variation_squad(
                state_path=state_path,
                generation=first_generation,
                player_ids={"repeat-a", "repeat-b"},
                **arguments,
            )
            same_generation_exposure = (
                optimizer.automatic_variation_exposure(
                    state_path=state_path,
                    generation=first_generation,
                    **arguments,
                )
            )
            _, next_generation = optimizer.automatic_variation_seed(
                state_path=state_path,
                new_variant=True,
                **arguments,
            )
            next_generation_exposure = (
                optimizer.automatic_variation_exposure(
                    state_path=state_path,
                    generation=next_generation,
                    **arguments,
                )
            )
            recent_squads = optimizer.automatic_variation_recent_squads(
                state_path=state_path,
                generation=next_generation,
                **arguments,
            )

        self.assertEqual(Counter(), same_generation_exposure)
        self.assertEqual(
            Counter({"repeat-a": 1, "repeat-b": 1}),
            next_generation_exposure,
        )
        self.assertEqual(
            [frozenset({"repeat-a", "repeat-b"})],
            recent_squads,
        )

    def test_five_installations_receive_five_controlled_synthetic_squads(self) -> None:
        players, scores = varied_pool()
        slots = {
            "GOALKEEPER": 3,
            "DEFENDER": 2,
            "MIDFIELDER": 2,
            "FORWARD": 2,
        }
        squads: set[frozenset[str]] = set()
        with tempfile.TemporaryDirectory() as directory:
            for index in range(1, 6):
                state_path = Path(directory) / f"colleague-{index}.json"
                state_path.write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "installation_id": f"{index:048x}",
                            "contexts": {},
                        }
                    ),
                    encoding="utf-8",
                )
                seed, _ = optimizer.automatic_variation_seed(
                    state_path=state_path,
                    competition="2. Bundesliga",
                    season="2026/27",
                    profile="balanced",
                    maintenance="normal",
                    variation="medium",
                    budget=900,
                    slots=slots,
                )
                squad = optimizer.varied_squad(
                    players,
                    900,
                    scores,
                    "balanced",
                    "medium",
                    seed,
                    1,
                    900,
                    slots,
                    set(),
                )[0]
                squads.add(squad.ids)

        self.assertEqual(5, len(squads))


class CentralNewsIdentityTests(unittest.TestCase):
    def test_verified_provider_identity_beats_unverified_kicker_placeholder(
        self,
    ) -> None:
        kicker_player = optimizer.replace(
            player("kicker-15", "Karlsruhe", "MIDFIELDER", 100),
            name="Marvin Wanitzek",
        )
        payload = {
            "schema_version": 1,
            "generated_at": "2026-07-24T08:00:00Z",
            "expires_at": "2026-07-25T02:00:00Z",
            "competition": "2. Bundesliga",
            "season": "2026/27",
            "providers": {"api_sports": {"status": "ok"}},
            "players": {
                "kicker-15": {
                    "name": "Marvin Wanitzek",
                    "club": "Karlsruher SC",
                    "mapping": {
                        "api_sports_player_id": None,
                        "api_sports_team_id": None,
                        "confidence": "unverified",
                    },
                    "signals": [
                        {
                            "kind": "transfer_rumour",
                            "status": "rumour",
                            "severity": 35,
                            "source_provider": "transfer_watcher",
                            "source_url": "https://example.com/transfer",
                            "observed_at": "2026-07-24T08:00:00Z",
                            "detail": "possible move",
                        }
                    ],
                    "consensus": {
                        "injury": 0,
                        "transfer": 35,
                        "rotation": 0,
                        "fitness_cap": 100,
                        "exclude": False,
                        "confidence": "low",
                        "conflicts": [],
                    },
                },
                "api_sports:101": {
                    "name": "M. Wanitzek",
                    "club": "Karlsruher SC",
                    "mapping": {
                        "api_sports_player_id": 101,
                        "api_sports_team_id": 10,
                        "confidence": "verified",
                    },
                    "signals": [],
                    "consensus": {
                        "injury": 20,
                        "transfer": 0,
                        "rotation": 0,
                        "fitness_cap": 60,
                        "exclude": False,
                        "confidence": "medium",
                        "conflicts": [],
                    },
                },
            },
        }

        updated, audit, exclusions = optimizer.apply_news_snapshot(
            [kicker_player],
            payload,
        )

        self.assertEqual([], exclusions)
        self.assertEqual(
            ["kicker-15"],
            audit["provider_mapped_player_ids"],
        )
        self.assertEqual(
            "api_sports:101",
            audit["identity_bindings"]["kicker-15"],
        )
        self.assertEqual(35, updated[0].risks["transfer"])
        self.assertEqual(20, updated[0].risks["injury"])
        self.assertEqual(60, updated[0].components["fitness"])
        self.assertTrue(
            any(
                item.get("source_provider") == "transfer_watcher"
                for item in updated[0].evidence
            )
        )

    def test_provider_roster_matches_kicker_full_name_to_initial(self) -> None:
        kicker_player = optimizer.replace(
            player("kicker-16", "Karlsruhe", "MIDFIELDER", 100),
            name="Marvin Wanitzek",
        )
        payload = {
            "schema_version": 1,
            "generated_at": "2026-07-24T08:00:00Z",
            "expires_at": "2026-07-25T02:00:00Z",
            "competition": "2. Bundesliga",
            "season": "2026/27",
            "providers": {"api_sports": {"status": "ok"}},
            "players": {
                "api_sports:101": {
                    "name": "M. Wanitzek",
                    "club": "Karlsruher SC",
                    "mapping": {
                        "api_sports_player_id": 101,
                        "api_sports_team_id": 10,
                        "confidence": "verified",
                    },
                    "signals": [],
                    "consensus": {
                        "injury": 0,
                        "transfer": 0,
                        "rotation": 0,
                        "fitness_cap": 100,
                        "exclude": False,
                        "confidence": "low",
                        "conflicts": [],
                    },
                }
            },
        }

        _, audit, exclusions = optimizer.apply_news_snapshot(
            [kicker_player],
            payload,
        )

        self.assertEqual([], exclusions)
        self.assertEqual(
            ["kicker-16"],
            audit["provider_mapped_player_ids"],
        )
        self.assertEqual(
            "api_sports:101",
            audit["identity_bindings"]["kicker-16"],
        )

    def test_provider_roster_matches_kicker_nickname_and_club_variant(self) -> None:
        kicker_player = optimizer.replace(
            player("kicker-17", "Hamburg", "MIDFIELDER", 100),
            name="Maxi Mustermann",
        )
        payload = {
            "schema_version": 1,
            "generated_at": "2026-07-24T08:00:00Z",
            "expires_at": "2026-07-25T02:00:00Z",
            "competition": "2. Bundesliga",
            "season": "2026/27",
            "providers": {"api_sports": {"status": "ok"}},
            "players": {
                "api_sports:101": {
                    "name": "Maximilian Mustermann",
                    "club": "Hamburger SV",
                    "mapping": {
                        "api_sports_player_id": 101,
                        "api_sports_team_id": 10,
                        "confidence": "verified",
                    },
                    "signals": [],
                    "consensus": {
                        "injury": 0,
                        "transfer": 0,
                        "rotation": 0,
                        "fitness_cap": 100,
                        "exclude": False,
                        "confidence": "low",
                        "conflicts": [],
                    },
                }
            },
        }

        updated, audit, exclusions = optimizer.apply_news_snapshot(
            [kicker_player],
            payload,
        )

        self.assertEqual(1, len(updated))
        self.assertEqual([], exclusions)
        self.assertEqual(
            ["kicker-17"],
            audit["provider_mapped_player_ids"],
        )
        self.assertEqual(
            "api_sports:101",
            audit["identity_bindings"]["kicker-17"],
        )

    def test_ambiguous_provider_identity_is_reported_as_conflict(self) -> None:
        kicker_player = optimizer.replace(
            player("kicker-18", "Teststadt", "DEFENDER", 100),
            name="Max Mustermann",
        )
        entry = {
            "name": "Max Mustermann",
            "club": "FC Teststadt",
            "mapping": {
                "api_sports_player_id": 101,
                "api_sports_team_id": 10,
                "confidence": "verified",
            },
            "signals": [],
            "consensus": {
                "injury": 0,
                "transfer": 0,
                "rotation": 0,
                "fitness_cap": 100,
                "exclude": False,
                "confidence": "low",
                "conflicts": [],
            },
        }
        payload = {
            "schema_version": 1,
            "generated_at": "2026-07-24T08:00:00Z",
            "expires_at": "2026-07-25T02:00:00Z",
            "competition": "2. Bundesliga",
            "season": "2026/27",
            "providers": {"api_sports": {"status": "ok"}},
            "players": {
                "api_sports:101": entry,
                "api_sports:102": {
                    **entry,
                    "mapping": {
                        **entry["mapping"],
                        "api_sports_player_id": 102,
                    },
                },
            },
        }

        _, audit, _ = optimizer.apply_news_snapshot(
            [kicker_player],
            payload,
        )

        self.assertIn("kicker-18", audit["conflicts"])
        self.assertEqual([], audit["provider_mapped_player_ids"])


class ReliableCorePolicyTests(unittest.TestCase):
    def test_restored_elite_striker_qualifies_without_name_or_top_price(
        self,
    ) -> None:
        rebound = optimizer.replace(
            player(
                "elite-rebound",
                "Rebound Club",
                "FORWARD",
                900,
                reliable_anchor=True,
                role_context={
                    "continuity": "confirmed",
                    "confidence": "high",
                    "expected_start_probability": 84,
                    "responsibilities": {
                        "offensive_focal_point": "primary",
                        "penalties": "primary",
                        "playmaker": "shared",
                    },
                },
            ),
            proven_seasons=6,
            components={
                "confirmed_performance": 89.0,
                "minutes": 86.0,
                "role": 94.0,
                "stability": 84.0,
                "context": 78.0,
                "fitness": 92.0,
                "upside": 66.0,
                "value": 45.0,
            },
            scorer_profile={
                "sample_minutes": 8_000,
                "proven_seasons": 6,
                "goals_per_90": 0.48,
                "contributions_per_90": 0.57,
            },
            form_summary={
                "latest_season_score": 62.0,
                "seasons": [
                    {"season": 2025, "score": 62.0},
                    {"season": 2024, "score": 89.0},
                    {"season": 2023, "score": 91.0},
                    {"season": 2022, "score": 88.0},
                ],
            },
        )
        current_top_price = player(
            "top-price",
            "Top Price Club",
            "FORWARD",
            1_000,
        )
        candidates = [rebound, current_top_price]
        raw_scores = {
            rebound.player_id: 82.0,
            current_top_price.player_id: 95.0,
        }

        evidence = optimizer.elite_rebound_striker_evidence(rebound)
        premium_ids = optimizer.premium_starter_candidate_ids(
            candidates,
            raw_scores,
        )

        self.assertTrue(evidence["qualified"])
        self.assertTrue(evidence["weak_latest_season"])
        self.assertGreater(
            optimizer.elite_rebound_class_adjustment(rebound),
            0.0,
        )
        self.assertIn(rebound.player_id, premium_ids)
        self.assertIn(current_top_price.player_id, premium_ids)

    def test_elite_rebound_requires_current_role_and_fitness_proof(
        self,
    ) -> None:
        unresolved = optimizer.replace(
            player(
                "unresolved-rebound",
                "Unresolved Club",
                "FORWARD",
                900,
                reliable_anchor=True,
            ),
            proven_seasons=6,
            components={
                key: value
                for key, value in {
                    "confirmed_performance": 92.0,
                    "minutes": 88.0,
                    "role": 90.0,
                    "stability": 85.0,
                    "context": 78.0,
                    "fitness": 92.0,
                    "upside": 65.0,
                    "value": 45.0,
                }.items()
            },
            scorer_profile={
                "sample_minutes": 8_000,
                "proven_seasons": 6,
                "goals_per_90": 0.48,
                "contributions_per_90": 0.57,
            },
        )

        evidence = optimizer.elite_rebound_striker_evidence(unresolved)

        self.assertFalse(evidence["qualified"])
        self.assertFalse(evidence["current_readiness_qualified"])
        self.assertEqual(
            0.0,
            optimizer.elite_rebound_class_adjustment(unresolved),
        )

    def test_reliable_low_scorer_is_not_an_offensive_premium_anchor(
        self,
    ) -> None:
        regular = optimizer.replace(
            player(
                "safe-low-scorer",
                "Safe Club",
                "MIDFIELDER",
                350,
                reliable_anchor=True,
            ),
            proven_seasons=5,
            components={
                "confirmed_performance": 100.0,
                "minutes": 89.26,
                "role": 90.86,
                "stability": 78.91,
                "context": 70.0,
                "fitness": 92.0,
                "upside": 70.0,
                "value": 64.67,
            },
            scorer_profile={
                "sample_minutes": 11_330,
                "proven_seasons": 5,
                "goals_per_90": 0.086,
                "contributions_per_90": 0.112,
            },
            role_context={
                "continuity": "confirmed",
                "responsibilities": {
                    "penalties": "none",
                    "direct_free_kicks": "none",
                    "corners": "none",
                    "playmaker": "none",
                    "offensive_focal_point": "none",
                },
            },
        )

        evidence = optimizer.offensive_premium_path_evidence(regular)

        self.assertTrue(regular.reliable_anchor)
        self.assertLess(
            optimizer.starting_scorer_leverage(regular),
            optimizer.OFFENSIVE_PREMIUM_SCORER_LEVERAGE_MINIMUM,
        )
        self.assertFalse(evidence["qualified"])
        self.assertFalse(optimizer.is_offensive_premium_anchor(regular))
        self.assertEqual(
            frozenset(),
            optimizer.protected_reliable_premium_anchor_ids(
                [regular],
                {regular.player_id: 100.0},
                {regular.player_id},
            ),
        )

    def test_repeatable_scorer_path_unlocks_offensive_premium_status(
        self,
    ) -> None:
        premium = optimizer.replace(
            player(
                "role-scorer",
                "Scoring Club",
                "MIDFIELDER",
                900,
                reliable_anchor=True,
                role_context={
                    "continuity": "confirmed",
                    "responsibilities": {
                        "direct_free_kicks": "primary",
                        "corners": "primary",
                        "playmaker": "shared",
                    },
                },
            ),
            proven_seasons=5,
            scorer_profile={
                "sample_minutes": 5_500,
                "proven_seasons": 5,
                "goals_per_90": 0.15,
                "contributions_per_90": 0.31,
            },
            components={
                key: value
                for key, value in {
                    "confirmed_performance": 98.0,
                    "minutes": 90.0,
                    "role": 94.0,
                    "stability": 84.0,
                    "context": 80.0,
                    "fitness": 88.0,
                    "upside": 72.0,
                    "value": 76.0,
                }.items()
            },
        )

        evidence = optimizer.offensive_premium_path_evidence(premium)

        self.assertTrue(evidence["qualified"])
        self.assertGreaterEqual(
            evidence["scorer_leverage"],
            optimizer.OFFENSIVE_PREMIUM_SCORER_LEVERAGE_MINIMUM,
        )
        self.assertTrue(optimizer.is_offensive_premium_anchor(premium))

    def test_protected_premium_anchor_is_evidence_and_percentile_based(
        self,
    ) -> None:
        candidates = [
            player(
                f"candidate-{index}",
                f"Candidate Club {index}",
                "MIDFIELDER",
                500,
            )
            for index in range(10)
        ]
        elite = optimizer.replace(
            candidates[0],
            player_id="elite",
            name="Elite",
            short_name="Elite",
            reliable_anchor=True,
            anchor_basis="explicit",
            anchor_reason="Repeatable elite role",
            proven_seasons=7,
            scorer_profile=premium_scorer_profile(),
            components={
                **candidates[0].components,
                "confirmed_performance": 99.0,
                "minutes": 92.0,
                "role": 95.0,
                "stability": 86.0,
                "fitness": 90.0,
            },
        )
        candidates[0] = elite
        scores = {
            candidate.player_id: 80.0 + index
            for index, candidate in enumerate(candidates)
        }
        scores[elite.player_id] = 100.0

        protected = optimizer.protected_reliable_premium_anchor_ids(
            candidates,
            scores,
            {elite.player_id},
        )
        benchmark_clone = optimizer.replace(
            elite,
            player_id="benchmark-only",
            benchmark=True,
            proven_seasons=3,
        )
        benchmark_only = optimizer.protected_reliable_premium_anchor_ids(
            [*candidates, benchmark_clone],
            {**scores, benchmark_clone.player_id: 100.0},
            {benchmark_clone.player_id},
        )

        self.assertEqual(frozenset({elite.player_id}), protected)
        self.assertEqual(frozenset(), benchmark_only)

    def test_equivalent_premium_anchor_is_exchangeable(self) -> None:
        original = player(
            "premium-original",
            "Original Club",
            "MIDFIELDER",
            1000,
            reliable_anchor=True,
        )
        equivalent = optimizer.replace(
            original,
            player_id="premium-equivalent",
            name="Equivalent",
            short_name="Equivalent",
            club="Equivalent Club",
        )
        players = [
            optimizer.replace(
                original,
                components={
                    **original.components,
                    "confirmed_performance": 99.0,
                    "minutes": 92.0,
                    "role": 95.0,
                    "stability": 86.0,
                    "fitness": 90.0,
                },
                proven_seasons=7,
                scorer_profile=premium_scorer_profile(),
                anchor_basis="explicit",
                anchor_reason="Stable elite role",
            ),
            optimizer.replace(
                equivalent,
                components={
                    **equivalent.components,
                    "confirmed_performance": 97.0,
                    "minutes": 90.0,
                    "role": 93.0,
                    "stability": 84.0,
                    "fitness": 88.0,
                },
                proven_seasons=6,
                scorer_profile=premium_scorer_profile(),
                anchor_basis="explicit",
                anchor_reason="Equivalent stable elite role",
            ),
        ]
        scores = {
            "premium-original": 100.0,
            "premium-equivalent": 98.0,
        }

        protected = optimizer.protected_reliable_premium_anchor_ids(
            players,
            scores,
            {"premium-original"},
        )

        self.assertEqual(frozenset(), protected)

    def test_finalized_objective_uses_joint_architecture_scale(self) -> None:
        item = player("objective", "Objective Club", "MIDFIELDER", 100)
        squad = optimizer.Squad(
            [item],
            0.0,
            architecture_diagnostics={"architecture_objective": 123.5},
        )

        objective, valid = optimizer.finalized_squad_objective(
            squad,
            [item],
            {item.player_id: 999.0},
            {item.player_id: 50.0},
            SimpleNamespace(min_core_budget_share=0.0),
        )

        self.assertTrue(valid)
        self.assertEqual(123.5, objective)

    def test_architecture_legality_preserves_required_player(self) -> None:
        required = player("required", "Required Club", "MIDFIELDER", 100)
        other = player("other", "Other Club", "FORWARD", 100)

        self.assertTrue(
            optimizer._architecture_candidate_is_legal(
                [required, other],
                budget=200,
                club_cap=1,
                min_reliable_anchors=0,
                required_player_ids={required.player_id},
            )
        )
        self.assertFalse(
            optimizer._architecture_candidate_is_legal(
                [other],
                budget=100,
                club_cap=1,
                min_reliable_anchors=0,
                required_player_ids={required.player_id},
            )
        )

    def test_core_weighting_uses_evidence_not_benchmark_flag(self) -> None:
        regular_anchor = player(
            "anchor",
            "Anchor Club",
            "MIDFIELDER",
            500,
            reliable_anchor=True,
        )
        premium_anchor = optimizer.Player(
            **{
                **player(
                    "premium",
                    "Premium Club",
                    "MIDFIELDER",
                    1000,
                    reliable_anchor=True,
                ).__dict__,
                "proven_seasons": 7,
                "scorer_profile": premium_scorer_profile(),
                "components": {
                    **player(
                        "premium-components",
                        "Premium Club",
                        "MIDFIELDER",
                        1000,
                    ).components,
                    "confirmed_performance": 99.0,
                    "role": 94.0,
                    "stability": 85.0,
                },
            }
        )
        benchmark_clone = optimizer.Player(
            **{**premium_anchor.__dict__, "player_id": "premium-benchmark", "benchmark": True}
        )
        contender = player(
            "contender",
            "Contender Club",
            "MIDFIELDER",
            600,
        )
        players = [regular_anchor, premium_anchor, benchmark_clone, contender]
        raw_scores = {
            regular_anchor.player_id: 70.0,
            premium_anchor.player_id: 95.0,
            benchmark_clone.player_id: 95.0,
            contender.player_id: 90.0,
        }

        weighted, multipliers = optimizer.core_weighted_scores(
            players,
            raw_scores,
            "reliable",
            "low",
        )

        self.assertLess(multipliers[regular_anchor.player_id], 0.95)
        self.assertGreaterEqual(multipliers[premium_anchor.player_id], 0.95)
        self.assertGreater(
            weighted[premium_anchor.player_id],
            raw_scores[premium_anchor.player_id],
        )
        self.assertEqual(
            weighted[premium_anchor.player_id],
            weighted[benchmark_clone.player_id],
        )

    def test_expensive_anchor_reserves_are_repaired_with_safe_value_depth(
        self,
    ) -> None:
        squad_players: list[optimizer.Player] = []
        scores: dict[str, float] = {}
        for position, prefix, count in (
            ("GOALKEEPER", "G", 3),
            ("DEFENDER", "D", 7),
            ("MIDFIELDER", "M", 7),
            ("FORWARD", "F", 5),
        ):
            for index in range(count):
                player_id = f"{prefix}{index}"
                is_anchor = position != "GOALKEEPER"
                cost = (
                    100
                    if position == "GOALKEEPER"
                    else (500 if is_anchor else (400 if index < 5 else 300))
                )
                squad_players.append(
                    player(
                        player_id,
                        f"Club {player_id}",
                        position,
                        cost,
                        reliable_anchor=is_anchor,
                    )
                )
                scores[player_id] = 100.0 - index
        candidates = list(squad_players)
        for position, prefix in (
            ("DEFENDER", "VD"),
            ("MIDFIELDER", "VM"),
            ("FORWARD", "VF"),
        ):
            for index in range(4):
                player_id = f"{prefix}{index}"
                candidates.append(
                    player(
                        player_id,
                        f"Value Club {player_id}",
                        position,
                        50,
                    )
                )
                scores[player_id] = 20.0 - index
        squad = optimizer.Squad(
            squad_players,
            sum(scores[item.player_id] for item in squad_players),
        )

        repaired = optimizer.repair_core_budget_share(
            squad,
            candidates,
            scores,
            scores,
            club_cap=3,
            min_reliable_anchors=4,
            min_attacking_anchors=3,
            min_core_budget_share=0.70,
            quality_floor=float("-inf"),
        )

        self.assertIsNotNone(repaired)
        audit = optimizer.reliable_core_audit(
            repaired,
            scores,
            4,
            3,
            0.70,
        )
        self.assertTrue(audit["passes"])
        self.assertLess(repaired.cost, squad.cost)

        protected = optimizer.repair_core_budget_share(
            squad,
            candidates,
            scores,
            scores,
            club_cap=3,
            min_reliable_anchors=4,
            min_attacking_anchors=3,
            min_core_budget_share=0.70,
            quality_floor=float("-inf"),
            minimum_spend=squad.cost,
        )

        self.assertIsNone(protected)

    def test_core_audit_rejects_equal_value_bench_and_accepts_star_heavy_core(
        self,
    ) -> None:
        anchor_ids = {"d0", "m0", "m1", "f0"}
        rich_core: list[optimizer.Player] = [
            player(f"g{index}", "Goalkeeper Club", "GOALKEEPER", 100)
            for index in range(3)
        ]
        for position, prefix, count, starters, starter_cost in (
            ("DEFENDER", "d", 7, 3, 600),
            ("MIDFIELDER", "m", 7, 4, 800),
            ("FORWARD", "f", 5, 3, 900),
        ):
            for index in range(count):
                rich_core.append(
                    player(
                        f"{prefix}{index}",
                        f"{prefix.upper()} Club {index}",
                        position,
                        starter_cost if index < starters else 50,
                        reliable_anchor=f"{prefix}{index}" in anchor_ids,
                    )
                )
        scores = {
            item.player_id: 100.0 - index
            for index, item in enumerate(rich_core)
        }
        strong = optimizer.reliable_core_audit(
            optimizer.Squad(rich_core, 0.0),
            scores,
            min_reliable_anchors=4,
            min_attacking_anchors=3,
            min_core_budget_share=0.70,
        )
        flat_players = [
            optimizer.replace(item, cost=100) for item in rich_core
        ]
        flat = optimizer.reliable_core_audit(
            optimizer.Squad(flat_players, 0.0),
            scores,
            min_reliable_anchors=4,
            min_attacking_anchors=3,
            min_core_budget_share=0.70,
        )

        self.assertTrue(strong["passes"])
        self.assertGreaterEqual(strong["core_budget_share"], 0.70)
        self.assertEqual(3, strong["attacking_anchors"])
        self.assertFalse(flat["passes"])
        self.assertAlmostEqual(0.5, flat["core_budget_share"])

    def test_remaining_budget_upgrades_the_starting_core(self) -> None:
        squad_players: list[optimizer.Player] = [
            player(f"g{index}", "Goalkeeper Club", "GOALKEEPER", 100)
            for index in range(3)
        ]
        for position, prefix, count in (
            ("DEFENDER", "d", 7),
            ("MIDFIELDER", "m", 7),
            ("FORWARD", "f", 5),
        ):
            for index in range(count):
                squad_players.append(
                    player(
                        f"{prefix}{index}",
                        f"{prefix.upper()} Club {index}",
                        position,
                        400 if index < 4 else 50,
                        reliable_anchor=index < 4,
                    )
                )
        scores = {
            item.player_id: 100.0 - index
            for index, item in enumerate(squad_players)
        }
        squad = optimizer.Squad(
            squad_players,
            sum(scores[item.player_id] for item in squad_players),
        )
        audit = optimizer.reliable_core_audit(squad, scores, 4, 3, 0.70)
        incumbent = next(
            item
            for item in squad_players
            if item.player_id in audit["player_ids"]
            and item.position == "MIDFIELDER"
        )
        premium = optimizer.replace(
            incumbent,
            player_id="premium-midfielder",
            name="Premium Midfielder",
            short_name="Premium",
            club="Premium Club",
            cost=incumbent.cost + 300,
        )
        scores[premium.player_id] = scores[incumbent.player_id] + 10.0

        upgraded = optimizer.upgrade_core_with_remaining_budget(
            squad,
            [*squad_players, premium],
            scores,
            scores,
            budget=squad.cost + 300,
            club_cap=4,
            min_reliable_anchors=4,
            min_attacking_anchors=3,
            min_core_budget_share=0.70,
        )

        self.assertIn(premium.player_id, upgraded.ids)
        self.assertEqual(len(squad.players), len(upgraded.players))
        self.assertEqual(1, len(squad.ids - upgraded.ids))
        self.assertEqual(squad.cost + 300, upgraded.cost)

    def test_full_budget_rebalance_pairs_bench_saving_with_core_upgrade(
        self,
    ) -> None:
        squad_players: list[optimizer.Player] = [
            player(f"g{index}", "Goalkeeper Club", "GOALKEEPER", 100)
            for index in range(3)
        ]
        scores = {
            item.player_id: 200.0 - index
            for index, item in enumerate(squad_players)
        }
        for position, prefix, count, starters in (
            ("DEFENDER", "d", 7, 4),
            ("MIDFIELDER", "m", 7, 4),
            ("FORWARD", "f", 5, 2),
        ):
            for index in range(count):
                item = player(
                    f"{prefix}{index}",
                    f"Club {prefix}{index}",
                    position,
                    400 if index < starters else 300,
                )
                squad_players.append(item)
                scores[item.player_id] = (
                    150.0 - index
                    if index < starters
                    else 20.0 - index
                )
        squad = optimizer.Squad(
            squad_players,
            sum(scores[item.player_id] for item in squad_players),
        )
        cheap_reserve = player(
            "cheap-d",
            "Cheap Club",
            "DEFENDER",
            100,
        )
        premium_forward = player(
            "premium-f",
            "Premium Club",
            "FORWARD",
            600,
        )
        scores[cheap_reserve.player_id] = 1.0
        scores[premium_forward.player_id] = scores["f0"] + 20.0
        before = optimizer.reliable_core_audit(
            squad,
            scores,
            0,
            0,
            0.50,
        )

        rebalanced = optimizer.rebalance_full_budget_core(
            squad,
            [*squad_players, cheap_reserve, premium_forward],
            scores,
            scores,
            budget=squad.cost,
            club_cap=4,
            min_reliable_anchors=0,
            min_attacking_anchors=0,
            min_core_budget_share=0.50,
            target_core_budget_share=0.65,
            quality_floor=float("-inf"),
        )
        after = optimizer.reliable_core_audit(
            rebalanced,
            scores,
            0,
            0,
            0.50,
        )

        self.assertEqual(squad.cost, rebalanced.cost)
        self.assertIn(cheap_reserve.player_id, rebalanced.ids)
        self.assertIn(premium_forward.player_id, rebalanced.ids)
        self.assertGreater(
            after["core_budget_share"],
            before["core_budget_share"],
        )

    def test_joint_architecture_values_positions_and_moves_budget_to_core(
        self,
    ) -> None:
        squad_players: list[optimizer.Player] = [
            player(f"g{index}", "Goalkeeper Club", "GOALKEEPER", 100)
            for index in range(3)
        ]
        scores = {
            item.player_id: 200.0 - index
            for index, item in enumerate(squad_players)
        }
        for position, prefix, count, starters in (
            ("DEFENDER", "d", 7, 4),
            ("MIDFIELDER", "m", 7, 4),
            ("FORWARD", "f", 5, 2),
        ):
            for index in range(count):
                item = player(
                    f"{prefix}{index}",
                    f"Club {prefix}{index}",
                    position,
                    400 if index < starters else 300,
                )
                squad_players.append(item)
                scores[item.player_id] = (
                    150.0 - index
                    if index < starters
                    else 20.0 - index
                )
        squad = optimizer.Squad(
            squad_players,
            sum(scores[item.player_id] for item in squad_players),
        )
        cheap_reserve = player(
            "cheap-d-joint",
            "Cheap Joint Club",
            "DEFENDER",
            100,
        )
        premium_forward = player(
            "premium-f-joint",
            "Premium Joint Club",
            "FORWARD",
            600,
        )
        scores[cheap_reserve.player_id] = 1.0
        scores[premium_forward.player_id] = scores["f0"] + 20.0
        before = optimizer.squad_architecture_metrics(
            squad,
            scores,
            maintenance="low",
            min_reliable_anchors=0,
            min_attacking_anchors=0,
            min_core_budget_share=0.50,
            target_core_budget_share=0.65,
        )

        optimized = optimizer.optimize_joint_squad_architecture(
            squad,
            [*squad_players, cheap_reserve, premium_forward],
            scores,
            scores,
            budget=squad.cost,
            club_cap=4,
            maintenance="low",
            min_reliable_anchors=0,
            min_attacking_anchors=0,
            min_core_budget_share=0.50,
            target_core_budget_share=0.65,
        )
        after = optimizer.squad_architecture_metrics(
            optimized,
            scores,
            maintenance="low",
            min_reliable_anchors=0,
            min_attacking_anchors=0,
            min_core_budget_share=0.50,
            target_core_budget_share=0.65,
        )

        self.assertEqual(squad.cost, optimized.cost)
        self.assertIn(cheap_reserve.player_id, optimized.ids)
        self.assertIn(premium_forward.player_id, optimized.ids)
        self.assertGreater(
            after["architecture_objective"],
            before["architecture_objective"],
        )
        self.assertGreater(
            after["core_budget_share"],
            before["core_budget_share"],
        )
        self.assertGreater(
            after["bench_usage_weights"]["DEFENDER"],
            after["bench_usage_weights"]["FORWARD"],
        )
        self.assertEqual(
            "joint-xi-bench-v15-package-gates",
            optimized.architecture_diagnostics["model_version"],
        )
        self.assertGreater(
            optimized.architecture_diagnostics["evaluated_rosters"],
            1,
        )
        self.assertIn(
            "triple_swap_rosters_evaluated",
            optimized.architecture_diagnostics,
        )
        self.assertIn(
            "four_swap_rosters_evaluated",
            optimized.architecture_diagnostics,
        )
        self.assertIn(
            "cross_position_pair_rosters_evaluated",
            optimized.architecture_diagnostics,
        )
        self.assertGreaterEqual(
            optimized.architecture_diagnostics[
                "architecture_metric_cache_hits"
            ],
            0,
        )
        self.assertTrue(
            optimized.architecture_diagnostics[
                "marginal_reallocation_audit"
            ]["search_complete"]
        )
        self.assertFalse(
            optimized.architecture_diagnostics[
                "marginal_reallocation_audit"
            ]["dominated_final_roster"]
        )

    def test_reference_architecture_restarts_from_equivalent_premium_anchor(
        self,
    ) -> None:
        incumbent = optimizer.replace(
            player(
                "premium-incumbent",
                "Incumbent Club",
                "FORWARD",
                1000,
                reliable_anchor=True,
            ),
            proven_seasons=7,
            scorer_profile=premium_scorer_profile(),
            components={
                key: 95.0 for key in optimizer.COMPONENTS
            },
        )
        challenger = optimizer.replace(
            incumbent,
            player_id="premium-challenger",
            name="Premium Challenger",
            short_name="Challenger",
            club="Challenger Club",
        )
        scores = {
            incumbent.player_id: 100.0,
            challenger.player_id: 98.0,
        }
        initial = optimizer.Squad([incumbent], 100.0)

        def local_optimum(
            seed: optimizer.Squad,
            *_: object,
            **__: object,
        ) -> optimizer.Squad:
            objective = (
                120.0
                if challenger.player_id in seed.ids
                else 110.0
            )
            return optimizer.Squad(
                list(seed.players),
                seed.objective_score,
                architecture_diagnostics={
                    "architecture_objective": objective,
                },
            )

        with mock.patch.object(
            optimizer,
            "optimize_joint_squad_architecture",
            side_effect=local_optimum,
        ) as joint_optimizer:
            result = optimizer.finalize_reliable_core_architecture(
                initial,
                [incumbent, challenger],
                scores,
                scores,
                budget=1000,
                club_cap=1,
                min_reliable_anchors=1,
                min_attacking_anchors=1,
                min_core_budget_share=0.0,
                target_core_budget_share=0.0,
                search_premium_restarts=True,
            )

        self.assertIn(challenger.player_id, result.ids)
        self.assertEqual(2, joint_optimizer.call_count)
        self.assertEqual(
            1,
            result.architecture_diagnostics[
                "premium_restarts_evaluated"
            ],
        )

    def test_joint_architecture_places_qualified_potential_in_extended_core(
        self,
    ) -> None:
        squad_players: list[optimizer.Player] = []
        scores: dict[str, float] = {}
        for position, prefix, count in (
            ("GOALKEEPER", "pg", 3),
            ("DEFENDER", "pd", 7),
            ("MIDFIELDER", "pm", 7),
            ("FORWARD", "pf", 5),
        ):
            for index in range(count):
                cost = (
                    200
                    if position == "MIDFIELDER" and index == 0
                    else 100
                )
                item = player(
                    f"{prefix}{index}",
                    (
                        "Potential Goalkeeper Club"
                        if position == "GOALKEEPER"
                        else f"Potential Club {prefix}{index}"
                    ),
                    position,
                    cost,
                )
                squad_players.append(item)
                scores[item.player_id] = 80.0 - index
        prospect_base = player(
            "qualified-prospect",
            "Prospect Club",
            "MIDFIELDER",
            200,
        )
        prospect = optimizer.replace(
            prospect_base,
            components={
                **prospect_base.components,
                "minutes": 82.0,
                "role": 78.0,
                "fitness": 84.0,
            },
            risks={
                "injury": 10.0,
                "transfer": 10.0,
                "rotation": 15.0,
                "outlier": 10.0,
                "unknown_role": 12.0,
            },
            history_summary={
                "talent_profile": {
                    "age": 20,
                    "talent_score": 86.0,
                    "readiness_score": 84.0,
                }
            },
        )
        scores[prospect.player_id] = 90.0
        squad = optimizer.Squad(
            squad_players,
            sum(scores[item.player_id] for item in squad_players),
        )

        optimized = optimizer.optimize_joint_squad_architecture(
            squad,
            [*squad_players, prospect],
            scores,
            scores,
            budget=squad.cost,
            club_cap=4,
            maintenance="low",
            min_reliable_anchors=0,
            min_attacking_anchors=0,
            min_core_budget_share=0.0,
            target_core_budget_share=0.0,
            min_qualified_potential_core=1,
            target_qualified_potential_core=1,
        )

        self.assertIn(prospect.player_id, optimized.ids)
        self.assertTrue(
            optimized.architecture_diagnostics[
                "qualified_potential_core_minimum_met"
            ]
        )
        self.assertEqual(
            [prospect.player_id],
            optimized.architecture_diagnostics[
                "qualified_potential_core_ids"
            ],
        )
        self.assertIn(
            prospect.player_id,
            optimized.architecture_diagnostics["player_ids"],
        )
        self.assertTrue(
            optimized.architecture_diagnostics[
                "qualified_potential_starter_minimum_met"
            ]
        )
        self.assertEqual(
            [prospect.player_id],
            optimized.architecture_diagnostics[
                "qualified_potential_starter_ids"
            ],
        )

    def test_forward_budget_prefers_top_three_over_equal_five(self) -> None:
        flat_players: list[optimizer.Player] = []
        scores: dict[str, float] = {}
        for position, prefix, count, base_score in (
            ("GOALKEEPER", "g", 3, 70.0),
            ("DEFENDER", "d", 7, 80.0),
            ("MIDFIELDER", "m", 7, 90.0),
        ):
            for index in range(count):
                item = player(
                    f"{prefix}{index}",
                    (
                        "Goalkeeper Club"
                        if position == "GOALKEEPER"
                        else f"Club {prefix}{index}"
                    ),
                    position,
                    100,
                )
                flat_players.append(item)
                scores[item.player_id] = base_score - index
        for index, score in enumerate((100.0, 99.0, 98.0, 90.0, 89.0)):
            item = player(
                f"f{index}",
                f"Club f{index}",
                "FORWARD",
                300,
            )
            flat_players.append(item)
            scores[item.player_id] = score

        flat_squad = optimizer.Squad(flat_players, 0.0)
        concentrated_squad = optimizer.Squad(
            [
                (
                    optimizer.replace(item, cost=550)
                    if item.player_id == "f0"
                    else (
                        optimizer.replace(item, cost=50)
                        if item.player_id == "f4"
                        else item
                    )
                )
                for item in flat_players
            ],
            0.0,
        )
        flat = optimizer.squad_architecture_metrics(
            flat_squad,
            scores,
            maintenance="low",
            min_reliable_anchors=0,
            min_attacking_anchors=0,
            min_core_budget_share=0.50,
            target_core_budget_share=0.80,
        )
        concentrated = optimizer.squad_architecture_metrics(
            concentrated_squad,
            scores,
            maintenance="low",
            min_reliable_anchors=0,
            min_attacking_anchors=0,
            min_core_budget_share=0.50,
            target_core_budget_share=0.80,
        )

        self.assertAlmostEqual(0.60, flat["forward_core_budget_share"])
        self.assertFalse(flat["forward_core_budget_target_met"])
        self.assertGreaterEqual(
            concentrated["forward_core_budget_share"],
            0.75,
        )
        self.assertTrue(concentrated["forward_core_budget_target_met"])
        self.assertEqual(
            0.18,
            flat["player_usage_weights"]["f3"],
        )
        self.assertEqual(
            0.05,
            flat["player_usage_weights"]["f4"],
        )
        self.assertGreater(
            concentrated["architecture_objective"],
            flat["architecture_objective"],
        )

    def test_formation_flexibility_credits_only_legal_alternative_starters(
        self,
    ) -> None:
        players: list[optimizer.Player] = []
        scores: dict[str, float] = {}
        for index, score in enumerate((100.0, 99.0, 98.0)):
            item = player(
                f"flex-g{index}",
                "Flex Goalkeeper Club",
                "GOALKEEPER",
                100,
            )
            players.append(item)
            scores[item.player_id] = score
        for position, prefix, values in (
            (
                "DEFENDER",
                "flex-d",
                (100.0, 99.0, 98.0, 93.0, 20.0, 19.0, 18.0),
            ),
            (
                "MIDFIELDER",
                "flex-m",
                (100.0, 99.0, 98.0, 97.0, 20.0, 19.0, 18.0),
            ),
            (
                "FORWARD",
                "flex-f",
                (110.0, 109.0, 108.0, 90.0, 80.0),
            ),
        ):
            for index, score in enumerate(values):
                item = player(
                    f"{prefix}{index}",
                    f"Flex Club {prefix}{index}",
                    position,
                    100,
                )
                players.append(item)
                scores[item.player_id] = score
        formation, core_ids = optimizer.best_starting_lineup(
            players,
            scores,
        )

        audit = optimizer.formation_flexibility_audit(
            optimizer.Squad(players, 0.0),
            scores,
            scores,
            core_ids,
        )

        self.assertEqual("3-4-3", formation)
        self.assertIn("flex-d3", audit["eligible_player_ids"])
        self.assertNotIn("flex-f3", audit["eligible_player_ids"])
        self.assertGreater(audit["adjustment"], 0.0)

    def test_expensive_fourth_forward_must_beat_cross_position_upgrade(
        self,
    ) -> None:
        selected: list[optimizer.Player] = []
        scores: dict[str, float] = {}
        for index, score in enumerate((100.0, 99.0, 98.0)):
            item = player(
                f"gate-g{index}",
                "Gate Goalkeeper Club",
                "GOALKEEPER",
                100,
            )
            selected.append(item)
            scores[item.player_id] = score
        for position, prefix, values, starter_cost in (
            (
                "DEFENDER",
                "gate-d",
                (95.0, 94.0, 93.0, 40.0, 39.0, 38.0, 37.0),
                200,
            ),
            (
                "MIDFIELDER",
                "gate-m",
                (95.0, 94.0, 93.0, 92.0, 30.0, 29.0, 28.0),
                200,
            ),
        ):
            for index, score in enumerate(values):
                item = player(
                    f"{prefix}{index}",
                    f"Gate Club {prefix}{index}",
                    position,
                    starter_cost if index < 3 else 50,
                )
                selected.append(item)
                scores[item.player_id] = score
        for index, (cost, score) in enumerate(
            (
                (300, 105.0),
                (300, 104.0),
                (300, 103.0),
                (300, 80.0),
                (50, 30.0),
            )
        ):
            item = player(
                f"gate-f{index}",
                f"Gate Club f{index}",
                "FORWARD",
                cost,
            )
            selected.append(item)
            scores[item.player_id] = score
        cheap_forward = player(
            "gate-f-cheap",
            "Gate Cheap Forward Club",
            "FORWARD",
            50,
        )
        upgraded_midfielder = player(
            "gate-m-upgrade",
            "Gate Midfielder Upgrade Club",
            "MIDFIELDER",
            300,
        )
        scores[cheap_forward.player_id] = 20.0
        scores[upgraded_midfielder.player_id] = 120.0
        squad = optimizer.Squad(
            selected,
            sum(scores[item.player_id] for item in selected),
        )

        optimized = optimizer.optimize_joint_squad_architecture(
            squad,
            [*selected, cheap_forward, upgraded_midfielder],
            scores,
            scores,
            budget=squad.cost,
            club_cap=4,
            maintenance="low",
            min_reliable_anchors=0,
            min_attacking_anchors=0,
            min_core_budget_share=0.50,
            target_core_budget_share=0.65,
        )

        self.assertNotIn("gate-f3", optimized.ids)
        self.assertIn(cheap_forward.player_id, optimized.ids)
        self.assertIn(upgraded_midfielder.player_id, optimized.ids)
        self.assertGreater(
            optimized.architecture_diagnostics[
                "expensive_fourth_forward_counterfactuals_evaluated"
            ],
            0,
        )
        self.assertTrue(
            optimized.architecture_diagnostics[
                "expensive_fourth_forward_justified"
            ]
        )

    def test_forward_package_search_escapes_two_swap_price_grid(self) -> None:
        candidates: list[optimizer.Player] = []
        scores: dict[str, float] = {}
        for index, (cost, score) in enumerate(
            (
                (350, 100.0),
                (350, 99.0),
                (350, 98.0),
                (350, 90.0),
                (250, 89.0),
                (450, 108.0),
                (450, 107.0),
                (250, 60.0),
                (150, 40.0),
                (50, 20.0),
            )
        ):
            item = player(
                f"package-f{index}",
                f"Package Club {index}",
                "FORWARD",
                cost,
            )
            candidates.append(item)
            scores[item.player_id] = score

        packages = optimizer.forward_roster_packages(
            candidates,
            scores,
            count=5,
            total_cost=1650,
            maintenance="low",
            limit=20,
        )

        self.assertTrue(packages)
        best = packages[0]
        likely_starters = sorted(
            best,
            key=lambda item: -scores[item.player_id],
        )[:3]
        self.assertGreaterEqual(
            sum(item.cost for item in likely_starters)
            / sum(item.cost for item in best),
            0.75,
        )

    def test_midfield_budget_prefers_core_over_equal_seven(self) -> None:
        flat_players: list[optimizer.Player] = []
        scores: dict[str, float] = {}
        for position, prefix, count, base_score in (
            ("GOALKEEPER", "mg", 3, 70.0),
            ("DEFENDER", "md", 7, 80.0),
            ("FORWARD", "mf", 5, 100.0),
        ):
            for index in range(count):
                item = player(
                    f"{prefix}{index}",
                    (
                        "Midfield Goalkeeper Club"
                        if position == "GOALKEEPER"
                        else f"Midfield Club {prefix}{index}"
                    ),
                    position,
                    100,
                )
                flat_players.append(item)
                scores[item.player_id] = base_score - index
        for index, score in enumerate(
            (110.0, 109.0, 108.0, 107.0, 90.0, 89.0, 88.0)
        ):
            item = player(
                f"mm{index}",
                f"Midfield Club {index}",
                "MIDFIELDER",
                300,
            )
            flat_players.append(item)
            scores[item.player_id] = score

        flat_squad = optimizer.Squad(flat_players, 0.0)
        concentrated_costs = {
            "mm0": 500,
            "mm1": 500,
            "mm2": 400,
            "mm3": 400,
            "mm4": 100,
            "mm5": 100,
            "mm6": 100,
        }
        concentrated_squad = optimizer.Squad(
            [
                optimizer.replace(
                    item,
                    cost=concentrated_costs[item.player_id],
                )
                if item.position == "MIDFIELDER"
                else item
                for item in flat_players
            ],
            0.0,
        )
        flat = optimizer.squad_architecture_metrics(
            flat_squad,
            scores,
            maintenance="low",
            min_reliable_anchors=0,
            min_attacking_anchors=0,
            min_core_budget_share=0.50,
            target_core_budget_share=0.65,
        )
        concentrated = optimizer.squad_architecture_metrics(
            concentrated_squad,
            scores,
            maintenance="low",
            min_reliable_anchors=0,
            min_attacking_anchors=0,
            min_core_budget_share=0.50,
            target_core_budget_share=0.65,
        )

        self.assertLess(flat["midfield_core_budget_share"], 0.80)
        self.assertFalse(flat["midfield_core_budget_target_met"])
        self.assertGreaterEqual(
            concentrated["midfield_core_budget_share"],
            0.80,
        )
        self.assertTrue(concentrated["midfield_core_budget_target_met"])
        self.assertEqual(0.22, flat["player_usage_weights"]["mm4"])
        self.assertEqual(0.12, flat["player_usage_weights"]["mm5"])
        self.assertEqual(0.06, flat["player_usage_weights"]["mm6"])
        self.assertGreater(
            concentrated["architecture_objective"],
            flat["architecture_objective"],
        )

    def test_low_maintenance_rejects_two_ordinary_expensive_midfield_reserves(
        self,
    ) -> None:
        midfielders = [
            player(
                f"bank-m{index}",
                f"Bank Midfield Club {index}",
                "MIDFIELDER",
                cost,
            )
            for index, cost in enumerate(
                (500, 450, 400, 350, 250, 200, 50)
            )
        ]
        squad = optimizer.Squad(midfielders, 0.0)
        core_ids = {
            player.player_id for player in midfielders[:4]
        }

        audit = optimizer.midfield_architecture_audit(
            squad,
            core_ids,
            maintenance="low",
            enforce=True,
            position_minimum_costs={"MIDFIELDER": 50},
            floor_available_count=10,
        )

        self.assertFalse(audit["passes"])
        self.assertEqual(1, audit["expensive_ordinary_reserve_excess"])
        self.assertEqual(
            ["bank-m4", "bank-m5"],
            audit["expensive_ordinary_reserve_ids"],
        )

    def test_qualified_potential_can_be_second_valuable_midfield_reserve(
        self,
    ) -> None:
        midfielders = [
            player(
                f"talent-bank-m{index}",
                f"Talent Midfield Club {index}",
                "MIDFIELDER",
                cost,
            )
            for index, cost in enumerate(
                (500, 450, 400, 350, 250, 200, 50)
            )
        ]
        squad = optimizer.Squad(midfielders, 0.0)
        core_ids = {
            player.player_id for player in midfielders[:4]
        }

        audit = optimizer.midfield_architecture_audit(
            squad,
            core_ids,
            maintenance="low",
            enforce=True,
            qualified_potential_ids=frozenset({"talent-bank-m5"}),
            position_minimum_costs={"MIDFIELDER": 50},
            floor_available_count=10,
        )

        self.assertTrue(audit["passes"])
        self.assertEqual(1, audit["expensive_ordinary_reserve_count"])
        self.assertEqual(
            ["talent-bank-m5"],
            audit["qualified_potential_reserve_ids"],
        )

    def test_low_maintenance_requires_a_playable_midfield_backup(self) -> None:
        midfielders = [
            player(
                f"ready-bank-m{index}",
                f"Ready Midfield Club {index}",
                "MIDFIELDER",
                250 if index < 4 else 50,
            )
            for index in range(7)
        ]
        midfielders[3] = optimizer.replace(
            midfielders[3],
            components={
                **midfielders[3].components,
                "minutes": 40.0,
                "role": 45.0,
            },
        )
        scores = {
            item.player_id: 100.0 - index
            for index, item in enumerate(midfielders)
        }

        audit = optimizer.midfield_architecture_audit(
            optimizer.Squad(midfielders, 0.0),
            {item.player_id for item in midfielders[:3]},
            maintenance="low",
            enforce=True,
            raw_scores=scores,
            position_minimum_costs={"MIDFIELDER": 50},
            floor_available_count=10,
            ready_reserve_available_count=5,
        )

        self.assertFalse(audit["passes"])
        self.assertEqual("ready-bank-m3", audit["direct_backup_player_id"])
        self.assertEqual(1, audit["direct_backup_deficit"])

    def test_paid_forward_depth_requires_cross_position_cover(self) -> None:
        forwards = [
            player(
                f"depth-f{index}",
                f"Depth Forward Club {index}",
                "FORWARD",
                cost,
            )
            for index, cost in enumerate((600, 550, 500, 250, 200))
        ]
        core_ids = {item.player_id for item in forwards[:3]}

        audit = optimizer.forward_reserve_architecture_audit(
            optimizer.Squad(forwards, 0.0),
            core_ids,
            maintenance="low",
            enforce=True,
            position_minimum_costs={"FORWARD": 50},
            midfield_direct_backup_ready=False,
            defender_direct_backup_ready=True,
        )

        self.assertFalse(audit["passes"])
        self.assertEqual(2, audit["expensive_reserve_count"])
        self.assertEqual(1, audit["expensive_reserve_excess"])
        self.assertEqual(1, audit["coverage_deficit"])

    def test_one_paid_forward_backup_is_allowed_after_other_cover(self) -> None:
        forwards = [
            player(
                f"covered-f{index}",
                f"Covered Forward Club {index}",
                "FORWARD",
                cost,
            )
            for index, cost in enumerate((600, 550, 500, 200, 50))
        ]

        audit = optimizer.forward_reserve_architecture_audit(
            optimizer.Squad(forwards, 0.0),
            {item.player_id for item in forwards[:3]},
            maintenance="low",
            enforce=True,
            position_minimum_costs={"FORWARD": 50},
            midfield_direct_backup_ready=True,
            defender_direct_backup_ready=True,
        )

        self.assertTrue(audit["passes"])
        self.assertEqual(1, audit["expensive_reserve_count"])
        self.assertGreaterEqual(audit["core_budget_share"], 0.75)

    def test_low_maintenance_caps_paid_forward_backup_price(self) -> None:
        forwards = [
            player(
                f"capped-f{index}",
                f"Capped Forward Club {index}",
                "FORWARD",
                cost,
            )
            for index, cost in enumerate(
                (600_000, 450_000, 350_000, 350_000, 50_000)
            )
        ]

        audit = optimizer.forward_reserve_architecture_audit(
            optimizer.Squad(forwards, 0.0),
            {item.player_id for item in forwards[:3]},
            maintenance="low",
            enforce=True,
            position_minimum_costs={"FORWARD": 50_000},
            midfield_direct_backup_ready=True,
            defender_direct_backup_ready=True,
        )

        self.assertFalse(audit["passes"])
        self.assertEqual(150_000, audit["maximum_reserve_cost"])
        self.assertEqual(1, audit["overpriced_reserve_count"])

    def test_midfield_package_search_retains_hard_gate_compliant_shape(
        self,
    ) -> None:
        candidates = [
            player("mid-premium", "Mid Club 0", "MIDFIELDER", 1_800_000),
            player("mid-1", "Mid Club 1", "MIDFIELDER", 1_400_000),
            player("mid-2", "Mid Club 2", "MIDFIELDER", 1_300_000),
            player("mid-3", "Mid Club 3", "MIDFIELDER", 1_200_000),
            player("mid-bank-1", "Mid Club 4", "MIDFIELDER", 800_000),
            player("mid-bank-2", "Mid Club 5", "MIDFIELDER", 700_000),
            player("mid-floor-1", "Mid Club 6", "MIDFIELDER", 500_000),
            player("mid-floor-2", "Mid Club 7", "MIDFIELDER", 500_000),
        ]
        scores = {
            item.player_id: score
            for item, score in zip(
                candidates,
                (101.0, 99.0, 98.0, 97.0, 96.0, 95.0, 94.0, 93.0),
            )
        }

        packages = optimizer.position_roster_packages(
            candidates,
            scores,
            position="MIDFIELDER",
            count=7,
            total_cost=7_400_000,
            maintenance="low",
            limit=1,
        )

        self.assertEqual(1, len(packages))
        selected = {item.player_id for item in packages[0]}
        self.assertIn("mid-premium", selected)
        self.assertIn("mid-floor-1", selected)
        self.assertIn("mid-floor-2", selected)

    def test_forward_package_search_retains_affordable_reserves(self) -> None:
        candidates = [
            player("fwd-premium", "Forward Club 0", "FORWARD", 4_100_000),
            player("fwd-1", "Forward Club 1", "FORWARD", 3_000_000),
            player("fwd-2", "Forward Club 2", "FORWARD", 2_500_000),
            player("fwd-3", "Forward Club 3", "FORWARD", 2_000_000),
            player("fwd-bank", "Forward Club 4", "FORWARD", 1_600_000),
            player("fwd-floor-1", "Forward Club 5", "FORWARD", 500_000),
            player("fwd-floor-2", "Forward Club 6", "FORWARD", 500_000),
        ]
        scores = {
            item.player_id: score
            for item, score in zip(
                candidates,
                (101.0, 100.0, 99.0, 98.0, 97.0, 96.0, 95.0),
            )
        }

        packages = optimizer.position_roster_packages(
            candidates,
            scores,
            position="FORWARD",
            count=5,
            total_cost=9_600_000,
            maintenance="low",
            limit=1,
        )

        self.assertEqual(1, len(packages))
        selected = {item.player_id for item in packages[0]}
        self.assertIn("fwd-premium", selected)
        self.assertIn("fwd-floor-1", selected)
        self.assertIn("fwd-floor-2", selected)
        self.assertNotIn("fwd-bank", selected)

    def test_premium_starter_requires_price_and_performance(self) -> None:
        candidates: list[optimizer.Player] = []
        scores: dict[str, float] = {}
        for index, (cost, score) in enumerate(
            (
                (600, 95.0),
                (600, 30.0),
                (450, 100.0),
                (350, 90.0),
                (250, 80.0),
                (150, 70.0),
                (50, 60.0),
                (50, 50.0),
            )
        ):
            item = player(
                f"premium-m{index}",
                f"Premium Club {index}",
                "MIDFIELDER",
                cost,
            )
            candidates.append(item)
            scores[item.player_id] = score

        premium_ids = optimizer.premium_starter_candidate_ids(
            candidates,
            scores,
        )

        self.assertIn("premium-m0", premium_ids)
        self.assertNotIn("premium-m1", premium_ids)
        self.assertNotIn("premium-m2", premium_ids)
        weighted, multipliers = optimizer.core_weighted_scores(
            candidates,
            scores,
            "reliable",
            "low",
        )
        self.assertAlmostEqual(
            60.0,
            weighted["premium-m0"]
            - scores["premium-m0"] * multipliers["premium-m0"],
        )
        self.assertAlmostEqual(
            0.0,
            weighted["premium-m1"]
            - scores["premium-m1"] * multipliers["premium-m1"],
        )

    def test_starting_scorer_leverage_rewards_repeatable_current_role(
        self,
    ) -> None:
        base = player(
            "scorer",
            "Scorer Club",
            "FORWARD",
            800,
            reliable_anchor=True,
            role_context={
                "continuity": "confirmed",
                "responsibilities": {
                    "offensive_focal_point": "primary",
                    "penalties": "shared",
                },
            },
        )
        scorer = optimizer.replace(
            base,
            proven_seasons=4,
            scorer_profile={
                "sample_minutes": 6_000,
                "proven_seasons": 4,
                "goals_per_90": 0.42,
                "contributions_per_90": 0.58,
            },
        )
        ordinary = optimizer.replace(
            scorer,
            player_id="ordinary",
            role_context={},
            scorer_profile={},
        )

        self.assertGreater(
            optimizer.starting_scorer_leverage(scorer),
            8.0,
        )
        self.assertEqual(
            0.0,
            optimizer.starting_scorer_leverage(ordinary),
        )

    def test_defensive_overspend_is_softly_penalized_when_scorer_exists(
        self,
    ) -> None:
        squad_players: list[optimizer.Player] = []
        scores: dict[str, float] = {}
        for position, prefix, count in (
            ("GOALKEEPER", "og", 3),
            ("DEFENDER", "od", 7),
            ("MIDFIELDER", "om", 7),
            ("FORWARD", "of", 5),
        ):
            for index in range(count):
                item = player(
                    f"{prefix}{index}",
                    (
                        "Opportunity Goalkeeper Club"
                        if position == "GOALKEEPER"
                        else f"Opportunity Club {prefix}{index}"
                    ),
                    position,
                    100,
                )
                squad_players.append(item)
                scores[item.player_id] = 90.0 - index
        metrics = optimizer.squad_architecture_metrics(
            optimizer.Squad(squad_players, 0.0),
            scores,
            maintenance="low",
            min_reliable_anchors=0,
            min_attacking_anchors=0,
            min_core_budget_share=0.0,
            target_core_budget_share=0.0,
            premium_starter_ids=frozenset({"of0"}),
        )

        self.assertGreater(
            metrics["defender_spend_share"],
            metrics["defender_spend_soft_cap"],
        )
        self.assertLess(
            metrics["defensive_overspend_adjustment"],
            0.0,
        )

    def test_financeable_elite_striker_penalizes_expensive_reserves(
        self,
    ) -> None:
        squad_players: list[optimizer.Player] = []
        scores: dict[str, float] = {}
        for position, prefix, count in (
            ("GOALKEEPER", "erg", 3),
            ("DEFENDER", "erd", 7),
            ("MIDFIELDER", "erm", 7),
            ("FORWARD", "erf", 5),
        ):
            for index in range(count):
                cost = (
                    500
                    if position == "MIDFIELDER" and index == 6
                    else 100
                )
                item = player(
                    f"{prefix}{index}",
                    (
                        "Elite Rebound Goalkeepers"
                        if position == "GOALKEEPER"
                        else f"Elite Rebound Club {prefix}{index}"
                    ),
                    position,
                    cost,
                )
                squad_players.append(item)
                scores[item.player_id] = 100.0 - index

        metrics = optimizer.squad_architecture_metrics(
            optimizer.Squad(squad_players, 0.0),
            scores,
            maintenance="low",
            min_reliable_anchors=0,
            min_attacking_anchors=0,
            min_core_budget_share=0.0,
            target_core_budget_share=0.0,
            premium_starter_ids=frozenset({"available-elite"}),
            elite_rebound_striker_costs={"available-elite": 500},
            position_minimum_costs={
                "DEFENDER": 100,
                "MIDFIELDER": 100,
                "FORWARD": 100,
            },
        )

        self.assertEqual(400, metrics["offensive_reserve_excess_budget"])
        self.assertEqual(400, metrics["elite_rebound_required_increment"])
        self.assertTrue(
            metrics["elite_rebound_financeable_from_reserves"]
        )
        self.assertEqual(
            -optimizer.ELITE_REBOUND_REALLOCATION_PENALTY,
            metrics["elite_rebound_reallocation_adjustment"],
        )

    def test_ready_minimum_price_defenders_count_as_functional(self) -> None:
        squad_players: list[optimizer.Player] = []
        scores: dict[str, float] = {}
        for position, prefix, count in (
            ("GOALKEEPER", "dfg", 3),
            ("DEFENDER", "dfd", 7),
            ("MIDFIELDER", "dfm", 7),
            ("FORWARD", "dff", 5),
        ):
            for index in range(count):
                item = player(
                    f"{prefix}{index}",
                    (
                        "Defender Floor Goalkeepers"
                        if position == "GOALKEEPER"
                        else f"Defender Floor Club {prefix}{index}"
                    ),
                    position,
                    50 if position == "DEFENDER" else 100,
                )
                squad_players.append(item)
                scores[item.player_id] = 100.0 - index

        metrics = optimizer.squad_architecture_metrics(
            optimizer.Squad(squad_players, 0.0),
            scores,
            maintenance="low",
            min_reliable_anchors=0,
            min_attacking_anchors=0,
            min_core_budget_share=0.10,
            target_core_budget_share=0.10,
            position_minimum_costs={"DEFENDER": 50},
        )

        defender_audit = metrics["defender_architecture"]
        self.assertTrue(metrics["passes"])
        self.assertEqual(7, defender_audit["minimum_price_count"])
        self.assertEqual(4, defender_audit["minimum_price_limit"])
        self.assertEqual(
            3,
            defender_audit["minimum_price_filler_count"],
        )
        self.assertEqual(3, defender_audit["minimum_price_filler_limit"])
        self.assertTrue(defender_audit["direct_backup_ready"])

    def test_recent_roster_exposure_penalizes_core_more_than_bench(self) -> None:
        squad_players: list[optimizer.Player] = []
        scores: dict[str, float] = {}
        for position, prefix, count in (
            ("GOALKEEPER", "vxg", 3),
            ("DEFENDER", "vxd", 7),
            ("MIDFIELDER", "vxm", 7),
            ("FORWARD", "vxf", 5),
        ):
            for index in range(count):
                item = player(
                    f"{prefix}{index}",
                    (
                        "Variation Goalkeepers"
                        if position == "GOALKEEPER"
                        else f"Variation Club {prefix}{index}"
                    ),
                    position,
                    100,
                )
                squad_players.append(item)
                scores[item.player_id] = 100.0 - index
        squad = optimizer.Squad(squad_players, 0.0)
        baseline = optimizer.squad_architecture_metrics(
            squad,
            scores,
            maintenance="low",
            min_reliable_anchors=0,
            min_attacking_anchors=0,
            min_core_budget_share=0.10,
            target_core_budget_share=0.10,
            position_minimum_costs={
                "DEFENDER": 100,
                "MIDFIELDER": 100,
                "FORWARD": 100,
            },
        )
        core_id = next(iter(baseline["player_ids"]))
        bench_id = next(
            player.player_id
            for player in squad_players
            if player.player_id not in baseline["player_ids"]
        )
        exposed = optimizer.squad_architecture_metrics(
            squad,
            scores,
            maintenance="low",
            min_reliable_anchors=0,
            min_attacking_anchors=0,
            min_core_budget_share=0.10,
            target_core_budget_share=0.10,
            position_minimum_costs={
                "DEFENDER": 100,
                "MIDFIELDER": 100,
                "FORWARD": 100,
            },
            variation_exposure={core_id: 1, bench_id: 1},
            variation_exposure_strength=2.0,
        )

        self.assertEqual(-5.0, exposed["variation_exposure_adjustment"])
        self.assertEqual(
            baseline["architecture_objective"],
            exposed["architecture_objective"],
        )
        self.assertLess(
            exposed["architecture_search_objective"],
            exposed["architecture_objective"],
        )
        preferred = optimizer.squad_architecture_metrics(
            squad,
            scores,
            maintenance="low",
            min_reliable_anchors=0,
            min_attacking_anchors=0,
            min_core_budget_share=0.10,
            target_core_budget_share=0.10,
            position_minimum_costs={
                "DEFENDER": 100,
                "MIDFIELDER": 100,
                "FORWARD": 100,
            },
            variation_preferences={core_id: 1.0, bench_id: 1.0},
        )
        self.assertEqual(
            2.5,
            preferred["variation_preference_adjustment"],
        )

    def test_final_architecture_enforces_variant_distance(self) -> None:
        squad_players = []
        scores = {}
        for position, count, prefix in (
            ("GOALKEEPER", 3, "g"),
            ("DEFENDER", 7, "d"),
            ("MIDFIELDER", 7, "m"),
            ("FORWARD", 5, "f"),
        ):
            for index in range(count):
                item = player(
                    f"{prefix}{index}",
                    (
                        "Distance Goalkeepers"
                        if position == "GOALKEEPER"
                        else f"Distance Club {prefix}{index}"
                    ),
                    position,
                    100,
                )
                squad_players.append(item)
                scores[item.player_id] = 100.0 - index
        squad = optimizer.Squad(squad_players, 0.0)
        metrics = optimizer.squad_architecture_metrics(
            squad,
            scores,
            maintenance="low",
            min_reliable_anchors=0,
            min_attacking_anchors=0,
            min_core_budget_share=0.10,
            target_core_budget_share=0.10,
            position_minimum_costs={
                "DEFENDER": 100,
                "MIDFIELDER": 100,
                "FORWARD": 100,
            },
            variation_reference_squads=(squad.ids,),
            minimum_variation_distance=5,
            maximum_variation_distance=7,
        )

        self.assertTrue(metrics["passes"])
        self.assertEqual([0], metrics["variation_distances"])
        self.assertEqual(5, metrics["variation_distance_deficit"])
        self.assertFalse(metrics["variation_distance_target_met"])
        self.assertEqual(-125.0, metrics["variation_distance_adjustment"])

    def test_defender_floor_requires_a_playable_first_reserve(self) -> None:
        defenders = [
            player(
                f"backup-d{index}",
                f"Backup Defender Club {index}",
                "DEFENDER",
                150 if index < 4 else 50,
            )
            for index in range(7)
        ]
        weak_backup = optimizer.replace(
            defenders[3],
            components={
                **defenders[3].components,
                "minutes": 40.0,
                "role": 45.0,
            },
        )
        defenders[3] = weak_backup
        scores = {
            item.player_id: 100.0 - index
            for index, item in enumerate(defenders)
        }

        audit = optimizer.defender_architecture_audit(
            optimizer.Squad(defenders, 0.0),
            {item.player_id for item in defenders[:3]},
            maintenance="low",
            enforce=True,
            raw_scores=scores,
            position_minimum_costs={"DEFENDER": 50},
            ready_reserve_available_count=5,
        )

        self.assertFalse(audit["passes"])
        self.assertEqual("backup-d3", audit["direct_backup_player_id"])
        self.assertEqual(1, audit["direct_backup_deficit"])

    def test_dynamic_defender_filler_limit_tracks_the_formation(self) -> None:
        defenders = [
            player(
                f"dynamic-d{index}",
                f"Dynamic Defender Club {index}",
                "DEFENDER",
                150 if index < 5 else 50,
            )
            for index in range(7)
        ]
        scores = {
            item.player_id: 100.0 - index
            for index, item in enumerate(defenders)
        }
        squad = optimizer.Squad(defenders, 0.0)

        three_defender_audit = optimizer.defender_architecture_audit(
            squad,
            {item.player_id for item in defenders[:3]},
            maintenance="low",
            enforce=True,
            raw_scores=scores,
            position_minimum_costs={"DEFENDER": 50},
            ready_reserve_available_count=5,
        )
        four_defender_audit = optimizer.defender_architecture_audit(
            squad,
            {item.player_id for item in defenders[:4]},
            maintenance="low",
            enforce=True,
            raw_scores=scores,
            position_minimum_costs={"DEFENDER": 50},
            ready_reserve_available_count=5,
        )

        self.assertEqual(3, three_defender_audit["minimum_price_filler_limit"])
        self.assertEqual(2, four_defender_audit["minimum_price_filler_limit"])
        self.assertTrue(three_defender_audit["direct_backup_ready"])
        self.assertTrue(four_defender_audit["direct_backup_ready"])

    def test_joint_architecture_repairs_defender_floor_progressively(
        self,
    ) -> None:
        squad_players: list[optimizer.Player] = []
        candidates: list[optimizer.Player] = []
        scores: dict[str, float] = {}
        for position, prefix, count, cost, score in (
            ("GOALKEEPER", "rfg", 3, 100, 70.0),
            ("DEFENDER", "rfd", 7, 50, 50.0),
            ("MIDFIELDER", "rfm", 7, 300, 90.0),
            ("FORWARD", "rff", 5, 300, 90.0),
        ):
            for index in range(count):
                item = player(
                    f"{prefix}{index}",
                    (
                        "Repair Floor Goalkeepers"
                        if position == "GOALKEEPER"
                        else f"Repair Floor Club {prefix}{index}"
                    ),
                    position,
                    cost,
                )
                squad_players.append(item)
                candidates.append(item)
                scores[item.player_id] = score - index

        for index in range(3):
            upgraded = player(
                f"repair-defender-{index}",
                f"Repair Defender Club {index}",
                "DEFENDER",
                150,
            )
            balancing = player(
                f"repair-forward-{index}",
                f"Repair Forward Club {index}",
                "FORWARD",
                200,
            )
            candidates.extend((upgraded, balancing))
            scores[upgraded.player_id] = 40.0 - index
            scores[balancing.player_id] = 75.0 - index

        initial = optimizer.Squad(
            squad_players,
            sum(scores[item.player_id] for item in squad_players),
        )
        optimized = optimizer.optimize_joint_squad_architecture(
            initial,
            candidates,
            scores,
            scores,
            budget=initial.cost,
            club_cap=4,
            maintenance="low",
            min_reliable_anchors=0,
            min_attacking_anchors=0,
            min_core_budget_share=0.10,
            target_core_budget_share=0.10,
            quality_loss_limit=0.0,
        )

        defender_audit = optimized.architecture_diagnostics[
            "defender_architecture"
        ]
        self.assertTrue(optimized.architecture_diagnostics["passes"])
        self.assertLess(optimized.objective_score, initial.objective_score)
        self.assertLessEqual(
            defender_audit["minimum_price_filler_count"],
            defender_audit["minimum_price_filler_limit"],
        )
        self.assertLessEqual(
            defender_audit["nonfunctional_minimum_price_starter_count"],
            defender_audit["minimum_price_starter_limit"],
        )
        self.assertGreaterEqual(
            optimized.architecture_diagnostics["improvement_iterations"],
            1,
        )

    def test_finalized_objective_rejects_failed_architecture_diagnostics(
        self,
    ) -> None:
        item = player("failed-architecture", "Failed Club", "MIDFIELDER", 100)
        squad = optimizer.Squad(
            [item],
            0.0,
            architecture_diagnostics={
                "architecture_objective": 999.0,
                "passes": False,
            },
        )

        objective, valid = optimizer.finalized_squad_objective(
            squad,
            [item],
            {item.player_id: 50.0},
            {item.player_id: 50.0},
            SimpleNamespace(min_core_budget_share=0.10),
        )

        self.assertEqual(999.0, objective)
        self.assertFalse(valid)

    def test_joint_architecture_values_goalkeeper_primary_over_backups(
        self,
    ) -> None:
        def goalkeeper(
            player_id: str,
            club: str,
            cost: int,
            rank: int,
        ) -> optimizer.Player:
            return optimizer.replace(
                player(player_id, club, "GOALKEEPER", cost),
                goalkeeper_outlook={
                    "club_rank": rank,
                    "starter_probability": 90 if rank == 1 else 5,
                    "hierarchy_score": 90 if rank == 1 else 20,
                },
            )

        current_goalkeepers = [
            goalkeeper("ga1", "Goalkeeper A", 100, 1),
            goalkeeper("ga2", "Goalkeeper A", 100, 2),
            goalkeeper("ga3", "Goalkeeper A", 100, 3),
        ]
        alternative_goalkeepers = [
            goalkeeper("gb1", "Goalkeeper B", 100, 1),
            goalkeeper("gb2", "Goalkeeper B", 100, 2),
            goalkeeper("gb3", "Goalkeeper B", 100, 3),
        ]
        squad_players = list(current_goalkeepers)
        scores = {
            "ga1": 80.0,
            "ga2": 90.0,
            "ga3": 90.0,
            "gb1": 100.0,
            "gb2": 70.0,
            "gb3": 70.0,
        }
        for position, prefix, count, starters in (
            ("DEFENDER", "gd", 7, 4),
            ("MIDFIELDER", "gm", 7, 4),
            ("FORWARD", "gf", 5, 2),
        ):
            for index in range(count):
                item = player(
                    f"{prefix}{index}",
                    f"Club {prefix}{index}",
                    position,
                    300,
                )
                squad_players.append(item)
                scores[item.player_id] = (
                    100.0 - index
                    if index < starters
                    else 30.0 - index
                )
        squad = optimizer.Squad(
            squad_players,
            sum(scores[item.player_id] for item in squad_players),
        )

        optimized = optimizer.optimize_joint_squad_architecture(
            squad,
            [*squad_players, *alternative_goalkeepers],
            scores,
            scores,
            budget=squad.cost,
            club_cap=4,
            maintenance="low",
            min_reliable_anchors=0,
            min_attacking_anchors=0,
            min_core_budget_share=0.50,
            target_core_budget_share=0.65,
        )

        self.assertTrue(
            {item.player_id for item in alternative_goalkeepers}
            <= optimized.ids
        )
        self.assertFalse(
            {item.player_id for item in current_goalkeepers}
            & optimized.ids
        )
        lineup = optimizer.reliable_core_audit(
            optimized,
            scores,
            0,
            0,
            0.50,
        )
        self.assertIn("gb1", lineup["player_ids"])
        self.assertNotIn("gb2", lineup["player_ids"])

    def test_final_annotation_requires_anchor_benchmark_and_evidence_fields(
        self,
    ) -> None:
        annotation = {
            "components": {key: 70.0 for key in optimizer.COMPONENTS},
            "risks": {key: 10.0 for key in optimizer.RISKS},
            "reliable_anchor": False,
            "benchmark": True,
            "evidence": [
                {
                    "claim": "Current role checked",
                    "source_url": "https://example.com/player",
                    "checked_at": "2026-07-24",
                }
            ],
        }
        self.assertTrue(optimizer.annotation_is_complete(annotation))
        self.assertTrue(
            optimizer.annotation_is_complete(
                {
                    **annotation,
                    "reliable_anchor": "auto",
                    "proven_seasons": 3,
                    "anchor_reason": "Let the strict model thresholds decide",
                }
            )
        )
        self.assertFalse(
            optimizer.annotation_is_complete(
                {
                    **annotation,
                    "reliable_anchor": "auto",
                    "proven_seasons": 1,
                    "anchor_reason": "Only one proven season",
                }
            )
        )
        self.assertFalse(
            optimizer.annotation_is_complete({**annotation, "evidence": []})
        )
        self.assertFalse(
            optimizer.annotation_is_complete(
                {key: value for key, value in annotation.items() if key != "benchmark"}
            )
        )

    def test_legacy_quality_merge_does_not_invent_empty_goalkeeper_outlook(
        self,
    ) -> None:
        merged = optimizer.merge_annotations(
            {},
            {
                "g1": {
                    "position": "GOALKEEPER",
                    "components": {"minutes": 80},
                    "risks": {"rotation": 10},
                }
            },
        )

        self.assertNotIn("goalkeeper_outlook", merged["g1"])

    def test_reliable_anchor_classification_respects_mode_and_safety_gate(
        self,
    ) -> None:
        components = {
            "confirmed_performance": 90.0,
            "minutes": 85.0,
            "role": 82.0,
            "stability": 80.0,
            "context": 70.0,
            "fitness": 85.0,
            "upside": 55.0,
            "value": 60.0,
        }
        risks = {
            "transfer": 10.0,
            "injury": 10.0,
            "rotation": 10.0,
            "outlier": 10.0,
            "unknown_role": 10.0,
        }

        self.assertEqual(
            (True, "auto"),
            optimizer.classify_reliable_anchor(
                {"proven_seasons": 3},
                True,
                "MIDFIELDER",
                80.0,
                components,
                risks,
            ),
        )
        self.assertEqual(
            (True, "explicit"),
            optimizer.classify_reliable_anchor(
                {
                    "reliable_anchor": True,
                    "proven_seasons": 3,
                    "anchor_reason": "Multi-season performance and stable role",
                },
                True,
                "FORWARD",
                20.0,
                components,
                risks,
            ),
        )
        self.assertEqual(
            (False, "explicit"),
            optimizer.classify_reliable_anchor(
                {"reliable_anchor": True},
                True,
                "FORWARD",
                80.0,
                components,
                risks,
            ),
        )
        self.assertEqual(
            (False, "explicit"),
            optimizer.classify_reliable_anchor(
                {
                    "reliable_anchor": True,
                    "proven_seasons": 3,
                    "anchor_reason": "One unrepeatable peak season",
                },
                True,
                "MIDFIELDER",
                80.0,
                components,
                {**risks, "outlier": 100.0},
            ),
        )
        self.assertEqual(
            (False, "explicit"),
            optimizer.classify_reliable_anchor(
                {
                    "reliable_anchor": True,
                    "proven_seasons": 3,
                    "anchor_reason": "Proven, but transfer status is unsafe",
                },
                True,
                "MIDFIELDER",
                80.0,
                components,
                {**risks, "transfer": 36.0},
            ),
        )
        self.assertEqual(
            (False, "explicit"),
            optimizer.classify_reliable_anchor(
                {
                    "reliable_anchor": True,
                    "proven_seasons": 3,
                    "anchor_reason": "Safe role, but not premium performance",
                },
                True,
                "MIDFIELDER",
                80.0,
                {**components, "confirmed_performance": 70.0},
                risks,
            ),
        )
        self.assertEqual(
            (False, "explicit"),
            optimizer.classify_reliable_anchor(
                {"reliable_anchor": False},
                True,
                "MIDFIELDER",
                80.0,
                components,
                risks,
            ),
        )
        self.assertEqual(
            (False, "none"),
            optimizer.classify_reliable_anchor(
                {
                    "reliable_anchor": True,
                    "proven_seasons": 3,
                    "anchor_reason": "Goalkeepers do not count as field anchors",
                },
                True,
                "GOALKEEPER",
                80.0,
                components,
                risks,
            ),
        )

    def test_optimize_enforces_three_anchors_over_higher_unconstrained_scores(
        self,
    ) -> None:
        slots = {
            "GOALKEEPER": 3,
            "DEFENDER": 2,
            "MIDFIELDER": 2,
            "FORWARD": 2,
        }
        players = [
            player(f"g{index}", "Goalkeeper Club", "GOALKEEPER", 100)
            for index in range(3)
        ]
        scores = {item.player_id: 5.0 for item in players}
        for position, prefix in (
            ("DEFENDER", "d"),
            ("MIDFIELDER", "m"),
            ("FORWARD", "f"),
        ):
            for index, score in enumerate((20.0, 19.0, 15.0)):
                item = player(
                    f"{prefix}{index}",
                    f"{prefix.upper()} Club {index}",
                    position,
                    100,
                    reliable_anchor=index == 2,
                )
                players.append(item)
                scores[item.player_id] = score

        unconstrained = optimizer.optimize(
            players,
            900,
            scores,
            1,
            900,
            slots,
        )
        constrained = optimizer.optimize(
            players,
            900,
            scores,
            1,
            900,
            slots,
            min_reliable_anchors=3,
        )

        self.assertEqual(
            0,
            sum(item.reliable_anchor for item in unconstrained.players),
        )
        self.assertEqual(
            3,
            sum(item.reliable_anchor for item in constrained.players),
        )
        self.assertLess(
            constrained.objective_score,
            unconstrained.objective_score,
        )

    def test_medium_variation_preserves_anchor_floor(self) -> None:
        players, scores = varied_pool()
        players = [
            optimizer.Player(
                **{
                    **item.__dict__,
                    "reliable_anchor": (
                        item.position != "GOALKEEPER"
                        and item.player_id[-1] in {"0", "2", "4"}
                    ),
                }
            )
            for item in players
        ]
        slots = {
            "GOALKEEPER": 3,
            "DEFENDER": 2,
            "MIDFIELDER": 2,
            "FORWARD": 2,
        }

        squad, optimum, distance, target_met = optimizer.varied_squad(
            players,
            900,
            scores,
            "reliable",
            "medium",
            20260724,
            1,
            900,
            slots,
            set(),
            min_reliable_anchors=3,
        )

        self.assertGreaterEqual(
            sum(item.reliable_anchor for item in optimum.players),
            3,
        )
        self.assertGreaterEqual(
            sum(item.reliable_anchor for item in squad.players),
            3,
        )
        self.assertTrue(target_met)
        self.assertEqual(5, distance)

    def test_infeasible_anchor_floor_reports_required_eligible_and_reachable(
        self,
    ) -> None:
        slots = {
            "GOALKEEPER": 3,
            "DEFENDER": 2,
            "MIDFIELDER": 2,
            "FORWARD": 2,
        }
        players = [
            player(f"g{index}", "Goalkeeper Club", "GOALKEEPER", 100)
            for index in range(3)
        ]
        scores = {item.player_id: 5.0 for item in players}
        anchor_ids = {"d0", "m0"}
        for position, prefix in (
            ("DEFENDER", "d"),
            ("MIDFIELDER", "m"),
            ("FORWARD", "f"),
        ):
            for index in range(2):
                item = player(
                    f"{prefix}{index}",
                    f"{prefix.upper()} Club {index}",
                    position,
                    100,
                    reliable_anchor=f"{prefix}{index}" in anchor_ids,
                )
                players.append(item)
                scores[item.player_id] = 10.0 - index

        with self.assertRaisesRegex(
            ValueError,
            (
                r"^reliable-anchor policy is infeasible: required=3, eligible=2, "
                r"max reachable under roster, budget and club constraints=2$"
            ),
        ):
            optimizer.optimize(
                players,
                900,
                scores,
                1,
                900,
                slots,
                min_reliable_anchors=3,
            )

    def test_core_weighting_emphasizes_top_scores_for_low_maintenance_profiles(
        self,
    ) -> None:
        players = [
            player("d-high", "D High", "DEFENDER", 100),
            player("d-mid", "D Mid", "DEFENDER", 100),
            player("d-low", "D Low", "DEFENDER", 100),
            player("m-high", "M High", "MIDFIELDER", 100),
            player("m-low", "M Low", "MIDFIELDER", 100),
        ]
        scores = {
            "d-high": 100.0,
            "d-mid": 70.0,
            "d-low": 40.0,
            "m-high": 80.0,
            "m-low": 20.0,
        }

        weighted, multipliers = optimizer.core_weighted_scores(
            players,
            scores,
            "reliable",
            "low",
        )

        self.assertAlmostEqual(1.0, multipliers["d-high"])
        self.assertAlmostEqual(0.15625, multipliers["d-mid"])
        self.assertAlmostEqual(0.1, multipliers["d-low"])
        self.assertGreater(
            multipliers["d-high"],
            multipliers["d-mid"],
        )
        self.assertGreater(
            multipliers["d-mid"],
            multipliers["d-low"],
        )
        self.assertAlmostEqual(100.0, weighted["d-high"])
        self.assertAlmostEqual(10.9375, weighted["d-mid"])
        self.assertAlmostEqual(4.0, weighted["d-low"])

        balanced, balanced_multipliers = optimizer.core_weighted_scores(
            players,
            scores,
            "balanced",
            "low",
        )
        self.assertAlmostEqual(1.0, balanced_multipliers["d-high"])
        self.assertLess(balanced_multipliers["d-mid"], 1.0)
        self.assertGreater(
            balanced_multipliers["d-mid"],
            multipliers["d-mid"],
        )
        self.assertLess(balanced["d-low"], scores["d-low"])

        breakout, breakout_multipliers = optimizer.core_weighted_scores(
            players,
            scores,
            "breakout",
            "low",
        )
        self.assertAlmostEqual(1.0, breakout_multipliers["d-high"])
        self.assertGreater(
            breakout_multipliers["d-mid"],
            balanced_multipliers["d-mid"],
        )
        self.assertLess(breakout["d-low"], scores["d-low"])

        for profile, maintenance in (
            ("reliable", "normal"),
            ("reliable", "active"),
            ("balanced", "normal"),
        ):
            with self.subTest(profile=profile, maintenance=maintenance):
                unchanged, neutral = optimizer.core_weighted_scores(
                    players,
                    scores,
                    profile,
                    maintenance,
                )
                self.assertEqual(scores, unchanged)
                self.assertEqual(
                    {item.player_id: 1.0 for item in players},
                    neutral,
                )

    def test_output_exposes_core_anchors_benchmarks_and_pool_scope(self) -> None:
        selected: list[optimizer.Player] = []
        all_players: list[optimizer.Player] = []
        for index in range(3):
            item = player(f"g{index}", "Goalkeeper Club", "GOALKEEPER", 100)
            selected.append(item)
            all_players.append(item)
        for position, prefix, count in (
            ("DEFENDER", "d", 7),
            ("MIDFIELDER", "m", 7),
            ("FORWARD", "f", 5),
        ):
            for index in range(count):
                item = player(
                    f"{prefix}{index}",
                    f"{prefix.upper()} Club {index}",
                    position,
                    100,
                    reliable_anchor=index == 0,
                )
                selected.append(item)
                all_players.append(item)
            for index in range(2):
                item = player(
                    f"{prefix}-benchmark-{index}",
                    f"{prefix.upper()} Benchmark {index}",
                    position,
                    120,
                )
                benchmark = optimizer.Player(
                    **{**item.__dict__, "benchmark": True}
                )
                all_players.append(benchmark)

        raw_scores = {
            item.player_id: 100.0006 - index
            for index, item in enumerate(all_players)
        }
        utility_scores = dict(raw_scores)
        multipliers = {item.player_id: 1.0 for item in all_players}
        squad_score = sum(raw_scores[item.player_id] for item in selected)
        squad = optimizer.Squad(selected, squad_score)
        args = SimpleNamespace(
            profile="reliable",
            maintenance="low",
            variation="medium",
            budget=3000,
            max_outfield_per_club=4,
            mixed_goalkeepers=False,
            min_reliable_anchors=3,
        )

        payload = optimizer.output_payload(
            squad=squad,
            optimum=squad,
            players=all_players,
            raw_scores=raw_scores,
            utility_scores=utility_scores,
            core_multipliers=multipliers,
            args=args,
            seed=42,
            distance=0,
            variation_target_met=True,
            annotated_count=len(all_players),
            annotated_by_position={
                "GOALKEEPER": 3,
                "DEFENDER": 9,
                "MIDFIELDER": 9,
                "FORWARD": 7,
            },
            annotation_requirements={
                "GOALKEEPER": 3,
                "DEFENDER": 7,
                "MIDFIELDER": 7,
                "FORWARD": 5,
            },
            annotated_goalkeeper_blocks=1,
            hard_exclusions=[
                {
                    "annotation_key": "injured-star",
                    "reason": "Long-term injury",
                    "benchmark": True,
                    "evidence": [],
                }
            ],
        )

        self.assertEqual(
            "fully_annotated_candidate_pool",
            payload["optimization_scope"]["basis"],
        )
        self.assertAlmostEqual(
            payload["score"],
            sum(item["score"] for item in payload["squad"]),
        )
        self.assertEqual(
            "finalized_starting_xi_and_bench_objective",
            payload["quality_gap_metric"],
        )
        self.assertEqual(3, payload["reliable_anchor_policy"]["selected"])
        self.assertEqual(
            11,
            sum(
                item["selection_role"] == "core"
                for item in payload["squad"]
            ),
        )
        self.assertEqual(6, len(payload["benchmark_audit"]))
        self.assertEqual(
            3,
            payload["suggested_starting_lineup"]["reliable_anchors"],
        )
        self.assertTrue(
            all(item["benchmark"] for item in payload["comparison_candidates"])
        )
        self.assertTrue(
            all(
                item["counterfactual"]["feasible"]
                for item in payload["comparison_candidates"]
            )
        )
        self.assertTrue(
            all(
                item["counterfactual"]["displaced_players"]
                for item in payload["comparison_candidates"]
            )
        )
        self.assertEqual(
            "injured-star",
            payload["hard_exclusions"][0]["annotation_key"],
        )
        self.assertIn("components", payload["squad"][0])
        self.assertTrue(payload["squad"][0]["evidence"])

    def test_unannotated_smoke_output_skips_expensive_counterfactuals(self) -> None:
        all_players = [
            player("g1", "GK Club", "GOALKEEPER", 100),
            player("d1", "Club D", "DEFENDER", 100),
            player("d2", "Club D2", "DEFENDER", 100),
            player("m1", "Club M", "MIDFIELDER", 100),
            player("m2", "Club M2", "MIDFIELDER", 100),
            player("f1", "Club F", "FORWARD", 100),
            player("f2", "Club F2", "FORWARD", 100),
        ]
        selected = [all_players[index] for index in (0, 1, 3, 5)]
        scores = {
            candidate.player_id: 100.0 - index
            for index, candidate in enumerate(all_players)
        }
        payload = optimizer.output_payload(
            squad=optimizer.Squad(
                selected,
                sum(scores[candidate.player_id] for candidate in selected),
            ),
            optimum=optimizer.Squad(
                selected,
                sum(scores[candidate.player_id] for candidate in selected),
            ),
            players=all_players,
            raw_scores=scores,
            utility_scores=scores,
            core_multipliers={
                candidate.player_id: 1.0 for candidate in all_players
            },
            args=SimpleNamespace(
                profile="balanced",
                maintenance="medium",
                variation="none",
                budget=400,
                max_outfield_per_club=4,
                mixed_goalkeepers=True,
                min_reliable_anchors=0,
                allow_unannotated=True,
                slots={
                    "GOALKEEPER": 1,
                    "DEFENDER": 1,
                    "MIDFIELDER": 1,
                    "FORWARD": 1,
                },
                min_spend_ratio=0.0,
            ),
            seed=1,
            distance=0,
            variation_target_met=True,
            annotated_count=0,
            annotated_by_position={
                "GOALKEEPER": 0,
                "DEFENDER": 0,
                "MIDFIELDER": 0,
                "FORWARD": 0,
            },
            annotation_requirements={
                "GOALKEEPER": 1,
                "DEFENDER": 1,
                "MIDFIELDER": 1,
                "FORWARD": 1,
            },
            annotated_goalkeeper_blocks=0,
            hard_exclusions=[],
        )

        self.assertTrue(payload["comparison_candidates"])
        self.assertEqual(
            "technical_unannotated_smoke_pool",
            payload["optimization_scope"]["basis"],
        )
        self.assertTrue(
            any(
                "Technical smoke test only" in warning
                for warning in payload["warnings"]
            )
        )
        self.assertTrue(
            all(
                item["counterfactual"]["feasible"] is None
                for item in payload["comparison_candidates"]
            )
        )

    def test_starting_lineup_places_required_anchors_in_the_core(self) -> None:
        players: list[optimizer.Player] = [
            player(f"g{index}", "Goalkeeper Club", "GOALKEEPER", 100)
            for index in range(3)
        ]
        anchor_ids = {"d6", "m6", "f4"}
        for position, prefix, count in (
            ("DEFENDER", "d", 7),
            ("MIDFIELDER", "m", 7),
            ("FORWARD", "f", 5),
        ):
            for index in range(count):
                players.append(
                    player(
                        f"{prefix}{index}",
                        f"{prefix.upper()} Club {index}",
                        position,
                        100,
                        reliable_anchor=f"{prefix}{index}" in anchor_ids,
                    )
                )
        scores = {
            item.player_id: 100.0 - index
            for index, item in enumerate(players)
        }

        _, unconstrained_ids = optimizer.best_starting_lineup(players, scores)
        formation, constrained_ids = optimizer.best_starting_lineup(
            players,
            scores,
            min_reliable_anchors=3,
        )

        self.assertFalse(anchor_ids.issubset(unconstrained_ids))
        self.assertTrue(anchor_ids.issubset(constrained_ids))
        self.assertEqual(11, len(constrained_ids))
        self.assertIn(formation, {"3-4-3", "3-5-2", "4-3-3", "4-4-2", "4-5-1", "5-3-2", "5-4-1"})


class NewsHardeningIntegrationTests(unittest.TestCase):
    def test_cli_accepts_fresh_fully_mapped_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            csv_path = root / "players.csv"
            csv_path.write_text(
                "ID;Angezeigter Name;Angezeigter Name (kurz);Verein;"
                "Position;Marktwert;Punkte;Notendurchschnitt\n"
                "g;Goalkeeper;GK;Club G;GOALKEEPER;100;0;0\n"
                "d;Defender;D;Club D;DEFENDER;100;0;0\n"
                "m;Midfielder;M;Club M;MIDFIELDER;100;0;0\n"
                "f;Forward;F;Club F;FORWARD;100;0;0\n",
                encoding="utf-8",
            )
            now = datetime.now(timezone.utc)
            generated_at = (now - timedelta(minutes=1)).replace(
                microsecond=0
            ).isoformat().replace("+00:00", "Z")
            expires_at = (now + timedelta(hours=1)).replace(
                microsecond=0
            ).isoformat().replace("+00:00", "Z")
            players = {}
            for index, (player_id, name, club) in enumerate(
                (
                    ("g", "Goalkeeper", "Club G"),
                    ("d", "Defender", "Club D"),
                    ("m", "Midfielder", "Club M"),
                    ("f", "Forward", "Club F"),
                ),
                start=1,
            ):
                players[player_id] = {
                    "name": name,
                    "club": club,
                    "mapping": {
                        "api_sports_player_id": index,
                        "api_sports_team_id": 100 + index,
                        "sportsmonks_player_id": None,
                        "sportsmonks_team_id": None,
                        "confidence": "verified",
                    },
                    "signals": [],
                    "consensus": {
                        "injury": 0,
                        "transfer": 0,
                        "rotation": 0,
                        "fitness_cap": 100,
                        "exclude": False,
                        "confidence": "medium",
                        "conflicts": [],
                    },
                }
            snapshot = {
                "schema_version": 1,
                "generated_at": generated_at,
                "expires_at": expires_at,
                "competition": "2. Bundesliga",
                "season": "2026/27",
                "providers": {
                    "api_sports": {
                        "status": "ok",
                        "fetched_at": generated_at,
                        "records": 0,
                    }
                },
                "players": players,
            }
            snapshot["content_sha256"] = news_snapshot.canonical_sha256(
                snapshot
            )
            snapshot_path = root / "news.json"
            snapshot_path.write_text(
                json.dumps(snapshot),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--players",
                    str(csv_path),
                    "--budget",
                    "400",
                    "--goalkeepers",
                    "1",
                    "--defenders",
                    "1",
                    "--midfielders",
                    "1",
                    "--forwards",
                    "1",
                    "--profile",
                    "balanced",
                    "--variation",
                    "none",
                    "--allow-unannotated",
                    "--competition",
                    "2. Bundesliga",
                    "--season",
                    "2026/27",
                    "--variation-state",
                    str(root / "variation-state.json"),
                    "--news-snapshot",
                    str(snapshot_path),
                    "--require-news-snapshot",
                    "--require-news-coverage",
                    "--format",
                    "json",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

        payload = json.loads(completed.stdout)
        self.assertEqual("fresh", payload["news_audit"]["status"])
        self.assertEqual(4, len(payload["squad"]))
        self.assertEqual(
            "automatic_local",
            payload["variation_identity"]["mode"],
        )
        self.assertEqual(0, payload["variation_identity"]["generation"])
        self.assertFalse(
            payload["variation_identity"]["private_installation_id_exposed"]
        )

    def test_news_only_increases_risk_and_removes_unsafe_anchor_status(self) -> None:
        candidate = player(
            "m1",
            "Current Club",
            "MIDFIELDER",
            100,
            reliable_anchor=True,
        )
        candidate = optimizer.replace(
            candidate,
            risks={**candidate.risks, "injury": 40.0},
            components={**candidate.components, "fitness": 80.0},
        )
        snapshot = {
            "schema_version": 1,
            "generated_at": "2026-07-24T10:00:00Z",
            "expires_at": "2026-07-25T04:00:00Z",
            "competition": "2. Bundesliga",
            "season": "2026/27",
            "providers": {"sportsmonks": {"status": "ok"}},
            "players": {
                "m1": {
                    "name": candidate.name,
                    "club": candidate.club,
                    "mapping": {
                        "sportsmonks_player_id": 123,
                        "sportsmonks_team_id": 321,
                        "api_sports_player_id": None,
                        "api_sports_team_id": None,
                        "confidence": "verified",
                    },
                    "signals": [
                        {
                            "kind": "transfer_rumour",
                            "status": "rumour",
                            "severity": 45,
                            "source_provider": "sportsmonks",
                            "source_url": "https://example.com/rumour",
                            "observed_at": "2026-07-24T10:00:00Z",
                            "detail": "possible move",
                        }
                    ],
                    "consensus": {
                        "injury": 10,
                        "transfer": 45,
                        "rotation": 0,
                        "fitness_cap": 95,
                        "exclude": False,
                        "confidence": "low",
                        "conflicts": [],
                    },
                }
            },
        }

        updated, audit, exclusions = optimizer.apply_news_snapshot(
            [candidate],
            snapshot,
        )

        self.assertEqual([], exclusions)
        self.assertEqual(40.0, updated[0].risks["injury"])
        self.assertEqual(45.0, updated[0].risks["transfer"])
        self.assertEqual(80.0, updated[0].components["fitness"])
        self.assertFalse(updated[0].reliable_anchor)
        self.assertEqual(["m1"], audit["provider_mapped_player_ids"])

    def test_confirmed_high_confidence_unavailability_excludes_player(self) -> None:
        candidate = player("f1", "Current Club", "FORWARD", 100)
        snapshot = {
            "schema_version": 1,
            "generated_at": "2026-07-24T10:00:00Z",
            "expires_at": "2026-07-25T04:00:00Z",
            "competition": "2. Bundesliga",
            "season": "2026/27",
            "providers": {"api_sports": {"status": "ok"}},
            "players": {
                "f1": {
                    "name": candidate.name,
                    "club": candidate.club,
                    "mapping": {
                        "api_sports_player_id": 456,
                        "api_sports_team_id": 654,
                        "confidence": "verified",
                    },
                    "signals": [],
                    "consensus": {
                        "injury": 95,
                        "transfer": 0,
                        "rotation": 0,
                        "fitness_cap": 5,
                        "exclude": True,
                        "confidence": "medium",
                        "conflicts": [],
                    },
                }
            },
        }

        updated, audit, exclusions = optimizer.apply_news_snapshot(
            [candidate],
            snapshot,
        )

        self.assertEqual([], updated)
        self.assertEqual(1, audit["hard_exclusions"])
        self.assertEqual("f1", exclusions[0]["annotation_key"])


if __name__ == "__main__":
    unittest.main()
