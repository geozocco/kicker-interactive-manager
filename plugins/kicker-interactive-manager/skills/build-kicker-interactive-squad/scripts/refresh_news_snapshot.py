#!/usr/bin/env python3
"""Build a normalized Kicker news snapshot from API-Sports and SportsMonks."""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from news_snapshot import (
    SCHEMA_VERSION,
    canonical_sha256,
    load_snapshot as load_news_snapshot,
    validate_snapshot,
)
from market_snapshot import load_snapshot as load_market_snapshot
from openai_role_research import (
    DEFAULT_MODEL as DEFAULT_OPENAI_ROLE_MODEL,
    research_role_profiles,
    select_role_targets,
)
from openai_team_research import research_team_profiles
from openai_transfer_research import (
    normalize_report,
    parse_bundesliga_transfer_centre,
    research_transfer_reports,
    select_transfer_targets,
)
from openai_usage import empty_usage, merge_usage
from quality_snapshot import load_snapshot as load_quality_snapshot


USER_AGENT = "kicker-interactive-manager-news-refresh/1"
ROLE_CACHE_MODEL_VERSION = "news-role-cache-v1"
ROLE_CACHE_TTL_DAYS = 45
ROLE_RESPONSIBILITIES = {
    "penalties",
    "direct_free_kicks",
    "corners",
    "playmaker",
    "offensive_focal_point",
    "aerial_set_piece_target",
    "captain",
}


