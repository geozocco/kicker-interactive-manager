#!/usr/bin/env python3
"""Deterministic team, competition, discipline and usage signals."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


MODEL_VERSION = "advanced-context-v1"
POSITION_NAMES = {
    "g": "GOALKEEPER",
    "gk": "GOALKEEPER",
    "goalkeeper": "GOALKEEPER",
    "d": "DEFENDER",
    "defender": "DEFENDER",
    "m": "MIDFIELDER",
    "midfielder": "MIDFIELDER",
    "f": "FORWARD",
    "fw": "FORWARD",
    "attacker": "FORWARD",
    "forward": "FORWARD",
}


def clamp(value: Any, default: float = 50.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return round(max(0.0, min(100.0, number)), 2)


def normalized_position(value: Any) -> str | None:
    text = str(value or "").strip().casefold()
    return POSITION_NAMES.get(text)


def percentile(value: float, values: list[float]) -> float:
    if not values:
        return 50.0
    below = sum(candidate < value for candidate in values)
    equal = sum(candidate == value for candidate in values)
    return 100.0 * (below + 0.5 * equal) / len(values)


def positional_flexibility(
    annotation: dict[str, Any],
    preseason_player: dict[str, Any] | None,
) -> dict[str, Any]:
    observations: list[str] = []
    for season in annotation.get("api_sports_history", [])[:3]:
        if not isinstance(season, dict):
            continue
        for value in season.get("positions", []):
            position = normalized_position(value)
            if position:
                observations.append(position)
    for item in (
        preseason_player.get("observations", [])
        if isinstance(preseason_player, dict)
        else []
    ):
        if not isinstance(item, dict) or not item.get("appeared"):
            continue
        position = normalized_position(item.get("position"))
        if position:
            observations.append(position)
    distinct = sorted(set(observations))
    samples = len(observations)
    score = (
        50.0
        if samples < 2
        else 58.0
        if len(distinct) == 1
        else 76.0
        if len(distinct) == 2
        else 88.0
    )
    return {
        "positions_observed": distinct,
        "observation_count": samples,
        "score": score,
        "confidence": (
            "high" if samples >= 8 else "medium" if samples >= 3 else "low"
        ),
    }


def discipline_profile(annotation: dict[str, Any]) -> dict[str, Any]:
    weighted_minutes = 0.0
    weighted_yellow = 0.0
    weighted_red = 0.0
    current_yellow = 0
    current_red = 0
    for index, season in enumerate(annotation.get("api_sports_history", [])[:3]):
        if not isinstance(season, dict):
            continue
        if index == 0:
            current_yellow = int(season.get("yellow_cards", 0) or 0)
            current_red = int(season.get("red_cards", 0) or 0)
        weight = (1.0, 0.62, 0.38)[index]
        weighted_minutes += weight * float(season.get("minutes", 0) or 0)
        weighted_yellow += weight * float(
            season.get("yellow_cards", 0) or 0
        )
        weighted_red += weight * float(season.get("red_cards", 0) or 0)
    yellow_per_90 = 90.0 * weighted_yellow / max(1.0, weighted_minutes)
    red_per_90 = 90.0 * weighted_red / max(1.0, weighted_minutes)
    one_card_from_suspension = current_yellow > 0 and current_yellow % 5 == 4
    risk = clamp(
        18.0
        + 150.0 * yellow_per_90
        + 420.0 * red_per_90
        + (22.0 if one_card_from_suspension else 0.0)
        if weighted_minutes >= 450
        else 50.0
    )
    return {
        "sample_minutes": round(weighted_minutes, 1),
        "yellow_cards_per_90": round(yellow_per_90, 3),
        "red_cards_per_90": round(red_per_90, 3),
        "current_yellow_cards": current_yellow,
        "current_red_cards": current_red,
        "one_card_from_suspension": one_card_from_suspension,
        "suspension_risk": risk,
        "confidence": (
            "high"
            if weighted_minutes >= 2_000
            else "medium"
            if weighted_minutes >= 900
            else "low"
        ),
    }


def usage_trajectory(
    annotation: dict[str, Any],
    preseason_player: dict[str, Any] | None,
) -> dict[str, Any]:
    observations = sorted(
        (
            item
            for item in (
                preseason_player.get("observations", [])
                if isinstance(preseason_player, dict)
                else []
            )
            if isinstance(item, dict) and str(item.get("date", "")).strip()
        ),
        key=lambda item: str(item["date"]),
    )
    starts = [1.0 if item.get("started") else 0.0 for item in observations]
    appearances = [
        1.0 if item.get("appeared") else 0.0 for item in observations
    ]
    split = max(1, len(starts) // 2)
    early = starts[:split]
    recent = starts[split:] or starts[-1:]
    early_rate = sum(early) / max(1, len(early))
    recent_rate = sum(recent) / max(1, len(recent))
    current_history = next(
        (
            season
            for season in annotation.get("api_sports_history", [])
            if isinstance(season, dict)
        ),
        {},
    )
    league_appearances = int(current_history.get("appearances", 0) or 0)
    league_starts = int(current_history.get("lineups", 0) or 0)
    league_start_rate = league_starts / max(1, league_appearances)
    if league_appearances:
        recent_rate = 0.65 * league_start_rate + 0.35 * recent_rate
    trend = 100.0 * (recent_rate - early_rate) if len(starts) >= 2 else 0.0
    consecutive_starts = 0
    for value in reversed(starts):
        if value <= 0:
            break
        consecutive_starts += 1
    return {
        "observation_count": len(observations),
        "appearance_share": round(
            sum(appearances) / max(1, len(appearances)),
            3,
        ),
        "early_start_share": round(early_rate, 3),
        "recent_start_share": round(recent_rate, 3),
        "trend": round(max(-100.0, min(100.0, trend)), 2),
        "consecutive_starts": consecutive_starts,
        "competitive_appearances": league_appearances,
        "competitive_start_share": round(league_start_rate, 3),
        "status": (
            "rising"
            if trend >= 25
            else "falling"
            if trend <= -25
            else "stable"
            if len(starts) >= 2 or league_appearances
            else "insufficient"
        ),
    }


def player_competition_score(annotation: dict[str, Any]) -> float:
    role = annotation.get("role_context", {})
    probability = float(role.get("expected_start_probability", 0) or 0)
    if probability > 0:
        return probability
    components = annotation.get("components", {})
    return clamp(
        0.55 * float(components.get("minutes", 50) or 50)
        + 0.45 * float(components.get("role", 50) or 50)
    )


def team_projection_raw(
    club_annotations: list[tuple[str, dict[str, Any]]],
) -> tuple[float, float, float]:
    attack: list[float] = []
    defense: list[float] = []
    creation: list[float] = []
    for _, annotation in club_annotations:
        position = str(annotation.get("position", ""))
        components = annotation.get("components", {})
        scorer = annotation.get("scorer_profile", {})
        if position in {"MIDFIELDER", "FORWARD"}:
            attack.append(
                0.30 * float(components.get("confirmed_performance", 50))
                + 0.25 * float(components.get("minutes", 50))
                + 0.25 * float(components.get("role", 50))
                + 0.20
                * min(
                    100.0,
                    180.0
                    * float(scorer.get("contributions_per_90", 0) or 0),
                )
            )
            responsibilities = scorer.get("responsibilities", {})
            creation.append(
                float(components.get("role", 50))
                + (
                    8.0
                    if isinstance(responsibilities, dict)
                    and responsibilities.get("playmaker")
                    in {"shared", "primary"}
                    else 0.0
                )
            )
        if position in {"GOALKEEPER", "DEFENDER"}:
            defense.append(
                0.30 * float(components.get("confirmed_performance", 50))
                + 0.28 * float(components.get("minutes", 50))
                + 0.24 * float(components.get("stability", 50))
                + 0.18 * float(components.get("fitness", 50))
            )
    attack.sort(reverse=True)
    defense.sort(reverse=True)
    creation.sort(reverse=True)
    return (
        sum(attack[:6]) / max(1, len(attack[:6])),
        sum(defense[:6]) / max(1, len(defense[:6])),
        sum(creation[:4]) / max(1, len(creation[:4])),
    )


def apply_advanced_signals(
    annotations: dict[str, dict[str, Any]],
    preseason_payload: dict[str, Any],
    news_payload: dict[str, Any] | None = None,
) -> None:
    """Attach and gently apply the advanced signals to every candidate."""

    by_club: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for player_id, annotation in annotations.items():
        by_club[str(annotation.get("club", ""))].append(
            (player_id, annotation)
        )
    raw_team = {
        club: team_projection_raw(items) for club, items in by_club.items()
    }
    attack_values = [value[0] for value in raw_team.values()]
    defense_values = [value[1] for value in raw_team.values()]
    creation_values = [value[2] for value in raw_team.values()]

    for club, club_items in by_club.items():
        attack, defense, creation = raw_team[club]
        researched_team = (
            news_payload.get("team_profiles", {}).get(club, {})
            if isinstance(news_payload, dict)
            and isinstance(news_payload.get("team_profiles"), dict)
            else {}
        )
        level_adjustment = {
            "low": -8.0,
            "medium": 0.0,
            "high": 8.0,
            "unknown": 0.0,
        }
        team_projection = {
            "attack_strength": clamp(
                percentile(attack, attack_values)
                + level_adjustment.get(
                    str(researched_team.get("attacking_outlook", "unknown")),
                    0.0,
                )
            ),
            "defense_strength": clamp(
                percentile(defense, defense_values)
                + level_adjustment.get(
                    str(researched_team.get("defensive_outlook", "unknown")),
                    0.0,
                )
            ),
            "chance_creation": round(
                percentile(creation, creation_values),
                2,
            ),
        }
        team_projection["clean_sheet_outlook"] = round(
            team_projection["defense_strength"],
            2,
        )
        for player_id, annotation in club_items:
            preseason_player = preseason_payload.get("players", {}).get(
                annotation.get("provider_news_id"),
                preseason_payload.get("players", {}).get(player_id),
            )
            flexibility = positional_flexibility(
                annotation,
                preseason_player,
            )
            discipline = discipline_profile(annotation)
            trajectory = usage_trajectory(annotation, preseason_player)
            peers = [
                (peer_id, player_competition_score(peer))
                for peer_id, peer in club_items
                if peer_id != player_id
                and peer.get("position") == annotation.get("position")
            ]
            player_score = player_competition_score(annotation)
            peers.sort(key=lambda item: (-item[1], item[0]))
            stronger = sum(score >= player_score + 5 for _, score in peers)
            close = sum(abs(score - player_score) < 10 for _, score in peers)
            rank = 1 + sum(score > player_score for _, score in peers)
            pressure = clamp(18 + 24 * stronger + 12 * close, 18)
            competition = {
                "rank_within_club_position": rank,
                "direct_competitor_count": len(peers),
                "strong_competitor_count": stronger,
                "close_competitor_count": close,
                "pressure_score": pressure,
                "nearest_competitors": [
                    {"player_id": peer_id, "role_score": round(score, 2)}
                    for peer_id, score in peers[:3]
                ],
            }
            age = (
                annotation.get("history_summary", {})
                .get("talent_profile", {})
                .get("age")
            )
            is_young = isinstance(age, int) and age <= 23
            coach_profile = {
                "source": (
                    "grounded_coach_history_plus_current_usage"
                    if researched_team
                    else "current_squad_role_and_usage_evidence"
                ),
                "coach_name": str(
                    researched_team.get("coach_name", "")
                ),
                "preferred_systems": list(
                    researched_team.get("preferred_systems", [])
                ),
                "historical_youth_usage": str(
                    researched_team.get("youth_usage", "unknown")
                ),
                "historical_rotation_tendency": str(
                    researched_team.get("rotation_tendency", "unknown")
                ),
                "system_stability": str(
                    researched_team.get("system_stability", "unknown")
                ),
                "player_coach_trust": annotation.get("role_context", {})
                .get("role_environment", {})
                .get("coach_trust", "unknown"),
                "player_tactical_fit": annotation.get("role_context", {})
                .get("role_environment", {})
                .get("tactical_fit", "unknown"),
                "young_player": is_young,
                "youth_usage_signal": (
                    "high"
                    if is_young
                    and trajectory["recent_start_share"] >= 0.65
                    else "medium"
                    if is_young
                    and trajectory["appearance_share"] >= 0.50
                    else "low"
                    if is_young and trajectory["observation_count"] >= 2
                    else "unknown"
                ),
                "rotation_signal": (
                    "high"
                    if trajectory["status"] == "falling"
                    or close >= 2
                    else "low"
                    if trajectory["consecutive_starts"] >= 3
                    and close == 0
                    else "medium"
                ),
            }
            annotation["advanced_signals"] = {
                "model_version": MODEL_VERSION,
                "positional_flexibility": flexibility,
                "team_projection": team_projection,
                "competition_graph": competition,
                "coach_usage": coach_profile,
                "discipline": discipline,
                "usage_trajectory": trajectory,
            }
            position = str(annotation.get("position", ""))
            team_context = (
                team_projection["attack_strength"]
                if position in {"MIDFIELDER", "FORWARD"}
                else team_projection["defense_strength"]
            )
            annotation["components"]["context"] = clamp(
                float(annotation["components"]["context"])
                + max(-4.0, min(4.0, 0.08 * (team_context - 50.0)))
            )
            annotation["components"]["stability"] = clamp(
                float(annotation["components"]["stability"])
                - max(0.0, 0.08 * (discipline["suspension_risk"] - 50.0))
            )
            if researched_team:
                if is_young:
                    youth_delta = {
                        "high": 2.0,
                        "medium": 0.0,
                        "low": -1.0,
                    }.get(str(researched_team.get("youth_usage")), 0.0)
                    annotation["components"]["upside"] = clamp(
                        float(annotation["components"]["upside"])
                        + youth_delta
                    )
                stability_delta = {
                    "high": 1.0,
                    "medium": 0.0,
                    "low": -1.0,
                }.get(
                    str(researched_team.get("system_stability")),
                    0.0,
                )
                annotation["components"]["stability"] = clamp(
                    float(annotation["components"]["stability"])
                    + stability_delta
                )
            annotation["risks"]["rotation"] = max(
                float(annotation["risks"]["rotation"]),
                round(0.35 * pressure, 2),
                (
                    28.0
                    if researched_team.get("rotation_tendency") == "high"
                    else 0.0
                ),
            )
