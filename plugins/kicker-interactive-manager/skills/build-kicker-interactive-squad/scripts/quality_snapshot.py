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
GOALKEEPER_HIERARCHY_MODEL = "multi-season-v12-news-role-cache"
RECENCY_FORM_MODEL = "recency-context-v4-evidence-role-transfer"
PRESEASON_READINESS_MODEL = "preseason-readiness-v3-role-responsibilities"
EXPECTED_ROLE_MODEL = "expected-role-v2"
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
GOALKEEPER_STATUSES = {
    "confirmed_starter",
    "clear_favourite",
    "likely_starter",
    "open_competition",
    "external_signing_risk",
    "challenger",
    "backup",
}
PRESEASON_CLASSIFICATIONS = {
    "insufficient",
    "negative",
    "neutral",
    "positive",
    "strong",
}
PRESEASON_TALENT_STATUSES = {
    "unchanged",
    "preseason_watchlist",
    "high_upside_pre_breakthrough",
}


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


def _validate_goalkeeper_outlook(
    outlook: Any,
    player_id: str,
) -> dict[str, Any]:
    if not isinstance(outlook, dict):
        raise QualitySnapshotError(
            f"quality goalkeeper outlook is missing for {player_id}"
        )
    if outlook.get("status") not in GOALKEEPER_STATUSES:
        raise QualitySnapshotError(
            f"quality goalkeeper status is invalid for {player_id}"
        )
    if outlook.get("confidence") not in {"low", "medium", "high"}:
        raise QualitySnapshotError(
            f"quality goalkeeper confidence is invalid for {player_id}"
        )
    for field_name in (
        "starter_probability",
        "current_hierarchy_probability",
        "hierarchy_score",
        "hierarchy_gap",
        "club_price_share",
        "global_price_percentile",
        "external_signing_risk",
    ):
        value = outlook.get(field_name)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not 0 <= float(value) <= 100
        ):
            raise QualitySnapshotError(
                f"quality goalkeeper {field_name} is invalid for {player_id}"
            )
    for field_name in (
        "club_rank",
        "market_goalkeeper_count",
        "provider_goalkeeper_count",
        "unpriced_provider_goalkeeper_count",
        "incoming_unpriced_goalkeeper_count",
    ):
        value = outlook.get(field_name)
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < (1 if field_name == "club_rank" else 0)
        ):
            raise QualitySnapshotError(
                f"quality goalkeeper {field_name} is invalid for {player_id}"
            )
    basis = outlook.get("basis")
    if (
        not isinstance(basis, list)
        or not basis
        or any(not str(item).strip() for item in basis)
    ):
        raise QualitySnapshotError(
            f"quality goalkeeper basis is invalid for {player_id}"
        )
    return outlook


