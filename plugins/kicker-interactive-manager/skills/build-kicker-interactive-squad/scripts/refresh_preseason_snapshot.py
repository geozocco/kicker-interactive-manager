#!/usr/bin/env python3
"""Build a decaying preseason evidence snapshot from API-Sports and official evidence."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from news_snapshot import load_snapshot as load_news_snapshot
from preseason_snapshot import (
    SCHEMA_VERSION,
    canonical_sha256,
    load_snapshot as load_preseason_snapshot,
    validate_snapshot,
)
from refresh_news_snapshot import (
    api_sports_pages,
    chunks,
    is_api_sports_daily_limit,
    optional_int,
)


API_BASE = "https://v3.football.api-sports.io"
LINEUP_ROLE = {
    "first_group": 100.0,
    "mixed": 65.0,
    "second_group": 35.0,
    "unknown": 50.0,
}
TRAINING_STATUS = {
    "full": 90.0,
    "partial": 55.0,
    "absent": 10.0,
    "unknown": 50.0,
}
CONFIDENCE_WEIGHT = {"low": 0.55, "medium": 0.78, "high": 1.0}
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


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def isoformat(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def clamp(value: Any, default: float = 50.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return round(max(0.0, min(100.0, number)), 2)


def parse_date(value: Any) -> date:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()


def normalized(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value).casefold()))


def fixture_is_preseason(item: dict[str, Any], patterns: list[str]) -> bool:
    league = item.get("league", {})
    label = normalized(
        f"{league.get('name', '')} {league.get('type', '')} "
        f"{league.get('round', '')}"
    )
    return any(normalized(pattern) in label for pattern in patterns)


def team_and_opponent(
    fixture: dict[str, Any],
    team_id: int,
) -> tuple[str, str]:
    teams = fixture.get("teams", {})
    home = teams.get("home", {}) if isinstance(teams, dict) else {}
    away = teams.get("away", {}) if isinstance(teams, dict) else {}
    if optional_int(home.get("id")) == team_id:
        return "home", str(away.get("name", "")).strip()
    return "away", str(home.get("name", "")).strip()


def fetch_fixtures(
    team_ids: Iterable[int],
    *,
    provider_season: int,
    window_start: date,
    window_end: date,
    patterns: list[str],
    headers: dict[str, str],
    request_delay: float,
) -> tuple[dict[int, dict[str, Any]], dict[int, set[int]], int]:
    fixtures: dict[int, dict[str, Any]] = {}
    team_fixtures: dict[int, set[int]] = defaultdict(set)
    calls = 0
    for team_id in sorted(set(team_ids)):
        for page in api_sports_pages(
            f"{API_BASE}/fixtures",
            query={
                "team": team_id,
                "season": provider_season,
                "from": window_start.isoformat(),
                "to": window_end.isoformat(),
                "status": "FT-AET-PEN",
            },
            headers=headers,
            paginate=False,
        ):
            calls += 1
            for item in page.get("response", []):
                if not isinstance(item, dict) or not fixture_is_preseason(
                    item,
                    patterns,
                ):
                    continue
                fixture_id = optional_int(item.get("fixture", {}).get("id"))
                if fixture_id is None:
                    continue
                fixtures[fixture_id] = item
                team_fixtures[team_id].add(fixture_id)
        time.sleep(request_delay)
    return fixtures, team_fixtures, calls


def fetch_fixture_details(
    fixtures: dict[int, dict[str, Any]],
    *,
    headers: dict[str, str],
    request_delay: float,
) -> tuple[dict[int, dict[str, Any]], int, int, int]:
    """Attach the player-stat endpoint to fixture metadata.

    API-Sports' general ``/fixtures`` response does not contain the ``players``
    collection. Fetching that endpoint again therefore produced apparently
    healthy snapshots with zero player evidence. ``/fixtures/players`` is the
    authoritative per-player source.
    """

    details: dict[int, dict[str, Any]] = {}
    calls = 0
    player_stat_fixtures = 0
    lineup_fixtures = 0
    for fixture_id in sorted(fixtures):
        player_blocks: list[dict[str, Any]] = []
        for page in api_sports_pages(
            f"{API_BASE}/fixtures/players",
            query={"fixture": fixture_id},
            headers=headers,
            paginate=False,
        ):
            calls += 1
            for item in page.get("response", []):
                if isinstance(item, dict):
                    player_blocks.append(item)
        detail = dict(fixtures[fixture_id])
        detail["players"] = player_blocks
        lineups = list(detail.get("lineups", []))
        if not player_blocks and not lineups:
            for page in api_sports_pages(
                f"{API_BASE}/fixtures/lineups",
                query={"fixture": fixture_id},
                headers=headers,
                paginate=False,
            ):
                calls += 1
                lineups.extend(
                    item
                    for item in page.get("response", [])
                    if isinstance(item, dict)
                )
            detail["lineups"] = lineups
        details[fixture_id] = detail
        if player_blocks:
            player_stat_fixtures += 1
        elif lineups:
            lineup_fixtures += 1
        time.sleep(request_delay)
    return details, calls, player_stat_fixtures, lineup_fixtures


def starter_ids(item: dict[str, Any], team_id: int) -> set[int]:
    result: set[int] = set()
    for lineup in item.get("lineups", []):
        if optional_int(lineup.get("team", {}).get("id")) != team_id:
            continue
        for entry in lineup.get("startXI", []):
            player_id = optional_int(entry.get("player", {}).get("id"))
            if player_id is not None:
                result.add(player_id)
    return result


def provider_observations(
    fixture: dict[str, Any],
    team_id: int,
    player_map: dict[int, str],
) -> dict[str, dict[str, Any]]:
    fixture_meta = fixture.get("fixture", {})
    fixture_date = str(fixture_meta.get("date", ""))[:10]
    side, opponent = team_and_opponent(fixture, team_id)
    starters = starter_ids(fixture, team_id)
    fixture_id = optional_int(fixture_meta.get("id"))
    league = fixture.get("league", {})
    output: dict[str, dict[str, Any]] = {}
    for team_block in fixture.get("players", []):
        if optional_int(team_block.get("team", {}).get("id")) != team_id:
            continue
        for entry in team_block.get("players", []):
            raw_player = entry.get("player", {})
            provider_id = optional_int(raw_player.get("id"))
            player_key = player_map.get(provider_id or -1)
            if not player_key:
                continue
            statistics = entry.get("statistics", [])
            stats = statistics[0] if statistics else {}
            games = stats.get("games", {}) if isinstance(stats, dict) else {}
            goals = stats.get("goals", {}) if isinstance(stats, dict) else {}
            minutes = optional_int(games.get("minutes")) or 0
            provider_started = games.get("substitute") is False
            started = provider_id in starters or provider_started
            appeared = minutes > 0 or started
            if not appeared:
                continue
            output[player_key] = {
                "event_key": f"api:{fixture_id}:{provider_id}",
                "fixture_id": fixture_id,
                "date": fixture_date,
                "opponent": opponent,
                "competition": str(league.get("name", "Club Friendly")),
                "home_away": side,
                "appeared": True,
                "started": started,
                "minutes": minutes,
                "position": str(games.get("position", "")).strip(),
                "goals": optional_int(goals.get("total")) or 0,
                "assists": optional_int(goals.get("assists")) or 0,
                "lineup_role": "unknown",
                "training_status": "unknown",
                "coach_signal": 50.0,
                "opponent_score": 50.0,
                "confidence": "medium",
                "claim": "API-Sports Testspieleinsatz",
                "source_provider": "api_sports",
                "source_url": (
                    "https://www.api-football.com/documentation"
                    f"?fixture={fixture_id}"
                ),
            }
    for provider_id in starters:
        player_key = player_map.get(provider_id)
        if not player_key or player_key in output:
            continue
        output[player_key] = {
            "event_key": f"api-lineup:{fixture_id}:{provider_id}",
            "fixture_id": fixture_id,
            "date": fixture_date,
            "opponent": opponent,
            "competition": str(league.get("name", "Club Friendly")),
            "home_away": side,
            "appeared": True,
            "started": True,
            "minutes": 0,
            "position": "",
            "goals": 0,
            "assists": 0,
            "lineup_role": "unknown",
            "training_status": "unknown",
            "coach_signal": 50.0,
            "opponent_score": 50.0,
            "confidence": "medium",
            "claim": "API-Sports Testspiel-Startaufstellung",
            "source_provider": "api_sports",
            "source_url": (
                "https://www.api-football.com/documentation"
                f"?fixture={fixture_id}"
            ),
        }
    return output


def manual_observation(player_id: str, item: dict[str, Any], index: int) -> dict[str, Any]:
    confidence = str(item.get("confidence", "high"))
    if confidence not in CONFIDENCE_WEIGHT:
        raise RuntimeError(
            f"invalid preseason confidence for {player_id}: {confidence}"
        )
    source_url = str(item.get("source_url", ""))
    if not source_url.startswith("https://"):
        raise RuntimeError(
            f"official preseason evidence needs HTTPS for {player_id}"
        )
    event_date = parse_date(item.get("date")).isoformat()
    raw_responsibilities = item.get("responsibilities", {})
    if not isinstance(raw_responsibilities, dict):
        raise RuntimeError(
            f"preseason responsibilities must be an object for {player_id}"
        )
    unknown_responsibilities = set(raw_responsibilities) - ROLE_RESPONSIBILITIES
    if unknown_responsibilities:
        raise RuntimeError(
            "unknown preseason responsibilities for "
            f"{player_id}: {sorted(unknown_responsibilities)}"
        )
    responsibilities = {}
    for responsibility, value in raw_responsibilities.items():
        level = str(value).strip().casefold()
        if level not in ROLE_LEVELS:
            raise RuntimeError(
                "invalid preseason responsibility level for "
                f"{player_id}: {responsibility}={value}"
            )
        responsibilities[responsibility] = level
    return {
        "event_key": str(
            item.get(
                "event_key",
                f"manual:{player_id}:{event_date}:{index}",
            )
        ),
        "fixture_id": optional_int(item.get("fixture_id")),
        "date": event_date,
        "opponent": str(item.get("opponent", "")).strip(),
        "competition": str(item.get("competition", "Testspiel")).strip(),
        "home_away": str(item.get("home_away", "unknown")),
        "appeared": bool(item.get("appeared", True)),
        "started": bool(item.get("started", False)),
        "minutes": max(0, optional_int(item.get("minutes")) or 0),
        "position": str(item.get("position", "")).strip(),
        "goals": max(0, optional_int(item.get("goals")) or 0),
        "assists": max(0, optional_int(item.get("assists")) or 0),
        "lineup_role": str(item.get("lineup_role", "unknown")),
        "training_status": str(item.get("training_status", "unknown")),
        "coach_signal": clamp(item.get("coach_signal"), 50),
        "opponent_score": clamp(item.get("opponent_score"), 50),
        "confidence": confidence,
        "claim": str(item.get("claim", "")).strip(),
        "responsibilities": responsibilities,
        "source_provider": str(item.get("source_provider", "official_club")),
        "source_url": source_url,
    }


def merge_observations(
    provider_items: list[dict[str, Any]],
    manual_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for item in provider_items:
        key = (str(item["date"]), normalized(item.get("opponent")))
        merged[key] = dict(item)
    for item in manual_items:
        key = (str(item["date"]), normalized(item.get("opponent")))
        previous = merged.get(key, {})
        merged[key] = {
            **previous,
            **item,
            "appeared": bool(item.get("appeared", previous.get("appeared", False))),
            "started": bool(item.get("started", previous.get("started", False))),
            "minutes": max(
                int(previous.get("minutes", 0)),
                int(item.get("minutes", 0)),
            ),
            "goals": max(
                int(previous.get("goals", 0)),
                int(item.get("goals", 0)),
            ),
            "assists": max(
                int(previous.get("assists", 0)),
                int(item.get("assists", 0)),
            ),
        }
    return sorted(
        merged.values(),
        key=lambda item: (item["date"], item["event_key"]),
    )


def event_decay(
    event_date: date,
    generated: date,
    *,
    decay_days: int,
) -> float:
    age_days = max(0, (generated - event_date).days)
    return 0.5 ** (age_days / max(1, decay_days))


def summarize(
    observations: list[dict[str, Any]],
    *,
    team_match_count: int,
    generated: datetime,
    season_start: date,
    decay_days: int,
    post_start_decay_days: int,
) -> dict[str, Any]:
    effective_factor = (
        max(
            0.0,
            1.0
            - max(0, (generated.date() - season_start).days)
            / post_start_decay_days,
        )
        if generated.date() >= season_start
        else 1.0
    )
    weighted: list[tuple[dict[str, Any], float]] = []
    for item in observations:
        weight = (
            event_decay(
                parse_date(item["date"]),
                generated.date(),
                decay_days=decay_days,
            )
            * CONFIDENCE_WEIGHT[str(item["confidence"])]
        )
        weighted.append((item, weight))
    opportunity_count = max(
        1,
        team_match_count,
        len({item["date"] for item in observations}),
    )
    appearance_weight = sum(
        weight for item, weight in weighted if item.get("appeared")
    )
    start_weight = sum(
        weight for item, weight in weighted if item.get("started")
    )
    minute_weight = sum(
        float(item.get("minutes", 0)) * weight for item, weight in weighted
    )
    total_weight = max(1.0, sum(weight for _, weight in weighted))
    appearance_rate = min(1.0, appearance_weight / opportunity_count)
    start_rate = min(1.0, start_weight / max(1.0, appearance_weight))
    minute_rate = min(1.0, minute_weight / (90.0 * opportunity_count))
    lineup_score = sum(
        LINEUP_ROLE.get(str(item.get("lineup_role")), 50.0) * weight
        for item, weight in weighted
    ) / total_weight
    training_score = sum(
        TRAINING_STATUS.get(str(item.get("training_status")), 50.0) * weight
        for item, weight in weighted
    ) / total_weight
    coach_score = sum(
        float(item.get("coach_signal", 50)) * weight
        for item, weight in weighted
    ) / total_weight
    opponent_score = sum(
        float(item.get("opponent_score", 50)) * weight
        for item, weight in weighted
    ) / total_weight
    contributions = sum(
        (int(item.get("goals", 0)) + int(item.get("assists", 0))) * weight
        for item, weight in weighted
    )
    availability_score = clamp(
        20
        + 60 * appearance_rate
        + 12 * minute_rate
        + 0.08 * training_score
    )
    role_score = clamp(
        18
        + 30 * start_rate
        + 22 * minute_rate
        + 0.18 * lineup_score
        + 0.12 * coach_score
    )
    performance_score = clamp(
        45 + min(32.0, 18.0 * contributions / max(0.75, appearance_weight))
    )
    signal_score = clamp(
        effective_factor
        * (
            0.40 * availability_score
            + 0.35 * role_score
            + 0.15 * performance_score
            + 0.10 * opponent_score
        )
        + (1.0 - effective_factor) * 50.0
    )
    official_source_count = len(
        {
            item["source_url"]
            for item in observations
            if item.get("source_provider") != "api_sports"
            and str(item.get("source_url", "")).startswith("https://")
        }
    )
    sample_size = sum(item.get("appeared", False) for item in observations)
    latest_observation = max(
        observations,
        key=lambda item: (str(item.get("date", "")), str(item.get("event_key", ""))),
        default={},
    )
    latest_training_status = str(
        latest_observation.get("training_status", "unknown")
    )
    if latest_training_status not in TRAINING_STATUS:
        latest_training_status = "unknown"
    confidence = (
        "high"
        if sample_size >= 3 and official_source_count >= 1
        else "medium"
        if sample_size >= 2 or official_source_count >= 1
        else "low"
    )
    classification = (
        "negative"
        if sample_size == 0
        and official_source_count >= 1
        and latest_training_status in {"partial", "absent"}
        else "insufficient"
        if sample_size == 0
        else "strong"
        if signal_score >= 72 and confidence in {"medium", "high"}
        else "positive"
        if signal_score >= 61
        else "negative"
        if signal_score < 42
        else "neutral"
    )
    return {
        "team_match_count": team_match_count,
        "appearances": sum(bool(item.get("appeared")) for item in observations),
        "starts": sum(bool(item.get("started")) for item in observations),
        "minutes": sum(int(item.get("minutes", 0)) for item in observations),
        "goals": sum(int(item.get("goals", 0)) for item in observations),
        "assists": sum(int(item.get("assists", 0)) for item in observations),
        "official_source_count": official_source_count,
        "availability_score": availability_score,
        "role_score": role_score,
        "performance_score": performance_score,
        "opponent_score": clamp(opponent_score),
        "training_score": clamp(training_score),
        "latest_training_status": latest_training_status,
        "latest_observation_date": str(latest_observation.get("date", "")),
        "signal_score": signal_score,
        "effective_factor": clamp(100.0 * effective_factor),
        "confidence": confidence,
        "classification": classification,
    }


def build_snapshot(
    news_payload: dict[str, Any],
    config: dict[str, Any],
    *,
    token: str,
    request_delay: float,
    ttl_hours: int,
    now: datetime | None = None,
    provider_enabled: bool = True,
) -> dict[str, Any]:
    generated = (now or utc_now()).astimezone(timezone.utc).replace(
        microsecond=0
    )
    if str(config.get("competition")) != str(news_payload["competition"]):
        raise RuntimeError("preseason and news competition do not match")
    if str(config.get("season")) != str(news_payload["season"]):
        raise RuntimeError("preseason and news season do not match")
    window_start = parse_date(config["window"]["from"])
    configured_end = parse_date(config["window"]["to"])
    window_end = min(configured_end, generated.date())
    season_start = parse_date(config["window"]["season_start"])
    decay_days = int(config["window"].get("decay_days", 28))
    post_start_decay_days = int(
        config["window"].get("post_start_decay_days", 35)
    )
    provider_season = optional_int(
        config.get("api_sports", {}).get("season")
    ) or optional_int(str(config["season"]).split("/", 1)[0])
    if provider_season is None:
        raise RuntimeError("preseason API-Sports season is required")
    patterns = [
        str(value)
        for value in config.get(
            "included_competition_patterns",
            ["friendly", "friendlies"],
        )
    ]
    if not patterns or any(not normalized(value) for value in patterns):
        raise RuntimeError(
            "preseason competition patterns must be non-empty"
        )
    provider_to_news_id: dict[int, str] = {}
    team_ids: set[int] = set()
    for news_id, player in news_payload["players"].items():
        mapping = player.get("mapping", {})
        if mapping.get("confidence") != "verified":
            continue
        provider_id = optional_int(mapping.get("api_sports_player_id"))
        team_id = optional_int(mapping.get("api_sports_team_id"))
        if provider_id is not None:
            provider_to_news_id[provider_id] = str(news_id)
        if team_id is not None:
            team_ids.add(team_id)
    headers = {"x-apisports-key": token}
    if window_end < window_start or not provider_enabled:
        fixtures, team_fixtures, fixture_calls = {}, {}, 0
    else:
        fixtures, team_fixtures, fixture_calls = fetch_fixtures(
            team_ids,
            provider_season=provider_season,
            window_start=window_start,
            window_end=window_end,
            patterns=patterns,
            headers=headers,
            request_delay=request_delay,
        )
    details, detail_calls, player_stat_fixtures, lineup_fixtures = (
        fetch_fixture_details(
        fixtures,
        headers=headers,
        request_delay=request_delay,
        )
    )
    manual_config = config.get("players", {})
    manual_record_count = sum(
        len(item.get("events", []))
        for item in manual_config.values()
        if isinstance(item, dict)
    )
    if (
        len(fixtures) >= 5
        and player_stat_fixtures == 0
        and lineup_fixtures == 0
        and manual_record_count == 0
    ):
        raise RuntimeError(
            "API-Sports returned preseason fixtures but neither player "
            "statistics nor lineups, and no official evidence is configured"
        )
    by_player: dict[str, list[dict[str, Any]]] = defaultdict(list)
    team_match_count_by_player: dict[str, int] = {}
    for team_id, fixture_ids in team_fixtures.items():
        team_player_keys = {
            news_id
            for provider_id, news_id in provider_to_news_id.items()
            if optional_int(
                news_payload["players"][news_id]
                .get("mapping", {})
                .get("api_sports_team_id")
            )
            == team_id
        }
        for player_key in team_player_keys:
            team_match_count_by_player[player_key] = len(fixture_ids)
        for fixture_id in fixture_ids:
            item = details.get(fixture_id, fixtures[fixture_id])
            observations = provider_observations(
                item,
                team_id,
                provider_to_news_id,
            )
            for player_key, observation in observations.items():
                by_player[player_key].append(observation)
    all_player_keys = set(by_player) | {
        str(player_id) for player_id in manual_config
    }
    players: dict[str, Any] = {}
    for player_key in sorted(all_player_keys):
        manual_entry = manual_config.get(player_key, {})
        manual_items = [
            manual_observation(player_key, item, index)
            for index, item in enumerate(manual_entry.get("events", []))
            if isinstance(item, dict)
        ]
        observations = merge_observations(
            by_player.get(player_key, []),
            manual_items,
        )
        if not observations:
            continue
        news_player = news_payload["players"].get(player_key, {})
        team_match_count = max(
            int(team_match_count_by_player.get(player_key, 0)),
            int(manual_entry.get("team_match_count", 0)),
            len({item["date"] for item in observations}),
        )
        players[player_key] = {
            "name": str(
                manual_entry.get("name")
                or news_player.get("name")
                or player_key
            ),
            "club": str(
                manual_entry.get("club")
                or news_player.get("club")
                or ""
            ),
            "mapping_confidence": str(
                news_player.get("mapping", {}).get(
                    "confidence",
                    manual_entry.get("mapping_confidence", "medium"),
                )
            ),
            "observations": observations,
            "summary": summarize(
                observations,
                team_match_count=team_match_count,
                generated=generated,
                season_start=season_start,
                decay_days=decay_days,
                post_start_decay_days=post_start_decay_days,
            ),
        }
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": isoformat(generated),
        "expires_at": isoformat(generated + timedelta(hours=ttl_hours)),
        "competition": str(config["competition"]),
        "season": str(config["season"]),
        "window": {
            "from": window_start.isoformat(),
            "to": configured_end.isoformat(),
            "season_start": season_start.isoformat(),
            "decay_days": decay_days,
            "post_start_decay_days": post_start_decay_days,
        },
        "providers": {
            "api_sports": {
                "status": (
                    "rate_limited_official_evidence_only"
                    if not provider_enabled
                    else "ok"
                    if player_stat_fixtures > 0
                    else "lineup_only"
                    if lineup_fixtures > 0
                    else "degraded_official_evidence_only"
                ),
                "requests": fixture_calls + detail_calls,
                "fixtures": len(fixtures),
                "player_stat_fixtures": player_stat_fixtures,
                "lineup_fixtures": lineup_fixtures,
                "player_observations": sum(len(items) for items in by_player.values()),
            },
            "official_evidence": {
                "status": "configured",
                "players": len(manual_config),
                "records": sum(
                    len(item.get("events", []))
                    for item in manual_config.values()
                    if isinstance(item, dict)
                ),
            },
        },
        "players": players,
    }
    payload["content_sha256"] = canonical_sha256(payload)
    return validate_snapshot(payload, now=generated)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--news", required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous")
    parser.add_argument("--request-delay", type=float, default=0.15)
    parser.add_argument("--ttl-hours", type=int, default=18)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    token = os.environ.get("API_SPORTS_KEY", "").strip()
    if not token:
        print("API_SPORTS_KEY is required", file=sys.stderr)
        return 2
    config = json.loads(args.mapping.read_text(encoding="utf-8"))
    news_payload = load_news_snapshot(args.news)
    try:
        payload = build_snapshot(
            news_payload,
            config,
            token=token,
            request_delay=args.request_delay,
            ttl_hours=args.ttl_hours,
        )
    except RuntimeError as error:
        if not args.previous or not is_api_sports_daily_limit(error):
            raise
        manual_records = sum(
            len(item.get("events", []))
            for item in config.get("players", {}).values()
            if isinstance(item, dict)
        )
        if manual_records:
            payload = build_snapshot(
                news_payload,
                config,
                token=token,
                request_delay=args.request_delay,
                ttl_hours=args.ttl_hours,
                provider_enabled=False,
            )
            print(
                "API-Sports daily limit reached; publishing fresh official "
                "evidence with an explicit provider-degraded status.",
                file=sys.stderr,
            )
        else:
            payload = load_preseason_snapshot(args.previous)
            if (
                payload["competition"] != config["competition"]
                or payload["season"] != config["season"]
            ):
                raise RuntimeError(
                    "previous preseason snapshot belongs to another competition"
                ) from error
            print(
                "API-Sports daily limit reached; reusing the previous fresh "
                "preseason snapshot without extending its expiry.",
                file=sys.stderr,
            )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(f"{args.output.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(args.output)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "players": len(payload["players"]),
                "fixtures": payload["providers"]["api_sports"]["fixtures"],
                "content_sha256": payload["content_sha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
