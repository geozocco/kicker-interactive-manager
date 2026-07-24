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
FORMATIONS = (
    (3, 4, 3),
    (3, 5, 2),
    (4, 3, 3),
    (4, 4, 2),
    (4, 5, 1),
    (5, 3, 2),
    (5, 4, 1),
)
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
    reliable_anchor: bool = field(default=False, compare=False)
    anchor_basis: str = field(default="none", compare=False)
    anchor_reason: str = field(default="", compare=False)
    benchmark: bool = field(default=False, compare=False)
    evidence: tuple[Any, ...] = field(default=(), compare=False)


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
        "DEFENDER": slots["DEFENDER"] * 2,
        "MIDFIELDER": slots["MIDFIELDER"] * 2,
        "FORWARD": slots["FORWARD"] * 2,
    }


def evidence_is_complete(annotation: dict[str, Any]) -> bool:
    evidence = annotation.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return False
    for item in evidence:
        if not isinstance(item, dict):
            return False
        if not all(
            str(item.get(key, "")).strip()
            for key in ("claim", "source_url", "checked_at")
        ):
            return False
    return True


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

    if not valid_scores(components, COMPONENTS) or not valid_scores(risks, RISKS):
        return False
    anchor_setting = annotation.get("reliable_anchor")
    anchor_setting_is_valid = isinstance(anchor_setting, bool) or (
        isinstance(anchor_setting, str)
        and anchor_setting.strip().lower() == "auto"
    )
    if not anchor_setting_is_valid:
        return False
    if not isinstance(annotation.get("benchmark"), bool):
        return False
    if (
        anchor_setting is True or isinstance(anchor_setting, str)
    ) and not str(
        annotation.get("anchor_reason", "")
    ).strip():
        return False
    return evidence_is_complete(annotation)


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
        reliable_anchor, anchor_basis = classify_reliable_anchor(
            annotation=annotation,
            researched=researched,
            position=position,
            price_percentile=price_pct,
            components=components,
            risks=risks,
        )
        raw_evidence = annotation.get("evidence", [])
        evidence = (
            tuple(raw_evidence)
            if isinstance(raw_evidence, list)
            else ()
        )

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
                reliable_anchor=reliable_anchor,
                anchor_basis=anchor_basis,
                anchor_reason=str(annotation.get("anchor_reason", "")).strip(),
                benchmark=bool(annotation.get("benchmark", False)),
                evidence=evidence,
            )
        )
    return players, annotated_count, annotated_by_position


def classify_reliable_anchor(
    annotation: dict[str, Any],
    researched: bool,
    position: str,
    price_percentile: float,
    components: dict[str, float],
    risks: dict[str, float],
) -> tuple[bool, str]:
    """Classify repeatable premium field players without hard-coded names."""

    if not researched or position == "GOALKEEPER":
        return False, "none"

    setting = annotation.get("reliable_anchor", "auto")
    if isinstance(setting, str):
        normalized = setting.strip().lower()
    elif setting is True:
        normalized = "eligible"
    elif setting is False:
        normalized = "ineligible"
    else:
        normalized = "auto"
    if normalized in {"false", "no", "ineligible"}:
        return False, "explicit"

    safety_gate = (
        components["fitness"] >= 60
        and risks["transfer"] <= 35
        and risks["injury"] <= 50
        and risks["rotation"] <= 35
        and risks["outlier"] <= 35
        and risks["unknown_role"] <= 30
    )
    if normalized in {"true", "yes", "eligible"}:
        has_reason = bool(str(annotation.get("anchor_reason", "")).strip())
        quality_gate = (
            components["confirmed_performance"] >= 78
            and components["minutes"] >= 75
            and components["role"] >= 70
            and components["stability"] >= 65
        )
        return safety_gate and quality_gate and has_reason, "explicit"

    automatic_gate = (
        components["confirmed_performance"] >= 78
        and components["minutes"] >= 75
        and components["role"] >= 70
        and components["stability"] >= 65
        and components["fitness"] >= 70
        and risks["transfer"] <= 20
        and risks["injury"] <= 35
        and risks["rotation"] <= 20
        and risks["outlier"] <= 35
        and risks["unknown_role"] <= 20
        and (
            price_percentile >= 65
            or (
                components["confirmed_performance"] >= 85
                and components["role"] >= 80
            )
        )
    )
    return safety_gate and automatic_gate, "auto"


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


def core_weighted_scores(
    players: list[Player],
    scores: dict[str, float],
    profile: str,
    maintenance: str,
) -> tuple[dict[str, float], dict[str, float]]:
    """Emphasize the likely scoring core over equally strong reserve depth.

    Only the conservative, low-maintenance default uses the stronger curve.
    It remains additive so all budget, position, goalkeeper and club
    constraints stay exact and the distance solver remains fast.
    """

    if profile != "reliable" or maintenance != "low":
        return dict(scores), {player.player_id: 1.0 for player in players}

    weighted: dict[str, float] = {}
    multipliers: dict[str, float] = {}
    for position in DEFAULT_SLOTS:
        position_players = [
            player for player in players if player.position == position
        ]
        ordered_values = sorted(scores[player.player_id] for player in position_players)
        for player in position_players:
            if len(ordered_values) <= 1:
                rank = 1.0
            else:
                rank = (
                    bisect.bisect_right(ordered_values, scores[player.player_id]) - 1
                ) / (len(ordered_values) - 1)
            multiplier = 0.30 + 0.70 * rank**2
            raw_score = scores[player.player_id]
            weighted[player.player_id] = (
                raw_score * multiplier if raw_score >= 0.0 else raw_score
            )
            multipliers[player.player_id] = multiplier
    return weighted, multipliers