def stable_goalkeeper_block_count(
    goalkeepers_by_club: dict[str, list[dict[str, Any]]],
) -> int:
    stable = 0
    for outlooks in goalkeepers_by_club.values():
        leaders = [
            outlook
            for outlook in outlooks
            if outlook.get("club_rank") == 1
        ]
        if len(outlooks) < 3 or len(leaders) != 1:
            continue
        leader = leaders[0]
        if (
            leader["status"] in {
                "confirmed_starter",
                "clear_favourite",
                "likely_starter",
            }
            and float(leader["starter_probability"]) >= 70
            and float(leader["external_signing_risk"]) <= 40
            and leader["confidence"] in {"medium", "high"}
        ):
            stable += 1
    return stable


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
        "preseason_sha256",
        "history_sha256",
        "kicker_history_sha256",
        "model_version",
        "preseason_model_version",
    ):
        if not str(payload.get(field_name, "")).strip():
            raise QualitySnapshotError(
                f"quality snapshot field {field_name!r} is missing"
            )
    if (
        payload.get("model_version") == GOALKEEPER_HIERARCHY_MODEL
        and payload.get("form_model_version") != RECENCY_FORM_MODEL
    ):
        raise QualitySnapshotError(
            "quality snapshot form model version is missing or unsupported"
        )
    annotations = payload.get("annotations")
    if not isinstance(annotations, dict):
        raise QualitySnapshotError(
            "quality snapshot annotations must be an object"
        )
    anchor_count = 0
    attacking_anchor_count = 0
    history_resolved_count = 0
    goalkeepers_by_club: dict[str, list[dict[str, Any]]] = {}
    legacy_goalkeepers_by_club: dict[str, int] = {}
    hierarchy_model = (
        payload.get("model_version") == GOALKEEPER_HIERARCHY_MODEL
    )
    recency_form_model = hierarchy_model
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
        if recency_form_model:
            form_summary = annotation.get("form_summary")
            if (
                not isinstance(form_summary, dict)
                or form_summary.get("model_version") != RECENCY_FORM_MODEL
            ):
                raise QualitySnapshotError(
                    f"quality form summary is missing for {player_id}"
                )
            for field_name in (
                "score",
                "confidence",
                "recency_decay",
                "latest_season_score",
                "context_transfer_factor",
            ):
                value = form_summary.get(field_name)
                upper_bound = 1 if field_name in {
                    "confidence",
                    "recency_decay",
                    "context_transfer_factor",
                } else 100
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not 0 <= float(value) <= upper_bound
                ):
                    raise QualitySnapshotError(
                        f"quality form {field_name} is invalid for {player_id}"
                    )
            season_count = form_summary.get("season_count")
            seasons = form_summary.get("seasons")
            if (
                isinstance(season_count, bool)
                or not isinstance(season_count, int)
                or season_count < 0
                or not isinstance(seasons, list)
                or len(seasons) != season_count
            ):
                raise QualitySnapshotError(
                    f"quality form seasons are invalid for {player_id}"
                )
            club_changed = form_summary.get("club_changed")
            if club_changed is not None and not isinstance(
                club_changed,
                bool,
            ):
                raise QualitySnapshotError(
                    f"quality form club context is invalid for {player_id}"
                )
            availability_ratio = form_summary.get("availability_ratio")
            if (
                availability_ratio is not None
                and (
                    isinstance(availability_ratio, bool)
                    or not isinstance(availability_ratio, (int, float))
                    or float(availability_ratio) < 0
                )
            ):
                raise QualitySnapshotError(
                    f"quality form availability ratio is invalid for {player_id}"
                )
            if not str(form_summary.get("recovery_status", "")).strip():
                raise QualitySnapshotError(
                    f"quality form recovery status is invalid for {player_id}"
                )
            if str(form_summary.get("role_continuity", "")) not in {
                "unknown",
                "confirmed",
                "expanded",
                "reduced",
            }:
                raise QualitySnapshotError(
                    f"quality form role continuity is invalid for {player_id}"
                )
            adjustments = form_summary.get("adjustments")
            if not isinstance(adjustments, dict):
                raise QualitySnapshotError(
                    f"quality form adjustments are invalid for {player_id}"
                )
            for field_name in (
                "confirmed_performance",
                "role",
                "context",
                "upside",
                "unknown_role_risk",
            ):
                value = adjustments.get(field_name)
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not -15 <= float(value) <= 15
                ):
                    raise QualitySnapshotError(
                        f"quality form adjustment {field_name} is invalid "
                        f"for {player_id}"
                    )
        role_metrics = annotation.get("api_sports_role_metrics")
        if not isinstance(role_metrics, dict):
            raise QualitySnapshotError(
                f"quality API-Sports role metrics are missing for {player_id}"
            )
        for field_name in (
            "latest_event_score",
            "multi_season_event_score",
            "provider_rating_score",
        ):
            value = role_metrics.get(field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not 0 <= float(value) <= 100
            ):
                raise QualitySnapshotError(
                    f"quality API-Sports {field_name} is invalid for {player_id}"
                )
        rating_weight = role_metrics.get(
            "rating_weight_in_api_confirmation"
        )
        if (
            isinstance(rating_weight, bool)
            or not isinstance(rating_weight, (int, float))
            or not 0 <= float(rating_weight) <= 0.15
        ):
            raise QualitySnapshotError(
                f"quality provider rating weight is invalid for {player_id}"
            )
        if hierarchy_model:
            role_context = annotation.get("role_context")
            if (
                not isinstance(role_context, dict)
                or role_context.get("model_version") != EXPECTED_ROLE_MODEL
                or role_context.get("continuity")
                not in {"unknown", "confirmed", "expanded", "reduced"}
            ):
                raise QualitySnapshotError(
                    f"quality expected role context is invalid for {player_id}"
                )
            responsibilities = role_context.get("responsibilities")
            if (
                not isinstance(responsibilities, dict)
                or set(responsibilities)
                != {
                    "penalties",
                    "direct_free_kicks",
                    "corners",
                    "playmaker",
                    "offensive_focal_point",
                    "aerial_set_piece_target",
                    "captain",
                }
                or any(
                    level not in {"none", "shared", "primary"}
                    for level in responsibilities.values()
                )
            ):
                raise QualitySnapshotError(
                    f"quality role responsibilities are invalid for {player_id}"
                )
            for field_name in (
                "expected_start_probability",
                "team_quality_delta",
            ):
                value = role_context.get(field_name)
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or (
                        not 0 <= float(value) <= 100
                        if field_name == "expected_start_probability"
                        else not -30 <= float(value) <= 30
                    )
                ):
                    raise QualitySnapshotError(
                        f"quality expected role {field_name} is invalid "
                        f"for {player_id}"
                    )
        preseason_summary = annotation.get("preseason_summary")
        if not isinstance(preseason_summary, dict):
            raise QualitySnapshotError(
                f"quality preseason summary is missing for {player_id}"
            )
        if not isinstance(preseason_summary.get("available"), bool):
            raise QualitySnapshotError(
                f"quality preseason availability is invalid for {player_id}"
            )
        if (
            preseason_summary.get("classification")
            not in PRESEASON_CLASSIFICATIONS
            or preseason_summary.get("talent_status")
            not in PRESEASON_TALENT_STATUSES
            or preseason_summary.get("confidence")
            not in {"low", "medium", "high"}
        ):
            raise QualitySnapshotError(
                f"quality preseason classification is invalid for {player_id}"
            )
        for field_name in (
            "signal_score",
            "availability_score",
            "role_score",
            "performance_score",
            "opponent_score",
            "effective_factor",
        ):
            value = preseason_summary.get(field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not 0 <= float(value) <= 100
            ):
                raise QualitySnapshotError(
                    f"quality preseason {field_name} is invalid for {player_id}"
                )
        applied_weight = preseason_summary.get("applied_weight")
        if (
            isinstance(applied_weight, bool)
            or not isinstance(applied_weight, (int, float))
            or not 0 <= float(applied_weight) <= 0.25
        ):
            raise QualitySnapshotError(
                f"quality preseason applied_weight is invalid for {player_id}"
            )
        for field_name in (
            "appearances",
            "starts",
            "minutes",
            "goals",
            "assists",
        ):
            value = preseason_summary.get(field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise QualitySnapshotError(
                    f"quality preseason {field_name} is invalid for {player_id}"
                )
        readiness_delta = preseason_summary.get("readiness_delta")
        if (
            isinstance(readiness_delta, bool)
            or not isinstance(readiness_delta, (int, float))
            or not -25 <= float(readiness_delta) <= 25
        ):
            raise QualitySnapshotError(
                f"quality preseason readiness_delta is invalid for {player_id}"
            )
        if payload.get("preseason_model_version") == PRESEASON_READINESS_MODEL:
            training_score = preseason_summary.get("training_score")
            if (
                isinstance(training_score, bool)
                or not isinstance(training_score, (int, float))
                or not 0 <= float(training_score) <= 100
                or preseason_summary.get("latest_training_status") not in {
                    "full",
                    "partial",
                    "absent",
                    "unknown",
                }
            ):
                raise QualitySnapshotError(
                    f"quality preseason recovery state is invalid for {player_id}"
                )
            for field_name in ("recovery_risk_floor", "injury_risk"):
                value = preseason_summary.get(field_name)
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not 0 <= float(value) <= 100
                ):
                    raise QualitySnapshotError(
                        f"quality preseason {field_name} is invalid for {player_id}"
                    )
        kicker_trend = annotation.get("kicker_trend")
        if not isinstance(kicker_trend, dict):
            raise QualitySnapshotError(
                f"quality Kicker trend is missing for {player_id}"
            )
        observation_count = kicker_trend.get("observation_count")
        trend_score = kicker_trend.get("trend_score")
        if (
            isinstance(observation_count, bool)
            or not isinstance(observation_count, int)
            or observation_count < 0
            or isinstance(trend_score, bool)
            or not isinstance(trend_score, (int, float))
            or not 0 <= float(trend_score) <= 100
        ):
            raise QualitySnapshotError(
                f"quality Kicker trend is invalid for {player_id}"
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
                legacy_goalkeepers_by_club[club] = (
                    legacy_goalkeepers_by_club.get(club, 0) + 1
                )
                if hierarchy_model or "goalkeeper_outlook" in annotation:
                    goalkeepers_by_club.setdefault(club, []).append(
                        _validate_goalkeeper_outlook(
                            annotation.get("goalkeeper_outlook"),
                            str(player_id),
                        )
                    )

    requirements = payload.get("requirements")
    if not isinstance(requirements, dict):
        raise QualitySnapshotError(
            "quality snapshot requirements must be an object"
        )
    for club, outlooks in goalkeepers_by_club.items():
        ranks = sorted(int(outlook["club_rank"]) for outlook in outlooks)
        if ranks != list(range(1, len(outlooks) + 1)):
            raise QualitySnapshotError(
                f"quality goalkeeper ranks are inconsistent for {club}"
            )
        external_risks = {
            round(float(outlook["external_signing_risk"]), 3)
            for outlook in outlooks
        }
        if len(external_risks) != 1:
            raise QualitySnapshotError(
                f"quality goalkeeper club risk is inconsistent for {club}"
            )
    actual = {
        "candidate_count": len(annotations),
        "anchor_count": anchor_count,
        "attacking_anchor_count": attacking_anchor_count,
        "goalkeeper_block_count": (
            stable_goalkeeper_block_count(goalkeepers_by_club)
            if hierarchy_model
            else sum(
                count >= 3
                for count in legacy_goalkeepers_by_club.values()
            )
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
        "preseason_sha256": payload["preseason_sha256"],
        "history_sha256": payload["history_sha256"],
        "kicker_history_sha256": payload["kicker_history_sha256"],
        "model_version": payload["model_version"],
        "preseason_model_version": payload["preseason_model_version"],
        "form_model_version": (
            payload.get("form_model_version")
            if payload.get("model_version") == GOALKEEPER_HIERARCHY_MODEL
            else None
        ),
        "form_covered_count": sum(
            isinstance(annotation.get("form_summary"), dict)
            and annotation["form_summary"].get("season_count", 0) > 0
            for annotation in annotations.values()
        ),
        "form_club_change_count": sum(
            isinstance(annotation.get("form_summary"), dict)
            and annotation["form_summary"].get("club_changed") is True
            for annotation in annotations.values()
        ),
        "form_recovery_watch_count": sum(
            isinstance(annotation.get("form_summary"), dict)
            and annotation["form_summary"].get("recovery_status")
            in {
                "current_injury_or_recovery",
                "recent_availability_drop",
            }
            for annotation in annotations.values()
        ),
        "preseason_covered_count": sum(
            annotation["preseason_summary"]["available"]
            for annotation in annotations.values()
        ),
        "preseason_high_upside_count": sum(
            annotation["preseason_summary"]["talent_status"]
            == "high_upside_pre_breakthrough"
            for annotation in annotations.values()
        ),
        "candidate_count": len(annotations),
        "anchor_count": len(anchors),
        "attacking_anchor_count": sum(
            annotation.get("position") in {"MIDFIELDER", "FORWARD"}
            for annotation in anchors
        ),
        "goalkeeper_block_count": (
            stable_goalkeeper_block_count(
                {
                    club: [
                        annotation["goalkeeper_outlook"]
                        for annotation in annotations.values()
                        if annotation.get("position") == "GOALKEEPER"
                        and annotation.get("club") == club
                    ]
                    for club in {
                        annotation.get("club")
                        for annotation in annotations.values()
                        if annotation.get("position") == "GOALKEEPER"
                    }
                    if club
                }
            )
            if payload.get("model_version") == GOALKEEPER_HIERARCHY_MODEL
            else len(
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
            )
        ),
        "goalkeeper_hierarchy_available": (
            payload.get("model_version") == GOALKEEPER_HIERARCHY_MODEL
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
