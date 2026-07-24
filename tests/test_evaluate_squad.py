from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
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

EVALUATOR_SPEC = importlib.util.spec_from_file_location(
    "evaluate_squad",
    SCRIPT_DIRECTORY / "evaluate_squad.py",
)
if EVALUATOR_SPEC is None or EVALUATOR_SPEC.loader is None:
    raise RuntimeError("could not load evaluate_squad.py")
evaluator = importlib.util.module_from_spec(EVALUATOR_SPEC)
sys.modules[EVALUATOR_SPEC.name] = evaluator
EVALUATOR_SPEC.loader.exec_module(evaluator)

import optimize_squad as optimizer


TODAY = date(2026, 7, 24)
SLOTS = {
    "GOALKEEPER": 1,
    "DEFENDER": 1,
    "MIDFIELDER": 1,
    "FORWARD": 1,
}


def player(
    player_id: str,
    name: str,
    club: str,
    position: str,
    cost: int,
    *,
    score: float = 70.0,
    evidence_date: str = "2026-07-24",
    risks: dict[str, float] | None = None,
) -> optimizer.Player:
    components = {key: score for key in optimizer.COMPONENTS}
    merged_risks = {key: 10.0 for key in optimizer.RISKS}
    if risks:
        merged_risks.update(risks)
    return optimizer.Player(
        player_id=player_id,
        name=name,
        short_name=name,
        club=club,
        position=position,
        cost=cost,
        points=0.0,
        grade=0.0,
        components=components,
        risks=merged_risks,
        researched=True,
        evidence=(
            {
                "claim": "Current role, fitness and transfer status checked",
                "source_url": f"https://example.com/{player_id}",
                "checked_at": evidence_date,
            },
        ),
    )


def selected_players() -> list[optimizer.Player]:
    return [
        player("g1", "Goal Keeper", "Club G", "GOALKEEPER", 100),
        player("d1", "Def Ender", "Club D", "DEFENDER", 100),
        player("m1", "Mid Fielder", "Club M", "MIDFIELDER", 100),
        player("f1", "For Ward", "Club F", "FORWARD", 100),
    ]


def evaluate(
    selected: list[optimizer.Player],
    *,
    candidates: list[optimizer.Player] | None = None,
    scores: dict[str, float] | None = None,
    news_exclusions: list[dict] | None = None,
    require_news_coverage: bool = False,
    mapped_ids: list[str] | None = None,
) -> dict:
    pool = candidates or selected
    score_map = scores or {
        candidate.player_id: 70.0 for candidate in pool
    }
    for candidate in selected:
        score_map.setdefault(candidate.player_id, 70.0)
    return evaluator.evaluate(
        selected=selected,
        candidate_pool=pool,
        scores=score_map,
        slots=SLOTS,
        budget=400,
        profile="balanced",
        maintenance="normal",
        club_cap=4,
        news_audit={
            "status": "fresh",
            "provider_mapped_player_ids": (
                mapped_ids
                if mapped_ids is not None
                else [candidate.player_id for candidate in selected]
            ),
            "conflicts": {},
        },
        news_exclusions=news_exclusions or [],
        annotation_excluded_ids=set(),
        resolution_errors=[],
        require_news_coverage=require_news_coverage,
        max_evidence_age_days=1,
        today=TODAY,
    )


class RosterResolutionTests(unittest.TestCase):
    def test_resolves_browser_entry_by_name_club_position_and_cost(self) -> None:
        official = [
            player("p1", "Max Mustermann", "Club A", "MIDFIELDER", 500),
            player("p2", "Max Mustermann", "Club B", "FORWARD", 600),
        ]

        selected, errors = evaluator.resolve_roster(
            [
                {
                    "name": "Max Mustermann",
                    "club": "Club B",
                    "position": "FORWARD",
                    "cost": 600,
                }
            ],
            official,
        )

        self.assertEqual([], errors)
        self.assertEqual(["p2"], [candidate.player_id for candidate in selected])

    def test_ambiguous_browser_entry_is_not_guessed(self) -> None:
        official = [
            player("p1", "Max Mustermann", "Club A", "MIDFIELDER", 500),
            player("p2", "Max Mustermann", "Club B", "FORWARD", 600),
        ]

        selected, errors = evaluator.resolve_roster(
            [{"name": "Max Mustermann"}],
            official,
        )

        self.assertEqual([], selected)
        self.assertIn("multiple official Kicker players", errors[0])

    def test_kicker_id_with_visible_price_mismatch_is_rejected(self) -> None:
        official = [
            player("p1", "Max Mustermann", "Club A", "MIDFIELDER", 500),
        ]

        selected, errors = evaluator.resolve_roster(
            [
                {
                    "id": "p1",
                    "name": "Max Mustermann",
                    "club": "Club A",
                    "position": "MIDFIELDER",
                    "cost": 600,
                }
            ],
            official,
        )

        self.assertEqual([], selected)
        self.assertIn("visible cost", errors[0])