def best_starting_lineup(
    players: list[Player],
    scores: dict[str, float],
    min_reliable_anchors: int = 0,
) -> tuple[str, frozenset[str]]:
    """Infer the strongest legal eleven while keeping the reliable core."""

    by_position = {
        position: [player for player in players if player.position == position]
        for position in DEFAULT_SLOTS
    }
    if not by_position["GOALKEEPER"]:
        return "", frozenset()
    goalkeeper = max(
        by_position["GOALKEEPER"],
        key=lambda player: (
            scores[player.player_id],
            -player.cost,
            player.name,
        ),
    )
    best_any: tuple[float, str, frozenset[str]] | None = None
    best_anchor_safe: tuple[float, str, frozenset[str]] | None = None
    for defenders, midfielders, forwards in FORMATIONS:
        counts = {
            "DEFENDER": defenders,
            "MIDFIELDER": midfielders,
            "FORWARD": forwards,
        }
        if any(len(by_position[position]) < count for position, count in counts.items()):
            continue
        formation = f"{defenders}-{midfielders}-{forwards}"
        for defender_group in itertools.combinations(
            by_position["DEFENDER"],
            defenders,
        ):
            for midfielder_group in itertools.combinations(
                by_position["MIDFIELDER"],
                midfielders,
            ):
                for forward_group in itertools.combinations(
                    by_position["FORWARD"],
                    forwards,
                ):
                    selected = (
                        goalkeeper,
                        *defender_group,
                        *midfielder_group,
                        *forward_group,
                    )
                    score = sum(scores[player.player_id] for player in selected)
                    ids = frozenset(player.player_id for player in selected)
                    candidate = (score, formation, ids)
                    if best_any is None or score > best_any[0]:
                        best_any = candidate
                    anchor_count = sum(
                        player.reliable_anchor for player in selected
                    )
                    if anchor_count < min_reliable_anchors:
                        continue
                    if best_anchor_safe is None or score > best_anchor_safe[0]:
                        best_anchor_safe = candidate
    chosen = best_anchor_safe or best_any
    if chosen is None:
        return "", frozenset()
    return chosen[1], chosen[2]


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
    min_reliable_anchors: int = 0,
) -> dict[
    tuple[int, int, int, int, int],
    tuple[float, tuple[Player, ...]],
]:
    """Enumerate the exact useful selections for one club."""

    positions = ("DEFENDER", "MIDFIELDER", "FORWARD")
    position_index = {position: index for index, position in enumerate(positions)}
    states: dict[
        tuple[int, int, int, int, int],
        tuple[float, tuple[Player, ...]],
    ] = {(0, 0, 0, 0, 0): (0.0, ())}
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
            anchors = min(
                min_reliable_anchors,
                key[4] + int(player.reliable_anchor),
            )
            new_key = (counts[0], counts[1], counts[2], new_cost, anchors)
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
    min_reliable_anchors: int = 0,
) -> dict[tuple[int, int], tuple[float, tuple[Player, ...]]]:
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
        tuple[int, int, int, int, int],
        tuple[float, tuple[Player, ...]],
    ] = {(0, 0, 0, 0, 0): (0.0, ())}
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
            min_reliable_anchors,
        )
        next_states: dict[
            tuple[int, int, int, int, int],
            tuple[float, tuple[Player, ...]],
        ] = {}
        for base_key, (base_score, base_players) in states.items():
            for local_key, (local_score, local_players) in local_options.items():
                defender_count = base_key[0] + local_key[0]
                midfielder_count = base_key[1] + local_key[1]
                forward_count = base_key[2] + local_key[2]
                if (
                    defender_count > target_counts[0]
                    or midfielder_count > target_counts[1]
                    or forward_count > target_counts[2]
                ):
                    continue
                total_cost = base_key[3] + local_key[3]
                if total_cost > budget:
                    continue
                anchors = base_key[4] + local_key[4]
                if anchors > min_reliable_anchors:
                    anchors = min_reliable_anchors
                new_key = (
                    defender_count,
                    midfielder_count,
                    forward_count,
                    total_cost,
                    anchors,
                )
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
        (key[3], key[4]): value
        for key, value in states.items()
        if key[:3] == target_counts
    }


