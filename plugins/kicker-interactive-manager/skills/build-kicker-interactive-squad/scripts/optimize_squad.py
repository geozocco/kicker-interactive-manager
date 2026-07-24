#!/usr/bin/env python3
"""Optimize a Kicker Interactive squad from the official player CSV.

The script deliberately separates historical CSV evidence from current,
agent-researched annotations. It uses only the Python standard library.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import itertools
import json
import math
import random
import secrets
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


DEFAULT_SLOTS = {
    "GOALKEEPER": 3,
    "DEFENDER": 7,
    "MIDFIELDER": 7,
    "FORWARD": 5,
}
POSITION_ORDER = {name: index for index, name in enumerate(DEFAULT_SLOTS)}
COMPONENTS = (
    "confirmed_performance",
    "minutes",
    "role",
    "stability",
    "context",
    "fitness",
    "upside",
    "value",
)
RISKS = ("transfer", "injury", "rotation", "outlier", "unknown_role")

PROFILE_ALIASES = {
    "reliable": "reliable",
    "conservative": "reliable",
    "verlässlich": "reliable",
    "balanced": "balanced",
    "ausgewogen": "balanced",
    "breakout": "breakout",
    "ausbruch": "breakout",
}
MAINTENANCE_ALIASES = {
    "low": "low",
    "gering": "low",
    "normal": "normal",
    "active": "active",
    "aktiv": "active",
}
VARIATION_ALIASES = {
    "none": "none",
    "keine": "none",
    "low": "low",
    "niedrig": "low",
    "medium": "medium",
    "mittel": "medium",
    "high": "high",
    "hoch": "high",
}

PROFILE_WEIGHTS = {
    "reliable": {
        "confirmed_performance": 30,
        "minutes": 25,
        "role": 14,
        "stability": 12,
        "context": 6,
        "fitness": 7,
        "upside": 2,
        "value": 4,
    },
    "balanced": {
        "confirmed_performance": 18,
        "minutes": 23,
        "role": 13,
        "stability": 10,
        "context": 8,
        "fitness": 8,
        "upside": 10,
        "value": 10,
    },
    "breakout": {
        "confirmed_performance": 8,
        "minutes": 18,
        "role": 10,
        "stability": 6,
        "context": 8,
        "fitness": 7,
        "upside": 25,
        "value": 18,
    },
}
RISK_WEIGHTS = {
    "reliable": {
        "transfer": 0.15,
        "injury": 0.12,
        "rotation": 0.16,
        "outlier": 0.12,
        "unknown_role": 0.14,
    },
    "balanced": {
        "transfer": 0.10,
        "injury": 0.10,
        "rotation": 0.12,
        "outlier": 0.08,
        "unknown_role": 0.10,
    },
    "breakout": {
        "transfer": 0.06,
        "injury": 0.08,
        "rotation": 0.08,
        "outlier": 0.04,
        "unknown_role": 0.07,
    },
}
VARIATION_CONFIG = {
    "none": {"noise": 0.0, "gap": 0.0, "distance": 0, "avoid": 0.0},
    "low": {"noise": 1.5, "gap": 0.02, "distance": 2, "avoid": 0.8},
    "medium": {"noise": 3.5, "gap": 0.05, "distance": 4, "avoid": 1.8},
    "high": {"noise": 6.0, "gap": 0.08, "distance": 6, "avoid": 3.0},
}
DEFAULT_CLUB_CAP = {"reliable": 4, "balanced": 4, "breakout": 3}
@dataclass(frozen=True)
class Player:
    player_id: str
    name: str
    short_name: str
    club: str
    position: str
    cost: int
    points: float
    grade: float
    components: dict[str, float] = field(compare=False)
    risks: dict[str, float] = field(compare=False)
    note: str = field(default="", compare=False)
    researched: bool = field(default=False, compare=False)


@dataclass
class Squad:
    players: list[Player]
    objective_score: float

    @property
    def cost(self) -> int:
        return sum(player.cost for player in self.players)

    @property
    def ids(self) -> frozenset[str]:
        return frozenset(player.player_id for player in self.players)


def clamp(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(100.0, number))


def numeric(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return default


def percentile(value: float, sorted_values: list[float]) -> float:
    if not sorted_values:
        return 50.0
    return 100.0 * bisect.bisect_right(sorted_values, value) / len(sorted_values)


def annotation_minimums(slots: dict[str, int]) -> dict[str, int]:
    return {
        "GOALKEEPER": max(slots["GOALKEEPER"] * 2, slots["GOALKEEPER"]),
        "DEFENDER": max(slots["DEFENDER"] + 3, slots["DEFENDER"]),
        "MIDFIELDER": max(slots["MIDFIELDER"] + 3, slots["MIDFIELDER"]),
        "FORWARD": max(slots["FORWARD"] + 3, slots["FORWARD"]),
    }


def annotation_is_complete(annotation: dict[str, Any]) -> bool:
    components = annotation.get("components")
    risks = annotation.get("risks")

    def valid_scores(values: Any, keys: tuple[str, ...]) -> bool:
        if not isinstance(values, dict):
            return False
        for key in keys:
            value = values.get(key)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or not 0.0 <= float(value) <= 100.0
            ):
                return False
        return True

    return valid_scores(components, COMPONENTS) and valid_scores(risks, RISKS)


def load_annotations(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    entries = payload.get("players", payload)
    if not isinstance(entries, dict):
        raise ValueError("annotations must contain an object named 'players'")
    return {str(key): value for key, value in entries.items() if isinstance(value, dict)}


def load_players(
    path: Path,
    annotations: dict[str, dict[str, Any]],
) -> tuple[list[Player], int, dict[str, int]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))
    if not rows:
        raise ValueError("player CSV is empty")

    points_by_position: dict[str, list[float]] = {
        position: [] for position in DEFAULT_SLOTS
    }
    costs_by_position: dict[str, list[float]] = {
        position: [] for position in DEFAULT_SLOTS
    }
    for row in rows:
        position = str(row.get("Position", "")).upper()
        if position not in DEFAULT_SLOTS:
            continue
        points_by_position[position].append(numeric(row.get("Punkte")))
        costs_by_position[position].append(numeric(row.get("Marktwert")))
    for values in (*points_by_position.values(), *costs_by_position.values()):
        values.sort()

    players: list[Player] = []
    annotated_count = 0
    annotated_by_position = {position: 0 for position in DEFAULT_SLOTS}
    for row in rows:
        position = str(row.get("Position", "")).upper()
        if position not in DEFAULT_SLOTS:
            continue
        player_id = str(row.get("ID", "")).strip()
        name = str(row.get("Angezeigter Name", "")).strip()
        short_name = str(row.get("Angezeigter Name (kurz)", "")).strip() or name
        club = str(row.get("Verein", "")).strip()
        cost = int(numeric(row.get("Marktwert")))
        points = numeric(row.get("Punkte"))
        grade = numeric(row.get("Notendurchschnitt"))
        if not player_id or not name or not club or cost <= 0:
            continue

        points_pct = percentile(points, points_by_position[position])
        price_pct = percentile(cost, costs_by_position[position])
        grade_score = 50.0 if grade <= 0 else clamp((4.5 - grade) * 50.0, 50.0)
        historical = 35.0 if points <= 0 else 0.72 * points_pct + 0.28 * grade_score
        minutes = 43.0 if points <= 0 else (58.0 if points_pct < 55 else 72.0)
        role = 44.0 if points <= 0 else (55.0 if points_pct < 65 else 68.0)
        value = 0.55 * (100.0 - price_pct) + 0.45 * historical
        components = {
            "confirmed_performance": historical,
            "minutes": minutes,
            "role": role,
            "stability": 60.0,
            "context": 50.0,
            "fitness": 65.0,
            "upside": 52.0 if points <= 0 else 45.0,
            "value": value,
        }
        risks = {
            "transfer": 10.0,
            "injury": 10.0,
            "rotation": 18.0 if points > 0 else 32.0,
            "outlier": 12.0 if points_pct < 85 else 28.0,
            "unknown_role": 12.0 if points > 0 else 38.0,
        }

        annotation = annotations.get(player_id) or annotations.get(name) or {}
        if bool(annotation.get("exclude", False)):
            continue
        researched = annotation_is_complete(annotation)
        if researched:
            annotated_count += 1
            annotated_by_position[position] += 1
        for key, value in annotation.get("components", {}).items():
            if key in components:
                components[key] = clamp(value, components[key])
        for key, value in annotation.get("risks", {}).items():
            if key in risks:
                risks[key] = clamp(value, risks[key])

        players.append(
            Player(
                player_id=player_id,
                name=name,
                short_name=short_name,
                club=club,
                position=position,
                cost=cost,
                points=points,
                grade=grade,
                components=components,
                risks=risks,
                note=str(annotation.get("note", "")).strip(),
                researched=researched,
            )
        )
    return players, annotated_count, annotated_by_position


def effective_weights(profile: str, maintenance: str) -> dict[str, float]:
    weights = {key: float(value) for key, value in PROFILE_WEIGHTS[profile].items()}
    if maintenance == "low":
        weights["minutes"] += 5
        weights["role"] += 2
        weights["stability"] += 4
        weights["upside"] -= 7
        weights["value"] -= 4
    elif maintenance == "active":
        weights["upside"] += 4
        weights["value"] += 3
        weights["stability"] -= 4
        weights["minutes"] -= 3
    total = sum(max(0.0, value) for value in weights.values())
    return {key: 100.0 * max(0.0, value) / total for key, value in weights.items()}


def score_players(players: Iterable[Player], profile: str, maintenance: str) -> dict[str, float]:
    weights = effective_weights(profile, maintenance)
    risk_weights = RISK_WEIGHTS[profile]
    scores: dict[str, float] = {}
    for player in players:
        component_score = sum(
            weights[key] * player.components[key] / 100.0 for key in COMPONENTS
        )
        risk_penalty = sum(risk_weights[key] * player.risks[key] for key in RISKS)
        scores[player.player_id] = component_score - risk_penalty
    return scores


def goalkeeper_options(
    players: list[Player],
    count: int,
    budget: int,
    scores: dict[str, float],
    same_club: bool,
) -> dict[int, tuple[float, tuple[Player, ...]]]:
    by_club: dict[str, list[Player]] = {}
    for player in players:
        if player.position == "GOALKEEPER":
            by_club.setdefault(player.club, []).append(player)
    options: dict[int, tuple[float, tuple[Player, ...]]] = {}
    candidate_groups = (
        list(by_club.values())
        if same_club
        else [[player for club_players in by_club.values() for player in club_players]]
    )
    for club_players in candidate_groups:
        for combination in itertools.combinations(club_players, count):
            cost = sum(player.cost for player in combination)
            if cost > budget:
                continue
            score = sum(scores[player.player_id] for player in combination)
            current = options.get(cost)
            if current is None or score > current[0]:
                options[cost] = (score, combination)
    return options


def club_outfield_options(
    players: list[Player],
    slots: dict[str, int],
    club_cap: int,
    budget: int,
    scores: dict[str, float],
) -> dict[
    tuple[int, int, int, int],
    tuple[float, tuple[Player, ...]],
]:
    """Enumerate the exact useful selections for one club."""

    positions = ("DEFENDER", "MIDFIELDER", "FORWARD")
    position_index = {position: index for index, position in enumerate(positions)}
    states: dict[
        tuple[int, int, int, int],
        tuple[float, tuple[Player, ...]],
    ] = {(0, 0, 0, 0): (0.0, ())}
    for player in players:
        index = position_index[player.position]
        next_states = dict(states)
        for key, (score, selected) in states.items():
            counts = list(key[:3])
            if sum(counts) >= club_cap or counts[index] >= slots[player.position]:
                continue
            new_cost = key[3] + player.cost
            if new_cost > budget:
                continue
            counts[index] += 1
            new_key = (counts[0], counts[1], counts[2], new_cost)
            new_score = score + scores[player.player_id]
            current = next_states.get(new_key)
            if current is None or new_score > current[0]:
                next_states[new_key] = (new_score, selected + (player,))
        states = next_states
    return states


def outfield_options(
    players: list[Player],
    slots: dict[str, int],
    club_cap: int,
    budget: int,
    scores: dict[str, float],
) -> dict[int, tuple[float, tuple[Player, ...]]]:
    """Return the exact best cap-compliant outfield selection per cost.

    Processing one club at a time makes the cap local. Once a club has been
    merged, equal position-and-cost states can safely retain only the
    highest-scoring selection.
    """

    by_club: dict[str, list[Player]] = {}
    for player in players:
        if player.position != "GOALKEEPER":
            by_club.setdefault(player.club, []).append(player)

    states: dict[
        tuple[int, int, int, int],
        tuple[float, tuple[Player, ...]],
    ] = {(0, 0, 0, 0): (0.0, ())}
    target_counts = (
        slots["DEFENDER"],
        slots["MIDFIELDER"],
        slots["FORWARD"],
    )
    for club in sorted(by_club):
        local_options = club_outfield_options(
            by_club[club],
            slots,
            club_cap,
            budget,
            scores,
        )
        next_states: dict[
            tuple[int, int, int, int],
            tuple[float, tuple[Player, ...]],
        ] = {}
        for base_key, (base_score, base_players) in states.items():
            for local_key, (local_score, local_players) in local_options.items():
                counts = (
                    base_key[0] + local_key[0],
                    base_key[1] + local_key[1],
                    base_key[2] + local_key[2],
                )
                if any(
                    count > target
                    for count, target in zip(counts, target_counts)
                ):
                    continue
                total_cost = base_key[3] + local_key[3]
                if total_cost > budget:
                    continue
                new_key = (*counts, total_cost)
                total_score = base_score + local_score
                current = next_states.get(new_key)
                if current is None or total_score > current[0]:
                    next_states[new_key] = (
                        total_score,
                        base_players + local_players,
                    )
        states = next_states
        if not states:
            return {}

    return {
        key[3]: value
        for key, value in states.items()
        if key[:3] == target_counts
    }


def combine_options(
    option_groups: list[dict[int, tuple[float, tuple[Player, ...]]]],
    budget: int,
    minimum_spend: int,
) -> Squad | None:
    states: dict[int, tuple[float, tuple[Player, ...]]] = {0: (0.0, ())}
    for options in option_groups:
        next_states: dict[int, tuple[float, tuple[Player, ...]]] = {}
        for base_cost, (base_score, base_players) in states.items():
            for option_cost, (option_score, option_players) in options.items():
                total_cost = base_cost + option_cost
                if total_cost > budget:
                    continue
                total_score = base_score + option_score
                current = next_states.get(total_cost)
                if current is None or total_score > current[0]:
                    next_states[total_cost] = (
                        total_score,
                        base_players + option_players,
                    )
        states = next_states
        if not states:
            return None
    eligible_states = {
        cost: value for cost, value in states.items() if cost >= minimum_spend
    }
    if not eligible_states:
        return None
    _, (score, selected) = max(
        eligible_states.items(),
        key=lambda item: item[1][0],
    )
    return Squad(list(selected), score)


def optimize(
    players: list[Player],
    budget: int,
    scores: dict[str, float],
    club_cap: int,
    minimum_spend: int,
    slots: dict[str, int],
    same_club_goalkeepers: bool = True,
) -> Squad:
    gk_options = goalkeeper_options(
        players,
        slots["GOALKEEPER"],
        budget,
        scores,
        same_club_goalkeepers,
    )
    if not gk_options:
        requirement = (
            "one club"
            if same_club_goalkeepers
            else "the complete goalkeeper pool"
        )
        raise ValueError(
            "the required number of eligible goalkeepers cannot be selected from "
            f"{requirement} within budget"
        )
    field_options = outfield_options(
        players,
        slots,
        club_cap,
        budget,
        scores,
    )
    if not field_options:
        raise ValueError(
            "no outfield selection satisfies the positional and club-cap constraints"
        )
    squad = combine_options(
        [gk_options, field_options],
        budget,
        minimum_spend,
    )
    if squad is None:
        raise ValueError("no complete squad fits the supplied budget and minimum spend")
    return squad


def load_avoid_ids(paths: list[Path]) -> set[str]:
    avoid: set[str] = set()
    for path in paths:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        entries = payload.get("squad", payload.get("players", []))
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, str):
                avoid.add(entry)
            elif isinstance(entry, dict):
                value = entry.get("id") or entry.get("player_id") or entry.get("name")
                if value:
                    avoid.add(str(value))
    return avoid


def varied_squad(
    players: list[Player],
    budget: int,
    base_scores: dict[str, float],
    profile: str,
    variation: str,
    seed: int,
    club_cap: int,
    minimum_spend: int,
    slots: dict[str, int],
    avoid_ids: set[str],
    same_club_goalkeepers: bool = True,
) -> tuple[Squad, Squad, int, bool]:
    optimum = optimize(
        players,
        budget,
        base_scores,
        club_cap,
        minimum_spend,
        slots,
        same_club_goalkeepers,
    )
    config = VARIATION_CONFIG[variation]
    if variation == "none":
        return optimum, optimum, 0, True

    profile_factor = 0.75 if profile == "reliable" else (1.20 if profile == "breakout" else 1.0)
    allowed_gap = config["gap"] * profile_factor
    target_distance = int(config["distance"])
    rng = random.Random(seed)
    accepted: dict[tuple[str, ...], tuple[int, float, Squad]] = {}
    optimum_score = sum(base_scores[player.player_id] for player in optimum.players)

    for _ in range(120):
        noisy_scores: dict[str, float] = {}
        for player in players:
            avoid_match = player.player_id in avoid_ids or player.name in avoid_ids
            avoid_penalty = config["avoid"] if avoid_match else 0.0
            noisy_scores[player.player_id] = (
                base_scores[player.player_id]
                + rng.uniform(-config["noise"], config["noise"])
                - avoid_penalty
            )
        candidate = optimize(
            players,
            budget,
            noisy_scores,
            club_cap,
            minimum_spend,
            slots,
            same_club_goalkeepers,
        )
        baseline_score = sum(base_scores[player.player_id] for player in candidate.players)
        gap = (optimum_score - baseline_score) / max(abs(optimum_score), 1e-9)
        if gap > allowed_gap + 1e-9:
            continue
        distance = len(optimum.ids.symmetric_difference(candidate.ids)) // 2
        key = tuple(sorted(candidate.ids))
        accepted[key] = (distance, rng.random(), Squad(candidate.players, baseline_score))

    if not accepted:
        return optimum, optimum, 0, False
    qualified = [value for value in accepted.values() if value[0] >= target_distance]
    pool = qualified or list(accepted.values())
    distance, _, chosen = min(
        pool,
        key=lambda value: (abs(value[0] - target_distance), -value[1]),
    )
    return chosen, optimum, distance, bool(qualified)


def output_payload(
    squad: Squad,
    optimum: Squad,
    base_scores: dict[str, float],
    args: argparse.Namespace,
    seed: int,
    distance: int,
    variation_target_met: bool,
    annotated_count: int,
    annotated_by_position: dict[str, int],
    annotation_requirements: dict[str, int],
    annotated_goalkeeper_blocks: int,
) -> dict[str, Any]:
    squad_score = sum(base_scores[player.player_id] for player in squad.players)
    optimum_score = sum(base_scores[player.player_id] for player in optimum.players)
    quality_gap = (
        100.0
        * (optimum_score - squad_score)
        / max(abs(optimum_score), 1e-9)
    )
    club_counts: dict[str, int] = {}
    for player in squad.players:
        if player.position != "GOALKEEPER":
            club_counts[player.club] = club_counts.get(player.club, 0) + 1
    warnings: list[str] = []
    missing_annotations = {
        position: {
            "actual": annotated_by_position[position],
            "required": minimum,
        }
        for position, minimum in annotation_requirements.items()
        if annotated_by_position[position] < minimum
    }
    if missing_annotations:
        warnings.append(
            "Current role, fitness and transfer annotations are below the recommended "
            f"coverage: {missing_annotations}"
        )
    overloaded = {
        club: count
        for club, count in club_counts.items()
        if count > args.max_outfield_per_club
    }
    if overloaded:
        warnings.append(f"Could not fully satisfy outfield club cap: {overloaded}")
    if not variation_target_met:
        warnings.append(
            "The requested minimum squad variation could not be reached inside "
            "the quality and roster constraints."
        )
    if args.budget - squad.cost > args.budget * 0.10:
        warnings.append(
            "More than 10% of the budget remains unused. Expand the researched "
            "candidate pool or set an explicit minimum spend after confirming "
            "that a complete squad can satisfy it."
        )

    ordered = sorted(
        squad.players,
        key=lambda player: (
            POSITION_ORDER[player.position],
            -base_scores[player.player_id],
            player.name,
        ),
    )
    return {
        "profile": args.profile,
        "maintenance": args.maintenance,
        "variation": args.variation,
        "seed": seed,
        "budget": args.budget,
        "cost": squad.cost,
        "remaining_budget": args.budget - squad.cost,
        "score": round(squad_score, 3),
        "optimal_score": round(optimum_score, 3),
        "quality_gap_percent": round(max(0.0, quality_gap), 3),
        "distance_from_optimum": distance,
        "variation_target_met": variation_target_met,
        "goalkeeper_mode": (
            "mixed" if args.mixed_goalkeepers else "same_club"
        ),
        "annotated_players": annotated_count,
        "annotated_players_by_position": annotated_by_position,
        "annotated_goalkeeper_blocks": annotated_goalkeeper_blocks,
        "warnings": warnings,
        "squad": [
            {
                "id": player.player_id,
                "name": player.name,
                "short_name": player.short_name,
                "club": player.club,
                "position": player.position,
                "cost": player.cost,
                "score": round(base_scores[player.player_id], 3),
                "note": player.note,
            }
            for player in ordered
        ],
    }


def shortlist_payload(
    players: list[Player],
    scores: dict[str, float],
    profile: str,
    slots: dict[str, int],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "profile": profile,
        "purpose": (
            "Research these baseline and unproven-value candidates before final optimization."
        ),
        "shortlist": {},
    }
    for position, slot_count in slots.items():
        candidates = [player for player in players if player.position == position]
        confirmed = sorted(
            candidates,
            key=lambda player: (
                -scores[player.player_id],
                player.cost,
                player.name,
            ),
        )[: max(6, slot_count * 2)]
        unproven = sorted(
            (player for player in candidates if player.points <= 0),
            key=lambda player: (
                -(
                    player.components["upside"]
                    + player.components["value"]
                    - player.risks["unknown_role"] * 0.5
                ),
                player.cost,
                player.name,
            ),
        )[: max(4, slot_count)]

        def serialize(player: Player) -> dict[str, Any]:
            return {
                "id": player.player_id,
                "name": player.name,
                "club": player.club,
                "position": player.position,
                "cost": player.cost,
                "points": player.points,
                "grade": player.grade,
                "baseline_score": round(scores[player.player_id], 3),
            }

        result["shortlist"][position] = {
            "confirmed": [serialize(player) for player in confirmed],
            "unproven_value": [serialize(player) for player in unproven],
        }
    return result


def print_text(payload: dict[str, Any]) -> None:
    print(
        f"Profile={payload['profile']} variation={payload['variation']} "
        f"maintenance={payload['maintenance']} seed={payload['seed']}"
    )
    print(
        f"Cost={payload['cost']} remaining={payload['remaining_budget']} "
        f"quality_gap={payload['quality_gap_percent']}%"
    )
    current_position = None
    for player in payload["squad"]:
        if player["position"] != current_position:
            current_position = player["position"]
            print(f"\n{current_position}")
        print(
            f"- {player['name']} | {player['club']} | "
            f"{player['cost']} | score {player['score']}"
        )
    for warning in payload["warnings"]:
        print(f"\nWARNING: {warning}", file=sys.stderr)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--players", type=Path, required=True, help="Official Kicker semicolon CSV")
    parser.add_argument("--annotations", type=Path, help="Current player annotations JSON")
    parser.add_argument("--budget", type=int, required=True, help="Budget in whole euros")
    parser.add_argument(
        "--min-spend-ratio",
        type=float,
        default=0.0,
        help="Optional minimum fraction of budget to spend; default 0",
    )
    parser.add_argument("--goalkeepers", type=int, default=3)
    parser.add_argument(
        "--mixed-goalkeepers",
        action="store_true",
        help="Allow goalkeepers from different clubs; default is one club block",
    )
    parser.add_argument("--defenders", type=int, default=7)
    parser.add_argument("--midfielders", type=int, default=7)
    parser.add_argument("--forwards", type=int, default=5)
    parser.add_argument("--profile", default="reliable", choices=sorted(PROFILE_ALIASES))
    parser.add_argument("--maintenance", default="low", choices=sorted(MAINTENANCE_ALIASES))
    parser.add_argument("--variation", default="medium", choices=sorted(VARIATION_ALIASES))
    parser.add_argument("--seed", type=int, help="Reproducible variation seed")
    parser.add_argument(
        "--max-outfield-per-club",
        type=int,
        help="Maximum outfield players from one club",
    )
    parser.add_argument(
        "--avoid-roster",
        type=Path,
        action="append",
        default=[],
        help="Prior optimizer JSON whose players should be de-emphasized; repeatable",
    )
    parser.add_argument(
        "--shortlist-only",
        action="store_true",
        help="Emit a research shortlist and skip final optimization",
    )
    parser.add_argument(
        "--allow-unannotated",
        action="store_true",
        help="Allow incomplete current annotations for technical smoke tests only",
    )
    parser.add_argument("--format", choices=("json", "text"), default="text")
    parser.add_argument("--output", type=Path, help="Optional output file")
    args = parser.parse_args()
    args.profile = PROFILE_ALIASES[args.profile]
    args.maintenance = MAINTENANCE_ALIASES[args.maintenance]
    args.variation = VARIATION_ALIASES[args.variation]
    if args.max_outfield_per_club is None:
        args.max_outfield_per_club = DEFAULT_CLUB_CAP[args.profile]
    if args.max_outfield_per_club < 1:
        parser.error("--max-outfield-per-club must be positive")
    if not 0.0 <= args.min_spend_ratio <= 1.0:
        parser.error("--min-spend-ratio must be between 0 and 1")
    args.slots = {
        "GOALKEEPER": args.goalkeepers,
        "DEFENDER": args.defenders,
        "MIDFIELDER": args.midfielders,
        "FORWARD": args.forwards,
    }
    if any(value < 1 for value in args.slots.values()):
        parser.error("all positional slot counts must be positive")
    return args


def main() -> int:
    args = parse_args()
    seed = args.seed if args.seed is not None else secrets.randbelow(2**31)
    annotations = load_annotations(args.annotations)
    players, annotated_count, annotated_by_position = load_players(
        args.players,
        annotations,
    )
    base_scores = score_players(players, args.profile, args.maintenance)
    if args.shortlist_only:
        payload = shortlist_payload(
            players,
            base_scores,
            args.profile,
            args.slots,
        )
        rendered = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        print(rendered)
        return 0

    required_annotations = annotation_minimums(args.slots)
    missing_annotations = {
        position: {
            "actual": annotated_by_position[position],
            "required": minimum,
        }
        for position, minimum in required_annotations.items()
        if annotated_by_position[position] < minimum
    }
    researched_goalkeepers_by_club: dict[str, int] = {}
    for player in players:
        if player.position == "GOALKEEPER" and player.researched:
            researched_goalkeepers_by_club[player.club] = (
                researched_goalkeepers_by_club.get(player.club, 0) + 1
            )
    annotated_goalkeeper_blocks = sum(
        count >= args.slots["GOALKEEPER"]
        for count in researched_goalkeepers_by_club.values()
    )
    goalkeeper_blocks_missing = (
        not args.mixed_goalkeepers and annotated_goalkeeper_blocks < 2
    )
    if (missing_annotations or goalkeeper_blocks_missing) and not args.allow_unannotated:
        goalkeeper_status = (
            "mixed-goalkeeper mode requested"
            if args.mixed_goalkeepers
            else f"complete goalkeeper blocks: {annotated_goalkeeper_blocks}/2"
        )
        print(
            "Current annotations are incomplete. Research and annotate the shortlist "
            f"before final optimization: {missing_annotations}; "
            f"{goalkeeper_status}. "
            "Use --allow-unannotated only for a technical smoke test.",
            file=sys.stderr,
        )
        return 2

    eligible_players = (
        players
        if args.allow_unannotated
        else [player for player in players if player.researched]
    )
    eligible_scores = {
        player.player_id: base_scores[player.player_id]
        for player in eligible_players
    }
    avoid_ids = load_avoid_ids(args.avoid_roster)
    minimum_spend = math.ceil(args.budget * args.min_spend_ratio)
    squad, optimum, distance, variation_target_met = varied_squad(
        players=eligible_players,
        budget=args.budget,
        base_scores=eligible_scores,
        profile=args.profile,
        variation=args.variation,
        seed=seed,
        club_cap=args.max_outfield_per_club,
        minimum_spend=minimum_spend,
        slots=args.slots,
        avoid_ids=avoid_ids,
        same_club_goalkeepers=not args.mixed_goalkeepers,
    )
    payload = output_payload(
        squad=squad,
        optimum=optimum,
        base_scores=eligible_scores,
        args=args,
        seed=seed,
        distance=distance,
        variation_target_met=variation_target_met,
        annotated_count=annotated_count,
        annotated_by_position=annotated_by_position,
        annotation_requirements=required_annotations,
        annotated_goalkeeper_blocks=annotated_goalkeeper_blocks,
    )
    rendered = (
        json.dumps(payload, ensure_ascii=False, indent=2)
        if args.format == "json"
        else None
    )
    if args.output:
        args.output.write_text(
            rendered
            if rendered is not None
            else json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if rendered is not None:
        print(rendered)
    else:
        print_text(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