def load_editorial_transfer_evidence(
    path: Path,
    *,
    market: dict[str, Any],
    competition: str,
    season: str,
    now: datetime,
    model: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Normalize centrally curated reports independently of web interpretation."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise RuntimeError("editorial transfer evidence schema_version must be 1")
    entries = payload.get("entries", [])
    if not isinstance(entries, list):
        raise RuntimeError("editorial transfer evidence entries must be a list")
    market_players = {
        str(player.get("id", "")): player
        for player in market.get("players", [])
        if isinstance(player, dict) and str(player.get("id", "")).strip()
    }
    competition_clubs = {
        str(player.get("club", "")).strip()
        for player in market_players.values()
        if str(player.get("club", "")).strip()
    }
    reports: dict[str, dict[str, Any]] = {}
    ignored = 0
    stale_market_player_ids: list[str] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise RuntimeError(f"editorial transfer evidence entry {index} is invalid")
        if (
            str(entry.get("competition", "")) != competition
            or str(entry.get("season", "")) != season
        ):
            ignored += 1
            continue
        player_id = str(entry.get("player_id", "")).strip()
        target_player = market_players.get(player_id)
        if target_player is None:
            # A completed outbound move removes the player from the next
            # Kicker market refresh before the curated warning is cleaned up.
            # That row is no longer selectable and therefore safely stale;
            # preserve it in the audit instead of blocking every league feed.
            stale_market_player_ids.append(player_id)
            continue
        if (
            str(entry.get("name", "")).strip() != str(target_player.get("name", "")).strip()
            or str(entry.get("club", "")).strip() != str(target_player.get("club", "")).strip()
        ):
            raise RuntimeError(
                f"editorial transfer evidence identity mismatch for {player_id!r}"
            )
        evidence = entry.get("evidence", [])
        if not isinstance(evidence, list) or not evidence:
            raise RuntimeError(
                f"editorial transfer evidence is missing for {player_id!r}"
            )
        grounded_urls = {
            str(item.get("source_url", "")).strip()
            for item in evidence
            if isinstance(item, dict)
            and str(item.get("source_url", "")).startswith("https://")
        }
        normalized = normalize_report(
            {
                **entry,
                "has_transfer_signal": True,
                "evidence": evidence,
            },
            target={
                "player_id": player_id,
                "name": str(target_player.get("name", "")),
                "club": str(target_player.get("club", "")),
                "position": str(target_player.get("position", "")),
                "market_value": int(float(target_player.get("market_value", 0))),
            },
            competition_clubs=competition_clubs,
            grounded_urls=grounded_urls,
            now=now,
            model=model,
        )
        if normalized is None:
            raise RuntimeError(
                f"editorial transfer evidence could not be normalized for {player_id!r}"
            )
        normalized["source_channel"] = "central_editorial_transfer_evidence"
        previous = reports.get(player_id)
        ranking = {"rumour": 1, "advanced": 2, "confirmed": 3}
        if previous is None or (
            ranking.get(str(normalized.get("status", "")), 0),
            float(normalized.get("probability", 0) or 0),
        ) > (
            ranking.get(str(previous.get("status", "")), 0),
            float(previous.get("probability", 0) or 0),
        ):
            reports[player_id] = normalized
    return reports, {
        "status": "ok",
        "source": str(path),
        "records": len(reports),
        "ignored_other_competitions": ignored,
        "ignored_stale_market_players": len(stale_market_player_ids),
        "stale_market_player_ids": sorted(stale_market_player_ids),
    }


def combined_openai_usage(*audits: dict[str, Any] | None) -> dict[str, Any]:
    model = next(
        (
            str(audit.get("model", ""))
            for audit in audits
            if isinstance(audit, dict) and str(audit.get("model", ""))
        ),
        DEFAULT_OPENAI_ROLE_MODEL,
    )
    total = empty_usage(model)
    stages: dict[str, Any] = {}
    for name, audit in zip(("role", "team", "transfer"), audits):
        usage = audit.get("usage", {}) if isinstance(audit, dict) else {}
        if isinstance(usage, dict):
            merge_usage(total, usage)
            stages[name] = copy.deepcopy(usage)
    total["stages"] = stages
    return total


def build_evidence_cache(
    role_profiles: dict[str, dict[str, Any]],
    team_profiles: dict[str, dict[str, Any]],
    transfer_profiles: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Deduplicate grounded sources for reuse across research stages."""

    sources: dict[str, dict[str, Any]] = {}

    def add(
        context: str,
        entity_id: str,
        evidence_items: Any,
    ) -> None:
        if not isinstance(evidence_items, list):
            return
        for item in evidence_items:
            if not isinstance(item, dict):
                continue
            url = str(item.get("source_url", "")).strip()
            if not url.startswith("https://"):
                continue
            record = sources.setdefault(
                url,
                {
                    "observed_at": str(item.get("observed_at", "")),
                    "contexts": [],
                    "entities": [],
                    "claims": [],
                },
            )
            observed_at = str(item.get("observed_at", ""))
            if observed_at > str(record.get("observed_at", "")):
                record["observed_at"] = observed_at
            if context not in record["contexts"]:
                record["contexts"].append(context)
            if entity_id not in record["entities"]:
                record["entities"].append(entity_id)
            claim = str(item.get("claim", "")).strip()[:360]
            if claim and claim not in record["claims"]:
                record["claims"].append(claim)
                record["claims"] = record["claims"][:4]

    for player_id, profile in role_profiles.items():
        add("role", str(player_id), profile.get("evidence", []))
    for club, profile in team_profiles.items():
        add("team", str(club), profile.get("evidence", []))
    for player_id, profile in transfer_profiles.items():
        add("transfer", str(player_id), profile.get("evidence", []))
    for record in sources.values():
        record["contexts"].sort()
        record["entities"].sort()
    return {
        "schema_version": 1,
        "source_count": len(sources),
        "sources": sources,
    }


def is_api_sports_rate_limit(value: Any) -> bool:
    details = str(value).casefold()
    return (
        "ratelimit" in details
        or "rate limit" in details
        or "too many requests" in details
        or "http error 429" in details
        or "request limit for the day" in details
        or "daily request limit" in details
    )


def is_api_sports_daily_limit(value: Any) -> bool:
    details = str(value).casefold()
    return (
        "request limit for the day" in details
        or "daily request limit" in details
    )


def merge_role_research_into_previous_snapshot(
    previous: dict[str, Any],
    *,
    role_profiles: dict[str, dict[str, Any]],
    role_research_abstentions: dict[str, dict[str, Any]],
    role_research_audit: dict[str, Any],
    team_profiles: dict[str, dict[str, Any]] | None = None,
    team_research_audit: dict[str, Any] | None = None,
    transfer_reports: dict[str, dict[str, Any]] | None = None,
    transfer_research_abstentions: dict[str, dict[str, Any]] | None = None,
    transfer_research_audit: dict[str, Any] | None = None,
    market_players: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Refresh grounded roles without extending stale provider timestamps."""

    merged = copy.deepcopy(previous)
    merged["role_profiles"] = copy.deepcopy(role_profiles)
    merged["role_research_abstentions"] = copy.deepcopy(
        role_research_abstentions
    )
    merged["role_research"] = copy.deepcopy(role_research_audit)
    merged["team_profiles"] = copy.deepcopy(team_profiles or {})
    merged["team_research"] = copy.deepcopy(
        team_research_audit
        or {
            "status": "not_configured",
            "targets": 0,
            "cache_hits": 0,
            "researched_profiles": 0,
            "inconclusive": 0,
            "requests": 0,
            "failures": [],
        }
    )
    merged["transfer_profiles"] = copy.deepcopy(transfer_reports or {})
    merged["transfer_research_abstentions"] = copy.deepcopy(
        transfer_research_abstentions or {}
    )
    merged["transfer_research"] = copy.deepcopy(
        transfer_research_audit
        or {
            "status": "not_configured",
            "targets": 0,
            "cache_hits": 0,
            "researched_reports": 0,
            "researched_abstentions": 0,
            "researched_inconclusive": 0,
            "requests": 0,
            "failures": [],
        }
    )
    editorial_report_count = sum(
        isinstance(report, dict)
        and report.get("source_channel")
        == "central_editorial_transfer_evidence"
        for report in (transfer_reports or {}).values()
    )
    if editorial_report_count:
        merged.setdefault("providers", {})[
            "central_editorial_transfer_evidence"
        ] = {
            "status": "ok",
            "fetched_at": iso_now(),
            "records": editorial_report_count,
            "requests": 0,
        }
    merged["openai_usage"] = combined_openai_usage(
        role_research_audit,
        team_research_audit,
        transfer_research_audit,
    )
    merged["evidence_cache"] = build_evidence_cache(
        merged["role_profiles"],
        merged["team_profiles"],
        merged["transfer_profiles"],
    )
    merged_players = merged.setdefault("players", {})
    market_by_id = {
        str(player.get("id", "")): player
        for player in market_players or []
        if isinstance(player, dict) and str(player.get("id", "")).strip()
    }
    for player_id, report in (transfer_reports or {}).items():
        if not isinstance(report, dict) or not report.get("fresh", False):
            continue
        market_player = market_by_id.get(str(player_id), {})
        player = merged_players.setdefault(
            str(player_id),
            {
                "name": str(market_player.get("name", "")),
                "club": str(market_player.get("club", "")),
                "mapping": {
                    "api_sports_player_id": None,
                    "api_sports_team_id": None,
                    "sportsmonks_player_id": None,
                    "sportsmonks_team_id": None,
                    "age": None,
                    "position": str(market_player.get("position", "")),
                    "confidence": "unverified",
                },
                "signals": [],
                "consensus": consensus_for([]),
            },
        )
        editorial_signal = transfer_report_signal(
            str(player_id),
            report,
            observed_at=str(
                report.get("observed_at", merged.get("generated_at", ""))
            ),
        )
        if editorial_signal is None:
            continue
        source_provider = str(editorial_signal.get("source_provider", ""))
        retained = [
            item
            for item in player.get("signals", [])
            if not (
                isinstance(item, dict)
                and item.get("source_provider") == source_provider
            )
        ]
        player["signals"] = [*retained, editorial_signal]
        player["consensus"] = consensus_for(player["signals"])
    for player_id, player in merged_players.items():
        if not isinstance(player, dict):
            continue
        abstention = (transfer_research_abstentions or {}).get(str(player_id))
        if not isinstance(abstention, dict):
            continue
        player["consensus"] = apply_transfer_research_caution(
            dict(player.get("consensus", {})),
            abstention,
        )
    merged.pop("content_sha256", None)
    merged["content_sha256"] = canonical_sha256(merged)
    return merged


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def parsed_role_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) == 10:
        text = f"{text}T12:00:00+00:00"
    elif text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def inferred_role_designation(profile: dict[str, Any]) -> str:
    explicit = str(profile.get("designation", "")).strip().casefold()
    allowed = {
        "confirmed_starter",
        "key_starter",
        "expected_starter",
        "immediate_help",
        "open_competition",
        "rotation",
        "perspective",
    }
    if explicit in allowed:
        return explicit
    continuity = str(profile.get("continuity", "unknown")).casefold()
    probability = float(profile.get("expected_start_probability", 0) or 0)
    responsibilities = profile.get("responsibilities", {})
    focal = (
        isinstance(responsibilities, dict)
        and responsibilities.get("offensive_focal_point") == "primary"
    )
    if continuity == "reduced" or probability < 40:
        return "perspective"
    if probability >= 90 and focal:
        return "key_starter"
    if probability >= 78:
        return "expected_starter"
    if probability >= 55:
        return "rotation"
    return "open_competition"


def cached_role_profiles(
    role_config: dict[str, Any] | None,
    *,
    generated_at: str,
) -> dict[str, dict[str, Any]]:
    """Normalize sourced role claims into a dated central cache.

    The source observation date, not the refresh time, controls freshness so
    repeatedly publishing an old quote cannot make it current again.
    """

    config = role_config if isinstance(role_config, dict) else {}
    generated = parsed_role_timestamp(generated_at)
    if generated is None:
        raise RuntimeError("generated_at is invalid for role cache")
    raw_profiles: dict[str, dict[str, Any]] = {}
    for player_id, value in config.get("role_evidence", {}).items():
        if isinstance(value, dict):
            raw_profiles[str(player_id)] = dict(value)
    goalkeeper_players = (
        config.get("goalkeeper_evidence", {}).get("players", {})
        if isinstance(config.get("goalkeeper_evidence"), dict)
        else {}
    )
    for player_id, value in goalkeeper_players.items():
        if not isinstance(value, dict):
            continue
        profile = dict(value)
        status = str(profile.get("status", "")).strip().casefold()
        profile.setdefault(
            "designation",
            {
                "confirmed_starter": "confirmed_starter",
                "clear_favourite": "expected_starter",
                "likely_starter": "expected_starter",
                "open_competition": "open_competition",
                "challenger": "rotation",
                "backup": "perspective",
                "external_signing_risk": "open_competition",
            }.get(status, ""),
        )
        profile.setdefault(
            "expected_start_probability",
            profile.get("starter_probability", 0),
        )
        raw_profiles[str(player_id)] = {
            **raw_profiles.get(str(player_id), {}),
            **profile,
        }

    output: dict[str, dict[str, Any]] = {}
    for player_id, profile in raw_profiles.items():
        evidence = []
        observed_values: list[datetime] = []
        for item in profile.get("evidence", []):
            if not isinstance(item, dict):
                continue
            claim = str(item.get("claim", "")).strip()
            source_url = str(item.get("source_url", "")).strip()
            observed = parsed_role_timestamp(
                item.get("observed_at", item.get("checked_at"))
            )
            if not claim or not source_url.startswith("https://") or observed is None:
                continue
            observed_values.append(observed)
            evidence.append(
                {
                    "claim": claim,
                    "source_url": source_url,
                    "observed_at": observed.isoformat().replace("+00:00", "Z"),
                    "source_authority": str(
                        item.get(
                            "source_authority",
                            profile.get("source_authority", "editorial_or_club"),
                        )
                    ).strip(),
                }
            )
        if not evidence:
            continue
        observed_at = max(observed_values)
        expires_at = observed_at + timedelta(days=ROLE_CACHE_TTL_DAYS)
        responsibilities = {
            key: str(value).strip().casefold()
            for key, value in (
                profile.get("responsibilities", {}) or {}
            ).items()
            if key in ROLE_RESPONSIBILITIES
            and str(value).strip().casefold() in {"none", "shared", "primary"}
        }
        normalized = {
            "model_version": ROLE_CACHE_MODEL_VERSION,
            "designation": inferred_role_designation(profile),
            "continuity": str(
                profile.get("continuity", "unknown")
            ).strip().casefold(),
            "expected_start_probability": max(
                0.0,
                min(
                    100.0,
                    float(profile.get("expected_start_probability", 0) or 0),
                ),
            ),
            "team_quality_delta": max(
                -30.0,
                min(30.0, float(profile.get("team_quality_delta", 0) or 0)),
            ),
            "responsibilities": responsibilities,
            "confidence": str(
                profile.get("confidence", "medium")
            ).strip().casefold(),
            "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
            "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
            "fresh": observed_at <= generated < expires_at,
            "evidence": evidence,
            "note": str(profile.get("note", "")).strip(),
        }
        output[player_id] = normalized
    return output


def request_json(
    base_url: str,
    *,
    query: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
    attempts: int = 4,
) -> dict[str, Any]:
    url = base_url
    if query:
        url = f"{base_url}?{urllib.parse.urlencode(query, doseq=True)}"
    request_headers = {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
        **(headers or {}),
    }
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, headers=request_headers),
                timeout=timeout,
            ) as response:
                result = json.loads(response.read().decode("utf-8"))
                if not isinstance(result, dict):
                    raise ValueError("provider response is not a JSON object")
                return result
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
            ValueError,
        ) as error:
            last_error = error
            if isinstance(error, urllib.error.HTTPError) and error.code not in {
                429,
                500,
                502,
                503,
                504,
            }:
                break
            if attempt + 1 < attempts:
                time.sleep(1.0 * (2**attempt))
    raise RuntimeError(f"provider request failed for {base_url}: {last_error}")