def combine_options(
    goalkeeper_group: dict[int, tuple[float, tuple[Player, ...]]],
    field_group: dict[tuple[int, int], tuple[float, tuple[Player, ...]]],
    budget: int,
    minimum_spend: int,
    min_reliable_anchors: int = 0,
) -> tuple[Squad | None, int]:
    states: dict[
        tuple[int, int],
        tuple[float, tuple[Player, ...]],
    ] = {}
    for goalkeeper_cost, (goalkeeper_score, goalkeepers) in goalkeeper_group.items():
        for (field_cost, anchors), (field_score, fielders) in field_group.items():
            total_cost = goalkeeper_cost + field_cost
            if total_cost > budget:
                continue
            key = (total_cost, anchors)
            total_score = goalkeeper_score + field_score
            current = states.get(key)
            if current is None or total_score > current[0]:
                states[key] = (total_score, goalkeepers + fielders)
    spend_eligible = {
        key: value for key, value in states.items() if key[0] >= minimum_spend
    }
    max_reachable = max((key[1] for key in spend_eligible), default=0)
    eligible_states = {
        key: value
        for key, value in spend_eligible.items()
        if key[1] >= min_reliable_anchors
    }
    if not eligible_states:
        return None, max_reachable
    _, (score, selected) = max(
        eligible_states.items(),
        key=lambda item: item[1][0],
    )
    return Squad(list(selected), score), max_reachable


def optimize(
    players: list[Player],
    budget: int,
    scores: dict[str, float],
    club_cap: int,
    minimum_spend: int,
    slots: dict[str, int],
    same_club_goalkeepers: bool = True,
    min_reliable_anchors: int = 0,
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
        min_reliable_anchors,
    )
    if not field_options:
        raise ValueError(
            "no outfield selection satisfies the positional and club-cap constraints"
        )
    squad, max_reachable_anchors = combine_options(
        gk_options,
        field_options,
        budget,
        minimum_spend,
        min_reliable_anchors,
    )
    if squad is None:
        if min_reliable_anchors > 0:
            eligible_anchors = sum(
                player.reliable_anchor
                for player in players
                if player.position != "GOALKEEPER"
            )
            raise ValueError(
                "reliable-anchor policy is infeasible: "
                f"required={min_reliable_anchors}, "
                f"eligible={eligible_anchors}, "
                "max reachable under roster, budget and club constraints="
                f"{max_reachable_anchors}"
            )
        raise ValueError("no complete squad fits the supplied budget and minimum spend")
    return squad


def distance_goalkeeper_options(
    players: list[Player],
    count: int,
    budget: int,
    scores: dict[str, float],
    same_club: bool,
    reference_ids: frozenset[str],
    distance_cap: int,
) -> dict[tuple[int, int], tuple[float, tuple[Player, ...]]]:
    """Return exact goalkeeper options keyed by cost and distance bucket."""

    by_club: dict[str, list[Player]] = {}
    for player in players:
        if player.position == "GOALKEEPER":
            by_club.setdefault(player.club, []).append(player)
    options: dict[
        tuple[int, int],
        tuple[float, tuple[Player, ...]],
    ] = {}
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
            distance = sum(
                player.player_id not in reference_ids for player in combination
            )
            if distance > distance_cap:
                continue
            score = sum(scores[player.player_id] for player in combination)
            key = (cost, distance)
            current = options.get(key)
            if current is None or score > current[0]:
                options[key] = (score, combination)
    return options


def distance_club_outfield_options(
    players: list[Player],
    slots: dict[str, int],
    club_cap: int,
    budget: int,
    scores: dict[str, float],
    reference_ids: frozenset[str],
    distance_cap: int,
    min_reliable_anchors: int = 0,
) -> dict[
    tuple[int, int, int, int, int, int],
    tuple[float, tuple[Player, ...]],
]:
    """Enumerate exact selections for one club with a distance bucket."""

    positions = ("DEFENDER", "MIDFIELDER", "FORWARD")
    position_index = {position: index for index, position in enumerate(positions)}
    states: dict[
        tuple[int, int, int, int, int, int],
        tuple[float, tuple[Player, ...]],
    ] = {(0, 0, 0, 0, 0, 0): (0.0, ())}
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
            distance = key[4] + (player.player_id not in reference_ids)
            if distance > distance_cap:
                continue
            anchors = min(
                min_reliable_anchors,
                key[5] + int(player.reliable_anchor),
            )
            new_key = (
                counts[0],
                counts[1],
                counts[2],
                new_cost,
                distance,
                anchors,
            )
            new_score = score + scores[player.player_id]
            current = next_states.get(new_key)
            if current is None or new_score > current[0]:
                next_states[new_key] = (new_score, selected + (player,))
        states = next_states
    return states


