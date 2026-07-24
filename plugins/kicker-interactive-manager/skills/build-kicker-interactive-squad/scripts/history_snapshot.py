#!/usr/bin/env python3
"""Validated Transfermarkt career-history snapshots for Kicker players."""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


SCHEMA_VERSION = 1
MAPPING_STATUSES = {"verified", "probable", "unmatched", "ambiguous"}


class HistorySnapshotError(ValueError):
    """Raised when a career-history snapshot cannot be trusted."""


def canonical_sha256(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        {
            key: value
            for key, value in payload.items()
            if key != "content_sha256"
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def parse_timestamp(value: Any, field_name: str) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise HistorySnapshotError(
            f"history snapshot field {field_name!r} is not ISO-8601"
        ) from error
    if parsed.tzinfo is None:
        raise HistorySnapshotError(
            f"history snapshot field {field_name!r} needs a timezone"
        )
    return parsed.astimezone(timezone.utc)


def _non_negative_number(value: Any, field_name: str, player_id: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or float(value) < 0
    ):
        raise HistorySnapshotError(
            f"history {field_name} is invalid for {player_id}"
        )
    return float(value)


def _validate_mapping(
    mapping: Any,
    *,
    player_id: str,
) -> str:
    if not isinstance(mapping, dict):
        raise HistorySnapshotError(
            f"history mapping is missing for {player_id}"
        )
    status = str(mapping.get("status", ""))
    if status not in MAPPING_STATUSES:
        raise HistorySnapshotError(
            f"history mapping status is invalid for {player_id}"
        )
    transfermarkt_id = mapping.get("transfermarkt_player_id")
    if status in {"verified", "probable"}:
        if (
            isinstance(transfermarkt_id, bool)
            or not isinstance(transfermarkt_id, int)
            or transfermarkt_id <= 0
        ):
            raise HistorySnapshotError(
                f"history Transfermarkt player id is invalid for {player_id}"
            )
        if not str(mapping.get("transfermarkt_name", "")).strip():
            raise HistorySnapshotError(
                f"history Transfermarkt name is missing for {player_id}"
            )
        if not str(mapping.get("profile_url", "")).startswith("https://"):
            raise HistorySnapshotError(
                f"history profile URL is invalid for {player_id}"
            )
    elif transfermarkt_id is not None:
        raise HistorySnapshotError(
            f"unresolved history mapping contains a player id for {player_id}"
        )
    return status


def _validate_seasons(
    seasons: Any,
    *,
    player_id: str,
) -> None:
    if not isinstance(seasons, list):
        raise HistorySnapshotError(
            f"history seasons are invalid for {player_id}"
        )
    seen: set[int] = set()
    for season in seasons:
        if not isinstance(season, dict):
            raise HistorySnapshotError(
                f"history season entry is invalid for {player_id}"
            )
        season_id = season.get("season")
        if (
            isinstance(season_id, bool)
            or not isinstance(season_id, int)
            or season_id < 1900
            or season_id in seen
        ):
            raise HistorySnapshotError(
                f"history season id is invalid for {player_id}"
            )
        seen.add(season_id)
        for field_name in (
            "appearances",
            "starts",
            "minutes",
            "goals",
            "assists",
            "level_adjusted_minutes",
            "comparable_minutes",
        ):
            _non_negative_number(
                season.get(field_name),
                field_name,
                player_id,
            )
        if not isinstance(season.get("proven"), bool):
            raise HistorySnapshotError(
                f"history proven flag is invalid for {player_id}"
            )
        competitions = season.get("competitions")
        if not isinstance(competitions, list):
            raise HistorySnapshotError(
                f"history competitions are invalid for {player_id}"
            )
        for competition in competitions:
            if (
                not isinstance(competition, dict)
                or not str(competition.get("competition_id", "")).strip()
                or not str(competition.get("kind", "")).strip()
                or not isinstance(competition.get("rated"), bool)
            ):
                raise HistorySnapshotError(
                    f"history competition is invalid for {player_id}"
                )
            _non_negative_number(
                competition.get("strength_factor"),
                "strength_factor",
                player_id,
            )
            for field_name in (
                "appearances",
                "starts",
                "minutes",
                "goals",
                "assists",
            ):
                _non_negative_number(
                    competition.get(field_name),
                    field_name,
                    player_id,
                )


def validate_snapshot(
    payload: Any,
    *,
    now: datetime | None = None,
    require_fresh: bool = True,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise HistorySnapshotError("history snapshot must be a JSON object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise HistorySnapshotError("unsupported history snapshot schema version")
    generated_at = parse_timestamp(payload.get("generated_at"), "generated_at")
    expires_at = parse_timestamp(payload.get("expires_at"), "expires_at")
    current = now or datetime.now(timezone.utc)
    if generated_at > current.replace(microsecond=0):
        raise HistorySnapshotError(
            "history snapshot generated_at is in the future"
        )
    if expires_at <= generated_at:
        raise HistorySnapshotError(
            "history snapshot expires_at must follow generated_at"
        )
    if require_fresh and expires_at <= current:
        raise HistorySnapshotError(
            f"history snapshot expired at {expires_at.isoformat()}"
        )
    for field_name in (
        "competition",
        "season",
        "market_sha256",
        "model_version",
        "strength_model_sha256",
    ):
        if not str(payload.get(field_name, "")).strip():
            raise HistorySnapshotError(
                f"history snapshot field {field_name!r} is missing"
            )
    target_strength = _non_negative_number(
        payload.get("target_strength"),
        "target_strength",
        "snapshot",
    )
    if target_strength <= 0:
        raise HistorySnapshotError(
            "history snapshot target_strength must be positive"
        )

    players = payload.get("players")
    if not isinstance(players, dict):
        raise HistorySnapshotError(
            "history snapshot players must be an object"
        )
    resolved_count = 0
    for player_id, player in players.items():
        if not str(player_id).strip() or not isinstance(player, dict):
            raise HistorySnapshotError(
                "history snapshot contains an invalid player"
            )
        for field_name in ("name", "club", "position"):
            if not str(player.get(field_name, "")).strip():
                raise HistorySnapshotError(
                    f"history {field_name} is missing for {player_id}"
                )
        status = _validate_mapping(
            player.get("mapping"),
            player_id=str(player_id),
        )
        _validate_seasons(player.get("seasons"), player_id=str(player_id))
        career = player.get("career")
        if not isinstance(career, dict):
            raise HistorySnapshotError(
                f"history career is missing for {player_id}"
            )
        for field_name in (
            "appearances",
            "starts",
            "minutes",
            "goals",
            "assists",
            "level_adjusted_minutes",
            "comparable_minutes",
            "proven_seasons",
            "confirmed_score",
            "recent_minutes_score",
            "role_score",
        ):
            _non_negative_number(
                career.get(field_name),
                field_name,
                str(player_id),
            )
        if float(career["confirmed_score"]) > 100:
            raise HistorySnapshotError(
                f"history confirmed_score is invalid for {player_id}"
            )
        if float(career["recent_minutes_score"]) > 100:
            raise HistorySnapshotError(
                f"history recent_minutes_score is invalid for {player_id}"
            )
        if float(career["role_score"]) > 100:
            raise HistorySnapshotError(
                f"history role_score is invalid for {player_id}"
            )
        retrieved_at = player.get("retrieved_at")
        if status in {"verified", "probable"}:
            parse_timestamp(retrieved_at, f"players.{player_id}.retrieved_at")
            resolved_count += 1
        elif retrieved_at is not None or player["seasons"]:
            raise HistorySnapshotError(
                f"unresolved history player contains performance data: {player_id}"
            )

    requirements = payload.get("requirements")
    if not isinstance(requirements, dict):
        raise HistorySnapshotError(
            "history snapshot requirements must be an object"
        )
    player_count = requirements.get("player_count")
    minimum_resolved_percent = requirements.get("minimum_resolved_percent")
    if (
        isinstance(player_count, bool)
        or not isinstance(player_count, int)
        or player_count != len(players)
    ):
        raise HistorySnapshotError(
            "history snapshot player_count does not cover the market inventory"
        )
    if (
        isinstance(minimum_resolved_percent, bool)
        or not isinstance(minimum_resolved_percent, (int, float))
        or not 0 <= float(minimum_resolved_percent) <= 100
    ):
        raise HistorySnapshotError(
            "history snapshot minimum_resolved_percent is invalid"
        )
    resolved_percent = 100.0 * resolved_count / max(1, len(players))
    if resolved_percent < float(minimum_resolved_percent):
        raise HistorySnapshotError(
            "history snapshot resolved coverage is too low: "
            f"required={minimum_resolved_percent}, actual={resolved_percent:.2f}"
        )
    expected_hash = str(payload.get("content_sha256", "")).strip()
    if not expected_hash or expected_hash != canonical_sha256(payload):
        raise HistorySnapshotError(
            "history snapshot content_sha256 does not match its content"
        )
    return payload


def _read_url(
    url: str,
    *,
    bearer_token: str | None,
    timeout: float,
    attempts: int = 3,
) -> bytes:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        and parsed.hostname not in {"127.0.0.1", "localhost"}
    ):
        raise HistorySnapshotError("remote history snapshots require HTTPS")
    headers = {
        "Accept": "application/json",
        "User-Agent": "kicker-interactive-manager-history-client/1",
    }
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, headers=headers),
                timeout=timeout,
            ) as response:
                raw = response.read(40_000_001)
                if len(raw) > 40_000_000:
                    raise HistorySnapshotError(
                        "central history snapshot exceeds 40 MB"
                    )
                return raw
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
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
                time.sleep(0.5 * (2**attempt))
    raise HistorySnapshotError(
        f"could not load central history snapshot: {last_error}"
    )


def load_snapshot(
    location: str | Path,
    *,
    token_env: str = "KICKER_HISTORY_FEED_TOKEN",
    timeout: float = 30.0,
    now: datetime | None = None,
    require_fresh: bool = True,
) -> dict[str, Any]:
    location_text = str(location)
    if location_text.startswith(("https://", "http://")):
        raw = _read_url(
            location_text,
            bearer_token=os.environ.get(token_env, "").strip() or None,
            timeout=timeout,
        )
    else:
        raw = Path(location_text).read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HistorySnapshotError(
            "history snapshot is not valid UTF-8 JSON"
        ) from error
    return validate_snapshot(
        payload,
        now=now,
        require_fresh=require_fresh,
    )


def snapshot_audit(payload: dict[str, Any]) -> dict[str, Any]:
    resolved = [
        player
        for player in payload["players"].values()
        if player["mapping"]["status"] in {"verified", "probable"}
    ]
    return {
        "status": "fresh",
        "schema_version": payload["schema_version"],
        "competition": payload["competition"],
        "season": payload["season"],
        "generated_at": payload["generated_at"],
        "expires_at": payload["expires_at"],
        "sha256": canonical_sha256(payload),
        "market_sha256": payload["market_sha256"],
        "model_version": payload["model_version"],
        "target_strength": payload["target_strength"],
        "player_count": len(payload["players"]),
        "resolved_player_count": len(resolved),
        "resolved_percent": round(
            100.0 * len(resolved) / max(1, len(payload["players"])),
            2,
        ),
        "proven_player_count": sum(
            int(player["career"]["proven_seasons"]) >= 2
            for player in resolved
        ),
        "requirements": payload["requirements"],
    }
