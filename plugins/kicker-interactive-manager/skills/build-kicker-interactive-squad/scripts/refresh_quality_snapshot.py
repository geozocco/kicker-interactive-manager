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
from preseason_snapshot import (
    canonical_sha256 as preseason_sha256,
    load_snapshot as load_preseason_snapshot,
)
from quality_snapshot import (
    SCHEMA_VERSION,
    QualitySnapshotError,
    canonical_sha256,
    load_snapshot as load_quality_snapshot,
    validate_snapshot,
)
from refresh_news_snapshot import (
    api_sports_pages,
    is_api_sports_rate_limit,
    optional_int,
)
from advanced_signals import apply_advanced_signals


MODEL_VERSION = "multi-season-v15-loan-pathway"
PRESEASON_MODEL_VERSION = "preseason-readiness-v3-role-responsibilities"
FORM_MODEL_VERSION = "recency-context-v4-evidence-role-transfer"
POSITIONS = ("GOALKEEPER", "DEFENDER", "MIDFIELDER", "FORWARD")
ROLE_CONTINUITY = {"unknown", "confirmed", "expanded", "reduced"}
ROLE_RESPONSIBILITIES = {
    "penalties",
    "direct_free_kicks",
    "corners",
    "playmaker",
    "offensive_focal_point",
    "aerial_set_piece_target",
    "captain",
}
ROLE_LEVELS = {"none", "shared", "primary"}
ROLE_ENVIRONMENT = {
    "coach_trust": {"unknown", "low", "medium", "high"},
    "squad_status": {
        "unknown",
        "core",
        "regular",
        "rotation",
        "development",
        "surplus",
    },
    "tactical_fit": {"unknown", "poor", "good", "strong"},
    "positional_competition": {"unknown", "low", "medium", "high"},
    "expected_minutes_band": {
        "unknown",
        "under_300",
        "300_899",
        "900_1799",
        "1800_2699",
        "2700_plus",
    },
    "role_stability": {"unknown", "fragile", "uncertain", "stable"},
}
MANUAL_NEWS_CLEARANCE_CATEGORIES = {
    "availability",
    "fitness",
    "role",
    "transfer",
}


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
    stopwords = {
        "1",
        "fc",
        "sc",
        "sv",
        "tsv",
        "vfb",
        "vfl",
        "bsc",
        "ev",
        "club",
        "football",
        "fussball",
    }
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
    preseason_payload: dict[str, Any] | None = None,
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
            if player["position"] == "GOALKEEPER":
                # Goalkeeper selection depends on a complete, provider-backed
                # club hierarchy. An unmapped keeper remains a block-level
                # uncertainty rather than a safe standalone candidate.
                continue
            news_id = f"kicker-unmapped:{player['id']}"
            news_player = {
                "name": str(player["name"]),
                "club": str(player["club"]),
                "mapping": {
                    "confidence": "none",
                    "api_sports_player_id": None,
                    "api_sports_team_id": None,
                },
                "consensus": {
                    "transfer": 0,
                    "injury": 0,
                    "rotation": 0,
                    "fitness_cap": 100,
                    "confidence": "low",
                    "exclude": False,
                },
                "signals": [],
            }
        else:
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
        if quotas[position] <= 0:
            continue
        candidates = sorted(
            ranked[position],
            key=lambda item: (-item[0], int(item[1]["market_value"]), item[1]["id"]),
        )
        if position == "GOALKEEPER":
            complete_clubs = {
                str(item[1]["club"])
                for item in candidates
                if sum(
                    candidate[1]["club"] == item[1]["club"]
                    for candidate in candidates
                )
                >= 3
            }
            requested_blocks = max(2, math.ceil(quotas[position] / 3))
            if len(complete_clubs) < requested_blocks:
                raise RuntimeError(
                    f"only {len(complete_clubs)} complete goalkeeper blocks, "
                    f"{requested_blocks} required"
                )
            # Goalkeeper decisions are club-wide hierarchy decisions. Keep every
            # provider-mapped market keeper instead of truncating clubs to the
            # three highest-ranked names; a fourth challenger or a newly listed
            # keeper can materially change the projected number one.
            selected.extend(
                (player, news_id, news_player)
                for _, player, news_id, news_player in candidates
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
        included_ids = {str(item[1]["id"]) for item in diversified}
        current_performance_references = [
            item
            for item in candidates
            if (
                (
                    percentile(
                        float(item[1].get("points", 0.0)),
                        points_by_position[position],
                    )
                    >= 90
                    or (
                        0
                        < float(item[1].get("average_grade", 0.0))
                        <= 3.0
                    )
                )
                and str(item[1]["id"]) not in included_ids
            )
        ]
        # Top current Kicker performers are mandatory comparison references.
        # This changes research coverage, never their numerical score.
        diversified.extend(current_performance_references)
        selected.extend(
            (player, news_id, news_player)
            for _, player, news_id, news_player in diversified
        )
    selected_ids = {str(item[0]["id"]) for item in selected}
    forced_ids = forced_candidate_ids or set()
    preseason_news_ids = {
        str(news_id)
        for news_id, item in (preseason_payload or {}).get("players", {}).items()
        if isinstance(item, dict)
        and isinstance(item.get("summary"), dict)
        and float(item["summary"].get("signal_score", 0)) >= 60
        and int(item["summary"].get("appearances", 0)) >= 2
    }
    for position in POSITIONS:
        for _, player, news_id, news_player in ranked[position]:
            player_id = str(player["id"])
            if (
                player_id in forced_ids or news_id in preseason_news_ids
            ) and player_id not in selected_ids:
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
        "clubs": [],
        "positions": [],
    }


def cached_api_histories(
    previous_quality_payload: dict[str, Any] | None,
    *,
    competition: str,
    season: str,
    player_id: str,
    news_id: str,
    include_current: bool = False,
) -> dict[int, dict[str, Any]]:
    if (
        not isinstance(previous_quality_payload, dict)
        or previous_quality_payload.get("competition") != competition
        or previous_quality_payload.get("season") != season
    ):
        return {}
    annotation = previous_quality_payload.get("annotations", {}).get(
        player_id,
        {},
    )
    if annotation.get("provider_news_id") != news_id:
        return {}
    current_history_season = optional_int(str(season).split("/", 1)[0])
    migrating_model = (
        previous_quality_payload.get("model_version") != MODEL_VERSION
    )
    return {
        int(item["season"]): item
        for item in annotation.get("api_sports_history", [])
        if (
            isinstance(item, dict)
            and optional_int(item.get("season")) is not None
            # v14 adds the observed match-position input used by the
            # flexibility signal. Older cached rows remain a valid
            # rate-limit fallback, but must be refreshed when the provider is
            # available instead of silently freezing the migration forever.
            and ("positions" in item or include_current)
            and (
                include_current
                or
                migrating_model
                or
                current_history_season is None
                or int(item["season"]) < current_history_season
            )
        )
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
                "clubs_by_name": {},
                "positions_seen": set(),
            })
            for item in response:
                for statistics in item.get("statistics", []):
                    team = statistics.get("team", {})
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
                    club_name = str(team.get("name", "")).strip()
                    provider_position = str(
                        games.get("position", "")
                    ).strip()
                    if provider_position:
                        totals["positions_seen"].add(provider_position)
                    if club_name:
                        club_totals = totals["clubs_by_name"].setdefault(
                            club_name,
                            {"appearances": 0, "minutes": 0},
                        )
                        club_totals["appearances"] += appearances
                        club_totals["minutes"] += minutes
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
            totals["clubs"] = [
                {
                    "name": name,
                    "appearances": values["appearances"],
                    "minutes": values["minutes"],
                }
                for name, values in sorted(
                    totals.pop("clubs_by_name").items(),
                    key=lambda item: (-item[1]["minutes"], item[0]),
                )
            ]
            totals["positions"] = sorted(totals.pop("positions_seen"))
            return totals
        except RuntimeError as error:
            last_error = error
            if attempt == 2:
                break
            time.sleep(
                65
                if is_api_sports_rate_limit(error)
                else 4 * (attempt + 1)
            )
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


def role_level(value: Any) -> str:
    normalized = str(value or "none").strip().casefold()
    return normalized if normalized in ROLE_LEVELS else "none"


def valid_role_evidence_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "claim": str(item["claim"]).strip(),
            "source_url": str(item["source_url"]).strip(),
            "checked_at": str(item["checked_at"]).strip(),
        }
        for item in payload.get("evidence", [])
        if (
            isinstance(item, dict)
            and str(item.get("claim", "")).strip()
            and str(item.get("source_url", "")).startswith("https://")
            and str(item.get("checked_at", "")).strip()
        )
    ]


def cached_role_evidence(
    news_payload: dict[str, Any],
    player_id: str,
    fallback: dict[str, Any] | None,
) -> dict[str, Any]:
    """Prefer a fresh central news role profile over an uncached fallback."""

    profiles = news_payload.get("role_profiles", {})
    profile = profiles.get(player_id, {}) if isinstance(profiles, dict) else {}
    if not isinstance(profile, dict) or not profile.get("fresh", False):
        return dict(fallback) if isinstance(fallback, dict) else {}
    evidence = [
        {
            "claim": str(item.get("claim", "")).strip(),
            "source_url": str(item.get("source_url", "")).strip(),
            "checked_at": str(item.get("observed_at", "")).strip(),
        }
        for item in profile.get("evidence", [])
        if isinstance(item, dict)
    ]
    if not valid_role_evidence_items({"evidence": evidence}):
        return dict(fallback) if isinstance(fallback, dict) else {}
    return {
        "continuity": str(profile.get("continuity", "unknown")),
        "confidence": str(profile.get("confidence", "medium")),
        "expected_start_probability": profile.get(
            "expected_start_probability",
            0,
        ),
        "team_quality_delta": profile.get("team_quality_delta", 0),
        "external_signing_risk": profile.get(
            "external_signing_risk",
            0,
        ),
        "responsibilities": dict(profile.get("responsibilities", {})),
        "role_environment": dict(profile.get("role_environment", {})),
        "designation": str(profile.get("designation", "")),
        "note": str(profile.get("note", "")),
        "evidence": evidence,
        "source": "central_news_role_cache",
        "cache_model_version": str(profile.get("model_version", "")),
        "cache_expires_at": str(profile.get("expires_at", "")),
    }


def cached_transfer_profile(
    news_payload: dict[str, Any],
    player_id: str,
) -> dict[str, Any]:
    """Return only a fresh, grounded central transfer-watcher profile."""

    profiles = news_payload.get("transfer_profiles", {})
    profile = profiles.get(player_id, {}) if isinstance(profiles, dict) else {}
    if (
        not isinstance(profile, dict)
        or not profile.get("fresh", False)
        or profile.get("model_version") != "openai-transfer-watch-v1"
        or profile.get("status") not in {"rumour", "advanced", "confirmed"}
    ):
        return {}
    return dict(profile)