def distance_outfield_options(
    players: list[Player],
    slots: dict[str, int],
    club_cap: int,
    budget: int,
    scores: dict[str, float],
    reference_ids: frozenset[str],
    distance_cap: int,
    min_reliable_anchors: int = 0,
) -> dict[tuple[int, int, int], tuple[float, tuple[Player, ...]]]:
    """Return exact outfield options up to the requested distance."""

    by_club: dict[str, list[Player]] = {}
    for player in players:
        if player.position != "GOALKEEPER":
            by_club.setdefault(player.club, []).append(player)

    states: dict[
        tuple[int, int, int, int, int, int],
        tuple[float, tuple[Player, ...]],
    ] = {(0, 0, 0, 0, 0, 0): (0.0, ())}
    target_counts = (
        slots["DEFENDER"],
        slots["MIDFIELDER"],
        slots["FORWARD"],
    )
    for club in sorted(by_club):
        local_options = distance_club_outfield_options(
            by_club[club],
            slots,
            club_cap,
            budget,
            scores,
            reference_ids,
            distance_cap,
            min_reliable_anchors,
        )
        next_states: dict[
            tuple[int, int, int, int, int, int],
            tuple[float, tuple[Player, ...]],
        ] = {}
        for base_key, (base_score, base_players) in states.items():
            for local_key, (local_score, local_players) in local_options.items():
                defender_count = base_key[0] + local_key[0]
                midfielder_count = base_key[1] + local_key[1]
                forward_count = base_key[2] + local_key[2]
                if (
                    defender_count > target_counts[0]
                    or midfielder_count > target_counts[1]
                    or forward_count > target_counts[2]
                ):
                    continue
                total_cost = base_key[3] + local_key[3]
                if total_cost > budget:
                    continue
                distance = base_key[4] + local_key[4]
                if distance > distance_cap:
                    continue
                anchors = base_key[5] + local_key[5]
                if anchors > min_reliable_anchors:
                    anchors = min_reliable_anchors
                new_key = (
                    defender_count,
                    midfielder_count,
                    forward_count,
                    total_cost,
                    distance,
                    anchors,
                )
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
        (key[3], key[4], key[5]): value
        for key, value in states.items()
        if key[:3] == target_counts
    }


def combine_distance_options(
    goalkeeper_group: dict[
        tuple[int, int], tuple[float, tuple[Player, ...]]
    ],
    field_group: dict[
        tuple[int, int, int], tuple[float, tuple[Player, ...]]
    ],
    budget: int,
    minimum_spend: int,
    distance_cap: int,
    min_reliable_anchors: int = 0,
) -> dict[int, Squad]:
    """Combine option groups and retain the exact best squad per bucket."""

    states: dict[
        tuple[int, int, int],
        tuple[float, tuple[Player, ...]],
    ] = {}
    for goalkeeper_key, (goalkeeper_score, goalkeepers) in goalkeeper_group.items():
        for field_key, (field_score, fielders) in field_group.items():
            total_cost = goalkeeper_key[0] + field_key[0]
            if total_cost > budget:
                continue
            distance = goalkeeper_key[1] + field_key[1]
            if distance > distance_cap:
                continue
            anchors = field_key[2]
            new_key = (total_cost, distance, anchors)
            total_score = goalkeeper_score + field_score
            current = states.get(new_key)
            if current is None or total_score > current[0]:
                states[new_key] = (
                    total_score,
                    goalkeepers + fielders,
                )

    best_by_distance: dict[int, Squad] = {}
    for (cost, distance, anchors), (score, selected) in states.items():
        if cost < minimum_spend or anchors < min_reliable_anchors:
            continue
        current = best_by_distance.get(distance)
        if current is None or score > current.objective_score:
            best_by_distance[distance] = Squad(list(selected), score)
    return best_by_distance


