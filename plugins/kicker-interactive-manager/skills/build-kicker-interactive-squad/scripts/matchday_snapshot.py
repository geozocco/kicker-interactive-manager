#!/usr/bin/env python3
"""Validated short-lived fixture and opponent-strength snapshots."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


class MatchdaySnapshotError(ValueError):
    pass


def canonical_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                key: value
                for key, value in payload.items()
                if key != "content_sha256"
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def timestamp(value: Any) -> datetime:
    text = str(value or "").replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise MatchdaySnapshotError("matchday timestamp needs timezone")
    return parsed.astimezone(timezone.utc)


def validate_snapshot(
    payload: dict[str, Any],
    *,
    now: datetime | None = None,
    require_fresh: bool = True,
) -> dict[str, Any]:
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("competition")
        not in {"Bundesliga", "2. Bundesliga", "3. Liga"}
        or not str(payload.get("season", "")).strip()
        or payload.get("status") not in {"ok", "unavailable"}
        or not isinstance(payload.get("fixtures"), list)
        or not isinstance(payload.get("teams"), dict)
    ):
        raise MatchdaySnapshotError("invalid matchday snapshot")
    generated = timestamp(payload.get("generated_at"))
    expires = timestamp(payload.get("expires_at"))
    if generated >= expires:
        raise MatchdaySnapshotError("invalid matchday expiry")
    if require_fresh and (now or datetime.now(timezone.utc)) >= expires:
        raise MatchdaySnapshotError("matchday snapshot expired")
    for club, context in payload["teams"].items():
        if (
            not str(club).strip()
            or not isinstance(context, dict)
            or not isinstance(context.get("fixture_difficulty"), (int, float))
            or not 0 <= float(context["fixture_difficulty"]) <= 100
        ):
            raise MatchdaySnapshotError(
                f"invalid matchday team context for {club!r}"
            )
    expected = canonical_sha256(payload)
    if payload.get("content_sha256") not in {None, expected}:
        raise MatchdaySnapshotError("invalid matchday content_sha256")
    return payload


def load_snapshot(
    location: str | Path,
    *,
    require_fresh: bool = True,
) -> dict[str, Any]:
    payload = json.loads(Path(location).read_text(encoding="utf-8"))
    return validate_snapshot(payload, require_fresh=require_fresh)
