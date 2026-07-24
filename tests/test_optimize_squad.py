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
        evidence=(
            {
                "claim": "Current role checked",
                "source_url": "https://example.com/player",
                "checked_at": "2026-07-24",
            },
        ),
    )


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
            goalkeeper_groups.extend(
                itertools.combinations(club_players, slots["GOALKEEPER"])
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
        self.assertEqual(4, distance)
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
        self.assertLess(distance, 4)
        self.assertGreaterEqual(squad_score, optimum_score * (1.0 - 0.05 * 0.75))

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


class CentralNewsIdentityTests(unittest.TestCase):
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
                    "anchor_reason": "Let the strict model thresholds decide",
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
                {},
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
        self.assertEqual(4, distance)

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

    def test_core_weighting_emphasizes_top_scores_only_for_reliable_low(
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
        self.assertAlmostEqual(0.475, multipliers["d-mid"])
        self.assertAlmostEqual(0.3, multipliers["d-low"])
        self.assertGreater(
            multipliers["d-high"],
            multipliers["d-mid"],
        )
        self.assertGreater(
            multipliers["d-mid"],
            multipliers["d-low"],
        )
        self.assertAlmostEqual(100.0, weighted["d-high"])
        self.assertAlmostEqual(33.25, weighted["d-mid"])
        self.assertAlmostEqual(12.0, weighted["d-low"])

        for profile, maintenance in (
            ("balanced", "low"),
            ("breakout", "low"),
            ("reliable", "normal"),
            ("reliable", "active"),
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
        self.assertEqual("model_utility", payload["quality_gap_metric"])
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