def optimize_distance_buckets(
    players: list[Player],
    budget: int,
    scores: dict[str, float],
    club_cap: int,
    minimum_spend: int,
    slots: dict[str, int],
    reference_ids: frozenset[str],
    distance_cap: int,
    same_club_goalkeepers: bool = True,
    min_reliable_anchors: int = 0,
) -> dict[int, Squad]:
    """Return the exact best squad for every capped distance bucket."""

    if distance_cap < 0:
        raise ValueError("distance cap cannot be negative")
    gk_options = distance_goalkeeper_options(
        players,
        slots["GOALKEEPER"],
        budget,
        scores,
        same_club_goalkeepers,
        reference_ids,
        distance_cap,
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
    field_options = distance_outfield_options(
        players,
        slots,
        club_cap,
        budget,
        scores,
        reference_ids,
        distance_cap,
        min_reliable_anchors,
    )
    if not field_options:
        raise ValueError(
            "no outfield selection satisfies the positional and club-cap constraints"
        )
    squads = combine_distance_options(
        gk_options,
        field_options,
        budget,
        minimum_spend,
        distance_cap,
        min_reliable_anchors,
    )
    if not squads:
        raise ValueError("no complete squad fits the supplied budget and minimum spend")
    return squads


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
    min_reliable_anchors: int = 0,
) -> tuple[Squad, Squad, int, bool]:
    optimum = optimize(
        players,
        budget,
        base_scores,
        club_cap,
        minimum_spend,
        slots,
        same_club_goalkeepers,
        min_reliable_anchors,
    )
    config = VARIATION_CONFIG[variation]
    if variation == "none":
        return optimum, optimum, 0, True

    profile_factor = (
        0.75
        if profile == "reliable"
        else (1.20 if profile == "breakout" else 1.0)
    )
    allowed_gap = config["gap"] * profile_factor
    target_distance = int(config["distance"])
    optimum_score = sum(base_scores[player.player_id] for player in optimum.players)
    score_denominator = max(abs(optimum_score), 1e-9)
    quality_floor = optimum_score - allowed_gap * score_denominator
    base_buckets = optimize_distance_buckets(
        players,
        budget,
        base_scores,
        club_cap,
        minimum_spend,
        slots,
        optimum.ids,
        target_distance,
        same_club_goalkeepers,
        min_reliable_anchors,
    )
    base_bucket_scores = {
        distance: sum(
            base_scores[player.player_id] for player in candidate.players
        )
        for distance, candidate in base_buckets.items()
    }

    if (
        target_distance in base_buckets
        and base_bucket_scores[target_distance] >= quality_floor
    ):
        chosen_bucket = target_distance
        variation_target_met = True
    else:
        feasible_buckets = [
            distance
            for distance, score in base_bucket_scores.items()
            if distance < target_distance and score >= quality_floor
        ]
        chosen_bucket = max(feasible_buckets, default=0)
        variation_target_met = False

    base_candidate = base_buckets[chosen_bucket]
    base_candidate_score = base_bucket_scores[chosen_bucket]
    slack = max(0.0, base_candidate_score - quality_floor)
    squad_size = sum(slots.values())
    # For N-player squads and per-player perturbations in [-a, a], two
    # perturbation sums differ by at most 2*N*a. Using a quarter of the
    # available slack therefore leaves a defensive half-slack quality margin.
    max_player_perturbation = (
        slack / (4.0 * squad_size)
        if squad_size > 0
        else 0.0
    )

    rng = random.Random(seed)
    raw_preferences: dict[str, float] = {}
    for player in sorted(players, key=lambda item: (item.player_id, item.name)):
        avoid_match = player.player_id in avoid_ids or player.name in avoid_ids
        avoid_penalty = config["avoid"] if avoid_match else 0.0
        raw_preferences[player.player_id] = (
            rng.uniform(-config["noise"], config["noise"]) - avoid_penalty
        )
    largest_preference = max(
        (abs(value) for value in raw_preferences.values()),
        default=0.0,
    )
    preference_scale = (
        min(1.0, max_player_perturbation / largest_preference)
        if largest_preference > 0.0
        else 0.0
    )
    seeded_scores = {
        player.player_id: (
            base_scores[player.player_id]
            + raw_preferences[player.player_id] * preference_scale
        )
        for player in players
    }
    seeded_buckets = optimize_distance_buckets(
        players,
        budget,
        seeded_scores,
        club_cap,
        minimum_spend,
        slots,
        optimum.ids,
        target_distance,
        same_club_goalkeepers,
        min_reliable_anchors,
    )
    seeded_candidate = seeded_buckets[chosen_bucket]
    seeded_baseline_score = sum(
        base_scores[player.player_id] for player in seeded_candidate.players
    )
    if seeded_baseline_score < quality_floor:
        chosen = Squad(base_candidate.players, base_candidate_score)
    else:
        chosen = Squad(seeded_candidate.players, seeded_baseline_score)

    distance = len(optimum.ids.symmetric_difference(chosen.ids)) // 2
    if variation_target_met and distance != target_distance:
        raise RuntimeError("distance-aware optimizer violated the exact target distance")
    if not variation_target_met and distance != chosen_bucket:
        raise RuntimeError("distance-aware optimizer returned the wrong distance bucket")
    return chosen, optimum, distance, variation_target_met


