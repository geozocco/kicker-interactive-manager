#!/usr/bin/env python3
"""Validated longitudinal Kicker price, points, and grade snapshots."""

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
POSITIONS = {"GOALKEEPER", "DEFENDER", "MIDFIELDER", "FORWARD"}


class KickerHistorySnapshotError(ValueError):
    """Raised when a longitudinal Kicker snapshot cannot be trusted."""


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
        raise KickerHistorySnapshotError(
            f"kicker history field {field_name!r} is not ISO-8601"
        ) from error
    if parsed.tzinfo is None:
        raise KickerHistorySnapshotError(
            f"kicker history field {field_name!r} needs a timezone"
        )
    return parsed.astimezone(timezone.utc)


def validate_snapshot(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise KickerHistorySnapshotError(
            "kicker history snapshot must be a JSON object"
        )
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise KickerHistorySnapshotError(
            "unsupported kicker history schema version"
        )
    parse_timestamp(payload.get("generated_at"), "generated_at")
    for field_name in ("competition", "season", "market_sha256"):
        if not str(payload.get(field_name, "")).strip():
            raise KickerHistorySnapshotError(
                f"kicker history field {field_name!r} is missing"
            )
    source = payload.get("source")
    if (
        not isinstance(source, dict)
        or source.get("provider") != "kicker"
        or not str(source.get("url", "")).startswith("https://")
    ):
        raise KickerHistorySnapshotError("kicker history source is invalid")
    players = payload.get("players")
    if not isinstance(players, dict) or not players:
        raise KickerHistorySnapshotError(
            "kicker history players must be a non-empty object"
        )
    for player_id, player in players.items():
        if not str(player_id).strip() or not isinstance(player, dict):
            raise KickerHistorySnapshotError(
                "kicker history contains an invalid player"
            )
        if (
            not str(player.get("name", "")).strip()
            or not str(player.get("club", "")).strip()
            or player.get("position") not in POSITIONS
        ):
            raise KickerHistorySnapshotError(
                f"kicker history identity is invalid for {player_id}"
            )
        observations = player.get("observations")
        if not isinstance(observations, list) or not observations:
            raise KickerHistorySnapshotError(
                f"kicker history observations are missing for {player_id}"
            )
        dates: list[str] = []
        for observation in observations:
            if not isinstance(observation, dict):
                raise KickerHistorySnapshotError(
                    f"kicker history observation is invalid for {player_id}"
                )
            observed_on = str(observation.get("observed_on", ""))
            try:
                datetime.strptime(observed_on, "%Y-%m-%d")
            except ValueError as error:
                raise KickerHistorySnapshotError(
                    f"kicker history date is invalid for {player_id}"
                ) from error
            dates.append(observed_on)
            market_value = observation.get("market_value")
            if (
                isinstance(market_value, bool)
                or not isinstance(market_value, int)
                or market_value <= 0
            ):
                raise KickerHistorySnapshotError(
                    f"kicker history market value is invalid for {player_id}"
                )
            for field_name in ("points", "average_grade"):
                value = observation.get(field_name)
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                ):
                    raise KickerHistorySnapshotError(
                        f"kicker history {field_name} is invalid for {player_id}"
                    )
        if dates != sorted(set(dates)):
            raise KickerHistorySnapshotError(
                f"kicker history dates are not unique and ordered for {player_id}"
            )
    expected_hash = str(payload.get("content_sha256", "")).strip()
    if not expected_hash or expected_hash != canonical_sha256(payload):
        raise KickerHistorySnapshotError(
            "kicker history content_sha256 does not match its content"
        )
    return payload


def _read_url(url: str, *, timeout: float, attempts: int = 3) -> bytes:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        and parsed.hostname not in {"127.0.0.1", "localhost"}
    ):
        raise KickerHistorySnapshotError(
            "remote kicker history snapshots require HTTPS"
        )
    headers = {
        "Accept": "application/json",
        "User-Agent": "kicker-interactive-manager-kicker-history-client/1",
    }
    token = os.environ.get("KICKER_HISTORY_FEED_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, headers=headers),
                timeout=timeout,
            ) as response:
                raw = response.read(20_000_001)
                if len(raw) > 20_000_000:
                    raise KickerHistorySnapshotError(
                        "central kicker history exceeds 20 MB"
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
    raise KickerHistorySnapshotError(
        f"could not load central kicker history: {last_error}"
    )


def load_snapshot(
    location: str | Path,
    *,
    timeout: float = 15.0,
) -> dict[str, Any]:
    location_text = str(location)
    raw = (
        _read_url(location_text, timeout=timeout)
        if location_text.startswith(("https://", "http://"))
        else Path(location_text).read_bytes()
    )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise KickerHistorySnapshotError(
            "kicker history is not valid UTF-8 JSON"
        ) from error
    return validate_snapshot(payload)


def snapshot_audit(payload: dict[str, Any]) -> dict[str, Any]:
    observations = [
        observation
        for player in payload["players"].values()
        for observation in player["observations"]
    ]
    return {
        "schema_version": payload["schema_version"],
        "competition": payload["competition"],
        "season": payload["season"],
        "generated_at": payload["generated_at"],
        "sha256": canonical_sha256(payload),
        "player_count": len(payload["players"]),
        "observation_count": len(observations),
        "first_observed_on": min(
            item["observed_on"] for item in observations
        ),
        "last_observed_on": max(
            item["observed_on"] for item in observations
        ),
    }