class SquadEvaluationTests(unittest.TestCase):
    def test_clean_current_squad_can_receive_error_free_confirmation(self) -> None:
        payload = evaluate(selected_players())

        self.assertEqual("ready", payload["status"])
        self.assertTrue(payload["avoidable_error_free"])
        self.assertIsNotNone(payload["rating"])
        self.assertTrue(payload["roster"]["valid"])
        self.assertEqual(4, len(payload["players"]))
        self.assertEqual([], payload["alerts"])

    def test_stale_research_blocks_numeric_confirmation(self) -> None:
        selected = selected_players()
        selected[2] = player(
            "m1",
            "Mid Fielder",
            "Club M",
            "MIDFIELDER",
            100,
            evidence_date="2026-07-20",
        )

        payload = evaluate(selected)

        self.assertEqual("blocked", payload["status"])
        self.assertFalse(payload["avoidable_error_free"])
        self.assertIsNone(payload["rating"])
        self.assertIn(
            "research_coverage",
            {alert["category"] for alert in payload["alerts"]},
        )

    def test_future_dated_research_does_not_count_as_current(self) -> None:
        selected = selected_players()
        selected[2] = player(
            "m1",
            "Mid Fielder",
            "Club M",
            "MIDFIELDER",
            100,
            evidence_date="2026-07-25",
        )

        payload = evaluate(selected)

        self.assertEqual("blocked", payload["status"])
        self.assertIsNone(payload["rating"])

    def test_injury_and_confirmed_unavailability_are_prominent(self) -> None:
        selected = selected_players()
        selected[3] = player(
            "f1",
            "For Ward",
            "Club F",
            "FORWARD",
            100,
            risks={"injury": 75.0},
        )

        payload = evaluate(
            selected,
            news_exclusions=[
                {
                    "annotation_key": "f1",
                    "player": "For Ward",
                    "evidence": [
                        {
                            "claim": "Player unavailable",
                            "source_url": "https://example.com/injury",
                            "checked_at": "2026-07-24",
                        }
                    ],
                }
            ],
        )

        self.assertEqual("critical", payload["status"])
        categories = [alert["category"] for alert in payload["alerts"]]
        self.assertIn("unavailable", categories)
        self.assertIn("injury", categories)
        self.assertFalse(payload["avoidable_error_free"])

    def test_missing_provider_mapping_blocks_news_confirmation(self) -> None:
        selected = selected_players()

        payload = evaluate(
            selected,
            require_news_coverage=True,
            mapped_ids=["g1", "d1", "m1"],
        )

        self.assertEqual("blocked", payload["status"])
        self.assertIsNone(payload["rating"])
        self.assertEqual(
            ["f1"],
            payload["news_audit"]["selected_missing_provider_ids"],
        )

    def test_affordable_researched_upgrade_is_reported_without_mutation(self) -> None:
        selected = selected_players()
        alternative = player(
            "f2",
            "Better Forward",
            "Club X",
            "FORWARD",
            100,
            score=82.0,
        )
        pool = [*selected, alternative]
        scores = {
            "g1": 70.0,
            "d1": 70.0,
            "m1": 70.0,
            "f1": 60.0,
            "f2": 82.0,
        }

        payload = evaluate(
            selected,
            candidates=pool,
            scores=scores,
        )

        self.assertEqual(1, len(payload["alternatives"]))
        self.assertEqual(
            "Better Forward",
            payload["alternatives"][0]["with"]["name"],
        )
        self.assertEqual("For Ward", payload["players"][-1]["name"])


class SquadEvaluationCliTests(unittest.TestCase):
    def test_cli_evaluates_complete_visible_roster_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            csv_path = root / "players.csv"
            csv_path.write_text(
                "ID;Angezeigter Name;Angezeigter Name (kurz);Verein;"
                "Position;Marktwert;Punkte;Notendurchschnitt\n"
                "g1;Goal Keeper;Keeper;Club G;GOALKEEPER;100;10;3,0\n"
                "d1;Def Ender;Ender;Club D;DEFENDER;100;10;3,0\n"
                "m1;Mid Fielder;Fielder;Club M;MIDFIELDER;100;10;3,0\n"
                "f1;For Ward;Ward;Club F;FORWARD;100;10;3,0\n",
                encoding="utf-8",
            )
            roster_path = root / "roster.json"
            roster_path.write_text(
                json.dumps(
                    {
                        "players": [
                            {"id": player_id}
                            for player_id in ("g1", "d1", "m1", "f1")
                        ]
                    }
                ),
                encoding="utf-8",
            )
            annotation = {
                "components": {
                    key: 75 for key in optimizer.COMPONENTS
                },
                "risks": {
                    key: 10 for key in optimizer.RISKS
                },
                "reliable_anchor": False,
                "benchmark": False,
                "evidence": [
                    {
                        "claim": "Current role, fitness and transfer status checked",
                        "source_url": "https://example.com/current",
                        "checked_at": (
                            datetime.now(timezone.utc).date().isoformat()
                        ),
                    }
                ],
                "exclude": False,
            }
            annotations_path = root / "annotations.json"
            annotations_path.write_text(
                json.dumps(
                    {
                        "players": {
                            player_id: annotation
                            for player_id in ("g1", "d1", "m1", "f1")
                        }
                    }
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIRECTORY / "evaluate_squad.py"),
                    "--players",
                    str(csv_path),
                    "--roster",
                    str(roster_path),
                    "--annotations",
                    str(annotations_path),
                    "--competition",
                    "Bundesliga",
                    "--season",
                    "2026/27",
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
                    "--maintenance",
                    "normal",
                    "--format",
                    "json",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

        payload = json.loads(completed.stdout)
        self.assertEqual("evaluate_current_squad", payload["mode"])
        self.assertEqual("ready", payload["status"])
        self.assertTrue(payload["avoidable_error_free"])
        self.assertEqual(4, payload["roster"]["players"])


if __name__ == "__main__":
    unittest.main()
