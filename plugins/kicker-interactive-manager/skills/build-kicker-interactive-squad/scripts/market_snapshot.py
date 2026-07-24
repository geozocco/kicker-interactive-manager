#!/usr/bin/env python3
"""Validated central market snapshots for the Kicker squad tools."""

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


class MarketSnapshotError(ValueError):
    """Raised when a central market snapshot cannot be trusted."""


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


def parse_timestamp(value: Any, field_name: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise MarketSnapshotError(
            f"market snapshot field '{field_name}' is missing"
        )
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise MarketSnapshotError(
            f"market snapshot field '{field_name}' is not ISO-8601"
        ) from error
    if parsed.tzinfo is None:
        raise MarketSnapshotError(
            f"market snapshot field '{field_name}' must include a timezone"
        )
    return parsed.astimezone(timezone.utc)


def validate_snapshot(
    payload: Any,
    *,
    now: datetime | None = None,
    require_fresh: bool = True,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise MarketSnapshotError("market snapshot must be a JSON object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise MarketSnapshotError(
            "unsupported market snapshot schema_version: "
            f"{payload.get('schema_version')!r}"
        )
    generated_at = parse_timestamp(payload.get("generated_at"), "generated_at")
    expires_at = parse_timestamp(payload.get("expires_at"), "expires_at")
    current = now or datetime.now(timezone.utc)
    if expires_at <= generated_at:
        raise MarketSnapshotError(
            "market snapshot expires_at must follow generated_at"
        )
    if generated_at > current.replace(microsecond=0):
        raise MarketSnapshotError("market snapshot generated_at is in the future")
    if require_fresh and expires_at <= current:
        raise MarketSnapshotError(
            f"market snapshot expired at {expires_at.isoformat()}"
        )
    if not str(payload.get("competition", "")).strip():
        raise MarketSnapshotError("market snapshot competition is missing")
    if not str(payload.get("season", "")).strip():
        raise MarketSnapshotError("market snapshot season is missing")

    source = payload.get("source")
    if not isinstance(source, dict):
        raise MarketSnapshotError("market snapshot source must be an object")
    source_url = str(source.get("url", "")).strip()
    parsed_source = urlparse(source_url)
    if (
        parsed_source.scheme != "https"
        or parsed_source.hostname not in {
            "kicker-libero.de",
            "www.kicker-libero.de",
        }
        or not parsed_source.path.startswith(
            "/api/sportsdata/v1/players-details/"
        )
        or not parsed_source.path.endswith(".csv")
    ):
        raise MarketSnapshotError(
            "market snapshot source must be an official Kicker HTTPS URL"
        )
    source_hash = str(source.get("csv_sha256", "")).strip()
    if len(source_hash) != 64 or any(
        character not in "0123456789abcdef" for character in source_hash
    ):
        raise MarketSnapshotError("market snapshot source csv_sha256 is invalid")

    players = payload.get("players")
    if not isinstance(players, list) or not players:
        raise MarketSnapshotError(
            "market snapshot players must be a non-empty list"
        )
    ids: set[str] = set()
    clubs: set[str] = set()
    for player in players:
        if not isinstance(player, dict):
            raise MarketSnapshotError(
                "market snapshot contains an invalid player entry"
            )
        player_id = str(player.get("id", "")).strip()
        name = str(player.get("name", "")).strip()
        club = str(player.get("club", "")).strip()
        position = str(player.get("position", "")).strip()
        market_value = player.get("market_value")
        available = player.get("available", True)
        if not player_id or player_id in ids:
            raise MarketSnapshotError(
                "market snapshot contains a missing or duplicate player id"
            )
        if not name or not club:
            raise MarketSnapshotError(
                f"market snapshot player {player_id!r} lacks name or club"
            )
        if position not in POSITIONS:
            raise MarketSnapshotError(
                f"market snapshot player {player_id!r} has invalid position"
            )
        if (
            isinstance(market_value, bool)
            or not isinstance(market_value, int)
            or market_value <= 0
        ):
            raise MarketSnapshotError(
                f"market snapshot player {player_id!r} has invalid market_value"
            )
        if not isinstance(available, bool):
            raise MarketSnapshotError(
                f"market snapshot player {player_id!r} has invalid availability"
            )
        for numeric_field in ("points", "average_grade"):
            value = player.get(numeric_field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise MarketSnapshotError(
                    f"market snapshot player {player_id!r} has invalid "
                    f"{numeric_field}"
                )
        ids.add(player_id)
        clubs.add(club)

    expected_team_count = payload.get("expected_team_count")
    if (
        isinstance(expected_team_count, bool)
        or not isinstance(expected_team_count, int)
        or expected_team_count < 1
        or len(clubs) != expected_team_count
    ):
        raise MarketSnapshotError(
            "market snapshot club count does not match expected_team_count"
        )
    annotations = payload.get("annotations", {})
    if not isinstance(annotations, dict):
        raise MarketSnapshotError("market snapshot annotations must be an object")
    unknown_annotation_ids = set(annotations) - ids
    if unknown_annotation_ids:
        raise MarketSnapshotError(
            "market snapshot annotations contain unknown player ids"
        )
    if any(not isinstance(value, dict) for value in annotations.values()):
        raise MarketSnapshotError(
            "market snapshot annotations must contain objects"
        )

    expected_hash = str(payload.get("content_sha256", "")).strip()
    if not expected_hash or expected_hash != canonical_sha256(payload):
        raise MarketSnapshotError(
            "market snapshot content_sha256 does not match its content"
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
        raise MarketSnapshotError("remote market snapshots require HTTPS")
    headers = {
        "Accept": "application/json",
        "User-Agent": "kicker-interactive-manager-market-client/1",
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
                    raise MarketSnapshotError(
                        "central market snapshot exceeds 10 MB"
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
    raise MarketSnapshotError(
        f"could not load central market snapshot: {last_error}"
    )


def load_snapshot(
    location: str | Path,
    *,
    token_env: str = "KICKER_MARKET_FEED_TOKEN",
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
        raise MarketSnapshotError(
            "market snapshot is not valid UTF-8 JSON"
        ) from error
    return validate_snapshot(
        payload,
        now=now,
        require_fresh=require_fresh,
    )


def csv_rows(payload: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "ID": str(player["id"]),
            "Angezeigter Name (kurz)": str(player.get("short_name", "")),
            "Angezeigter Name": str(player["name"]),
            "Verein": str(player["club"]),
            "Position": str(player["position"]),
            "Marktwert": str(player["market_value"]),
            "Punkte": str(player["points"]),
            "Notendurchschnitt": str(player["average_grade"]),
        }
        for player in payload["players"]
        if player.get("available", True)
    ]


def snapshot_audit(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "fresh",
        "schema_version": payload["schema_version"],
        "competition": payload["competition"],
        "season": payload["season"],
        "generated_at": payload["generated_at"],
        "expires_at": payload["expires_at"],
        "sha256": canonical_sha256(payload),
        "source_url": payload["source"]["url"],
        "source_csv_sha256": payload["source"]["csv_sha256"],
        "player_count": len(payload["players"]),
        "available_player_count": sum(
            player.get("available", True)
            for player in payload["players"]
        ),
        "club_count": len(
            {player["club"] for player in payload["players"]}
        ),
        "central_annotation_count": len(payload.get("annotations", {})),
    }
