#!/usr/bin/env python3
"""Validated central quality annotations for Kicker squad optimization."""

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


SCHEMA_VERSION = 3
COMPONENTS = {
    "confirmed_performance",
    "minutes",
    "role",
    "stability",
    "context",
    "fitness",
    "upside",
    "value",
}
RISKS = {"transfer", "injury", "rotation", "outlier", "unknown_role"}


class QualitySnapshotError(ValueError):
    """Raised when a central quality snapshot cannot be trusted."""


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
        raise QualitySnapshotError(
            f"quality snapshot field {field_name!r} is not ISO-8601"
        ) from error
    if parsed.tzinfo is None:
        raise QualitySnapshotError(
            f"quality snapshot field {field_name!r} needs a timezone"
        )
    return parsed.astimezone(timezone.utc)


def _score_object(
    value: Any,
    expected_keys: set[str],
    field_name: str,
    player_id: str,
) -> None:
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise QualitySnapshotError(
            f"quality annotation {field_name} is incomplete for {player_id}"
        )
    if any(
        isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not 0 <= float(score) <= 100
        for score in value.values()
    ):
        raise QualitySnapshotError(
            f"quality annotation {field_name} is invalid for {player_id}"
        )


def validate_snapshot(
    payload: Any,
    *,
    now: datetime | None = None,
    require_fresh: bool = True,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise QualitySnapshotError("quality snapshot must be a JSON object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise QualitySnapshotError("unsupported quality snapshot schema version")
    generated_at = parse_timestamp(payload.get("generated_at"), "generated_at")
    expires_at = parse_timestamp(payload.get("expires_at"), "expires_at")
    current = now or datetime.now(timezone.utc)
    if generated_at > current.replace(microsecond=0):
        raise QualitySnapshotError("quality snapshot generated_at is in the future")
    if expires_at <= generated_at:
        raise QualitySnapshotError(
            "quality snapshot expires_at must follow generated_at"
        )
    if require_fresh and expires_at <= current:
        raise QualitySnapshotError(
            f"quality snapshot expired at {expires_at.isoformat()}"
        )
    for field_name in (
        "competition",
        "season",
        "market_sha256",
        "news_sha256",
        "history_sha256",
        "model_version",
    ):
        if not str(payload.get(field_name, "")).strip():
            raise QualitySnapshotError(
                f"quality snapshot field {field_name!r} is missing"
            )
    annotations = payload.get("annotations")
    if not isinstance(annotations, dict):
        raise QualitySnapshotError(
            "quality snapshot annotations must be an object"
        )
    anchor_count = 0
    attacking_anchor_count = 0
    history_resolved_count = 0
    goalkeepers_by_club: dict[str, int] = {}
    for player_id, annotation in annotations.items():
        if not str(player_id).strip() or not isinstance(annotation, dict):
            raise QualitySnapshotError(
                "quality snapshot contains an invalid annotation"
            )
        _score_object(
            annotation.get("components"),
            COMPONENTS,
            "components",
            str(player_id),
        )
        _score_object(
            annotation.get("risks"),
            RISKS,
            "risks",
            str(player_id),
        )
        if not isinstance(annotation.get("reliable_anchor"), bool):
            raise QualitySnapshotError(
                f"quality anchor flag is invalid for {player_id}"
            )
        if not isinstance(annotation.get("benchmark"), bool):
            raise QualitySnapshotError(
                f"quality benchmark flag is invalid for {player_id}"
            )
        history_summary = annotation.get("history_summary")
        if not isinstance(history_summary, dict):
            raise QualitySnapshotError(
                f"quality history summary is missing for {player_id}"
            )
        mapping_status = str(history_summary.get("mapping_status", ""))
        if mapping_status not in {
            "verified",
            "probable",
            "unmatched",
            "ambiguous",
        }:
            raise QualitySnapshotError(
                f"quality history mapping status is invalid for {player_id}"
            )
        if mapping_status in {"verified", "probable"}:
            transfermarkt_id = history_summary.get("transfermarkt_player_id")
            if (
                isinstance(transfermarkt_id, bool)
                or not isinstance(transfermarkt_id, int)
                or transfermarkt_id <= 0
                or not str(history_summary.get("profile_url", "")).startswith(
                    "https://"
                )
            ):
                raise QualitySnapshotError(
                    f"quality history identity is invalid for {player_id}"
                )
            history_resolved_count += 1
        for field_name in (
            "proven_seasons",
            "comparable_minutes",
            "level_adjusted_minutes",
            "youth_adjusted_minutes",
            "youth_adjusted_contributions",
            "youth_score",
        ):
            value = history_summary.get(field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or float(value) < 0
            ):
                raise QualitySnapshotError(
                    f"quality history {field_name} is invalid for {player_id}"
                )
        if float(history_summary["youth_score"]) > 100:
            raise QualitySnapshotError(
                f"quality history youth_score is invalid for {player_id}"
            )
        proven_seasons = annotation.get("proven_seasons")
        if (
            isinstance(proven_seasons, bool)
            or not isinstance(proven_seasons, int)
            or proven_seasons < 0
        ):
            raise QualitySnapshotError(
                f"quality proven_seasons is invalid for {player_id}"
            )
        evidence = annotation.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise QualitySnapshotError(
                f"quality evidence is missing for {player_id}"
            )
        for item in evidence:
            if (
                not isinstance(item, dict)
                or not str(item.get("claim", "")).strip()
                or not str(item.get("source_url", "")).startswith("https://")
                or not str(item.get("checked_at", "")).strip()
            ):
                raise QualitySnapshotError(
                    f"quality evidence is invalid for {player_id}"
                )
        if annotation["reliable_anchor"]:
            anchor_count += 1
            if annotation.get("position") in {"MIDFIELDER", "FORWARD"}:
                attacking_anchor_count += 1
        if annotation.get("position") == "GOALKEEPER":
            club = str(annotation.get("club", "")).strip()
            if club:
                goalkeepers_by_club[club] = goalkeepers_by_club.get(club, 0) + 1

    requirements = payload.get("requirements")
    if not isinstance(requirements, dict):
        raise QualitySnapshotError(
            "quality snapshot requirements must be an object"
        )
    actual = {
        "candidate_count": len(annotations),
        "anchor_count": anchor_count,
        "attacking_anchor_count": attacking_anchor_count,
        "goalkeeper_block_count": sum(
            count >= 3 for count in goalkeepers_by_club.values()
        ),
        "history_resolved_percent": round(
            100.0 * history_resolved_count / max(1, len(annotations))
        ),
    }
    for field_name, actual_value in actual.items():
        required = requirements.get(field_name)
        if (
            isinstance(required, bool)
            or not isinstance(required, int)
            or required < 0
            or actual_value < required
        ):
            raise QualitySnapshotError(
                f"quality snapshot requirement {field_name} is not met: "
                f"required={required}, actual={actual_value}"
            )
    expected_hash = str(payload.get("content_sha256", "")).strip()
    if not expected_hash or expected_hash != canonical_sha256(payload):
        raise QualitySnapshotError(
            "quality snapshot content_sha256 does not match its content"
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
        raise QualitySnapshotError("remote quality snapshots require HTTPS")
    headers = {
        "Accept": "application/json",
        "User-Agent": "kicker-interactive-manager-quality-client/1",
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
                    raise QualitySnapshotError(
                        "central quality snapshot exceeds 10 MB"
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
    raise QualitySnapshotError(
        f"could not load central quality snapshot: {last_error}"
    )


def load_snapshot(
    location: str | Path,
    *,
    token_env: str = "KICKER_QUALITY_FEED_TOKEN",
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
        raise QualitySnapshotError(
            "quality snapshot is not valid UTF-8 JSON"
        ) from error
    return validate_snapshot(
        payload,
        now=now,
        require_fresh=require_fresh,
    )


def snapshot_audit(payload: dict[str, Any]) -> dict[str, Any]:
    annotations = payload["annotations"]
    anchors = [
        annotation
        for annotation in annotations.values()
        if annotation["reliable_anchor"]
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
        "news_sha256": payload["news_sha256"],
        "history_sha256": payload["history_sha256"],
        "model_version": payload["model_version"],
        "candidate_count": len(annotations),
        "anchor_count": len(anchors),
        "attacking_anchor_count": sum(
            annotation.get("position") in {"MIDFIELDER", "FORWARD"}
            for annotation in anchors
        ),
        "goalkeeper_block_count": len(
            {
                annotation.get("club")
                for annotation in annotations.values()
                if annotation.get("position") == "GOALKEEPER"
                and sum(
                    candidate.get("position") == "GOALKEEPER"
                    and candidate.get("club") == annotation.get("club")
                    for candidate in annotations.values()
                )
                >= 3
            }
        ),
        "history_resolved_count": sum(
            annotation["history_summary"]["mapping_status"]
            in {"verified", "probable"}
            for annotation in annotations.values()
        ),
        "history_resolved_percent": round(
            100.0
            * sum(
                annotation["history_summary"]["mapping_status"]
                in {"verified", "probable"}
                for annotation in annotations.values()
            )
            / max(1, len(annotations)),
            2,
        ),
        "requirements": payload["requirements"],
    }