def goalkeeper_role_cache_adjustment(profile: dict[str, Any] | None) -> float:
    if not isinstance(profile, dict) or not profile.get("fresh", False):
        return 0.0
    return {
        "confirmed_starter": 60.0,
        "key_starter": 45.0,
        "expected_starter": 30.0,
        "immediate_help": 22.0,
        "open_competition": 0.0,
        "rotation": -25.0,
        "perspective": -55.0,
    }.get(str(profile.get("designation", "")), 0.0)


def manual_news_clearance_profile(
    payload: dict[str, Any] | None,
    *,
    generated_at: str,
) -> dict[str, Any]:
    """Validate a short-lived manual fallback for a missing provider mapping."""

    value = payload if isinstance(payload, dict) else {}
    evidence = valid_role_evidence_items(value)
    categories = {
        str(item).strip().casefold()
        for item in value.get("coverage", [])
        if str(item).strip()
    }
    try:
        checked_at = datetime.fromisoformat(
            str(value.get("checked_at", "")).replace("Z", "+00:00")
        )
        generated = datetime.fromisoformat(
            generated_at.replace("Z", "+00:00")
        )
        age_hours = (
            generated - checked_at
        ).total_seconds() / 3600.0
    except ValueError:
        checked_at = None
        age_hours = math.inf
    valid = (
        checked_at is not None
        and 0 <= age_hours <= 168
        and categories >= MANUAL_NEWS_CLEARANCE_CATEGORIES
        and len(evidence) >= 2
        and str(value.get("confidence", "")).casefold()
        in {"medium", "high"}
    )
    return {
        "model_version": "manual-news-clearance-v1",
        "valid": valid,
        "checked_at": (
            checked_at.isoformat().replace("+00:00", "Z")
            if checked_at is not None
            else None
        ),
        "age_hours": round(age_hours, 2) if math.isfinite(age_hours) else None,
        "coverage": sorted(categories),
        "confidence": str(value.get("confidence", "none")).casefold(),
        "risk_floors": {
            key: clamp(
                (value.get("risk_floors", {}) or {}).get(key),
                0,
            )
            for key in ("transfer", "injury", "rotation")
        },
        "fitness_cap": clamp(value.get("fitness_cap"), 100),
        "evidence": evidence,
        "note": str(value.get("note", "")).strip(),
    }


def confirmed_inbound_transfer(news_player: dict[str, Any]) -> bool:
    return any(
        isinstance(signal, dict)
        and str(signal.get("kind")) == "transfer_confirmed"
        and str(signal.get("status")) == "confirmed"
        and str(signal.get("availability_impact")) == "in"
        for signal in news_player.get("signals", [])
    )


def historical_club_context(
    histories: list[dict[str, Any]],
    *,
    market_club: str,
    news_player: dict[str, Any],
) -> tuple[list[str], bool | None, str]:
    provider_by_season = {
        int(item["season"]): item
        for item in histories
        if optional_int(item.get("season")) is not None
    }
    latest_provider = next(
        (
            provider_by_season[season]
            for season in sorted(provider_by_season, reverse=True)
            if provider_by_season[season].get("clubs")
        ),
        {},
    )
    historical_clubs = [
        str(club.get("name", "")).strip()
        for club in latest_provider.get("clubs", [])
        if str(club.get("name", "")).strip()
    ]
    if historical_clubs:
        return (
            historical_clubs,
            all(
                not club_match(market_club, club)
                for club in historical_clubs
            ),
            "provider_history",
        )
    if confirmed_inbound_transfer(news_player):
        return historical_clubs, True, "confirmed_inbound_transfer"
    return historical_clubs, None, "unknown"


def transfermarkt_role_metrics(
    history_player: dict[str, Any],
) -> dict[str, float]:
    recent_competitions: list[dict[str, Any]] = []
    for season in history_player.get("seasons", [])[:2]:
        domestic = [
            competition
            for competition in season.get("competitions", [])
            if (
                str(competition.get("kind", "")) == "domestic_league"
                and numeric(competition.get("minutes")) >= 180
            )
        ]
        if domestic:
            recent_competitions.extend(domestic)
    minutes = sum(
        numeric(competition.get("minutes"))
        for competition in recent_competitions
    )
    appearances = sum(
        numeric(competition.get("appearances"))
        for competition in recent_competitions
    )
    starts = sum(
        numeric(competition.get("starts"))
        for competition in recent_competitions
    )
    goals = sum(
        numeric(competition.get("goals"))
        for competition in recent_competitions
    )
    assists = sum(
        numeric(competition.get("assists"))
        for competition in recent_competitions
    )
    return {
        "minutes": minutes,
        "start_rate": starts / max(1.0, appearances),
        "goals_per_90": 90.0 * goals / max(1.0, minutes),
        "assists_per_90": 90.0 * assists / max(1.0, minutes),
        "contributions_per_90": (
            90.0 * (goals + assists) / max(1.0, minutes)
        ),
    }


def stronger_role_level(current: str, candidate: str) -> str:
    rank = {"none": 0, "shared": 1, "primary": 2}
    return candidate if rank[candidate] > rank[current] else current


def resolve_role_evidence(
    *,
    position: str,
    history_player: dict[str, Any],
    preseason_player: dict[str, Any] | None,
    explicit_role_evidence: dict[str, Any] | None,
    club_changed: bool | None,
) -> dict[str, Any]:
    """Combine explicit role facts with conservative current-club inference.

    Historical production is translated only after current official evidence
    repeatedly places the player in the first group. This avoids carrying an
    old-club role across a transfer merely because it once existed.
    """

    explicit = (
        dict(explicit_role_evidence)
        if isinstance(explicit_role_evidence, dict)
        else {}
    )
    explicit_items = valid_role_evidence_items(explicit)
    preseason = (
        preseason_player if isinstance(preseason_player, dict) else {}
    )
    summary = (
        preseason.get("summary", {})
        if isinstance(preseason.get("summary"), dict)
        else {}
    )
    current_observations = [
        item
        for item in preseason.get("observations", [])
        if (
            isinstance(item, dict)
            and item.get("source_provider") != "api_sports"
            and str(item.get("source_url", "")).startswith("https://")
            and str(item.get("claim", "")).strip()
            and str(item.get("date", "")).strip()
            and (
                bool(item.get("started"))
                or str(item.get("lineup_role")) == "first_group"
                or bool(item.get("responsibilities"))
            )
        )
    ]
    current_items = [
        {
            "claim": str(item["claim"]).strip(),
            "source_url": str(item["source_url"]).strip(),
            "checked_at": str(item["date"]).strip(),
        }
        for item in current_observations
    ]
    current_responsibilities = {
        key: "none" for key in ROLE_RESPONSIBILITIES
    }
    for item in current_observations:
        responsibilities = item.get("responsibilities", {})
        if not isinstance(responsibilities, dict):
            continue
        for key, value in responsibilities.items():
            if key not in ROLE_RESPONSIBILITIES:
                continue
            level = role_level(value)
            current_responsibilities[key] = stronger_role_level(
                current_responsibilities[key],
                level,
            )

    if explicit_items:
        resolved = dict(explicit)
        responsibilities = {
            key: role_level(
                (explicit.get("responsibilities", {}) or {}).get(key)
            )
            for key in ROLE_RESPONSIBILITIES
        }
        for key, level in current_responsibilities.items():
            responsibilities[key] = stronger_role_level(
                responsibilities[key],
                level,
            )
        resolved["responsibilities"] = responsibilities
        resolved["evidence"] = explicit_items + [
            item for item in current_items if item not in explicit_items
        ]
        resolved["source"] = "explicit_with_current_preseason"
        return resolved

    classification = str(summary.get("classification", "insufficient"))
    effective_factor = numeric(summary.get("effective_factor"))
    appearances = max(0.0, numeric(summary.get("appearances")))
    starts = max(0.0, numeric(summary.get("starts")))
    team_matches = max(1.0, numeric(summary.get("team_match_count")))
    official_first_group_starts = sum(
        bool(item.get("started"))
        and str(item.get("lineup_role")) == "first_group"
        for item in current_observations
    )
    repeated_current_role = (
        classification in {"positive", "strong"}
        and effective_factor > 0
        and len(current_items) >= 2
        and official_first_group_starts >= 2
        and starts >= 2
        and starts / max(1.0, appearances) >= 0.60
    )
    has_current_responsibility = any(
        level != "none" for level in current_responsibilities.values()
    )
    if not repeated_current_role and not has_current_responsibility:
        return {}

    historical = transfermarkt_role_metrics(history_player)
    responsibilities = dict(current_responsibilities)
    if (
        repeated_current_role
        and position in {"MIDFIELDER", "FORWARD"}
        and historical["minutes"] >= 1_200
        and historical["start_rate"] >= 0.65
    ):
        if historical["assists_per_90"] >= 0.25:
            responsibilities["playmaker"] = stronger_role_level(
                responsibilities["playmaker"],
                "shared",
            )
        if historical["contributions_per_90"] >= 0.55:
            responsibilities["offensive_focal_point"] = stronger_role_level(
                responsibilities["offensive_focal_point"],
                "shared",
            )

    expected_start_probability = 0.0
    continuity = "unknown"
    if repeated_current_role:
        start_rate = starts / max(1.0, appearances)
        coverage = min(1.0, appearances / team_matches)
        expected_start_probability = min(
            85.0,
            55.0 + 20.0 * start_rate + 10.0 * coverage,
        )
        continuity = "confirmed"
    return {
        "continuity": continuity,
        "confidence": "medium",
        "expected_start_probability": round(
            expected_start_probability,
            2,
        ),
        "team_quality_delta": 0.0,
        "responsibilities": responsibilities,
        "evidence": current_items,
        "source": (
            "current_preseason_plus_historical_role"
            if repeated_current_role
            else "current_preseason_responsibility"
        ),
        "club_changed": club_changed,
    }


