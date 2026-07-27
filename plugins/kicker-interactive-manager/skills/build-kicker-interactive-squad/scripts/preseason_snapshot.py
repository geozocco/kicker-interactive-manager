#!/usr/bin/env python3
"""Validated, provider-neutral preseason evidence for Kicker projections."""

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
CONFIDENCE_LEVELS = {"low", "medium", "high"}
SIGNAL_CLASSES = {"insufficient", "negative", "neutral", "positive", "strong"}
SUMMARY_SCORES = {
    "availability_score",
    "role_score",
    "performance_score",
    "opponent_score",
    "signal_score",
    "effective_factor",
}


class PreseasonSnapshotError(ValueError):
    """Raised when preseason evidence is incomplete, stale, or malformed."""


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
        raise PreseasonSnapshotError(
            f"preseason snapshot field {field_name!r} is not ISO-8601"
        ) from error
    if parsed.tzinfo is None:
        raise PreseasonSnapshotError(
            f"preseason snapshot field {field_name!r} needs a timezone"
        )
    return parsed.astimezone(timezone.utc)


def _score(value: Any, field_name: str, player_id: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0 <= float(value) <= 100
    ):
        raise PreseasonSnapshotError(
            f"preseason {field_name} is invalid for {player_id}"
        )


def validate_snapshot(
    payload: Any,
    *,
    now: datetime | None = None,
    require_fresh: bool = True,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise PreseasonSnapshotError("preseason snapshot must be a JSON object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise PreseasonSnapshotError(
            "unsupported preseason snapshot schema version"
        )
    generated_at = parse_timestamp(payload.get("generated_at"), "generated_at")
    expires_at = parse_timestamp(payload.get("expires_at"), "expires_at")
    current = now or datetime.now(timezone.utc)
    if generated_at > current.replace(microsecond=0):
        raise PreseasonSnapshotError(
            "preseason snapshot generated_at is in the future"
        )
    if expires_at <= generated_at:
        raise PreseasonSnapshotError(
            "preseason snapshot expires_at must follow generated_at"
        )
    if require_fresh and expires_at <= current:
        raise PreseasonSnapshotError(
            f"preseason snapshot expired at {expires_at.isoformat()}"
        )
    for field_name in ("competition", "season"):
        if not str(payload.get(field_name, "")).strip():
            raise PreseasonSnapshotError(
                f"preseason snapshot field {field_name!r} is missing"
            )
    window = payload.get("window")
    if not isinstance(window, dict):
        raise PreseasonSnapshotError("preseason window is missing")
    try:
        start = datetime.fromisoformat(str(window["from"]))
        end = datetime.fromisoformat(str(window["to"]))
        season_start = datetime.fromisoformat(str(window["season_start"]))
    except (KeyError, ValueError) as error:
        raise PreseasonSnapshotError("preseason window dates are invalid") from error
    if end < start or season_start < start:
        raise PreseasonSnapshotError("preseason window order is invalid")
    for field_name in ("decay_days", "post_start_decay_days"):
        value = window.get(field_name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise PreseasonSnapshotError(
                f"preseason window {field_name!r} is invalid"
            )
    providers = payload.get("providers")
    if not isinstance(providers, dict) or not providers:
        raise PreseasonSnapshotError("preseason providers are missing")
    players = payload.get("players")
    if not isinstance(players, dict):
        raise PreseasonSnapshotError("preseason players must be an object")
    for player_id, player in players.items():
        if not str(player_id).strip() or not isinstance(player, dict):
            raise PreseasonSnapshotError(
                "preseason snapshot contains an invalid player"
            )
        observations = player.get("observations")
        if not isinstance(observations, list):
            raise PreseasonSnapshotError(
                f"preseason observations are invalid for {player_id}"
            )
        for observation in observations:
            if not isinstance(observation, dict):
                raise PreseasonSnapshotError(
                    f"preseason observation is invalid for {player_id}"
                )
            try:
                datetime.fromisoformat(str(observation["date"]))
            except (KeyError, ValueError) as error:
                raise PreseasonSnapshotError(
                    f"preseason observation date is invalid for {player_id}"
                ) from error
            if observation.get("confidence") not in CONFIDENCE_LEVELS:
                raise PreseasonSnapshotError(
                    f"preseason observation confidence is invalid for {player_id}"
                )
            source_url = str(observation.get("source_url", ""))
            if source_url and not source_url.startswith("https://"):
                raise PreseasonSnapshotError(
                    f"preseason observation source is invalid for {player_id}"
                )
        summary = player.get("summary")
        if not isinstance(summary, dict):
            raise PreseasonSnapshotError(
                f"preseason summary is missing for {player_id}"
            )
        for field_name in SUMMARY_SCORES:
            _score(summary.get(field_name), field_name, str(player_id))
        if "training_score" in summary:
            _score(
                summary.get("training_score"),
                "training_score",
                str(player_id),
            )
        if summary.get("confidence") not in CONFIDENCE_LEVELS:
            raise PreseasonSnapshotError(
                f"preseason confidence is invalid for {player_id}"
            )
        if summary.get("classification") not in SIGNAL_CLASSES:
            raise PreseasonSnapshotError(
                f"preseason classification is invalid for {player_id}"
            )
        if (
            "latest_training_status" in summary
            and summary.get("latest_training_status") not in {
            "full",
            "partial",
            "absent",
            "unknown",
            }
        ):
            raise PreseasonSnapshotError(
                f"preseason latest training status is invalid for {player_id}"
            )
        if "latest_observation_date" in summary:
            try:
                datetime.fromisoformat(str(summary["latest_observation_date"]))
            except ValueError as error:
                raise PreseasonSnapshotError(
                    f"preseason latest observation date is invalid for {player_id}"
                ) from error
        for field_name in (
            "team_match_count",
            "appearances",
            "starts",
            "minutes",
            "goals",
            "assists",
            "official_source_count",
        ):
            value = summary.get(field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or float(value) < 0
            ):
                raise PreseasonSnapshotError(
                    f"preseason {field_name} is invalid for {player_id}"
                )
    expected_hash = str(payload.get("content_sha256", "")).strip()
    if not expected_hash or expected_hash != canonical_sha256(payload):
        raise PreseasonSnapshotError(
            "preseason snapshot content_sha256 does not match its content"
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
        raise PreseasonSnapshotError(
            "remote preseason snapshots require HTTPS"
        )
    headers = {
        "Accept": "application/json",
        "User-Agent": "kicker-interactive-manager-preseason-client/1",
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
                raw = response.read(10_000_001)
                if len(raw) > 10_000_000:
                    raise PreseasonSnapshotError(
                        "central preseason snapshot exceeds 10 MB"
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
    raise PreseasonSnapshotError(
        f"could not load central preseason snapshot: {last_error}"
    )


def load_snapshot(
    location: str | Path,
    *,
    token_env: str = "KICKER_PRESEASON_FEED_TOKEN",
    timeout: float = 15.0,
    now: datetime | None = None,
    require_fresh: bool = True,
) -> dict[str, Any]:
    location_text = str(location)
    if location_text.startswith(("https://", "http://")):
        token = os.environ.get(token_env, "").strip() or None
        raw = _read_url(
            location_text,
            bearer_token=token,
            timeout=timeout,
        )
    else:
        raw = Path(location_text).read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PreseasonSnapshotError(
            "preseason snapshot is not valid UTF-8 JSON"
        ) from error
    return validate_snapshot(
        payload,
        now=now,
        require_fresh=require_fresh,
    )
