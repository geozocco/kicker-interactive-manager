#!/usr/bin/env python3
"""Ground current club-role profiles with OpenAI web search.

The model is an evidence extractor, not the final football scorer. Every
accepted profile is constrained by deterministic source, recency, confidence,
and designation rules before it can enter the central news snapshot.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable
from urllib.parse import urlparse


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5.6-luna"
MODEL_VERSION = "openai-role-web-v1"
PROMPT_VERSION = "role-research-2026-07-28-v1"
USER_AGENT = "kicker-interactive-manager-role-research/1"
ROLE_RESPONSIBILITIES = {
    "penalties",
    "direct_free_kicks",
    "corners",
    "playmaker",
    "offensive_focal_point",
    "aerial_set_piece_target",
    "captain",
}
DESIGNATION_BOUNDS = {
    "confirmed_starter": (90.0, 100.0),
    "key_starter": (82.0, 98.0),
    "expected_starter": (70.0, 92.0),
    "immediate_help": (60.0, 88.0),
    "open_competition": (35.0, 69.0),
    "rotation": (20.0, 55.0),
    "perspective": (0.0, 30.0),
}
SOURCE_AUTHORITY = {
    "head_coach": 5,
    "official_club": 5,
    "transfer_announcement": 4,
    "sporting_director": 4,
    "player_statement": 3,
    "reputable_editorial": 2,
}
POSITIONS = {"GOALKEEPER", "DEFENDER", "MIDFIELDER", "FORWARD"}


def parsed_timestamp(value: Any) -> datetime | None:
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


def iso_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00",
        "Z",
    )


def optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _available_market_players(market: dict[str, Any]) -> list[dict[str, Any]]:
    players = market.get("players", [])
    if not isinstance(players, list):
        return []
    return [
        player
        for player in players
        if isinstance(player, dict)
        and player.get("available", True)
        and str(player.get("id", "")).strip()
        and str(player.get("name", "")).strip()
        and str(player.get("club", "")).strip()
        and str(player.get("position", "")) in POSITIONS
        and optional_float(player.get("market_value")) is not None
        and float(player["market_value"]) < 100_000_000
    ]


def select_role_targets(
    market: dict[str, Any],
    previous_quality: dict[str, Any] | None,
    *,
    explicit_player_ids: Iterable[str] = (),
    max_players: int = 96,
) -> list[dict[str, Any]]:
    """Select a broad, deterministic and position-balanced target set."""

    if max_players < 1:
        return []
    players = _available_market_players(market)
    by_id = {str(player["id"]): player for player in players}
    annotations = (
        previous_quality.get("annotations", {})
        if isinstance(previous_quality, dict)
        else {}
    )
    if not isinstance(annotations, dict):
        annotations = {}

    priority: dict[str, float] = {}
    protected_ids: set[str] = set()

    def promote(player_id: str, score: float) -> None:
        if player_id in by_id:
            priority[player_id] = max(priority.get(player_id, 0.0), score)

    for player_id in explicit_player_ids:
        normalized_id = str(player_id)
        promote(normalized_id, 1_000.0)
        protected_ids.add(normalized_id)
    for player_id, annotation in annotations.items():
        if not isinstance(annotation, dict):
            continue
        if annotation.get("role_research", {}).get("required"):
            promote(str(player_id), 950.0)
            protected_ids.add(str(player_id))
        if annotation.get("benchmark"):
            promote(str(player_id), 900.0)
            protected_ids.add(str(player_id))
        if annotation.get("offensive_premium_anchor"):
            promote(str(player_id), 825.0)
        if annotation.get("reliable_anchor"):
            promote(str(player_id), 780.0)
        components = annotation.get("components", {})
        talent_profile = (
            annotation.get("history_summary", {}).get("talent_profile", {})
            if isinstance(annotation.get("history_summary"), dict)
            else {}
        )
        if (
            isinstance(components, dict)
            and isinstance(talent_profile, dict)
            and optional_float(talent_profile.get("age")) is not None
            and float(talent_profile["age"]) <= 23
            and optional_float(components.get("upside")) is not None
            and float(components["upside"]) >= 72
            and optional_float(components.get("minutes")) is not None
            and float(components["minutes"]) >= 55
        ):
            promote(str(player_id), 735.0)

    by_club_goalkeepers: dict[str, list[dict[str, Any]]] = {}
    for player in players:
        if player["position"] == "GOALKEEPER":
            by_club_goalkeepers.setdefault(str(player["club"]), []).append(player)
    goalkeeper_coverage_ids: list[str] = []
    for club in sorted(by_club_goalkeepers):
        club_players = by_club_goalkeepers[club]
        ranked = sorted(
            club_players,
            key=lambda player: (
                -float(player["market_value"]),
                -float(player.get("points", 0) or 0),
                str(player["id"]),
            ),
        )
        for rank, player in enumerate(ranked[:2]):
            player_id = str(player["id"])
            goalkeeper_coverage_ids.append(player_id)
            promote(player_id, 760.0 - 10.0 * rank)

    position_limits = {
        "DEFENDER": 12,
        "MIDFIELDER": 18,
        "FORWARD": 18,
    }
    for position, limit in position_limits.items():
        ranked = sorted(
            (player for player in players if player["position"] == position),
            key=lambda player: (
                -float(player["market_value"]),
                -float(player.get("points", 0) or 0),
                str(player["id"]),
            ),
        )
        for rank, player in enumerate(ranked[:limit]):
            promote(str(player["id"]), 700.0 - rank)

    offensive_club_coverage_ids: list[str] = []
    clubs = sorted({str(player["club"]) for player in players})
    for club in clubs:
        ranked = sorted(
            (
                player
                for player in players
                if str(player["club"]) == club
                and player["position"] in {"MIDFIELDER", "FORWARD"}
            ),
            key=lambda player: (
                -float(player["market_value"]),
                -float(player.get("points", 0) or 0),
                str(player["id"]),
            ),
        )
        if ranked:
            player_id = str(ranked[0]["id"])
            offensive_club_coverage_ids.append(player_id)
            promote(player_id, 725.0)

    priority_order = sorted(
        priority,
        key=lambda player_id: (
            -priority[player_id],
            -float(by_id[player_id]["market_value"]),
            str(by_id[player_id]["club"]),
            player_id,
        ),
    )
    protected_order = [
        player_id for player_id in priority_order if player_id in protected_ids
    ]
    ordered_ids: list[str] = []
    for player_id in (
        protected_order
        + goalkeeper_coverage_ids
        + offensive_club_coverage_ids
        + priority_order
    ):
        if player_id not in ordered_ids:
            ordered_ids.append(player_id)
    return [
        {
            "player_id": player_id,
            "name": str(by_id[player_id]["name"]).strip(),
            "club": str(by_id[player_id]["club"]).strip(),
            "position": str(by_id[player_id]["position"]),
            "market_value": int(float(by_id[player_id]["market_value"])),
        }
        for player_id in ordered_ids[:max_players]
    ]


def reusable_profile(
    profile: Any,
    *,
    now: datetime,
    model: str,
) -> bool:
    if not isinstance(profile, dict):
        return False
    if profile.get("model_version") != MODEL_VERSION:
        return False
    if profile.get("research_model") != model:
        return False
    refresh_after = parsed_timestamp(profile.get("refresh_after"))
    expires_at = parsed_timestamp(profile.get("expires_at"))
    return bool(
        refresh_after
        and expires_at
        and now < refresh_after
        and now < expires_at
        and profile.get("fresh", False)
    )


def reusable_abstention(
    record: Any,
    *,
    now: datetime,
    model: str,
) -> bool:
    if not isinstance(record, dict):
        return False
    if record.get("model_version") != MODEL_VERSION:
        return False
    if record.get("research_model") != model:
        return False
    refresh_after = parsed_timestamp(record.get("refresh_after"))
    expires_at = parsed_timestamp(record.get("expires_at"))
    return bool(
        refresh_after
        and expires_at
        and now < refresh_after
        and now < expires_at
        and record.get("status") == "no_grounded_signal"
    )


def abstention_record(
    target: dict[str, Any],
    *,
    now: datetime,
    model: str,
) -> dict[str, Any]:
    refresh_days = 3 if target["position"] == "GOALKEEPER" else 7
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "prompt": PROMPT_VERSION,
                "model": model,
                "target": target,
                "status": "no_grounded_signal",
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "status": "no_grounded_signal",
        "model_version": MODEL_VERSION,
        "prompt_version": PROMPT_VERSION,
        "research_model": model,
        "research_fingerprint": fingerprint,
        "checked_at": iso_timestamp(now),
        "refresh_after": iso_timestamp(now + timedelta(days=refresh_days)),
        "expires_at": iso_timestamp(now + timedelta(days=14)),
    }


def _schema() -> dict[str, Any]:
    responsibility_properties = {
        key: {
            "type": "string",
            "enum": ["none", "shared", "primary"],
        }
        for key in sorted(ROLE_RESPONSIBILITIES)
    }
    evidence_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "claim": {"type": "string"},
            "source_url": {"type": "string"},
            "observed_at": {"type": "string"},
            "source_authority": {
                "type": "string",
                "enum": sorted(SOURCE_AUTHORITY),
            },
        },
        "required": [
            "claim",
            "source_url",
            "observed_at",
            "source_authority",
        ],
    }
    profile_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "player_id": {"type": "string"},
            "has_role_signal": {"type": "boolean"},
            "designation": {
                "type": "string",
                "enum": sorted(DESIGNATION_BOUNDS),
            },
            "continuity": {
                "type": "string",
                "enum": ["confirmed", "expanded", "unknown", "reduced"],
            },
            "expected_start_probability": {
                "type": "number",
                "minimum": 0,
                "maximum": 100,
            },
            "external_signing_risk": {
                "type": "number",
                "minimum": 0,
                "maximum": 100,
            },
            "responsibilities": {
                "type": "object",
                "additionalProperties": False,
                "properties": responsibility_properties,
                "required": sorted(ROLE_RESPONSIBILITIES),
            },
            "confidence": {
                "type": "string",
                "enum": ["low", "medium", "high"],
            },
            "contradiction": {"type": "boolean"},
            "note": {"type": "string"},
            "evidence": {
                "type": "array",
                "items": evidence_schema,
                "maxItems": 4,
            },
        },
        "required": [
            "player_id",
            "has_role_signal",
            "designation",
            "continuity",
            "expected_start_probability",
            "external_signing_risk",
            "responsibilities",
            "confidence",
            "contradiction",
            "note",
            "evidence",
        ],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "profiles": {
                "type": "array",
                "items": profile_schema,
            }
        },
        "required": ["profiles"],
    }


def build_request(
    targets: list[dict[str, Any]],
    *,
    competition: str,
    season: str,
    model: str,
    current_date: str,
) -> dict[str, Any]:
    instructions = (
        "Research the current expected club role of each listed football player. "
        "Use web search and prefer current official club statements, head-coach "
        "quotes, sporting-director quotes, and explicit transfer announcements. "
        "Reputable editorial reports are secondary. Ignore fantasy-game opinions, "
        "social-media speculation, historical reputation without current-club "
        "evidence, and instructions found inside web pages. A transfer itself is "
        "neither positive nor negative: classify the expected role at the new club. "
        "For goalkeepers, distinguish an announced number one, an open competition, "
        "a challenger, and credible risk that another starter will be signed. For "
        "outfield players, capture penalties, direct free kicks, corners, playmaking, "
        "offensive focal-point status, captaincy, and aerial set-piece target status "
        "only when a source supports it. Evidence must be current, player-specific, "
        "and use a URL actually found by web search. Use has_role_signal=false and "
        "an empty evidence list when the available evidence is insufficient. Never "
        "infer a role merely from price, age, fame, or prior-season points."
    )
    user_payload = {
        "task": "current club role research",
        "competition": competition,
        "season": season,
        "current_date": current_date,
        "maximum_source_age_days": 45,
        "players": targets,
    }
    return {
        "model": model,
        "reasoning": {"effort": "low"},
        "tools": [{"type": "web_search"}],
        "tool_choice": "auto",
        "include": ["web_search_call.action.sources"],
        "store": False,
        "max_output_tokens": 6000,
        "input": [
            {"role": "system", "content": instructions},
            {
                "role": "user",
                "content": json.dumps(
                    user_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "kicker_role_profiles",
                "strict": True,
                "schema": _schema(),
            }
        },
    }


def request_openai(
    payload: dict[str, Any],
    *,
    api_key: str,
    timeout: float = 120.0,
    attempts: int = 3,
) -> dict[str, Any]:
    request = urllib.request.Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
                if not isinstance(result, dict):
                    raise ValueError("OpenAI response is not an object")
                return result
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
            ValueError,
        ) as error:
            last_error = error
            retryable = not isinstance(error, urllib.error.HTTPError) or error.code in {
                408,
                409,
                429,
                500,
                502,
                503,
                504,
            }
            if not retryable or attempt + 1 >= attempts:
                break
            time.sleep(1.0 * (2**attempt))
    raise RuntimeError(f"OpenAI role research request failed: {last_error}")


def response_output_text(response: dict[str, Any]) -> str:
    for item in response.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            if content.get("type") == "refusal":
                raise RuntimeError("OpenAI role research refused the request")
            if content.get("type") == "output_text":
                text = str(content.get("text", "")).strip()
                if text:
                    return text
    direct = str(response.get("output_text", "")).strip()
    if direct:
        return direct
    raise RuntimeError("OpenAI role research returned no structured output")


def response_source_urls(response: dict[str, Any]) -> set[str]:
    urls: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"url", "source_url"} and isinstance(item, str):
                    parsed = urlparse(item)
                    if parsed.scheme == "https" and parsed.netloc:
                        urls.add(item)
                else:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    for item in response.get("output", []):
        if isinstance(item, dict) and item.get("type") in {
            "web_search_call",
            "message",
        }:
            visit(item)
    return urls


def _source_url_is_grounded(url: str, grounded_urls: set[str]) -> bool:
    if url in grounded_urls:
        return True
    parsed = urlparse(url)
    return any(
        urlparse(candidate).netloc == parsed.netloc
        and urlparse(candidate).path.rstrip("/") == parsed.path.rstrip("/")
        for candidate in grounded_urls
    )


def normalize_profile(
    raw: Any,
    *,
    target: dict[str, Any],
    grounded_urls: set[str],
    now: datetime,
    model: str,
) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not raw.get("has_role_signal"):
        return None
    if str(raw.get("player_id", "")) != str(target["player_id"]):
        return None
    designation = str(raw.get("designation", ""))
    if designation not in DESIGNATION_BOUNDS:
        return None

    evidence: list[dict[str, Any]] = []
    for item in raw.get("evidence", []):
        if not isinstance(item, dict):
            continue
        claim = str(item.get("claim", "")).strip()
        source_url = str(item.get("source_url", "")).strip()
        observed = parsed_timestamp(item.get("observed_at"))
        authority = str(item.get("source_authority", ""))
        if (
            not claim
            or len(claim) > 360
            or authority not in SOURCE_AUTHORITY
            or not _source_url_is_grounded(source_url, grounded_urls)
            or observed is None
            or observed > now + timedelta(days=1)
            or observed < now - timedelta(days=45)
        ):
            continue
        evidence.append(
            {
                "claim": claim,
                "source_url": source_url,
                "observed_at": iso_timestamp(observed),
                "source_authority": authority,
            }
        )
    if not evidence:
        return None

    strongest = max(SOURCE_AUTHORITY[item["source_authority"]] for item in evidence)
    independent_hosts = {urlparse(item["source_url"]).netloc for item in evidence}
    requested_confidence = str(raw.get("confidence", "low"))
    confidence = (
        "high"
        if requested_confidence == "high"
        and strongest >= 4
        and len(independent_hosts) >= 1
        else "medium"
        if requested_confidence in {"medium", "high"}
        and (strongest >= 3 or len(independent_hosts) >= 2)
        else "low"
    )
    contradiction = bool(raw.get("contradiction"))
    if contradiction:
        designation = "open_competition"
        confidence = "low"

    lower, upper = DESIGNATION_BOUNDS[designation]
    probability = optional_float(raw.get("expected_start_probability"))
    probability = max(lower, min(upper, probability if probability is not None else lower))
    if contradiction:
        probability = min(probability, 55.0)

    responsibilities = {
        key: str((raw.get("responsibilities") or {}).get(key, "none"))
        for key in sorted(ROLE_RESPONSIBILITIES)
    }
    if confidence == "low":
        responsibilities = {
            key: ("none" if value == "primary" else value)
            for key, value in responsibilities.items()
        }
    responsibilities = {
        key: value if value in {"none", "shared", "primary"} else "none"
        for key, value in responsibilities.items()
    }

    observed_at = max(
        parsed_timestamp(item["observed_at"]) for item in evidence
    )
    assert observed_at is not None
    refresh_days = (
        3
        if contradiction or designation == "open_competition"
        else 7
        if target["position"] == "GOALKEEPER"
        else 14
    )
    expiry_days = 30 if target["position"] == "GOALKEEPER" else 45
    external_risk = optional_float(raw.get("external_signing_risk"))
    external_risk = max(0.0, min(100.0, external_risk or 0.0))
    if target["position"] != "GOALKEEPER":
        external_risk = 0.0

    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "prompt": PROMPT_VERSION,
                "model": model,
                "target": target,
                "evidence": evidence,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "model_version": MODEL_VERSION,
        "prompt_version": PROMPT_VERSION,
        "research_model": model,
        "research_fingerprint": fingerprint,
        "designation": designation,
        "continuity": str(raw.get("continuity", "unknown")),
        "expected_start_probability": round(probability, 2),
        "team_quality_delta": 0.0,
        "external_signing_risk": round(external_risk, 2),
        "responsibilities": responsibilities,
        "confidence": confidence,
        "observed_at": iso_timestamp(observed_at),
        "refresh_after": iso_timestamp(now + timedelta(days=refresh_days)),
        "expires_at": iso_timestamp(observed_at + timedelta(days=expiry_days)),
        "fresh": observed_at <= now < observed_at + timedelta(days=expiry_days),
        "evidence": evidence,
        "note": str(raw.get("note", "")).strip()[:500],
        "contradiction": contradiction,
    }


def chunks(values: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


def research_role_profiles(
    targets: list[dict[str, Any]],
    *,
    competition: str,
    season: str,
    previous_profiles: dict[str, Any] | None,
    previous_abstentions: dict[str, Any] | None = None,
    api_key: str,
    model: str = DEFAULT_MODEL,
    now: datetime | None = None,
    batch_size: int = 4,
    requester: Callable[..., dict[str, Any]] = request_openai,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, Any],
]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    previous = previous_profiles if isinstance(previous_profiles, dict) else {}
    previous_empty = (
        previous_abstentions if isinstance(previous_abstentions, dict) else {}
    )
    profiles: dict[str, dict[str, Any]] = {}
    abstentions: dict[str, dict[str, Any]] = {}
    pending: list[dict[str, Any]] = []
    for target in targets:
        player_id = str(target["player_id"])
        cached = previous.get(player_id)
        if reusable_profile(cached, now=current, model=model):
            profiles[player_id] = dict(cached)
        elif reusable_abstention(
            previous_empty.get(player_id),
            now=current,
            model=model,
        ):
            abstentions[player_id] = dict(previous_empty[player_id])
        else:
            pending.append(target)

    failures: list[str] = []
    requests = 0
    researched = 0
    researched_abstentions = 0
    for batch in chunks(pending, max(1, min(8, batch_size))):
        completed_ids: set[str] = set()
        try:
            response = requester(
                build_request(
                    batch,
                    competition=competition,
                    season=season,
                    model=model,
                    current_date=current.date().isoformat(),
                ),
                api_key=api_key,
            )
            requests += 1
            grounded_urls = response_source_urls(response)
            parsed = json.loads(response_output_text(response))
            raw_profiles = parsed.get("profiles", [])
            by_id = {
                str(item.get("player_id", "")): item
                for item in raw_profiles
                if isinstance(item, dict)
            }
            for target in batch:
                player_id = str(target["player_id"])
                raw = by_id.get(player_id)
                if isinstance(raw, dict) and not raw.get("has_role_signal"):
                    abstentions[player_id] = abstention_record(
                        target,
                        now=current,
                        model=model,
                    )
                    completed_ids.add(player_id)
                    researched_abstentions += 1
                    continue
                normalized = normalize_profile(
                    raw,
                    target=target,
                    grounded_urls=grounded_urls,
                    now=current,
                    model=model,
                )
                if normalized:
                    profiles[player_id] = normalized
                    completed_ids.add(player_id)
                    researched += 1
        except (
            RuntimeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ) as error:
            failures.append(str(error)[:240])
        for target in batch:
            player_id = str(target["player_id"])
            if player_id in completed_ids:
                continue
            cached = previous.get(player_id)
            expires_at = (
                parsed_timestamp(cached.get("expires_at"))
                if isinstance(cached, dict)
                else None
            )
            if (
                isinstance(cached, dict)
                and cached.get("model_version") == MODEL_VERSION
                and cached.get("research_model") == model
                and cached.get("fresh", False)
                and expires_at is not None
                and current < expires_at
            ):
                profiles[player_id] = dict(cached)
                continue
            cached_empty = previous_empty.get(player_id)
            expires_at = (
                parsed_timestamp(cached_empty.get("expires_at"))
                if isinstance(cached_empty, dict)
                else None
            )
            if (
                isinstance(cached_empty, dict)
                and cached_empty.get("model_version") == MODEL_VERSION
                and cached_empty.get("research_model") == model
                and cached_empty.get("status") == "no_grounded_signal"
                and expires_at is not None
                and current < expires_at
            ):
                abstentions[player_id] = dict(cached_empty)

    return profiles, abstentions, {
        "status": (
            "ok"
            if not failures
            else "partial"
            if profiles
            else "unavailable"
        ),
        "model": model,
        "model_version": MODEL_VERSION,
        "prompt_version": PROMPT_VERSION,
        "targets": len(targets),
        "cache_hits": len(targets) - len(pending),
        "researched_profiles": researched,
        "researched_abstentions": researched_abstentions,
        "requests": requests,
        "failures": failures[:5],
    }