def expected_role_profile(
    *,
    position: str,
    histories: list[dict[str, Any]],
    history_player: dict[str, Any] | None = None,
    role_evidence: dict[str, Any] | None = None,
    club_changed: bool | None = None,
) -> dict[str, Any]:
    """Model the expected new-club role instead of penalizing every transfer."""

    evidence = role_evidence if isinstance(role_evidence, dict) else {}
    evidence_items = valid_role_evidence_items(evidence)
    continuity = str(evidence.get("continuity", "unknown")).strip().casefold()
    if continuity not in ROLE_CONTINUITY or not evidence_items:
        continuity = "unknown"
    responsibilities = {
        key: role_level(
            (evidence.get("responsibilities", {}) or {}).get(key)
        )
        for key in ROLE_RESPONSIBILITIES
    }
    if not evidence_items:
        responsibilities = {
            key: "none" for key in ROLE_RESPONSIBILITIES
        }
    raw_environment = evidence.get("role_environment", {})
    if not isinstance(raw_environment, dict):
        raw_environment = {}
    role_environment = {
        key: (
            str(raw_environment.get(key, "unknown"))
            if str(raw_environment.get(key, "unknown")) in allowed
            else "unknown"
        )
        for key, allowed in ROLE_ENVIRONMENT.items()
    }
    if not evidence_items:
        role_environment = {key: "unknown" for key in ROLE_ENVIRONMENT}

    recent = [
        season
        for season in histories[:3]
        if numeric(season.get("minutes")) >= 180
    ]
    recent_minutes = sum(numeric(season.get("minutes")) for season in recent)
    recent_penalties = sum(
        numeric(season.get("penalties_scored")) for season in recent
    )
    key_passes_per_90 = (
        90.0
        * sum(numeric(season.get("key_passes")) for season in recent)
        / max(1.0, recent_minutes)
    )
    contributions_per_90 = (
        90.0
        * sum(
            numeric(season.get("goals"))
            + numeric(season.get("assists"))
            for season in recent
        )
        / max(1.0, recent_minutes)
    )
    goal_threat_per_90 = (
        90.0
        * sum(
            numeric(season.get("goals"))
            + 0.35 * numeric(season.get("shots_on"))
            for season in recent
        )
        / max(1.0, recent_minutes)
    )
    transfermarkt_metrics = transfermarkt_role_metrics(
        history_player or {}
    )
    if recent_minutes < 180 and transfermarkt_metrics["minutes"] >= 180:
        recent_minutes = transfermarkt_metrics["minutes"]
        key_passes_per_90 = 0.0
        contributions_per_90 = transfermarkt_metrics[
            "contributions_per_90"
        ]
        goal_threat_per_90 = transfermarkt_metrics["goals_per_90"]

    # Historical responsibilities remain useful when no newer structured role
    # statement exists. Once current evidence is supplied, only explicitly
    # confirmed responsibilities are used.
    historical_role_is_portable = (
        club_changed is not True and not evidence_items
    )
    if historical_role_is_portable:
        if recent_penalties >= 2 and responsibilities["penalties"] == "none":
            responsibilities["penalties"] = "shared"
        if (
            position in {"MIDFIELDER", "FORWARD"}
            and key_passes_per_90 >= 1.25
            and responsibilities["playmaker"] == "none"
        ):
            responsibilities["playmaker"] = "shared"
        if (
            position in {"MIDFIELDER", "FORWARD"}
            and contributions_per_90 >= 0.42
            and responsibilities["offensive_focal_point"] == "none"
        ):
            responsibilities["offensive_focal_point"] = "shared"
        if (
            position == "DEFENDER"
            and goal_threat_per_90 >= 0.16
            and responsibilities["aerial_set_piece_target"] == "none"
        ):
            responsibilities["aerial_set_piece_target"] = "shared"

    responsibility_weights = {
        "penalties": (4.0, 8.0),
        "direct_free_kicks": (3.0, 6.0),
        "corners": (2.5, 5.0),
        "playmaker": (4.0, 8.0),
        "offensive_focal_point": (4.0, 8.0),
        "aerial_set_piece_target": (3.5, 7.0),
        "captain": (1.5, 2.5),
    }
    responsibility_score = sum(
        responsibility_weights[key][0 if level == "shared" else 1]
        for key, level in responsibilities.items()
        if level in {"shared", "primary"}
    )
    continuity_adjustment = {
        "expanded": 4.0,
        "confirmed": 2.0,
        "reduced": -10.0,
        "unknown": 0.0,
    }[continuity]
    environment_adjustment = (
        {
            "unknown": 0.0,
            "low": -4.0,
            "medium": 1.0,
            "high": 4.0,
        }[role_environment["coach_trust"]]
        + {
            "unknown": 0.0,
            "core": 4.0,
            "regular": 2.0,
            "rotation": -4.0,
            "development": -7.0,
            "surplus": -12.0,
        }[role_environment["squad_status"]]
        + {
            "unknown": 0.0,
            "poor": -5.0,
            "good": 1.5,
            "strong": 3.0,
        }[role_environment["tactical_fit"]]
        + {
            "unknown": 0.0,
            "low": 2.0,
            "medium": 0.0,
            "high": -5.0,
        }[role_environment["positional_competition"]]
        + {
            "unknown": 0.0,
            "fragile": -5.0,
            "uncertain": -2.0,
            "stable": 3.0,
        }[role_environment["role_stability"]]
    )
    environment_adjustment = max(
        -10.0,
        min(10.0, environment_adjustment),
    )
    expected_start_probability = clamp(
        evidence.get("expected_start_probability"),
        0,
    )
    if not evidence_items:
        expected_start_probability = 0.0
    team_quality_delta = max(
        -30.0,
        min(30.0, numeric(evidence.get("team_quality_delta"))),
    )
    if not evidence_items:
        team_quality_delta = 0.0
    return {
        "model_version": "expected-role-v3",
        "evidence_source": str(evidence.get("source", "explicit")),
        "continuity": continuity,
        "evidence_confidence": (
            str(evidence.get("confidence", "medium"))
            if evidence_items
            else "none"
        ),
        "expected_start_probability": round(expected_start_probability, 2),
        "team_quality_delta": round(team_quality_delta, 2),
        "responsibilities": responsibilities,
        "role_environment": role_environment,
        "historical_metrics": {
            "penalties_scored": round(recent_penalties, 2),
            "key_passes_per_90": round(key_passes_per_90, 3),
            "assists_per_90": round(
                transfermarkt_metrics["assists_per_90"],
                3,
            ),
            "historical_start_rate": round(
                transfermarkt_metrics["start_rate"],
                3,
            ),
            "contributions_per_90": round(contributions_per_90, 3),
            "defender_goal_threat_per_90": round(goal_threat_per_90, 3),
        },
        "adjustments": {
            "minutes_floor": round(
                40.0 + 0.55 * expected_start_probability
                if expected_start_probability > 0
                else 0.0,
                2,
            ),
            "role_floor": round(
                45.0 + 0.50 * expected_start_probability
                if expected_start_probability > 0
                else 0.0,
                2,
            ),
            "role": round(
                max(
                    -14.0,
                    min(
                        14.0,
                        continuity_adjustment
                        + responsibility_score
                        + environment_adjustment,
                    ),
                ),
                2,
            ),
            "context": round(
                max(-8.0, min(8.0, 0.25 * team_quality_delta)),
                2,
            ),
            "unknown_role_risk": max(
                -15.0,
                min(
                    15.0,
                    {
                        "expanded": -12.0,
                        "confirmed": -10.0,
                        "reduced": 8.0,
                        "unknown": 0.0,
                    }[continuity]
                    - 0.5 * environment_adjustment,
                ),
            ),
            "rotation_risk_cap": round(
                max(0.0, 100.0 - expected_start_probability)
                if expected_start_probability > 0
                else 100.0,
                2,
            ),
        },
        "evidence": evidence_items,
    }


def provider_season_form_score(
    position: str,
    stats: dict[str, Any],
) -> tuple[float, float]:
    """Return a sample-shrunk season score and its evidence confidence."""

    minutes = numeric(stats.get("minutes"))
    appearances = numeric(stats.get("appearances"))
    lineups = numeric(stats.get("lineups"))
    rating = numeric(stats.get("rating"))
    sample_confidence = min(
        1.0,
        max(minutes / 1_800.0, appearances / 24.0),
    )
    availability_score = clamp(32 + minutes / 32)
    starting_score = clamp(
        36 + 58 * lineups / max(1.0, appearances)
    )
    rating_score = (
        clamp(50 + (rating - 6.35) * 62)
        if rating > 0
        else 50.0
    )
    event_score = event_role_score(position, stats)
    observed_score = (
        0.24 * availability_score
        + 0.22 * starting_score
        + 0.24 * rating_score
        + 0.30 * event_score
    )
    return (
        clamp(50 + sample_confidence * (observed_score - 50)),
        sample_confidence,
    )


def transfermarkt_season_form_score(
    position: str,
    season: dict[str, Any],
) -> tuple[float, float]:
    """Score older seasons after league-strength adjustment."""

    minutes = numeric(season.get("minutes"))
    adjusted_minutes = numeric(season.get("level_adjusted_minutes"))
    appearances = numeric(season.get("appearances"))
    starts = numeric(season.get("starts"))
    contributions = numeric(season.get("goals")) + numeric(
        season.get("assists")
    )
    sample_confidence = min(
        0.86,
        max(adjusted_minutes / 1_900.0, appearances / 28.0),
    )
    strength_ratio = min(
        1.2,
        adjusted_minutes / max(1.0, minutes),
    )
    adjusted_contributions_per_900 = (
        900.0
        * contributions
        * strength_ratio
        / max(1.0, adjusted_minutes)
    )
    availability_score = clamp(30 + adjusted_minutes / 32)
    starting_score = clamp(
        38 + 55 * starts / max(1.0, appearances)
    )
    if position in {"MIDFIELDER", "FORWARD"}:
        production_score = clamp(
            42 + 8.5 * adjusted_contributions_per_900
        )
    else:
        production_score = clamp(48 + 2.5 * adjusted_contributions_per_900)
    observed_score = (
        0.42 * availability_score
        + 0.34 * starting_score
        + 0.24 * production_score
    )
    return (
        clamp(50 + sample_confidence * (observed_score - 50)),
        sample_confidence,
    )


