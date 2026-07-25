#!/usr/bin/env python3
"""Build a broad, multi-season Kicker quality pool from central snapshots."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from market_snapshot import (
    canonical_sha256 as market_sha256,
    load_snapshot as load_market_snapshot,
)
from kicker_history_snapshot import (
    canonical_sha256 as kicker_history_sha256,
    load_snapshot as load_kicker_history_snapshot,
)
from history_snapshot import (
    canonical_sha256 as history_sha256,
    load_snapshot as load_history_snapshot,
)
from news_snapshot import (
    canonical_sha256 as news_sha256,
    load_snapshot as load_news_snapshot,
)
from quality_snapshot import SCHEMA_VERSION, canonical_sha256, validate_snapshot
from refresh_news_snapshot import api_sports_pages, optional_int


MODEL_VERSION = "multi-season-v5-age-curve-youth-pathway"
POSITIONS = ("GOALKEEPER", "DEFENDER", "MIDFIELDER", "FORWARD")


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def isoformat(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def identity_words(value: str) -> tuple[str, ...]:
    folded = unicodedata.normalize(
        "NFKD",
        value.replace("ß", "ss"),
    ).encode("ascii", "ignore").decode("ascii").casefold()
    return tuple(re.findall(r"[a-z0-9]+", folded))


def name_key(value: str) -> str:
    words = identity_words(value)
    return " ".join(words)


def surname_key(value: str) -> str:
    words = identity_words(value)
    return words[-1] if words else ""


def club_match(left: str, right: str) -> bool:
    left_words = set(identity_words(left))
    right_words = set(identity_words(right))
    stopwords = {"1", "fc", "sc", "sv", "tsv", "vfb", "vfl", "bsc", "ev"}
    return bool((left_words - stopwords) & (right_words - stopwords))


def clamp(value: Any, default: float = 50.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return round(max(0.0, min(100.0, number)), 2)


def percentile(value: float, values: list[float]) -> float:
    if len(values) <= 1:
        return 50.0
    below = sum(candidate < value for candidate in values)
    equal = sum(candidate == value for candidate in values)
    return 100.0 * (below + 0.5 * equal) / len(values)


def available_market_players(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        player
        for player in payload["players"]
        if player.get("available", True)
        and int(player.get("market_value", 0)) < 100_000_000
    ]


def news_provider_index(
    payload: dict[str, Any],
) -> tuple[dict[str, list[tuple[str, dict[str, Any]]]], dict[str, dict[str, Any]]]:
    by_name: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    by_surname: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for news_id, player in payload["players"].items():
        mapping = player.get("mapping", {})
        if (
            mapping.get("confidence") != "verified"
            or optional_int(mapping.get("api_sports_player_id")) is None
        ):
            continue
        item = (str(news_id), player)
        by_name[name_key(str(player.get("name", "")))].append(item)
        by_surname[surname_key(str(player.get("name", "")))].append(item)
    return dict(by_name), dict(by_surname)


def match_news_player(
    market_player: dict[str, Any],
    by_name: dict[str, list[tuple[str, dict[str, Any]]]],
    by_surname: dict[str, list[tuple[str, dict[str, Any]]]],
) -> tuple[str, dict[str, Any]] | None:
    candidates = by_name.get(name_key(str(market_player["name"])), [])
    if not candidates:
        candidates = by_surname.get(
            surname_key(str(market_player["name"])),
            [],
        )
    matching_club = [
        item
        for item in candidates
        if club_match(str(market_player["club"]), str(item[1].get("club", "")))
    ]
    if len(matching_club) == 1:
        return matching_club[0]
    if len(candidates) == 1:
        return candidates[0]
    return None


def youth_talent_profile(
    history_player: dict[str, Any],
    age: int | None,
) -> dict[str, Any]:
    """Measure exceptional youth pathways without inventing senior proof."""

    career = history_player.get("career", {})
    seasons = history_player.get("seasons", [])
    current_age = age if age is not None and 15 <= age <= 30 else 27
    latest_season = max(
        (
            int(season.get("season", 0))
            for season in seasons
            if int(season.get("season", 0)) > 0
        ),
        default=0,
    )
    national_minutes = 0
    national_levels: set[int] = set()
    elite_youth_minutes = 0.0
    early_senior_weighted_minutes = 0.0
    for season in seasons:
        season_id = int(season.get("season", 0))
        season_age = current_age - max(0, latest_season - season_id)
        for competition in season.get("competitions", []):
            if not isinstance(competition, dict):
                continue
            competition_id = str(
                competition.get("competition_id", "")
            ).upper()
            label = str(competition.get("label", ""))
            kind = str(competition.get("kind", ""))
            minutes = int(competition.get("minutes", 0))
            strength = float(competition.get("strength_factor", 0))
            national_match = (
                kind == "youth"
                and competition_id != "19YL"
                and (
                    "NATIONALMANNSCHAFT" in label.upper()
                    or bool(
                        re.search(
                            r"(?:^U?(?:15|16|17|18|19|20|21)"
                            r"(?:Q|EU|LA|FS)?$)|"
                            r"(?:INTERNATIONAL U(?:15|16|17|18|19|20|21))",
                            f"{competition_id} {label.upper()}",
                        )
                    )
                )
            )
            if national_match:
                national_minutes += minutes
                for match in re.findall(
                    r"(?:U)?(15|16|17|18|19|20|21)",
                    f"{competition_id} {label.upper()}",
                ):
                    national_levels.add(int(match))
            if kind == "youth" and strength >= 0.42:
                elite_youth_minutes += minutes * min(1.4, strength / 0.42)
            if kind == "domestic_league" and season_age <= 21:
                age_multiplier = (
                    1.6
                    if season_age <= 17
                    else 1.3
                    if season_age == 18
                    else 1.0
                    if season_age == 19
                    else 0.8
                    if season_age == 20
                    else 0.6
                )
                early_senior_weighted_minutes += (
                    minutes
                    * max(0.0, strength)
                    / 0.64
                    * age_multiplier
                )
    age_phase_bonus = (
        8.0
        if current_age <= 17
        else 10.0
        if current_age == 18
        else 9.0
        if current_age == 19
        else 7.0
        if current_age == 20
        else 4.0
        if current_age == 21
        else 0.0
    )
    youth_score = float(career.get("youth_score", 0))
    talent_score = clamp(
        0.30 * youth_score
        + min(15.0, national_minutes / 90.0)
        + min(8.0, len(national_levels) * 4.0)
        + min(12.0, elite_youth_minutes / 600.0)
        + min(35.0, early_senior_weighted_minutes / 85.0)
        + age_phase_bonus,
        0.0,
    )
    readiness_score = clamp(
        0.62 * talent_score
        + 0.38 * min(100.0, early_senior_weighted_minutes / 24.0),
        0.0,
    )
    return {
        "age": age if age is not None else None,
        "talent_score": talent_score,
        "readiness_score": readiness_score,
        "national_team_minutes": national_minutes,
        "national_team_levels": sorted(national_levels),
        "elite_youth_minutes": round(elite_youth_minutes, 1),
        "early_senior_weighted_minutes": round(
            early_senior_weighted_minutes,
            1,
        ),
        "breakthrough_phase": (
            "exceptional_early"
            if current_age <= 18 and early_senior_weighted_minutes >= 900
            else "prime_window"
            if current_age in {19, 20}
            else "development_window"
            if current_age == 21
            else "pre_breakthrough"
            if current_age <= 18
            else "senior"
        ),
        "talent_tier": (
            "exceptional"
            if talent_score >= 85
            or (
                current_age <= 18
                and early_senior_weighted_minutes >= 900
                and talent_score >= 80
            )
            else "high"
            if talent_score >= 68
            else "emerging"
            if talent_score >= 52
            else "standard"
        ),
    }


def candidate_rank(
    player: dict[str, Any],
    points_by_position: dict[str, list[float]],
    prices_by_position: dict[str, list[float]],
    history_player: dict[str, Any],
    age: int | None = None,
) -> float:
    position = str(player["position"])
    points = float(player.get("points", 0.0))
    price = float(player.get("market_value", 0))
    points_pct = percentile(points, points_by_position[position])
    price_pct = percentile(price, prices_by_position[position])
    grade = float(player.get("average_grade", 0.0))
    grade_score = 50.0 if grade <= 0 else max(0.0, min(100.0, (4.7 - grade) * 45))
    history_score = float(
        history_player.get("career", {}).get("confirmed_score", 0)
    )
    youth_score = float(
        history_player.get("career", {}).get("youth_score", 0)
    )
    mapping_status = history_player.get("mapping", {}).get("status")
    history_weight = (
        1.0
        if mapping_status == "verified"
        else 0.65
        if mapping_status == "probable"
        else 0.0
    )
    talent_profile = youth_talent_profile(history_player, age)
    talent_score = float(talent_profile["talent_score"])
    age_value = talent_profile["age"]
    age_factor = (
        1.0
        if isinstance(age_value, int) and age_value <= 19
        else 0.65
        if age_value == 20
        else 0.35
        if age_value == 21
        else 0.0
    )
    editorial_talent_signal = (
        price_pct
        * age_factor
        * min(1.0, max(0.0, talent_score - 50.0) / 35.0)
        if talent_score >= 60
        else 0.0
    )
    historical_score = max(
        history_score,
        0.70 * youth_score,
        0.86 * talent_score,
    )
    historical_signal = 45.0 + history_weight * (historical_score - 45.0)
    price_signal = max(100 - price_pct, editorial_talent_signal)
    return (
        0.32 * points_pct
        + 0.17 * grade_score
        + 0.16 * price_signal
        + 0.35 * historical_signal
    )


def select_candidates(
    market_payload: dict[str, Any],
    news_payload: dict[str, Any],
    history_payload: dict[str, Any],
    quotas: dict[str, int],
    forced_candidate_ids: set[str] | None = None,
) -> list[tuple[dict[str, Any], str, dict[str, Any]]]:
    market_players = available_market_players(market_payload)
    points_by_position = {
        position: [
            float(player.get("points", 0.0))
            for player in market_players
            if player["position"] == position
        ]
        for position in POSITIONS
    }
    prices_by_position = {
        position: [
            float(player.get("market_value", 0))
            for player in market_players
            if player["position"] == position
        ]
        for position in POSITIONS
    }
    by_name, by_surname = news_provider_index(news_payload)
    ranked: dict[str, list[tuple[float, dict[str, Any], str, dict[str, Any]]]] = {
        position: [] for position in POSITIONS
    }
    for player in market_players:
        match = match_news_player(player, by_name, by_surname)
        if match is None:
            continue
        news_id, news_player = match
        history_player = history_payload["players"].get(
            str(player["id"]),
            {
                "mapping": {"status": "unmatched"},
                "career": {"confirmed_score": 0, "proven_seasons": 0},
            },
        )
        ranked[str(player["position"])].append(
            (
                candidate_rank(
                    player,
                    points_by_position,
                    prices_by_position,
                    history_player,
                    optional_int(
                        news_player.get("mapping", {}).get("age")
                    ),
                ),
                player,
                news_id,
                news_player,
            )
        )
    selected: list[tuple[dict[str, Any], str, dict[str, Any]]] = []
    for position in POSITIONS:
        candidates = sorted(
            ranked[position],
            key=lambda item: (-item[0], int(item[1]["market_value"]), item[1]["id"]),
        )
        if position == "GOALKEEPER":
            by_club: dict[
                str,
                list[tuple[float, dict[str, Any], str, dict[str, Any]]],
            ] = defaultdict(list)
            for item in candidates:
                by_club[str(item[1]["club"])].append(item)
            complete_blocks = [
                (
                    sum(item[0] for item in club_candidates[:3]) / 3,
                    club,
                    club_candidates[:3],
                )
                for club, club_candidates in by_club.items()
                if len(club_candidates) >= 3
            ]
            complete_blocks.sort(key=lambda item: (-item[0], item[1]))
            requested_blocks = max(2, math.ceil(quotas[position] / 3))
            if len(complete_blocks) < requested_blocks:
                raise RuntimeError(
                    f"only {len(complete_blocks)} complete goalkeeper blocks, "
                    f"{requested_blocks} required"
                )
            selected.extend(
                (player, news_id, news_player)
                for _, _, block in complete_blocks[:requested_blocks]
                for _, player, news_id, news_player in block
            )
            continue
        premium_count = max(1, math.ceil(quotas[position] * 0.65))
        premium = candidates[:premium_count]
        premium_ids = {str(item[1]["id"]) for item in premium}
        value_depth = sorted(
            (
                item
                for item in candidates
                if str(item[1]["id"]) not in premium_ids
            ),
            key=lambda item: (
                int(item[1]["market_value"]),
                -item[0],
                item[1]["id"],
            ),
        )
        diversified = [
            *premium,
            *value_depth[: max(0, quotas[position] - len(premium))],
        ]
        diversified_ids = {str(item[1]["id"]) for item in diversified}
        historically_proven = [
            item
            for item in candidates
            if int(
                history_payload["players"]
                .get(str(item[1]["id"]), {})
                .get("career", {})
                .get("proven_seasons", 0)
            )
            >= 2
            and str(item[1]["id"]) not in diversified_ids
        ]
        diversified.extend(historically_proven)
        selected.extend(
            (player, news_id, news_player)
            for _, player, news_id, news_player in diversified
        )
    selected_ids = {str(item[0]["id"]) for item in selected}
    forced_ids = forced_candidate_ids or set()
    for position in POSITIONS:
        for _, player, news_id, news_player in ranked[position]:
            player_id = str(player["id"])
            if player_id in forced_ids and player_id not in selected_ids:
                selected.append((player, news_id, news_player))
                selected_ids.add(player_id)
    return selected


def numeric(value: Any) -> float:
    try:
        return float(str(value or 0).strip().rstrip("%"))
    except (TypeError, ValueError):
        return 0.0


def empty_season_stats(season: int, age: int | None = None) -> dict[str, Any]:
    return {
        "season": season,
        "appearances": 0,
        "minutes": 0,
        "lineups": 0,
        "substitutions_in": 0,
        "substitutions_out": 0,
        "bench": 0,
        "rating": 0.0,
        "goals": 0,
        "goals_conceded": 0,
        "assists": 0,
        "saves": 0,
        "shots_total": 0,
        "shots_on": 0,
        "passes_total": 0,
        "key_passes": 0,
        "pass_accuracy": 0.0,
        "tackles": 0,
        "blocks": 0,
        "interceptions": 0,
        "duels": 0,
        "duels_won": 0,
        "dribbles_attempted": 0,
        "dribbles_successful": 0,
        "fouls_drawn": 0,
        "fouls_committed": 0,
        "yellow_cards": 0,
        "red_cards": 0,
        "penalties_scored": 0,
        "penalties_missed": 0,
        "penalties_saved": 0,
        "age": age,
    }


def fetch_player_season(
    player_id: int,
    season: int,
    *,
    headers: dict[str, str],
    request_delay: float,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            pages = list(
                api_sports_pages(
                    "https://v3.football.api-sports.io/players",
                    query={"id": player_id, "season": season},
                    headers=headers,
                )
            )
            time.sleep(request_delay)
            response = [
                item
                for page in pages
                for item in page.get("response", [])
                if isinstance(item, dict)
            ]
            if not response:
                return empty_season_stats(season)
            player = response[0].get("player", {})
            totals = empty_season_stats(
                season,
                optional_int(player.get("age")),
            )
            totals.update({
                "rating_weighted": 0.0,
                "rating_minutes": 0,
                "pass_accuracy_weighted": 0.0,
                "pass_accuracy_attempts": 0,
            })
            for item in response:
                for statistics in item.get("statistics", []):
                    games = statistics.get("games", {})
                    goals = statistics.get("goals", {})
                    substitutes = statistics.get("substitutes", {})
                    shots = statistics.get("shots", {})
                    passes = statistics.get("passes", {})
                    tackles = statistics.get("tackles", {})
                    duels = statistics.get("duels", {})
                    dribbles = statistics.get("dribbles", {})
                    fouls = statistics.get("fouls", {})
                    cards = statistics.get("cards", {})
                    penalty = statistics.get("penalty", {})
                    appearances = int(numeric(games.get("appearences")))
                    minutes = int(numeric(games.get("minutes")))
                    rating = numeric(games.get("rating"))
                    pass_total = int(numeric(passes.get("total")))
                    pass_accuracy = numeric(passes.get("accuracy"))
                    totals["appearances"] += appearances
                    totals["minutes"] += minutes
                    totals["lineups"] += int(numeric(games.get("lineups")))
                    totals["substitutions_in"] += int(
                        numeric(substitutes.get("in"))
                    )
                    totals["substitutions_out"] += int(
                        numeric(substitutes.get("out"))
                    )
                    totals["bench"] += int(numeric(substitutes.get("bench")))
                    totals["goals"] += int(numeric(goals.get("total")))
                    totals["goals_conceded"] += int(
                        numeric(goals.get("conceded"))
                    )
                    totals["assists"] += int(numeric(goals.get("assists")))
                    totals["saves"] += int(numeric(goals.get("saves")))
                    totals["shots_total"] += int(
                        numeric(shots.get("total"))
                    )
                    totals["shots_on"] += int(numeric(shots.get("on")))
                    totals["passes_total"] += pass_total
                    totals["key_passes"] += int(numeric(passes.get("key")))
                    totals["tackles"] += int(numeric(tackles.get("total")))
                    totals["blocks"] += int(numeric(tackles.get("blocks")))
                    totals["interceptions"] += int(
                        numeric(tackles.get("interceptions"))
                    )
                    totals["duels"] += int(numeric(duels.get("total")))
                    totals["duels_won"] += int(numeric(duels.get("won")))
                    totals["dribbles_attempted"] += int(
                        numeric(dribbles.get("attempts"))
                    )
                    totals["dribbles_successful"] += int(
                        numeric(dribbles.get("success"))
                    )
                    totals["fouls_drawn"] += int(
                        numeric(fouls.get("drawn"))
                    )
                    totals["fouls_committed"] += int(
                        numeric(fouls.get("committed"))
                    )
                    totals["yellow_cards"] += int(
                        numeric(cards.get("yellow"))
                    ) + int(numeric(cards.get("yellowred")))
                    totals["red_cards"] += int(numeric(cards.get("red")))
                    totals["penalties_scored"] += int(
                        numeric(penalty.get("scored"))
                    )
                    totals["penalties_missed"] += int(
                        numeric(penalty.get("missed"))
                    )
                    totals["penalties_saved"] += int(
                        numeric(penalty.get("saved"))
                    )
                    if rating > 0:
                        weight = max(1, minutes)
                        totals["rating_weighted"] += rating * weight
                        totals["rating_minutes"] += weight
                    if pass_accuracy > 0 and pass_total > 0:
                        totals["pass_accuracy_weighted"] += (
                            pass_accuracy * pass_total
                        )
                        totals["pass_accuracy_attempts"] += pass_total
            totals["rating"] = round(
                totals.pop("rating_weighted")
                / max(1, totals.pop("rating_minutes")),
                2,
            )
            totals["pass_accuracy"] = round(
                totals.pop("pass_accuracy_weighted")
                / max(1, totals.pop("pass_accuracy_attempts")),
                2,
            )
            return totals
        except RuntimeError as error:
            last_error = error
            if attempt == 2:
                break
            time.sleep(65 if "limit" in str(error).casefold() else 4 * (attempt + 1))
    raise RuntimeError(
        f"could not load API-Sports history for player {player_id}, "
        f"season {season}: {last_error}"
    )


def season_is_proven(position: str, stats: dict[str, Any]) -> bool:
    appearances = int(stats["appearances"])
    minutes = int(stats["minutes"])
    rating = float(stats["rating"])
    contributions = int(stats["goals"]) + int(stats["assists"])
    if appearances < 15 and minutes < 900:
        return False
    if position in {"GOALKEEPER", "DEFENDER"}:
        return minutes >= 1_100 or (minutes >= 800 and rating >= 6.35)
    return (
        rating >= 6.35
        or contributions >= 5
        or (minutes >= 1_300 and contributions >= 3)
    )


def per_90(stats: dict[str, Any], field_name: str) -> float:
    return 90.0 * numeric(stats.get(field_name)) / max(
        1.0,
        numeric(stats.get("minutes")),
    )


def event_role_score(position: str, stats: dict[str, Any]) -> float:
    """Score repeatable on-ball/off-ball actions without treating ratings as truth."""

    duel_win_rate = (
        100.0
        * numeric(stats.get("duels_won"))
        / max(1.0, numeric(stats.get("duels")))
    )
    dribble_success_rate = (
        100.0
        * numeric(stats.get("dribbles_successful"))
        / max(1.0, numeric(stats.get("dribbles_attempted")))
    )
    contributions_per_90 = per_90(stats, "goals") + per_90(
        stats,
        "assists",
    )
    defensive_actions_per_90 = sum(
        per_90(stats, field_name)
        for field_name in ("tackles", "blocks", "interceptions")
    )
    if position == "GOALKEEPER":
        return clamp(
            48
            + 6.0 * per_90(stats, "saves")
            - 7.0 * per_90(stats, "goals_conceded")
            + 4.0 * numeric(stats.get("penalties_saved"))
        )
    if position == "DEFENDER":
        return clamp(
            38
            + 6.0 * defensive_actions_per_90
            + 0.18 * duel_win_rate
            + 5.0 * per_90(stats, "key_passes")
        )
    if position == "MIDFIELDER":
        return clamp(
            36
            + 11.0 * per_90(stats, "key_passes")
            + 18.0 * contributions_per_90
            + 0.10 * dribble_success_rate
            + 2.5 * defensive_actions_per_90
        )
    return clamp(
        34
        + 35.0 * per_90(stats, "goals")
        + 20.0 * per_90(stats, "assists")
        + 7.0 * per_90(stats, "shots_on")
        + 5.0 * per_90(stats, "key_passes")
    )


def kicker_trend_summary(
    player: dict[str, Any] | None,
) -> dict[str, Any]:
    observations = list((player or {}).get("observations", []))
    summary = {
        "observation_count": len(observations),
        "first_observed_on": None,
        "last_observed_on": None,
        "points_delta": 0.0,
        "market_value_delta": 0,
        "average_grade_delta": 0.0,
        "trend_score": 50.0,
    }
    if not observations:
        return summary
    first = observations[0]
    last = observations[-1]
    summary.update(
        {
            "first_observed_on": first["observed_on"],
            "last_observed_on": last["observed_on"],
            "points_delta": round(
                numeric(last.get("points"))
                - numeric(first.get("points")),
                2,
            ),
            "market_value_delta": int(last["market_value"])
            - int(first["market_value"]),
            "average_grade_delta": round(
                numeric(last.get("average_grade"))
                - numeric(first.get("average_grade")),
                2,
            ),
        }
    )
    if len(observations) < 2:
        return summary
    first_date = datetime.strptime(first["observed_on"], "%Y-%m-%d")
    last_date = datetime.strptime(last["observed_on"], "%Y-%m-%d")
    weeks = max(1.0, (last_date - first_date).days / 7)
    points_per_week = float(summary["points_delta"]) / weeks
    price_change_percent = (
        100.0
        * int(summary["market_value_delta"])
        / max(1, int(first["market_value"]))
    )
    grade_improvement = -float(summary["average_grade_delta"])
    summary["trend_score"] = clamp(
        50
        + 1.8 * points_per_week
        + 0.12 * price_change_percent
        + 8.0 * grade_improvement
    )
    return summary


def build_annotation(
    market_player: dict[str, Any],
    news_id: str,
    news_player: dict[str, Any],
    histories: list[dict[str, Any]],
    history_player: dict[str, Any],
    kicker_history_player: dict[str, Any] | None = None,
    talent_evidence: dict[str, Any] | None = None,
    *,
    competition: str,
    points_pct: float,
    price_pct: float,
    generated_at: str,
) -> dict[str, Any]:
    position = str(market_player["position"])
    consensus = news_player.get("consensus", {})
    latest = histories[0] if histories else {}
    api_proven_seasons = sum(
        season_is_proven(position, stats) for stats in histories
    )
    career_appearances = sum(int(stats["appearances"]) for stats in histories)
    career_minutes = sum(int(stats["minutes"]) for stats in histories)
    contributions = sum(
        int(stats["goals"]) + int(stats["assists"]) for stats in histories
    )
    ratings = [
        float(stats["rating"])
        for stats in histories
        if float(stats["rating"]) > 0
    ]
    rating_score = (
        clamp(50 + (sum(ratings) / len(ratings) - 6.25) * 55)
        if ratings
        else 45.0
    )
    latest_event_score = event_role_score(position, latest)
    career_event_scores = [
        event_role_score(position, stats)
        for stats in histories
        if numeric(stats.get("minutes")) >= 180
    ]
    event_score = (
        sum(career_event_scores) / len(career_event_scores)
        if career_event_scores
        else latest_event_score
    )
    trend_summary = kicker_trend_summary(kicker_history_player)
    trend_score = float(trend_summary["trend_score"])
    api_confirmed = clamp(
        30
        + 18 * api_proven_seasons
        + 0.20 * points_pct
        + 0.08 * rating_score
        + 0.18 * event_score
        + min(12, career_appearances / 5)
    )
    api_minutes = clamp(
        42
        + min(30, numeric(latest.get("minutes")) / 55)
        + min(18, career_minutes / 180)
    )
    api_role = clamp(
        48
        + min(22, numeric(latest.get("lineups")) * 1.4)
        + min(16, contributions * (1.5 if position in {"MIDFIELDER", "FORWARD"} else 0.5))
        + 0.18 * (event_score - 50)
    )
    history_mapping = history_player.get(
        "mapping",
        {"status": "unmatched", "confidence": "none"},
    )
    history_status = str(history_mapping.get("status", "unmatched"))
    history_confidence = (
        1.0
        if history_status == "verified"
        else 0.65
        if history_status == "probable"
        else 0.0
    )
    history_career = history_player.get("career", {})
    history_proven_seasons = int(
        history_career.get("proven_seasons", 0)
    )
    history_confirmed = float(
        history_career.get("confirmed_score", 0)
    )
    history_minutes = float(
        history_career.get("recent_minutes_score", 0)
    )
    history_role = float(history_career.get("role_score", 0))
    history_youth_score = float(history_career.get("youth_score", 0))
    if history_confidence > 0:
        confirmed = clamp(
            history_confidence
            * (
                0.58 * history_confirmed
                + 0.22 * api_confirmed
                + 0.20 * points_pct
            )
            + (1 - history_confidence) * api_confirmed
        )
        minutes = clamp(
            history_confidence
            * (0.48 * history_minutes + 0.52 * api_minutes)
            + (1 - history_confidence) * api_minutes
        )
        role = clamp(
            history_confidence
            * (0.45 * history_role + 0.55 * api_role)
            + (1 - history_confidence) * api_role
        )
        proven_seasons = history_proven_seasons
    else:
        confirmed = api_confirmed
        minutes = api_minutes
        role = api_role
        proven_seasons = api_proven_seasons
    confirmed = clamp(confirmed + 0.08 * (trend_score - 50))
    role = clamp(role + 0.10 * (trend_score - 50))
    transfer_risk = clamp(consensus.get("transfer", 0), 0)
    injury_risk = clamp(consensus.get("injury", 0), 0)
    rotation_risk = clamp(consensus.get("rotation", 0), 0)
    fitness_cap = clamp(consensus.get("fitness_cap", 100), 100)
    provider_age = optional_int(
        news_player.get("mapping", {}).get("age")
    )
    age = provider_age or next(
        (int(stats["age"]) for stats in histories if stats.get("age") is not None),
        27,
    )
    talent_profile = youth_talent_profile(history_player, age)
    talent_score = float(talent_profile["talent_score"])
    readiness_score = float(talent_profile["readiness_score"])
    age_factor = (
        1.0
        if age <= 19
        else 0.65
        if age == 20
        else 0.35
        if age == 21
        else 0.0
    )
    editorial_talent_signal = (
        price_pct
        * age_factor
        * min(1.0, max(0.0, talent_score - 50.0) / 35.0)
        if talent_score >= 60
        else 0.0
    )
    if age <= 21 and talent_score >= 68:
        minutes = max(minutes, clamp(44 + 0.43 * readiness_score))
        role = max(role, clamp(42 + 0.43 * readiness_score))
    early_senior_confirmation = (
        min(62.0, 0.58 * readiness_score)
        if talent_profile["breakthrough_phase"] == "exceptional_early"
        else 0.0
    )
    confirmed = clamp(max(confirmed, early_senior_confirmation))
    talent_evidence = talent_evidence or {}
    minutes = max(
        minutes,
        clamp(talent_evidence.get("minutes_floor", 0), 0),
    )
    role = max(
        role,
        clamp(talent_evidence.get("role_floor", 0), 0),
    )
    stability = clamp(82 - 0.55 * transfer_risk - 0.25 * rotation_risk)
    stability = clamp(stability + 0.08 * (trend_score - 50))
    fitness = clamp(min(fitness_cap, 92 - 0.58 * injury_risk))
    base_upside = clamp(
        78 - max(0, age - 20) * 2.1 + (100 - points_pct) * 0.12
    )
    youth_relevance = max(0.0, 1.0 - max(0, age - 21) * 0.18)
    youth_upside = clamp(
        35 + 0.65 * history_youth_score * youth_relevance
    )
    editorial_upside = clamp(
        talent_score + 0.10 * editorial_talent_signal
    )
    upside = max(base_upside, youth_upside, editorial_upside)
    value = clamp(
        0.42 * (100 - price_pct)
        + 0.32 * confirmed
        + 0.26 * points_pct
        + 0.08 * (trend_score - 50)
    )
    if age <= 21 and talent_score >= 68:
        talent_value = clamp(
            0.20 * (100 - price_pct)
            + 0.35 * readiness_score
            + 0.25 * editorial_talent_signal
            + 0.20 * role
        )
        value = max(value, talent_value)
    risks = {
        "transfer": transfer_risk,
        "injury": injury_risk,
        "rotation": max(rotation_risk, clamp(82 - minutes)),
        "outlier": clamp(42 - 15 * proven_seasons + max(0, points_pct - 88) * 1.2),
        "unknown_role": clamp(
            min(
                74 - role,
                max(18.0, 62.0 - 0.42 * readiness_score),
            )
            if age <= 21 and talent_score >= 68
            else 74 - role
        ),
    }
    components = {
        "confirmed_performance": confirmed,
        "minutes": minutes,
        "role": role,
        "stability": stability,
        "context": clamp(65 + 0.18 * (trend_score - 50)),
        "fitness": fitness,
        "upside": upside,
        "value": value,
    }
    reliable_anchor = (
        position != "GOALKEEPER"
        and history_confidence > 0
        and history_proven_seasons >= 2
        and proven_seasons >= 2
        and confirmed >= 72
        and minutes >= 70
        and role >= 62
        and stability >= 62
        and fitness >= 70
        and transfer_risk < 45
        and injury_risk < 45
    )
    provider_id = int(news_player["mapping"]["api_sports_player_id"])
    evidence = [
        {
            "claim": "Aktueller Kicker-Marktwert und Vorjahresdaten",
            "source_url": str(
                market_player.get(
                    "source_url",
                    "https://www.kicker.de/managerspiel/interactive",
                )
            ),
            "checked_at": generated_at,
        },
        {
            "claim": "Ergänzende mehrjährige Einsatz-, Bewertungs- und Scorerhistorie",
            "source_url": (
                "https://v3.football.api-sports.io/players"
                f"?id={provider_id}"
            ),
            "checked_at": generated_at,
        },
        {
            "claim": "Aktuelle Verletzungs-, Transfer- und Rollenprüfung",
            "source_url": (
                "https://geozocco.github.io/kicker-interactive-manager/"
                f"v1/news/{'2-bundesliga' if competition == '2. Bundesliga' else '3-liga'}.json"
            ),
            "checked_at": generated_at,
        },
    ]
    profile_url = str(history_mapping.get("profile_url", ""))
    if history_confidence > 0 and profile_url.startswith("https://"):
        evidence.insert(
            1,
            {
                "claim": (
                    "Ligakontextualisierte historische Einsätze, Minuten "
                    "und Scorer über bis zu acht Spielzeiten"
                ),
                "source_url": profile_url,
                "checked_at": generated_at,
            },
        )
    for item in talent_evidence.get("evidence", []):
        if (
            isinstance(item, dict)
            and str(item.get("claim", "")).strip()
            and str(item.get("source_url", "")).startswith("https://")
            and str(item.get("checked_at", "")).strip()
        ):
            evidence.append(
                {
                    "claim": str(item["claim"]),
                    "source_url": str(item["source_url"]),
                    "checked_at": str(item["checked_at"]),
                }
            )
    history_summary = {
        "mapping_status": history_status,
        "confidence": str(history_mapping.get("confidence", "none")),
        "transfermarkt_player_id": history_mapping.get(
            "transfermarkt_player_id"
        ),
        "profile_url": profile_url or None,
        "proven_seasons": history_proven_seasons,
        "comparable_minutes": round(
            float(history_career.get("comparable_minutes", 0)),
            1,
        ),
        "level_adjusted_minutes": round(
            float(history_career.get("level_adjusted_minutes", 0)),
            1,
        ),
        "youth_adjusted_minutes": round(
            float(history_career.get("youth_adjusted_minutes", 0)),
            1,
        ),
        "youth_adjusted_contributions": round(
            float(
                history_career.get(
                    "youth_adjusted_contributions",
                    0,
                )
            ),
            2,
        ),
        "youth_score": round(history_youth_score, 2),
        "talent_score": round(talent_score, 2),
        "early_senior_confirmation": round(
            early_senior_confirmation,
            2,
        ),
        "editorial_talent_signal": round(editorial_talent_signal, 2),
        "talent_profile": talent_profile,
    }
    return {
        "position": position,
        "club": str(market_player["club"]),
        "components": components,
        "risks": risks,
        "proven_seasons": proven_seasons,
        "reliable_anchor": reliable_anchor,
        "anchor_reason": (
            f"{proven_seasons} belastbare Spielzeiten, stabile Einsatz- und "
            "Rollenwerte"
            if reliable_anchor
            else ""
        ),
        "benchmark": bool(talent_evidence.get("benchmark", False)),
        "note": " ".join(
            part
            for part in (
                (
                    f"Mehrjahres-Check: {history_proven_seasons} im Zielniveau "
                    "bestätigte Spielzeiten; "
                    f"{int(history_career.get('comparable_minutes', 0))} Minuten "
                    "auf vergleichbarem oder höherem Ligastand."
                ),
                (
                    f"Talentpfad: {talent_profile['talent_tier']} "
                    f"({talent_score:.1f}/100), "
                    f"Phase {talent_profile['breakthrough_phase']}."
                    if talent_score >= 52
                    else ""
                ),
                str(talent_evidence.get("note", "")).strip(),
            )
            if part
        ),
        "evidence": evidence,
        "provider_news_id": news_id,
        "api_sports_history": histories,
        "api_sports_role_metrics": {
            "latest_event_score": round(latest_event_score, 2),
            "multi_season_event_score": round(event_score, 2),
            "provider_rating_score": round(rating_score, 2),
            "rating_weight_in_api_confirmation": 0.08,
        },
        "kicker_trend": trend_summary,
        "history_summary": history_summary,
    }


def generate_snapshot(
    market_payload: dict[str, Any],
    news_payload: dict[str, Any],
    history_payload: dict[str, Any],
    kicker_history_payload: dict[str, Any],
    config: dict[str, Any],
    *,
    token: str,
    request_delay: float,
    ttl_hours: int,
) -> dict[str, Any]:
    if market_payload["competition"] != news_payload["competition"]:
        raise RuntimeError("market and news competition do not match")
    if market_payload["season"] != news_payload["season"]:
        raise RuntimeError("market and news season do not match")
    if market_payload["competition"] != history_payload["competition"]:
        raise RuntimeError("market and history competition do not match")
    if market_payload["season"] != history_payload["season"]:
        raise RuntimeError("market and history season do not match")
    if market_payload["competition"] != kicker_history_payload["competition"]:
        raise RuntimeError("market and kicker history competition do not match")
    if market_payload["season"] != kicker_history_payload["season"]:
        raise RuntimeError("market and kicker history season do not match")
    if market_sha256(market_payload) != history_payload["market_sha256"]:
        raise RuntimeError("history snapshot does not belong to the market")
    if market_sha256(market_payload) != kicker_history_payload["market_sha256"]:
        raise RuntimeError("kicker history does not belong to the market")
    quotas = {
        position: int(config["candidate_quotas"][position])
        for position in POSITIONS
    }
    candidates = select_candidates(
        market_payload,
        news_payload,
        history_payload,
        quotas,
        {
            str(player_id)
            for player_id in config.get("talent_evidence", {})
        },
    )
    minimum_candidates = int(config["minimum_candidates"])
    if len(candidates) < minimum_candidates:
        raise RuntimeError(
            f"only {len(candidates)} provider-mapped candidates, "
            f"{minimum_candidates} required"
        )
    market_players = available_market_players(market_payload)
    points_by_position = {
        position: [
            float(player.get("points", 0.0))
            for player in market_players
            if player["position"] == position
        ]
        for position in POSITIONS
    }
    prices_by_position = {
        position: [
            float(player.get("market_value", 0))
            for player in market_players
            if player["position"] == position
        ]
        for position in POSITIONS
    }
    generated = utc_now()
    generated_at = isoformat(generated)
    annotations: dict[str, dict[str, Any]] = {}
    headers = {"x-apisports-key": token}
    history_seasons = [int(value) for value in config["history_seasons"]]
    total_requests = len(candidates) * len(history_seasons)
    completed = 0
    for market_player, news_id, news_player in candidates:
        provider_id = int(news_player["mapping"]["api_sports_player_id"])
        histories = []
        for history_season in history_seasons:
            histories.append(
                fetch_player_season(
                    provider_id,
                    history_season,
                    headers=headers,
                    request_delay=request_delay,
                )
            )
            completed += 1
            print(
                f"quality history {completed}/{total_requests}",
                file=sys.stderr,
                flush=True,
            )
        position = str(market_player["position"])
        annotation = build_annotation(
            market_player,
            news_id,
            news_player,
            histories,
            history_payload["players"].get(
                str(market_player["id"]),
                {
                    "mapping": {
                        "status": "unmatched",
                        "confidence": "none",
                    },
                    "career": {},
                },
            ),
            kicker_history_payload["players"].get(
                str(market_player["id"])
            ),
            config.get("talent_evidence", {}).get(
                str(market_player["id"]),
                {},
            ),
            competition=str(market_payload["competition"]),
            points_pct=percentile(
                float(market_player.get("points", 0.0)),
                points_by_position[position],
            ),
            price_pct=percentile(
                float(market_player.get("market_value", 0)),
                prices_by_position[position],
            ),
            generated_at=generated_at,
        )
        annotations[str(market_player["id"])] = annotation

    for position in ("DEFENDER", "MIDFIELDER", "FORWARD"):
        position_items = [
            (player_id, annotation)
            for player_id, annotation in annotations.items()
            if annotation["position"] == position
        ]
        position_items.sort(
            key=lambda item: (
                -float(item[1]["components"]["confirmed_performance"]),
                -int(item[1]["proven_seasons"]),
                item[0],
            )
        )
        for player_id, _ in position_items[:2]:
            annotations[player_id]["benchmark"] = True

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "expires_at": isoformat(generated + timedelta(hours=ttl_hours)),
        "competition": market_payload["competition"],
        "season": market_payload["season"],
        "market_sha256": market_sha256(market_payload),
        "news_sha256": news_sha256(news_payload),
        "history_sha256": history_sha256(history_payload),
        "kicker_history_sha256": kicker_history_sha256(
            kicker_history_payload
        ),
        "model_version": MODEL_VERSION,
        "requirements": {
            "candidate_count": int(config["minimum_candidates"]),
            "anchor_count": int(config["minimum_anchors"]),
            "attacking_anchor_count": int(config["minimum_attacking_anchors"]),
            "goalkeeper_block_count": int(
                config["minimum_goalkeeper_blocks"]
            ),
            "history_resolved_percent": int(
                config["minimum_history_resolved_percent"]
            ),
        },
        "annotations": annotations,
    }
    payload["content_sha256"] = canonical_sha256(payload)
    return validate_snapshot(payload)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", required=True)
    parser.add_argument("--news", required=True)
    parser.add_argument("--history", required=True)
    parser.add_argument("--kicker-history", required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ttl-hours", type=int, default=18)
    parser.add_argument("--request-delay", type=float, default=0.25)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    token = os.environ.get("API_SPORTS_KEY", "").strip()
    if not token:
        print("API_SPORTS_KEY is required", file=sys.stderr)
        return 2
    config = json.loads(args.mapping.read_text(encoding="utf-8"))
    market_payload = load_market_snapshot(args.market)
    news_payload = load_news_snapshot(args.news)
    history_payload = load_history_snapshot(args.history)
    kicker_history_payload = load_kicker_history_snapshot(
        args.kicker_history
    )
    payload = generate_snapshot(
        market_payload,
        news_payload,
        history_payload,
        kicker_history_payload,
        config,
        token=token,
        request_delay=args.request_delay,
        ttl_hours=args.ttl_hours,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    anchors = sum(
        annotation["reliable_anchor"]
        for annotation in payload["annotations"].values()
    )
    print(
        f"Wrote {len(payload['annotations'])} candidates and {anchors} anchors "
        f"to {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