def request_text(
    url: str,
    *,
    timeout: float = 20.0,
    attempts: int = 3,
) -> str:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "Accept": "text/html,application/xhtml+xml",
                    "User-Agent": USER_AGENT,
                },
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", "replace")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(1.0 * (2**attempt))
    raise RuntimeError(
        f"editorial register request failed for {url}: {last_error}"
    )


def api_sports_pages(
    base_url: str,
    *,
    query: dict[str, Any],
    headers: dict[str, str],
    paginate: bool = True,
    rate_limit_attempts: int = 3,
    rate_limit_delay: float = 65.0,
) -> Iterable[dict[str, Any]]:
    page = 1
    while True:
        request_query = (
            {**query, "page": page}
            if paginate
            else dict(query)
        )
        payload: dict[str, Any] | None = None
        for attempt in range(rate_limit_attempts):
            payload = request_json(
                base_url,
                query=request_query,
                headers=headers,
            )
            errors = payload.get("errors")
            if not errors:
                break
            if isinstance(errors, dict):
                details = "; ".join(
                    f"{key}: {value}"
                    for key, value in sorted(errors.items())
                )
            elif isinstance(errors, list):
                details = "; ".join(str(value) for value in errors)
            else:
                details = str(errors)
            if (
                is_api_sports_rate_limit(details)
                and attempt + 1 < rate_limit_attempts
            ):
                time.sleep(rate_limit_delay * (attempt + 1))
                continue
            raise RuntimeError(
                f"API-Sports rejected the request: {details}"
            )
        if payload is None:
            raise RuntimeError("API-Sports returned no payload")
        yield payload
        if not paginate:
            return
        paging = payload.get("paging", {})
        total = optional_int(paging.get("total")) if isinstance(paging, dict) else None
        current = (
            optional_int(paging.get("current"))
            if isinstance(paging, dict)
            else None
        )
        if total is None or current is None or current >= total:
            return
        page = current + 1


def sportsmonks_pages(
    base_url: str,
    *,
    query: dict[str, Any],
    headers: dict[str, str],
) -> Iterable[dict[str, Any]]:
    page = 1
    while True:
        payload = request_json(
            base_url,
            query={**query, "page": page, "per_page": 50},
            headers=headers,
        )
        yield payload
        pagination = payload.get("pagination", {})
        if not isinstance(pagination, dict):
            pagination = payload.get("meta", {}).get("pagination", {})
        has_more = (
            pagination.get("has_more", pagination.get("has_more_data", False))
            if isinstance(pagination, dict)
            else False
        )
        if not has_more:
            return
        page += 1