def output_payload(
    squad: Squad,
    optimum: Squad,
    players: list[Player],
    raw_scores: dict[str, float],
    utility_scores: dict[str, float],
    core_multipliers: dict[str, float],
    args: argparse.Namespace,
    seed: int,
    distance: int,
    variation_target_met: bool,
    annotated_count: int,
    annotated_by_position: dict[str, int],
    annotation_requirements: dict[str, int],
    annotated_goalkeeper_blocks: int,
    hard_exclusions: list[dict[str, Any]],
) -> dict[str, Any]:
    squad_score = sum(utility_scores[player.player_id] for player in squad.players)
    optimum_score = sum(utility_scores[player.player_id] for player in optimum.players)
    raw_squad_score = sum(
        round(raw_scores[player.player_id], 3) for player in squad.players
    )
    raw_optimum_score = sum(raw_scores[player.player_id] for player in optimum.players)
    visible_squad_utility = sum(
        round(utility_scores[player.player_id], 3) for player in squad.players
    )
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
            -utility_scores[player.player_id],
            player.name,
        ),
    )
    selected_ids = squad.ids
    core_anchor_requirement = (
        args.min_reliable_anchors if args.profile == "reliable" else 0
    )
    formation, core_ids = best_starting_lineup(
        squad.players,
        raw_scores,
        core_anchor_requirement,
    )
    selected_anchors = [
        player for player in squad.players if player.reliable_anchor
    ]
    core_anchor_count = sum(
        player.reliable_anchor
        for player in squad.players
        if player.player_id in core_ids
    )
    if core_anchor_count < core_anchor_requirement:
        warnings.append(
            "The selected squad satisfies the roster anchor floor, but no legal "
            "starting formation can place all required anchors in the core."
        )

    def serialize_player(
        player: Player,
        *,
        selection_role: str | None = None,
        comparison_to: Player | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": player.player_id,
            "name": player.name,
            "short_name": player.short_name,
            "club": player.club,
            "position": player.position,
            "cost": player.cost,
            "score": round(raw_scores[player.player_id], 3),
            "utility_score": round(utility_scores[player.player_id], 3),
            "core_multiplier": round(core_multipliers[player.player_id], 3),
            "components": {
                key: round(player.components[key], 3) for key in COMPONENTS
            },
            "risks": {
                key: round(player.risks[key], 3) for key in RISKS
            },
            "note": player.note,
            "evidence": list(player.evidence),
            "benchmark": player.benchmark,
            "reliable_anchor": player.reliable_anchor,
            "anchor_basis": player.anchor_basis,
            "anchor_reason": player.anchor_reason,
        }
        if selection_role is not None:
            payload["selection_role"] = selection_role
        if comparison_to is not None:
            payload["position_cutoff_player"] = {
                "id": comparison_to.player_id,
                "name": comparison_to.name,
                "cost": comparison_to.cost,
                "utility_score": round(
                    utility_scores[comparison_to.player_id],
                    3,
                ),
            }
            payload["cost_delta_vs_cutoff"] = player.cost - comparison_to.cost
            payload["utility_delta_vs_cutoff"] = round(
                utility_scores[player.player_id]
                - utility_scores[comparison_to.player_id],
                3,
            )
        return payload

    roster_slots = getattr(
        args,
        "slots",
        {
            position: sum(
                player.position == position for player in squad.players
            )
            for position in DEFAULT_SLOTS
        },
    )
    minimum_spend = math.ceil(
        args.budget * float(getattr(args, "min_spend_ratio", 0.0))
    )
    force_bonus = 2.0 * sum(abs(score) for score in utility_scores.values()) + 1.0

    def counterfactual_for(player: Player) -> dict[str, Any]:
        forced_scores = dict(utility_scores)
        forced_scores[player.player_id] += force_bonus
        try:
            forced = optimize(
                players,
                args.budget,
                forced_scores,
                args.max_outfield_per_club,
                minimum_spend,
                roster_slots,
                not args.mixed_goalkeepers,
                args.min_reliable_anchors,
            )
        except ValueError as error:
            return {
                "feasible": False,
                "reason": str(error),
            }
        if player.player_id not in forced.ids:
            return {
                "feasible": False,
                "reason": "candidate cannot be forced inside the roster constraints",
            }
        forced_utility = sum(
            utility_scores[forced_player.player_id]
            for forced_player in forced.players
        )
        forced_ids = forced.ids

        def compact(candidate: Player) -> dict[str, Any]:
            return {
                "id": candidate.player_id,
                "name": candidate.name,
                "position": candidate.position,
                "cost": candidate.cost,
                "utility_score": round(
                    utility_scores[candidate.player_id],
                    3,
                ),
            }

        displaced = sorted(
            (
                candidate
                for candidate in squad.players
                if candidate.player_id not in forced_ids
            ),
            key=lambda candidate: (
                POSITION_ORDER[candidate.position],
                candidate.name,
            ),
        )
        added = sorted(
            (
                candidate
                for candidate in forced.players
                if candidate.player_id not in selected_ids
            ),
            key=lambda candidate: (
                POSITION_ORDER[candidate.position],
                candidate.name,
            ),
        )
        return {
            "feasible": True,
            "scope": "best_feasible_pool_squad_with_candidate",
            "cost": forced.cost,
            "budget_delta_vs_selected": forced.cost - squad.cost,
            "model_utility": round(forced_utility, 3),
            "utility_gap_vs_selected_percent": round(
                100.0
                * (squad_score - forced_utility)
                / max(abs(squad_score), 1e-9),
                3,
            ),
            "displaced_players": [compact(candidate) for candidate in displaced],
            "additional_players": [compact(candidate) for candidate in added],
        }

    comparison_candidates: list[dict[str, Any]] = []
    comparison_ids: set[str] = set()
    for position in ("DEFENDER", "MIDFIELDER", "FORWARD"):
        selected_position = [
            player for player in squad.players if player.position == position
        ]
        cutoff = min(
            selected_position,
            key=lambda player: (
                utility_scores[player.player_id],
                -player.cost,
                player.name,
            ),
        )
        omitted = sorted(
            (
                player
                for player in players
                if player.position == position and player.player_id not in selected_ids
            ),
            key=lambda player: (
                -utility_scores[player.player_id],
                player.cost,
                player.name,
            ),
        )
        required = omitted[:2]
        benchmarks = [player for player in omitted if player.benchmark]
        for player in (*required, *benchmarks):
            if player.player_id in comparison_ids:
                continue
            comparison_ids.add(player.player_id)
            comparison = serialize_player(player, comparison_to=cutoff)
            comparison["counterfactual"] = counterfactual_for(player)
            comparison_candidates.append(comparison)

    benchmark_audit = [
        {
            **serialize_player(player),
            "selected": player.player_id in selected_ids,
        }
        for player in sorted(
            (player for player in players if player.benchmark),
            key=lambda player: (
                POSITION_ORDER[player.position],
                -utility_scores[player.player_id],
                player.name,
            ),
        )
    ]
    anchor_budget = sum(player.cost for player in selected_anchors)
    return {
        "profile": args.profile,
        "maintenance": args.maintenance,
        "variation": args.variation,
        "seed": seed,
        "budget": args.budget,
        "cost": squad.cost,
        "remaining_budget": args.budget - squad.cost,
        "score": round(raw_squad_score, 3),
        "optimal_score": round(raw_optimum_score, 3),
        "model_utility": round(visible_squad_utility, 3),
        "best_pool_utility": round(optimum_score, 3),
        "quality_gap_percent": round(max(0.0, quality_gap), 3),
        "quality_gap_metric": "model_utility",
        "optimization_scope": {
            "eligible_players": len(players),
            "basis": "fully_annotated_candidate_pool",
            "quality_gap_reference": (
                "best_feasible_squad_within_this_annotated_pool"
            ),
            "core_weighting": (
                "strong_starting_core_affordable_playable_reserve"
                if args.profile == "reliable" and args.maintenance == "low"
                else "uniform_player_utility"
            ),
        },
        "distance_from_optimum": distance,
        "variation_target_met": variation_target_met,
        "suggested_starting_lineup": {
            "formation": formation,
            "player_ids": sorted(core_ids),
            "reliable_anchors": core_anchor_count,
            "reliable_anchors_required": core_anchor_requirement,
        },
        "reliable_anchor_policy": {
            "required": args.min_reliable_anchors,
            "eligible": sum(
                player.reliable_anchor
                for player in players
                if player.position != "GOALKEEPER"
            ),
            "selected": len(selected_anchors),
            "selected_names": sorted(player.name for player in selected_anchors),
            "budget": anchor_budget,
            "budget_share_percent": round(
                100.0 * anchor_budget / max(args.budget, 1),
                3,
            ),
        },
        "goalkeeper_mode": (
            "mixed" if args.mixed_goalkeepers else "same_club"
        ),
        "annotated_players": annotated_count,
        "annotated_players_by_position": annotated_by_position,
        "annotated_goalkeeper_blocks": annotated_goalkeeper_blocks,
        "comparison_candidates": comparison_candidates,
        "benchmark_audit": benchmark_audit,
        "hard_exclusions": hard_exclusions,
        "warnings": warnings,
        "squad": [
            serialize_player(
                player,
                selection_role=(
                    "core" if player.player_id in core_ids else "bench"
                ),
            )
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
        premium_review_pool: dict[str, Player] = {}
        premium_count = max(6, slot_count)
        for ranked in (
            sorted(
                candidates,
                key=lambda player: (-player.cost, player.name),
            ),
            sorted(
                candidates,
                key=lambda player: (-player.points, player.name),
            ),
            sorted(
                candidates,
                key=lambda player: (-scores[player.player_id], player.name),
            ),
        ):
            for player in ranked[:premium_count]:
                premium_review_pool[player.player_id] = player
        premium_review = sorted(
            premium_review_pool.values(),
            key=lambda player: (
                -scores[player.player_id],
                -player.cost,
                player.name,
            ),
        )

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
            "premium_review": [serialize(player) for player in premium_review],
        }
    return result


def print_text(payload: dict[str, Any]) -> None:
    print(
        f"Profile={payload['profile']} variation={payload['variation']} "
        f"maintenance={payload['maintenance']} seed={payload['seed']}"
    )
    print(
        f"Cost={payload['cost']} remaining={payload['remaining_budget']} "
        f"annotated_pool_gap={payload['quality_gap_percent']}%"
    )
    anchor_policy = payload["reliable_anchor_policy"]
    print(
        "Reliable anchors="
        f"{anchor_policy['selected']}/{anchor_policy['required']} "
        f"starting formation={payload['suggested_starting_lineup']['formation']}"
    )
    current_position = None
    for player in payload["squad"]:
        if player["position"] != current_position:
            current_position = player["position"]
            print(f"\n{current_position}")
        print(
            f"- {player['name']} | {player['club']} | "
            f"{player['cost']} | {player['selection_role']} | "
            f"score {player['score']}"
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
        "--min-reliable-anchors",
        type=int,
        help=(
            "Minimum repeatable premium field-player anchors; default 3 for "
            "a final reliable squad and 0 otherwise"
        ),
    )
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
    if args.min_reliable_anchors is None:
        args.min_reliable_anchors = (
            3
            if args.profile == "reliable" and not args.allow_unannotated
            else 0
        )
    if args.min_reliable_anchors < 0:
        parser.error("--min-reliable-anchors cannot be negative")
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
    field_slots = (
        args.slots["DEFENDER"]
        + args.slots["MIDFIELDER"]
        + args.slots["FORWARD"]
    )
    if args.min_reliable_anchors > field_slots:
        parser.error("--min-reliable-anchors exceeds the number of field slots")
    return args


def main() -> int:
    args = parse_args()
    seed = args.seed if args.seed is not None else secrets.randbelow(2**31)
    print(f"Variation seed: {seed}", file=sys.stderr, flush=True)
    annotations = load_annotations(args.annotations)
    hard_exclusions = [
        {
            "annotation_key": key,
            "reason": str(annotation.get("note", "")).strip(),
            "benchmark": bool(annotation.get("benchmark", False)),
            "evidence": (
                annotation.get("evidence", [])
                if isinstance(annotation.get("evidence", []), list)
                else []
            ),
        }
        for key, annotation in annotations.items()
        if bool(annotation.get("exclude", False))
    ]
    players, annotated_count, annotated_by_position = load_players(
        args.players,
        annotations,
    )
    raw_scores = score_players(players, args.profile, args.maintenance)
    if args.shortlist_only:
        payload = shortlist_payload(
            players,
            raw_scores,
            args.profile,
            args.slots,
        )
        rendered = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        print(rendered)
        return 0

    undocumented_benchmark_exclusions = [
        key
        for key, annotation in annotations.items()
        if (
            bool(annotation.get("exclude", False))
            and bool(annotation.get("benchmark", False))
            and (
                not str(annotation.get("note", "")).strip()
                or not evidence_is_complete(annotation)
            )
        )
    ]
    if undocumented_benchmark_exclusions and not args.allow_unannotated:
        print(
            "Excluded benchmark players need a concrete reason and current "
            "evidence before final optimization: "
            f"{sorted(undocumented_benchmark_exclusions)}.",
            file=sys.stderr,
        )
        return 2

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
    eligible_raw_scores = {
        player.player_id: raw_scores[player.player_id]
        for player in eligible_players
    }
    if args.profile == "reliable" and not args.allow_unannotated:
        benchmark_counts = {
            position: sum(
                player.benchmark
                for player in eligible_players
                if player.position == position
            )
            for position in ("DEFENDER", "MIDFIELDER", "FORWARD")
        }
        missing_benchmarks = {
            position: {"actual": count, "required": 2}
            for position, count in benchmark_counts.items()
            if count < 2
        }
        if missing_benchmarks:
            print(
                "Reliable-profile premium audit is incomplete. Mark and fully "
                "annotate at least two established benchmark candidates per field "
                f"position before optimization: {missing_benchmarks}.",
                file=sys.stderr,
            )
            return 2
    anchor_candidates = sum(
        player.reliable_anchor
        for player in eligible_players
        if player.position != "GOALKEEPER"
    )
    if anchor_candidates < args.min_reliable_anchors:
        print(
            "Reliable-anchor research is incomplete: "
            f"required={args.min_reliable_anchors}, eligible={anchor_candidates}. "
            "Expand or correct the researched premium pool; the policy is not "
            "relaxed automatically.",
            file=sys.stderr,
        )
        return 2
    eligible_utility_scores, core_multipliers = core_weighted_scores(
        eligible_players,
        eligible_raw_scores,
        args.profile,
        args.maintenance,
    )
    avoid_ids = load_avoid_ids(args.avoid_roster)
    minimum_spend = math.ceil(args.budget * args.min_spend_ratio)
    try:
        squad, optimum, distance, variation_target_met = varied_squad(
            players=eligible_players,
            budget=args.budget,
            base_scores=eligible_utility_scores,
            profile=args.profile,
            variation=args.variation,
            seed=seed,
            club_cap=args.max_outfield_per_club,
            minimum_spend=minimum_spend,
            slots=args.slots,
            avoid_ids=avoid_ids,
            same_club_goalkeepers=not args.mixed_goalkeepers,
            min_reliable_anchors=args.min_reliable_anchors,
        )
    except ValueError as error:
        print(f"Optimization stopped: {error}", file=sys.stderr)
        return 2
    if args.profile == "reliable" and args.min_reliable_anchors > 0:
        _, core_ids = best_starting_lineup(
            squad.players,
            eligible_raw_scores,
            args.min_reliable_anchors,
        )
        core_anchor_count = sum(
            player.reliable_anchor
            for player in squad.players
            if player.player_id in core_ids
        )
        if core_anchor_count < args.min_reliable_anchors:
            print(
                "Optimization stopped: the squad-level anchor floor cannot be "
                "placed inside one legal starting formation. Recalibrate the "
                "anchor pool instead of treating bench anchors as the reliable core.",
                file=sys.stderr,
            )
            return 2
    payload = output_payload(
        squad=squad,
        optimum=optimum,
        players=eligible_players,
        raw_scores=eligible_raw_scores,
        utility_scores=eligible_utility_scores,
        core_multipliers=core_multipliers,
        args=args,
        seed=seed,
        distance=distance,
        variation_target_met=variation_target_met,
        annotated_count=annotated_count,
        annotated_by_position=annotated_by_position,
        annotation_requirements=required_annotations,
        annotated_goalkeeper_blocks=annotated_goalkeeper_blocks,
        hard_exclusions=hard_exclusions,
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
