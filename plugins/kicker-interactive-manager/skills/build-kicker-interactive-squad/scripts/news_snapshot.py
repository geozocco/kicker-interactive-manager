#!/usr/bin/env python3
"""Provider-neutral news snapshot helpers for the Kicker squad optimizer."""

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
CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}
ALLOWED_SIGNAL_KINDS = {
    "injury",
    "suspension",
    "transfer_confirmed",
    "transfer_rumour",
    "lineup",
}
ALLOWED_SIGNAL_STATUS = {
    "confirmed",
    "questionable",
    "rumour",
    "cleared",
}


class NewsSnapshotError(ValueError):
    """Raised when a snapshot is unsafe or cannot be loaded."""


def parse_timestamp(value: Any, field_name: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise NewsSnapshotError(f"news snapshot field '{field_name}' is missing")
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise NewsSnapshotError(
            f"news snapshot field '{field_name}' is not an ISO-8601 timestamp"
        ) from error
    if parsed.tzinfo is None:
        raise NewsSnapshotError(
            f"news snapshot field '{field_name}' must include a timezone"
        )
    return parsed.astimezone(timezone.utc)


def canonical_sha256(payload: dict[str, Any]) -> str:
    hashable = {
        key: value
        for key, value in payload.items()
        if key != "content_sha256"
    }
    canonical = json.dumps(
        hashable,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def validate_snapshot(
    payload: Any,
    *,
    now: datetime | None = None,
    require_fresh: bool = True,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise NewsSnapshotError("news snapshot must be a JSON object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise NewsSnapshotError(
            f"unsupported news snapshot schema_version: {payload.get('schema_version')!r}"
        )
    generated_at = parse_timestamp(payload.get("generated_at"), "generated_at")
    expires_at = parse_timestamp(payload.get("expires_at"), "expires_at")
    if expires_at <= generated_at:
        raise NewsSnapshotError("news snapshot expires_at must follow generated_at")
    current = now or datetime.now(timezone.utc)
    if generated_at > current.replace(microsecond=0):
        raise NewsSnapshotError("news snapshot generated_at is in the future")
    if require_fresh and expires_at <= current:
        raise NewsSnapshotError(
            f"news snapshot expired at {expires_at.isoformat()}"
        )
    if not str(payload.get("competition", "")).strip():
        raise NewsSnapshotError("news snapshot competition is missing")
    if not str(payload.get("season", "")).strip():
        raise NewsSnapshotError("news snapshot season is missing")
    providers = payload.get("providers")
    if not isinstance(providers, dict) or not providers:
        raise NewsSnapshotError("news snapshot providers must be a non-empty object")
    players = payload.get("players")
    if not isinstance(players, dict):
        raise NewsSnapshotError("news snapshot players must be an object")

    for kicker_id, player in players.items():
        if not str(kicker_id).strip() or not isinstance(player, dict):
            raise NewsSnapshotError("news snapshot contains an invalid player entry")
        signals = player.get("signals", [])
        if not isinstance(signals, list):
            raise NewsSnapshotError(
                f"news signals for player {kicker_id!r} must be a list"
            )
        for signal in signals:
            if not isinstance(signal, dict):
                raise NewsSnapshotError(
                    f"news signal for player {kicker_id!r} must be an object"
                )
            if signal.get("kind") not in ALLOWED_SIGNAL_KINDS:
                raise NewsSnapshotError(
                    f"unsupported news signal kind for player {kicker_id!r}"
                )
            if signal.get("status") not in ALLOWED_SIGNAL_STATUS:
                raise NewsSnapshotError(
                    f"unsupported news signal status for player {kicker_id!r}"
                )
            severity = signal.get("severity")
            if (
                isinstance(severity, bool)
                or not isinstance(severity, (int, float))
                or not 0 <= float(severity) <= 100
            ):
                raise NewsSnapshotError(
                    f"news signal severity for player {kicker_id!r} must be 0..100"
                )
            parse_timestamp(signal.get("observed_at"), "signal.observed_at")
            if not str(signal.get("source_provider", "")).strip():
                raise NewsSnapshotError(
                    f"news signal source_provider for player {kicker_id!r} is missing"
                )
        mapping = player.get("mapping", {})
        if not isinstance(mapping, dict):
            raise NewsSnapshotError(
                f"news mapping for player {kicker_id!r} must be an object"
            )
        if mapping.get("confidence", "unverified") not in {
            "unverified",
            "low",
            "medium",
            "high",
            "verified",
        }:
            raise NewsSnapshotError(
                f"invalid mapping confidence for player {kicker_id!r}"
            )
        age = mapping.get("age")
        if age is not None and (
            isinstance(age, bool)
            or not isinstance(age, int)
            or not 15 <= age <= 50
        ):
            raise NewsSnapshotError(
                f"invalid player age for player {kicker_id!r}"
            )
        position = mapping.get("position")
        if position is not None and (
            not isinstance(position, str) or len(position.strip()) > 80
        ):
            raise NewsSnapshotError(
                f"invalid player position for player {kicker_id!r}"
            )
        consensus = player.get("consensus", {})
        if not isinstance(consensus, dict):
            raise NewsSnapshotError(
                f"news consensus for player {kicker_id!r} must be an object"
            )
        confidence = consensus.get("confidence", "low")
        if confidence not in CONFIDENCE_ORDER:
            raise NewsSnapshotError(
                f"invalid news confidence for player {kicker_id!r}"
            )
        for key in ("injury", "transfer", "rotation", "fitness_cap"):
            value = consensus.get(key, 0 if key != "fitness_cap" else 100)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not 0 <= float(value) <= 100
            ):
                raise NewsSnapshotError(
                    f"news consensus {key!r} for player {kicker_id!r} must be 0..100"
                )
        conflicts = consensus.get("conflicts", [])
        if not isinstance(conflicts, list):
            raise NewsSnapshotError(
                f"news conflicts for player {kicker_id!r} must be a list"
            )
    role_profiles = payload.get("role_profiles", {})
    if not isinstance(role_profiles, dict):
        raise NewsSnapshotError("news role_profiles must be an object")
    for player_id, profile in role_profiles.items():
        if not str(player_id).strip() or not isinstance(profile, dict):
            raise NewsSnapshotError("news snapshot contains an invalid role profile")
        if profile.get("designation") not in {
            "confirmed_starter",
            "key_starter",
            "expected_starter",
            "immediate_help",
            "open_competition",
            "rotation",
            "perspective",
        }:
            raise NewsSnapshotError(
                f"invalid role designation for player {player_id!r}"
            )
        probability = profile.get("expected_start_probability")
        if (
            isinstance(probability, bool)
            or not isinstance(probability, (int, float))
            or not 0 <= float(probability) <= 100
        ):
            raise NewsSnapshotError(
                f"invalid role probability for player {player_id!r}"
            )
        if profile.get("confidence") not in CONFIDENCE_ORDER:
            raise NewsSnapshotError(
                f"invalid role confidence for player {player_id!r}"
            )
        observed_at = parse_timestamp(
            profile.get("observed_at"),
            "role_profile.observed_at",
        )
        role_expires_at = parse_timestamp(
            profile.get("expires_at"),
            "role_profile.expires_at",
        )
        if role_expires_at <= observed_at:
            raise NewsSnapshotError(
                f"role profile expiry must follow observation for {player_id!r}"
            )
        if not isinstance(profile.get("fresh"), bool):
            raise NewsSnapshotError(
                f"role profile freshness is invalid for {player_id!r}"
            )
        evidence = profile.get("evidence", [])
        if not isinstance(evidence, list) or not evidence:
            raise NewsSnapshotError(
                f"role profile evidence is missing for {player_id!r}"
            )
        for item in evidence:
            if (
                not isinstance(item, dict)
                or not str(item.get("claim", "")).strip()
                or not str(item.get("source_url", "")).startswith("https://")
            ):
                raise NewsSnapshotError(
                    f"invalid role evidence for player {player_id!r}"
                )
            parse_timestamp(
                item.get("observed_at"),
                "role_profile.evidence.observed_at",
            )
    expected_hash = str(payload.get("content_sha256", "")).strip()
    if expected_hash and expected_hash != canonical_sha256(payload):
        raise NewsSnapshotError("news snapshot content_sha256 does not match its content")
    return payload


def _read_url(
    url: str,
    *,
    bearer_token: str | None,
    timeout: float,
    attempts: int = 3,
) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise NewsSnapshotError("remote news snapshots require HTTPS")
    headers = {
        "Accept": "application/json",
        "User-Agent": "kicker-interactive-manager-news-client/1",
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
                return response.read()
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
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
    raise NewsSnapshotError(f"could not load central news snapshot: {last_error}")


def load_snapshot(
    location: str | Path,
    *,
    token_env: str = "KICKER_NEWS_FEED_TOKEN",
    timeout: float = 15.0,
    now: datetime | None = None,
    require_fresh: bool = True,
) -> dict[str, Any]:
    location_text = str(location)
    if location_text.startswith(("https://", "http://")):
        token = os.environ.get(token_env, "").strip() or None
        raw = _read_url(location_text, bearer_token=token, timeout=timeout)
    else:
        raw = Path(location_text).read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NewsSnapshotError("news snapshot is not valid UTF-8 JSON") from error
    return validate_snapshot(payload, now=now, require_fresh=require_fresh)


def snapshot_audit(payload: dict[str, Any]) -> dict[str, Any]:
    providers = payload.get("providers", {})
    player_entries = payload.get("players", {})
    conflicts = {
        kicker_id: list(entry.get("consensus", {}).get("conflicts", []))
        for kicker_id, entry in player_entries.items()
        if entry.get("consensus", {}).get("conflicts")
    }
    return {
        "status": "fresh",
        "schema_version": payload["schema_version"],
        "competition": payload["competition"],
        "season": payload["season"],
        "generated_at": payload["generated_at"],
        "expires_at": payload["expires_at"],
        "sha256": canonical_sha256(payload),
        "providers": providers,
        "player_count": len(player_entries),
        "signal_count": sum(
            len(entry.get("signals", [])) for entry in player_entries.values()
        ),
        "conflicts": conflicts,
    }