def historical_form_profile(
    *,
    position: str,
    histories: list[dict[str, Any]],
    history_player: dict[str, Any],
    market_club: str,
    news_player: dict[str, Any],
    age: int,
    role_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a recency-weighted form curve with context uncertainty."""

    by_season: dict[int, dict[str, Any]] = {}
    provider_by_season = {
        int(stats.get("season", 0)): stats
        for stats in histories
        if int(stats.get("season", 0)) > 0
    }
    transfermarkt_by_season = {
        int(season.get("season", 0)): season
        for season in history_player.get("seasons", [])
        if int(season.get("season", 0)) > 0
    }
    for season_id in sorted(
        set(provider_by_season) | set(transfermarkt_by_season),
        reverse=True,
    ):
        provider = provider_by_season.get(season_id)
        transfermarkt = transfermarkt_by_season.get(season_id)
        scores: list[tuple[float, float, float]] = []
        competition_context_factor = 1.0
        if transfermarkt is not None:
            competition_context_factor = min(
                1.0,
                max(
                    0.20,
                    numeric(transfermarkt.get("level_adjusted_minutes"))
                    / max(
                        1.0,
                        numeric(transfermarkt.get("minutes")),
                    ),
                ),
            )
        if provider is not None:
            score, confidence = provider_season_form_score(
                position,
                provider,
            )
            score = clamp(
                50
                + competition_context_factor * (score - 50)
            )
            scores.append((score, confidence, 0.70))
        if transfermarkt is not None:
            score, confidence = transfermarkt_season_form_score(
                position,
                transfermarkt,
            )
            scores.append((score, confidence, 0.30 if provider else 1.0))
        evidence_weight = sum(
            confidence * source_weight
            for _, confidence, source_weight in scores
        )
        if evidence_weight <= 0:
            continue
        season_score = (
            sum(
                score * confidence * source_weight
                for score, confidence, source_weight in scores
            )
            / max(evidence_weight, 1e-9)
        )
        season_confidence = min(
            1.0,
            sum(
                confidence * source_weight
                for _, confidence, source_weight in scores
            )
            / max(
                sum(source_weight for _, _, source_weight in scores),
                1e-9,
            ),
        )
        by_season[season_id] = {
            "season": season_id,
            "score": clamp(season_score),
            "confidence": season_confidence,
            "competition_context_factor": competition_context_factor,
            "minutes": numeric(
                (provider or transfermarkt or {}).get("minutes")
            ),
        }

    seasons = list(by_season.values())
    decay = 0.50 if age <= 21 else 0.62
    weighted_sum = 0.0
    total_weight = 0.0
    for index, season in enumerate(seasons):
        recency_weight = decay**index
        evidence_weight = recency_weight * max(
            0.20,
            float(season["confidence"]),
        )
        season["recency_weight"] = round(recency_weight, 4)
        weighted_sum += float(season["score"]) * evidence_weight
        total_weight += evidence_weight
    weighted_score = (
        weighted_sum / total_weight if total_weight > 0 else 50.0
    )
    trajectory_delta = (
        float(seasons[0]["score"]) - float(seasons[1]["score"])
        if len(seasons) >= 2
        else 0.0
    )
    development_adjustment = min(
        7.0,
        max(0.0, trajectory_delta)
        * (
            0.28
            if age <= 19
            else 0.20
            if age == 20
            else 0.13
            if age <= 23
            else 0.0
        ),
    )
    form_score = clamp(weighted_score + development_adjustment)
    form_confidence = min(
        1.0,
        sum(
            float(season["confidence"]) * decay**index
            for index, season in enumerate(seasons)
        )
        / max(
            sum(decay**index for index in range(len(seasons))),
            1e-9,
        ),
    )

    historical_clubs, club_changed, club_change_source = (
        historical_club_context(
            histories,
            market_club=market_club,
            news_player=news_player,
        )
    )
    explicit_role_evidence = (
        role_evidence if isinstance(role_evidence, dict) else {}
    )
    evidence_items = explicit_role_evidence.get("evidence", [])
    continuity = str(
        explicit_role_evidence.get("continuity", "unknown")
    ).strip().casefold()
    role_is_currently_evidenced = (
        continuity in ROLE_CONTINUITY - {"unknown"}
        and isinstance(evidence_items, list)
        and any(
            isinstance(item, dict)
            and str(item.get("source_url", "")).startswith("https://")
            and str(item.get("claim", "")).strip()
            and str(item.get("checked_at", "")).strip()
            for item in evidence_items
        )
    )
    context_transfer_factor = (
        1.0
        if role_is_currently_evidenced
        and continuity in {"confirmed", "expanded"}
        else 0.52
        if role_is_currently_evidenced and continuity == "reduced"
        else 0.58
        if club_changed is True
        else 1.0
        if club_changed is False
        else 0.82
    )

    latest_minutes = (
        numeric(seasons[0].get("minutes")) if seasons else 0.0
    )
    previous_minutes = (
        numeric(seasons[1].get("minutes")) if len(seasons) >= 2 else 0.0
    )
    availability_ratio = (
        latest_minutes / max(1.0, previous_minutes)
        if previous_minutes > 0
        else None
    )
    injury_risk = clamp(
        news_player.get("consensus", {}).get("injury", 0),
        0,
    )
    if injury_risk >= 40:
        recovery_status = "current_injury_or_recovery"
    elif (
        availability_ratio is not None
        and previous_minutes >= 900
        and availability_ratio < 0.55
    ):
        recovery_status = "recent_availability_drop"
    elif (
        availability_ratio is not None
        and latest_minutes >= 900
        and availability_ratio > 1.35
    ):
        recovery_status = "rebounded"
    elif len(seasons) >= 2:
        recovery_status = "stable"
    else:
        recovery_status = "insufficient_history"

    adjustment_confidence = 0.35 + 0.65 * form_confidence
    portable_delta = max(
        -10.0,
        min(10.0, 0.20 * (form_score - 50)),
    ) * adjustment_confidence
    # Missing minutes after an injury describe availability, not a sudden loss
    # of the player's healthy footballing level. Keep that quality baseline and
    # express the uncertainty through readiness and risk instead.
    confirmed_delta = (
        max(0.0, portable_delta)
        if recovery_status in {
            "current_injury_or_recovery",
            "recent_availability_drop",
        }
        else portable_delta
    )
    context_uncertainty = (
        0.0
        if role_is_currently_evidenced
        and continuity in {"confirmed", "expanded"}
        else 8.0
        if role_is_currently_evidenced and continuity == "reduced"
        else 6.0
        if club_changed is True
        else 2.0
        if club_changed is None
        else 0.0
    )
    if recovery_status == "recent_availability_drop":
        context_uncertainty += 4.0
    return {
        "model_version": FORM_MODEL_VERSION,
        "score": round(form_score, 2),
        "confidence": round(form_confidence, 3),
        "season_count": len(seasons),
        "recency_decay": decay,
        "latest_season_score": (
            round(float(seasons[0]["score"]), 2) if seasons else 50.0
        ),
        "trajectory_delta": round(trajectory_delta, 2),
        "development_adjustment": round(development_adjustment, 2),
        "seasons": [
            {
                "season": int(season["season"]),
                "score": round(float(season["score"]), 2),
                "confidence": round(float(season["confidence"]), 3),
                "recency_weight": season["recency_weight"],
                "competition_context_factor": round(
                    float(season["competition_context_factor"]),
                    3,
                ),
            }
            for season in seasons
        ],
        "current_club": market_club,
        "latest_historical_clubs": historical_clubs,
        "club_changed": club_changed,
        "club_change_source": club_change_source,
        "context_transfer_factor": context_transfer_factor,
        "role_continuity": (
            continuity if role_is_currently_evidenced else "unknown"
        ),
        "availability_ratio": (
            round(availability_ratio, 3)
            if availability_ratio is not None
            else None
        ),
        "recovery_status": recovery_status,
        "adjustments": {
            "confirmed_performance": round(
                confirmed_delta
                * (
                    0.85
                    if club_changed is True
                    and not (
                        role_is_currently_evidenced
                        and continuity in {"confirmed", "expanded"}
                    )
                    else 1.0
                ),
                2,
            ),
            "role": round(portable_delta * context_transfer_factor, 2),
            "context": round(
                portable_delta * context_transfer_factor * 0.80,
                2,
            ),
            "upside": round(
                min(
                    8.0,
                    max(0.0, trajectory_delta)
                    * (0.24 if age <= 21 else 0.08),
                ),
                2,
            ),
            "unknown_role_risk": round(context_uncertainty, 2),
        },
    }


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


def preseason_adjustment(
    preseason_player: dict[str, Any] | None,
    *,
    age: int,
    proven_seasons: int,
    comparable_minutes: float,
    youth_score: float,
    talent_score: float,
    minutes: float,
    role: float,
    upside: float,
    value: float,
    unknown_role: float,
    fitness: float = 50.0,
    injury_risk: float = 0.0,
) -> dict[str, Any]:
    """Blend preparation into readiness without turning friendlies into proof."""

    empty = {
        "available": False,
        "classification": "insufficient",
        "confidence": "low",
        "appearances": 0,
        "starts": 0,
        "minutes": 0,
        "goals": 0,
        "assists": 0,
        "signal_score": 50.0,
        "availability_score": 50.0,
        "role_score": 50.0,
        "performance_score": 50.0,
        "opponent_score": 50.0,
        "effective_factor": 0.0,
        "applied_weight": 0.0,
        "readiness_delta": 0.0,
        "talent_status": "unchanged",
        "components": {
            "minutes": minutes,
            "role": role,
            "upside": upside,
            "value": value,
            "fitness": fitness,
        },
        "training_score": 50.0,
        "latest_training_status": "unknown",
        "recovery_risk_floor": 0.0,
        "injury_risk": injury_risk,
        "unknown_role": unknown_role,
    }
    if not isinstance(preseason_player, dict):
        return empty
    summary = preseason_player.get("summary", {})
    if not isinstance(summary, dict):
        return empty
    appearances = int(summary.get("appearances", 0))
    official_sources = int(summary.get("official_source_count", 0))
    training_status = str(summary.get("latest_training_status", "unknown"))
    recovery_evidence = (
        official_sources >= 1 and training_status in {"partial", "absent"}
    )
    if appearances <= 0 and not recovery_evidence:
        return empty
    confidence = str(summary.get("confidence", "low"))
    confidence_factor = {"low": 0.55, "medium": 0.78, "high": 1.0}.get(
        confidence,
        0.55,
    )
    sample_factor = (
        min(1.0, appearances / 3.0)
        if appearances > 0
        else 0.65
    )
    effective_factor = clamp(summary.get("effective_factor"), 0) / 100.0
    thin_history = proven_seasons == 0 or comparable_minutes < 900
    base_weight = (
        0.25
        if age <= 21 and thin_history
        else 0.18
        if thin_history
        else 0.10
        if age <= 23
        else 0.06
    )
    applied_weight = base_weight * confidence_factor * sample_factor * effective_factor
    availability_score = clamp(summary.get("availability_score"), 50)
    role_score = clamp(summary.get("role_score"), 50)
    signal_score = clamp(summary.get("signal_score"), 50)
    training_score = clamp(summary.get("training_score"), 50)
    adjusted_minutes = clamp(
        minutes + applied_weight * (availability_score - minutes)
    )
    adjusted_role = clamp(role + applied_weight * (role_score - role))
    positive_signal = max(0.0, signal_score - 50.0)
    adjusted_upside = max(
        upside,
        clamp(talent_score + 0.22 * positive_signal),
    )
    adjusted_value = max(
        value,
        clamp(
            0.58 * value
            + 0.24 * signal_score
            + 0.18 * availability_score
        ),
    )
    adjusted_unknown_role = clamp(
        max(
            18.0,
            unknown_role - applied_weight * positive_signal * 0.75,
        )
    )
    recovery_risk_floor = (
        72.0 if training_status == "absent" else 45.0
        if training_status == "partial" else 0.0
    )
    fitness_cap = (
        35.0 if training_status == "absent" else 68.0
        if training_status == "partial" else 100.0
    )
    adjusted_fitness = (
        min(
            fitness,
            fitness_cap,
            clamp(0.65 * fitness + 0.35 * training_score),
        )
        if training_status in {"full", "partial", "absent"}
        else min(fitness, fitness_cap)
    )
    adjusted_injury_risk = max(injury_risk, recovery_risk_floor)
    high_upside = (
        age <= 21
        and proven_seasons == 0
        and (
            talent_score >= 68
            or (talent_score >= 52 and youth_score >= 80)
            or youth_score >= 90
        )
        and signal_score >= 60
        and appearances >= 2
        and confidence in {"medium", "high"}
    )
    watchlist = (
        age <= 22
        and proven_seasons == 0
        and max(talent_score, youth_score) >= 52
        and signal_score >= 56
    )
    talent_status = (
        "high_upside_pre_breakthrough"
        if high_upside
        else "preseason_watchlist"
        if watchlist
        else "unchanged"
    )
    return {
        "available": True,
        "classification": str(summary.get("classification", "insufficient")),
        "confidence": confidence,
        "appearances": appearances,
        "starts": int(summary.get("starts", 0)),
        "minutes": int(summary.get("minutes", 0)),
        "goals": int(summary.get("goals", 0)),
        "assists": int(summary.get("assists", 0)),
        "signal_score": signal_score,
        "availability_score": availability_score,
        "role_score": role_score,
        "performance_score": clamp(summary.get("performance_score"), 50),
        "opponent_score": clamp(summary.get("opponent_score"), 50),
        "training_score": training_score,
        "latest_training_status": training_status,
        "recovery_risk_floor": recovery_risk_floor,
        "injury_risk": adjusted_injury_risk,
        "effective_factor": clamp(summary.get("effective_factor"), 0),
        "applied_weight": round(applied_weight, 4),
        "readiness_delta": round(
            0.5 * (adjusted_minutes - minutes)
            + 0.5 * (adjusted_role - role),
            2,
        ),
        "talent_status": talent_status,
        "components": {
            "minutes": adjusted_minutes,
            "role": adjusted_role,
            "upside": adjusted_upside,
            "value": adjusted_value,
            "fitness": adjusted_fitness,
        },
        "unknown_role": adjusted_unknown_role,
    }


def lower_league_translation_profile(
    history_player: dict[str, Any],
    *,
    position: str,
    target_strength: float,
    age: int,
) -> dict[str, Any]:
    """Translate recent standout production one tier below the target league."""

    candidates: list[dict[str, Any]] = []
    for season in history_player.get("seasons", [])[:2]:
        for competition in season.get("competitions", []):
            if str(competition.get("kind", "")) != "domestic_league":
                continue
            strength = numeric(competition.get("strength_factor"))
            if not target_strength * 0.70 <= strength < target_strength * 0.92:
                continue
            minutes = numeric(competition.get("minutes"))
            appearances = numeric(competition.get("appearances"))
            starts = numeric(competition.get("starts"))
            contributions = numeric(competition.get("goals")) + numeric(
                competition.get("assists")
            )
            if minutes < 700:
                continue
            translation = min(1.0, strength / max(0.01, target_strength))
            start_rate = starts / max(1.0, appearances)
            production_per_900 = 900.0 * contributions / max(1.0, minutes)
            role_score = clamp(38 + 42 * start_rate + min(20, minutes / 120))
            production_score = (
                clamp(40 + 9 * production_per_900)
                if position in {"MIDFIELDER", "FORWARD"}
                else clamp(46 + 3 * production_per_900)
            )
            translated_score = clamp(
                translation * (0.62 * role_score + 0.38 * production_score)
                + (1.0 - translation) * 42
            )
            candidates.append(
                {
                    "season": int(season.get("season", 0)),
                    "competition": str(competition.get("label", "")),
                    "strength_ratio": round(translation, 3),
                    "minutes": int(minutes),
                    "start_rate": round(start_rate, 3),
                    "contributions_per_900": round(production_per_900, 2),
                    "translated_score": translated_score,
                }
            )
    best = max(candidates, key=lambda item: item["translated_score"], default=None)
    if best is None:
        return {
            "status": "none",
            "score": 50.0,
            "value_bonus": 0.0,
            "upside_bonus": 0.0,
            "evidence": None,
        }
    age_multiplier = 1.15 if age <= 22 else 1.0 if age <= 27 else 0.85
    surplus = max(0.0, float(best["translated_score"]) - 55.0)
    return {
        "status": (
            "standout_lower_league"
            if surplus >= 8 and int(best["minutes"]) >= 1200
            else "lower_league_watch"
        ),
        "score": best["translated_score"],
        "value_bonus": round(min(8.0, surplus * 0.30 * age_multiplier), 2),
        "upside_bonus": round(min(7.0, surplus * 0.26 * age_multiplier), 2),
        "evidence": best,
    }


def loan_pathway_profile(
    history_player: dict[str, Any],
    transfer_profile: dict[str, Any] | None,
    *,
    talent_profile: dict[str, Any],
    lower_league_profile: dict[str, Any],
    role_context: dict[str, Any],
    target_strength: float,
    age: int,
) -> dict[str, Any]:
    """Value a loan pathway without treating parent-club prestige as proof."""

    transfer = (
        transfer_profile if isinstance(transfer_profile, dict) else {}
    )
    active_loan = (
        transfer.get("status") == "confirmed"
        and transfer.get("stage") == "official"
        and transfer.get("direction") == "in"
        and transfer.get("deal_type") == "loan"
        and transfer.get("fresh", False)
    )
    if not active_loan:
        return {
            "model_version": "loan-pathway-v1",
            "status": "none",
            "qualified_potential": False,
            "parent_club": "",
            "parent_club_level": "unknown",
            "loan_intent": "unclear",
            "source_level": None,
            "higher_tier_senior_minutes": 0,
            "value_bonus": 0.0,
            "upside_bonus": 0.0,
            "minutes_floor": 0.0,
            "role_floor": 0.0,
            "evidence": [],
        }

    senior_competitions: list[dict[str, Any]] = []
    higher_tier_minutes = 0.0
    for season in history_player.get("seasons", [])[:3]:
        for competition in season.get("competitions", []):
            if str(competition.get("kind", "")) != "domestic_league":
                continue
            strength = numeric(competition.get("strength_factor"))
            minutes = numeric(competition.get("minutes"))
            if minutes <= 0:
                continue
            senior_competitions.append(
                {
                    "competition": str(competition.get("label", "")),
                    "strength_factor": round(strength, 3),
                    "minutes": int(minutes),
                }
            )
            if strength >= target_strength:
                higher_tier_minutes += minutes
    source_level = max(
        senior_competitions,
        key=lambda item: (
            float(item["strength_factor"]),
            int(item["minutes"]),
        ),
        default=None,
    )

    talent_score = numeric(talent_profile.get("talent_score"))
    readiness = numeric(talent_profile.get("readiness_score"))
    early_senior_minutes = numeric(
        talent_profile.get("early_senior_weighted_minutes")
    )
    lower_status = str(lower_league_profile.get("status", "none"))
    parent_level = str(
        transfer.get("parent_club_level", "unknown")
    )
    intent = str(transfer.get("loan_intent", "unclear"))
    start_probability = numeric(
        role_context.get("expected_start_probability")
    )
    role_evidenced = bool(role_context.get("evidence"))

    maturity_signal = (
        3.0
        if age <= 18 and early_senior_minutes >= 1_200
        else 2.0
        if age <= 20 and early_senior_minutes >= 700
        else 1.0
        if age <= 22 and readiness >= 60
        else 0.0
    )
    parent_signal = {
        "top_five_first_division": 1.5,
        "other_first_division": 0.75,
        "lower_division": 0.25,
        "unknown": 0.0,
    }.get(parent_level, 0.0)
    intent_signal = {
        "immediate_help": 2.0,
        "development_minutes": 1.25,
        "squad_depth": -1.5,
        "unclear": 0.0,
    }.get(intent, 0.0)
    role_signal = (
        2.0
        if role_evidenced and start_probability >= 75
        else 1.0
        if role_evidenced and start_probability >= 60
        else 0.0
    )
    lower_signal = (
        2.0
        if lower_status == "standout_lower_league"
        else 0.75
        if lower_status == "lower_league_watch"
        else 0.0
    )
    higher_level_signal = min(2.5, higher_tier_minutes / 600)
    independent_signal = (
        maturity_signal
        + lower_signal
        + higher_level_signal
        + role_signal
    )
    # Parent-club reputation is only a small corroborating signal. It cannot
    # create a qualified pathway without performance, maturity, or role proof.
    qualified = (
        age <= 23
        and (
            talent_score >= 68
            or higher_tier_minutes >= 300
            or (
                lower_status == "standout_lower_league"
                and readiness >= 58
            )
        )
    )
    pathway_increment = (
        min(1.0, 0.33 * maturity_signal)
        + min(0.75, 0.38 * lower_signal)
        + min(0.75, 0.30 * higher_level_signal)
        + role_signal
        + min(parent_signal, max(0.0, independent_signal * 0.35))
        + intent_signal
    )
    value_bonus = (
        min(
            5.0,
            max(0.0, pathway_increment),
        )
        if qualified
        else 0.0
    )
    upside_bonus = (
        min(
            6.0,
            max(0.0, 0.9 * pathway_increment),
        )
        if qualified
        else 0.0
    )
    minutes_floor = (
        clamp(48 + 0.24 * start_probability)
        if qualified and role_evidenced and start_probability >= 60
        else 0.0
    )
    role_floor = (
        clamp(50 + 0.24 * start_probability)
        if qualified and role_evidenced and start_probability >= 60
        else 0.0
    )
    return {
        "model_version": "loan-pathway-v1",
        "status": (
            "qualified"
            if qualified
            else "loan_watch"
        ),
        "qualified_potential": qualified,
        "parent_club": str(transfer.get("from_club", "")).strip(),
        "parent_club_level": parent_level,
        "loan_intent": intent,
        "source_level": source_level,
        "higher_tier_senior_minutes": int(higher_tier_minutes),
        "parent_environment_signal": round(parent_signal, 2),
        "independent_performance_signal": round(independent_signal, 2),
        "value_bonus": round(value_bonus, 2),
        "upside_bonus": round(upside_bonus, 2),
        "minutes_floor": minutes_floor,
        "role_floor": role_floor,
        "evidence": [
            {
                "claim": str(item.get("claim", "")).strip(),
                "source_url": str(item.get("source_url", "")).strip(),
                "checked_at": str(item.get("observed_at", "")).strip(),
            }
            for item in transfer.get("evidence", [])
            if isinstance(item, dict)
            and str(item.get("claim", "")).strip()
            and str(item.get("source_url", "")).startswith("https://")
        ],
    }


def build_annotation(
    market_player: dict[str, Any],
    news_id: str,
    news_player: dict[str, Any],
    histories: list[dict[str, Any]],
    history_player: dict[str, Any],
    kicker_history_player: dict[str, Any] | None = None,
    talent_evidence: dict[str, Any] | None = None,
    role_evidence: dict[str, Any] | None = None,
    manual_news_clearance: dict[str, Any] | None = None,
    preseason_player: dict[str, Any] | None = None,
    transfer_profile: dict[str, Any] | None = None,
    *,
    competition: str,
    points_pct: float,
    price_pct: float,
    generated_at: str,
    target_strength: float = 0.8,
) -> dict[str, Any]:
    position = str(market_player["position"])
    consensus = news_player.get("consensus", {})
    latest = next(
        (
            stats
            for stats in histories
            if numeric(stats.get("minutes")) >= 90
            or numeric(stats.get("appearances")) >= 2
        ),
        histories[0] if histories else {},
    )
    api_proven_seasons = sum(
        season_is_proven(position, stats) for stats in histories
    )
    career_appearances = sum(int(stats["appearances"]) for stats in histories)
    career_minutes = sum(int(stats["minutes"]) for stats in histories)
    career_goals = sum(int(stats["goals"]) for stats in histories)
    career_assists = sum(int(stats["assists"]) for stats in histories)
    contributions = career_goals + career_assists
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
    transfer_signals = [
        signal
        for signal in news_player.get("signals", [])
        if (
            isinstance(signal, dict)
            and str(signal.get("kind", "")).startswith("transfer")
        )
    ]
    if (
        transfer_signals
        and all(
            str(signal.get("kind")) == "transfer_confirmed"
            and str(signal.get("status")) == "confirmed"
            and str(signal.get("availability_impact")) == "in"
            for signal in transfer_signals
        )
    ):
        # A completed incoming move is a club-context event, not an ongoing
        # risk that the player will leave the newly listed Kicker club.
        transfer_risk = 0.0
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
    _, club_changed_hint, _ = historical_club_context(
        histories,
        market_club=str(market_player["club"]),
        news_player=news_player,
    )
    resolved_role_evidence = resolve_role_evidence(
        position=position,
        history_player=history_player,
        preseason_player=preseason_player,
        explicit_role_evidence=role_evidence,
        club_changed=club_changed_hint,
    )
    form_summary = historical_form_profile(
        position=position,
        histories=histories,
        history_player=history_player,
        market_club=str(market_player["club"]),
        news_player=news_player,
        age=age,
        role_evidence=resolved_role_evidence,
    )
    form_adjustments = form_summary["adjustments"]
    confirmed = clamp(
        confirmed + float(form_adjustments["confirmed_performance"])
    )
    role = clamp(role + float(form_adjustments["role"]))
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
    upside = clamp(
        max(base_upside, youth_upside, editorial_upside)
        + float(form_adjustments["upside"])
    )
    value = clamp(
        0.42 * (100 - price_pct)
        + 0.32 * confirmed
        + 0.26 * points_pct
        + 0.08 * (trend_score - 50)
    )
    lower_league_profile = lower_league_translation_profile(
        history_player,
        position=position,
        target_strength=target_strength,
        age=age,
    )
    upside = clamp(
        upside + float(lower_league_profile["upside_bonus"])
    )
    value = clamp(value + float(lower_league_profile["value_bonus"]))
    if age <= 21 and talent_score >= 68:
        talent_value = clamp(
            0.20 * (100 - price_pct)
            + 0.35 * readiness_score
            + 0.25 * editorial_talent_signal
            + 0.20 * role
        )
        value = max(value, talent_value)
    baseline_unknown_role = clamp(
        max(
            20.0,
            62.0 - 0.42 * readiness_score,
            74.0 - role,
        )
        if age <= 21 and talent_score >= 52
        else 74.0 - role
    )
    preseason_summary = preseason_adjustment(
        preseason_player,
        age=age,
        proven_seasons=proven_seasons,
        comparable_minutes=float(
            history_career.get("comparable_minutes", 0)
        ),
        youth_score=history_youth_score,
        talent_score=talent_score,
        minutes=minutes,
        role=role,
        upside=upside,
        value=value,
        unknown_role=baseline_unknown_role,
        fitness=fitness,
        injury_risk=injury_risk,
    )
    minutes = float(preseason_summary["components"]["minutes"])
    role = float(preseason_summary["components"]["role"])
    upside = float(preseason_summary["components"]["upside"])
    value = float(preseason_summary["components"]["value"])
    fitness = float(preseason_summary["components"]["fitness"])
    injury_risk = float(preseason_summary["injury_risk"])
    role_context = expected_role_profile(
        position=position,
        histories=histories,
        history_player=history_player,
        role_evidence=resolved_role_evidence,
        club_changed=form_summary["club_changed"],
    )
    loan_pathway = loan_pathway_profile(
        history_player,
        transfer_profile,
        talent_profile=talent_profile,
        lower_league_profile=lower_league_profile,
        role_context=role_context,
        target_strength=target_strength,
        age=age,
    )
    minutes = max(minutes, float(loan_pathway["minutes_floor"]))
    role = max(role, float(loan_pathway["role_floor"]))
    upside = clamp(upside + float(loan_pathway["upside_bonus"]))
    value = clamp(value + float(loan_pathway["value_bonus"]))
    role_adjustments = role_context["adjustments"]
    transfermarkt_scorer_metrics = transfermarkt_role_metrics(
        history_player
    )
    api_goals_per_90 = 90.0 * career_goals / max(1.0, career_minutes)
    api_assists_per_90 = 90.0 * career_assists / max(
        1.0,
        career_minutes,
    )
    scorer_profile = {
        "model_version": "repeatable-scorer-v1",
        "goals_per_90": round(
            max(
                api_goals_per_90,
                transfermarkt_scorer_metrics["goals_per_90"],
            ),
            3,
        ),
        "assists_per_90": round(
            max(
                api_assists_per_90,
                transfermarkt_scorer_metrics["assists_per_90"],
            ),
            3,
        ),
        "contributions_per_90": round(
            max(
                api_goals_per_90 + api_assists_per_90,
                transfermarkt_scorer_metrics[
                    "contributions_per_90"
                ],
            ),
            3,
        ),
        "sample_minutes": round(
            max(
                float(career_minutes),
                transfermarkt_scorer_metrics["minutes"],
            ),
            1,
        ),
        "proven_seasons": int(history_proven_seasons),
        "responsibilities": dict(role_context["responsibilities"]),
    }
    repeatable_attacking_scorer = (
        position in {"MIDFIELDER", "FORWARD"}
        and history_proven_seasons >= 3
        and confirmed >= 72
        and (
            scorer_profile["contributions_per_90"] >= 0.30
            or points_pct >= 88
        )
    )
    current_role_is_resolved = (
        role_context["continuity"] in {"confirmed", "expanded", "reduced"}
        and bool(role_context["evidence"])
        and role_context["evidence_confidence"] in {"low", "medium", "high"}
    )
    role_research_required = (
        form_summary["club_changed"] is True
        and repeatable_attacking_scorer
        and not current_role_is_resolved
    )
    role_research = {
        "model_version": "premium-transfer-role-gate-v1",
        "required": role_research_required,
        "priority": "high" if role_research_required else "none",
        "reason": (
            "A proven attacking scorer changed clubs, but the current "
            "starting probability and responsibilities are not evidenced."
            if role_research_required
            else ""
        ),
    }
    manual_clearance = manual_news_clearance_profile(
        manual_news_clearance,
        generated_at=generated_at,
    )
    if manual_clearance["valid"]:
        transfer_risk = max(
            transfer_risk,
            float(manual_clearance["risk_floors"]["transfer"]),
        )
        injury_risk = max(
            injury_risk,
            float(manual_clearance["risk_floors"]["injury"]),
        )
        rotation_risk = max(
            rotation_risk,
            float(manual_clearance["risk_floors"]["rotation"]),
        )
        fitness = min(
            fitness,
            float(manual_clearance["fitness_cap"]),
        )
    minutes = max(
        minutes,
        float(role_adjustments["minutes_floor"]),
    )
    role = max(
        float(role_adjustments["role_floor"]),
        clamp(role + float(role_adjustments["role"])),
    )
    risks = {
        "transfer": transfer_risk,
        "injury": injury_risk,
        "rotation": max(
            rotation_risk,
            min(
                float(role_adjustments["rotation_risk_cap"]),
                clamp(82 - minutes),
            ),
        ),
        "outlier": clamp(42 - 15 * proven_seasons + max(0, points_pct - 88) * 1.2),
        "unknown_role": clamp(
            float(preseason_summary["unknown_role"])
            + float(form_adjustments["unknown_role_risk"])
            + float(role_adjustments["unknown_role_risk"])
        ),
    }
    components = {
        "confirmed_performance": confirmed,
        "minutes": minutes,
        "role": role,
        "stability": stability,
        "context": clamp(
            65
            + 0.18 * (trend_score - 50)
            + float(form_adjustments["context"])
            + float(role_adjustments["context"])
        ),
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
        and float(form_summary["context_transfer_factor"]) >= 0.75
    )
    provider_id = optional_int(
        news_player.get("mapping", {}).get("api_sports_player_id")
    )
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
            "claim": "Aktuelle Verletzungs-, Transfer- und Rollenprüfung",
            "source_url": (
                "https://geozocco.github.io/kicker-interactive-manager/"
                f"v1/news/{'2-bundesliga' if competition == '2. Bundesliga' else '3-liga'}.json"
            ),
            "checked_at": generated_at,
        },
    ]
    if provider_id is not None:
        evidence.insert(
            1,
            {
                "claim": (
                    "Ergänzende mehrjährige Einsatz-, Bewertungs- und "
                    "Scorerhistorie"
                ),
                "source_url": (
                    "https://v3.football.api-sports.io/players"
                    f"?id={provider_id}"
                ),
                "checked_at": generated_at,
            },
        )
    evidence.extend(manual_clearance["evidence"])
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
    for item in role_context["evidence"]:
        evidence.append(
            {
                "claim": str(item["claim"]),
                "source_url": str(item["source_url"]),
                "checked_at": str(item["checked_at"]),
            }
        )
    for item in loan_pathway["evidence"]:
        evidence.append(dict(item))
    for item in (preseason_player or {}).get("observations", []):
        if (
            isinstance(item, dict)
            and str(item.get("claim", "")).strip()
            and str(item.get("source_url", "")).startswith("https://")
        ):
            evidence.append(
                {
                    "claim": str(item["claim"]),
                    "source_url": str(item["source_url"]),
                    "checked_at": str(item.get("date", generated_at)),
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
        "lower_league_translation": lower_league_profile,
        "loan_pathway": loan_pathway,
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
                (
                    "Vorbereitung: "
                    f"{preseason_summary['classification']} "
                    f"({preseason_summary['signal_score']:.1f}/100; "
                    f"{preseason_summary['appearances']} Einsätze, "
                    f"{preseason_summary['starts']} Startelf). "
                    f"Status {preseason_summary['talent_status']}."
                    if preseason_summary["available"]
                    else ""
                ),
                (
                    "Formkurve: "
                    f"{form_summary['score']:.1f}/100 über "
                    f"{form_summary['season_count']} Spielzeiten, "
                    f"Trend {form_summary['trajectory_delta']:+.1f}; "
                    f"Kontext {form_summary['context_transfer_factor']:.2f}, "
                    f"Status {form_summary['recovery_status']}."
                    if form_summary["season_count"] > 0
                    else ""
                ),
                (
                    "Erwartete Rolle: "
                    f"{role_context['continuity']}, "
                    f"Startwahrscheinlichkeit "
                    f"{role_context['expected_start_probability']:.0f}%, "
                    f"Teamkontext {role_context['team_quality_delta']:+.0f}."
                    if role_context["evidence"]
                    else ""
                ),
                (
                    "Leihpfad: "
                    f"{loan_pathway['status']}, "
                    f"Stammvereinsniveau "
                    f"{loan_pathway['parent_club_level']}, "
                    f"Leihzweck {loan_pathway['loan_intent']}."
                    if loan_pathway["status"] != "none"
                    else ""
                ),
                str(talent_evidence.get("note", "")).strip(),
            )
            if part
        ),
        "evidence": evidence,
        "provider_news_id": news_id,
        "provider_mapping_status": (
            "verified" if provider_id is not None else "missing"
        ),
        "api_sports_history": histories,
        "api_sports_role_metrics": {
            "latest_event_score": round(latest_event_score, 2),
            "multi_season_event_score": round(event_score, 2),
            "provider_rating_score": round(rating_score, 2),
            "rating_weight_in_api_confirmation": 0.08,
        },
        "role_context": role_context,
        "loan_pathway": loan_pathway,
        "scorer_profile": scorer_profile,
        "role_research": role_research,
        "manual_news_clearance": manual_clearance,
        "kicker_trend": trend_summary,
        "form_summary": form_summary,
        "history_summary": history_summary,
        "preseason_summary": {
            key: value
            for key, value in preseason_summary.items()
            if key not in {"components", "unknown_role"}
        },
    }


def provider_position_is_goalkeeper(value: Any) -> bool:
    normalized = name_key(str(value or ""))
    return normalized in {"g", "gk", "goalkeeper", "keeper", "torwart"} or (
        "goalkeeper" in normalized or "torwart" in normalized
    )


def goalkeeper_hierarchy_score(
    annotation: dict[str, Any],
    *,
    club_price_share: float,
    global_price_percentile: float,
) -> float:
    components = annotation["components"]
    risks = annotation["risks"]
    return clamp(
        0.28 * float(components["minutes"])
        + 0.22 * float(components["role"])
        + 0.16 * float(components["confirmed_performance"])
        + 0.12 * float(components["upside"])
        + 0.16 * club_price_share
        + 0.06 * global_price_percentile
        - 0.12 * float(risks["transfer"])
        - 0.10 * float(risks["rotation"])
    )


def goalkeeper_rank_score(
    annotation: dict[str, Any],
    *,
    club_price_share: float,
    global_price_percentile: float,
    role_profile: dict[str, Any] | None,
) -> float:
    return clamp(
        goalkeeper_hierarchy_score(
            annotation,
            club_price_share=club_price_share,
            global_price_percentile=global_price_percentile,
        )
        + goalkeeper_role_cache_adjustment(role_profile)
    )


def apply_goalkeeper_hierarchy(
    annotations: dict[str, dict[str, Any]],
    market_payload: dict[str, Any],
    news_payload: dict[str, Any],
    config: dict[str, Any],
) -> None:
    """Attach a season-long number-one outlook to every researched keeper."""

    market_goalkeepers = [
        player
        for player in available_market_players(market_payload)
        if player["position"] == "GOALKEEPER"
    ]
    prices = [
        float(player["market_value"])
        for player in market_goalkeepers
    ]
    market_by_id = {
        str(player["id"]): player for player in market_goalkeepers
    }
    by_name, by_surname = news_provider_index(news_payload)
    matched_news_ids_by_club: dict[str, set[str]] = defaultdict(set)
    team_ids_by_club: dict[str, set[int]] = defaultdict(set)
    market_counts_by_club: dict[str, int] = defaultdict(int)
    for market_player in market_goalkeepers:
        club = str(market_player["club"])
        market_counts_by_club[club] += 1
        matched = match_news_player(market_player, by_name, by_surname)
        if matched is None:
            continue
        news_id, news_player = matched
        matched_news_ids_by_club[club].add(news_id)
        team_id = optional_int(
            news_player.get("mapping", {}).get("api_sports_team_id")
        )
        if team_id is not None:
            team_ids_by_club[club].add(team_id)

    provider_goalkeepers_by_team: dict[int, list[tuple[str, dict[str, Any]]]] = (
        defaultdict(list)
    )
    for news_id, news_player in news_payload["players"].items():
        mapping = news_player.get("mapping", {})
        if not provider_position_is_goalkeeper(mapping.get("position")):
            continue
        team_id = optional_int(mapping.get("api_sports_team_id"))
        if team_id is not None:
            provider_goalkeepers_by_team[team_id].append(
                (str(news_id), news_player)
            )

    annotation_ids_by_club: dict[str, list[str]] = defaultdict(list)
    for player_id, annotation in annotations.items():
        if annotation.get("position") == "GOALKEEPER":
            annotation_ids_by_club[str(annotation["club"])].append(player_id)

    hierarchy_evidence = config.get("goalkeeper_evidence", {})
    player_overrides = (
        hierarchy_evidence.get("players", {})
        if isinstance(hierarchy_evidence, dict)
        else {}
    )
    club_overrides = (
        hierarchy_evidence.get("clubs", {})
        if isinstance(hierarchy_evidence, dict)
        else {}
    )

    for club, player_ids in annotation_ids_by_club.items():
        club_market_players = [
            market_by_id[player_id]
            for player_id in player_ids
            if player_id in market_by_id
        ]
        total_price = sum(
            float(player["market_value"])
            for player in market_goalkeepers
            if str(player["club"]) == club
        )
        ranked: list[tuple[float, str, float, float]] = []
        for player_id in player_ids:
            market_player = market_by_id.get(player_id)
            if market_player is None:
                continue
            price = float(market_player["market_value"])
            price_share = 100.0 * price / max(1.0, total_price)
            price_percentile = percentile(price, prices)
            role_profile = (
                news_payload.get("role_profiles", {}).get(player_id, {})
                if isinstance(news_payload.get("role_profiles"), dict)
                else {}
            )
            ranked.append(
                (
                    goalkeeper_rank_score(
                        annotations[player_id],
                        club_price_share=price_share,
                        global_price_percentile=price_percentile,
                        role_profile=role_profile,
                    ),
                    player_id,
                    price_share,
                    price_percentile,
                )
            )
        ranked.sort(key=lambda item: (-item[0], -item[2], item[1]))
        if not ranked:
            continue

        provider_goalkeepers = [
            item
            for team_id in team_ids_by_club.get(club, set())
            for item in provider_goalkeepers_by_team.get(team_id, [])
        ]
        provider_goalkeeper_ids = {item[0] for item in provider_goalkeepers}
        unpriced_provider_ids = (
            provider_goalkeeper_ids - matched_news_ids_by_club.get(club, set())
        )
        incoming_unpriced = 0
        rumoured_unpriced = 0
        for news_id, news_player in provider_goalkeepers:
            if news_id not in unpriced_provider_ids:
                continue
            for signal in news_player.get("signals", []):
                if signal.get("availability_impact") != "in":
                    continue
                if signal.get("kind") == "transfer_confirmed":
                    incoming_unpriced += 1
                    break
                if signal.get("kind") == "transfer_rumour":
                    rumoured_unpriced += 1
                    break

        top_score, top_id, top_share, top_price_percentile = ranked[0]
        second_score = ranked[1][0] if len(ranked) > 1 else top_score - 4.0
        top_gap = max(0.0, top_score - second_score)
        confidence = (
            "high"
            if top_gap >= 12 and top_share >= 45
            else "medium"
            if top_gap >= 6 and top_share >= 35
            else "low"
        )
        top_annotation = annotations[top_id]
        external_signing_risk = (
            12.0
            + (25.0 if confidence == "low" else 10.0 if confidence == "medium" else 0)
            + (18.0 if top_price_percentile < 35 else 0)
            + (8.0 if int(top_annotation.get("proven_seasons", 0)) == 0 else 0)
            + min(12.0, 4.0 * len(unpriced_provider_ids))
            + min(55.0, 45.0 * incoming_unpriced)
            + min(30.0, 20.0 * rumoured_unpriced)
        )
        club_override = (
            club_overrides.get(club, {})
            if isinstance(club_overrides, dict)
            else {}
        )
        manual_club_context = isinstance(club_override, dict) and bool(
            club_override
        )
        if isinstance(club_override, dict) and (
            "external_signing_risk" in club_override
        ):
            external_signing_risk = clamp(
                club_override["external_signing_risk"]
            )
        top_cached_profile = (
            news_payload.get("role_profiles", {}).get(top_id, {})
            if isinstance(news_payload.get("role_profiles"), dict)
            else {}
        )
        if (
            isinstance(top_cached_profile, dict)
            and top_cached_profile.get("fresh", False)
        ):
            cached_external_risk = top_cached_profile.get(
                "external_signing_risk"
            )
            if isinstance(cached_external_risk, (int, float)) and not isinstance(
                cached_external_risk,
                bool,
            ):
                external_signing_risk = max(
                    external_signing_risk,
                    clamp(cached_external_risk),
                )
        if isinstance(club_override, dict):
            override_note = str(club_override.get("note", "")).strip()
            override_evidence = club_override.get("evidence", [])
            for player_id in player_ids:
                if override_note:
                    annotations[player_id]["note"] = " ".join(
                        part
                        for part in (
                            annotations[player_id].get("note", ""),
                            override_note,
                        )
                        if part
                    )
                for evidence in override_evidence:
                    if isinstance(evidence, dict):
                        annotations[player_id]["evidence"].append(evidence)
        external_signing_risk = clamp(external_signing_risk)
        current_hierarchy_probability = clamp(
            56.0 + 2.3 * top_gap + 0.22 * (top_share - 45.0)
        )
        season_starter_probability = clamp(
            current_hierarchy_probability - 0.35 * external_signing_risk
        )

        for rank, (score, player_id, price_share, price_percentile) in enumerate(
            ranked,
            start=1,
        ):
            gap_to_top = max(0.0, top_score - score)
            player_confidence = confidence
            if rank == 1:
                player_probability = season_starter_probability
                status = (
                    "external_signing_risk"
                    if external_signing_risk >= 55
                    else "clear_favourite"
                    if player_probability >= 82 and confidence == "high"
                    else "likely_starter"
                    if player_probability >= 70
                    else "open_competition"
                )
            else:
                player_probability = clamp(
                    max(2.0, 42.0 - 2.2 * gap_to_top)
                )
                status = "challenger" if gap_to_top < 10 else "backup"

            player_override = (
                player_overrides.get(player_id, {})
                if isinstance(player_overrides, dict)
                else {}
            )
            cached_profile = (
                news_payload.get("role_profiles", {}).get(player_id, {})
                if isinstance(news_payload.get("role_profiles"), dict)
                else {}
            )
            if isinstance(cached_profile, dict) and cached_profile.get(
                "fresh",
                False,
            ):
                cached_probability = clamp(
                    cached_profile.get("expected_start_probability"),
                    0,
                )
                designation = str(
                    cached_profile.get("designation", "")
                )
                if designation == "confirmed_starter":
                    player_probability = max(92.0, cached_probability)
                    status = "confirmed_starter"
                elif designation in {
                    "key_starter",
                    "expected_starter",
                    "immediate_help",
                }:
                    player_probability = max(
                        player_probability,
                        cached_probability,
                    )
                    status = (
                        "clear_favourite"
                        if player_probability >= 82
                        else "likely_starter"
                    )
                elif designation == "open_competition":
                    player_probability = min(player_probability, 69.0)
                    status = "open_competition"
                elif designation == "rotation":
                    player_probability = min(player_probability, 50.0)
                    status = "challenger"
                elif designation == "perspective":
                    player_probability = min(player_probability, 25.0)
                    status = "backup"
                cached_confidence = str(
                    cached_profile.get("confidence", "")
                )
                if cached_confidence in {"low", "medium", "high"}:
                    player_confidence = cached_confidence
                for item in cached_profile.get("evidence", []):
                    if not isinstance(item, dict):
                        continue
                    annotations[player_id]["evidence"].append(
                        {
                            "claim": str(item.get("claim", "")).strip(),
                            "source_url": str(
                                item.get("source_url", "")
                            ).strip(),
                            "checked_at": str(
                                item.get("observed_at", "")
                            ).strip(),
                        }
                    )
            if isinstance(player_override, dict):
                if "starter_probability" in player_override:
                    player_probability = clamp(
                        player_override["starter_probability"]
                    )
                if str(player_override.get("confidence", "")) in {
                    "low",
                    "medium",
                    "high",
                }:
                    player_confidence = str(player_override["confidence"])
                if str(player_override.get("status", "")) in {
                    "confirmed_starter",
                    "clear_favourite",
                    "likely_starter",
                    "open_competition",
                    "external_signing_risk",
                    "challenger",
                    "backup",
                }:
                    status = str(player_override["status"])
                for evidence in player_override.get("evidence", []):
                    if isinstance(evidence, dict):
                        annotations[player_id]["evidence"].append(evidence)
                override_note = str(player_override.get("note", "")).strip()
                if override_note:
                    annotations[player_id]["note"] = " ".join(
                        part
                        for part in (
                            annotations[player_id].get("note", ""),
                            override_note,
                        )
                        if part
                    )

            annotations[player_id]["goalkeeper_outlook"] = {
                "status": status,
                "starter_probability": round(player_probability, 2),
                "current_hierarchy_probability": round(
                    current_hierarchy_probability
                    if rank == 1
                    else max(2.0, 45.0 - 2.0 * gap_to_top),
                    2,
                ),
                "confidence": player_confidence,
                "club_rank": rank,
                "hierarchy_score": round(score, 2),
                "hierarchy_gap": round(
                    top_gap if rank == 1 else gap_to_top,
                    2,
                ),
                "club_price_share": round(price_share, 2),
                "global_price_percentile": round(price_percentile, 2),
                "external_signing_risk": round(external_signing_risk, 2),
                "market_goalkeeper_count": market_counts_by_club.get(
                    club,
                    len(club_market_players),
                ),
                "provider_goalkeeper_count": len(provider_goalkeeper_ids),
                "unpriced_provider_goalkeeper_count": len(
                    unpriced_provider_ids
                ),
                "incoming_unpriced_goalkeeper_count": incoming_unpriced,
                "basis": [
                    "aktuelle Einsatz- und Rollenwerte",
                    "Abstand zur vereinsinternen Konkurrenz",
                    "relativer Kicker-Preis im Torwartblock",
                    "aktuelle Provider-Kader- und Transferlage",
                    *(
                        ["aktuell belegte manuelle Vereins-/Trainerlage"]
                        if manual_club_context
                        else []
                    ),
                ],
            }


def mark_benchmark_references(
    annotations: dict[str, dict[str, Any]],
    per_position: int = 4,
) -> None:
    """Mark redundant, score-neutral comparison references per field position."""

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
        # Later injuries, transfers or provider-identity conflicts may remove
        # individual references. The optimizer still requires two eligible
        # benchmarks. These flags never affect player scoring.
        for player_id, _ in position_items[:per_position]:
            annotations[player_id]["benchmark"] = True


def generate_snapshot(
    market_payload: dict[str, Any],
    news_payload: dict[str, Any],
    preseason_payload: dict[str, Any],
    history_payload: dict[str, Any],
    kicker_history_payload: dict[str, Any],
    config: dict[str, Any],
    previous_quality_payload: dict[str, Any] | None = None,
    *,
    token: str,
    request_delay: float,
    ttl_hours: int,
) -> dict[str, Any]:
    if market_payload["competition"] != news_payload["competition"]:
        raise RuntimeError("market and news competition do not match")
    if market_payload["season"] != news_payload["season"]:
        raise RuntimeError("market and news season do not match")
    if market_payload["competition"] != preseason_payload["competition"]:
        raise RuntimeError("market and preseason competition do not match")
    if market_payload["season"] != preseason_payload["season"]:
        raise RuntimeError("market and preseason season do not match")
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
        preseason_payload,
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
    total_requests = sum(
        optional_int(
            news_player.get("mapping", {}).get(
                "api_sports_player_id"
            )
        )
        is not None
        for _, _, news_player in candidates
    ) * len(history_seasons)
    completed = 0
    reused = 0
    fetched = 0
    provider_rate_limited = str(
        preseason_payload.get("providers", {})
        .get("api_sports", {})
        .get("status", "")
    ).startswith("rate_limited")
    for market_player, news_id, news_player in candidates:
        provider_id = optional_int(
            news_player.get("mapping", {}).get(
                "api_sports_player_id"
            )
        )
        cached_by_season = cached_api_histories(
            previous_quality_payload,
            competition=str(market_payload["competition"]),
            season=str(market_payload["season"]),
            player_id=str(market_player["id"]),
            news_id=news_id,
        )
        fallback_by_season = cached_api_histories(
            previous_quality_payload,
            competition=str(market_payload["competition"]),
            season=str(market_payload["season"]),
            player_id=str(market_player["id"]),
            news_id=news_id,
            include_current=True,
        )
        histories: list[dict[str, Any]] = []
        for history_season in history_seasons:
            if provider_id is None:
                histories.append(
                    empty_season_stats(
                        history_season,
                        optional_int(
                            news_player.get("mapping", {}).get("age")
                        ),
                    )
                )
                continue
            cached = cached_by_season.get(history_season)
            if cached is not None:
                histories.append(cached)
                reused += 1
            elif provider_rate_limited:
                fallback = fallback_by_season.get(history_season)
                if fallback is not None:
                    histories.append(fallback)
                    reused += 1
                else:
                    histories.append(
                        empty_season_stats(
                            history_season,
                            optional_int(
                                news_player.get("mapping", {}).get("age")
                            ),
                        )
                    )
            else:
                try:
                    histories.append(
                        fetch_player_season(
                            provider_id,
                            history_season,
                            headers=headers,
                            request_delay=request_delay,
                        )
                    )
                    fetched += 1
                except RuntimeError as error:
                    fallback = fallback_by_season.get(history_season)
                    if not is_api_sports_rate_limit(error):
                        raise
                    provider_rate_limited = True
                    if fallback is not None:
                        histories.append(fallback)
                        reused += 1
                    else:
                        histories.append(
                            empty_season_stats(
                                history_season,
                                optional_int(
                                    news_player.get("mapping", {}).get("age")
                                ),
                            )
                        )
                    print(
                        "API-Sports rate limit reached; reusing validated "
                        "raw histories where available and leaving provider "
                        "history empty for newly selected players.",
                        file=sys.stderr,
                    )
            completed += 1
            print(
                f"quality history {completed}/{total_requests} "
                f"(reused={reused}, fetched={fetched})",
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
            cached_role_evidence(
                news_payload,
                str(market_player["id"]),
                config.get("role_evidence", {}).get(
                    str(market_player["id"]),
                    {},
                ),
            ),
            config.get("manual_news_clearance", {}).get(
                str(market_player["id"]),
                {},
            ),
            preseason_payload.get("players", {}).get(
                news_id,
                preseason_payload.get("players", {}).get(
                    str(market_player["id"])
                ),
            ),
            cached_transfer_profile(
                news_payload,
                str(market_player["id"]),
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
            target_strength=float(history_payload["target_strength"]),
        )
        annotations[str(market_player["id"])] = annotation

    apply_goalkeeper_hierarchy(
        annotations,
        market_payload,
        news_payload,
        config,
    )

    apply_advanced_signals(annotations, preseason_payload, news_payload)

    mark_benchmark_references(annotations)

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "expires_at": isoformat(generated + timedelta(hours=ttl_hours)),
        "competition": market_payload["competition"],
        "season": market_payload["season"],
        "market_sha256": market_sha256(market_payload),
        "news_sha256": news_sha256(news_payload),
        "preseason_sha256": preseason_sha256(preseason_payload),
        "history_sha256": history_sha256(history_payload),
        "kicker_history_sha256": kicker_history_sha256(
            kicker_history_payload
        ),
        "model_version": MODEL_VERSION,
        "form_model_version": FORM_MODEL_VERSION,
        "preseason_model_version": PRESEASON_MODEL_VERSION,
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
    parser.add_argument("--preseason", required=True)
    parser.add_argument("--history", required=True)
    parser.add_argument("--kicker-history", required=True)
    parser.add_argument("--previous-quality")
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
    preseason_payload = load_preseason_snapshot(args.preseason)
    history_payload = load_history_snapshot(args.history)
    kicker_history_payload = load_kicker_history_snapshot(
        args.kicker_history
    )
    previous_quality_payload = None
    if args.previous_quality:
        try:
            previous_quality_payload = load_quality_snapshot(
                args.previous_quality,
                require_fresh=False,
            )
        except (OSError, QualitySnapshotError) as error:
            print(
                f"Previous quality cache unavailable; refreshing live: {error}",
                file=sys.stderr,
            )
    payload = generate_snapshot(
        market_payload,
        news_payload,
        preseason_payload,
        history_payload,
        kicker_history_payload,
        config,
        previous_quality_payload,
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