def chunks(values: list[int], size: int) -> Iterable[list[int]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


def optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def provider_id_map(
    config: dict[str, Any],
    provider_key: str,
) -> dict[int, str]:
    result: dict[int, str] = {}
    for kicker_id, player in config.get("players", {}).items():
        if not isinstance(player, dict):
            continue
        raw_id = player.get(f"{provider_key}_player_id")
        if raw_id is None:
            continue
        normalized = optional_int(raw_id)
        if normalized is not None:
            existing = result.get(normalized)
            if existing is not None and existing != str(kicker_id):
                raise RuntimeError(
                    f"provider player id {normalized} maps to both "
                    f"{existing!r} and {str(kicker_id)!r}"
                )
            result[normalized] = str(kicker_id)
    return result


def competition_team_ids(
    config: dict[str, Any],
    provider_key: str,
) -> tuple[set[int], bool]:
    section = config.get(provider_key, {})
    raw_ids: list[Any] = []
    configured = section.get("competition_team_ids", [])
    if isinstance(configured, list):
        raw_ids.extend(configured)
    team_ids = section.get("team_ids", {})
    if isinstance(team_ids, dict):
        raw_ids.extend(team_ids.values())
    for player in config.get("players", {}).values():
        if isinstance(player, dict):
            raw_ids.append(player.get(f"{provider_key}_team_id"))
    normalized = {
        team_id
        for raw_id in raw_ids
        if (team_id := optional_int(raw_id)) is not None
    }
    return normalized, bool(section.get("competition_team_ids_complete", False))


def discover_api_sports_roster(
    config: dict[str, Any],
    token: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Discover the current league roster without storing provider secrets."""

    section = config.get("api_sports", {})
    if not section.get("auto_discover_players", False):
        return copy.deepcopy(config), {
            "status": "configured",
            "players": len(config.get("players", {})),
            "teams": len(section.get("team_ids", {})),
            "requests": 0,
        }

    league_id = optional_int(section.get("league_id"))
    season = optional_int(section.get("season"))
    if league_id is None or season is None:
        raise RuntimeError(
            "API-Sports roster discovery requires league_id and season"
        )

    headers = {"x-apisports-key": token}
    requests = 0
    teams: dict[int, str] = {}
    for response in api_sports_pages(
        "https://v3.football.api-sports.io/teams",
        query={"league": league_id, "season": season},
        headers=headers,
        paginate=False,
    ):
        requests += 1
        for item in response.get("response", []):
            if not isinstance(item, dict):
                continue
            team = item.get("team", {})
            if not isinstance(team, dict):
                continue
            team_id = optional_int(team.get("id"))
            if team_id is not None:
                teams[team_id] = str(team.get("name", "")).strip()

    expected_team_count = optional_int(section.get("expected_team_count"))
    if not teams:
        raise RuntimeError(
            f"API-Sports returned no teams for league {league_id}, season {season}"
        )
    if expected_team_count is not None and len(teams) != expected_team_count:
        raise RuntimeError(
            "API-Sports roster discovery returned "
            f"{len(teams)} teams, expected {expected_team_count}"
        )

    players: dict[str, dict[str, Any]] = {}
    for requested_team_id, requested_team_name in sorted(teams.items()):
        for response in api_sports_pages(
            "https://v3.football.api-sports.io/players/squads",
            query={"team": requested_team_id},
            headers=headers,
            paginate=False,
        ):
            requests += 1
            for squad in response.get("response", []):
                if not isinstance(squad, dict):
                    continue
                team = squad.get("team", {})
                if not isinstance(team, dict):
                    continue
                team_id = optional_int(team.get("id"))
                if team_id != requested_team_id:
                    continue
                team_name = (
                    str(team.get("name", "")).strip()
                    or requested_team_name
                )
                for player in squad.get("players", []):
                    if not isinstance(player, dict):
                        continue
                    player_id = optional_int(player.get("id"))
                    if player_id is None:
                        continue
                    players[f"api_sports:{player_id}"] = {
                        "name": str(player.get("name", "")).strip(),
                        "club": team_name,
                        "age": optional_int(player.get("age")),
                        "position": str(player.get("position", "")).strip(),
                        "api_sports_player_id": player_id,
                        "api_sports_team_id": team_id,
                        "mapping_confidence": "verified",
                    }

    if not players:
        raise RuntimeError(
            f"API-Sports returned no players for league {league_id}, season {season}"
        )

    discovered = copy.deepcopy(config)
    discovered_section = discovered.setdefault("api_sports", {})
    discovered_section["competition_team_ids"] = sorted(teams)
    discovered_section["competition_team_ids_complete"] = True
    discovered_section["team_ids"] = {
        name: team_id for team_id, name in sorted(teams.items())
    }
    configured_players = discovered.get("players", {})
    if not isinstance(configured_players, dict):
        configured_players = {}
    discovered["players"] = {
        player_id: {
            **players.get(player_id, {}),
            **(
                configured_players.get(player_id, {})
                if isinstance(configured_players.get(player_id, {}), dict)
                else {}
            ),
        }
        for player_id in sorted(players.keys() | configured_players.keys())
    }
    return discovered, {
        "status": "discovered",
        "players": len(players),
        "teams": len(teams),
        "requests": requests,
    }


def classify_transfer_impact(
    *,
    current_team_id: int | None,
    from_team_id: int | None,
    to_team_id: int | None,
    league_team_ids: set[int],
    league_team_ids_complete: bool,
) -> tuple[str, int]:
    if current_team_id is not None and to_team_id == current_team_id:
        return "in", 10
    if current_team_id is None or from_team_id != current_team_id:
        return "unknown", 30
    if to_team_id in league_team_ids:
        return "within_competition", 55
    if league_team_ids_complete:
        return "out", 95
    return "unknown_destination", 70


def signal(
    *,
    kind: str,
    status: str,
    severity: float,
    provider: str,
    observed_at: str,
    record_id: Any = "",
    detail: str = "",
    source_url: str = "",
    effective_from: Any = "",
    effective_until: Any = "",
    availability_impact: str = "unknown",
) -> dict[str, Any]:
    return {
        "kind": kind,
        "status": status,
        "severity": max(0.0, min(100.0, float(severity))),
        "effective_from": str(effective_from or ""),
        "effective_until": str(effective_until or ""),
        "source_provider": provider,
        "source_url": str(source_url or ""),
        "observed_at": observed_at,
        "provider_record_id": str(record_id or ""),
        "detail": str(detail or "").strip(),
        "availability_impact": availability_impact,
    }


def recent_enough(value: Any, lookback_days: int) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed >= datetime.now(timezone.utc) - timedelta(days=lookback_days)


def api_sports_signals(
    config: dict[str, Any],
    token: str,
    observed_at: str,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    section = config.get("api_sports", {})
    player_map = provider_id_map(config, "api_sports")
    output: dict[str, list[dict[str, Any]]] = defaultdict(list)
    headers = {"x-apisports-key": token}
    calls = 0
    lookback_days = int(section.get("transfer_lookback_days", 120))
    league_team_ids, league_team_ids_complete = competition_team_ids(
        config,
        "api_sports",
    )

    league_id = section.get("league_id")
    season = section.get("season")
    if league_id is not None and season is not None:
        for response in api_sports_pages(
            "https://v3.football.api-sports.io/injuries",
            query={"league": league_id, "season": season},
            headers=headers,
            paginate=False,
        ):
            calls += 1
            for item in response.get("response", []):
                if not isinstance(item, dict):
                    continue
                player = item.get("player", {})
                kicker_id = player_map.get(optional_int(player.get("id")) or -1)
                if not kicker_id:
                    continue
                reason = player.get("reason") or player.get("type") or "current injury"
                output[kicker_id].append(
                    signal(
                        kind="injury",
                        status="confirmed",
                        severity=85,
                        provider="api_sports",
                        observed_at=observed_at,
                        record_id=player.get("id"),
                        detail=str(reason),
                        source_url="https://api-sports.io/documentation/football/v3",
                        effective_from=item.get("fixture", {}).get("date", ""),
                    )
                )

    player_ids = sorted(player_map)
    for batch in chunks(player_ids, 20):
        for response in api_sports_pages(
            "https://v3.football.api-sports.io/sidelined",
            query={"players": "-".join(str(item) for item in batch)},
            headers=headers,
            paginate=False,
        ):
            calls += 1
            for item in response.get("response", []):
                if not isinstance(item, dict):
                    continue
                raw_player = item.get("player", {})
                provider_player_id = (
                    raw_player.get("id") if isinstance(raw_player, dict) else None
                )
                if provider_player_id is None:
                    provider_player_id = item.get("player_id")
                if provider_player_id is None and len(batch) == 1:
                    provider_player_id = batch[0]
                kicker_id = player_map.get(optional_int(provider_player_id) or -1)
                if not kicker_id:
                    continue
                detail = item.get("type") or item.get("reason") or "sidelined"
                output[kicker_id].append(
                    signal(
                        kind="injury",
                        status="confirmed",
                        severity=75,
                        provider="api_sports",
                        observed_at=observed_at,
                        record_id=item.get("id"),
                        detail=str(detail),
                        source_url="https://api-sports.io/documentation/football/v3",
                        effective_from=item.get("start"),
                        effective_until=item.get("end"),
                    )
                )

    current_team_ids = sorted(
        {
            team_id
            for mapping in config.get("players", {}).values()
            if isinstance(mapping, dict)
            and (team_id := optional_int(mapping.get("api_sports_team_id")))
            is not None
        }
    )
    transfer_queries = (
        [("team", team_id) for team_id in current_team_ids]
        if current_team_ids
        else [("player", player_id) for player_id in sorted(player_map)]
    )
    for query_key, query_id in transfer_queries:
        for response in api_sports_pages(
            "https://v3.football.api-sports.io/transfers",
            query={query_key: query_id},
            headers=headers,
            paginate=False,
        ):
            calls += 1
            for container in response.get("response", []):
                if not isinstance(container, dict):
                    continue
                raw_player = container.get("player", {})
                provider_player_id = (
                    optional_int(raw_player.get("id"))
                    if isinstance(raw_player, dict)
                    else None
                )
                if provider_player_id is None and query_key == "player":
                    provider_player_id = query_id
                kicker_id = player_map.get(provider_player_id or -1)
                if not kicker_id:
                    continue
                mapping = config.get("players", {}).get(kicker_id, {})
                current_team_id = optional_int(
                    mapping.get("api_sports_team_id")
                )
                for transfer in container.get("transfers", []):
                    if not isinstance(transfer, dict):
                        continue
                    if not recent_enough(transfer.get("date"), lookback_days):
                        continue
                    teams = transfer.get("teams", {})
                    team_in = teams.get("in", {}) if isinstance(teams, dict) else {}
                    team_out = teams.get("out", {}) if isinstance(teams, dict) else {}
                    team_out_id = optional_int(team_out.get("id"))
                    team_in_id = optional_int(team_in.get("id"))
                    impact, severity = classify_transfer_impact(
                        current_team_id=current_team_id,
                        from_team_id=team_out_id,
                        to_team_id=team_in_id,
                        league_team_ids=league_team_ids,
                        league_team_ids_complete=league_team_ids_complete,
                    )
                    detail = (
                        f"{team_out.get('name', '?')} -> {team_in.get('name', '?')}"
                    )
                    output[kicker_id].append(
                        signal(
                            kind="transfer_confirmed",
                            status="confirmed",
                            severity=severity,
                            provider="api_sports",
                            observed_at=observed_at,
                            record_id=f"{provider_player_id}:{transfer.get('date', '')}",
                            detail=detail,
                            source_url="https://api-sports.io/documentation/football/v3",
                            effective_from=transfer.get("date"),
                            availability_impact=impact,
                        )
                    )
    return output, {
        "status": "ok",
        "fetched_at": observed_at,
        "records": sum(len(items) for items in output.values()),
        "requests": calls,
    }


def _sportmonks_data(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data", [])
    if isinstance(data, dict):
        return [data]
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def sportsmonks_signals(
    config: dict[str, Any],
    token: str,
    observed_at: str,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    section = config.get("sportsmonks", {})
    player_map = provider_id_map(config, "sportsmonks")
    output: dict[str, list[dict[str, Any]]] = defaultdict(list)
    calls = 0
    lookback_days = int(section.get("transfer_lookback_days", 120))
    base = "https://api.sportmonks.com/v3/football"
    headers = {"Authorization": token}
    league_team_ids, league_team_ids_complete = competition_team_ids(
        config,
        "sportsmonks",
    )

    team_ids = sorted(
        {
            normalized
            for team_id in section.get("team_ids", {}).values()
            if (normalized := optional_int(team_id)) is not None
        }
    )
    for team_id in team_ids:
        response = request_json(
            f"{base}/teams/{team_id}",
            query={
                "include": "sidelined.player;sidelined.sideline",
            },
            headers=headers,
        )
        calls += 1
        for team in _sportmonks_data(response):
            for item in team.get("sidelined", []):
                if not isinstance(item, dict):
                    continue
                provider_player_id = item.get("player_id")
                if provider_player_id is None and isinstance(item.get("player"), dict):
                    provider_player_id = item["player"].get("id")
                kicker_id = player_map.get(optional_int(provider_player_id) or -1)
                if not kicker_id:
                    continue
                sideline = item.get("sideline", {})
                detail = (
                    sideline.get("name")
                    if isinstance(sideline, dict)
                    else ""
                ) or item.get("category") or "sidelined"
                output[kicker_id].append(
                    signal(
                        kind="injury",
                        status="confirmed",
                        severity=80,
                        provider="sportsmonks",
                        observed_at=observed_at,
                        record_id=item.get("id"),
                        detail=str(detail),
                        source_url=(
                            "https://docs.sportmonks.com/v3/endpoints-and-entities/"
                            "endpoints/teams"
                        ),
                        effective_from=item.get("start_date"),
                        effective_until=item.get("end_date"),
                    )
                )

    rumour_days = min(31, lookback_days)
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=rumour_days)
    for response in sportsmonks_pages(
        (
            f"{base}/transfer-rumours/between/"
            f"{start_date.isoformat()}/{end_date.isoformat()}"
        ),
        query={"order": "desc"},
        headers=headers,
    ):
        calls += 1
        for rumour in _sportmonks_data(response):
            provider_player_id = optional_int(rumour.get("player_id"))
            kicker_id = player_map.get(provider_player_id or -1)
            if not kicker_id:
                continue
            probability = str(rumour.get("probability", "")).strip().upper()
            severity = {
                "HIGH": 70,
                "MEDIUM": 50,
                "LOW": 30,
            }.get(probability, 35)
            destination = rumour.get("to_team_id")
            detail = (
                f"{probability or 'UNKNOWN'} transfer rumour"
                + (f" to team {destination}" if destination is not None else "")
            )
            output[kicker_id].append(
                signal(
                    kind="transfer_rumour",
                    status="rumour",
                    severity=severity,
                    provider="sportsmonks",
                    observed_at=observed_at,
                    record_id=rumour.get("id"),
                    detail=detail,
                    source_url=(
                        rumour.get("source_url")
                        or (
                            "https://docs.sportmonks.com/v3/endpoints-and-entities/"
                            "endpoints/transfer-rumours"
                        )
                    ),
                    effective_from=rumour.get("date"),
                    availability_impact="rumour",
                )
            )

    for team_id in team_ids:
        for response in sportsmonks_pages(
            f"{base}/transfers/teams/{team_id}",
            query={"order": "desc"},
            headers=headers,
        ):
            calls += 1
            transfers = _sportmonks_data(response)
            page_has_recent_transfer = False
            for transfer in transfers:
                transfer_date = transfer.get("date")
                if not recent_enough(transfer_date, lookback_days):
                    continue
                page_has_recent_transfer = True
                provider_player_id = optional_int(transfer.get("player_id"))
                kicker_id = player_map.get(provider_player_id or -1)
                if not kicker_id:
                    continue
                mapping = config.get("players", {}).get(kicker_id, {})
                current_team_id = optional_int(
                    mapping.get("sportsmonks_team_id")
                )
                from_team_id = optional_int(transfer.get("from_team_id"))
                to_team_id = optional_int(transfer.get("to_team_id"))
                impact, severity = classify_transfer_impact(
                    current_team_id=current_team_id,
                    from_team_id=from_team_id,
                    to_team_id=to_team_id,
                    league_team_ids=league_team_ids,
                    league_team_ids_complete=league_team_ids_complete,
                )
                output[kicker_id].append(
                    signal(
                        kind="transfer_confirmed",
                        status="confirmed",
                        severity=severity,
                        provider="sportsmonks",
                        observed_at=observed_at,
                        record_id=transfer.get("id"),
                        detail=(
                            f"team {from_team_id or '?'} -> "
                            f"team {to_team_id or '?'}"
                        ),
                        source_url=(
                            "https://docs.sportmonks.com/v3/endpoints-and-entities/"
                            "endpoints/transfers/get-transfers-by-team-id"
                        ),
                        effective_from=transfer_date,
                        availability_impact=impact,
                    )
                )
            if transfers and not page_has_recent_transfer:
                break
    return output, {
        "status": "ok",
        "fetched_at": observed_at,
        "records": sum(len(items) for items in output.values()),
        "requests": calls,
    }


def consensus_for(signals: list[dict[str, Any]]) -> dict[str, Any]:
    active = [item for item in signals if item["status"] != "cleared"]
    confirmed_transfers = [
        item
        for item in active
        if (
            item["kind"] == "transfer_confirmed"
            and item["status"] == "confirmed"
        )
    ]
    latest_transfer_date = max(
        (
            str(item.get("effective_from", "")).strip()
            for item in confirmed_transfers
            if str(item.get("effective_from", "")).strip()
        ),
        default="",
    )
    current_confirmed_transfers = (
        [
            item
            for item in confirmed_transfers
            if str(item.get("effective_from", "")).strip()
            == latest_transfer_date
        ]
        if latest_transfer_date
        else confirmed_transfers
    )
    active_for_consensus = [
        item
        for item in active
        if item["kind"] != "transfer_confirmed"
    ] + current_confirmed_transfers
    injury = max(
        (
            item["severity"]
            for item in active_for_consensus
            if item["kind"] in {"injury", "suspension"}
        ),
        default=0,
    )
    transfer = max(
        (
            item["severity"]
            for item in active_for_consensus
            if item["kind"] in {"transfer_confirmed", "transfer_rumour"}
        ),
        default=0,
    )
    provider_sets: dict[str, set[str]] = defaultdict(set)
    for item in active_for_consensus:
        provider_sets[item["kind"]].add(item["source_provider"])
    corroborated = any(len(providers) >= 2 for providers in provider_sets.values())
    confirmed = any(item["status"] == "confirmed" for item in active)
    confidence = "high" if corroborated else ("medium" if confirmed else "low")
    injury_statuses = {
        item["status"]
        for item in signals
        if item["kind"] in {"injury", "suspension"}
    }
    conflicts = []
    if "cleared" in injury_statuses and injury_statuses - {"cleared"}:
        conflicts.append("providers disagree whether the player is currently available")
    transfer_impacts = {
        item.get("availability_impact")
        for item in current_confirmed_transfers
        if item["kind"] == "transfer_confirmed"
        and item.get("availability_impact")
        not in {None, "unknown", "unknown_destination"}
    }
    if "out" in transfer_impacts and transfer_impacts - {"out"}:
        conflicts.append("providers disagree about the confirmed transfer direction")
    confirmed_transfer_out = any(
        item["kind"] == "transfer_confirmed" and item["status"] == "confirmed"
        and item.get("availability_impact") == "out"
        for item in current_confirmed_transfers
    )
    selection_blocked = any(
        item.get("selection_blocking") is True
        for item in active_for_consensus
    )
    return {
        "injury": injury,
        "transfer": transfer,
        "rotation": 0,
        "fitness_cap": max(0, 100 - injury),
        "exclude": bool(
            (injury >= 90 or confirmed_transfer_out)
            and confidence in {"medium", "high"}
        ),
        "selection_blocked": selection_blocked,
        "selection_reason": (
            "current advanced outbound transfer evidence requires verification"
            if selection_blocked
            else ""
        ),
        "confidence": confidence,
        "conflicts": conflicts,
    }


def merge_market_mappings(
    runtime_config: dict[str, Any],
    market_players: list[dict[str, Any]] | None,
) -> None:
    """Keep fresh Kicker additions visible before provider IDs catch up."""

    configured = runtime_config.setdefault("players", {})
    if not isinstance(configured, dict):
        configured = {}
        runtime_config["players"] = configured
    for player in market_players or []:
        if not isinstance(player, dict):
            continue
        player_id = str(player.get("id", "")).strip()
        if not player_id:
            continue
        existing = configured.get(player_id, {})
        existing = dict(existing) if isinstance(existing, dict) else {}
        configured[player_id] = {
            **existing,
            "name": str(player.get("name", existing.get("name", ""))).strip(),
            "club": str(player.get("club", existing.get("club", ""))).strip(),
            "position": str(
                player.get("position", existing.get("position", ""))
            ).strip(),
            "mapping_confidence": existing.get(
                "mapping_confidence",
                "unverified",
            ),
        }


def transfer_report_signal(
    player_id: str,
    report: dict[str, Any],
    *,
    observed_at: str,
) -> dict[str, Any] | None:
    """Convert grounded editorial research into the provider-neutral gate."""

    status = str(report.get("status", ""))
    stage = str(report.get("stage", ""))
    direction = str(report.get("direction", "unknown"))
    if status not in {"rumour", "advanced", "confirmed"}:
        return None
    if status == "confirmed":
        kind = "transfer_confirmed"
        signal_status = "confirmed"
        impact = direction
    else:
        kind = "transfer_rumour"
        signal_status = "rumour"
        impact = "rumour"
    severity = {
        "rumour": 35,
        "contact": 42,
        "negotiation": 55,
        "agreement": 72,
        "medical": 84,
        "official": (
            95 if direction == "out" else 55
            if direction == "within_competition"
            else 10
        ),
    }.get(stage, 35)
    evidence = report.get("evidence", [])
    source_url = next(
        (
            str(item.get("source_url", ""))
            for item in evidence
            if isinstance(item, dict)
            and str(item.get("source_url", "")).startswith("https://")
        ),
        "",
    )
    detail = (
        f"{report.get('from_club', '?')} -> {report.get('to_club', '?')} "
        f"({stage}, {report.get('deal_type', 'unknown')})"
    )
    output = signal(
        kind=kind,
        status=signal_status,
        severity=severity,
        provider=str(
            report.get("source_channel", "openai_transfer_watcher")
        ),
        observed_at=observed_at,
        record_id=str(report.get("research_fingerprint", player_id)),
        detail=detail,
        source_url=source_url,
        effective_from=report.get("observed_at", observed_at),
        availability_impact=impact,
    )
    output["selection_blocking"] = bool(
        status == "advanced"
        and direction == "out"
        and stage in {"agreement", "medical", "official"}
        and str(report.get("confidence", "low")) in {"medium", "high"}
    )
    return output


def apply_transfer_research_caution(
    consensus: dict[str, Any],
    abstention: Any,
) -> dict[str, Any]:
    """Prevent uncertain critical research from looking like zero risk."""

    if not isinstance(abstention, dict):
        return consensus
    priority = str(abstention.get("research_priority", "routine"))
    status = str(abstention.get("status", ""))
    if priority != "critical":
        return consensus
    cautious = dict(consensus)
    if status == "research_inconclusive":
        cautious["transfer"] = max(float(cautious.get("transfer", 0)), 45.0)
        cautious["selection_blocked"] = True
        cautious["selection_reason"] = (
            "critical transfer research remained inconclusive"
        )
    elif status == "no_grounded_transfer_signal":
        cautious["transfer"] = max(float(cautious.get("transfer", 0)), 15.0)
        cautious["selection_reason"] = (
            "critical transfer search found no signal after independent verification"
        )
    cautious["transfer_research_status"] = status
    cautious["transfer_verification_passes"] = int(
        abstention.get("verification_passes", 1) or 1
    )
    return cautious


def build_snapshot(
    config: dict[str, Any],
    *,
    providers: list[str],
    optional_providers: list[str] | None = None,
    ttl_hours: int,
    role_config: dict[str, Any] | None = None,
    researched_role_profiles: dict[str, dict[str, Any]] | None = None,
    role_research_abstentions: dict[str, dict[str, Any]] | None = None,
    role_research_audit: dict[str, Any] | None = None,
    researched_team_profiles: dict[str, dict[str, Any]] | None = None,
    team_research_audit: dict[str, Any] | None = None,
    researched_transfer_reports: dict[str, dict[str, Any]] | None = None,
    transfer_research_abstentions: dict[str, dict[str, Any]] | None = None,
    transfer_research_audit: dict[str, Any] | None = None,
    market_players: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    observed_at = iso_now()
    runtime_config = copy.deepcopy(config)
    all_signals: dict[str, list[dict[str, Any]]] = defaultdict(list)
    provider_audit: dict[str, Any] = {}
    optional_provider_set = set(optional_providers or [])
    requested_providers = list(
        dict.fromkeys([*providers, *(optional_providers or [])])
    )
    for provider in requested_providers:
        if provider == "api_sports":
            token = os.environ.get("API_SPORTS_KEY", "").strip()
            if not token:
                if provider in optional_provider_set:
                    provider_audit[provider] = {
                        "status": "not_configured",
                        "records": 0,
                        "requests": 0,
                    }
                    continue
                raise RuntimeError("API_SPORTS_KEY is required")
            runtime_config, roster_audit = discover_api_sports_roster(
                runtime_config,
                token,
            )
            signals, audit = api_sports_signals(
                runtime_config,
                token,
                observed_at,
            )
            audit["roster"] = roster_audit
        elif provider == "sportsmonks":
            token = os.environ.get("SPORTMONKS_API_TOKEN", "").strip()
            if not token:
                if provider in optional_provider_set:
                    provider_audit[provider] = {
                        "status": "not_configured",
                        "records": 0,
                        "requests": 0,
                    }
                    continue
                raise RuntimeError("SPORTMONKS_API_TOKEN is required")
            sportsmonks = runtime_config.get("sportsmonks", {})
            player_map = provider_id_map(runtime_config, "sportsmonks")
            team_ids, _ = competition_team_ids(
                runtime_config,
                "sportsmonks",
            )
            if not sportsmonks or not player_map or not team_ids:
                if provider in optional_provider_set:
                    provider_audit[provider] = {
                        "status": "configuration_required",
                        "records": 0,
                        "requests": 0,
                        "detail": (
                            "sportsmonks team and player mappings are required"
                        ),
                    }
                    continue
                raise RuntimeError(
                    "Sportsmonks requires team and player mappings"
                )
            signals, audit = sportsmonks_signals(
                runtime_config,
                token,
                observed_at,
            )
        else:
            raise RuntimeError(f"unsupported provider: {provider}")
        provider_audit[provider] = audit
        for kicker_id, items in signals.items():
            all_signals[kicker_id].extend(items)

    merge_market_mappings(runtime_config, market_players)
    if researched_transfer_reports:
        provider_audit["openai_transfer_watcher"] = {
            "status": str(
                (transfer_research_audit or {}).get("status", "ok")
            ),
            "fetched_at": observed_at,
            "records": len(researched_transfer_reports),
            "requests": int(
                (transfer_research_audit or {}).get("requests", 0)
            ),
        }
    editorial_reports = [
        report
        for report in (researched_transfer_reports or {}).values()
        if isinstance(report, dict)
        and report.get("source_channel") == "central_editorial_transfer_evidence"
    ]
    if editorial_reports:
        provider_audit["central_editorial_transfer_evidence"] = {
            "status": "ok",
            "fetched_at": observed_at,
            "records": len(editorial_reports),
            "requests": 0,
        }
    for kicker_id, report in (researched_transfer_reports or {}).items():
        if not isinstance(report, dict) or not report.get("fresh", False):
            continue
        editorial_signal = transfer_report_signal(
            str(kicker_id),
            report,
            observed_at=observed_at,
        )
        if editorial_signal is not None:
            all_signals[str(kicker_id)].append(editorial_signal)

    players: dict[str, Any] = {}
    for kicker_id, mapping in runtime_config.get("players", {}).items():
        if not isinstance(mapping, dict):
            continue
        deduplicated: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
        for item in all_signals.get(str(kicker_id), []):
            key = (
                item["source_provider"],
                item["kind"],
                item["provider_record_id"],
                item["effective_from"],
                item["detail"],
            )
            deduplicated[key] = item
        signals = sorted(
            deduplicated.values(),
            key=lambda item: (
                item["kind"],
                item["source_provider"],
                item["provider_record_id"],
            ),
        )
        consensus = apply_transfer_research_caution(
            consensus_for(signals),
            (transfer_research_abstentions or {}).get(str(kicker_id)),
        )
        players[str(kicker_id)] = {
            "name": str(mapping.get("name", "")),
            "club": str(mapping.get("club", "")),
            "mapping": {
                "api_sports_player_id": mapping.get("api_sports_player_id"),
                "api_sports_team_id": mapping.get("api_sports_team_id"),
                "sportsmonks_player_id": mapping.get("sportsmonks_player_id"),
                "sportsmonks_team_id": mapping.get("sportsmonks_team_id"),
                "age": mapping.get("age"),
                "position": str(mapping.get("position", "")).strip(),
                "confidence": str(mapping.get("mapping_confidence", "unverified")),
            },
            "signals": signals,
            "consensus": consensus,
        }

    generated = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    role_profiles = cached_role_profiles(
        role_config,
        generated_at=observed_at,
    )
    for player_id, profile in (researched_role_profiles or {}).items():
        if isinstance(profile, dict):
            role_profiles[str(player_id)] = dict(profile)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": observed_at,
        "expires_at": (
            generated + timedelta(hours=ttl_hours)
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "competition": str(config["competition"]),
        "season": str(config["season"]),
        "providers": provider_audit,
        "players": players,
        "role_profiles": role_profiles,
        "role_research_abstentions": role_research_abstentions or {},
        "role_research": role_research_audit or {
            "status": "not_configured",
            "targets": 0,
            "cache_hits": 0,
            "researched_profiles": 0,
            "researched_abstentions": 0,
            "requests": 0,
            "failures": [],
        },
        "team_profiles": researched_team_profiles or {},
        "team_research": team_research_audit or {
            "status": "not_configured",
            "targets": 0,
            "cache_hits": 0,
            "researched_profiles": 0,
            "inconclusive": 0,
            "requests": 0,
            "failures": [],
        },
        "transfer_profiles": researched_transfer_reports or {},
        "transfer_research_abstentions": (
            transfer_research_abstentions or {}
        ),
        "transfer_research": transfer_research_audit or {
            "status": "not_configured",
            "targets": 0,
            "cache_hits": 0,
            "researched_reports": 0,
            "researched_abstentions": 0,
            "researched_inconclusive": 0,
            "requests": 0,
            "failures": [],
        },
    }
    payload["openai_usage"] = combined_openai_usage(
        payload["role_research"],
        payload["team_research"],
        payload["transfer_research"],
    )
    payload["evidence_cache"] = build_evidence_cache(
        payload["role_profiles"],
        payload["team_profiles"],
        payload["transfer_profiles"],
    )
    validate_snapshot(payload)
    payload["content_sha256"] = canonical_sha256(payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--role-evidence-config", type=Path)
    parser.add_argument("--editorial-transfer-evidence", type=Path)
    parser.add_argument("--market")
    parser.add_argument("--previous-quality")
    parser.add_argument("--openai-role-model", default=DEFAULT_OPENAI_ROLE_MODEL)
    parser.add_argument(
        "--openai-role-max-players",
        type=int,
        default=0,
        help="maximum targets; 0 researches every available market player",
    )
    parser.add_argument("--openai-role-batch-size", type=int, default=8)
    parser.add_argument(
        "--openai-transfer-max-players",
        type=int,
        default=0,
        help="maximum transfer-watcher targets; 0 researches the full market",
    )
    parser.add_argument("--openai-transfer-batch-size", type=int, default=8)
    parser.add_argument("--openai-transfer-workers", type=int, default=4)
    parser.add_argument(
        "--openai-refresh-mode",
        choices=("urgent", "standard", "full"),
        default="standard",
        help=(
            "urgent refreshes only high-risk changes, standard obeys the "
            "risk-based cache, full bypasses OpenAI research caches"
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous")
    parser.add_argument(
        "--provider",
        action="append",
        choices=("api_sports", "sportsmonks"),
        dest="providers",
    )
    parser.add_argument(
        "--optional-provider",
        action="append",
        choices=("api_sports", "sportsmonks"),
        dest="optional_providers",
    )
    parser.add_argument("--ttl-hours", type=int, default=18)
    args = parser.parse_args()
    if args.ttl_hours < 1 or args.ttl_hours > 72:
        parser.error("--ttl-hours must be between 1 and 72")
    if not 0 <= args.openai_role_max_players <= 2_000:
        parser.error(
            "--openai-role-max-players must be 0 (all) or between 1 and 2000"
        )
    if not 1 <= args.openai_role_batch_size <= 8:
        parser.error("--openai-role-batch-size must be between 1 and 8")
    if not 0 <= args.openai_transfer_max_players <= 2_000:
        parser.error(
            "--openai-transfer-max-players must be 0 (all) or between 1 and 2000"
        )
    if not 1 <= args.openai_transfer_batch_size <= 8:
        parser.error("--openai-transfer-batch-size must be between 1 and 8")
    if not 1 <= args.openai_transfer_workers <= 8:
        parser.error("--openai-transfer-workers must be between 1 and 8")
    if bool(args.market) != bool(args.previous_quality):
        parser.error(
            "--market and --previous-quality must be provided together"
        )
    if args.editorial_transfer_evidence and not args.market:
        parser.error(
            "--editorial-transfer-evidence requires --market and --previous-quality"
        )
    if not args.providers:
        args.providers = ["api_sports"]
    return args


def main() -> int:
    args = parse_args()
    config = json.loads(args.mapping.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise SystemExit("mapping configuration must be a JSON object")
    if config.get("competition") not in {
        "Bundesliga",
        "2. Bundesliga",
        "3. Liga",
    }:
        raise SystemExit(
            "mapping competition must be Bundesliga, 2. Bundesliga or 3. Liga"
        )
    if not str(config.get("season", "")).strip():
        raise SystemExit("mapping season is required")
    players = config.get("players", {})
    role_config: dict[str, Any] | None = None
    if args.role_evidence_config:
        role_config = json.loads(
            args.role_evidence_config.read_text(encoding="utf-8")
        )
        if not isinstance(role_config, dict):
            raise SystemExit("role evidence configuration must be an object")
    auto_discover = bool(
        config.get("api_sports", {}).get("auto_discover_players", False)
    )
    if not isinstance(players, dict) or (not players and not auto_discover):
        raise SystemExit(
            "mapping players must be a non-empty object unless "
            "api_sports.auto_discover_players is enabled"
        )
    previous_news: dict[str, Any] | None = None
    if args.previous:
        try:
            previous_news = load_news_snapshot(
                args.previous,
                require_fresh=False,
            )
        except (OSError, ValueError):
            previous_news = None

    researched_role_profiles: dict[str, dict[str, Any]] = {}
    role_research_abstentions: dict[str, dict[str, Any]] = {}
    role_research_audit: dict[str, Any] = {
        "status": "not_configured",
        "targets": 0,
        "cache_hits": 0,
        "researched_profiles": 0,
        "researched_abstentions": 0,
        "researched_inconclusive": 0,
        "requests": 0,
        "failures": [],
    }
    researched_team_profiles: dict[str, dict[str, Any]] = {}
    team_research_audit: dict[str, Any] = {
        "status": "not_configured",
        "targets": 0,
        "cache_hits": 0,
        "researched_profiles": 0,
        "inconclusive": 0,
        "requests": 0,
        "failures": [],
    }
    researched_transfer_reports: dict[str, dict[str, Any]] = {}
    transfer_research_abstentions: dict[str, dict[str, Any]] = {}
    transfer_research_audit: dict[str, Any] = {
        "status": "not_configured",
        "targets": 0,
        "cache_hits": 0,
        "researched_reports": 0,
        "researched_abstentions": 0,
        "researched_inconclusive": 0,
        "requests": 0,
        "failures": [],
    }
    market_payload: dict[str, Any] | None = None
    if args.market and args.previous_quality:
        market_payload = load_market_snapshot(args.market)
        try:
            previous_quality = load_quality_snapshot(
                args.previous_quality,
                require_fresh=False,
            )
        except (OSError, ValueError):
            previous_quality = {
                "competition": config["competition"],
                "season": config["season"],
                "annotations": {},
            }
        if (
            market_payload["competition"] != config["competition"]
            or market_payload["season"] != config["season"]
            or previous_quality["competition"] != config["competition"]
            or previous_quality["season"] != config["season"]
        ):
            raise RuntimeError(
                "OpenAI role-research inputs belong to another competition"
            )
        explicit_player_ids = (
            role_config.get("role_evidence", {}).keys()
            if isinstance(role_config, dict)
            and isinstance(role_config.get("role_evidence"), dict)
            else ()
        )
        targets = select_role_targets(
            market_payload,
            previous_quality,
            explicit_player_ids=explicit_player_ids,
            max_players=args.openai_role_max_players,
        )
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if api_key:
            (
                researched_role_profiles,
                role_research_abstentions,
                role_research_audit,
            ) = (
                research_role_profiles(
                    targets,
                    competition=str(config["competition"]),
                    season=str(config["season"]),
                    previous_profiles=(
                        previous_news.get("role_profiles", {})
                        if isinstance(previous_news, dict)
                        else {}
                    ),
                    previous_abstentions=(
                        previous_news.get("role_research_abstentions", {})
                        if isinstance(previous_news, dict)
                        else {}
                    ),
                    api_key=api_key,
                    model=args.openai_role_model,
                    batch_size=args.openai_role_batch_size,
                    refresh_mode=args.openai_refresh_mode,
                )
            )
        else:
            reusable = {
                str(player_id): dict(profile)
                for player_id, profile in (
                    previous_news.get("role_profiles", {}).items()
                    if isinstance(previous_news, dict)
                    and isinstance(previous_news.get("role_profiles"), dict)
                    else []
                )
                if isinstance(profile, dict)
                and str(profile.get("model_version", "")).startswith(
                    "openai-role-web-"
                )
                and profile.get("fresh", False)
            }
            researched_role_profiles = reusable
            role_research_abstentions = {
                str(player_id): dict(record)
                for player_id, record in (
                    previous_news.get(
                        "role_research_abstentions",
                        {},
                    ).items()
                    if isinstance(previous_news, dict)
                    and isinstance(
                        previous_news.get("role_research_abstentions"),
                        dict,
                    )
                    else []
                )
                if isinstance(record, dict)
            }
            role_research_audit = {
                "status": "not_configured",
                "model": args.openai_role_model,
                "targets": len(targets),
                "cache_hits": len(reusable) + len(role_research_abstentions),
                "researched_profiles": 0,
                "researched_abstentions": 0,
                "researched_inconclusive": 0,
                "requests": 0,
                "failures": [],
            }
        role_research_audit["target_positions"] = {
            position: sum(
                target.get("position") == position for target in targets
            )
            for position in (
                "GOALKEEPER",
                "DEFENDER",
                "MIDFIELDER",
                "FORWARD",
            )
        }
        role_research_audit["target_clubs"] = len(
            {str(target.get("club", "")) for target in targets}
        )
        clubs = sorted(
            {
                str(player.get("club", "")).strip()
                for player in market_payload.get("players", [])
                if isinstance(player, dict)
                and player.get("available", True)
                and str(player.get("club", "")).strip()
            }
        )
        # Resolve deterministic primary-source registers before paid web search.
        # Players already confirmed there do not need an OpenAI transfer query.
        register_failures: list[str] = []
        official_register_reports: dict[str, dict[str, Any]] = {}
        editorial_reports: dict[str, dict[str, Any]] = {}
        editorial_audit: dict[str, Any] = {
            "status": "not_configured",
            "records": 0,
        }
        if args.editorial_transfer_evidence:
            editorial_reports, editorial_audit = (
                load_editorial_transfer_evidence(
                    args.editorial_transfer_evidence,
                    market=market_payload,
                    competition=str(config["competition"]),
                    season=str(config["season"]),
                    now=datetime.now(timezone.utc),
                    model=args.openai_role_model,
                )
            )
        for register in config.get("official_transfer_registers", []):
            if not isinstance(register, dict):
                register_failures.append("invalid register configuration")
                continue
            source_url = str(register.get("url", "")).strip()
            try:
                if (
                    register.get("format")
                    != "bundesliga_transfer_centre"
                    or not source_url.startswith("https://")
                ):
                    raise RuntimeError(
                        "unsupported official transfer register"
                    )
                parsed_reports = parse_bundesliga_transfer_centre(
                    request_text(source_url),
                    market=market_payload,
                    source_url=source_url,
                    now=datetime.now(timezone.utc),
                    model=args.openai_role_model,
                )
                minimum_records = int(register.get("minimum_records", 1))
                if len(parsed_reports) < minimum_records:
                    raise RuntimeError(
                        "official transfer register returned only "
                        f"{len(parsed_reports)} matched records"
                    )
                official_register_reports.update(parsed_reports)
            except (OSError, RuntimeError, ValueError) as error:
                register_failures.append(str(error)[:240])
        all_transfer_targets = select_transfer_targets(
            market_payload,
            previous_quality,
            previous_news,
            max_players=args.openai_transfer_max_players,
        )
        transfer_targets = [
            target
            for target in all_transfer_targets
            if str(target["player_id"]) not in official_register_reports
            and str(target["player_id"]) not in editorial_reports
        ]
        if api_key:
            (
                researched_transfer_reports,
                transfer_research_abstentions,
                transfer_research_audit,
            ) = research_transfer_reports(
                transfer_targets,
                competition=str(config["competition"]),
                season=str(config["season"]),
                competition_clubs=set(clubs),
                previous_reports=(
                    previous_news.get("transfer_profiles", {})
                    if isinstance(previous_news, dict)
                    else {}
                ),
                previous_abstentions=(
                    previous_news.get(
                        "transfer_research_abstentions",
                        {},
                    )
                    if isinstance(previous_news, dict)
                    else {}
                ),
                api_key=api_key,
                model=args.openai_role_model,
                batch_size=args.openai_transfer_batch_size,
                max_workers=args.openai_transfer_workers,
                refresh_mode=args.openai_refresh_mode,
            )
        else:
            researched_transfer_reports = {
                str(player_id): dict(report)
                for player_id, report in (
                    previous_news.get("transfer_profiles", {}).items()
                    if isinstance(previous_news, dict)
                    and isinstance(
                        previous_news.get("transfer_profiles"),
                        dict,
                    )
                    else []
                )
                if isinstance(report, dict) and report.get("fresh", False)
            }
            transfer_research_abstentions = {
                str(player_id): dict(record)
                for player_id, record in (
                    previous_news.get(
                        "transfer_research_abstentions",
                        {},
                    ).items()
                    if isinstance(previous_news, dict)
                    and isinstance(
                        previous_news.get(
                            "transfer_research_abstentions"
                        ),
                        dict,
                    )
                    else []
                )
                if isinstance(record, dict)
            }
            transfer_research_audit = {
                **transfer_research_audit,
                "model": args.openai_role_model,
                "targets": len(transfer_targets),
                "cache_hits": (
                    len(researched_transfer_reports)
                    + len(transfer_research_abstentions)
                ),
            }
        researched_transfer_reports.update(official_register_reports)
        researched_transfer_reports.update(editorial_reports)
        for player_id in {*official_register_reports, *editorial_reports}:
            transfer_research_abstentions.pop(player_id, None)
        transfer_research_audit["official_register_reports"] = len(
            official_register_reports
        )
        transfer_research_audit["deterministic_search_skips"] = len(
            {
                str(target["player_id"])
                for target in all_transfer_targets
            }
            & {*official_register_reports, *editorial_reports}
        )
        transfer_research_audit["official_register_failures"] = (
            register_failures[:5]
        )
        transfer_research_audit["editorial_evidence"] = editorial_audit
        if api_key:
            (
                researched_team_profiles,
                team_research_audit,
            ) = research_team_profiles(
                clubs,
                competition=str(config["competition"]),
                season=str(config["season"]),
                previous_profiles=(
                    previous_news.get("team_profiles", {})
                    if isinstance(previous_news, dict)
                    else {}
                ),
                api_key=api_key,
                model=args.openai_role_model,
            )
        else:
            researched_team_profiles = {
                str(club): dict(profile)
                for club, profile in (
                    previous_news.get("team_profiles", {}).items()
                    if isinstance(previous_news, dict)
                    and isinstance(previous_news.get("team_profiles"), dict)
                    else []
                )
                if isinstance(profile, dict)
            }
            team_research_audit = {
                **team_research_audit,
                "targets": len(clubs),
                "cache_hits": len(researched_team_profiles),
            }

    try:
        payload = build_snapshot(
            config,
            providers=list(dict.fromkeys(args.providers)),
            optional_providers=list(
                dict.fromkeys(args.optional_providers or [])
            ),
            ttl_hours=args.ttl_hours,
            role_config=role_config,
            researched_role_profiles=researched_role_profiles,
            role_research_abstentions=role_research_abstentions,
            role_research_audit=role_research_audit,
            researched_team_profiles=researched_team_profiles,
            team_research_audit=team_research_audit,
            researched_transfer_reports=researched_transfer_reports,
            transfer_research_abstentions=transfer_research_abstentions,
            transfer_research_audit=transfer_research_audit,
            market_players=(
                market_payload.get("players", [])
                if isinstance(market_payload, dict)
                else []
            ),
        )
    except RuntimeError as error:
        if not args.previous or not is_api_sports_daily_limit(error):
            raise
        payload = load_news_snapshot(args.previous)
        if (
            payload["competition"] != config["competition"]
            or payload["season"] != config["season"]
        ):
            raise RuntimeError(
                "previous news snapshot belongs to another competition"
            ) from error
        payload = merge_role_research_into_previous_snapshot(
            payload,
            role_profiles=researched_role_profiles,
            role_research_abstentions=role_research_abstentions,
            role_research_audit=role_research_audit,
            team_profiles=researched_team_profiles,
            team_research_audit=team_research_audit,
            transfer_reports=researched_transfer_reports,
            transfer_research_abstentions=transfer_research_abstentions,
            transfer_research_audit=transfer_research_audit,
            market_players=(
                market_payload.get("players", [])
                if isinstance(market_payload, dict)
                else []
            ),
        )
        validate_snapshot(payload)
        print(
            "API-Sports daily limit reached; reusing the previous fresh "
            "provider snapshot without extending its expiry while publishing "
            "the refreshed grounded role research.",
            file=sys.stderr,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(f"{args.output.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(args.output)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "competition": payload["competition"],
                "season": payload["season"],
                "players": len(payload["players"]),
                "providers": sorted(payload["providers"]),
                "role_research": payload["role_research"],
                "team_research": payload["team_research"],
                "transfer_research": payload["transfer_research"],
                "content_sha256": payload["content_sha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
