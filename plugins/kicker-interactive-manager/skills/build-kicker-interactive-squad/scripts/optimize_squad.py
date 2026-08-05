#!/usr/bin/env python3
"""Optimize a Kicker Interactive squad from the official player CSV.

The script deliberately separates historical CSV evidence from current,
agent-researched annotations. It uses only the Python standard library.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import heapq
import hashlib
import itertools
import json
import math
import os
import random
import re
import secrets
import sys
import unicodedata
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import AbstractSet, Any, Iterable

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from news_snapshot import NewsSnapshotError, load_snapshot, snapshot_audit
from market_snapshot import (
    MarketSnapshotError,
    canonical_sha256 as market_canonical_sha256,
    csv_rows as market_csv_rows,
    load_snapshot as load_market_snapshot,
    snapshot_audit as market_snapshot_audit,
)
from quality_snapshot import (
    GOALKEEPER_HIERARCHY_MODEL,
    QualitySnapshotError,
    load_snapshot as load_quality_snapshot,
    snapshot_audit as quality_snapshot_audit,
)


DEFAULT_SLOTS = {
    "GOALKEEPER": 3,
    "DEFENDER": 7,
    "MIDFIELDER": 7,
    "FORWARD": 5,
}
POSITION_ORDER = {name: index for index, name in enumerate(DEFAULT_SLOTS)}
FORMATIONS = (
    (3, 4, 3),
    (3, 5, 2),
    (4, 3, 3),
    (4, 4, 2),
    (4, 5, 1),
    (5, 3, 2),
    (5, 4, 1),
)
COMPONENTS = (
    "confirmed_performance",
    "minutes",
    "role",
    "stability",
    "context",
    "fitness",
    "upside",
    "value",
)
RISKS = ("transfer", "injury", "rotation", "outlier", "unknown_role")
DEFAULT_NEWS_FEEDS = {
    ("Bundesliga", "2026/27"): (
        "https://geozocco.github.io/kicker-interactive-manager/"
        "v1/news/bundesliga.json"
    ),
    ("2. Bundesliga", "2026/27"): (
        "https://geozocco.github.io/kicker-interactive-manager/"
        "v1/news/2-bundesliga.json"
    ),
    ("3. Liga", "2026/27"): (
        "https://geozocco.github.io/kicker-interactive-manager/"
        "v1/news/3-liga.json"
    ),
}
DEFAULT_MARKET_FEEDS = {
    ("Bundesliga", "2026/27"): (
        "https://geozocco.github.io/kicker-interactive-manager/"
        "v1/market/bundesliga.json"
    ),
    ("2. Bundesliga", "2026/27"): (
        "https://geozocco.github.io/kicker-interactive-manager/"
        "v1/market/2-bundesliga.json"
    ),
    ("3. Liga", "2026/27"): (
        "https://geozocco.github.io/kicker-interactive-manager/"
        "v1/market/3-liga.json"
    ),
}
DEFAULT_QUALITY_FEEDS = {
    ("Bundesliga", "2026/27"): (
        "https://geozocco.github.io/kicker-interactive-manager/"
        "v1/quality/bundesliga.json"
    ),
    ("2. Bundesliga", "2026/27"): (
        "https://geozocco.github.io/kicker-interactive-manager/"
        "v1/quality/2-bundesliga.json"
    ),
    ("3. Liga", "2026/27"): (
        "https://geozocco.github.io/kicker-interactive-manager/"
        "v1/quality/3-liga.json"
    ),
}
CLUB_IDENTITY_STOPWORDS = {
    "1",
    "fc",
    "sc",
    "sv",
    "tsv",
    "vfb",
    "vfl",
    "bsc",
    "spvgg",
    "ev",
}
VARIATION_STATE_ENV = "KICKER_VARIATION_STATE"
VARIATION_STATE_SCHEMA_VERSION = 2
OPTIMIZER_CACHE_ENV = "KICKER_OPTIMIZER_CACHE"
OPTIMIZER_CACHE_SCHEMA_VERSION = 1
OPTIMIZER_ALGORITHM_VERSION = "exact-dp-v7-depth-diversity"
ARCHITECTURE_MODEL_VERSION = "joint-xi-bench-v16-scorer-defense-gates"
COMPETITION_BUDGETS = {
    "Bundesliga": 42_500_000,
    "2. Bundesliga": 10_000_000,
    "3. Liga": 6_000_000,
}

PROFILE_ALIASES = {
    "reliable": "reliable",
    "conservative": "reliable",
    "verlässlich": "reliable",
    "balanced": "balanced",
    "ausgewogen": "balanced",
    "breakout": "breakout",
    "ausbruch": "breakout",
}
MAINTENANCE_ALIASES = {
    "low": "low",
    "gering": "low",
    "normal": "normal",
    "active": "active",
    "aktiv": "active",
}
VARIATION_ALIASES = {
    "none": "none",
    "keine": "none",
    "low": "low",
    "niedrig": "low",
    "medium": "medium",
    "mittel": "medium",
    "high": "high",
    "hoch": "high",
}


class VariationStateError(ValueError):
    """Raised when the private local variation state cannot be used safely."""


def default_optimizer_cache_path() -> Path:
    """Return the cross-platform cache used for seed-independent optima."""

    explicit_path = os.environ.get(OPTIMIZER_CACHE_ENV)
    if explicit_path:
        return Path(explicit_path).expanduser()
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        return (
            Path(codex_home).expanduser()
            / "cache"
            / "kicker-interactive-manager"
            / "optimizer"
        )
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return (
            Path(os.environ["LOCALAPPDATA"])
            / "Codex"
            / "cache"
            / "kicker-interactive-manager"
            / "optimizer"
        )
    return (
        Path.home()
        / ".codex"
        / "cache"
        / "kicker-interactive-manager"
        / "optimizer"
    )


def default_variation_state_path() -> Path:
    """Return a cross-platform, user-local state path without exposing identity."""

    explicit_path = os.environ.get(VARIATION_STATE_ENV)
    if explicit_path:
        return Path(explicit_path).expanduser()
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        return Path(codex_home).expanduser() / "state" / "kicker-interactive-manager.json"
    if os.name == "nt" and os.environ.get("APPDATA"):
        return (
            Path(os.environ["APPDATA"])
            / "Codex"
            / "state"
            / "kicker-interactive-manager.json"
        )
    return (
        Path.home()
        / ".codex"
        / "state"
        / "kicker-interactive-manager.json"
    )


def _load_variation_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": VARIATION_STATE_SCHEMA_VERSION,
            "installation_id": secrets.token_hex(24),
            "contexts": {},
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise VariationStateError(
            f"local variation state is unreadable at {path}: {error}"
        ) from error
    installation_id = payload.get("installation_id")
    contexts = payload.get("contexts")
    schema_version = payload.get("schema_version")
    if (
        schema_version not in {1, VARIATION_STATE_SCHEMA_VERSION}
        or not isinstance(installation_id, str)
        or re.fullmatch(r"[0-9a-f]{48}", installation_id) is None
        or not isinstance(contexts, dict)
        or any(
            not isinstance(key, str)
            or (
                not (
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and value >= 0
                )
                and not (
                    isinstance(value, dict)
                    and isinstance(value.get("generation"), int)
                    and not isinstance(value.get("generation"), bool)
                    and value["generation"] >= 0
                    and isinstance(value.get("squads", {}), dict)
                    and all(
                        isinstance(generation, str)
                        and generation.isdigit()
                        and isinstance(player_ids, list)
                        and all(
                            isinstance(player_id, str)
                            for player_id in player_ids
                        )
                        for generation, player_ids in value.get(
                            "squads",
                            {},
                        ).items()
                    )
                )
            )
            for key, value in contexts.items()
        )
    ):
        raise VariationStateError(
            f"local variation state has an unsupported format at {path}"
        )
    normalized_contexts = {
        key: (
            {"generation": value, "squads": {}}
            if isinstance(value, int)
            else {
                "generation": value["generation"],
                "squads": dict(value.get("squads", {})),
            }
        )
        for key, value in contexts.items()
    }
    return {
        "schema_version": VARIATION_STATE_SCHEMA_VERSION,
        "installation_id": installation_id,
        "contexts": normalized_contexts,
    }


def _save_variation_state(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(
            f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
        )
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        try:
            temporary_path.chmod(0o600)
        except OSError:
            pass
        os.replace(temporary_path, path)
    except OSError as error:
        raise VariationStateError(
            f"local variation state cannot be saved at {path}: {error}"
        ) from error


def automatic_variation_seed(
    *,
    state_path: Path,
    competition: str | None,
    season: str | None,
    profile: str,
    maintenance: str,
    variation: str,
    budget: int,
    slots: Mapping[str, int],
    new_variant: bool = False,
) -> tuple[int, int]:
    """Derive a stable anonymous seed and optionally advance its local variant."""

    context = json.dumps(
        {
            "competition": competition or "unspecified",
            "season": season or "unspecified",
            "profile": profile,
            "maintenance": maintenance,
            "variation": variation,
            "budget": budget,
            "slots": dict(sorted(slots.items())),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    context_key = hashlib.sha256(context.encode("utf-8")).hexdigest()[:24]
    state = _load_variation_state(state_path)
    context_state = state["contexts"].get(
        context_key,
        {"generation": 0, "squads": {}},
    )
    generation = int(context_state["generation"])
    if new_variant:
        generation += 1
    context_state["generation"] = generation
    state["contexts"][context_key] = context_state
    _save_variation_state(state_path, state)
    digest = hashlib.sha256(
        (
            f"{state['installation_id']}\0{context}\0{generation}"
        ).encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], "big") % (2**31), generation


def automatic_variation_exposure(
    *,
    state_path: Path,
    competition: str | None,
    season: str | None,
    profile: str,
    maintenance: str,
    variation: str,
    budget: int,
    slots: Mapping[str, int],
    generation: int,
) -> Counter[str]:
    """Return deterministic exposure from completed earlier local variants."""

    context = json.dumps(
        {
            "competition": competition or "unspecified",
            "season": season or "unspecified",
            "profile": profile,
            "maintenance": maintenance,
            "variation": variation,
            "budget": budget,
            "slots": dict(sorted(slots.items())),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    context_key = hashlib.sha256(context.encode("utf-8")).hexdigest()[:24]
    state = _load_variation_state(state_path)
    context_state = state["contexts"].get(
        context_key,
        {"generation": generation, "squads": {}},
    )
    return Counter(
        player_id
        for stored_generation, player_ids in context_state.get(
            "squads",
            {},
        ).items()
        if int(stored_generation) < generation
        for player_id in player_ids
    )


def automatic_variation_recent_squads(
    *,
    state_path: Path,
    competition: str | None,
    season: str | None,
    profile: str,
    maintenance: str,
    variation: str,
    budget: int,
    slots: Mapping[str, int],
    generation: int,
) -> list[frozenset[str]]:
    """Return completed recent rosters, newest first, for overlap checks."""

    context = json.dumps(
        {
            "competition": competition or "unspecified",
            "season": season or "unspecified",
            "profile": profile,
            "maintenance": maintenance,
            "variation": variation,
            "budget": budget,
            "slots": dict(sorted(slots.items())),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    context_key = hashlib.sha256(context.encode("utf-8")).hexdigest()[:24]
    state = _load_variation_state(state_path)
    context_state = state["contexts"].get(
        context_key,
        {"generation": generation, "squads": {}},
    )
    completed = [
        (int(stored_generation), frozenset(player_ids))
        for stored_generation, player_ids in context_state.get(
            "squads",
            {},
        ).items()
        if int(stored_generation) < generation
    ]
    return [
        player_ids
        for _, player_ids in sorted(completed, reverse=True)
    ]


def record_automatic_variation_squad(
    *,
    state_path: Path,
    competition: str | None,
    season: str | None,
    profile: str,
    maintenance: str,
    variation: str,
    budget: int,
    slots: Mapping[str, int],
    generation: int,
    player_ids: Iterable[str],
) -> None:
    """Remember one local result per generation for future rerolls."""

    context = json.dumps(
        {
            "competition": competition or "unspecified",
            "season": season or "unspecified",
            "profile": profile,
            "maintenance": maintenance,
            "variation": variation,
            "budget": budget,
            "slots": dict(sorted(slots.items())),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    context_key = hashlib.sha256(context.encode("utf-8")).hexdigest()[:24]
    state = _load_variation_state(state_path)
    context_state = state["contexts"].get(
        context_key,
        {"generation": generation, "squads": {}},
    )
    context_state["generation"] = max(
        generation,
        int(context_state["generation"]),
    )
    context_state.setdefault("squads", {})[str(generation)] = sorted(
        set(player_ids)
    )
    retained_generations = sorted(
        context_state["squads"],
        key=int,
    )[-5:]
    context_state["squads"] = {
        key: context_state["squads"][key]
        for key in retained_generations
    }
    state["contexts"][context_key] = context_state
    _save_variation_state(state_path, state)

PROFILE_WEIGHTS = {
    "reliable": {
        "confirmed_performance": 38,
        "minutes": 22,
        "role": 13,
        "stability": 11,
        "context": 6,
        "fitness": 6,
        "upside": 2,
        "value": 2,
    },
    "balanced": {
        "confirmed_performance": 18,
        "minutes": 23,
        "role": 13,
        "stability": 10,
        "context": 8,
        "fitness": 8,
        "upside": 10,
        "value": 10,
    },
    "breakout": {
        "confirmed_performance": 8,
        "minutes": 18,
        "role": 10,
        "stability": 6,
        "context": 8,
        "fitness": 7,
        "upside": 25,
        "value": 18,
    },
}
RISK_WEIGHTS = {
    "reliable": {
        "transfer": 0.15,
        "injury": 0.12,
        "rotation": 0.16,
        "outlier": 0.12,
        "unknown_role": 0.14,
    },
    "balanced": {
        "transfer": 0.10,
        "injury": 0.10,
        "rotation": 0.12,
        "outlier": 0.08,
        "unknown_role": 0.10,
    },
    "breakout": {
        "transfer": 0.06,
        "injury": 0.08,
        "rotation": 0.08,
        "outlier": 0.04,
        "unknown_role": 0.07,
    },
}
VARIATION_CONFIG = {
    "none": {
        "noise": 0.0,
        "gap": 0.0,
        "distance": 0,
        "avoid": 0.0,
        "history_distance": 0,
        "history_strength": 0.0,
    },
    "low": {
        "noise": 2.0,
        "gap": 0.025,
        "distance": 3,
        "avoid": 1.2,
        "history_distance": 2,
        "history_strength": 1.5,
    },
    "medium": {
        "noise": 4.5,
        "gap": 0.07,
        "distance": 5,
        "avoid": 3.0,
        "history_distance": 4,
        "history_strength": 2.5,
    },
    "high": {
        "noise": 7.5,
        "gap": 0.10,
        "distance": 8,
        "avoid": 5.0,
        "history_distance": 7,
        "history_strength": 4.0,
    },
}
DEFAULT_CLUB_CAP = {"reliable": 4, "balanced": 4, "breakout": 3}
OFFENSIVE_PREMIUM_ANCHOR_MINIMUM = 14.0
OFFENSIVE_PREMIUM_SCORER_LEVERAGE_MINIMUM = 4.0
ELITE_REBOUND_MINIMUM_PROVEN_SEASONS = 4
ELITE_REBOUND_MINIMUM_CONFIRMED_PERFORMANCE = 84.0
ELITE_REBOUND_MINIMUM_START_PROBABILITY = 75.0
ELITE_REBOUND_MINIMUM_FITNESS = 80.0
ELITE_REBOUND_MINIMUM_SCORER_LEVERAGE = 10.0
ELITE_REBOUND_MINIMUM_SAMPLE_MINUTES = 1_200
ELITE_REBOUND_MINIMUM_GOALS_PER_90 = 0.40
ELITE_REBOUND_MINIMUM_CONTRIBUTIONS_PER_90 = 0.70
ELITE_REBOUND_REALLOCATION_PENALTY = 24.0
TOP_SCORER_MINIMUM_PROVEN_SEASONS = 3
TOP_SCORER_MINIMUM_SAMPLE_MINUTES = 1_200
TOP_SCORER_MINIMUM_GOALS_PER_90 = 0.35
TOP_SCORER_MINIMUM_CONTRIBUTIONS_PER_90 = 0.60
TOP_SCORER_MINIMUM_LEVERAGE = 8.0


def variation_distance_met(variation: str, distance: int) -> bool:
    """Accept the narrow post-processing corridor around a variation target."""

    target = int(VARIATION_CONFIG[variation]["distance"])
    if target == 0:
        return distance == 0
    return max(1, target - 1) <= distance <= target + 1


@dataclass(frozen=True)
class Player:
    player_id: str
    name: str
    short_name: str
    club: str
    position: str
    cost: int
    points: float
    grade: float
    components: dict[str, float] = field(compare=False)
    risks: dict[str, float] = field(compare=False)
    note: str = field(default="", compare=False)
    researched: bool = field(default=False, compare=False)
    reliable_anchor: bool = field(default=False, compare=False)
    anchor_basis: str = field(default="none", compare=False)
    anchor_reason: str = field(default="", compare=False)
    benchmark: bool = field(default=False, compare=False)
    evidence: tuple[Any, ...] = field(default=(), compare=False)
    proven_seasons: int = field(default=0, compare=False)
    goalkeeper_outlook: dict[str, Any] = field(
        default_factory=dict,
        compare=False,
    )
    preseason_summary: dict[str, Any] = field(
        default_factory=dict,
        compare=False,
    )
    form_summary: dict[str, Any] = field(
        default_factory=dict,
        compare=False,
    )
    history_summary: dict[str, Any] = field(
        default_factory=dict,
        compare=False,
    )
    role_context: dict[str, Any] = field(
        default_factory=dict,
        compare=False,
    )
    scorer_profile: dict[str, Any] = field(
        default_factory=dict,
        compare=False,
    )
    role_research: dict[str, Any] = field(
        default_factory=dict,
        compare=False,
    )
    manual_news_clearance: dict[str, Any] = field(
        default_factory=dict,
        compare=False,
    )


@dataclass
class Squad:
    players: list[Player]
    objective_score: float
    architecture_diagnostics: dict[str, Any] = field(
        default_factory=dict,
        compare=False,
    )

    @property
    def cost(self) -> int:
        return sum(player.cost for player in self.players)

    @property
    def ids(self) -> frozenset[str]:
        return frozenset(player.player_id for player in self.players)


def clamp(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(100.0, number))


def numeric(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return default


def percentile(value: float, sorted_values: list[float]) -> float:
    if not sorted_values:
        return 50.0
    return 100.0 * bisect.bisect_right(sorted_values, value) / len(sorted_values)


def annotation_minimums(slots: dict[str, int]) -> dict[str, int]:
    return {
        "GOALKEEPER": max(slots["GOALKEEPER"] * 2, slots["GOALKEEPER"]),
        "DEFENDER": slots["DEFENDER"] * 2,
        "MIDFIELDER": slots["MIDFIELDER"] * 2,
        "FORWARD": slots["FORWARD"] * 2,
    }


def evidence_is_complete(annotation: dict[str, Any]) -> bool:
    evidence = annotation.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return False
    for item in evidence:
        if not isinstance(item, dict):
            return False
        if not all(
            str(item.get(key, "")).strip()
            for key in ("claim", "source_url", "checked_at")
        ):
            return False
    return True


def goalkeeper_outlook_is_complete(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("status") not in {
        "confirmed_starter",
        "clear_favourite",
        "likely_starter",
        "open_competition",
        "external_signing_risk",
        "challenger",
        "backup",
    }:
        return False
    if value.get("confidence") not in {"low", "medium", "high"}:
        return False
    for key in (
        "starter_probability",
        "current_hierarchy_probability",
        "hierarchy_score",
        "hierarchy_gap",
        "club_price_share",
        "global_price_percentile",
        "external_signing_risk",
    ):
        score = value.get(key)
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(float(score))
            or not 0 <= float(score) <= 100
        ):
            return False
    rank = value.get("club_rank")
    return (
        isinstance(rank, int)
        and not isinstance(rank, bool)
        and rank >= 1
    )


def annotation_is_complete(
    annotation: dict[str, Any],
    position: str | None = None,
) -> bool:
    components = annotation.get("components")
    risks = annotation.get("risks")

    def valid_scores(values: Any, keys: tuple[str, ...]) -> bool:
        if not isinstance(values, dict):
            return False
        for key in keys:
            value = values.get(key)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or not 0.0 <= float(value) <= 100.0
            ):
                return False
        return True

    if not valid_scores(components, COMPONENTS) or not valid_scores(risks, RISKS):
        return False
    anchor_setting = annotation.get("reliable_anchor")
    anchor_setting_is_valid = isinstance(anchor_setting, bool) or (
        isinstance(anchor_setting, str)
        and anchor_setting.strip().lower() == "auto"
    )
    if not anchor_setting_is_valid:
        return False
    if not isinstance(annotation.get("benchmark"), bool):
        return False
    if (
        anchor_setting is True or isinstance(anchor_setting, str)
    ) and not str(
        annotation.get("anchor_reason", "")
    ).strip():
        return False
    if anchor_setting is True or (
        isinstance(anchor_setting, str)
        and anchor_setting.strip().lower() == "auto"
    ):
        proven_seasons = annotation.get("proven_seasons")
        if (
            isinstance(proven_seasons, bool)
            or not isinstance(proven_seasons, int)
            or proven_seasons < 2
        ):
            return False
    if "goalkeeper_outlook" in annotation and not (
        goalkeeper_outlook_is_complete(
            annotation.get("goalkeeper_outlook")
        )
    ):
        return False
    return evidence_is_complete(annotation)


def load_annotations(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    entries = payload.get("players", payload)
    if not isinstance(entries, dict):
        raise ValueError("annotations must contain an object named 'players'")
    return {str(key): value for key, value in entries.items() if isinstance(value, dict)}


def merge_annotations(
    central: dict[str, dict[str, Any]],
    local: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    merged = {
        str(key): dict(value)
        for key, value in central.items()
        if isinstance(value, dict)
    }
    for key, local_value in local.items():
        current = merged.get(str(key), {})
        combined = {**current, **local_value}
        for nested_key in (
            "components",
            "risks",
            "goalkeeper_outlook",
            "preseason_summary",
            "form_summary",
            "role_context",
            "scorer_profile",
            "role_research",
            "manual_news_clearance",
        ):
            central_nested = current.get(nested_key, {})
            local_nested = local_value.get(nested_key, {})
            if (
                nested_key in current or nested_key in local_value
            ) and isinstance(central_nested, dict) and isinstance(
                local_nested,
                dict,
            ):
                combined[nested_key] = {
                    **central_nested,
                    **local_nested,
                }
        merged[str(key)] = combined
    return merged


def load_players_from_rows(
    rows: list[dict[str, str]],
    annotations: dict[str, dict[str, Any]],
) -> tuple[list[Player], int, dict[str, int]]:
    if not rows:
        raise ValueError("player market is empty")

    points_by_position: dict[str, list[float]] = {
        position: [] for position in DEFAULT_SLOTS
    }
    costs_by_position: dict[str, list[float]] = {
        position: [] for position in DEFAULT_SLOTS
    }
    for row in rows:
        position = str(row.get("Position", "")).upper()
        if position not in DEFAULT_SLOTS:
            continue
        points_by_position[position].append(numeric(row.get("Punkte")))
        costs_by_position[position].append(numeric(row.get("Marktwert")))
    for values in (*points_by_position.values(), *costs_by_position.values()):
        values.sort()

    players: list[Player] = []
    annotated_count = 0
    annotated_by_position = {position: 0 for position in DEFAULT_SLOTS}
    for row in rows:
        position = str(row.get("Position", "")).upper()
        if position not in DEFAULT_SLOTS:
            continue
        player_id = str(row.get("ID", "")).strip()
        name = str(row.get("Angezeigter Name", "")).strip()
        short_name = str(row.get("Angezeigter Name (kurz)", "")).strip() or name
        club = str(row.get("Verein", "")).strip()
        cost = int(numeric(row.get("Marktwert")))
        points = numeric(row.get("Punkte"))
        grade = numeric(row.get("Notendurchschnitt"))
        if not player_id or not name or not club or cost <= 0:
            continue

        points_pct = percentile(points, points_by_position[position])
        price_pct = percentile(cost, costs_by_position[position])
        grade_score = 50.0 if grade <= 0 else clamp((4.5 - grade) * 50.0, 50.0)
        historical = 35.0 if points <= 0 else 0.72 * points_pct + 0.28 * grade_score
        minutes = 43.0 if points <= 0 else (58.0 if points_pct < 55 else 72.0)
        role = 44.0 if points <= 0 else (55.0 if points_pct < 65 else 68.0)
        value = 0.55 * (100.0 - price_pct) + 0.45 * historical
        components = {
            "confirmed_performance": historical,
            "minutes": minutes,
            "role": role,
            "stability": 60.0,
            "context": 50.0,
            "fitness": 65.0,
            "upside": 52.0 if points <= 0 else 45.0,
            "value": value,
        }
        risks = {
            "transfer": 10.0,
            "injury": 10.0,
            "rotation": 18.0 if points > 0 else 32.0,
            "outlier": 12.0 if points_pct < 85 else 28.0,
            "unknown_role": 12.0 if points > 0 else 38.0,
        }

        annotation = annotations.get(player_id) or annotations.get(name) or {}
        if bool(annotation.get("exclude", False)):
            continue
        researched = annotation_is_complete(annotation, position)
        if researched:
            annotated_count += 1
            annotated_by_position[position] += 1
        for key, value in annotation.get("components", {}).items():
            if key in components:
                components[key] = clamp(value, components[key])
        for key, value in annotation.get("risks", {}).items():
            if key in risks:
                risks[key] = clamp(value, risks[key])
        reliable_anchor, anchor_basis = classify_reliable_anchor(
            annotation=annotation,
            researched=researched,
            position=position,
            price_percentile=price_pct,
            components=components,
            risks=risks,
        )
        raw_evidence = annotation.get("evidence", [])
        evidence = (
            tuple(raw_evidence)
            if isinstance(raw_evidence, list)
            else ()
        )

        players.append(
            Player(
                player_id=player_id,
                name=name,
                short_name=short_name,
                club=club,
                position=position,
                cost=cost,
                points=points,
                grade=grade,
                components=components,
                risks=risks,
                note=str(annotation.get("note", "")).strip(),
                researched=researched,
                reliable_anchor=reliable_anchor,
                anchor_basis=anchor_basis,
                anchor_reason=str(annotation.get("anchor_reason", "")).strip(),
                benchmark=bool(annotation.get("benchmark", False)),
                evidence=evidence,
                proven_seasons=(
                    annotation.get("proven_seasons", 0)
                    if isinstance(annotation.get("proven_seasons", 0), int)
                    and not isinstance(annotation.get("proven_seasons", 0), bool)
                    else 0
                ),
                goalkeeper_outlook=(
                    dict(annotation.get("goalkeeper_outlook", {}))
                    if isinstance(
                        annotation.get("goalkeeper_outlook"),
                        dict,
                    )
                    else {}
                ),
                preseason_summary=(
                    dict(annotation.get("preseason_summary", {}))
                    if isinstance(
                        annotation.get("preseason_summary"),
                        dict,
                    )
                    else {}
                ),
                form_summary=(
                    dict(annotation.get("form_summary", {}))
                    if isinstance(
                        annotation.get("form_summary"),
                        dict,
                    )
                    else {}
                ),
                history_summary=(
                    dict(annotation.get("history_summary", {}))
                    if isinstance(
                        annotation.get("history_summary"),
                        dict,
                    )
                    else {}
                ),
                role_context=(
                    dict(annotation.get("role_context", {}))
                    if isinstance(annotation.get("role_context"), dict)
                    else {}
                ),
                scorer_profile=(
                    dict(annotation.get("scorer_profile", {}))
                    if isinstance(annotation.get("scorer_profile"), dict)
                    else {}
                ),
                role_research=(
                    dict(annotation.get("role_research", {}))
                    if isinstance(annotation.get("role_research"), dict)
                    else {}
                ),
                manual_news_clearance=(
                    dict(annotation.get("manual_news_clearance", {}))
                    if isinstance(
                        annotation.get("manual_news_clearance"),
                        dict,
                    )
                    else {}
                ),
            )
        )
    return players, annotated_count, annotated_by_position


def load_players(
    path: Path,
    annotations: dict[str, dict[str, Any]],
) -> tuple[list[Player], int, dict[str, int]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))
    return load_players_from_rows(rows, annotations)


def identity_words(value: str) -> tuple[str, ...]:
    folded = unicodedata.normalize(
        "NFKD",
        value.replace("ß", "ss"),
    ).encode("ascii", "ignore").decode("ascii").casefold()
    return tuple(re.findall(r"[a-z0-9]+", folded))


def player_name_match_score(left: str, right: str) -> int:
    left_words = identity_words(left)
    right_words = identity_words(right)
    if not left_words or not right_words:
        return 0
    if left_words == right_words or (
        len(left_words) == len(right_words)
        and sorted(left_words) == sorted(right_words)
    ):
        return 3
    if len(left_words) < 2 or len(right_words) < 2:
        return 0
    if left_words[-1] != right_words[-1]:
        return 0
    left_first = left_words[0]
    right_first = right_words[0]
    if (
        min(len(left_first), len(right_first)) == 1
        and left_first[0] == right_first[0]
    ):
        return 1
    if min(len(left_first), len(right_first)) >= 3 and (
        left_first.startswith(right_first)
        or right_first.startswith(left_first)
    ):
        return 2
    return 0


def clubs_match(left: str, right: str) -> bool:
    left_words = {
        word
        for word in identity_words(left)
        if word not in CLUB_IDENTITY_STOPWORDS
    }
    right_words = {
        word
        for word in identity_words(right)
        if word not in CLUB_IDENTITY_STOPWORDS
    }
    if not left_words or not right_words:
        return False
    if left_words == right_words or left_words.issubset(right_words) or right_words.issubset(left_words):
        return True
    return any(
        min(len(left_word), len(right_word)) >= 5
        and (
            left_word.startswith(right_word)
            or right_word.startswith(left_word)
        )
        for left_word in left_words
        for right_word in right_words
    )


def snapshot_provider_mapping_rank(entry: dict[str, Any]) -> int:
    mapping = entry.get("mapping", {})
    if not isinstance(mapping, dict):
        return 0
    confidence = str(mapping.get("confidence", "")).strip().lower()
    if confidence not in {"verified", "high"}:
        return 0
    return int(
        any(
            mapping.get(player_key) is not None
            and mapping.get(team_key) is not None
            for player_key, team_key in (
                ("api_sports_player_id", "api_sports_team_id"),
                ("sportsmonks_player_id", "sportsmonks_team_id"),
            )
        )
    )


def merge_snapshot_entries(
    primary: dict[str, Any],
    supplemental: dict[str, Any] | None,
) -> dict[str, Any]:
    """Keep a verified identity while retaining Kicker-keyed news signals."""

    if not isinstance(supplemental, dict) or supplemental is primary:
        return primary
    merged = dict(primary)
    primary_consensus = primary.get("consensus", {})
    supplemental_consensus = supplemental.get("consensus", {})
    if not isinstance(primary_consensus, dict):
        primary_consensus = {}
    if not isinstance(supplemental_consensus, dict):
        supplemental_consensus = {}
    confidence_order = {"low": 0, "medium": 1, "high": 2}
    confidence = max(
        (
            str(primary_consensus.get("confidence", "low")),
            str(supplemental_consensus.get("confidence", "low")),
        ),
        key=lambda value: confidence_order.get(value, 0),
    )
    merged["consensus"] = {
        **primary_consensus,
        "injury": max(
            clamp(primary_consensus.get("injury"), 0.0),
            clamp(supplemental_consensus.get("injury"), 0.0),
        ),
        "transfer": max(
            clamp(primary_consensus.get("transfer"), 0.0),
            clamp(supplemental_consensus.get("transfer"), 0.0),
        ),
        "rotation": max(
            clamp(primary_consensus.get("rotation"), 0.0),
            clamp(supplemental_consensus.get("rotation"), 0.0),
        ),
        "fitness_cap": min(
            clamp(primary_consensus.get("fitness_cap"), 100.0),
            clamp(supplemental_consensus.get("fitness_cap"), 100.0),
        ),
        "exclude": bool(primary_consensus.get("exclude", False))
        or bool(supplemental_consensus.get("exclude", False)),
        "selection_blocked": bool(
            primary_consensus.get("selection_blocked", False)
        )
        or bool(supplemental_consensus.get("selection_blocked", False)),
        "selection_reason": next(
            (
                str(value)
                for value in (
                    primary_consensus.get("selection_reason", ""),
                    supplemental_consensus.get("selection_reason", ""),
                )
                if str(value).strip()
            ),
            "",
        ),
        "confidence": confidence,
        "conflicts": sorted(
            {
                str(value)
                for value in (
                    *primary_consensus.get("conflicts", []),
                    *supplemental_consensus.get("conflicts", []),
                )
                if str(value).strip()
            }
        ),
    }
    signals: list[dict[str, Any]] = []
    seen_signals: set[str] = set()
    for signal in (
        *primary.get("signals", []),
        *supplemental.get("signals", []),
    ):
        if not isinstance(signal, dict):
            continue
        fingerprint = json.dumps(
            signal,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if fingerprint in seen_signals:
            continue
        seen_signals.add(fingerprint)
        signals.append(signal)
    merged["signals"] = signals
    return merged


def resolve_snapshot_entry(
    player: Player,
    entries: dict[str, Any],
) -> tuple[str | None, dict[str, Any] | None, list[str]]:
    direct = entries.get(player.player_id)
    if (
        isinstance(direct, dict)
        and snapshot_provider_mapping_rank(direct) > 0
    ):
        return player.player_id, direct, []

    candidates: list[tuple[int, int, int, str, dict[str, Any]]] = []
    for snapshot_key, raw_entry in entries.items():
        if not isinstance(raw_entry, dict):
            continue
        name_score = player_name_match_score(
            player.name,
            str(raw_entry.get("name", "")),
        )
        if name_score == 0 or not clubs_match(
            player.club,
            str(raw_entry.get("club", "")),
        ):
            continue
        candidates.append(
            (
                snapshot_provider_mapping_rank(raw_entry),
                name_score,
                int(str(snapshot_key) == player.player_id),
                str(snapshot_key),
                raw_entry,
            )
        )
    if not candidates:
        return (
            (player.player_id, direct, [])
            if isinstance(direct, dict)
            else (None, None, [])
        )
    best_rank = max(item[:3] for item in candidates)
    best = [item for item in candidates if item[:3] == best_rank]
    if len(best) != 1:
        return None, None, [
            "multiple central news identities match this Kicker player"
        ]
    _, _, _, snapshot_key, entry = best[0]
    return snapshot_key, merge_snapshot_entries(entry, direct), []


def apply_news_snapshot(
    players: list[Player],
    payload: dict[str, Any],
) -> tuple[list[Player], dict[str, Any], list[dict[str, Any]]]:
    """Apply only conservative, non-downgrading news overrides."""

    entries = payload.get("players", {})
    updated: list[Player] = []
    excluded: list[dict[str, Any]] = []
    applied_ids: list[str] = []
    provider_mapped_ids: list[str] = []
    manually_cleared_ids: list[str] = []
    conflicts: dict[str, list[str]] = {}
    selection_blocked_ids: list[str] = []
    identity_bindings: dict[str, str] = {}
    matched_snapshot_keys: set[str] = set()
    csv_ids = {player.player_id for player in players}

    for player in players:
        snapshot_key, entry, identity_conflicts = resolve_snapshot_entry(
            player,
            entries,
        )
        if identity_conflicts:
            conflicts[player.player_id] = identity_conflicts
        if not isinstance(entry, dict):
            updated.append(player)
            continue
        if snapshot_key is not None:
            identity_bindings[player.player_id] = snapshot_key
            matched_snapshot_keys.add(snapshot_key)
        mapping = entry.get("mapping", {})
        if not isinstance(mapping, dict):
            mapping = {}
        mapping_confidence = str(
            mapping.get("confidence", "")
        ).strip().lower()
        has_provider_mapping = (
            mapping_confidence in {"verified", "high"}
            and any(
                mapping.get(player_key) is not None
                and mapping.get(team_key) is not None
                for player_key, team_key in (
                    (
                        "api_sports_player_id",
                        "api_sports_team_id",
                    ),
                    (
                        "sportsmonks_player_id",
                        "sportsmonks_team_id",
                    ),
                )
            )
        )
        if has_provider_mapping:
            provider_mapped_ids.append(player.player_id)
        elif manual_news_clearance_is_current(
            player.manual_news_clearance
        ):
            manually_cleared_ids.append(player.player_id)

        entry_conflicts = list(entry.get("consensus", {}).get("conflicts", []))
        entry_name = str(entry.get("name", "")).strip()
        entry_club = str(entry.get("club", "")).strip()
        if entry_name and not player_name_match_score(entry_name, player.name):
            entry_conflicts.append(
                f"Kicker-ID maps to snapshot name {entry_name!r}, not {player.name!r}"
            )
        if entry_club and not clubs_match(entry_club, player.club):
            entry_conflicts.append(
                f"Kicker-ID maps to snapshot club {entry_club!r}, not {player.club!r}"
            )
        if entry_conflicts:
            conflicts[player.player_id] = sorted(set(entry_conflicts))

        consensus = entry.get("consensus", {})
        components = dict(player.components)
        risks = dict(player.risks)
        risks["injury"] = max(
            risks["injury"],
            clamp(consensus.get("injury"), 0.0),
        )
        risks["transfer"] = max(
            risks["transfer"],
            clamp(consensus.get("transfer"), 0.0),
        )
        risks["rotation"] = max(
            risks["rotation"],
            clamp(consensus.get("rotation"), 0.0),
        )
        components["fitness"] = min(
            components["fitness"],
            clamp(consensus.get("fitness_cap"), 100.0),
        )

        signal_evidence = []
        for signal in entry.get("signals", []):
            if not isinstance(signal, dict):
                continue
            source_url = str(signal.get("source_url", "")).strip()
            observed_at = str(signal.get("observed_at", "")).strip()
            if not source_url or not observed_at:
                continue
            signal_evidence.append(
                {
                    "claim": (
                        f"{signal.get('kind', 'news')}: "
                        f"{signal.get('detail', signal.get('status', ''))}"
                    ).strip(),
                    "source_url": source_url,
                    "checked_at": observed_at,
                    "source_provider": str(
                        signal.get("source_provider", "")
                    ).strip(),
                }
            )
        evidence = tuple((*player.evidence, *signal_evidence))
        news_note = (
            f"Central news snapshot {payload['generated_at']}: "
            f"injury={risks['injury']:.0f}, transfer={risks['transfer']:.0f}, "
            f"fitness<={components['fitness']:.0f}."
        )
        note = " ".join(part for part in (player.note, news_note) if part)
        anchor_safe = (
            components["fitness"] >= 60
            and risks["transfer"] <= 35
            and risks["injury"] <= 50
            and risks["rotation"] <= 35
        )
        refreshed = replace(
            player,
            components=components,
            risks=risks,
            note=note,
            reliable_anchor=player.reliable_anchor and anchor_safe,
            evidence=evidence,
        )
        applied_ids.append(player.player_id)
        should_exclude = bool(consensus.get("exclude", False))
        selection_blocked = bool(consensus.get("selection_blocked", False))
        confidence = str(consensus.get("confidence", "low"))
        if selection_blocked and not entry_conflicts:
            selection_blocked_ids.append(player.player_id)
            excluded.append(
                {
                    "annotation_key": player.player_id,
                    "player": player.name,
                    "reason": (
                        "Finaler News-Gate: "
                        + str(
                            consensus.get(
                                "selection_reason",
                                "aktuelle Transferlage ist nicht freigegeben",
                            )
                        )
                    ),
                    "benchmark": player.benchmark,
                    "evidence": signal_evidence,
                    "source": "central_news_final_gate",
                    "automatic_reoptimization": True,
                }
            )
            continue
        if (
            should_exclude
            and confidence in {"medium", "high"}
            and not entry_conflicts
        ):
            excluded.append(
                {
                    "annotation_key": player.player_id,
                    "player": player.name,
                    "reason": (
                        "Central news consensus marks the player unavailable "
                        f"(confidence={confidence})."
                    ),
                    "benchmark": player.benchmark,
                    "evidence": signal_evidence,
                    "source": "central_news_snapshot",
                }
            )
            continue
        updated.append(refreshed)

    audit = snapshot_audit(payload)
    coverage_cleared_ids = sorted(
        set(provider_mapped_ids).union(manually_cleared_ids)
    )
    audit.update(
        {
            "applied_player_ids": sorted(applied_ids),
            "provider_mapped_player_ids": sorted(provider_mapped_ids),
            "manually_cleared_player_ids": sorted(manually_cleared_ids),
            "coverage_cleared_player_ids": coverage_cleared_ids,
            "unmapped_csv_player_ids": sorted(
                csv_ids - set(coverage_cleared_ids)
            ),
            "snapshot_only_player_ids": sorted(
                set(entries) - matched_snapshot_keys
            ),
            "identity_bindings": identity_bindings,
            "conflicts": conflicts,
            "hard_exclusions": len(excluded),
            "selection_blocked_player_ids": sorted(selection_blocked_ids),
            "automatic_reoptimization": bool(selection_blocked_ids),
        }
    )
    return updated, audit, excluded


def manual_news_clearance_is_current(value: Any) -> bool:
    """Accept only complete manual coverage checked within the last week."""

    if not isinstance(value, dict) or value.get("valid") is not True:
        return False
    coverage = {
        str(item).strip().casefold()
        for item in value.get("coverage", [])
    }
    if not {
        "availability",
        "fitness",
        "role",
        "transfer",
    }.issubset(coverage):
        return False
    try:
        checked_at = datetime.fromisoformat(
            str(value.get("checked_at", "")).replace("Z", "+00:00")
        )
    except ValueError:
        return False
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - checked_at.astimezone(timezone.utc)
    return 0 <= age.total_seconds() <= 7 * 24 * 3600


def classify_reliable_anchor(
    annotation: dict[str, Any],
    researched: bool,
    position: str,
    price_percentile: float,
    components: dict[str, float],
    risks: dict[str, float],
) -> tuple[bool, str]:
    """Classify repeatable premium field players without hard-coded names."""

    if not researched or position == "GOALKEEPER":
        return False, "none"

    setting = annotation.get("reliable_anchor", "auto")
    if isinstance(setting, str):
        normalized = setting.strip().lower()
    elif setting is True:
        normalized = "eligible"
    elif setting is False:
        normalized = "ineligible"
    else:
        normalized = "auto"
    if normalized in {"false", "no", "ineligible"}:
        return False, "explicit"
    safety_gate = (
        components["fitness"] >= 60
        and risks["transfer"] <= 35
        and risks["injury"] <= 50
        and risks["rotation"] <= 35
        and risks["outlier"] <= 35
        and risks["unknown_role"] <= 30
    )
    if normalized in {"true", "yes", "eligible"}:
        has_reason = bool(str(annotation.get("anchor_reason", "")).strip())
        if not has_reason:
            return False, "explicit"
        proven_seasons = annotation.get("proven_seasons", 0)
        if (
            isinstance(proven_seasons, bool)
            or not isinstance(proven_seasons, int)
            or proven_seasons < 2
        ):
            return False, "insufficient_history"
        quality_gate = (
            components["confirmed_performance"] >= 78
            and components["minutes"] >= 75
            and components["role"] >= 70
            and components["stability"] >= 65
        )
        return safety_gate and quality_gate, "explicit"

    proven_seasons = annotation.get("proven_seasons", 0)
    if (
        isinstance(proven_seasons, bool)
        or not isinstance(proven_seasons, int)
        or proven_seasons < 2
    ):
        return False, "insufficient_history"
    automatic_gate = (
        components["confirmed_performance"] >= 78
        and components["minutes"] >= 75
        and components["role"] >= 70
        and components["stability"] >= 65
        and components["fitness"] >= 70
        and risks["transfer"] <= 20
        and risks["injury"] <= 35
        and risks["rotation"] <= 20
        and risks["outlier"] <= 35
        and risks["unknown_role"] <= 20
        and (
            price_percentile >= 65
            or (
                components["confirmed_performance"] >= 85
                and components["role"] >= 80
            )
        )
    )
    return safety_gate and automatic_gate, "auto"


def offensive_premium_anchor_strength(player: Player) -> float:
    """Rate repeatable attacking excellence with a proven scoring path.

    Multi-season reliability is only the foundation. A midfielder or forward
    must additionally offer a currently usable route to Kicker points through
    repeatable production, set pieces, playmaking or an offensive focal role.
    This prevents safe low-scorer regulars from being misclassified as
    offensive premium anchors.
    """

    if (
        player.position not in {"MIDFIELDER", "FORWARD"}
        or not player.reliable_anchor
        or starting_scorer_leverage(player)
        < OFFENSIVE_PREMIUM_SCORER_LEVERAGE_MINIMUM
    ):
        return 0.0
    strength = (
        2.0 * min(6, max(0, player.proven_seasons - 2))
        + 0.6 * max(0.0, player.components["role"] - 85.0)
        + 0.8
        * max(
            0.0,
            player.components["confirmed_performance"] - 95.0,
        )
        + 0.2 * max(0.0, player.components["stability"] - 75.0)
    )
    return min(18.0, strength)


def is_offensive_premium_anchor(player: Player) -> bool:
    """Identify a multi-season premium scorer or creator from evidence only."""

    return (
        offensive_premium_anchor_strength(player)
        >= OFFENSIVE_PREMIUM_ANCHOR_MINIMUM
    )


def starting_scorer_leverage(player: Player) -> float:
    """Reward repeatable, currently usable Kicker scoring paths in the XI."""

    if player.position == "GOALKEEPER":
        return 0.0
    profile = player.scorer_profile
    responsibilities = player.role_context.get(
        "responsibilities",
        profile.get("responsibilities", {}),
    )
    if not isinstance(responsibilities, dict):
        responsibilities = {}

    level_factor = {"none": 0.0, "shared": 0.58, "primary": 1.0}
    responsibility_weights = (
        {
            "penalties": 5.0,
            "direct_free_kicks": 3.5,
            "corners": 1.8,
            "playmaker": 3.5,
            "offensive_focal_point": 4.5,
        }
        if player.position in {"MIDFIELDER", "FORWARD"}
        else {
            "penalties": 3.5,
            "direct_free_kicks": 2.5,
            "aerial_set_piece_target": 5.0,
        }
    )
    role_bonus = sum(
        weight
        * level_factor.get(
            str(responsibilities.get(key, "none")).casefold(),
            0.0,
        )
        for key, weight in responsibility_weights.items()
    )
    sample_minutes = numeric(profile.get("sample_minutes"))
    sample_factor = min(1.0, sample_minutes / 1_200.0)
    proven_seasons = max(
        player.proven_seasons,
        int(numeric(profile.get("proven_seasons"))),
    )
    repeatability = min(1.0, 0.35 + 0.22 * proven_seasons)
    goals_per_90 = numeric(profile.get("goals_per_90"))
    contributions_per_90 = numeric(
        profile.get("contributions_per_90")
    )
    if player.position in {"MIDFIELDER", "FORWARD"}:
        production_bonus = min(
            9.0,
            18.0 * max(0.0, contributions_per_90 - 0.12)
            + 8.0 * max(0.0, goals_per_90 - 0.08),
        )
        maximum = 16.0
    else:
        production_bonus = min(
            4.5,
            24.0 * max(0.0, goals_per_90 - 0.035),
        )
        maximum = 8.0
    readiness = (
        player.components["minutes"]
        + player.components["role"]
        + player.components["fitness"]
    ) / 300.0
    continuity = str(
        player.role_context.get("continuity", "unknown")
    ).casefold()
    club_changed = player.form_summary.get("club_changed") is True
    portability = (
        0.45
        if club_changed and continuity == "unknown"
        else 0.35
        if continuity == "reduced"
        else 1.0
    )
    uncertainty = (
        1.0
        - 0.003 * player.risks["rotation"]
        - 0.002 * player.risks["unknown_role"]
        - 0.0015 * player.risks["injury"]
    )
    return round(
        min(
            maximum,
            max(
                0.0,
                (
                    role_bonus
                    + production_bonus * sample_factor * repeatability
                )
                * readiness
                * portability
                * max(0.45, uncertainty),
            ),
        ),
        3,
    )


def scorer_leverage_candidate_ids(
    players: Iterable[Player],
) -> frozenset[str]:
    return frozenset(
        player.player_id
        for player in players
        if starting_scorer_leverage(player) >= 4.0
    )


def genuine_top_scorer_evidence(player: Player) -> dict[str, Any]:
    """Recognize a currently usable, multi-season elite scorer path."""

    profile = player.scorer_profile
    sample_minutes = numeric(profile.get("sample_minutes"))
    goals_per_90 = numeric(profile.get("goals_per_90"))
    contributions_per_90 = numeric(profile.get("contributions_per_90"))
    scorer_leverage = starting_scorer_leverage(player)
    qualified = (
        player.position in {"MIDFIELDER", "FORWARD"}
        and player.reliable_anchor
        and player.proven_seasons >= TOP_SCORER_MINIMUM_PROVEN_SEASONS
        and sample_minutes >= TOP_SCORER_MINIMUM_SAMPLE_MINUTES
        and (
            goals_per_90 >= TOP_SCORER_MINIMUM_GOALS_PER_90
            or contributions_per_90
            >= TOP_SCORER_MINIMUM_CONTRIBUTIONS_PER_90
        )
        and scorer_leverage >= TOP_SCORER_MINIMUM_LEVERAGE
        and player.components["confirmed_performance"] >= 80.0
        and player.components["minutes"] >= 75.0
        and player.components["role"] >= 70.0
        and player.components["fitness"] >= 70.0
        and player.risks["transfer"] <= 25.0
        and player.risks["injury"] <= 35.0
        and player.risks["rotation"] <= 35.0
        and player.risks["unknown_role"] <= 30.0
    )
    return {
        "qualified": qualified,
        "proven_seasons": player.proven_seasons,
        "sample_minutes": int(sample_minutes),
        "goals_per_90": round(goals_per_90, 3),
        "contributions_per_90": round(contributions_per_90, 3),
        "scorer_leverage": scorer_leverage,
    }


def is_genuine_top_scorer(player: Player) -> bool:
    return bool(genuine_top_scorer_evidence(player)["qualified"])


def elite_rebound_striker_evidence(
    player: Player,
) -> dict[str, Any]:
    """Recognize restored elite scorers after one misleading weak season.

    This is deliberately name-independent. Long-term scoring class alone is
    insufficient: the current role, start probability, fitness and risk
    picture must prove that the old level is usable again.
    """

    role_confidence = str(
        player.role_context.get(
            "evidence_confidence",
            player.role_context.get("confidence", "none"),
        )
    ).casefold()
    expected_start_probability = numeric(
        player.role_context.get("expected_start_probability")
    )
    sample_minutes = numeric(player.scorer_profile.get("sample_minutes"))
    goals_per_90 = numeric(player.scorer_profile.get("goals_per_90"))
    contributions_per_90 = numeric(
        player.scorer_profile.get("contributions_per_90")
    )
    scorer_leverage = starting_scorer_leverage(player)
    seasons = player.form_summary.get("seasons", [])
    season_scores = [
        numeric(season.get("score"))
        for season in seasons
        if isinstance(season, dict)
        and isinstance(season.get("score"), (int, float))
        and not isinstance(season.get("score"), bool)
    ]
    latest_score = (
        numeric(player.form_summary.get("latest_season_score"))
        if season_scores
        else None
    )
    prior_average = (
        sum(season_scores[1:]) / len(season_scores[1:])
        if len(season_scores) >= 2
        else None
    )
    weak_latest_season = (
        latest_score is not None
        and prior_average is not None
        and prior_average - latest_score >= 8.0
    )
    scoring_path_qualified = (
        sample_minutes >= ELITE_REBOUND_MINIMUM_SAMPLE_MINUTES
        and (
            goals_per_90 >= ELITE_REBOUND_MINIMUM_GOALS_PER_90
            or contributions_per_90
            >= ELITE_REBOUND_MINIMUM_CONTRIBUTIONS_PER_90
        )
    )
    current_readiness_qualified = (
        expected_start_probability
        >= ELITE_REBOUND_MINIMUM_START_PROBABILITY
        and role_confidence in {"medium", "high"}
        and player.components["fitness"] >= ELITE_REBOUND_MINIMUM_FITNESS
        and player.components["role"] >= 80.0
        and player.risks["injury"] <= 25.0
        and player.risks["rotation"] <= 25.0
        and player.risks["transfer"] <= 25.0
        and player.risks["unknown_role"] <= 25.0
    )
    qualified = (
        player.position == "FORWARD"
        and player.reliable_anchor
        and player.proven_seasons
        >= ELITE_REBOUND_MINIMUM_PROVEN_SEASONS
        and player.components["confirmed_performance"]
        >= ELITE_REBOUND_MINIMUM_CONFIRMED_PERFORMANCE
        and scorer_leverage >= ELITE_REBOUND_MINIMUM_SCORER_LEVERAGE
        and scoring_path_qualified
        and current_readiness_qualified
        and weak_latest_season
    )
    return {
        "qualified": qualified,
        "proven_seasons": player.proven_seasons,
        "minimum_proven_seasons": (
            ELITE_REBOUND_MINIMUM_PROVEN_SEASONS
        ),
        "confirmed_performance": round(
            player.components["confirmed_performance"],
            3,
        ),
        "expected_start_probability": round(
            expected_start_probability,
            3,
        ),
        "role_confidence": role_confidence,
        "fitness": round(player.components["fitness"], 3),
        "scorer_leverage": scorer_leverage,
        "sample_minutes": int(sample_minutes),
        "goals_per_90": round(goals_per_90, 3),
        "contributions_per_90": round(contributions_per_90, 3),
        "scoring_path_qualified": scoring_path_qualified,
        "current_readiness_qualified": current_readiness_qualified,
        "weak_latest_season": weak_latest_season,
        "latest_season_score": (
            round(latest_score, 3) if latest_score is not None else None
        ),
        "prior_seasons_average": (
            round(prior_average, 3)
            if prior_average is not None
            else None
        ),
    }


def is_elite_rebound_striker(player: Player) -> bool:
    return bool(elite_rebound_striker_evidence(player)["qualified"])


def elite_rebound_class_adjustment(player: Player) -> float:
    """Bound the recency penalty from one weak season after readiness returns."""

    evidence = elite_rebound_striker_evidence(player)
    if not evidence["qualified"] or not evidence["weak_latest_season"]:
        return 0.0
    latest = float(evidence["latest_season_score"])
    prior_average = float(evidence["prior_seasons_average"])
    return round(min(6.0, 0.20 * (prior_average - latest)), 3)


def offensive_premium_path_evidence(
    player: Player,
) -> dict[str, Any]:
    """Expose why a player does or does not have an offensive premium path."""

    profile = player.scorer_profile
    responsibilities = player.role_context.get(
        "responsibilities",
        profile.get("responsibilities", {}),
    )
    if not isinstance(responsibilities, dict):
        responsibilities = {}
    relevant_keys = (
        "penalties",
        "direct_free_kicks",
        "corners",
        "playmaker",
        "offensive_focal_point",
    )
    active_responsibilities = {
        key: str(responsibilities.get(key, "none")).casefold()
        for key in relevant_keys
        if str(responsibilities.get(key, "none")).casefold()
        in {"shared", "primary"}
    }
    leverage = starting_scorer_leverage(player)
    return {
        "qualified": (
            player.position in {"MIDFIELDER", "FORWARD"}
            and leverage
            >= OFFENSIVE_PREMIUM_SCORER_LEVERAGE_MINIMUM
        ),
        "minimum_scorer_leverage": (
            OFFENSIVE_PREMIUM_SCORER_LEVERAGE_MINIMUM
        ),
        "scorer_leverage": leverage,
        "active_responsibilities": active_responsibilities,
        "sample_minutes": int(numeric(profile.get("sample_minutes"))),
        "goals_per_90": round(
            numeric(profile.get("goals_per_90")),
            3,
        ),
        "contributions_per_90": round(
            numeric(profile.get("contributions_per_90")),
            3,
        ),
    }


def protected_reliable_premium_anchor_ids(
    players: list[Player],
    raw_scores: Mapping[str, float],
    reference_ids: AbstractSet[str],
) -> frozenset[str]:
    """Protect only the safest elite anchors already chosen by the optimum.

    This is intentionally evidence- and percentile-based. A famous name,
    benchmark flag or user mention never enters the decision.
    """

    protected: set[str] = set()
    for position in ("MIDFIELDER", "FORWARD"):
        position_scores = sorted(
            raw_scores[player.player_id]
            for player in players
            if player.position == position
        )
        if not position_scores:
            continue
        elite_index = max(
            0,
            math.ceil(0.90 * len(position_scores)) - 1,
        )
        elite_floor = position_scores[elite_index]
        for player in players:
            if (
                player.position != position
                or player.player_id not in reference_ids
                or raw_scores[player.player_id] < elite_floor
                or not is_offensive_premium_anchor(player)
                or player.proven_seasons < 4
                or player.components["confirmed_performance"] < 90
                or player.components["minutes"] < 80
                or player.components["role"] < 80
                or player.components["stability"] < 70
                or player.components["fitness"] < 70
                or player.risks["transfer"] > 15
                or player.risks["injury"] > 25
                or player.risks["rotation"] > 15
                or player.risks["outlier"] > 20
                or player.risks["unknown_role"] > 15
            ):
                continue
            exchangeable = any(
                candidate.player_id not in reference_ids
                and candidate.position == player.position
                and is_offensive_premium_anchor(candidate)
                and candidate.proven_seasons >= 4
                and raw_scores[candidate.player_id]
                >= 0.97 * raw_scores[player.player_id]
                and candidate.components["minutes"] >= 80
                and candidate.components["role"] >= 80
                and candidate.components["fitness"] >= 70
                and candidate.risks["transfer"] <= 20
                and candidate.risks["injury"] <= 30
                and candidate.risks["rotation"] <= 20
                and candidate.risks["unknown_role"] <= 20
                for candidate in players
            )
            if not exchangeable:
                protected.add(player.player_id)
    return frozenset(protected)


def qualified_potential_player_ids(
    players: list[Player],
) -> frozenset[str]:
    """Find meaningful U23 upside investments, excluding minimum-price fillers."""

    minimum_cost_by_position = {
        position: min(
            (
                player.cost
                for player in players
                if player.position == position
            ),
            default=0,
        )
        for position in ("DEFENDER", "MIDFIELDER", "FORWARD")
    }
    qualified: set[str] = set()
    for player in players:
        if player.position == "GOALKEEPER":
            continue
        talent_profile = player.history_summary.get("talent_profile", {})
        age = talent_profile.get("age")
        talent_score = talent_profile.get("talent_score")
        readiness_score = talent_profile.get("readiness_score")
        if (
            isinstance(age, bool)
            or not isinstance(age, (int, float))
            or isinstance(talent_score, bool)
            or not isinstance(talent_score, (int, float))
            or isinstance(readiness_score, bool)
            or not isinstance(readiness_score, (int, float))
        ):
            continue
        if (
            float(age) <= 22
            and float(talent_score) >= 68
            and float(readiness_score) >= 72
            and player.cost > minimum_cost_by_position[player.position]
            and player.components["minutes"] >= 70
            and player.components["role"] >= 65
            and player.components["fitness"] >= 65
            and player.risks["transfer"] <= 45
            and player.risks["injury"] <= 45
            and player.risks["rotation"] <= 45
            and player.risks["unknown_role"] <= 45
        ):
            qualified.add(player.player_id)
    return frozenset(qualified)


def player_age(player: Player) -> int | None:
    age = player.history_summary.get("talent_profile", {}).get("age")
    return (
        int(age)
        if isinstance(age, (int, float)) and not isinstance(age, bool)
        else None
    )


def effective_weights(profile: str, maintenance: str) -> dict[str, float]:
    weights = {key: float(value) for key, value in PROFILE_WEIGHTS[profile].items()}
    if maintenance == "low":
        weights["minutes"] += 5
        weights["role"] += 2
        weights["stability"] += 4
        weights["upside"] = max(2.0, weights["upside"] - 4)
        weights["value"] = max(2.0, weights["value"] - 2)
    elif maintenance == "active":
        weights["upside"] += 4
        weights["value"] += 3
        weights["stability"] -= 4
        weights["minutes"] -= 3
    total = sum(max(0.0, value) for value in weights.values())
    return {key: 100.0 * max(0.0, value) / total for key, value in weights.items()}


def score_players(players: Iterable[Player], profile: str, maintenance: str) -> dict[str, float]:
    weights = effective_weights(profile, maintenance)
    risk_weights = RISK_WEIGHTS[profile]
    scores: dict[str, float] = {}
    for player in players:
        component_score = sum(
            weights[key] * player.components[key] / 100.0 for key in COMPONENTS
        )
        risk_penalty = sum(risk_weights[key] * player.risks[key] for key in RISKS)
        rebound_scale = {
            "reliable": 1.0,
            "balanced": 0.8,
            "breakout": 0.6,
        }[profile]
        scores[player.player_id] = (
            component_score
            - risk_penalty
            + rebound_scale * elite_rebound_class_adjustment(player)
        )
    return scores


def core_weighted_scores(
    players: list[Player],
    scores: dict[str, float],
    profile: str,
    maintenance: str,
) -> tuple[dict[str, float], dict[str, float]]:
    """Emphasize the likely scoring core over equally strong reserve depth.

    Low-maintenance squads use this curve in every strategy profile because
    their expensive places should be likely starters rather than equivalent
    reserves. Reliable remains strongest; balanced and breakout retain more
    depth and protect exceptional, role-ready prospects.
    """

    if maintenance != "low":
        return dict(scores), {player.player_id: 1.0 for player in players}

    curve_floor, curve_exponent, premium_scale = {
        "reliable": (0.10, 4.0, 1.0),
        "balanced": (0.22, 3.0, 0.45),
        "breakout": (0.32, 2.0, 0.25),
    }[profile]
    premium_starter_ids = premium_starter_candidate_ids(
        players,
        scores,
    )
    price_premium_bonus = {
        "reliable": 60.0,
        "balanced": 40.0,
        "breakout": 25.0,
    }[profile]
    weighted: dict[str, float] = {}
    multipliers: dict[str, float] = {}
    for position in DEFAULT_SLOTS:
        position_players = [
            player for player in players if player.position == position
        ]
        ordered_values = sorted(scores[player.player_id] for player in position_players)
        for player in position_players:
            premium_bonus = 0.0
            if player.reliable_anchor:
                premium_bonus = offensive_premium_anchor_strength(player)
                if player.position == "DEFENDER":
                    premium_bonus = (
                        2.0 * min(6, max(0, player.proven_seasons - 2))
                        + 0.6 * max(0.0, player.components["role"] - 85.0)
                        + 0.8
                        * max(
                            0.0,
                            player.components["confirmed_performance"] - 95.0,
                        )
                        + 0.2
                        * max(0.0, player.components["stability"] - 75.0)
                    )
                premium_bonus = premium_scale * min(
                    18.0
                    if player.position in {"MIDFIELDER", "FORWARD"}
                    else 8.0,
                    premium_bonus
                    * (
                        1.0
                        if player.position in {"MIDFIELDER", "FORWARD"}
                        else 0.5
                    ),
                )
            if len(ordered_values) <= 1:
                rank = 1.0
            else:
                rank = (
                    bisect.bisect_right(ordered_values, scores[player.player_id]) - 1
                ) / (len(ordered_values) - 1)
            multiplier = (
                curve_floor
                + (1.0 - curve_floor) * rank**curve_exponent
            )
            # A broad anchor flag proves floor-level reliability, but it must
            # not make every established regular as valuable as a genuine
            # multi-season premium player. The floor therefore depends only on
            # repeatable performance, role, stability and proven seasons.
            if premium_bonus >= 8.0:
                anchor_floor = (
                    0.95
                    if player.position in {"MIDFIELDER", "FORWARD"}
                    else 0.85
                )
                multiplier = max(multiplier, anchor_floor)
            exceptional_ready_prospect = (
                player.components["upside"] >= 90
                and player.components["minutes"] >= 80
                and player.components["role"] >= 80
            )
            if exceptional_ready_prospect and profile in {"balanced", "breakout"}:
                multiplier = max(
                    multiplier,
                    0.78 if profile == "balanced" else 0.88,
                )
            raw_score = scores[player.player_id]
            weighted_score = (
                raw_score * multiplier if raw_score >= 0.0 else raw_score
            )
            # The squad optimizer scores all 22 places additively. This
            # bounded, evidence-derived premium prevents several tiny reserve
            # upgrades from collectively displacing a proven top scorer.
            weighted_score += premium_bonus
            if player.player_id in premium_starter_ids:
                # A candidate qualifies through current top-price performance
                # or through the stricter elite-rebound evidence gate.
                weighted_score += price_premium_bonus
            weighted[player.player_id] = weighted_score
            multipliers[player.player_id] = multiplier
    return weighted, multipliers


def best_starting_lineup(
    players: list[Player],
    scores: dict[str, float],
    min_reliable_anchors: int = 0,
    min_forwards: int = 1,
    max_defenders: int = 5,
    min_offensive_premium_anchors: int = 0,
    qualified_potential_ids: AbstractSet[str] = frozenset(),
    min_qualified_potential_starters: int = 0,
) -> tuple[str, frozenset[str]]:
    """Infer the strongest legal eleven while keeping the reliable core."""

    by_position = {
        position: [player for player in players if player.position == position]
        for position in DEFAULT_SLOTS
    }
    if not by_position["GOALKEEPER"]:
        return "", frozenset()
    goalkeeper = expected_primary_goalkeeper(
        by_position["GOALKEEPER"],
        scores,
    )
    field_position_index = {
        "DEFENDER": 0,
        "MIDFIELDER": 1,
        "FORWARD": 2,
    }
    maximum_counts = {
        "DEFENDER": max(formation[0] for formation in FORMATIONS),
        "MIDFIELDER": max(formation[1] for formation in FORMATIONS),
        "FORWARD": max(formation[2] for formation in FORMATIONS),
    }
    states: dict[
        tuple[int, int, int, int, int, int],
        tuple[float, frozenset[str]],
    ] = {(0, 0, 0, 0, 0, 0): (0.0, frozenset())}
    for player in sorted(
        (
            player
            for player in players
            if player.position != "GOALKEEPER"
        ),
        key=lambda player: player.player_id,
    ):
        position_index = field_position_index[player.position]
        next_states = dict(states)
        for key, (score, ids) in states.items():
            counts = list(key[:3])
            if counts[position_index] >= maximum_counts[player.position]:
                continue
            counts[position_index] += 1
            anchors = min(
                min_reliable_anchors,
                key[3] + int(player.reliable_anchor),
            )
            premium_anchors = min(
                min_offensive_premium_anchors,
                key[4] + int(is_offensive_premium_anchor(player)),
            )
            potential_starters = min(
                min_qualified_potential_starters,
                key[5] + int(player.player_id in qualified_potential_ids),
            )
            new_key = (
                counts[0],
                counts[1],
                counts[2],
                anchors,
                premium_anchors,
                potential_starters,
            )
            new_score = score + scores[player.player_id]
            current = next_states.get(new_key)
            if current is None or new_score > current[0]:
                next_states[new_key] = (
                    new_score,
                    ids | {player.player_id},
                )
        states = next_states

    best_any: tuple[float, str, frozenset[str]] | None = None
    best_anchor_safe: tuple[float, str, frozenset[str]] | None = None
    for defenders, midfielders, forwards in FORMATIONS:
        if forwards < min_forwards or defenders > max_defenders:
            continue
        counts = {
            "DEFENDER": defenders,
            "MIDFIELDER": midfielders,
            "FORWARD": forwards,
        }
        if any(len(by_position[position]) < count for position, count in counts.items()):
            continue
        formation = f"{defenders}-{midfielders}-{forwards}"
        for key, (field_score, field_ids) in states.items():
            if key[:3] != (defenders, midfielders, forwards):
                continue
            candidate = (
                field_score + scores[goalkeeper.player_id],
                formation,
                field_ids | {goalkeeper.player_id},
            )
            if best_any is None or candidate[0] > best_any[0]:
                best_any = candidate
            if (
                key[3] < min_reliable_anchors
                or key[4] < min_offensive_premium_anchors
                or key[5] < min_qualified_potential_starters
            ):
                continue
            if (
                best_anchor_safe is None
                or candidate[0] > best_anchor_safe[0]
            ):
                best_anchor_safe = candidate
    chosen = best_anchor_safe or best_any
    if chosen is None:
        return "", frozenset()
    return chosen[1], chosen[2]


def formation_flexibility_audit(
    squad: Squad,
    lineup_scores: Mapping[str, float],
    raw_scores: Mapping[str, float],
    core_ids: AbstractSet[str],
) -> dict[str, Any]:
    """Credit reserves that can enter a near-equivalent legal formation."""

    by_position = {
        position: sorted(
            (
                player
                for player in squad.players
                if player.position == position
            ),
            key=lambda player: (
                -lineup_scores[player.player_id],
                player.player_id,
            ),
        )
        for position in DEFAULT_SLOTS
    }
    if not by_position["GOALKEEPER"] or not core_ids:
        return {
            "adjustment": 0.0,
            "eligible_player_ids": [],
            "player_credits": {},
            "near_equivalent_formations": [],
        }
    goalkeeper = expected_primary_goalkeeper(
        by_position["GOALKEEPER"],
        dict(lineup_scores),
    )
    reference_score = sum(
        lineup_scores[player_id] for player_id in core_ids
    )
    players_by_id = {
        player.player_id: player for player in squad.players
    }
    credits: dict[str, float] = {}
    formation_options: list[dict[str, Any]] = []
    for defenders, midfielders, forwards in FORMATIONS:
        counts = {
            "DEFENDER": defenders,
            "MIDFIELDER": midfielders,
            "FORWARD": forwards,
        }
        if any(
            len(by_position[position]) < count
            for position, count in counts.items()
        ):
            continue
        alternative_ids = {goalkeeper.player_id}
        for position, count in counts.items():
            alternative_ids.update(
                player.player_id
                for player in by_position[position][:count]
            )
        added_ids = alternative_ids.difference(core_ids)
        if not added_ids:
            continue
        alternative_score = sum(
            lineup_scores[player_id] for player_id in alternative_ids
        )
        relative_gap = max(
            0.0,
            (reference_score - alternative_score)
            / max(abs(reference_score), 1.0),
        )
        if relative_gap > FORMATION_FLEXIBILITY_MAX_GAP:
            continue
        closeness = max(
            0.0,
            1.0 - relative_gap / FORMATION_FLEXIBILITY_MAX_GAP,
        )
        credited_ids: list[str] = []
        for player_id in added_ids:
            player = players_by_id[player_id]
            weight = FORMATION_FLEXIBILITY_WEIGHTS.get(
                player.position,
                0.0,
            )
            credit = max(
                0.0,
                raw_scores[player_id] * weight * closeness,
            )
            if credit <= 0.0:
                continue
            credits[player_id] = max(credits.get(player_id, 0.0), credit)
            credited_ids.append(player_id)
        if credited_ids:
            formation_options.append(
                {
                    "formation": f"{defenders}-{midfielders}-{forwards}",
                    "relative_gap": round(relative_gap, 6),
                    "added_player_ids": sorted(credited_ids),
                }
            )
    return {
        "adjustment": sum(credits.values()),
        "eligible_player_ids": sorted(credits),
        "player_credits": {
            player_id: round(value, 6)
            for player_id, value in sorted(credits.items())
        },
        "near_equivalent_formations": formation_options,
    }


def reliable_core_audit(
    squad: Squad,
    scores: dict[str, float],
    min_reliable_anchors: int,
    min_attacking_anchors: int,
    min_core_budget_share: float,
    min_offensive_premium_anchors: int = 0,
    qualified_potential_ids: AbstractSet[str] = frozenset(),
    min_qualified_potential_starters: int = 0,
) -> dict[str, Any]:
    """Measure whether a conservative squad actually funds its scoring core."""

    formation, core_ids = best_starting_lineup(
        squad.players,
        scores,
        min_reliable_anchors,
        2 if min_core_budget_share > 0 else 1,
        4 if min_core_budget_share > 0 else 5,
        min_offensive_premium_anchors,
        qualified_potential_ids,
        min_qualified_potential_starters,
    )
    core_players = [
        player for player in squad.players if player.player_id in core_ids
    ]
    reliable_anchors = sum(player.reliable_anchor for player in core_players)
    attacking_anchors = sum(
        player.reliable_anchor
        and player.position in {"MIDFIELDER", "FORWARD"}
        for player in core_players
    )
    offensive_premium_anchors = sum(
        is_offensive_premium_anchor(player)
        for player in core_players
    )
    qualified_potential_starter_ids = sorted(
        core_ids.intersection(qualified_potential_ids)
    )
    core_budget = sum(player.cost for player in core_players)
    core_budget_share = core_budget / max(squad.cost, 1)
    return {
        "formation": formation,
        "player_ids": core_ids,
        "reliable_anchors": reliable_anchors,
        "attacking_anchors": attacking_anchors,
        "offensive_premium_anchors": offensive_premium_anchors,
        "qualified_potential_starter_ids": (
            qualified_potential_starter_ids
        ),
        "qualified_potential_starter_count": len(
            qualified_potential_starter_ids
        ),
        "qualified_potential_starter_minimum": (
            min_qualified_potential_starters
        ),
        "qualified_potential_starter_minimum_met": (
            len(qualified_potential_starter_ids)
            >= min_qualified_potential_starters
        ),
        "core_budget": core_budget,
        "core_budget_share": core_budget_share,
        "passes": (
            reliable_anchors >= min_reliable_anchors
            and attacking_anchors >= min_attacking_anchors
            and offensive_premium_anchors
            >= min_offensive_premium_anchors
            and len(qualified_potential_starter_ids)
            >= min_qualified_potential_starters
            and core_budget_share >= min_core_budget_share
        ),
    }


def market_core_budget_share_target(
    candidates: list[Player],
    budget: int,
    requested_target: float,
) -> float:
    """Cap the desired core share at the market's positional price ceiling."""

    if requested_target <= 0 or budget <= 0:
        return 0.0
    by_position = {
        position: sorted(
            (
                player.cost
                for player in candidates
                if player.position == position
            ),
            reverse=True,
        )
        for position in DEFAULT_SLOTS
    }
    goalkeeper_costs = by_position["GOALKEEPER"]
    if not goalkeeper_costs:
        return 0.0
    maximum_core_cost = 0
    for defenders, midfielders, forwards in FORMATIONS:
        # Low-maintenance recommendations use a real scoring attack and avoid
        # five-defender formations. This mirrors best_starting_lineup().
        if forwards < 2 or defenders > 4:
            continue
        counts = {
            "DEFENDER": defenders,
            "MIDFIELDER": midfielders,
            "FORWARD": forwards,
        }
        if any(
            len(by_position[position]) < count
            for position, count in counts.items()
        ):
            continue
        formation_cost = goalkeeper_costs[0] + sum(
            sum(by_position[position][:count])
            for position, count in counts.items()
        )
        maximum_core_cost = max(maximum_core_cost, formation_cost)
    return min(requested_target, maximum_core_cost / budget)


BENCH_SLOT_USAGE_WEIGHTS = {
    "low": {
        "GOALKEEPER": (0.03, 0.01),
        "DEFENDER": (0.28, 0.16, 0.08, 0.04),
        "MIDFIELDER": (0.22, 0.12, 0.06, 0.03),
        "FORWARD": (0.18, 0.05),
    },
    "normal": {
        "GOALKEEPER": (0.08, 0.03),
        "DEFENDER": (0.36, 0.24, 0.15, 0.09),
        "MIDFIELDER": (0.31, 0.21, 0.13, 0.08),
        "FORWARD": (0.28, 0.12),
    },
    "active": {
        "GOALKEEPER": (0.12, 0.06),
        "DEFENDER": (0.44, 0.34, 0.25, 0.18),
        "MIDFIELDER": (0.39, 0.30, 0.22, 0.15),
        "FORWARD": (0.36, 0.20),
    },
}
BENCH_USAGE_WEIGHTS = {
    maintenance: {
        position: slot_weights[0]
        for position, slot_weights in position_weights.items()
    }
    for maintenance, position_weights in BENCH_SLOT_USAGE_WEIGHTS.items()
}
POSITION_CORE_BUDGET_TARGETS = {
    "low": {
        "DEFENDER": 0.65,
        "MIDFIELDER": 0.80,
        "FORWARD": 0.75,
    },
    "normal": {
        "DEFENDER": 0.55,
        "MIDFIELDER": 0.58,
        "FORWARD": 0.65,
    },
    "active": {
        "DEFENDER": 0.45,
        "MIDFIELDER": 0.50,
        "FORWARD": 0.55,
    },
}
POSITION_CONCENTRATION_WEIGHTS = {
    "DEFENDER": 160.0,
    "MIDFIELDER": 600.0,
    "FORWARD": 600.0,
}
DEFENSIVE_TOTAL_BUDGET_SOFT_CAPS = {
    "low": 0.28,
    "normal": 0.32,
    "active": 0.36,
}
DEFENSIVE_OVERSPEND_WEIGHTS = {
    "low": 500.0,
    "normal": 260.0,
    "active": 120.0,
}
PACKAGE_STARTER_LIMITS = {
    "DEFENDER": 4,
    "MIDFIELDER": 4,
    "FORWARD": 3,
}
DEFENDER_MINIMUM_PRICE_LIMITS = {
    "low": 4,
    "normal": 5,
    "active": 6,
}
DEFENDER_MINIMUM_PRICE_STARTER_LIMITS = {
    "low": 1,
    "normal": 2,
    "active": 3,
}
FORMATION_FLEXIBILITY_MAX_GAP = 0.05
FORMATION_FLEXIBILITY_WEIGHTS = {
    "DEFENDER": 0.06,
    "MIDFIELDER": 0.06,
    "FORWARD": 0.04,
}
MIDFIELD_EXPENSIVE_ORDINARY_RESERVE_LIMITS = {
    "low": 1,
    "normal": 2,
    "active": 3,
}
FORWARD_EXPENSIVE_RESERVE_LIMITS = {
    "low": 1,
    "normal": 2,
    "active": 2,
}


def bench_player_usage_weights(
    squad: Squad,
    core_ids: set[str],
    raw_scores: Mapping[str, float],
    maintenance: str,
) -> dict[str, float]:
    """Apply diminishing expected use to successive reserves by position."""

    weights = {
        player.player_id: 1.0
        for player in squad.players
        if player.player_id in core_ids
    }
    slot_weights = BENCH_SLOT_USAGE_WEIGHTS.get(
        maintenance,
        BENCH_SLOT_USAGE_WEIGHTS["normal"],
    )
    for position in DEFAULT_SLOTS:
        reserves = sorted(
            (
                player
                for player in squad.players
                if (
                    player.position == position
                    and player.player_id not in core_ids
                )
            ),
            key=lambda player: (
                -raw_scores[player.player_id],
                player.player_id,
            ),
        )
        position_weights = slot_weights[position]
        for index, player in enumerate(reserves):
            weights[player.player_id] = position_weights[
                min(index, len(position_weights) - 1)
            ]
    return weights


def premium_starter_candidate_ids(
    candidates: list[Player],
    raw_scores: Mapping[str, float],
) -> frozenset[str]:
    """Find expensive, proven scorers whose points justify starter budget."""

    eligible: set[str] = {
        player.player_id
        for player in candidates
        if is_elite_rebound_striker(player)
    }
    for position in ("MIDFIELDER", "FORWARD"):
        position_players = [
            player
            for player in candidates
            if player.position == position
        ]
        if not position_players:
            continue
        ordered_costs = sorted(player.cost for player in position_players)
        premium_price_index = max(
            0,
            math.ceil(0.85 * len(ordered_costs)) - 1,
        )
        premium_price_floor = ordered_costs[premium_price_index]
        ordered_scores = sorted(
            raw_scores[player.player_id]
            for player in position_players
        )
        upper_quartile_index = max(
            0,
            math.ceil(0.75 * len(ordered_scores)) - 1,
        )
        score_floor = ordered_scores[upper_quartile_index]
        eligible.update(
            player.player_id
            for player in position_players
            if (
                is_genuine_top_scorer(player)
                and player.cost >= premium_price_floor
                and raw_scores[player.player_id] >= score_floor
            )
        )
    return frozenset(eligible)


def minimum_costs_by_position(
    players: Iterable[Player],
) -> dict[str, int]:
    """Return the real market floor for each position."""

    minimums: dict[str, int] = {}
    for player in players:
        current = minimums.get(player.position)
        if current is None or player.cost < current:
            minimums[player.position] = player.cost
    return minimums


def defender_is_lineup_ready(player: Player) -> bool:
    """Return whether a defender is credible as a current starting option."""

    return (
        player.components["minutes"] >= 65
        and player.components["role"] >= 65
        and player.components["fitness"] >= 65
        and player.risks["transfer"] <= 45
        and player.risks["injury"] <= 45
        and player.risks["rotation"] <= 40
        and player.risks["unknown_role"] <= 40
    )


def defender_is_direct_backup_ready(player: Player) -> bool:
    """Return whether a defender is a credible first substitute."""

    return (
        player.components["minutes"] >= 60
        and player.components["role"] >= 60
        and player.components["fitness"] >= 65
        and player.risks["transfer"] <= 45
        and player.risks["injury"] <= 45
        and player.risks["rotation"] <= 45
        and player.risks["unknown_role"] <= 45
    )


def midfielder_is_direct_backup_ready(player: Player) -> bool:
    """Return whether a midfielder is credible as the first substitute."""

    return (
        player.components["minutes"] >= 60
        and player.components["role"] >= 60
        and player.components["fitness"] >= 65
        and player.risks["transfer"] <= 45
        and player.risks["injury"] <= 45
        and player.risks["rotation"] <= 45
        and player.risks["unknown_role"] <= 45
    )


def midfield_architecture_audit(
    squad: Squad,
    core_ids: AbstractSet[str],
    *,
    maintenance: str,
    enforce: bool,
    qualified_potential_ids: AbstractSet[str] = frozenset(),
    raw_scores: Mapping[str, float] | None = None,
    position_minimum_costs: Mapping[str, int] | None = None,
    floor_available_count: int | None = None,
    ready_reserve_available_count: int | None = None,
) -> dict[str, Any]:
    """Keep low-maintenance midfield budget in starters, not ordinary depth."""

    midfielders = [
        player for player in squad.players if player.position == "MIDFIELDER"
    ]
    reserves = sorted(
        (
            player
            for player in midfielders
            if player.player_id not in core_ids
        ),
        key=lambda player: (
            -(raw_scores or {}).get(player.player_id, 0.0),
            player.player_id,
        ),
    )
    direct_backup = reserves[0] if reserves else None
    direct_backup_ready = bool(
        direct_backup
        and midfielder_is_direct_backup_ready(direct_backup)
    )
    inferred_minimum = min(
        (player.cost for player in midfielders),
        default=0,
    )
    minimum_cost = int(
        (position_minimum_costs or {}).get(
            "MIDFIELDER",
            inferred_minimum,
        )
    )
    expensive_ordinary_reserves = [
        player
        for player in reserves
        if (
            player.cost > minimum_cost
            and player.player_id not in qualified_potential_ids
        )
    ]
    qualified_potential_reserves = [
        player
        for player in reserves
        if (
            player.cost > minimum_cost
            and player.player_id in qualified_potential_ids
        )
    ]
    limit = MIDFIELD_EXPENSIVE_ORDINARY_RESERVE_LIMITS.get(
        maintenance,
        MIDFIELD_EXPENSIVE_ORDINARY_RESERVE_LIMITS["normal"],
    )
    enough_floor_options = (
        floor_available_count is None
        or floor_available_count >= max(0, len(reserves) - 1)
    )
    effective_enforcement = enforce and enough_floor_options
    excess = max(0, len(expensive_ordinary_reserves) - limit)
    direct_backup_required = bool(
        reserves
        and (
            ready_reserve_available_count is None
            or ready_reserve_available_count > 0
        )
    )
    direct_backup_deficit = int(
        effective_enforcement
        and direct_backup_required
        and not direct_backup_ready
    )
    violation_score = (
        excess + direct_backup_deficit
        if effective_enforcement
        else 0
    )
    return {
        "enforced": effective_enforcement,
        "minimum_cost": minimum_cost,
        "reserve_count": len(reserves),
        "expensive_ordinary_reserve_count": len(
            expensive_ordinary_reserves
        ),
        "expensive_ordinary_reserve_limit": limit,
        "expensive_ordinary_reserve_excess": excess,
        "expensive_ordinary_reserve_ids": sorted(
            player.player_id for player in expensive_ordinary_reserves
        ),
        "qualified_potential_reserve_ids": sorted(
            player.player_id for player in qualified_potential_reserves
        ),
        "direct_backup_player_id": (
            direct_backup.player_id if direct_backup else None
        ),
        "direct_backup_ready": direct_backup_ready,
        "direct_backup_required": direct_backup_required,
        "direct_backup_available_count": ready_reserve_available_count,
        "direct_backup_deficit": direct_backup_deficit,
        "floor_candidate_count": floor_available_count,
        "violation_score": violation_score,
        "passes": not effective_enforcement or violation_score == 0,
    }


def forward_reserve_architecture_audit(
    squad: Squad,
    core_ids: AbstractSet[str],
    *,
    maintenance: str,
    enforce: bool,
    position_minimum_costs: Mapping[str, int] | None = None,
    midfield_direct_backup_ready: bool = True,
    defender_direct_backup_ready: bool = True,
) -> dict[str, Any]:
    """Prioritize playable midfield/defense cover over surplus forwards."""

    forwards = [
        player for player in squad.players if player.position == "FORWARD"
    ]
    reserves = [
        player for player in forwards if player.player_id not in core_ids
    ]
    inferred_minimum = min(
        (player.cost for player in forwards),
        default=0,
    )
    minimum_cost = int(
        (position_minimum_costs or {}).get("FORWARD", inferred_minimum)
    )
    expensive_reserves = [
        player for player in reserves if player.cost > minimum_cost
    ]
    limit = FORWARD_EXPENSIVE_RESERVE_LIMITS.get(
        maintenance,
        FORWARD_EXPENSIVE_RESERVE_LIMITS["normal"],
    )
    expensive_reserve_excess = max(
        0,
        len(expensive_reserves) - limit,
    )
    maximum_reserve_cost = (
        minimum_cost + 100_000
        if maintenance == "low"
        else None
    )
    overpriced_reserves = [
        player
        for player in reserves
        if (
            maximum_reserve_cost is not None
            and player.cost > maximum_reserve_cost
        )
    ]
    total_spend = sum(player.cost for player in forwards)
    core_spend = sum(
        player.cost
        for player in forwards
        if player.player_id in core_ids
    )
    core_budget_share = core_spend / total_spend if total_spend else 0.0
    core_budget_target = POSITION_CORE_BUDGET_TARGETS.get(
        maintenance,
        POSITION_CORE_BUDGET_TARGETS["normal"],
    )["FORWARD"]
    core_budget_deficit = int(
        enforce
        and bool(expensive_reserves)
        and core_budget_share + 1e-9 < core_budget_target
    )
    coverage_deficit = int(
        enforce
        and bool(expensive_reserves)
        and (
            not midfield_direct_backup_ready
            or not defender_direct_backup_ready
        )
    )
    violation_score = (
        expensive_reserve_excess
        + len(overpriced_reserves)
        + core_budget_deficit
        + coverage_deficit
        if enforce
        else 0
    )
    return {
        "enforced": enforce,
        "minimum_cost": minimum_cost,
        "reserve_count": len(reserves),
        "expensive_reserve_count": len(expensive_reserves),
        "expensive_reserve_limit": limit,
        "expensive_reserve_excess": expensive_reserve_excess,
        "expensive_reserve_ids": sorted(
            player.player_id for player in expensive_reserves
        ),
        "maximum_reserve_cost": maximum_reserve_cost,
        "overpriced_reserve_count": len(overpriced_reserves),
        "overpriced_reserve_ids": sorted(
            player.player_id for player in overpriced_reserves
        ),
        "core_spend": core_spend,
        "reserve_spend": total_spend - core_spend,
        "core_budget_share": core_budget_share,
        "core_budget_target": core_budget_target,
        "core_budget_target_met": (
            core_budget_share + 1e-9 >= core_budget_target
        ),
        "core_budget_deficit": core_budget_deficit,
        "midfield_direct_backup_ready": midfield_direct_backup_ready,
        "defender_direct_backup_ready": defender_direct_backup_ready,
        "coverage_deficit": coverage_deficit,
        "violation_score": violation_score,
        "passes": not enforce or violation_score == 0,
    }


def defender_architecture_audit(
    squad: Squad,
    core_ids: AbstractSet[str],
    *,
    maintenance: str,
    enforce: bool,
    raw_scores: Mapping[str, float] | None = None,
    position_minimum_costs: Mapping[str, int] | None = None,
    ready_reserve_available_count: int | None = None,
    qualified_potential_ids: AbstractSet[str] = frozenset(),
) -> dict[str, Any]:
    """Keep one playable reserve without funding a second starting defense."""

    defenders = [
        player for player in squad.players if player.position == "DEFENDER"
    ]
    starting_defenders = [
        player for player in defenders if player.player_id in core_ids
    ]
    reserve_defenders = sorted(
        (
            player
            for player in defenders
            if player.player_id not in core_ids
        ),
        key=lambda player: (
            -(raw_scores or {}).get(player.player_id, 0.0),
            player.player_id,
        ),
    )
    direct_backup = reserve_defenders[0] if reserve_defenders else None
    inferred_minimum = min(
        (player.cost for player in defenders),
        default=0,
    )
    minimum_cost = int(
        (position_minimum_costs or {}).get(
            "DEFENDER",
            inferred_minimum,
        )
    )
    minimum_price_defenders = [
        player for player in defenders if player.cost <= minimum_cost
    ]
    minimum_price_starters = [
        player
        for player in starting_defenders
        if player.cost <= minimum_cost
    ]
    lineup_ready_defenders = [
        player
        for player in starting_defenders
        if defender_is_lineup_ready(player)
    ]
    direct_backup_ready = bool(
        direct_backup
        and defender_is_direct_backup_ready(direct_backup)
    )
    maximum_minimum_price = min(
        DEFENDER_MINIMUM_PRICE_LIMITS.get(
            maintenance,
            DEFENDER_MINIMUM_PRICE_LIMITS["normal"],
        ),
        max(0, len(defenders) - 1),
    )
    maximum_minimum_price_starters = (
        DEFENDER_MINIMUM_PRICE_STARTER_LIMITS.get(
            maintenance,
            DEFENDER_MINIMUM_PRICE_STARTER_LIMITS["normal"],
        )
    )
    required_lineup_ready = max(0, len(starting_defenders) - 1)
    functional_minimum_price_ids = {
        player.player_id
        for player in minimum_price_defenders
        if (
            (
                player.player_id in core_ids
                and defender_is_lineup_ready(player)
            )
            or (
                direct_backup is not None
                and player.player_id == direct_backup.player_id
                and direct_backup_ready
            )
        )
    }
    minimum_price_filler_count = (
        len(minimum_price_defenders) - len(functional_minimum_price_ids)
    )
    nonfunctional_minimum_price_starters = [
        player
        for player in minimum_price_starters
        if player.player_id not in functional_minimum_price_ids
    ]
    minimum_price_filler_limit = max(
        0,
        len(defenders) - len(starting_defenders) - 1,
    )
    minimum_price_excess = max(
        0,
        len(minimum_price_defenders) - maximum_minimum_price,
    )
    minimum_price_filler_excess = max(
        0,
        minimum_price_filler_count - minimum_price_filler_limit,
    )
    minimum_price_starter_excess = max(
        0,
        len(nonfunctional_minimum_price_starters)
        - maximum_minimum_price_starters,
    )
    lineup_ready_deficit = max(
        0,
        required_lineup_ready - len(lineup_ready_defenders),
    )
    direct_backup_required = bool(
        reserve_defenders
        and (
            ready_reserve_available_count is None
            or ready_reserve_available_count > 0
        )
    )
    direct_backup_deficit = int(
        direct_backup_required and not direct_backup_ready
    )
    paid_reserves = [
        player for player in reserve_defenders if player.cost > minimum_cost
    ]
    ordinary_paid_reserves = [
        player
        for player in paid_reserves
        if player.player_id not in qualified_potential_ids
    ]
    paid_reserve_limit = 2
    ordinary_paid_reserve_limit = 1
    paid_reserve_excess = max(0, len(paid_reserves) - paid_reserve_limit)
    ordinary_paid_reserve_excess = max(
        0,
        len(ordinary_paid_reserves) - ordinary_paid_reserve_limit,
    )
    reserve_budget_violation = max(
        paid_reserve_excess,
        ordinary_paid_reserve_excess,
    )
    violation_score = (
        minimum_price_filler_excess
        + minimum_price_starter_excess
        + lineup_ready_deficit
        + direct_backup_deficit
        + reserve_budget_violation
    )
    return {
        "enforced": enforce,
        "minimum_cost": minimum_cost,
        "minimum_price_count": len(minimum_price_defenders),
        "minimum_price_limit": maximum_minimum_price,
        "minimum_price_excess": minimum_price_excess,
        "minimum_price_filler_count": minimum_price_filler_count,
        "minimum_price_filler_limit": minimum_price_filler_limit,
        "minimum_price_filler_excess": minimum_price_filler_excess,
        "functional_minimum_price_player_ids": sorted(
            functional_minimum_price_ids
        ),
        "starting_count": len(starting_defenders),
        "minimum_price_starter_count": len(minimum_price_starters),
        "nonfunctional_minimum_price_starter_count": len(
            nonfunctional_minimum_price_starters
        ),
        "minimum_price_starter_limit": maximum_minimum_price_starters,
        "minimum_price_starter_excess": minimum_price_starter_excess,
        "lineup_ready_count": len(lineup_ready_defenders),
        "lineup_ready_required": required_lineup_ready,
        "lineup_ready_deficit": lineup_ready_deficit,
        "lineup_ready_player_ids": sorted(
            player.player_id for player in lineup_ready_defenders
        ),
        "direct_backup_player_id": (
            direct_backup.player_id if direct_backup else None
        ),
        "direct_backup_ready": direct_backup_ready,
        "direct_backup_required": direct_backup_required,
        "direct_backup_available_count": ready_reserve_available_count,
        "direct_backup_deficit": direct_backup_deficit,
        "paid_reserve_count": len(paid_reserves),
        "paid_reserve_limit": paid_reserve_limit,
        "paid_reserve_excess": paid_reserve_excess,
        "paid_reserve_ids": sorted(
            player.player_id for player in paid_reserves
        ),
        "ordinary_paid_reserve_count": len(ordinary_paid_reserves),
        "ordinary_paid_reserve_limit": ordinary_paid_reserve_limit,
        "ordinary_paid_reserve_excess": ordinary_paid_reserve_excess,
        "reserve_budget_violation": reserve_budget_violation,
        "violation_score": violation_score if enforce else 0,
        "passes": not enforce or violation_score == 0,
    }


def squad_architecture_metrics(
    squad: Squad,
    raw_scores: Mapping[str, float],
    *,
    maintenance: str,
    min_reliable_anchors: int,
    min_attacking_anchors: int,
    min_core_budget_share: float,
    target_core_budget_share: float,
    min_offensive_premium_anchors: int = 0,
    premium_starter_ids: frozenset[str] = frozenset(),
    elite_rebound_striker_costs: Mapping[str, int] | None = None,
    qualified_potential_ids: frozenset[str] = frozenset(),
    min_qualified_potential_core: int = 0,
    target_qualified_potential_core: int = 0,
    position_minimum_costs: Mapping[str, int] | None = None,
    defender_ready_reserve_available_count: int | None = None,
    midfield_floor_available_count: int | None = None,
    midfield_ready_reserve_available_count: int | None = None,
    variation_exposure: Mapping[str, int] | None = None,
    variation_exposure_strength: float = 0.0,
    protected_variation_ids: AbstractSet[str] = frozenset(),
    variation_reference_squads: Sequence[AbstractSet[str]] = (),
    minimum_variation_distance: int = 0,
    maximum_variation_distance: int | None = None,
    variation_preferences: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Value starters at full use and reserves at expected positional use."""

    scorer_leverage = {
        player.player_id: starting_scorer_leverage(player)
        for player in squad.players
    }
    lineup_scores = {
        player.player_id: (
            raw_scores[player.player_id]
            + scorer_leverage[player.player_id]
        )
        for player in squad.players
    }
    available_potential_count = len(qualified_potential_ids)
    effective_potential_minimum = min(
        min_qualified_potential_core,
        available_potential_count,
    )
    effective_potential_target = min(
        max(
            effective_potential_minimum,
            target_qualified_potential_core,
        ),
        available_potential_count,
    )
    effective_potential_starter_minimum = min(
        1,
        effective_potential_minimum,
    )
    audit = reliable_core_audit(
        squad,
        lineup_scores,
        min_reliable_anchors,
        min_attacking_anchors,
        min_core_budget_share,
        min_offensive_premium_anchors,
        qualified_potential_ids,
        effective_potential_starter_minimum,
    )
    core_ids = set(audit["player_ids"])
    player_usage_weights = bench_player_usage_weights(
        squad,
        core_ids,
        raw_scores,
        maintenance,
    )
    extended_core_ids = set(core_ids)
    for position in ("DEFENDER", "MIDFIELDER", "FORWARD"):
        reserves = sorted(
            (
                player
                for player in squad.players
                if (
                    player.position == position
                    and player.player_id not in core_ids
                )
            ),
            key=lambda player: (
                -player_usage_weights[player.player_id],
                -raw_scores[player.player_id],
                player.player_id,
            ),
        )
        if reserves:
            extended_core_ids.add(reserves[0].player_id)
    selected_potential_core_ids = sorted(
        extended_core_ids.intersection(qualified_potential_ids)
    )
    defender_audit = defender_architecture_audit(
        squad,
        core_ids,
        maintenance=maintenance,
        enforce=(
            maintenance == "low"
            and min_core_budget_share > 0
        ),
        raw_scores=raw_scores,
        position_minimum_costs=position_minimum_costs,
        ready_reserve_available_count=(
            defender_ready_reserve_available_count
        ),
        qualified_potential_ids=qualified_potential_ids,
    )
    midfield_audit = midfield_architecture_audit(
        squad,
        core_ids,
        maintenance=maintenance,
        enforce=(
            maintenance == "low"
            and min_core_budget_share > 0
        ),
        qualified_potential_ids=qualified_potential_ids,
        raw_scores=raw_scores,
        position_minimum_costs=position_minimum_costs,
        floor_available_count=midfield_floor_available_count,
        ready_reserve_available_count=(
            midfield_ready_reserve_available_count
        ),
    )
    forward_audit = forward_reserve_architecture_audit(
        squad,
        core_ids,
        maintenance=maintenance,
        enforce=(
            maintenance == "low"
            and min_core_budget_share > 0
        ),
        position_minimum_costs=position_minimum_costs,
        midfield_direct_backup_ready=bool(
            midfield_audit["direct_backup_ready"]
        ),
        defender_direct_backup_ready=bool(
            defender_audit["direct_backup_ready"]
        ),
    )
    reliable_anchor_deficit = max(
        0,
        min_reliable_anchors - int(audit["reliable_anchors"]),
    )
    attacking_anchor_deficit = max(
        0,
        min_attacking_anchors - int(audit["attacking_anchors"]),
    )
    offensive_premium_deficit = max(
        0,
        min_offensive_premium_anchors
        - int(audit["offensive_premium_anchors"]),
    )
    core_budget_deficit = max(
        0,
        math.ceil(
            20
            * max(
                0.0,
                min_core_budget_share - float(audit["core_budget_share"]),
            )
        ),
    )
    potential_core_deficit = max(
        0,
        effective_potential_minimum - len(selected_potential_core_ids),
    )
    potential_starter_deficit = max(
        0,
        effective_potential_starter_minimum
        - int(audit["qualified_potential_starter_count"]),
    )
    variation_distances = [
        len(squad.ids.symmetric_difference(frozenset(reference_ids))) // 2
        for reference_ids in variation_reference_squads
    ]
    variation_distance_deficit = sum(
        max(0, minimum_variation_distance - distance)
        for distance in variation_distances
    )
    variation_distance_excess = (
        max(
            0,
            variation_distances[0] - maximum_variation_distance,
        )
        if (
            variation_distances
            and maximum_variation_distance is not None
        )
        else 0
    )
    hard_violation_score = (
        reliable_anchor_deficit
        + attacking_anchor_deficit
        + offensive_premium_deficit
        + core_budget_deficit
        + potential_core_deficit
        + potential_starter_deficit
        + int(defender_audit["violation_score"])
        + int(midfield_audit["violation_score"])
        + int(forward_audit["violation_score"])
    )
    potential_core_adjustment = -8.0 * max(
        0,
        effective_potential_target - len(selected_potential_core_ids),
    )
    squad_ages = [
        age
        for player in squad.players
        if (age := player_age(player)) is not None
    ]
    starting_ages = [
        age
        for player in squad.players
        if (
            player.player_id in core_ids
            and (age := player_age(player)) is not None
        )
    ]
    player_contributions: dict[str, float] = {}
    for player in squad.players:
        player_contributions[player.player_id] = (
            (
                raw_scores[player.player_id]
                + scorer_leverage[player.player_id]
            )
            * player_usage_weights[player.player_id]
        )
    expected_contribution = sum(player_contributions.values())
    formation_flexibility = formation_flexibility_audit(
        squad,
        lineup_scores,
        raw_scores,
        core_ids,
    )
    target_gap = max(
        0.0,
        target_core_budget_share - audit["core_budget_share"],
    )
    # A ten-point core-share gap is worth twelve model points. This makes
    # concentration material, but never strong enough to replace several
    # genuinely better starters merely because they are cheaper.
    concentration_adjustment = -120.0 * target_gap
    position_targets = POSITION_CORE_BUDGET_TARGETS.get(
        maintenance,
        POSITION_CORE_BUDGET_TARGETS["normal"],
    )
    position_core_budget: dict[str, dict[str, Any]] = {}
    position_concentration_adjustment = 0.0
    for position in ("DEFENDER", "MIDFIELDER", "FORWARD"):
        position_players = [
            player
            for player in squad.players
            if player.position == position
        ]
        total_spend = sum(player.cost for player in position_players)
        core_spend = sum(
            player.cost
            for player in position_players
            if player.player_id in core_ids
        )
        core_share = core_spend / total_spend if total_spend else 0.0
        target = position_targets[position]
        adjustment = -POSITION_CONCENTRATION_WEIGHTS[position] * max(
            0.0,
            target - core_share,
        )
        position_concentration_adjustment += adjustment
        position_core_budget[position] = {
            "core_spend": core_spend,
            "reserve_spend": total_spend - core_spend,
            "core_budget_share": core_share,
            "target": target,
            "target_met": core_share + 1e-9 >= target,
            "adjustment": adjustment,
        }
    premium_starters = sorted(core_ids.intersection(premium_starter_ids))
    premium_starter_target = int(bool(premium_starter_ids))
    premium_starter_adjustment = -45.0 * max(
        0,
        premium_starter_target - len(premium_starters),
    )
    elite_rebound_costs = dict(elite_rebound_striker_costs or {})
    elite_rebound_ids = set(elite_rebound_costs)
    elite_rebound_core_ids = sorted(core_ids.intersection(elite_rebound_ids))
    core_forward_costs = [
        player.cost
        for player in squad.players
        if (
            player.position == "FORWARD"
            and player.player_id in core_ids
        )
    ]
    reserve_excess_budget = 0
    for position in ("MIDFIELDER", "FORWARD"):
        minimum_cost = (position_minimum_costs or {}).get(position, 0)
        reserve_players = [
            player
            for player in squad.players
            if (
                player.position == position
                and player.player_id not in core_ids
            )
        ]
        reserve_excess_budget += sum(
            max(0, player.cost - minimum_cost)
            for player in reserve_players
        )
    elite_rebound_required_increment = (
        min(
            max(0, candidate_cost - incumbent_cost)
            for candidate_cost in elite_rebound_costs.values()
            for incumbent_cost in core_forward_costs
        )
        if elite_rebound_costs and core_forward_costs
        else None
    )
    elite_rebound_financeable_from_reserves = (
        elite_rebound_required_increment is not None
        and reserve_excess_budget >= elite_rebound_required_increment
    )
    elite_rebound_reallocation_adjustment = (
        -ELITE_REBOUND_REALLOCATION_PENALTY
        if (
            elite_rebound_ids
            and not elite_rebound_core_ids
            and elite_rebound_financeable_from_reserves
        )
        else 0.0
    )
    defender_spend = sum(
        player.cost
        for player in squad.players
        if player.position == "DEFENDER"
    )
    defender_spend_share = defender_spend / max(squad.cost, 1)
    defender_scorer_credit = min(
        0.02,
        sum(
            scorer_leverage[player.player_id]
            for player in squad.players
            if (
                player.position == "DEFENDER"
                and player.player_id in core_ids
            )
        )
        / 400.0,
    )
    defender_spend_soft_cap = (
        DEFENSIVE_TOTAL_BUDGET_SOFT_CAPS.get(
            maintenance,
            DEFENSIVE_TOTAL_BUDGET_SOFT_CAPS["normal"],
        )
        + defender_scorer_credit
    )
    offensive_scorer_opportunity_available = bool(premium_starter_ids)
    defender_overspend = (
        max(0.0, defender_spend_share - defender_spend_soft_cap)
        if offensive_scorer_opportunity_available
        else 0.0
    )
    defensive_overspend_adjustment = (
        -DEFENSIVE_OVERSPEND_WEIGHTS.get(
            maintenance,
            DEFENSIVE_OVERSPEND_WEIGHTS["normal"],
        )
        * defender_overspend
    )
    forward_budget = position_core_budget["FORWARD"]
    midfield_budget = position_core_budget["MIDFIELDER"]
    architecture_passes = (
        bool(audit["passes"])
        and potential_core_deficit == 0
        and potential_starter_deficit == 0
        and bool(defender_audit["passes"])
        and bool(midfield_audit["passes"])
        and bool(forward_audit["passes"])
    )
    diversity_adjustment = -max(0.0, variation_exposure_strength) * sum(
        int((variation_exposure or {}).get(player.player_id, 0))
        * (2.0 if player.player_id in core_ids else 0.5)
        for player in squad.players
        if player.player_id not in protected_variation_ids
    )
    variation_distance_adjustment = -25.0 * (
        variation_distance_deficit + variation_distance_excess
    )
    variation_preference_adjustment = sum(
        float((variation_preferences or {}).get(player.player_id, 0.0))
        * (2.0 if player.player_id in core_ids else 0.5)
        for player in squad.players
        if player.player_id not in protected_variation_ids
    )
    architecture_objective = (
        expected_contribution
        + concentration_adjustment
        + position_concentration_adjustment
        + premium_starter_adjustment
        + elite_rebound_reallocation_adjustment
        + potential_core_adjustment
        + defensive_overspend_adjustment
        + formation_flexibility["adjustment"]
        - 50.0 * int(defender_audit["violation_score"])
        - 50.0 * int(midfield_audit["violation_score"])
        - 50.0 * int(forward_audit["violation_score"])
    )
    return {
        **audit,
        "passes": architecture_passes,
        "hard_violation_score": hard_violation_score,
        "defender_architecture": defender_audit,
        "midfield_architecture": midfield_audit,
        "forward_reserve_architecture": forward_audit,
        "expected_contribution": expected_contribution,
        "concentration_adjustment": concentration_adjustment,
        "position_concentration_adjustment": (
            position_concentration_adjustment
        ),
        "position_core_budget": position_core_budget,
        "forward_core_spend": forward_budget["core_spend"],
        "forward_reserve_spend": forward_budget["reserve_spend"],
        "forward_core_budget_share": forward_budget["core_budget_share"],
        "forward_core_budget_target": forward_budget["target"],
        "forward_core_budget_target_met": forward_budget["target_met"],
        "midfield_core_spend": midfield_budget["core_spend"],
        "midfield_reserve_spend": midfield_budget["reserve_spend"],
        "midfield_core_budget_share": midfield_budget["core_budget_share"],
        "midfield_core_budget_target": midfield_budget["target"],
        "midfield_core_budget_target_met": midfield_budget["target_met"],
        "premium_starter_candidate_ids": sorted(premium_starter_ids),
        "premium_starter_ids": premium_starters,
        "premium_starter_target": premium_starter_target,
        "premium_starter_target_met": (
            len(premium_starters) >= premium_starter_target
        ),
        "premium_starter_adjustment": premium_starter_adjustment,
        "elite_rebound_striker_candidate_ids": sorted(
            elite_rebound_ids
        ),
        "elite_rebound_striker_core_ids": elite_rebound_core_ids,
        "elite_rebound_striker_target_met": bool(
            elite_rebound_core_ids
        )
        or not elite_rebound_ids,
        "elite_rebound_required_increment": (
            elite_rebound_required_increment
        ),
        "offensive_reserve_excess_budget": reserve_excess_budget,
        "elite_rebound_financeable_from_reserves": (
            elite_rebound_financeable_from_reserves
        ),
        "elite_rebound_reallocation_adjustment": (
            elite_rebound_reallocation_adjustment
        ),
        "scorer_leverage": scorer_leverage,
        "starting_scorer_leverage": round(
            sum(
                scorer_leverage[player_id]
                for player_id in core_ids
            ),
            3,
        ),
        "defender_spend": defender_spend,
        "defender_spend_share": defender_spend_share,
        "defender_spend_soft_cap": defender_spend_soft_cap,
        "defender_scorer_credit": defender_scorer_credit,
        "offensive_scorer_opportunity_available": (
            offensive_scorer_opportunity_available
        ),
        "defensive_overspend_adjustment": (
            defensive_overspend_adjustment
        ),
        "formation_flexibility_adjustment": (
            formation_flexibility["adjustment"]
        ),
        "formation_flexibility": formation_flexibility,
        "qualified_potential_candidate_ids": sorted(
            qualified_potential_ids
        ),
        "qualified_potential_core_ids": selected_potential_core_ids,
        "qualified_potential_available": available_potential_count,
        "qualified_potential_core_count": len(
            selected_potential_core_ids
        ),
        "qualified_potential_core_minimum": effective_potential_minimum,
        "qualified_potential_core_target": effective_potential_target,
        "qualified_potential_core_minimum_met": (
            len(selected_potential_core_ids)
            >= effective_potential_minimum
        ),
        "qualified_potential_core_target_met": (
            len(selected_potential_core_ids)
            >= effective_potential_target
        ),
        "qualified_potential_starter_deficit": (
            potential_starter_deficit
        ),
        "potential_core_adjustment": potential_core_adjustment,
        "squad_average_age": (
            sum(squad_ages) / len(squad_ages) if squad_ages else None
        ),
        "starting_xi_average_age": (
            sum(starting_ages) / len(starting_ages)
            if starting_ages
            else None
        ),
        "starting_u23_count": sum(
            player.player_id in core_ids
            and (player_age(player) or 99) <= 22
            for player in squad.players
        ),
        "architecture_objective": architecture_objective,
        "variation_exposure_adjustment": diversity_adjustment,
        "variation_distances": variation_distances,
        "minimum_variation_distance": minimum_variation_distance,
        "maximum_variation_distance": maximum_variation_distance,
        "variation_distance_deficit": variation_distance_deficit,
        "variation_distance_excess": variation_distance_excess,
        "variation_distance_target_met": (
            variation_distance_deficit == 0
            and variation_distance_excess == 0
        ),
        "variation_distance_adjustment": variation_distance_adjustment,
        "variation_preference_adjustment": (
            variation_preference_adjustment
        ),
        "architecture_search_objective": (
            architecture_objective
            + diversity_adjustment
            + variation_distance_adjustment
            + variation_preference_adjustment
        ),
        "player_contributions": player_contributions,
        "player_usage_weights": player_usage_weights,
        "bench_usage_weights": dict(
            BENCH_USAGE_WEIGHTS.get(
                maintenance,
                BENCH_USAGE_WEIGHTS["normal"],
            )
        ),
        "bench_slot_usage_weights": {
            position: list(weights)
            for position, weights in BENCH_SLOT_USAGE_WEIGHTS.get(
                maintenance,
                BENCH_SLOT_USAGE_WEIGHTS["normal"],
            ).items()
        },
    }


def finalized_squad_objective(
    squad: Squad,
    candidates: list[Player],
    utility_scores: Mapping[str, float],
    raw_scores: Mapping[str, float],
    args: argparse.Namespace,
) -> tuple[float, bool]:
    """Evaluate final, varied and counterfactual squads on one scale."""

    architecture_objective = squad.architecture_diagnostics.get(
        "architecture_objective"
    )
    architecture_passes = squad.architecture_diagnostics.get("passes")
    if architecture_objective is not None and architecture_passes is not None:
        return float(architecture_objective), bool(architecture_passes)
    if (
        architecture_objective is not None
        and float(getattr(args, "min_core_budget_share", 0.0)) <= 0.0
    ):
        return float(architecture_objective), True
    if float(getattr(args, "min_core_budget_share", 0.0)) <= 0.0:
        return (
            sum(utility_scores[player.player_id] for player in squad.players),
            True,
        )
    candidate_minimum_costs = minimum_costs_by_position(candidates)
    qualified_potential_ids = qualified_potential_player_ids(candidates)
    metrics = squad_architecture_metrics(
        squad,
        raw_scores,
        maintenance=args.maintenance,
        min_reliable_anchors=args.min_reliable_anchors,
        min_attacking_anchors=args.min_attacking_anchors,
        min_core_budget_share=args.min_core_budget_share,
        target_core_budget_share=float(
            getattr(args, "effective_core_budget_share_target", 0.0)
        ),
        min_offensive_premium_anchors=(
            args.min_offensive_premium_anchors
        ),
        premium_starter_ids=premium_starter_candidate_ids(
            candidates,
            raw_scores,
        ),
        elite_rebound_striker_costs={
            player.player_id: player.cost
            for player in candidates
            if is_elite_rebound_striker(player)
        },
        qualified_potential_ids=qualified_potential_ids,
        min_qualified_potential_core=int(
            getattr(args, "min_qualified_potential_core", 0)
        ),
        target_qualified_potential_core=int(
            getattr(args, "target_qualified_potential_core", 0)
        ),
        position_minimum_costs=candidate_minimum_costs,
        defender_ready_reserve_available_count=sum(
            player.position == "DEFENDER"
            and defender_is_direct_backup_ready(player)
            for player in candidates
        ),
        midfield_floor_available_count=sum(
            player.position == "MIDFIELDER"
            and player.cost
            <= candidate_minimum_costs.get("MIDFIELDER", 0)
            for player in candidates
        ),
        midfield_ready_reserve_available_count=sum(
            player.position == "MIDFIELDER"
            and midfielder_is_direct_backup_ready(player)
            for player in candidates
        ),
    )
    return float(metrics["architecture_objective"]), bool(metrics["passes"])


def _architecture_candidate_is_legal(
    players: list[Player],
    *,
    budget: int,
    club_cap: int,
    min_reliable_anchors: int,
    required_player_ids: AbstractSet[str] = frozenset(),
) -> bool:
    if len(players) != len({player.player_id for player in players}):
        return False
    if sum(player.cost for player in players) != budget:
        return False
    if not frozenset(required_player_ids).issubset(
        player.player_id for player in players
    ):
        return False
    if any(
        count > club_cap
        for count in Counter(
            player.club
            for player in players
            if player.position != "GOALKEEPER"
        ).values()
    ):
        return False
    return (
        sum(
            player.reliable_anchor
            for player in players
            if player.position != "GOALKEEPER"
        )
        >= min_reliable_anchors
    )


def position_roster_packages(
    candidates: list[Player],
    raw_scores: Mapping[str, float],
    *,
    position: str,
    count: int,
    total_cost: int,
    maintenance: str,
    limit: int = 300,
    qualified_potential_ids: AbstractSet[str] = frozenset(),
) -> list[tuple[Player, ...]]:
    """Find strong full-position packages without brute-forcing the market."""

    if (
        position not in PACKAGE_STARTER_LIMITS
        or count <= 0
        or total_cost <= 0
        or limit <= 0
    ):
        return []
    by_cost: dict[int, list[Player]] = {}
    for player in candidates:
        if player.position == position:
            by_cost.setdefault(player.cost, []).append(player)
    for cost, players_at_cost in by_cost.items():
        tier_candidate_limit = 6 if count >= 7 else 8
        by_cost[cost] = sorted(
            players_at_cost,
            key=lambda player: (
                -raw_scores[player.player_id],
                player.player_id,
            ),
        )[:tier_candidate_limit]
    costs = sorted(by_cost)
    if not costs:
        return []

    target = POSITION_CORE_BUDGET_TARGETS.get(
        maintenance,
        POSITION_CORE_BUDGET_TARGETS["normal"],
    )[position]
    concentration_weight = POSITION_CONCENTRATION_WEIGHTS[position]
    reserve_weights = BENCH_SLOT_USAGE_WEIGHTS.get(
        maintenance,
        BENCH_SLOT_USAGE_WEIGHTS["normal"],
    )[position]
    heap: list[
        tuple[float, tuple[str, ...], tuple[Player, ...]]
    ] = []

    def cost_patterns(
        start_index: int,
        remaining_count: int,
        remaining_cost: int,
    ) -> Iterable[tuple[int, ...]]:
        if remaining_count == 0:
            if remaining_cost == 0:
                yield ()
            return
        for index in range(start_index, len(costs)):
            cost = costs[index]
            if cost * remaining_count > remaining_cost:
                break
            if cost + costs[-1] * (remaining_count - 1) < remaining_cost:
                continue
            for suffix in cost_patterns(
                index,
                remaining_count - 1,
                remaining_cost - cost,
            ):
                yield (cost, *suffix)

    for cost_pattern in cost_patterns(0, count, total_cost):
        tier_counts = Counter(cost_pattern)
        if any(
            tier_count > len(by_cost[cost])
            for cost, tier_count in tier_counts.items()
        ):
            continue
        tier_options = [
            tuple(itertools.combinations(by_cost[cost], tier_count))
            for cost, tier_count in sorted(tier_counts.items())
        ]
        partial_packages: list[tuple[Player, ...]] = [()]
        beam_limit = max(160, 2 * limit)
        for options in tier_options:
            partial_packages = sorted(
                (
                    (*partial, *option)
                    for partial in partial_packages
                    for option in options
                ),
                key=lambda package: (
                    -sum(
                        raw_scores[player.player_id]
                        for player in package
                    ),
                    tuple(
                        sorted(player.player_id for player in package)
                    ),
                ),
            )[:beam_limit]
        for package in partial_packages:
            ordered = sorted(
                package,
                key=lambda player: (
                    -raw_scores[player.player_id],
                    player.player_id,
                ),
            )
            starter_count = min(
                PACKAGE_STARTER_LIMITS[position],
                len(ordered),
            )
            starters = ordered[:starter_count]
            reserves = ordered[starter_count:]
            core_spend = sum(player.cost for player in starters)
            core_share = core_spend / total_cost
            expected_contribution = sum(
                raw_scores[player.player_id]
                for player in starters
            ) + sum(
                raw_scores[player.player_id]
                * reserve_weights[
                    min(index, len(reserve_weights) - 1)
                ]
                for index, player in enumerate(reserves)
            )
            hard_violation_proxy = 0
            minimum_cost = costs[0]
            if maintenance == "low" and position == "MIDFIELDER":
                expensive_ordinary_reserves = sum(
                    player.cost > minimum_cost
                    and player.player_id not in qualified_potential_ids
                    for player in reserves
                )
                hard_violation_proxy += max(
                    0,
                    expensive_ordinary_reserves
                    - MIDFIELD_EXPENSIVE_ORDINARY_RESERVE_LIMITS["low"],
                )
                if reserves and not midfielder_is_direct_backup_ready(
                    reserves[0]
                ):
                    hard_violation_proxy += 1
            elif maintenance == "low" and position == "FORWARD":
                expensive_reserves = [
                    player
                    for player in reserves
                    if player.cost > minimum_cost
                ]
                hard_violation_proxy += max(
                    0,
                    len(expensive_reserves)
                    - FORWARD_EXPENSIVE_RESERVE_LIMITS["low"],
                )
                maximum_reserve_cost = minimum_cost + 100_000
                hard_violation_proxy += sum(
                    player.cost > maximum_reserve_cost
                    for player in reserves
                )
                if expensive_reserves and core_share + 1e-9 < target:
                    hard_violation_proxy += 1
            proxy = (
                expected_contribution
                - concentration_weight * max(0.0, target - core_share)
                - 10_000.0 * hard_violation_proxy
            )
            package_ids = tuple(
                sorted(player.player_id for player in package)
            )
            item = (proxy, package_ids, package)
            if len(heap) < limit:
                heapq.heappush(heap, item)
            elif item[:2] > heap[0][:2]:
                heapq.heapreplace(heap, item)
    return [
        item[2]
        for item in sorted(
            heap,
            key=lambda item: (item[0], item[1]),
            reverse=True,
        )
    ]


def forward_roster_packages(
    candidates: list[Player],
    raw_scores: Mapping[str, float],
    *,
    count: int,
    total_cost: int,
    maintenance: str,
    limit: int = 300,
) -> list[tuple[Player, ...]]:
    """Backward-compatible wrapper for the full-forward package search."""

    return position_roster_packages(
        candidates,
        raw_scores,
        position="FORWARD",
        count=count,
        total_cost=total_cost,
        maintenance=maintenance,
        limit=limit,
    )


def optimize_joint_squad_architecture(
    squad: Squad,
    candidates: list[Player],
    quality_scores: Mapping[str, float],
    raw_scores: Mapping[str, float],
    *,
    budget: int,
    club_cap: int,
    maintenance: str,
    min_reliable_anchors: int,
    min_attacking_anchors: int,
    min_core_budget_share: float,
    target_core_budget_share: float,
    min_offensive_premium_anchors: int = 0,
    min_qualified_potential_core: int = 0,
    target_qualified_potential_core: int = 0,
    quality_loss_limit: float = 0.05,
    max_iterations: int = 10,
    same_club_goalkeepers: bool = True,
    protected_player_ids: AbstractSet[str] = frozenset(),
    variation_exposure: Mapping[str, int] | None = None,
    variation_exposure_strength: float = 0.0,
    variation_reference_squads: Sequence[AbstractSet[str]] = (),
    minimum_variation_distance: int = 0,
    maximum_variation_distance: int | None = None,
    variation_preferences: Mapping[str, float] | None = None,
) -> Squad:
    """Jointly improve the legal XI and its reserves at exact total spend."""

    if squad.cost != budget:
        return squad
    current = squad
    baseline_quality = sum(
        quality_scores[player.player_id] for player in squad.players
    )
    # The additive 22-player score overstates equally strong reserves. Keep a
    # broad safety floor, then let the role-adjusted architecture objective
    # decide whether concentrating money in the usable XI is genuinely better.
    quality_floor = (
        baseline_quality - quality_loss_limit * abs(baseline_quality)
    )
    positions = ("DEFENDER", "MIDFIELDER", "FORWARD")
    candidate_by_position: dict[str, list[Player]] = {
        position: [
            player
            for player in candidates
            if player.position == position
        ]
        for position in positions
    }
    candidate_lineup_scores = {
        player.player_id: (
            raw_scores[player.player_id]
            + starting_scorer_leverage(player)
        )
        for player in candidates
    }
    premium_starter_ids = premium_starter_candidate_ids(
        candidates,
        raw_scores,
    )
    elite_rebound_striker_costs = {
        player.player_id: player.cost
        for player in candidates
        if is_elite_rebound_striker(player)
    }
    qualified_potential_ids = qualified_potential_player_ids(candidates)
    position_minimum_costs = minimum_costs_by_position(candidates)
    defender_ready_reserve_available_count = sum(
        player.position == "DEFENDER"
        and defender_is_direct_backup_ready(player)
        for player in candidates
    )
    midfield_floor_available_count = sum(
        player.position == "MIDFIELDER"
        and player.cost <= position_minimum_costs.get("MIDFIELDER", 0)
        for player in candidates
    )
    midfield_ready_reserve_available_count = sum(
        player.position == "MIDFIELDER"
        and midfielder_is_direct_backup_ready(player)
        for player in candidates
    )
    single_packages: dict[tuple[str, int], list[Player]] = {}
    for position in positions:
        for player in candidate_by_position[position]:
            single_packages.setdefault(
                (position, player.cost),
                [],
            ).append(player)
    for key, values in single_packages.items():
        single_packages[key] = sorted(
            values,
            key=lambda player: (
                -raw_scores[player.player_id],
                player.player_id,
            ),
        )[:40]

    pair_packages: dict[
        tuple[str, str, int], list[tuple[Player, Player]]
    ] = {}
    for first_index, first_position in enumerate(positions):
        for second_position in positions[first_index:]:
            first_players = candidate_by_position[first_position]
            second_players = candidate_by_position[second_position]
            combinations: Iterable[tuple[Player, Player]]
            if first_position == second_position:
                combinations = itertools.combinations(first_players, 2)
            else:
                combinations = itertools.product(
                    first_players,
                    second_players,
                )
            for first, second in combinations:
                pair_packages.setdefault(
                    (
                        first_position,
                        second_position,
                        first.cost + second.cost,
                    ),
                    [],
                ).append((first, second))
    for key, values in pair_packages.items():
        pair_packages[key] = sorted(
            values,
            key=lambda pair: (
                -(
                    raw_scores[pair[0].player_id]
                    + raw_scores[pair[1].player_id]
                ),
                pair[0].player_id,
                pair[1].player_id,
            ),
        )[:300]
    targeted_bench_defense_packages: dict[
        tuple[str, str, int], list[tuple[Player, Player]]
    ] = {}
    for key, packages in pair_packages.items():
        if "DEFENDER" not in key[:2] or not (
            {"MIDFIELDER", "FORWARD"}.intersection(key[:2])
        ):
            continue

        def targeted_package_priority(
            package: tuple[Player, Player],
        ) -> tuple[int, int, float, str, str]:
            defender = next(
                player
                for player in package
                if player.position == "DEFENDER"
            )
            reserve_position_player = next(
                player
                for player in package
                if player.position != "DEFENDER"
            )
            reserve_minimum = position_minimum_costs.get(
                reserve_position_player.position,
                0,
            )
            expensive_ordinary_reserve = (
                reserve_position_player.cost > reserve_minimum
                and reserve_position_player.player_id
                not in qualified_potential_ids
            )
            return (
                int(not defender_is_direct_backup_ready(defender)),
                int(expensive_ordinary_reserve),
                -(
                    raw_scores[defender.player_id]
                    + raw_scores[reserve_position_player.player_id]
                ),
                defender.player_id,
                reserve_position_player.player_id,
            )

        targeted_bench_defense_packages[key] = sorted(
            packages,
            key=targeted_package_priority,
        )[:48]

    # Four-player reallocations use one targeted premium/potential incoming
    # player plus a compact three-player balancing package. Keep the package
    # pool deliberately narrow so this broader search remains fast.
    compact_by_position: dict[str, list[Player]] = {}
    focus_ids = (
        premium_starter_ids
        .union(elite_rebound_striker_costs)
        .union(qualified_potential_ids)
        .union(scorer_leverage_candidate_ids(candidates))
    )
    for position in positions:
        position_players = candidate_by_position[position]
        compact_ids = {
            player.player_id
            for player in sorted(
                position_players,
                key=lambda player: (
                    -raw_scores[player.player_id],
                    player.cost,
                    player.player_id,
                ),
            )[:14]
        }
        compact_ids.update(
            player.player_id
            for player in sorted(
                position_players,
                key=lambda player: (
                    player.cost,
                    -raw_scores[player.player_id],
                    player.player_id,
                ),
            )[:6]
        )
        compact_ids.update(
            player.player_id
            for player in sorted(
                (
                    candidate
                    for candidate in position_players
                    if candidate.player_id in focus_ids
                ),
                key=lambda player: (
                    -raw_scores[player.player_id],
                    player.player_id,
                ),
            )[:8]
        )
        compact_by_position[position] = [
            player
            for player in position_players
            if player.player_id in compact_ids
        ]

    triple_package_heaps: dict[
        tuple[str, str, str, int],
        list[
            tuple[
                float,
                tuple[str, str, str],
                tuple[Player, Player, Player],
            ]
        ],
    ] = {}
    for first_index, first_position in enumerate(positions):
        for second_index in range(first_index, len(positions)):
            second_position = positions[second_index]
            for third_position in positions[second_index:]:
                position_pattern = (
                    first_position,
                    second_position,
                    third_position,
                )
                pools = [
                    compact_by_position[position]
                    for position in position_pattern
                ]
                for package in itertools.product(*pools):
                    if len({player.player_id for player in package}) < 3:
                        continue
                    if any(
                        package[index].player_id
                        >= package[index + 1].player_id
                        for index in range(2)
                        if (
                            position_pattern[index]
                            == position_pattern[index + 1]
                        )
                    ):
                        continue
                    package_key = (
                        *position_pattern,
                        sum(player.cost for player in package),
                    )
                    item = (
                        sum(
                            raw_scores[player.player_id]
                            for player in package
                        ),
                        tuple(player.player_id for player in package),
                        package,
                    )
                    heap = triple_package_heaps.setdefault(
                        package_key,
                        [],
                    )
                    if len(heap) < 160:
                        heapq.heappush(heap, item)
                    elif item[:2] > heap[0][:2]:
                        heapq.heapreplace(heap, item)
    triple_packages: dict[
        tuple[str, str, str, int],
        list[tuple[Player, Player, Player]],
    ] = {
        key: [
            item[2]
            for item in sorted(
                heap,
                key=lambda item: (item[0], item[1]),
                reverse=True,
            )
        ]
        for key, heap in triple_package_heaps.items()
    }

    goalkeeper_blocks: list[tuple[Player, ...]] = []
    if same_club_goalkeepers:
        goalkeeper_count = sum(
            player.position == "GOALKEEPER"
            for player in squad.players
        )
        goalkeepers_by_club: dict[str, list[Player]] = {}
        for player in candidates:
            if player.position == "GOALKEEPER":
                goalkeepers_by_club.setdefault(
                    player.club,
                    [],
                ).append(player)
        for club_players in goalkeepers_by_club.values():
            if len(club_players) < goalkeeper_count:
                continue
            expected_primary = expected_primary_goalkeeper(
                club_players,
                raw_scores,
            )
            for block in itertools.combinations(
                club_players,
                goalkeeper_count,
            ):
                if expected_primary in block:
                    goalkeeper_blocks.append(block)

    metric_cache: dict[frozenset[str], dict[str, Any]] = {}
    architecture_metric_cache_hits = 0

    def architecture_metrics(candidate: Squad) -> dict[str, Any]:
        nonlocal architecture_metric_cache_hits
        cache_key = candidate.ids
        cached = metric_cache.get(cache_key)
        if cached is not None:
            architecture_metric_cache_hits += 1
            return cached
        metrics = squad_architecture_metrics(
            candidate,
            raw_scores,
            maintenance=maintenance,
            min_reliable_anchors=min_reliable_anchors,
            min_attacking_anchors=min_attacking_anchors,
            min_core_budget_share=min_core_budget_share,
            target_core_budget_share=target_core_budget_share,
            min_offensive_premium_anchors=min_offensive_premium_anchors,
            premium_starter_ids=premium_starter_ids,
            elite_rebound_striker_costs=elite_rebound_striker_costs,
            qualified_potential_ids=qualified_potential_ids,
            min_qualified_potential_core=min_qualified_potential_core,
            target_qualified_potential_core=target_qualified_potential_core,
            position_minimum_costs=position_minimum_costs,
            defender_ready_reserve_available_count=(
                defender_ready_reserve_available_count
            ),
            midfield_floor_available_count=(
                midfield_floor_available_count
            ),
            midfield_ready_reserve_available_count=(
                midfield_ready_reserve_available_count
            ),
            variation_exposure=variation_exposure,
            variation_exposure_strength=variation_exposure_strength,
            protected_variation_ids=protected_player_ids,
            variation_reference_squads=variation_reference_squads,
            minimum_variation_distance=minimum_variation_distance,
            maximum_variation_distance=maximum_variation_distance,
            variation_preferences=variation_preferences,
        )
        metric_cache[cache_key] = metrics
        return metrics

    current_metrics = architecture_metrics(current)
    maximum_reachable_core_share = current_metrics["core_budget_share"]
    evaluated_rosters = 1
    triple_swap_rosters_evaluated = 0
    four_swap_rosters_evaluated = 0
    cross_position_pair_rosters_evaluated = 0
    expensive_fourth_forward_counterfactuals_evaluated = 0
    completed_iterations = 0
    marginal_search_complete = False
    position_packages_by_cost: dict[
        tuple[str, int, int], list[tuple[Player, ...]]
    ] = {}
    for iteration in range(max_iterations):
        selected_ids = current.ids
        alternatives: list[
            tuple[float, float, float, Squad, dict[str, Any]]
        ] = []
        seen_rosters: set[frozenset[str]] = set()
        iteration_triple_attempts = 0
        iteration_four_attempts = 0

        def consider(replacement_players: list[Player]) -> None:
            nonlocal maximum_reachable_core_share, evaluated_rosters
            replacement_ids = frozenset(
                player.player_id for player in replacement_players
            )
            if replacement_ids in seen_rosters:
                return
            seen_rosters.add(replacement_ids)
            if not _architecture_candidate_is_legal(
                replacement_players,
                budget=budget,
                club_cap=club_cap,
                min_reliable_anchors=min_reliable_anchors,
                required_player_ids=protected_player_ids,
            ):
                return
            replacement_quality = sum(
                quality_scores[player.player_id]
                for player in replacement_players
            )
            replacement = Squad(
                replacement_players,
                replacement_quality,
            )
            metrics = architecture_metrics(replacement)
            evaluated_rosters += 1
            # A quality corridor may rank two legal squads, but it must never
            # make every hard-gate-compliant architecture unreachable. This
            # matters especially in the Bundesliga, where replacing two
            # costly reserves with price-floor players can create a larger
            # additive 22-player score drop while improving the usable XI.
            repairs_hard_gate = (
                not current_metrics["passes"]
                and metrics["hard_violation_score"]
                < current_metrics["hard_violation_score"]
            )
            if (
                replacement_quality < quality_floor
                and not metrics["passes"]
                and not repairs_hard_gate
            ):
                return
            if (
                not metrics["passes"]
                and current_metrics["passes"]
            ):
                return
            if (
                not metrics["passes"]
                and not current_metrics["passes"]
                and metrics["hard_violation_score"]
                >= current_metrics["hard_violation_score"]
            ):
                return
            maximum_reachable_core_share = max(
                maximum_reachable_core_share,
                metrics["core_budget_share"],
            )
            alternatives.append(
                (
                    metrics["architecture_search_objective"],
                    metrics["expected_contribution"],
                    metrics["core_budget_share"],
                    replacement,
                    metrics,
                )
            )

        def consider_package(
            outgoing: tuple[Player, ...],
            incoming: tuple[Player, ...],
            *,
            package_size: int,
        ) -> None:
            nonlocal triple_swap_rosters_evaluated
            nonlocal four_swap_rosters_evaluated
            nonlocal iteration_triple_attempts
            nonlocal iteration_four_attempts
            if package_size == 3 and iteration_triple_attempts >= 120:
                return
            if package_size == 4 and iteration_four_attempts >= 60:
                return
            outgoing_ids = {player.player_id for player in outgoing}
            incoming_ids = {player.player_id for player in incoming}
            if len(outgoing_ids) != len(outgoing):
                return
            if len(incoming_ids) != len(incoming):
                return
            if incoming_ids.intersection(selected_ids - outgoing_ids):
                return
            outgoing_by_position: dict[str, list[Player]] = {
                position: [] for position in positions
            }
            incoming_by_position: dict[str, list[Player]] = {
                position: [] for position in positions
            }
            for player in outgoing:
                outgoing_by_position[player.position].append(player)
            for player in incoming:
                incoming_by_position[player.position].append(player)
            if any(
                len(outgoing_by_position[position])
                != len(incoming_by_position[position])
                for position in positions
            ):
                return
            replacement_map: dict[str, Player] = {}
            for position in positions:
                for displaced, added in zip(
                    sorted(
                        outgoing_by_position[position],
                        key=lambda player: player.player_id,
                    ),
                    sorted(
                        incoming_by_position[position],
                        key=lambda player: player.player_id,
                    ),
                ):
                    replacement_map[displaced.player_id] = added
            if package_size == 3:
                iteration_triple_attempts += 1
                triple_swap_rosters_evaluated += 1
            elif package_size == 4:
                iteration_four_attempts += 1
                four_swap_rosters_evaluated += 1
            consider(
                [
                    replacement_map.get(player.player_id, player)
                    for player in current.players
                ]
            )

        field_players = [
            player
            for player in current.players
            if player.position != "GOALKEEPER"
        ]
        minimum_forward_cost = position_minimum_costs.get("FORWARD", 0)
        ordered_forwards = sorted(
            (
                player
                for player in current.players
                if player.position == "FORWARD"
            ),
            key=lambda player: (
                -candidate_lineup_scores[player.player_id],
                player.player_id,
            ),
        )
        expensive_fourth_forwards = [
            player
            for index, player in enumerate(ordered_forwards)
            if (
                index >= 3
                and player.cost > minimum_forward_cost
                and player.player_id
                not in current_metrics["player_ids"]
            )
        ]
        minimum_price_forwards = [
            player
            for player in candidate_by_position["FORWARD"]
            if player.cost == minimum_forward_cost
        ]
        # A fourth or fifth forward can never join three other forwards in a
        # legal XI. Exhaustively compare every such premium reserve with a
        # minimum-price forward plus an exact-cost defender or midfielder
        # upgrade before accepting the reserve spend.
        for reserve in expensive_fourth_forwards:
            for cheap_forward in minimum_price_forwards:
                if cheap_forward.player_id in selected_ids:
                    continue
                saving = reserve.cost - cheap_forward.cost
                if saving <= 0:
                    continue
                for incumbent in field_players:
                    if incumbent.position not in {
                        "DEFENDER",
                        "MIDFIELDER",
                    }:
                        continue
                    upgrade_cost = incumbent.cost + saving
                    for upgrade in candidate_by_position[
                        incumbent.position
                    ]:
                        if (
                            upgrade.cost != upgrade_cost
                            or upgrade.player_id in selected_ids
                            or upgrade.player_id
                            == cheap_forward.player_id
                            or candidate_lineup_scores[
                                upgrade.player_id
                            ]
                            <= candidate_lineup_scores[
                                incumbent.player_id
                            ]
                        ):
                            continue
                        expensive_fourth_forward_counterfactuals_evaluated += 1
                        consider(
                            [
                                (
                                    cheap_forward
                                    if player.player_id
                                    == reserve.player_id
                                    else upgrade
                                    if player.player_id
                                    == incumbent.player_id
                                    else player
                                )
                                for player in current.players
                            ]
                        )
        for incumbent in field_players:
            for replacement in single_packages.get(
                (incumbent.position, incumbent.cost),
                [],
            )[:12]:
                if replacement.player_id in selected_ids:
                    continue
                consider(
                    [
                        (
                            replacement
                            if player.player_id == incumbent.player_id
                            else player
                        )
                        for player in current.players
                    ]
                )

        current_goalkeepers = [
            player
            for player in current.players
            if player.position == "GOALKEEPER"
        ]
        current_goalkeeper_ids = {
            player.player_id for player in current_goalkeepers
        }
        current_goalkeeper_cost = sum(
            player.cost for player in current_goalkeepers
        )
        for block in goalkeeper_blocks:
            block_ids = {player.player_id for player in block}
            if block_ids == current_goalkeeper_ids:
                continue
            block_cost = sum(player.cost for player in block)
            if block_cost == current_goalkeeper_cost:
                consider(
                    [
                        player
                        for player in current.players
                        if player.position != "GOALKEEPER"
                    ]
                    + list(block)
                )
            cost_delta = block_cost - current_goalkeeper_cost
            for incumbent in field_players:
                replacement_cost = incumbent.cost - cost_delta
                if replacement_cost <= 0:
                    continue
                for replacement in single_packages.get(
                    (incumbent.position, replacement_cost),
                    [],
                )[:12]:
                    if (
                        replacement.player_id in selected_ids
                        or replacement.player_id in block_ids
                    ):
                        continue
                    consider(
                        [
                            (
                                replacement
                                if (
                                    player.player_id
                                    == incumbent.player_id
                                )
                                else player
                            )
                            for player in current.players
                            if player.position != "GOALKEEPER"
                        ]
                        + list(block)
                    )

        for first, second in itertools.combinations(field_players, 2):
            outgoing_positions = {first.position, second.position}
            current_core_ids = set(current_metrics["player_ids"])
            targets_bench_to_defense_reallocation = (
                "DEFENDER" in outgoing_positions
                and any(
                    player.position in {"MIDFIELDER", "FORWARD"}
                    and player.player_id not in current_core_ids
                    for player in (first, second)
                )
            )
            ordered_positions = tuple(
                sorted(
                    (first.position, second.position),
                    key=positions.index,
                )
            )
            package_key = (
                ordered_positions[0],
                ordered_positions[1],
                first.cost + second.cost,
            )
            if targets_bench_to_defense_reallocation:
                pair_candidates = targeted_bench_defense_packages.get(
                    package_key,
                    pair_packages.get(package_key, [])[:48],
                )
            else:
                pair_candidates = pair_packages.get(
                    package_key,
                    [],
                )[: (80 if not current_metrics["passes"] else 24)]
            for first_replacement, second_replacement in pair_candidates:
                if (
                    first_replacement.player_id in selected_ids
                    or second_replacement.player_id in selected_ids
                ):
                    continue
                replacements_by_position: dict[str, list[Player]] = {
                    position: [] for position in positions
                }
                replacements_by_position[
                    first_replacement.position
                ].append(first_replacement)
                replacements_by_position[
                    second_replacement.position
                ].append(second_replacement)
                outgoing_by_position: dict[str, list[Player]] = {
                    position: [] for position in positions
                }
                outgoing_by_position[first.position].append(first)
                outgoing_by_position[second.position].append(second)
                if any(
                    len(replacements_by_position[position])
                    != len(outgoing_by_position[position])
                    for position in positions
                ):
                    continue
                replacement_map: dict[str, Player] = {}
                for position in positions:
                    for outgoing, incoming in zip(
                        sorted(
                            outgoing_by_position[position],
                            key=lambda player: player.player_id,
                        ),
                        sorted(
                            replacements_by_position[position],
                            key=lambda player: player.player_id,
                        ),
                    ):
                        replacement_map[outgoing.player_id] = incoming
                if targets_bench_to_defense_reallocation:
                    cross_position_pair_rosters_evaluated += 1
                consider(
                    [
                        replacement_map.get(player.player_id, player)
                        for player in current.players
                    ]
                )

        # Search targeted cross-position reallocations. This finds structures
        # such as "premium attacker plus two cheap reserves" that no sequence
        # of exact-cost one-for-one swaps can reach.
        if iteration < 3:
            current_contributions = current_metrics[
                "player_contributions"
            ]
            top_raw_ids = {
                candidate.player_id
                for position in positions
                for candidate in sorted(
                    candidate_by_position[position],
                    key=lambda player: (
                        -raw_scores[player.player_id],
                        player.player_id,
                    ),
                )[:3]
            }
            balancing_pool = sorted(
                field_players,
                key=lambda player: (
                    current_contributions[player.player_id]
                    / max(player.cost / 100_000, 1.0),
                    raw_scores[player.player_id],
                    -player.cost,
                    player.player_id,
                ),
            )[:10]
            targeted_incoming = sorted(
                (
                    player
                    for player in candidates
                    if (
                        player.position != "GOALKEEPER"
                        and player.player_id not in selected_ids
                        and (
                            player.player_id in focus_ids
                            or player.player_id in top_raw_ids
                        )
                    )
                ),
                key=lambda player: (
                    -raw_scores[player.player_id],
                    player.player_id,
                ),
            )[:18]
            for incoming_focus in targeted_incoming:
                primary_outgoing = sorted(
                    (
                        player
                        for player in field_players
                        if player.position == incoming_focus.position
                    ),
                    key=lambda player: (
                        raw_scores[player.player_id],
                        -player.cost,
                        player.player_id,
                    ),
                )[:3]
                for primary in primary_outgoing:
                    other_pool = [
                        player
                        for player in balancing_pool
                        if player.player_id != primary.player_id
                    ]
                    for balancing in itertools.combinations(other_pool, 2):
                        ordered_balancing = tuple(
                            sorted(
                                balancing,
                                key=lambda player: (
                                    positions.index(player.position),
                                    player.player_id,
                                ),
                            )
                        )
                        replacement_cost = (
                            primary.cost
                            + sum(player.cost for player in balancing)
                            - incoming_focus.cost
                        )
                        package_key = (
                            ordered_balancing[0].position,
                            ordered_balancing[1].position,
                            replacement_cost,
                        )
                        for package in pair_packages.get(
                            package_key,
                            [],
                        )[:6]:
                            consider_package(
                                (primary, *balancing),
                                (incoming_focus, *package),
                                package_size=3,
                            )
                    for balancing in itertools.combinations(other_pool, 3):
                        ordered_balancing = tuple(
                            sorted(
                                balancing,
                                key=lambda player: (
                                    positions.index(player.position),
                                    player.player_id,
                                ),
                            )
                        )
                        replacement_cost = (
                            primary.cost
                            + sum(player.cost for player in balancing)
                            - incoming_focus.cost
                        )
                        package_key = (
                            *(player.position for player in ordered_balancing),
                            replacement_cost,
                        )
                        for package in triple_packages.get(
                            package_key,
                            [],
                        )[:4]:
                            consider_package(
                                (primary, *balancing),
                                (incoming_focus, *package),
                                package_size=4,
                            )

        for position in PACKAGE_STARTER_LIMITS:
            current_position_players = [
                player
                for player in current.players
                if player.position == position
            ]
            position_package_key = (
                position,
                len(current_position_players),
                sum(
                    player.cost
                    for player in current_position_players
                ),
            )
            if position_package_key not in position_packages_by_cost:
                position_packages_by_cost[position_package_key] = (
                    position_roster_packages(
                        candidate_by_position[position],
                        raw_scores,
                        position=position,
                        count=position_package_key[1],
                        total_cost=position_package_key[2],
                        maintenance=maintenance,
                        limit=(
                            80
                            if position == "MIDFIELDER"
                            else 200
                        ),
                        qualified_potential_ids=qualified_potential_ids,
                    )
                )
            current_position_ids = {
                player.player_id for player in current_position_players
            }
            other_positions = [
                player
                for player in current.players
                if player.position != position
            ]
            for package in position_packages_by_cost[
                position_package_key
            ]:
                if {
                    player.player_id for player in package
                } == current_position_ids:
                    continue
                consider([*other_positions, *package])

        if not alternatives:
            marginal_search_complete = True
            break
        best = max(
            alternatives,
            key=lambda item: (
                int(item[4]["passes"]),
                -int(item[4]["hard_violation_score"]),
                item[0],
                item[1],
                item[2],
            ),
        )
        if (
            current_metrics["passes"]
            and (
                not best[4]["passes"]
                or best[0]
                <= current_metrics["architecture_search_objective"] + 1e-9
            )
        ):
            marginal_search_complete = True
            break
        if (
            not current_metrics["passes"]
            and not best[4]["passes"]
            and best[4]["hard_violation_score"]
            >= current_metrics["hard_violation_score"]
        ):
            marginal_search_complete = True
            break
        current = best[3]
        current_metrics = best[4]
        completed_iterations = iteration + 1
    else:
        marginal_search_complete = False

    optimizer_reachable_target = min(
        target_core_budget_share,
        maximum_reachable_core_share,
    )
    final_ordered_forwards = sorted(
        (
            player
            for player in current.players
            if player.position == "FORWARD"
        ),
        key=lambda player: (
            -candidate_lineup_scores[player.player_id],
            player.player_id,
        ),
    )
    final_expensive_fourth_forward_ids = sorted(
        player.player_id
        for index, player in enumerate(final_ordered_forwards)
        if (
            index >= 3
            and player.cost
            > position_minimum_costs.get("FORWARD", 0)
            and player.player_id not in current_metrics["player_ids"]
        )
    )
    current.architecture_diagnostics = {
        "model_version": ARCHITECTURE_MODEL_VERSION,
        "passes": bool(
            current_metrics["passes"] and marginal_search_complete
        ),
        "hard_violation_score": int(
            current_metrics["hard_violation_score"]
        ),
        "formation": current_metrics["formation"],
        "player_ids": sorted(current_metrics["player_ids"]),
        "expected_contribution": round(
            current_metrics["expected_contribution"],
            6,
        ),
        "architecture_objective": round(
            current_metrics["architecture_objective"],
            6,
        ),
        "architecture_search_objective": round(
            current_metrics["architecture_search_objective"],
            6,
        ),
        "variation_exposure_adjustment": round(
            current_metrics["variation_exposure_adjustment"],
            6,
        ),
        "requested_core_budget_share_target": (
            target_core_budget_share
        ),
        "optimizer_reachable_core_budget_share_target": (
            optimizer_reachable_target
        ),
        "selected_core_budget_share": current_metrics[
            "core_budget_share"
        ],
        "quality_floor": quality_floor,
        "quality_score": sum(
            quality_scores[player.player_id]
            for player in current.players
        ),
        "quality_loss_limit": quality_loss_limit,
        "bench_usage_weights": current_metrics["bench_usage_weights"],
        "bench_slot_usage_weights": current_metrics[
            "bench_slot_usage_weights"
        ],
        "position_core_budget": current_metrics[
            "position_core_budget"
        ],
        "forward_core_spend": current_metrics["forward_core_spend"],
        "forward_reserve_spend": current_metrics[
            "forward_reserve_spend"
        ],
        "forward_core_budget_share": current_metrics[
            "forward_core_budget_share"
        ],
        "forward_core_budget_target": current_metrics[
            "forward_core_budget_target"
        ],
        "forward_core_budget_target_met": current_metrics[
            "forward_core_budget_target_met"
        ],
        "midfield_core_spend": current_metrics["midfield_core_spend"],
        "midfield_reserve_spend": current_metrics[
            "midfield_reserve_spend"
        ],
        "midfield_core_budget_share": current_metrics[
            "midfield_core_budget_share"
        ],
        "midfield_core_budget_target": current_metrics[
            "midfield_core_budget_target"
        ],
        "midfield_core_budget_target_met": current_metrics[
            "midfield_core_budget_target_met"
        ],
        "premium_starter_candidate_ids": current_metrics[
            "premium_starter_candidate_ids"
        ],
        "premium_starter_ids": current_metrics["premium_starter_ids"],
        "premium_starter_target": current_metrics[
            "premium_starter_target"
        ],
        "premium_starter_target_met": current_metrics[
            "premium_starter_target_met"
        ],
        "elite_rebound_striker_candidate_ids": current_metrics[
            "elite_rebound_striker_candidate_ids"
        ],
        "elite_rebound_striker_core_ids": current_metrics[
            "elite_rebound_striker_core_ids"
        ],
        "elite_rebound_striker_target_met": current_metrics[
            "elite_rebound_striker_target_met"
        ],
        "elite_rebound_required_increment": current_metrics[
            "elite_rebound_required_increment"
        ],
        "offensive_reserve_excess_budget": current_metrics[
            "offensive_reserve_excess_budget"
        ],
        "elite_rebound_financeable_from_reserves": current_metrics[
            "elite_rebound_financeable_from_reserves"
        ],
        "elite_rebound_reallocation_adjustment": current_metrics[
            "elite_rebound_reallocation_adjustment"
        ],
        "qualified_potential_candidate_ids": current_metrics[
            "qualified_potential_candidate_ids"
        ],
        "qualified_potential_core_ids": current_metrics[
            "qualified_potential_core_ids"
        ],
        "qualified_potential_available": current_metrics[
            "qualified_potential_available"
        ],
        "qualified_potential_core_count": current_metrics[
            "qualified_potential_core_count"
        ],
        "qualified_potential_core_minimum": current_metrics[
            "qualified_potential_core_minimum"
        ],
        "qualified_potential_core_target": current_metrics[
            "qualified_potential_core_target"
        ],
        "qualified_potential_core_minimum_met": current_metrics[
            "qualified_potential_core_minimum_met"
        ],
        "qualified_potential_core_target_met": current_metrics[
            "qualified_potential_core_target_met"
        ],
        "qualified_potential_starter_ids": current_metrics[
            "qualified_potential_starter_ids"
        ],
        "qualified_potential_starter_count": current_metrics[
            "qualified_potential_starter_count"
        ],
        "qualified_potential_starter_minimum": current_metrics[
            "qualified_potential_starter_minimum"
        ],
        "qualified_potential_starter_minimum_met": current_metrics[
            "qualified_potential_starter_minimum_met"
        ],
        "qualified_potential_starter_deficit": current_metrics[
            "qualified_potential_starter_deficit"
        ],
        "potential_core_adjustment": current_metrics[
            "potential_core_adjustment"
        ],
        "scorer_leverage": current_metrics["scorer_leverage"],
        "starting_scorer_leverage": current_metrics[
            "starting_scorer_leverage"
        ],
        "defender_spend": current_metrics["defender_spend"],
        "defender_spend_share": current_metrics[
            "defender_spend_share"
        ],
        "defender_spend_soft_cap": current_metrics[
            "defender_spend_soft_cap"
        ],
        "defender_scorer_credit": current_metrics[
            "defender_scorer_credit"
        ],
        "offensive_scorer_opportunity_available": current_metrics[
            "offensive_scorer_opportunity_available"
        ],
        "defensive_overspend_adjustment": current_metrics[
            "defensive_overspend_adjustment"
        ],
        "formation_flexibility_adjustment": current_metrics[
            "formation_flexibility_adjustment"
        ],
        "formation_flexibility": current_metrics[
            "formation_flexibility"
        ],
        "defender_architecture": current_metrics[
            "defender_architecture"
        ],
        "midfield_architecture": current_metrics[
            "midfield_architecture"
        ],
        "forward_reserve_architecture": current_metrics[
            "forward_reserve_architecture"
        ],
        "squad_average_age": current_metrics["squad_average_age"],
        "starting_xi_average_age": current_metrics[
            "starting_xi_average_age"
        ],
        "starting_u23_count": current_metrics["starting_u23_count"],
        "player_contributions": current_metrics[
            "player_contributions"
        ],
        "player_usage_weights": current_metrics["player_usage_weights"],
        "evaluated_rosters": evaluated_rosters,
        "triple_swap_rosters_evaluated": (
            triple_swap_rosters_evaluated
        ),
        "four_swap_rosters_evaluated": four_swap_rosters_evaluated,
        "cross_position_pair_rosters_evaluated": (
            cross_position_pair_rosters_evaluated
        ),
        "expensive_fourth_forward_ids": (
            final_expensive_fourth_forward_ids
        ),
        "expensive_fourth_forward_counterfactuals_evaluated": (
            expensive_fourth_forward_counterfactuals_evaluated
        ),
        "expensive_fourth_forward_justified": bool(
            marginal_search_complete
            and current_metrics["forward_reserve_architecture"]["passes"]
        ),
        "architecture_metric_cache_hits": (
            architecture_metric_cache_hits
        ),
        "unique_architecture_rosters": len(metric_cache),
        "marginal_reallocation_audit": {
            "search_complete": marginal_search_complete,
            "dominated_final_roster": (
                False if marginal_search_complete else None
            ),
            "scope": (
                "exact-cost single, pair, position, targeted three- "
                "and four-player packages"
            ),
        },
        "improvement_iterations": completed_iterations,
    }
    return current


def rebalance_full_budget_core(
    squad: Squad,
    candidates: list[Player],
    quality_scores: Mapping[str, float],
    core_scores: dict[str, float],
    *,
    budget: int,
    club_cap: int,
    min_reliable_anchors: int,
    min_attacking_anchors: int,
    min_core_budget_share: float,
    target_core_budget_share: float,
    quality_floor: float,
    min_offensive_premium_anchors: int = 0,
) -> Squad:
    """Move money from a reserve to a starter without changing total spend."""

    if squad.cost != budget or target_core_budget_share <= 0:
        return squad
    current = squad
    by_position: dict[str, list[Player]] = {
        position: [
            player
            for player in candidates
            if player.position == position
        ]
        for position in DEFAULT_SLOTS
    }
    for _ in range(len(current.players)):
        audit = reliable_core_audit(
            current,
            core_scores,
            min_reliable_anchors,
            min_attacking_anchors,
            min_core_budget_share,
            min_offensive_premium_anchors,
        )
        if audit["core_budget_share"] >= target_core_budget_share:
            break
        selected_ids = current.ids
        core_ids = set(audit["player_ids"])
        upgrade_options: dict[
            tuple[str, int], list[tuple[Player, Player]]
        ] = {}
        for incumbent in current.players:
            if (
                incumbent.player_id not in core_ids
                or incumbent.position == "GOALKEEPER"
            ):
                continue
            for candidate in by_position[incumbent.position]:
                extra_cost = candidate.cost - incumbent.cost
                if (
                    extra_cost <= 0
                    or candidate.player_id in selected_ids
                    or core_scores[candidate.player_id]
                    <= core_scores[incumbent.player_id]
                ):
                    continue
                upgrade_options.setdefault(
                    (incumbent.position, extra_cost),
                    [],
                ).append((incumbent, candidate))

        alternatives: list[tuple[float, float, Squad]] = []
        for reserve in current.players:
            if (
                reserve.player_id in core_ids
                or reserve.position == "GOALKEEPER"
            ):
                continue
            for cheaper in by_position[reserve.position]:
                saving = reserve.cost - cheaper.cost
                if (
                    saving <= 0
                    or cheaper.player_id in selected_ids
                    or core_scores[cheaper.player_id]
                    > core_scores[reserve.player_id]
                ):
                    continue
                for position in ("DEFENDER", "MIDFIELDER", "FORWARD"):
                    for incumbent, premium in upgrade_options.get(
                        (position, saving),
                        [],
                    ):
                        if premium.player_id == cheaper.player_id:
                            continue
                        replacement_players = [
                            (
                                cheaper
                                if player.player_id == reserve.player_id
                                else premium
                                if player.player_id == incumbent.player_id
                                else player
                            )
                            for player in current.players
                        ]
                        if len(
                            {
                                player.player_id
                                for player in replacement_players
                            }
                        ) != len(replacement_players):
                            continue
                        club_counts = Counter(
                            player.club
                            for player in replacement_players
                            if player.position != "GOALKEEPER"
                        )
                        if any(
                            count > club_cap
                            for count in club_counts.values()
                        ):
                            continue
                        replacement_score = sum(
                            quality_scores[player.player_id]
                            for player in replacement_players
                        )
                        if replacement_score < quality_floor:
                            continue
                        replacement = Squad(
                            replacement_players,
                            replacement_score,
                        )
                        if replacement.cost != budget:
                            continue
                        replacement_audit = reliable_core_audit(
                            replacement,
                            core_scores,
                            min_reliable_anchors,
                            min_attacking_anchors,
                            min_core_budget_share,
                            min_offensive_premium_anchors,
                        )
                        if (
                            not replacement_audit["passes"]
                            or premium.player_id
                            not in replacement_audit["player_ids"]
                            or cheaper.player_id
                            in replacement_audit["player_ids"]
                            or replacement_audit["core_budget_share"]
                            <= audit["core_budget_share"]
                        ):
                            continue
                        alternatives.append(
                            (
                                replacement_audit["core_budget_share"],
                                replacement_score,
                                replacement,
                            )
                        )
        if not alternatives:
            break
        _, _, current = max(
            alternatives,
            key=lambda item: (item[0], item[1]),
        )
    return current


def repair_core_budget_share(
    squad: Squad,
    candidates: list[Player],
    quality_scores: Mapping[str, float],
    core_scores: dict[str, float],
    *,
    club_cap: int,
    min_reliable_anchors: int,
    min_attacking_anchors: int,
    min_core_budget_share: float,
    quality_floor: float,
    minimum_spend: int = 0,
    min_offensive_premium_anchors: int = 0,
    protected_player_ids: AbstractSet[str] = frozenset(),
) -> Squad | None:
    """Replace expensive reserves with the best safe cheaper alternatives."""

    current = squad
    candidate_by_position: dict[str, list[Player]] = {
        position: sorted(
            (
                player
                for player in candidates
                if player.position == position
            ),
            key=lambda player: (
                -quality_scores[player.player_id],
                player.cost,
                player.player_id,
            ),
        )
        for position in DEFAULT_SLOTS
    }
    for _ in range(2 * len(current.players)):
        audit = reliable_core_audit(
            current,
            core_scores,
            min_reliable_anchors,
            min_attacking_anchors,
            min_core_budget_share,
            min_offensive_premium_anchors,
        )
        if audit["passes"]:
            return current
        selected_ids = current.ids
        core_ids = set(audit["player_ids"])
        club_counts = Counter(
            player.club
            for player in current.players
            if player.position != "GOALKEEPER"
        )
        alternatives: list[
            tuple[float, float, int, Squad]
        ] = []
        for reserve in current.players:
            if (
                reserve.player_id in core_ids
                or reserve.player_id in protected_player_ids
                or reserve.position == "GOALKEEPER"
            ):
                continue
            for candidate in candidate_by_position[reserve.position]:
                # A same-position replacement no stronger than a non-core
                # reserve cannot displace the already optimal starting eleven.
                # Its anchor counts and core cost therefore remain invariant.
                if (
                    candidate.player_id in selected_ids
                    or candidate.cost >= reserve.cost
                    or core_scores[candidate.player_id]
                    > core_scores[reserve.player_id]
                ):
                    continue
                if (
                    candidate.club != reserve.club
                    and club_counts[candidate.club] >= club_cap
                ):
                    continue
                replacement_players = [
                    candidate if player.player_id == reserve.player_id else player
                    for player in current.players
                ]
                replacement = Squad(
                    replacement_players,
                    sum(
                        quality_scores[player.player_id]
                        for player in replacement_players
                    ),
                )
                if replacement.cost < minimum_spend:
                    continue
                replacement_score = sum(
                    quality_scores[player.player_id]
                    for player in replacement_players
                )
                if replacement_score < quality_floor:
                    continue
                replacement_audit = dict(audit)
                replacement_audit["core_budget_share"] = (
                    float(audit["core_budget"])
                    / max(replacement.cost, 1)
                )
                replacement_audit["passes"] = (
                    replacement_audit["reliable_anchors"]
                    >= min_reliable_anchors
                    and replacement_audit["attacking_anchors"]
                    >= min_attacking_anchors
                    and replacement_audit["offensive_premium_anchors"]
                    >= min_offensive_premium_anchors
                    and replacement_audit["core_budget_share"]
                    >= min_core_budget_share
                )
                if (
                    replacement_audit["reliable_anchors"]
                    < min_reliable_anchors
                    or replacement_audit["attacking_anchors"]
                    < min_attacking_anchors
                    or replacement_audit["offensive_premium_anchors"]
                    < min_offensive_premium_anchors
                    or replacement_audit["core_budget_share"]
                    <= audit["core_budget_share"]
                ):
                    continue
                alternatives.append(
                    (
                        replacement_score,
                        replacement_audit["core_budget_share"],
                        reserve.cost - candidate.cost,
                        replacement,
                    )
                )
        if not alternatives:
            return None
        _, _, _, current = max(
            alternatives,
            key=lambda item: (
                item[0],
                item[1],
                item[2],
            ),
        )
    return None


def upgrade_core_with_remaining_budget(
    squad: Squad,
    candidates: list[Player],
    quality_scores: Mapping[str, float],
    core_scores: dict[str, float],
    *,
    budget: int,
    club_cap: int,
    min_reliable_anchors: int,
    min_attacking_anchors: int,
    min_core_budget_share: float,
    min_offensive_premium_anchors: int = 0,
    protected_player_ids: AbstractSet[str] = frozenset(),
) -> Squad:
    """Spend remaining budget only on safe, stronger starting-core upgrades."""

    current = squad
    for _ in range(len(current.players)):
        remaining_budget = budget - current.cost
        if remaining_budget < 0:
            break
        audit = reliable_core_audit(
            current,
            core_scores,
            min_reliable_anchors,
            min_attacking_anchors,
            min_core_budget_share,
            min_offensive_premium_anchors,
        )
        core_ids = set(audit["player_ids"])
        selected_ids = current.ids
        club_counts = Counter(
            player.club
            for player in current.players
            if player.position != "GOALKEEPER"
        )
        alternatives: list[tuple[float, float, int, Squad]] = []
        for incumbent in current.players:
            if (
                incumbent.player_id not in core_ids
                or incumbent.player_id in protected_player_ids
                or incumbent.position == "GOALKEEPER"
            ):
                continue
            for candidate in candidates:
                if (
                    candidate.position != incumbent.position
                    or candidate.player_id in selected_ids
                    or candidate.cost < incumbent.cost
                    or candidate.cost - incumbent.cost > remaining_budget
                    or core_scores[candidate.player_id]
                    <= core_scores[incumbent.player_id]
                    or quality_scores[candidate.player_id]
                    < quality_scores[incumbent.player_id]
                ):
                    continue
                candidate_club_count = club_counts[candidate.club]
                if candidate.club == incumbent.club:
                    candidate_club_count -= 1
                if candidate_club_count >= club_cap:
                    continue
                replacement_players = [
                    candidate if player.player_id == incumbent.player_id else player
                    for player in current.players
                ]
                replacement = Squad(
                    replacement_players,
                    sum(
                        quality_scores[player.player_id]
                        for player in replacement_players
                    ),
                )
                replacement_audit = reliable_core_audit(
                    replacement,
                    core_scores,
                    min_reliable_anchors,
                    min_attacking_anchors,
                    min_core_budget_share,
                    min_offensive_premium_anchors,
                )
                if (
                    not replacement_audit["passes"]
                    or candidate.player_id
                    not in replacement_audit["player_ids"]
                ):
                    continue
                alternatives.append(
                    (
                        core_scores[candidate.player_id]
                        - core_scores[incumbent.player_id],
                        quality_scores[candidate.player_id]
                        - quality_scores[incumbent.player_id],
                        -(candidate.cost - incumbent.cost),
                        replacement,
                    )
                )
        if not alternatives:
            break
        _, _, _, current = max(
            alternatives,
            key=lambda item: (item[0], item[1], item[2]),
        )
    return current


def finalize_reliable_core_architecture(
    squad: Squad,
    candidates: list[Player],
    quality_scores: Mapping[str, float],
    core_scores: dict[str, float],
    *,
    budget: int,
    club_cap: int,
    min_reliable_anchors: int,
    min_attacking_anchors: int,
    min_core_budget_share: float,
    target_core_budget_share: float = 0.0,
    minimum_spend: int = 0,
    min_offensive_premium_anchors: int = 0,
    min_qualified_potential_core: int = 0,
    target_qualified_potential_core: int = 0,
    maintenance: str = "low",
    same_club_goalkeepers: bool = True,
    protected_player_ids: AbstractSet[str] = frozenset(),
    search_premium_restarts: bool = False,
    variation_exposure: Mapping[str, int] | None = None,
    variation_exposure_strength: float = 0.0,
    variation_reference_squads: Sequence[AbstractSet[str]] = (),
    minimum_variation_distance: int = 0,
    maximum_variation_distance: int | None = None,
    variation_preferences: Mapping[str, float] | None = None,
) -> Squad:
    """Apply the same core-first architecture to a squad and its reference."""

    current = squad
    roster_slots = Counter(player.position for player in current.players)
    bounded_candidates = strategic_optimization_pool(
        candidates,
        core_scores,
        roster_slots,
    )
    bounded_ids = {
        player.player_id for player in bounded_candidates
    }
    required_candidate_ids = set(current.ids).union(protected_player_ids)
    if not required_candidate_ids.issubset(bounded_ids):
        bounded_candidates = [
            *bounded_candidates,
            *(
                player
                for player in candidates
                if (
                    player.player_id in required_candidate_ids
                    and player.player_id not in bounded_ids
                )
            ),
        ]
    audit = reliable_core_audit(
        current,
        core_scores,
        min_reliable_anchors,
        min_attacking_anchors,
        min_core_budget_share,
        min_offensive_premium_anchors,
    )
    if not audit["passes"]:
        repaired = repair_core_budget_share(
            current,
            bounded_candidates,
            quality_scores,
            core_scores,
            club_cap=club_cap,
            min_reliable_anchors=min_reliable_anchors,
            min_attacking_anchors=min_attacking_anchors,
            min_core_budget_share=min_core_budget_share,
            quality_floor=float("-inf"),
            minimum_spend=minimum_spend,
            min_offensive_premium_anchors=0,
            protected_player_ids=protected_player_ids,
        )
        if repaired is not None:
            current = repaired
    current = upgrade_core_with_remaining_budget(
        current,
        bounded_candidates,
        quality_scores,
        core_scores,
        budget=budget,
        club_cap=club_cap,
        min_reliable_anchors=min_reliable_anchors,
        min_attacking_anchors=min_attacking_anchors,
        min_core_budget_share=min_core_budget_share,
        min_offensive_premium_anchors=min_offensive_premium_anchors,
        protected_player_ids=protected_player_ids,
    )
    optimized = optimize_joint_squad_architecture(
        current,
        bounded_candidates,
        quality_scores,
        core_scores,
        budget=budget,
        club_cap=club_cap,
        maintenance=maintenance,
        min_reliable_anchors=min_reliable_anchors,
        min_attacking_anchors=min_attacking_anchors,
        min_core_budget_share=min_core_budget_share,
        target_core_budget_share=target_core_budget_share,
        min_offensive_premium_anchors=min_offensive_premium_anchors,
        min_qualified_potential_core=min_qualified_potential_core,
        target_qualified_potential_core=target_qualified_potential_core,
        same_club_goalkeepers=same_club_goalkeepers,
        protected_player_ids=protected_player_ids,
        variation_exposure=variation_exposure,
        variation_exposure_strength=variation_exposure_strength,
        variation_reference_squads=variation_reference_squads,
        minimum_variation_distance=minimum_variation_distance,
        maximum_variation_distance=maximum_variation_distance,
        variation_preferences=variation_preferences,
    )
    if not search_premium_restarts:
        return optimized

    selected_ids = optimized.ids
    restart_seeds: list[tuple[float, Squad]] = []
    for incumbent in optimized.players:
        if (
            incumbent.position not in {"MIDFIELDER", "FORWARD"}
            or incumbent.player_id in protected_player_ids
            or not is_offensive_premium_anchor(incumbent)
        ):
            continue
        for candidate in bounded_candidates:
            if (
                candidate.player_id in selected_ids
                or candidate.position != incumbent.position
                or candidate.cost != incumbent.cost
                or not is_offensive_premium_anchor(candidate)
                or core_scores[candidate.player_id]
                < 0.94 * core_scores[incumbent.player_id]
            ):
                continue
            replacement_players = [
                (
                    candidate
                    if player.player_id == incumbent.player_id
                    else player
                )
                for player in optimized.players
            ]
            if not _architecture_candidate_is_legal(
                replacement_players,
                budget=budget,
                club_cap=club_cap,
                min_reliable_anchors=min_reliable_anchors,
                required_player_ids=protected_player_ids,
            ):
                continue
            restart_seeds.append(
                (
                    core_scores[candidate.player_id]
                    - core_scores[incumbent.player_id],
                    Squad(
                        replacement_players,
                        sum(
                            quality_scores[player.player_id]
                            for player in replacement_players
                        ),
                    ),
                )
            )

    best = optimized
    best_objective = float(
        optimized.architecture_diagnostics.get(
            "architecture_search_objective",
            optimized.architecture_diagnostics.get(
                "architecture_objective",
                float("-inf"),
            ),
        )
    )
    evaluated_restarts = 0
    seen_restart_ids: set[frozenset[str]] = set()
    for _, seed in sorted(
        restart_seeds,
        key=lambda item: (
            -item[0],
            tuple(sorted(item[1].ids)),
        ),
    ):
        if seed.ids in seen_restart_ids:
            continue
        seen_restart_ids.add(seed.ids)
        evaluated_restarts += 1
        restarted = optimize_joint_squad_architecture(
            seed,
            bounded_candidates,
            quality_scores,
            core_scores,
            budget=budget,
            club_cap=club_cap,
            maintenance=maintenance,
            min_reliable_anchors=min_reliable_anchors,
            min_attacking_anchors=min_attacking_anchors,
            min_core_budget_share=min_core_budget_share,
            target_core_budget_share=target_core_budget_share,
            min_offensive_premium_anchors=min_offensive_premium_anchors,
            min_qualified_potential_core=min_qualified_potential_core,
            target_qualified_potential_core=target_qualified_potential_core,
            same_club_goalkeepers=same_club_goalkeepers,
            protected_player_ids=protected_player_ids,
            variation_exposure=variation_exposure,
            variation_exposure_strength=variation_exposure_strength,
            variation_reference_squads=variation_reference_squads,
            minimum_variation_distance=minimum_variation_distance,
            maximum_variation_distance=maximum_variation_distance,
            variation_preferences=variation_preferences,
        )
        restarted_objective = float(
            restarted.architecture_diagnostics.get(
                "architecture_search_objective",
                restarted.architecture_diagnostics.get(
                    "architecture_objective",
                    float("-inf"),
                ),
            )
        )
        if restarted_objective > best_objective + 1e-9:
            best = restarted
            best_objective = restarted_objective
        if evaluated_restarts >= 4:
            break
    best.architecture_diagnostics["premium_restarts_evaluated"] = (
        evaluated_restarts
    )
    return best


def expected_primary_goalkeeper(
    club_players: list[Player],
    scores: Mapping[str, float],
) -> Player:
    """Return the keeper whose current evidence most strongly projects starts."""

    hierarchy_leaders = [
        player
        for player in club_players
        if player.goalkeeper_outlook.get("club_rank") == 1
    ]
    if hierarchy_leaders:
        return max(
            hierarchy_leaders,
            key=lambda player: (
                numeric(
                    player.goalkeeper_outlook.get(
                        "starter_probability"
                    )
                ),
                numeric(
                    player.goalkeeper_outlook.get("hierarchy_score")
                ),
                scores[player.player_id],
                -player.cost,
                player.name,
            ),
        )
    return max(
        club_players,
        key=lambda player: (
            0.50 * player.components["minutes"]
            + 0.35 * player.components["role"]
            + 0.15 * player.components["upside"],
            scores[player.player_id],
            -player.cost,
            player.name,
        ),
    )


def goalkeeper_block_assessment(
    club_players: list[Player],
    scores: Mapping[str, float],
    maintenance: str,
    *,
    require_hierarchy: bool,
) -> tuple[bool, list[str], Player]:
    primary = expected_primary_goalkeeper(club_players, scores)
    outlook = primary.goalkeeper_outlook
    if not goalkeeper_outlook_is_complete(outlook):
        return (
            not require_hierarchy,
            (
                []
                if not require_hierarchy
                else ["keine vollständige Torwarthierarchie"]
            ),
            primary,
        )
    thresholds = {
        "low": (70.0, 40.0, {"medium", "high"}),
        "normal": (60.0, 55.0, {"medium", "high"}),
        "active": (48.0, 70.0, {"low", "medium", "high"}),
    }
    minimum_probability, maximum_external_risk, confidences = thresholds[
        maintenance
    ]
    reasons: list[str] = []
    probability = numeric(outlook.get("starter_probability"))
    external_risk = numeric(outlook.get("external_signing_risk"), 100.0)
    confidence = str(outlook.get("confidence", "low"))
    status = str(outlook.get("status", "open_competition"))
    if probability < minimum_probability:
        reasons.append(
            f"Stammplatzwahrscheinlichkeit nur {probability:.0f}%"
        )
    if external_risk > maximum_external_risk:
        reasons.append(
            f"Risiko eines externen Stammkeepers {external_risk:.0f}%"
        )
    if confidence not in confidences:
        reasons.append(f"Hierarchiesicherheit nur {confidence}")
    if maintenance == "low" and status not in {
        "confirmed_starter",
        "clear_favourite",
        "likely_starter",
    }:
        reasons.append(f"Torwartstatus {status}")
    if maintenance == "normal" and status == "external_signing_risk":
        reasons.append("konkretes externes Besetzungsrisiko")
    return not reasons, reasons, primary


def filter_goalkeeper_blocks_by_hierarchy(
    players: list[Player],
    scores: Mapping[str, float],
    *,
    count: int,
    maintenance: str,
    require_hierarchy: bool,
) -> tuple[list[Player], list[dict[str, Any]], int]:
    by_club: dict[str, list[Player]] = {}
    for player in players:
        if player.position == "GOALKEEPER":
            by_club.setdefault(player.club, []).append(player)
    permitted_clubs: set[str] = set()
    exclusions: list[dict[str, Any]] = []
    for club, club_players in by_club.items():
        if len(club_players) < count:
            continue
        allowed, reasons, primary = goalkeeper_block_assessment(
            club_players,
            scores,
            maintenance,
            require_hierarchy=require_hierarchy,
        )
        if allowed:
            permitted_clubs.add(club)
            continue
        exclusions.append(
            {
                "annotation_key": f"goalkeeper-club:{club}",
                "reason": "; ".join(reasons),
                "benchmark": False,
                "evidence": list(primary.evidence),
                "expected_primary": primary.name,
                "goalkeeper_outlook": dict(
                    primary.goalkeeper_outlook
                ),
            }
        )
    filtered = [
        player
        for player in players
        if player.position != "GOALKEEPER"
        or player.club in permitted_clubs
    ]
    return filtered, exclusions, len(permitted_clubs)


def goalkeeper_options(
    players: list[Player],
    count: int,
    budget: int,
    scores: dict[str, float],
    same_club: bool,
) -> dict[int, tuple[float, tuple[Player, ...]]]:
    by_club: dict[str, list[Player]] = {}
    for player in players:
        if player.position == "GOALKEEPER":
            by_club.setdefault(player.club, []).append(player)
    options: dict[int, tuple[float, tuple[Player, ...]]] = {}
    candidate_groups = (
        list(by_club.values())
        if same_club
        else [[player for club_players in by_club.values() for player in club_players]]
    )
    for club_players in candidate_groups:
        expected_primary = (
            expected_primary_goalkeeper(club_players, scores)
            if same_club
            else None
        )
        for combination in itertools.combinations(club_players, count):
            if expected_primary is not None and expected_primary not in combination:
                continue
            cost = sum(player.cost for player in combination)
            if cost > budget:
                continue
            score = sum(scores[player.player_id] for player in combination)
            current = options.get(cost)
            if current is None or score > current[0]:
                options[cost] = (score, combination)
    return options


def club_outfield_options(
    players: list[Player],
    slots: dict[str, int],
    club_cap: int,
    budget: int,
    scores: dict[str, float],
    min_reliable_anchors: int = 0,
) -> dict[
    tuple[int, int, int, int, int],
    tuple[float, tuple[Player, ...]],
]:
    """Enumerate the exact useful selections for one club."""

    positions = ("DEFENDER", "MIDFIELDER", "FORWARD")
    position_index = {position: index for index, position in enumerate(positions)}
    states: dict[
        tuple[int, int, int, int, int],
        tuple[float, tuple[Player, ...]],
    ] = {(0, 0, 0, 0, 0): (0.0, ())}
    for player in players:
        index = position_index[player.position]
        next_states = dict(states)
        for key, (score, selected) in states.items():
            counts = list(key[:3])
            if sum(counts) >= club_cap or counts[index] >= slots[player.position]:
                continue
            new_cost = key[3] + player.cost
            if new_cost > budget:
                continue
            counts[index] += 1
            anchors = min(
                min_reliable_anchors,
                key[4] + int(player.reliable_anchor),
            )
            new_key = (counts[0], counts[1], counts[2], new_cost, anchors)
            new_score = score + scores[player.player_id]
            current = next_states.get(new_key)
            if current is None or new_score > current[0]:
                next_states[new_key] = (new_score, selected + (player,))
        states = next_states
    return states


def outfield_options(
    players: list[Player],
    slots: dict[str, int],
    club_cap: int,
    budget: int,
    scores: dict[str, float],
    min_reliable_anchors: int = 0,
) -> dict[tuple[int, int], tuple[float, tuple[Player, ...]]]:
    """Return the exact best cap-compliant outfield selection per cost.

    Processing one club at a time makes the cap local. Once a club has been
    merged, equal position-and-cost states can safely retain only the
    highest-scoring selection.
    """

    by_club: dict[str, list[Player]] = {}
    for player in players:
        if player.position != "GOALKEEPER":
            by_club.setdefault(player.club, []).append(player)

    states: dict[
        tuple[int, int, int, int, int],
        tuple[float, tuple[Player, ...]],
    ] = {(0, 0, 0, 0, 0): (0.0, ())}
    target_counts = (
        slots["DEFENDER"],
        slots["MIDFIELDER"],
        slots["FORWARD"],
    )
    for club in sorted(by_club):
        local_options = club_outfield_options(
            by_club[club],
            slots,
            club_cap,
            budget,
            scores,
            min_reliable_anchors,
        )
        next_states: dict[
            tuple[int, int, int, int, int],
            tuple[float, tuple[Player, ...]],
        ] = {}
        for base_key, (base_score, base_players) in states.items():
            for local_key, (local_score, local_players) in local_options.items():
                defender_count = base_key[0] + local_key[0]
                midfielder_count = base_key[1] + local_key[1]
                forward_count = base_key[2] + local_key[2]
                if (
                    defender_count > target_counts[0]
                    or midfielder_count > target_counts[1]
                    or forward_count > target_counts[2]
                ):
                    continue
                total_cost = base_key[3] + local_key[3]
                if total_cost > budget:
                    continue
                anchors = base_key[4] + local_key[4]
                if anchors > min_reliable_anchors:
                    anchors = min_reliable_anchors
                new_key = (
                    defender_count,
                    midfielder_count,
                    forward_count,
                    total_cost,
                    anchors,
                )
                total_score = base_score + local_score
                current = next_states.get(new_key)
                if current is None or total_score > current[0]:
                    next_states[new_key] = (
                        total_score,
                        base_players + local_players,
                    )
        states = next_states
        if not states:
            return {}

    return {
        (key[3], key[4]): value
        for key, value in states.items()
        if key[:3] == target_counts
    }


def combine_options(
    goalkeeper_group: dict[int, tuple[float, tuple[Player, ...]]],
    field_group: dict[tuple[int, int], tuple[float, tuple[Player, ...]]],
    budget: int,
    minimum_spend: int,
    min_reliable_anchors: int = 0,
) -> tuple[Squad | None, int]:
    states: dict[
        tuple[int, int],
        tuple[float, tuple[Player, ...]],
    ] = {}
    for goalkeeper_cost, (goalkeeper_score, goalkeepers) in goalkeeper_group.items():
        for (field_cost, anchors), (field_score, fielders) in field_group.items():
            total_cost = goalkeeper_cost + field_cost
            if total_cost > budget:
                continue
            key = (total_cost, anchors)
            total_score = goalkeeper_score + field_score
            current = states.get(key)
            if current is None or total_score > current[0]:
                states[key] = (total_score, goalkeepers + fielders)
    spend_eligible = {
        key: value for key, value in states.items() if key[0] >= minimum_spend
    }
    max_reachable = max((key[1] for key in spend_eligible), default=0)
    eligible_states = {
        key: value
        for key, value in spend_eligible.items()
        if key[1] >= min_reliable_anchors
    }
    if not eligible_states:
        return None, max_reachable
    _, (score, selected) = max(
        eligible_states.items(),
        key=lambda item: item[1][0],
    )
    return Squad(list(selected), score), max_reachable


def optimizer_cache_key(
    players: Iterable[Player],
    scores: Mapping[str, float],
    budget: int,
    club_cap: int,
    minimum_spend: int,
    slots: Mapping[str, int],
    same_club_goalkeepers: bool,
    min_reliable_anchors: int,
) -> str:
    """Hash every input that can affect the seed-independent optimum."""

    payload = {
        "algorithm": OPTIMIZER_ALGORITHM_VERSION,
        "players": [
            {
                "id": player.player_id,
                "club": player.club,
                "position": player.position,
                "cost": player.cost,
                "reliable_anchor": player.reliable_anchor,
                "score": float(scores[player.player_id]).hex(),
                "goalkeeper_outlook": (
                    player.goalkeeper_outlook
                    if player.position == "GOALKEEPER"
                    else None
                ),
                "scorer_leverage": starting_scorer_leverage(player),
            }
            for player in sorted(players, key=lambda player: player.player_id)
        ],
        "budget": budget,
        "club_cap": club_cap,
        "minimum_spend": minimum_spend,
        "slots": dict(sorted(slots.items())),
        "same_club_goalkeepers": same_club_goalkeepers,
        "min_reliable_anchors": min_reliable_anchors,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def load_cached_optimum(
    cache_directory: Path,
    cache_key: str,
    players: Iterable[Player],
    scores: Mapping[str, float],
) -> Squad | None:
    """Load a validated cached optimum, treating corruption as a cache miss."""

    path = cache_directory / f"{cache_key}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        payload.get("schema_version") != OPTIMIZER_CACHE_SCHEMA_VERSION
        or payload.get("algorithm") != OPTIMIZER_ALGORITHM_VERSION
        or payload.get("cache_key") != cache_key
        or not isinstance(payload.get("player_ids"), list)
    ):
        return None
    player_by_id = {player.player_id: player for player in players}
    try:
        selected = [
            player_by_id[str(player_id)]
            for player_id in payload["player_ids"]
        ]
    except KeyError:
        return None
    if len(selected) != len(set(payload["player_ids"])):
        return None
    return Squad(
        selected,
        sum(scores[player.player_id] for player in selected),
    )


def save_cached_optimum(
    cache_directory: Path,
    cache_key: str,
    squad: Squad,
) -> None:
    """Atomically persist an optimum; cache write failures never stop a run."""

    path = cache_directory / f"{cache_key}.json"
    temporary_path = path.with_name(
        f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    )
    try:
        cache_directory.mkdir(parents=True, exist_ok=True)
        temporary_path.write_text(
            json.dumps(
                {
                    "schema_version": OPTIMIZER_CACHE_SCHEMA_VERSION,
                    "algorithm": OPTIMIZER_ALGORITHM_VERSION,
                    "cache_key": cache_key,
                    "player_ids": sorted(squad.ids),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_path, path)
    except OSError:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


def optimize(
    players: list[Player],
    budget: int,
    scores: dict[str, float],
    club_cap: int,
    minimum_spend: int,
    slots: dict[str, int],
    same_club_goalkeepers: bool = True,
    min_reliable_anchors: int = 0,
    cache_directory: Path | None = None,
) -> Squad:
    players = exact_distance_candidate_pool(
        players,
        scores,
        slots,
        club_cap,
        frozenset(),
        club_cap,
        allow_cheaper_dominance=minimum_spend == 0,
    )
    cache_key: str | None = None
    if cache_directory is not None:
        cache_key = optimizer_cache_key(
            players,
            scores,
            budget,
            club_cap,
            minimum_spend,
            slots,
            same_club_goalkeepers,
            min_reliable_anchors,
        )
        cached = load_cached_optimum(
            cache_directory,
            cache_key,
            players,
            scores,
        )
        cached_position_counts = (
            Counter(player.position for player in cached.players)
            if cached is not None
            else Counter()
        )
        cached_outfield_clubs = (
            Counter(
                player.club
                for player in cached.players
                if player.position != "GOALKEEPER"
            )
            if cached is not None
            else Counter()
        )
        cached_goalkeeper_clubs = (
            {
                player.club
                for player in cached.players
                if player.position == "GOALKEEPER"
            }
            if cached is not None
            else set()
        )
        if (
            cached is not None
            and cached_position_counts == Counter(slots)
            and minimum_spend <= cached.cost <= budget
            and all(
                count <= club_cap
                for count in cached_outfield_clubs.values()
            )
            and (
                not same_club_goalkeepers
                or len(cached_goalkeeper_clubs) == 1
            )
            and sum(
                player.reliable_anchor
                for player in cached.players
                if player.position != "GOALKEEPER"
            )
            >= min_reliable_anchors
        ):
            return cached
    gk_options = goalkeeper_options(
        players,
        slots["GOALKEEPER"],
        budget,
        scores,
        same_club_goalkeepers,
    )
    if not gk_options:
        requirement = (
            "one club"
            if same_club_goalkeepers
            else "the complete goalkeeper pool"
        )
        raise ValueError(
            "the required number of eligible goalkeepers cannot be selected from "
            f"{requirement} within budget"
        )
    field_options = outfield_options(
        players,
        slots,
        club_cap,
        budget,
        scores,
        min_reliable_anchors,
    )
    if not field_options:
        raise ValueError(
            "no outfield selection satisfies the positional and club-cap constraints"
        )
    squad, max_reachable_anchors = combine_options(
        gk_options,
        field_options,
        budget,
        minimum_spend,
        min_reliable_anchors,
    )
    if squad is None:
        if min_reliable_anchors > 0:
            eligible_anchors = sum(
                player.reliable_anchor
                for player in players
                if player.position != "GOALKEEPER"
            )
            raise ValueError(
                "reliable-anchor policy is infeasible: "
                f"required={min_reliable_anchors}, "
                f"eligible={eligible_anchors}, "
                "max reachable under roster, budget and club constraints="
                f"{max_reachable_anchors}"
            )
        raise ValueError("no complete squad fits the supplied budget and minimum spend")
    if cache_directory is not None and cache_key is not None:
        save_cached_optimum(cache_directory, cache_key, squad)
    return squad


def distance_goalkeeper_options(
    players: list[Player],
    count: int,
    budget: int,
    scores: dict[str, float],
    same_club: bool,
    reference_ids: frozenset[str],
    distance_cap: int,
) -> dict[tuple[int, int], tuple[float, tuple[Player, ...]]]:
    """Return exact goalkeeper options keyed by cost and distance bucket."""

    by_club: dict[str, list[Player]] = {}
    for player in players:
        if player.position == "GOALKEEPER":
            by_club.setdefault(player.club, []).append(player)
    options: dict[
        tuple[int, int],
        tuple[float, tuple[Player, ...]],
    ] = {}
    candidate_groups = (
        list(by_club.values())
        if same_club
        else [[player for club_players in by_club.values() for player in club_players]]
    )
    for club_players in candidate_groups:
        expected_primary = (
            expected_primary_goalkeeper(club_players, scores)
            if same_club
            else None
        )
        for combination in itertools.combinations(club_players, count):
            if expected_primary is not None and expected_primary not in combination:
                continue
            cost = sum(player.cost for player in combination)
            if cost > budget:
                continue
            distance = sum(
                player.player_id not in reference_ids for player in combination
            )
            if distance > distance_cap:
                continue
            score = sum(scores[player.player_id] for player in combination)
            key = (cost, distance)
            current = options.get(key)
            if current is None or score > current[0]:
                options[key] = (score, combination)
    return options


def distance_club_outfield_options(
    players: list[Player],
    slots: dict[str, int],
    club_cap: int,
    budget: int,
    scores: dict[str, float],
    reference_ids: frozenset[str],
    distance_cap: int,
    min_reliable_anchors: int = 0,
) -> dict[
    tuple[int, int, int, int, int, int],
    tuple[float, tuple[Player, ...]],
]:
    """Enumerate exact selections for one club with a distance bucket."""

    positions = ("DEFENDER", "MIDFIELDER", "FORWARD")
    position_index = {position: index for index, position in enumerate(positions)}
    states: dict[
        tuple[int, int, int, int, int, int],
        tuple[float, tuple[Player, ...]],
    ] = {(0, 0, 0, 0, 0, 0): (0.0, ())}
    for player in players:
        index = position_index[player.position]
        next_states = dict(states)
        for key, (score, selected) in states.items():
            counts = list(key[:3])
            if sum(counts) >= club_cap or counts[index] >= slots[player.position]:
                continue
            new_cost = key[3] + player.cost
            if new_cost > budget:
                continue
            counts[index] += 1
            distance = key[4] + (player.player_id not in reference_ids)
            if distance > distance_cap:
                continue
            anchors = min(
                min_reliable_anchors,
                key[5] + int(player.reliable_anchor),
            )
            new_key = (
                counts[0],
                counts[1],
                counts[2],
                new_cost,
                distance,
                anchors,
            )
            new_score = score + scores[player.player_id]
            current = next_states.get(new_key)
            if current is None or new_score > current[0]:
                next_states[new_key] = (new_score, selected + (player,))
        states = next_states
    return states


def exact_distance_candidate_pool(
    players: list[Player],
    scores: Mapping[str, float],
    slots: Mapping[str, int],
    club_cap: int,
    reference_ids: frozenset[str],
    distance_cap: int,
    allow_cheaper_dominance: bool = False,
) -> list[Player]:
    """Remove only candidates that cannot improve a capped-distance solution.

    Every selected non-reference player consumes one distance slot. Within an
    identical club, position and anchor class, a player with at least the same
    score dominates another at the same price. A cheaper player may dominate
    only when no minimum-spend constraint applies. We retain as many Pareto
    layers as the roster can possibly select from that class, so the reduction
    remains exact even when several mutually dominating players are selected.
    Reference players and goalkeepers are always retained.
    """

    if distance_cap <= 0:
        return [
            player
            for player in players
            if (
                player.position == "GOALKEEPER"
                or player.player_id in reference_ids
            )
        ]

    retained_ids = {
        player.player_id
        for player in players
        if (
            player.position == "GOALKEEPER"
            or player.player_id in reference_ids
        )
    }
    groups: dict[tuple[str, str, bool], list[Player]] = {}
    for player in players:
        if (
            player.position == "GOALKEEPER"
            or player.player_id in reference_ids
        ):
            continue
        groups.setdefault(
            (player.club, player.position, player.reliable_anchor),
            [],
        ).append(player)

    for (_, position, _), group in groups.items():
        remaining = sorted(
            group,
            key=lambda player: (
                player.cost,
                -scores[player.player_id],
                player.player_id,
            ),
        )
        selection_limit = min(
            distance_cap,
            club_cap,
            slots[position],
        )
        for _ in range(selection_limit):
            if not remaining:
                break
            frontier: list[Player] = []
            for player in remaining:
                dominated = any(
                    other.player_id != player.player_id
                    and (
                        other.cost == player.cost
                        or (
                            allow_cheaper_dominance
                            and other.cost < player.cost
                        )
                    )
                    and scores[other.player_id] >= scores[player.player_id]
                    and (
                        other.cost < player.cost
                        or scores[other.player_id] > scores[player.player_id]
                    )
                    for other in remaining
                )
                if not dominated:
                    frontier.append(player)
            retained_ids.update(player.player_id for player in frontier)
            frontier_ids = {player.player_id for player in frontier}
            remaining = [
                player
                for player in remaining
                if player.player_id not in frontier_ids
            ]

    return [
        player for player in players if player.player_id in retained_ids
    ]


def distance_outfield_options(
    players: list[Player],
    slots: dict[str, int],
    club_cap: int,
    budget: int,
    scores: dict[str, float],
    reference_ids: frozenset[str],
    distance_cap: int,
    min_reliable_anchors: int = 0,
) -> dict[tuple[int, int, int], tuple[float, tuple[Player, ...]]]:
    """Return exact outfield options up to the requested distance."""

    by_club: dict[str, list[Player]] = {}
    for player in players:
        if player.position != "GOALKEEPER":
            by_club.setdefault(player.club, []).append(player)

    states: dict[
        tuple[int, int, int, int, int, int],
        tuple[float, tuple[Player, ...]],
    ] = {(0, 0, 0, 0, 0, 0): (0.0, ())}
    target_counts = (
        slots["DEFENDER"],
        slots["MIDFIELDER"],
        slots["FORWARD"],
    )
    ordered_clubs = sorted(by_club)
    remaining_counts: list[Counter[str]] = [
        Counter() for _ in range(len(ordered_clubs) + 1)
    ]
    remaining_reference_counts: list[Counter[str]] = [
        Counter() for _ in range(len(ordered_clubs) + 1)
    ]
    remaining_anchor_counts = [0] * (len(ordered_clubs) + 1)
    for index in range(len(ordered_clubs) - 1, -1, -1):
        club_players = by_club[ordered_clubs[index]]
        remaining_counts[index] = remaining_counts[index + 1].copy()
        remaining_reference_counts[index] = (
            remaining_reference_counts[index + 1].copy()
        )
        remaining_anchor_counts[index] = remaining_anchor_counts[index + 1]
        for player in club_players:
            remaining_counts[index][player.position] += 1
            if player.player_id in reference_ids:
                remaining_reference_counts[index][player.position] += 1
            if player.reliable_anchor:
                remaining_anchor_counts[index] += 1

    for club_index, club in enumerate(ordered_clubs):
        local_options = distance_club_outfield_options(
            by_club[club],
            slots,
            club_cap,
            budget,
            scores,
            reference_ids,
            distance_cap,
            min_reliable_anchors,
        )
        next_states: dict[
            tuple[int, int, int, int, int, int],
            tuple[float, tuple[Player, ...]],
        ] = {}
        for base_key, (base_score, base_players) in states.items():
            for local_key, (local_score, local_players) in local_options.items():
                defender_count = base_key[0] + local_key[0]
                midfielder_count = base_key[1] + local_key[1]
                forward_count = base_key[2] + local_key[2]
                if (
                    defender_count > target_counts[0]
                    or midfielder_count > target_counts[1]
                    or forward_count > target_counts[2]
                ):
                    continue
                total_cost = base_key[3] + local_key[3]
                if total_cost > budget:
                    continue
                distance = base_key[4] + local_key[4]
                if distance > distance_cap:
                    continue
                anchors = base_key[5] + local_key[5]
                if anchors > min_reliable_anchors:
                    anchors = min_reliable_anchors
                new_key = (
                    defender_count,
                    midfielder_count,
                    forward_count,
                    total_cost,
                    distance,
                    anchors,
                )
                total_score = base_score + local_score
                current = next_states.get(new_key)
                if current is None or total_score > current[0]:
                    next_states[new_key] = (
                        total_score,
                        base_players + local_players,
                    )
        future_counts = remaining_counts[club_index + 1]
        future_reference_counts = remaining_reference_counts[club_index + 1]
        future_anchor_count = remaining_anchor_counts[club_index + 1]
        states = {}
        for key, value in next_states.items():
            needed_counts = {
                position: target_counts[position_index]
                - key[position_index]
                for position_index, position in enumerate(
                    ("DEFENDER", "MIDFIELDER", "FORWARD")
                )
            }
            if any(
                future_counts[position] < needed
                for position, needed in needed_counts.items()
            ):
                continue
            minimum_future_distance = sum(
                max(
                    0,
                    needed - future_reference_counts[position],
                )
                for position, needed in needed_counts.items()
            )
            if key[4] + minimum_future_distance > distance_cap:
                continue
            if (
                key[5] < min_reliable_anchors
                and key[5] + future_anchor_count < min_reliable_anchors
            ):
                continue
            states[key] = value
        if not states:
            return {}

    return {
        (key[3], key[4], key[5]): value
        for key, value in states.items()
        if key[:3] == target_counts
    }


def combine_distance_options(
    goalkeeper_group: dict[
        tuple[int, int], tuple[float, tuple[Player, ...]]
    ],
    field_group: dict[
        tuple[int, int, int], tuple[float, tuple[Player, ...]]
    ],
    budget: int,
    minimum_spend: int,
    distance_cap: int,
    min_reliable_anchors: int = 0,
) -> dict[int, Squad]:
    """Combine option groups and retain the exact best squad per bucket."""

    states: dict[
        tuple[int, int, int],
        tuple[float, tuple[Player, ...]],
    ] = {}
    for goalkeeper_key, (goalkeeper_score, goalkeepers) in goalkeeper_group.items():
        for field_key, (field_score, fielders) in field_group.items():
            total_cost = goalkeeper_key[0] + field_key[0]
            if total_cost > budget:
                continue
            distance = goalkeeper_key[1] + field_key[1]
            if distance > distance_cap:
                continue
            anchors = field_key[2]
            new_key = (total_cost, distance, anchors)
            total_score = goalkeeper_score + field_score
            current = states.get(new_key)
            if current is None or total_score > current[0]:
                states[new_key] = (
                    total_score,
                    goalkeepers + fielders,
                )

    best_by_distance: dict[int, Squad] = {}
    for (cost, distance, anchors), (score, selected) in states.items():
        if cost < minimum_spend or anchors < min_reliable_anchors:
            continue
        current = best_by_distance.get(distance)
        if current is None or score > current.objective_score:
            best_by_distance[distance] = Squad(list(selected), score)
    return best_by_distance


def optimize_distance_buckets(
    players: list[Player],
    budget: int,
    scores: dict[str, float],
    club_cap: int,
    minimum_spend: int,
    slots: dict[str, int],
    reference_ids: frozenset[str],
    distance_cap: int,
    same_club_goalkeepers: bool = True,
    min_reliable_anchors: int = 0,
) -> dict[int, Squad]:
    """Return the exact best squad for every capped distance bucket."""

    if distance_cap < 0:
        raise ValueError("distance cap cannot be negative")
    players = exact_distance_candidate_pool(
        players,
        scores,
        slots,
        club_cap,
        reference_ids,
        distance_cap,
        allow_cheaper_dominance=minimum_spend == 0,
    )
    gk_options = distance_goalkeeper_options(
        players,
        slots["GOALKEEPER"],
        budget,
        scores,
        same_club_goalkeepers,
        reference_ids,
        distance_cap,
    )
    if not gk_options:
        requirement = (
            "one club"
            if same_club_goalkeepers
            else "the complete goalkeeper pool"
        )
        raise ValueError(
            "the required number of eligible goalkeepers cannot be selected from "
            f"{requirement} within budget"
        )
    field_options = distance_outfield_options(
        players,
        slots,
        club_cap,
        budget,
        scores,
        reference_ids,
        distance_cap,
        min_reliable_anchors,
    )
    if not field_options:
        raise ValueError(
            "no outfield selection satisfies the positional and club-cap constraints"
        )
    squads = combine_distance_options(
        gk_options,
        field_options,
        budget,
        minimum_spend,
        distance_cap,
        min_reliable_anchors,
    )
    if not squads:
        raise ValueError("no complete squad fits the supplied budget and minimum spend")
    return squads


def load_avoid_exposure(paths: list[Path]) -> Counter[str]:
    exposure: Counter[str] = Counter()
    for path in paths:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        entries = payload.get("squad", payload.get("players", []))
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, str):
                exposure[entry] += 1
            elif isinstance(entry, dict):
                value = entry.get("id") or entry.get("player_id") or entry.get("name")
                if value:
                    exposure[str(value)] += 1
    return exposure


def technical_variation_pool(
    players: list[Player],
    scores: dict[str, float],
    optimum: Squad,
    slots: dict[str, int],
) -> list[Player]:
    """Bound unannotated smoke tests while preserving strong and cheap options."""

    if len(players) <= 160:
        return players
    retained_ids = set(optimum.ids)
    retained_ids.update(
        player.player_id
        for player in players
        if player.reliable_anchor or player.benchmark
    )
    for position, slot_count in slots.items():
        position_players = [
            player for player in players if player.position == position
        ]
        strongest_count = max(slot_count * 4, 16)
        cheapest_count = max(slot_count * 3, 12)
        strongest = sorted(
            position_players,
            key=lambda player: (
                -scores[player.player_id],
                player.cost,
                player.player_id,
            ),
        )[:strongest_count]
        cheapest = sorted(
            position_players,
            key=lambda player: (
                player.cost,
                -scores[player.player_id],
                player.player_id,
            ),
        )[:cheapest_count]
        retained_ids.update(player.player_id for player in (*strongest, *cheapest))

    goalkeeper_clubs = {
        player.club
        for player in players
        if (
            player.position == "GOALKEEPER"
            and player.player_id in retained_ids
        )
    }
    retained_ids.update(
        player.player_id
        for player in players
        if (
            player.position == "GOALKEEPER"
            and player.club in goalkeeper_clubs
        )
    )
    return [
        player for player in players if player.player_id in retained_ids
    ]


def strategic_optimization_pool(
    players: list[Player],
    scores: Mapping[str, float],
    slots: Mapping[str, int],
) -> list[Player]:
    """Bound the exact base search without dropping meaningful archetypes.

    The central quality feed deliberately covers far more players than an
    exact 22-player dynamic program needs. Preserve every goalkeeper block,
    anchor, benchmark and qualified prospect, then retain the strongest,
    cheapest and best candidates in every price tier. The later joint
    architecture search still receives the complete researched pool.
    """

    if len(players) <= 160:
        return players
    retained_ids = {
        player.player_id
        for player in players
        if (
            player.position == "GOALKEEPER"
            or player.benchmark
        )
    }
    retained_ids.update(qualified_potential_player_ids(players))
    retained_ids.update(scorer_leverage_candidate_ids(players))
    for position, slot_count in slots.items():
        if position == "GOALKEEPER":
            continue
        position_players = [
            player for player in players if player.position == position
        ]
        retained_ids.update(
            player.player_id
            for player in sorted(
                (
                    candidate
                    for candidate in position_players
                    if candidate.reliable_anchor
                ),
                key=lambda player: (
                    -scores[player.player_id],
                    player.cost,
                    player.player_id,
                ),
            )[: max(slot_count + 3, 8)]
        )
        retained_ids.update(
            player.player_id
            for player in sorted(
                position_players,
                key=lambda player: (
                    -scores[player.player_id],
                    player.cost,
                    player.player_id,
                ),
            )[: max(slot_count * 2, 12)]
        )
        retained_ids.update(
            player.player_id
            for player in sorted(
                position_players,
                key=lambda player: (
                    player.cost,
                    -scores[player.player_id],
                    player.player_id,
                ),
            )[: max(slot_count + 3, 10)]
        )
        by_cost: dict[int, list[Player]] = {}
        for player in position_players:
            by_cost.setdefault(player.cost, []).append(player)
        for tier in by_cost.values():
            retained_ids.update(
                player.player_id
                for player in sorted(
                    tier,
                    key=lambda player: (
                        -scores[player.player_id],
                        -player.components["minutes"],
                        -player.components["role"],
                        player.player_id,
                    ),
                )[:1]
            )
    return [
        player for player in players if player.player_id in retained_ids
    ]


def prepare_variation_context(
    players: list[Player],
    budget: int,
    base_scores: dict[str, float],
    profile: str,
    variation: str,
    club_cap: int,
    minimum_spend: int,
    slots: dict[str, int],
    same_club_goalkeepers: bool,
    min_reliable_anchors: int,
    technical_smoke: bool,
    optimizer_cache: Path | None = None,
) -> dict[str, Any]:
    """Calculate the seed-independent portfolio search state once."""

    optimization_players = strategic_optimization_pool(
        players,
        base_scores,
        slots,
    )
    optimum = optimize(
        optimization_players,
        budget,
        base_scores,
        club_cap,
        minimum_spend,
        slots,
        same_club_goalkeepers,
        min_reliable_anchors,
        optimizer_cache,
    )
    config = VARIATION_CONFIG[variation]
    if variation == "none":
        return {"optimum": optimum}

    profile_factor = 1.20 if profile == "breakout" else 1.0
    allowed_gap = config["gap"] * profile_factor
    target_distance = int(config["distance"])
    variation_players = (
        technical_variation_pool(
            optimization_players,
            base_scores,
            optimum,
            slots,
        )
        if technical_smoke
        else optimization_players
    )
    optimum_score = sum(base_scores[player.player_id] for player in optimum.players)
    score_denominator = max(abs(optimum_score), 1e-9)
    quality_floor = optimum_score - allowed_gap * score_denominator
    base_buckets = optimize_distance_buckets(
        variation_players,
        budget,
        base_scores,
        club_cap,
        minimum_spend,
        slots,
        optimum.ids,
        target_distance,
        same_club_goalkeepers,
        min_reliable_anchors,
    )
    base_bucket_scores = {
        distance: sum(
            base_scores[player.player_id] for player in candidate.players
        )
        for distance, candidate in base_buckets.items()
    }
    if (
        target_distance in base_buckets
        and base_bucket_scores[target_distance] >= quality_floor
    ):
        chosen_bucket = target_distance
        variation_target_met = True
    else:
        feasible_buckets = [
            distance
            for distance, score in base_bucket_scores.items()
            if distance < target_distance and score >= quality_floor
        ]
        chosen_bucket = max(feasible_buckets, default=0)
        variation_target_met = False

    base_candidate = base_buckets[chosen_bucket]
    base_candidate_score = base_bucket_scores[chosen_bucket]
    slack = max(0.0, base_candidate_score - quality_floor)
    max_player_perturbation = (
        slack / max(2.0 * target_distance, 1.0)
        if target_distance > 0
        else 0.0
    )
    return {
        "optimum": optimum,
        "config": config,
        "target_distance": target_distance,
        "variation_players": variation_players,
        "optimization_pool_size": len(optimization_players),
        "researched_pool_size": len(players),
        "quality_floor": quality_floor,
        "chosen_bucket": chosen_bucket,
        "variation_target_met": variation_target_met,
        "base_candidate": base_candidate,
        "base_candidate_score": base_candidate_score,
        "max_player_perturbation": max_player_perturbation,
    }


def varied_squad(
    players: list[Player],
    budget: int,
    base_scores: dict[str, float],
    profile: str,
    variation: str,
    seed: int,
    club_cap: int,
    minimum_spend: int,
    slots: dict[str, int],
    avoid_ids: set[str] | Mapping[str, int],
    same_club_goalkeepers: bool = True,
    min_reliable_anchors: int = 0,
    technical_smoke: bool = False,
    exposure_strength: float = 1.0,
    prepared_context: dict[str, Any] | None = None,
    forbidden_ids: set[str] | None = None,
    protected_ids: AbstractSet[str] = frozenset(),
    optimizer_cache: Path | None = None,
) -> tuple[Squad, Squad, int, bool]:
    context = prepared_context or prepare_variation_context(
        players=players,
        budget=budget,
        base_scores=base_scores,
        profile=profile,
        variation=variation,
        club_cap=club_cap,
        minimum_spend=minimum_spend,
        slots=slots,
        same_club_goalkeepers=same_club_goalkeepers,
        min_reliable_anchors=min_reliable_anchors,
        technical_smoke=technical_smoke,
        optimizer_cache=optimizer_cache,
    )
    optimum = context["optimum"]
    protected_ids = frozenset(protected_ids).intersection(optimum.ids)
    if variation == "none":
        return optimum, optimum, 0, True

    config = context["config"]
    target_distance = context["target_distance"]
    variation_players = context["variation_players"]
    quality_floor = context["quality_floor"]
    chosen_bucket = context["chosen_bucket"]
    variation_target_met = context["variation_target_met"]
    base_candidate = context["base_candidate"]
    base_candidate_score = context["base_candidate_score"]
    max_player_perturbation = context["max_player_perturbation"]
    distance_cap = target_distance
    forbidden_ids = forbidden_ids or set()
    if forbidden_ids:
        variation_players = [
            player
            for player in variation_players
            if player.player_id not in forbidden_ids
        ]
        distance_cap = sum(slots.values())
        base_buckets = optimize_distance_buckets(
            variation_players,
            budget,
            base_scores,
            club_cap,
            minimum_spend,
            slots,
            optimum.ids,
            distance_cap,
            same_club_goalkeepers,
            min_reliable_anchors,
        )
        feasible_buckets = {
            distance: candidate
            for distance, candidate in base_buckets.items()
            if sum(
                base_scores[player.player_id]
                for player in candidate.players
            )
            >= quality_floor
        }
        if not feasible_buckets:
            raise ValueError(
                "anchor-diverse portfolio is infeasible inside the quality "
                "corridor; broaden the league-wide reliable-anchor pool"
            )
        chosen_bucket = min(
            feasible_buckets,
            key=lambda distance: (
                abs(distance - target_distance),
                distance,
            ),
        )
        variation_target_met = chosen_bucket == target_distance
        base_candidate = feasible_buckets[chosen_bucket]
        base_candidate_score = sum(
            base_scores[player.player_id]
            for player in base_candidate.players
        )
        slack = max(0.0, base_candidate_score - quality_floor)
        max_player_perturbation = (
            slack / max(2.0 * target_distance, 1.0)
            if target_distance > 0
            else 0.0
        )

    rng = random.Random(seed)
    raw_preferences: dict[str, float] = {}
    for player in sorted(
        variation_players,
        key=lambda item: (item.player_id, item.name),
    ):
        if isinstance(avoid_ids, Mapping):
            exposure = max(
                int(avoid_ids.get(player.player_id, 0)),
                int(avoid_ids.get(player.name, 0)),
            )
        else:
            exposure = int(
                player.player_id in avoid_ids or player.name in avoid_ids
            )
        avoid_penalty = (
            config["avoid"] * exposure * max(exposure_strength, 0.0)
        )
        noise_strength = min(1.0, 1.0 / max(exposure_strength, 1.0))
        raw_preferences[player.player_id] = (
            rng.uniform(-config["noise"], config["noise"]) * noise_strength
            - avoid_penalty
        )
    largest_preference = max(
        (abs(value) for value in raw_preferences.values()),
        default=0.0,
    )
    preference_scale = (
        min(1.0, max_player_perturbation / largest_preference)
        if largest_preference > 0.0
        else 0.0
    )
    seeded_scores = {
        player.player_id: (
            base_scores[player.player_id]
            + raw_preferences[player.player_id] * preference_scale
        )
        for player in variation_players
    }
    selection_scores = dict(seeded_scores)
    if protected_ids:
        retention_bonus = (
            2.0 * sum(abs(score) for score in base_scores.values()) + 1.0
        )
        for player_id in protected_ids:
            selection_scores[player_id] += retention_bonus
    seeded_buckets = optimize_distance_buckets(
        variation_players,
        budget,
        selection_scores,
        club_cap,
        minimum_spend,
        slots,
        optimum.ids,
        distance_cap,
        same_club_goalkeepers,
        min_reliable_anchors,
    )
    preferred_distances = [
        chosen_bucket,
        *range(chosen_bucket - 1, -1, -1),
    ]
    chosen: Squad | None = None
    selected_distance = chosen_bucket
    for candidate_distance in preferred_distances:
        seeded_candidate = seeded_buckets.get(candidate_distance)
        if seeded_candidate is None:
            continue
        if not protected_ids.issubset(seeded_candidate.ids):
            continue
        seeded_baseline_score = sum(
            base_scores[player.player_id]
            for player in seeded_candidate.players
        )
        if seeded_baseline_score < quality_floor:
            continue
        chosen = Squad(
            seeded_candidate.players,
            seeded_baseline_score,
        )
        selected_distance = candidate_distance
        break
    if chosen is None:
        chosen = optimum
        selected_distance = 0
    variation_target_met = (
        variation_target_met
        and selected_distance == target_distance
    )

    distance = len(optimum.ids.symmetric_difference(chosen.ids)) // 2
    if distance != selected_distance:
        raise RuntimeError(
            "distance-aware optimizer returned the wrong protected distance"
        )
    if variation_target_met and distance != target_distance:
        raise RuntimeError("distance-aware optimizer violated the exact target distance")
    return chosen, optimum, distance, variation_target_met


def varied_portfolio(
    players: list[Player],
    budget: int,
    base_scores: dict[str, float],
    profile: str,
    variation: str,
    seed: int,
    club_cap: int,
    minimum_spend: int,
    slots: dict[str, int],
    avoid_exposure: Mapping[str, int],
    portfolio_size: int,
    portfolio_index: int,
    maintenance: str = "low",
    same_club_goalkeepers: bool = True,
    min_reliable_anchors: int = 0,
    min_attacking_anchors: int = 0,
    min_core_budget_share: float = 0.0,
    target_core_budget_share: float = 0.0,
    min_offensive_premium_anchors: int = 0,
    min_qualified_potential_core: int = 0,
    target_qualified_potential_core: int = 0,
    core_scores: Mapping[str, float] | None = None,
    technical_smoke: bool = False,
    max_reliable_anchor_exposure: int = 1,
    optimizer_cache: Path | None = None,
) -> tuple[Squad, Squad, int, bool, dict[str, Any]]:
    """Build a reproducible set of near-optimal squads with balanced exposure."""

    if portfolio_size < 1:
        raise ValueError("portfolio size must be positive")
    if not 1 <= portfolio_index <= portfolio_size:
        raise ValueError("portfolio index must be inside the portfolio size")
    if max_reliable_anchor_exposure < 1:
        raise ValueError("maximum reliable-anchor exposure must be positive")
    effective_core_scores = core_scores or base_scores

    reliable_anchor_ids = {
        player.player_id
        for player in players
        if player.reliable_anchor and player.position != "GOALKEEPER"
    }
    required_anchor_slots = portfolio_size * min_reliable_anchors
    available_anchor_slots = (
        len(reliable_anchor_ids) * max_reliable_anchor_exposure
    )
    if available_anchor_slots < required_anchor_slots:
        raise ValueError(
            "anchor-diverse portfolio is infeasible: "
            f"required_anchor_slots={required_anchor_slots}, "
            f"eligible_reliable_anchors={len(reliable_anchor_ids)}, "
            f"max_anchor_exposure={max_reliable_anchor_exposure}. "
            "Broaden the league-wide anchor research instead of repeating "
            "named examples."
        )
    attacking_anchor_ids = {
        player.player_id
        for player in players
        if player.reliable_anchor
        and player.position in {"MIDFIELDER", "FORWARD"}
    }
    offensive_premium_anchor_ids = {
        player.player_id
        for player in players
        if is_offensive_premium_anchor(player)
    }
    required_attacking_slots = portfolio_size * min_attacking_anchors
    if (
        max_reliable_anchor_exposure == 1
        and len(attacking_anchor_ids) < required_attacking_slots
    ):
        raise ValueError(
            "anchor-diverse portfolio is infeasible: "
            f"required_attacking_anchor_slots={required_attacking_slots}, "
            f"eligible_attacking_anchors={len(attacking_anchor_ids)}."
        )
    required_premium_slots = (
        portfolio_size * min_offensive_premium_anchors
    )
    if (
        max_reliable_anchor_exposure == 1
        and len(offensive_premium_anchor_ids) < required_premium_slots
    ):
        raise ValueError(
            "premium-anchor-diverse portfolio is infeasible: "
            f"required_offensive_premium_slots={required_premium_slots}, "
            "eligible_offensive_premium_anchors="
            f"{len(offensive_premium_anchor_ids)}."
        )

    exposure = Counter(
        {
            str(player_key): int(count)
            for player_key, count in avoid_exposure.items()
            if int(count) > 0
        }
    )
    assigned_anchor_groups: list[set[str]] | None = None
    if (
        max_reliable_anchor_exposure == 1
        and min_reliable_anchors > 0
    ):
        player_by_id = {player.player_id: player for player in players}
        assignment_rng = random.Random(seed ^ 0x5A17C0DE)
        anchor_tiebreak = {
            player_id: assignment_rng.uniform(-1.5, 1.5)
            for player_id in sorted(reliable_anchor_ids)
        }
        attacking_candidates = sorted(
            attacking_anchor_ids,
            key=lambda player_id: (
                -(
                    base_scores[player_id]
                    + anchor_tiebreak[player_id]
                ),
                player_id,
            ),
        )
        if min_offensive_premium_anchors > 0:
            premium_candidates = [
                player_id
                for player_id in attacking_candidates
                if player_id in offensive_premium_anchor_ids
            ]
            attacking_candidates = [
                player_id
                for player_id in attacking_candidates
                if player_id not in offensive_premium_anchor_ids
            ]
        else:
            premium_candidates = []
        other_candidates = sorted(
            reliable_anchor_ids - attacking_anchor_ids,
            key=lambda player_id: (
                -(
                    base_scores[player_id]
                    + anchor_tiebreak[player_id]
                ),
                player_id,
            ),
        )
        assigned_anchor_groups = [set() for _ in range(portfolio_size)]

        def take_candidate(
            candidates: list[str],
            group: set[str],
        ) -> str:
            club_counts = Counter(
                player_by_id[player_id].club for player_id in group
            )
            for index, player_id in enumerate(candidates):
                if club_counts[player_by_id[player_id].club] < club_cap:
                    return candidates.pop(index)
            raise ValueError(
                "anchor-diverse portfolio cannot satisfy the club cap"
            )

        if min_offensive_premium_anchors == 0:
            for _ in range(min_attacking_anchors):
                for group in assigned_anchor_groups:
                    group.add(take_candidate(attacking_candidates, group))
        else:
            for _ in range(min_offensive_premium_anchors):
                for group in assigned_anchor_groups:
                    group.add(take_candidate(premium_candidates, group))
            remaining_attacking_requirements = max(
                0,
                min_attacking_anchors - min_offensive_premium_anchors,
            )
            for _ in range(remaining_attacking_requirements):
                for group in assigned_anchor_groups:
                    available_attacking_candidates = [
                        *attacking_candidates,
                        *premium_candidates,
                    ]
                    chosen = take_candidate(
                        available_attacking_candidates,
                        group,
                    )
                    group.add(chosen)
                    if chosen in attacking_candidates:
                        attacking_candidates.remove(chosen)
                    else:
                        premium_candidates.remove(chosen)
        remaining_candidates = [
            *other_candidates,
            *attacking_candidates,
            *premium_candidates,
        ]
        remaining_candidates.sort(
            key=lambda player_id: (
                -(
                    base_scores[player_id]
                    + anchor_tiebreak[player_id]
                ),
                player_id,
            )
        )
        while any(
            len(group) < min_reliable_anchors
            for group in assigned_anchor_groups
        ):
            for group in assigned_anchor_groups:
                if len(group) >= min_reliable_anchors:
                    continue
                group.add(take_candidate(remaining_candidates, group))
    prepared_context = (
        None
        if assigned_anchor_groups is not None
        else prepare_variation_context(
            players=players,
            budget=budget,
            base_scores=base_scores,
            profile=profile,
            variation=variation,
            club_cap=club_cap,
            minimum_spend=minimum_spend,
            slots=slots,
            same_club_goalkeepers=same_club_goalkeepers,
            min_reliable_anchors=min_reliable_anchors,
            technical_smoke=technical_smoke,
            optimizer_cache=optimizer_cache,
        )
    )
    generated: list[tuple[Squad, Squad, int, bool, int]] = []
    used_rosters: set[frozenset[str]] = set()
    for slot in range(1, portfolio_size + 1):
        selected: tuple[Squad, Squad, int, bool, int] | None = None
        last_core_audit: dict[str, Any] | None = None
        forbidden_anchor_ids = {
            player_id
            for player_id in reliable_anchor_ids
            if exposure[player_id] >= max_reliable_anchor_exposure
        }
        if assigned_anchor_groups is not None:
            forbidden_anchor_ids = (
                reliable_anchor_ids - assigned_anchor_groups[slot - 1]
            )
            slot_players = [
                player
                for player in players
                if player.player_id not in forbidden_anchor_ids
            ]
            slot_scores = {
                player.player_id: base_scores[player.player_id]
                for player in slot_players
            }
            slot_context = prepare_variation_context(
                players=slot_players,
                budget=budget,
                base_scores=slot_scores,
                profile=profile,
                variation=variation,
                club_cap=club_cap,
                minimum_spend=minimum_spend,
                slots=slots,
                same_club_goalkeepers=same_club_goalkeepers,
                min_reliable_anchors=min_reliable_anchors,
                technical_smoke=technical_smoke,
                optimizer_cache=optimizer_cache,
            )
            slot_forbidden_ids: set[str] = set()
        else:
            slot_players = players
            slot_scores = base_scores
            slot_context = prepared_context
            slot_forbidden_ids = forbidden_anchor_ids
        for attempt in range(8):
            slot_seed = seed + slot * 104_729 + attempt * 7_919
            squad, optimum, distance, target_met = varied_squad(
                players=slot_players,
                budget=budget,
                base_scores=slot_scores,
                profile=profile,
                variation=variation,
                seed=slot_seed,
                club_cap=club_cap,
                minimum_spend=minimum_spend,
                slots=slots,
                avoid_ids=exposure,
                same_club_goalkeepers=same_club_goalkeepers,
                min_reliable_anchors=min_reliable_anchors,
                technical_smoke=technical_smoke,
                exposure_strength=10.0,
                prepared_context=slot_context,
                forbidden_ids=slot_forbidden_ids,
                optimizer_cache=optimizer_cache,
            )
            if min_core_budget_share > 0:
                optimum = finalize_reliable_core_architecture(
                    optimum,
                    slot_players,
                    slot_scores,
                    effective_core_scores,
                    budget=budget,
                    club_cap=club_cap,
                    min_reliable_anchors=min_reliable_anchors,
                    min_attacking_anchors=min_attacking_anchors,
                    min_core_budget_share=min_core_budget_share,
                    target_core_budget_share=target_core_budget_share,
                    minimum_spend=minimum_spend,
                    min_offensive_premium_anchors=(
                        min_offensive_premium_anchors
                    ),
                    min_qualified_potential_core=(
                        min_qualified_potential_core
                    ),
                    target_qualified_potential_core=(
                        target_qualified_potential_core
                    ),
                    maintenance=maintenance,
                    same_club_goalkeepers=same_club_goalkeepers,
                )
                squad = finalize_reliable_core_architecture(
                    squad,
                    slot_players,
                    slot_scores,
                    effective_core_scores,
                    budget=budget,
                    club_cap=club_cap,
                    min_reliable_anchors=min_reliable_anchors,
                    min_attacking_anchors=min_attacking_anchors,
                    min_core_budget_share=min_core_budget_share,
                    target_core_budget_share=target_core_budget_share,
                    minimum_spend=minimum_spend,
                    min_offensive_premium_anchors=(
                        min_offensive_premium_anchors
                    ),
                    min_qualified_potential_core=(
                        min_qualified_potential_core
                    ),
                    target_qualified_potential_core=(
                        target_qualified_potential_core
                    ),
                    maintenance=maintenance,
                    same_club_goalkeepers=same_club_goalkeepers,
                )
                distance = len(
                    optimum.ids.symmetric_difference(squad.ids)
                ) // 2
                target_met = variation_distance_met(variation, distance)
                core_audit = reliable_core_audit(
                    squad,
                    effective_core_scores,
                    min_reliable_anchors,
                    min_attacking_anchors,
                    min_core_budget_share,
                    min_offensive_premium_anchors,
                )
                last_core_audit = core_audit
            else:
                core_audit = reliable_core_audit(
                    squad,
                    effective_core_scores,
                    min_reliable_anchors,
                    min_attacking_anchors,
                    min_core_budget_share,
                    min_offensive_premium_anchors,
                )
                last_core_audit = core_audit
            if (
                (
                    min_core_budget_share > 0
                    and (
                        core_audit["reliable_anchors"]
                        < min_reliable_anchors
                        or core_audit["attacking_anchors"]
                        < min_attacking_anchors
                        or core_audit["offensive_premium_anchors"]
                        < min_offensive_premium_anchors
                        or core_audit["core_budget_share"]
                        < min_core_budget_share
                    )
                )
                or squad.ids in used_rosters
            ):
                continue
            selected = (squad, optimum, distance, target_met, slot_seed)
            break
        if selected is None:
            raise ValueError(
                "portfolio generation cannot satisfy the starting-core "
                f"anchor and budget-share policy for slot {slot}: "
                f"{last_core_audit}"
            )
        generated.append(selected)
        used_rosters.add(selected[0].ids)
        exposure.update(selected[0].ids)

    selected_squad, optimum, distance, target_met, selected_seed = generated[
        portfolio_index - 1
    ]
    squad_id_sets = [entry[0].ids for entry in generated]
    common_ids = (
        set.intersection(*(set(ids) for ids in squad_id_sets))
        if squad_id_sets
        else set()
    )
    player_by_id = {player.player_id: player for player in players}
    starting_id_sets = [
        set(
            best_starting_lineup(
                entry[0].players,
                base_scores,
                min_reliable_anchors,
                2 if min_core_budget_share > 0 else 1,
                4 if min_core_budget_share > 0 else 5,
                min_offensive_premium_anchors,
            )[1]
        )
        for entry in generated
    ]
    common_starting_ids = (
        set.intersection(*starting_id_sets)
        if starting_id_sets
        else set()
    )
    portfolio_exposure = Counter(
        player_id
        for squad_ids in squad_id_sets
        for player_id in squad_ids
    )
    reliable_anchor_exposure = {
        player_id: portfolio_exposure[player_id]
        for player_id in sorted(reliable_anchor_ids)
        if portfolio_exposure[player_id] > 0
    }
    max_anchor_exposure = max(
        reliable_anchor_exposure.values(),
        default=0,
    )
    if max_anchor_exposure > max_reliable_anchor_exposure:
        raise RuntimeError(
            "portfolio optimizer violated the reliable-anchor exposure limit"
        )
    audit = {
        "size": portfolio_size,
        "index": portfolio_index,
        "base_seed": seed,
        "selected_seed": selected_seed,
        "unique_rosters": len(used_rosters),
        "common_player_ids": sorted(common_ids),
        "common_player_count": len(common_ids),
        "common_starting_player_ids": sorted(common_starting_ids),
        "common_starting_player_count": len(common_starting_ids),
        "common_reliable_anchor_ids": sorted(
            player_id
            for player_id in common_ids
            if player_by_id[player_id].reliable_anchor
        ),
        "common_benchmark_ids": sorted(
            player_id
            for player_id in common_ids
            if player_by_id[player_id].benchmark
        ),
        "required_anchor_slots": required_anchor_slots,
        "eligible_reliable_anchor_count": len(reliable_anchor_ids),
        "max_reliable_anchor_exposure_allowed": (
            max_reliable_anchor_exposure
        ),
        "max_reliable_anchor_exposure": max_anchor_exposure,
        "reliable_anchor_exposure": reliable_anchor_exposure,
        "anchor_diversity_target_met": (
            max_anchor_exposure <= max_reliable_anchor_exposure
        ),
        "assigned_anchor_groups": (
            [sorted(group) for group in assigned_anchor_groups]
            if assigned_anchor_groups is not None
            else None
        ),
        "max_player_exposure": max(portfolio_exposure.values(), default=0),
        "player_exposure": dict(sorted(portfolio_exposure.items())),
        "slots": [
            {
                "index": slot,
                "seed": entry[4],
                "distance_from_optimum": entry[2],
                "variation_target_met": entry[3],
                "player_ids": sorted(entry[0].ids),
                "reliable_anchor_ids": sorted(
                    player.player_id
                    for player in entry[0].players
                    if player.reliable_anchor
                ),
                "core_audit": reliable_core_audit(
                    entry[0],
                    effective_core_scores,
                    min_reliable_anchors,
                    min_attacking_anchors,
                    min_core_budget_share,
                    min_offensive_premium_anchors,
                )
                | {
                    "player_ids": sorted(
                        reliable_core_audit(
                            entry[0],
                            effective_core_scores,
                            min_reliable_anchors,
                            min_attacking_anchors,
                            min_core_budget_share,
                            min_offensive_premium_anchors,
                        )["player_ids"]
                    )
                },
            }
            for slot, entry in enumerate(generated, start=1)
        ],
    }
    return selected_squad, optimum, distance, target_met, audit


def output_payload(
    squad: Squad,
    optimum: Squad,
    players: list[Player],
    raw_scores: dict[str, float],
    utility_scores: dict[str, float],
    core_multipliers: dict[str, float],
    args: argparse.Namespace,
    seed: int,
    distance: int,
    variation_target_met: bool,
    annotated_count: int,
    annotated_by_position: dict[str, int],
    annotation_requirements: dict[str, int],
    annotated_goalkeeper_blocks: int,
    hard_exclusions: list[dict[str, Any]],
    news_audit: dict[str, Any] | None = None,
    portfolio_audit: dict[str, Any] | None = None,
    market_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    news_audit = news_audit or {
        "status": "not_configured",
        "required": False,
    }
    squad_score, squad_objective_valid = finalized_squad_objective(
        squad,
        players,
        utility_scores,
        raw_scores,
        args,
    )
    optimum_score, optimum_objective_valid = finalized_squad_objective(
        optimum,
        players,
        utility_scores,
        raw_scores,
        args,
    )
    if not squad_objective_valid or not optimum_objective_valid:
        raise ValueError(
            "finalized squad objective cannot compare an invalid core architecture"
        )
    raw_squad_score = sum(
        round(raw_scores[player.player_id], 3) for player in squad.players
    )
    raw_optimum_score = sum(raw_scores[player.player_id] for player in optimum.players)
    visible_squad_utility = squad_score
    quality_gap = (
        100.0
        * (optimum_score - squad_score)
        / max(abs(optimum_score), 1e-9)
    )
    club_counts: dict[str, int] = {}
    for player in squad.players:
        if player.position != "GOALKEEPER":
            club_counts[player.club] = club_counts.get(player.club, 0) + 1
    warnings: list[str] = []
    missing_annotations = {
        position: {
            "actual": annotated_by_position[position],
            "required": minimum,
        }
        for position, minimum in annotation_requirements.items()
        if annotated_by_position[position] < minimum
    }
    if missing_annotations:
        warnings.append(
            "Current role, fitness and transfer annotations are below the recommended "
            f"coverage: {missing_annotations}"
        )
    if bool(getattr(args, "allow_unannotated", False)):
        warnings.append(
            "Technical smoke test only: unannotated output is not a recommendation "
            "and must not be used as a Chrome target squad."
        )
    overloaded = {
        club: count
        for club, count in club_counts.items()
        if count > args.max_outfield_per_club
    }
    if overloaded:
        warnings.append(f"Could not fully satisfy outfield club cap: {overloaded}")
    if not variation_target_met:
        warnings.append(
            "The requested minimum squad variation could not be reached inside "
            "the quality and roster constraints."
        )
    if portfolio_audit and (
        portfolio_audit["unique_rosters"] < portfolio_audit["size"]
    ):
        warnings.append(
            "The requested portfolio contains duplicate squads. Expand the "
            "annotated candidate pool or increase variation before assigning it "
            "to multiple people."
        )
    if args.budget - squad.cost > 0:
        warnings.append(
            "Budget remains unused. Final recommendations must spend the full "
            "available budget."
        )

    ordered = sorted(
        squad.players,
        key=lambda player: (
            POSITION_ORDER[player.position],
            -utility_scores[player.player_id],
            player.name,
        ),
    )
    selected_ids = squad.ids
    core_anchor_requirement = (
        args.min_reliable_anchors if args.profile == "reliable" else 0
    )
    architecture_core_ids = squad.architecture_diagnostics.get(
        "player_ids"
    )
    architecture_formation = squad.architecture_diagnostics.get(
        "formation"
    )
    if (
        isinstance(architecture_core_ids, list)
        and len(architecture_core_ids) == 11
        and isinstance(architecture_formation, str)
        and architecture_formation
    ):
        formation = architecture_formation
        core_ids = frozenset(
            str(player_id) for player_id in architecture_core_ids
        )
    else:
        formation, core_ids = best_starting_lineup(
            squad.players,
            raw_scores,
            core_anchor_requirement,
            2 if args.maintenance == "low" else 1,
            4 if args.maintenance == "low" else 5,
            int(getattr(args, "min_offensive_premium_anchors", 0)),
        )
    selected_anchors = [
        player for player in squad.players if player.reliable_anchor
    ]
    core_anchor_count = sum(
        player.reliable_anchor
        for player in squad.players
        if player.player_id in core_ids
    )
    if core_anchor_count < core_anchor_requirement:
        warnings.append(
            "The selected squad satisfies the roster anchor floor, but no legal "
            "starting formation can place all required anchors in the core."
        )

    def serialize_player(
        player: Player,
        *,
        selection_role: str | None = None,
        comparison_to: Player | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": player.player_id,
            "name": player.name,
            "short_name": player.short_name,
            "club": player.club,
            "position": player.position,
            "cost": player.cost,
            "score": round(raw_scores[player.player_id], 3),
            "utility_score": round(utility_scores[player.player_id], 3),
            "core_multiplier": round(core_multipliers[player.player_id], 3),
            "components": {
                key: round(player.components[key], 3) for key in COMPONENTS
            },
            "risks": {
                key: round(player.risks[key], 3) for key in RISKS
            },
            "note": player.note,
            "evidence": list(player.evidence),
            "benchmark": player.benchmark,
            "reliable_anchor": player.reliable_anchor,
            "offensive_premium_anchor": is_offensive_premium_anchor(player),
            "offensive_premium_strength": round(
                offensive_premium_anchor_strength(player),
                3,
            ),
            "offensive_premium_path": (
                offensive_premium_path_evidence(player)
            ),
            "starting_scorer_leverage": starting_scorer_leverage(
                player
            ),
            "elite_rebound_striker": is_elite_rebound_striker(player),
            "elite_rebound_evidence": (
                elite_rebound_striker_evidence(player)
            ),
            "elite_rebound_class_adjustment": (
                elite_rebound_class_adjustment(player)
            ),
            "anchor_basis": player.anchor_basis,
            "anchor_reason": player.anchor_reason,
            "proven_seasons": player.proven_seasons,
        }
        if player.position == "GOALKEEPER":
            payload["goalkeeper_outlook"] = dict(
                player.goalkeeper_outlook
            )
        if player.preseason_summary:
            payload["preseason_summary"] = dict(
                player.preseason_summary
            )
        if player.form_summary:
            payload["form_summary"] = dict(player.form_summary)
        if player.history_summary:
            payload["history_summary"] = dict(player.history_summary)
        if player.role_context:
            payload["role_context"] = dict(player.role_context)
        if player.scorer_profile:
            payload["scorer_profile"] = dict(player.scorer_profile)
        if player.role_research:
            payload["role_research"] = dict(player.role_research)
        if player.manual_news_clearance:
            payload["manual_news_clearance"] = dict(
                player.manual_news_clearance
            )
        if selection_role is not None:
            payload["selection_role"] = selection_role
        architecture_contributions = squad.architecture_diagnostics.get(
            "player_contributions",
            {},
        )
        if player.player_id in architecture_contributions:
            contribution = float(
                architecture_contributions[player.player_id]
            )
            raw_score = raw_scores[player.player_id]
            payload["expected_role_contribution"] = round(
                contribution,
                3,
            )
            payload["expected_usage_weight"] = round(
                contribution / raw_score
                if abs(raw_score) > 1e-9
                else 0.0,
                3,
            )
            payload["contribution_per_100k"] = round(
                contribution / max(player.cost / 100_000, 1e-9),
                3,
            )
        if comparison_to is not None:
            payload["position_cutoff_player"] = {
                "id": comparison_to.player_id,
                "name": comparison_to.name,
                "cost": comparison_to.cost,
                "utility_score": round(
                    utility_scores[comparison_to.player_id],
                    3,
                ),
            }
            payload["cost_delta_vs_cutoff"] = player.cost - comparison_to.cost
            payload["utility_delta_vs_cutoff"] = round(
                utility_scores[player.player_id]
                - utility_scores[comparison_to.player_id],
                3,
            )
        return payload

    roster_slots = getattr(
        args,
        "slots",
        {
            position: sum(
                player.position == position for player in squad.players
            )
            for position in DEFAULT_SLOTS
        },
    )
    minimum_spend = math.ceil(
        args.budget * float(getattr(args, "min_spend_ratio", 0.0))
    )
    force_bonus = 2.0 * sum(abs(score) for score in utility_scores.values()) + 1.0

    def counterfactual_for(player: Player) -> dict[str, Any]:
        if bool(getattr(args, "allow_unannotated", False)):
            return {
                "feasible": None,
                "reason": (
                    "counterfactual omitted for an unannotated technical smoke "
                    "test; final researched squads compute a direct replacement"
                ),
            }
        exact_counterfactuals = bool(
            getattr(args, "exact_counterfactuals", True)
        )
        if exact_counterfactuals:
            forced_scores = dict(utility_scores)
            forced_scores[player.player_id] += force_bonus
            try:
                forced = optimize(
                    players,
                    args.budget,
                    forced_scores,
                    args.max_outfield_per_club,
                    minimum_spend,
                    roster_slots,
                    not args.mixed_goalkeepers,
                    args.min_reliable_anchors,
                )
            except ValueError as error:
                return {
                    "feasible": False,
                    "reason": str(error),
                }
            if player.player_id not in forced.ids:
                return {
                    "feasible": False,
                    "reason": (
                        "candidate cannot be forced inside the roster constraints"
                    ),
                }
            if float(
                getattr(args, "min_core_budget_share", 0.0)
            ) > 0:
                forced = finalize_reliable_core_architecture(
                    forced,
                    players,
                    utility_scores,
                    raw_scores,
                    budget=args.budget,
                    club_cap=args.max_outfield_per_club,
                    min_reliable_anchors=args.min_reliable_anchors,
                    min_attacking_anchors=getattr(
                        args,
                        "min_attacking_anchors",
                        0,
                    ),
                    min_core_budget_share=getattr(
                        args,
                        "min_core_budget_share",
                        0.0,
                    ),
                    target_core_budget_share=(
                        getattr(
                            args,
                            "effective_core_budget_share_target",
                            0.0,
                        )
                    ),
                    minimum_spend=minimum_spend,
                    min_offensive_premium_anchors=(
                        getattr(
                            args,
                            "min_offensive_premium_anchors",
                            0,
                        )
                    ),
                    min_qualified_potential_core=int(
                        getattr(
                            args,
                            "min_qualified_potential_core",
                            0,
                        )
                    ),
                    target_qualified_potential_core=int(
                        getattr(
                            args,
                            "target_qualified_potential_core",
                            0,
                        )
                    ),
                    maintenance=getattr(args, "maintenance", "normal"),
                    same_club_goalkeepers=not args.mixed_goalkeepers,
                    protected_player_ids=frozenset(
                        {player.player_id}
                    ),
                )
            counterfactual_scope = (
                "best_finalized_pool_squad_with_candidate"
            )
        else:
            direct_replacements: list[Squad] = []
            for displaced in squad.players:
                if displaced.position != player.position:
                    continue
                replacement_players = [
                    candidate
                    for candidate in squad.players
                    if candidate.player_id != displaced.player_id
                ] + [player]
                replacement_cost = sum(
                    candidate.cost for candidate in replacement_players
                )
                if not minimum_spend <= replacement_cost <= args.budget:
                    continue
                replacement_clubs = Counter(
                    candidate.club
                    for candidate in replacement_players
                    if candidate.position != "GOALKEEPER"
                )
                if any(
                    count > args.max_outfield_per_club
                    for count in replacement_clubs.values()
                ):
                    continue
                if (
                    sum(
                        candidate.reliable_anchor
                        for candidate in replacement_players
                        if candidate.position != "GOALKEEPER"
                    )
                    < args.min_reliable_anchors
                ):
                    continue
                replacement_score = sum(
                    utility_scores[candidate.player_id]
                    for candidate in replacement_players
                )
                direct_replacements.append(
                    Squad(replacement_players, replacement_score)
                )
            if not direct_replacements:
                return {
                    "feasible": None,
                    "scope": "fast_direct_replacement",
                    "reason": (
                        "no legal one-for-one replacement; use "
                        "--exact-counterfactuals only when a full package "
                        "comparison is material"
                    ),
                }
            forced = max(
                direct_replacements,
                key=lambda candidate: candidate.objective_score,
            )
            if float(
                getattr(args, "min_core_budget_share", 0.0)
            ) > 0:
                forced = finalize_reliable_core_architecture(
                    forced,
                    players,
                    utility_scores,
                    raw_scores,
                    budget=args.budget,
                    club_cap=args.max_outfield_per_club,
                    min_reliable_anchors=args.min_reliable_anchors,
                    min_attacking_anchors=getattr(
                        args,
                        "min_attacking_anchors",
                        0,
                    ),
                    min_core_budget_share=getattr(
                        args,
                        "min_core_budget_share",
                        0.0,
                    ),
                    target_core_budget_share=getattr(
                        args,
                        "effective_core_budget_share_target",
                        0.0,
                    ),
                    minimum_spend=minimum_spend,
                    min_offensive_premium_anchors=getattr(
                        args,
                        "min_offensive_premium_anchors",
                        0,
                    ),
                    min_qualified_potential_core=int(
                        getattr(
                            args,
                            "min_qualified_potential_core",
                            0,
                        )
                    ),
                    target_qualified_potential_core=int(
                        getattr(
                            args,
                            "target_qualified_potential_core",
                            0,
                        )
                    ),
                    maintenance=getattr(
                        args,
                        "maintenance",
                        "normal",
                    ),
                    same_club_goalkeepers=not args.mixed_goalkeepers,
                    protected_player_ids=frozenset(
                        {player.player_id}
                    ),
                )
            counterfactual_scope = "best_feasible_direct_replacement"
        forced_utility, forced_objective_valid = finalized_squad_objective(
            forced,
            players,
            utility_scores,
            raw_scores,
            args,
        )
        if not forced_objective_valid:
            return {
                "feasible": False,
                "scope": counterfactual_scope,
                "reason": (
                    "candidate package fails the finalized starting-XI and "
                    "bench architecture"
                ),
            }
        if forced_utility > optimum_score + 1e-9:
            return {
                "feasible": None,
                "scope": counterfactual_scope,
                "reason": (
                    "finalized counterfactual exceeds the current reference "
                    "optimum; re-optimize the reference before reporting a "
                    "percentage comparison"
                ),
                "model_utility": round(forced_utility, 3),
                "best_pool_utility": round(optimum_score, 3),
                "requires_reference_reoptimization": True,
            }
        forced_ids = forced.ids

        def compact(candidate: Player) -> dict[str, Any]:
            return {
                "id": candidate.player_id,
                "name": candidate.name,
                "position": candidate.position,
                "cost": candidate.cost,
                "utility_score": round(
                    utility_scores[candidate.player_id],
                    3,
                ),
            }

        displaced = sorted(
            (
                candidate
                for candidate in squad.players
                if candidate.player_id not in forced_ids
            ),
            key=lambda candidate: (
                POSITION_ORDER[candidate.position],
                candidate.name,
            ),
        )
        added = sorted(
            (
                candidate
                for candidate in forced.players
                if candidate.player_id not in selected_ids
            ),
            key=lambda candidate: (
                POSITION_ORDER[candidate.position],
                candidate.name,
            ),
        )
        return {
            "feasible": True,
            "scope": counterfactual_scope,
            "cost": forced.cost,
            "budget_delta_vs_selected": forced.cost - squad.cost,
            "model_utility": round(forced_utility, 3),
            "utility_gap_vs_selected_percent": round(
                100.0
                * (squad_score - forced_utility)
                / max(abs(squad_score), 1e-9),
                3,
            ),
            "displaced_players": [compact(candidate) for candidate in displaced],
            "additional_players": [compact(candidate) for candidate in added],
        }

    comparison_candidates: list[dict[str, Any]] = []
    comparison_ids: set[str] = set()
    for position in ("DEFENDER", "MIDFIELDER", "FORWARD"):
        selected_position = [
            player for player in squad.players if player.position == position
        ]
        cutoff = min(
            selected_position,
            key=lambda player: (
                utility_scores[player.player_id],
                -player.cost,
                player.name,
            ),
        )
        omitted = sorted(
            (
                player
                for player in players
                if player.position == position and player.player_id not in selected_ids
            ),
            key=lambda player: (
                -utility_scores[player.player_id],
                player.cost,
                player.name,
            ),
        )
        required = omitted[:2]
        benchmarks = [player for player in omitted if player.benchmark]
        for player in (*required, *benchmarks):
            if player.player_id in comparison_ids:
                continue
            comparison_ids.add(player.player_id)
            comparison = serialize_player(player, comparison_to=cutoff)
            comparison["counterfactual"] = counterfactual_for(player)
            comparison_candidates.append(comparison)

    benchmark_audit = [
        {
            **serialize_player(player),
            "selected": player.player_id in selected_ids,
        }
        for player in sorted(
            (player for player in players if player.benchmark),
            key=lambda player: (
                POSITION_ORDER[player.position],
                -utility_scores[player.player_id],
                player.name,
            ),
        )
    ]
    anchor_budget = sum(player.cost for player in selected_anchors)
    attacking_anchors = [
        player
        for player in selected_anchors
        if player.position in {"MIDFIELDER", "FORWARD"}
    ]
    core_attacking_anchors = [
        player
        for player in attacking_anchors
        if player.player_id in core_ids
    ]
    offensive_premium_anchors = [
        player
        for player in squad.players
        if is_offensive_premium_anchor(player)
    ]
    core_offensive_premium_anchors = [
        player
        for player in offensive_premium_anchors
        if player.player_id in core_ids
    ]
    core_players = [
        player for player in squad.players if player.player_id in core_ids
    ]
    core_budget = sum(player.cost for player in core_players)
    core_budget_share = core_budget / max(squad.cost, 1)
    effective_core_target = float(
        getattr(args, "effective_core_budget_share_target", 0.0)
    )
    if (
        effective_core_target > 0
        and core_budget_share + 1e-9 < effective_core_target
    ):
        warnings.append(
            "The optimizer-reachable starting-core target could not be fully "
            "reached inside the quality, role and exact-budget constraints; "
            f"selected={core_budget_share:.1%}, "
            f"target={effective_core_target:.1%}."
        )
    architecture_audit = dict(squad.architecture_diagnostics)
    architecture_audit.pop("player_contributions", None)
    architecture_audit.pop("player_usage_weights", None)
    if architecture_audit:
        architecture_audit[
            "optimizer_reachable_core_budget_share_target_percent"
        ] = round(
            100.0
            * float(
                architecture_audit.get(
                    "optimizer_reachable_core_budget_share_target",
                    0.0,
                )
            ),
            3,
        )
        architecture_audit["selected_core_budget_share_percent"] = round(
            100.0
            * float(
                architecture_audit.get(
                    "selected_core_budget_share",
                    0.0,
                )
            ),
            3,
        )
        architecture_audit["forward_core_budget_share_percent"] = round(
            100.0
            * float(
                architecture_audit.get(
                    "forward_core_budget_share",
                    0.0,
                )
            ),
            3,
        )
        architecture_audit["forward_core_budget_target_percent"] = round(
            100.0
            * float(
                architecture_audit.get(
                    "forward_core_budget_target",
                    0.0,
                )
            ),
            3,
        )
        architecture_audit["midfield_core_budget_share_percent"] = round(
            100.0
            * float(
                architecture_audit.get(
                    "midfield_core_budget_share",
                    0.0,
                )
            ),
            3,
        )
        architecture_audit["midfield_core_budget_target_percent"] = round(
            100.0
            * float(
                architecture_audit.get(
                    "midfield_core_budget_target",
                    0.0,
                )
            ),
            3,
        )
        if not architecture_audit.get(
            "forward_core_budget_target_met",
            True,
        ):
            warnings.append(
                "The forward budget is still spread too evenly across all "
                "five slots; prefer one or two stronger starting attackers "
                "and cheaper fourth/fifth forwards."
            )
        if not architecture_audit.get(
            "midfield_core_budget_target_met",
            True,
        ):
            warnings.append(
                "The midfield budget is still spread too evenly across all "
                "seven slots; prefer stronger starters and cheaper sixth/"
                "seventh midfielders."
            )
        if not architecture_audit.get(
            "premium_starter_target_met",
            True,
        ):
            warnings.append(
                "No quality-qualified player from the highest offensive "
                "price tier reached the starting eleven."
            )
        if float(
            architecture_audit.get(
                "defensive_overspend_adjustment",
                0.0,
            )
        ) < 0:
            warnings.append(
                "The defense exceeds its soft opportunity-cost budget "
                "while a quality-qualified attacking scorer is available; "
                "recheck a multi-player reallocation toward midfield or "
                "attack."
            )
        if not architecture_audit.get(
            "qualified_potential_core_minimum_met",
            True,
        ):
            warnings.append(
                "The extended sporting core contains no qualified U23 "
                "potential investment despite suitable candidates."
            )
        if not architecture_audit.get(
            "qualified_potential_starter_minimum_met",
            True,
        ):
            warnings.append(
                "No evidence-qualified U23 potential player reached the "
                "starting eleven despite suitable candidates."
            )
        if not architecture_audit.get(
            "qualified_potential_core_target_met",
            True,
        ):
            warnings.append(
                "The extended sporting core meets its minimum youth floor, "
                "but remains below the evidence-qualified U23 target."
            )
        defender_architecture = architecture_audit.get(
            "defender_architecture",
            {},
        )
        if (
            isinstance(defender_architecture, dict)
            and not defender_architecture.get("passes", True)
        ):
            warnings.append(
                "The defense fails the playable-floor gate: too many "
                "minimum-price defenders or too few lineup-ready starters."
            )
        if float(
            architecture_audit.get("starting_xi_average_age") or 0.0
        ) > 28.0:
            warnings.append(
                "The projected starting eleven averages above 28 years; "
                "verify that the experience premium is worth the missing "
                "development upside."
            )
    architecture_contributions = squad.architecture_diagnostics.get(
        "player_contributions",
        {},
    )
    if not architecture_contributions:
        fallback_usage_weights = bench_player_usage_weights(
            squad,
            set(core_ids),
            raw_scores,
            args.maintenance,
        )
        architecture_contributions = {
            player.player_id: raw_scores[player.player_id]
            * fallback_usage_weights[player.player_id]
            for player in squad.players
        }
    budget_allocation_by_position: dict[str, dict[str, Any]] = {}
    for position in DEFAULT_SLOTS:
        position_players = [
            player
            for player in squad.players
            if player.position == position
        ]
        core_position_players = [
            player
            for player in position_players
            if player.player_id in core_ids
        ]
        reserve_position_players = [
            player
            for player in position_players
            if player.player_id not in core_ids
        ]
        core_spend = sum(
            player.cost for player in core_position_players
        )
        reserve_spend = sum(
            player.cost for player in reserve_position_players
        )
        core_contribution = sum(
            float(architecture_contributions.get(player.player_id, 0.0))
            for player in core_position_players
        )
        reserve_contribution = sum(
            float(architecture_contributions.get(player.player_id, 0.0))
            for player in reserve_position_players
        )
        budget_allocation_by_position[position] = {
            "core_spend": core_spend,
            "reserve_spend": reserve_spend,
            "core_budget_share_percent": round(
                100.0 * core_spend / max(core_spend + reserve_spend, 1),
                3,
            ),
            "core_expected_contribution": round(
                core_contribution,
                3,
            ),
            "reserve_expected_contribution": round(
                reserve_contribution,
                3,
            ),
            "core_contribution_per_100k": round(
                core_contribution / max(core_spend / 100_000, 1e-9),
                3,
            ),
            "reserve_contribution_per_100k": round(
                reserve_contribution
                / max(reserve_spend / 100_000, 1e-9),
                3,
            ),
        }
    return {
        "profile": args.profile,
        "maintenance": args.maintenance,
        "variation": args.variation,
        "seed": seed,
        "budget": args.budget,
        "budget_contract": {
            "competition": getattr(args, "competition", None),
            "fixed_budget": COMPETITION_BUDGETS.get(
                getattr(args, "competition", None)
            ),
            "matches": (
                COMPETITION_BUDGETS.get(getattr(args, "competition", None))
                in {None, args.budget}
            ),
        },
        "cost": squad.cost,
        "remaining_budget": args.budget - squad.cost,
        "score": round(raw_squad_score, 3),
        "optimal_score": round(raw_optimum_score, 3),
        "model_utility": round(visible_squad_utility, 3),
        "best_pool_utility": round(optimum_score, 3),
        "quality_gap_percent": round(max(0.0, quality_gap), 3),
        "quality_gap_metric": "finalized_starting_xi_and_bench_objective",
        "optimization_scope": {
            "eligible_players": len(players),
            "basis": (
                "technical_unannotated_smoke_pool"
                if bool(getattr(args, "allow_unannotated", False))
                else "fully_annotated_candidate_pool"
            ),
            "quality_gap_reference": (
                "best_feasible_squad_within_this_annotated_pool"
            ),
            "core_weighting": (
                "strong_starting_core_affordable_playable_reserve"
                if args.maintenance == "low"
                else "uniform_player_utility"
            ),
        },
        "distance_from_optimum": distance,
        "variation_target_met": variation_target_met,
        "portfolio": portfolio_audit or {
            "size": 1,
            "index": 1,
            "base_seed": seed,
            "selected_seed": seed,
            "unique_rosters": 1,
            "common_player_ids": sorted(squad.ids),
            "common_player_count": len(squad.ids),
            "common_starting_player_ids": sorted(core_ids),
            "common_starting_player_count": len(core_ids),
            "common_reliable_anchor_ids": sorted(
                player.player_id
                for player in squad.players
                if player.reliable_anchor
            ),
            "common_benchmark_ids": sorted(
                player.player_id
                for player in squad.players
                if player.benchmark
            ),
            "max_reliable_anchor_exposure_allowed": 1,
            "max_reliable_anchor_exposure": int(bool(selected_anchors)),
            "reliable_anchor_exposure": {
                player.player_id: 1
                for player in selected_anchors
            },
            "anchor_diversity_target_met": True,
            "max_player_exposure": 1,
        },
        "suggested_starting_lineup": {
            "formation": formation,
            "player_ids": sorted(core_ids),
            "reliable_anchors": core_anchor_count,
            "reliable_anchors_required": core_anchor_requirement,
            "budget": core_budget,
            "budget_share_percent": round(100.0 * core_budget_share, 3),
            "offensive_premium_anchors": len(
                core_offensive_premium_anchors
            ),
            "offensive_premium_anchor_names": sorted(
                player.name
                for player in core_offensive_premium_anchors
            ),
            "offensive_premium_anchors_required": int(
                getattr(args, "min_offensive_premium_anchors", 0)
            ),
        },
        "squad_architecture": architecture_audit,
        "budget_allocation": {
            "policy": (
                "exact_budget_joint_starting_xi_and_position_weighted_reserves"
            ),
            "by_position": budget_allocation_by_position,
            "lowest_marginal_value_slots": [
                {
                    "id": player.player_id,
                    "name": player.name,
                    "position": player.position,
                    "selection_role": (
                        "core"
                        if player.player_id in core_ids
                        else "bench"
                    ),
                    "cost": player.cost,
                    "expected_contribution": round(
                        float(
                            architecture_contributions.get(
                                player.player_id,
                                0.0,
                            )
                        ),
                        3,
                    ),
                    "contribution_per_100k": round(
                        float(
                            architecture_contributions.get(
                                player.player_id,
                                0.0,
                            )
                        )
                        / max(player.cost / 100_000, 1e-9),
                        3,
                    ),
                }
                for player in sorted(
                    squad.players,
                    key=lambda player: (
                        float(
                            architecture_contributions.get(
                                player.player_id,
                                0.0,
                            )
                        )
                        / max(player.cost / 100_000, 1e-9),
                        player.player_id,
                    ),
                )[:5]
            ],
        },
        "reliable_anchor_policy": {
            "required": args.min_reliable_anchors,
            "eligible": sum(
                player.reliable_anchor
                for player in players
                if player.position != "GOALKEEPER"
            ),
            "selected": len(selected_anchors),
            "selected_names": sorted(player.name for player in selected_anchors),
            "budget": anchor_budget,
            "budget_share_percent": round(
                100.0 * anchor_budget / max(args.budget, 1),
                3,
            ),
            "attacking_required": int(
                getattr(args, "min_attacking_anchors", 0)
            ),
            "attacking_selected": len(attacking_anchors),
            "attacking_selected_names": sorted(
                player.name for player in attacking_anchors
            ),
            "attacking_core": len(core_attacking_anchors),
            "attacking_core_names": sorted(
                player.name for player in core_attacking_anchors
            ),
            "offensive_premium_required": int(
                getattr(args, "min_offensive_premium_anchors", 0)
            ),
            "offensive_premium_selected": len(
                offensive_premium_anchors
            ),
            "offensive_premium_selected_names": sorted(
                player.name for player in offensive_premium_anchors
            ),
            "offensive_premium_core": len(
                core_offensive_premium_anchors
            ),
            "offensive_premium_core_names": sorted(
                player.name
                for player in core_offensive_premium_anchors
            ),
            "minimum_core_budget_share_percent": round(
                100.0 * float(
                    getattr(args, "min_core_budget_share", 0.0)
                ),
                3,
            ),
            "requested_core_budget_share_target_percent": round(
                100.0 * float(
                    getattr(args, "target_core_budget_share", 0.0)
                ),
                3,
            ),
            "price_ceiling_core_budget_share_target_percent": round(
                100.0 * float(
                    getattr(
                        args,
                        "price_ceiling_core_budget_share_target",
                        0.0,
                    )
                ),
                3,
            ),
            "optimizer_reachable_core_budget_share_target_percent": round(
                100.0 * float(
                    getattr(
                        args,
                        "effective_core_budget_share_target",
                        0.0,
                    )
                ),
                3,
            ),
            "market_adjusted_core_budget_share_target_percent": round(
                100.0 * float(
                    getattr(
                        args,
                        "effective_core_budget_share_target",
                        0.0,
                    )
                ),
                3,
            ),
        },
        "goalkeeper_mode": (
            "mixed" if args.mixed_goalkeepers else "same_club"
        ),
        "goalkeeper_hierarchy_policy": {
            "maintenance": args.maintenance,
            "season_starter_probability_minimum": (
                70 if args.maintenance == "low"
                else 60 if args.maintenance == "normal"
                else 48
            ),
            "external_signing_risk_maximum": (
                40 if args.maintenance == "low"
                else 55 if args.maintenance == "normal"
                else 70
            ),
            "open_competition_allowed": args.maintenance == "active",
        },
        "annotated_players": annotated_count,
        "annotated_players_by_position": annotated_by_position,
        "annotated_goalkeeper_blocks": annotated_goalkeeper_blocks,
        "comparison_candidates": comparison_candidates,
        "benchmark_audit": benchmark_audit,
        "hard_exclusions": hard_exclusions,
        "news_audit": news_audit,
        "market_audit": market_audit or {
            "status": "not_configured",
            "required": False,
        },
        "warnings": warnings,
        "squad": [
            serialize_player(
                player,
                selection_role=(
                    "core" if player.player_id in core_ids else "bench"
                ),
            )
            for player in ordered
        ],
    }


def shortlist_payload(
    players: list[Player],
    scores: dict[str, float],
    profile: str,
    slots: dict[str, int],
    market_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "profile": profile,
        "purpose": (
            "Research these baseline and unproven-value candidates before final optimization."
        ),
        "market_audit": market_audit or {
            "status": "not_configured",
        },
        "shortlist": {},
    }
    for position, slot_count in slots.items():
        candidates = [player for player in players if player.position == position]
        confirmed = sorted(
            candidates,
            key=lambda player: (
                -scores[player.player_id],
                player.cost,
                player.name,
            ),
        )[: max(6, slot_count * 2)]
        unproven = sorted(
            (player for player in candidates if player.points <= 0),
            key=lambda player: (
                -(
                    player.components["upside"]
                    + player.components["value"]
                    - player.risks["unknown_role"] * 0.5
                ),
                player.cost,
                player.name,
            ),
        )[: max(4, slot_count)]
        premium_review_pool: dict[str, Player] = {}
        premium_count = max(6, slot_count)
        for ranked in (
            sorted(
                candidates,
                key=lambda player: (-player.cost, player.name),
            ),
            sorted(
                candidates,
                key=lambda player: (-player.points, player.name),
            ),
            sorted(
                candidates,
                key=lambda player: (-scores[player.player_id], player.name),
            ),
        ):
            for player in ranked[:premium_count]:
                premium_review_pool[player.player_id] = player
        # Surface evidence-backed role winners even when their old Kicker
        # points do not place them in the generic top-price/top-score buckets.
        # This is intentionally name-free and does not force selection; it
        # ensures that promoted creators, set-piece takers and focal attackers
        # receive an explicit review before optimization.
        for player in candidates:
            role = player.role_context
            responsibilities = role.get("responsibilities", {})
            has_attacking_responsibility = (
                isinstance(responsibilities, dict)
                and any(
                    responsibilities.get(key) in {"shared", "primary"}
                    for key in (
                        "penalties",
                        "direct_free_kicks",
                        "corners",
                        "playmaker",
                        "offensive_focal_point",
                        "aerial_set_piece_target",
                    )
                )
            )
            if (
                role.get("continuity") in {"confirmed", "expanded"}
                and float(role.get("expected_start_probability", 0)) >= 75
                and has_attacking_responsibility
            ):
                premium_review_pool[player.player_id] = player
        premium_review = sorted(
            premium_review_pool.values(),
            key=lambda player: (
                -scores[player.player_id],
                -player.cost,
                player.name,
            ),
        )

        def serialize(player: Player) -> dict[str, Any]:
            return {
                "id": player.player_id,
                "name": player.name,
                "club": player.club,
                "position": player.position,
                "cost": player.cost,
                "points": player.points,
                "grade": player.grade,
                "baseline_score": round(scores[player.player_id], 3),
            }

        result["shortlist"][position] = {
            "confirmed": [serialize(player) for player in confirmed],
            "unproven_value": [serialize(player) for player in unproven],
            "premium_review": [serialize(player) for player in premium_review],
        }
    return result


def print_text(payload: dict[str, Any]) -> None:
    print(
        f"Profile={payload['profile']} variation={payload['variation']} "
        f"maintenance={payload['maintenance']} seed={payload['seed']}"
    )
    print(
        f"Cost={payload['cost']} remaining={payload['remaining_budget']} "
        f"annotated_pool_gap={payload['quality_gap_percent']}%"
    )
    portfolio = payload["portfolio"]
    if portfolio["size"] > 1:
        print(
            "Portfolio="
            f"{portfolio['index']}/{portfolio['size']} "
            f"unique={portfolio['unique_rosters']} "
            f"common_players={portfolio['common_player_count']} "
            "max_anchor_exposure="
            f"{portfolio['max_reliable_anchor_exposure']}"
        )
    anchor_policy = payload["reliable_anchor_policy"]
    print(
        "Reliable anchors="
        f"{anchor_policy['selected']}/{anchor_policy['required']} "
        f"starting formation={payload['suggested_starting_lineup']['formation']}"
    )
    current_position = None
    for player in payload["squad"]:
        if player["position"] != current_position:
            current_position = player["position"]
            print(f"\n{current_position}")
        print(
            f"- {player['name']} | {player['club']} | "
            f"{player['cost']} | {player['selection_role']} | "
            f"score {player['score']}"
        )
    for warning in payload["warnings"]:
        print(f"\nWARNING: {warning}", file=sys.stderr)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    player_source = parser.add_mutually_exclusive_group()
    player_source.add_argument(
        "--players",
        type=Path,
        help="Local official Kicker semicolon CSV fallback",
    )
    player_source.add_argument(
        "--market-snapshot",
        default=os.environ.get("KICKER_MARKET_FEED_URL"),
        help=(
            "Central market JSON path or HTTPS URL; defaults by competition "
            "and season when no local CSV is supplied"
        ),
    )
    parser.add_argument(
        "--market-token-env",
        default="KICKER_MARKET_FEED_TOKEN",
        help="Environment variable containing an optional market feed token",
    )
    parser.add_argument(
        "--require-market-snapshot",
        action="store_true",
        help="Stop unless a fresh, matching central market snapshot is available",
    )
    parser.add_argument(
        "--quality-snapshot",
        default=os.environ.get("KICKER_QUALITY_FEED_URL"),
        help=(
            "Central multi-season quality JSON path or HTTPS URL; defaults by "
            "competition and season when no local CSV is supplied"
        ),
    )
    parser.add_argument(
        "--quality-token-env",
        default="KICKER_QUALITY_FEED_TOKEN",
        help="Environment variable containing an optional quality feed token",
    )
    parser.add_argument(
        "--require-quality-snapshot",
        action="store_true",
        help="Stop unless a fresh quality pool matching market and season is available",
    )
    parser.add_argument("--annotations", type=Path, help="Current player annotations JSON")
    parser.add_argument(
        "--competition",
        choices=("Bundesliga", "2. Bundesliga", "3. Liga"),
        help="Competition used to verify the central news snapshot",
    )
    parser.add_argument(
        "--season",
        help="Season label used to verify the central news snapshot, for example 2026/27",
    )
    parser.add_argument(
        "--news-snapshot",
        default=os.environ.get("KICKER_NEWS_FEED_URL"),
        help=(
            "Local JSON path or HTTPS URL; defaults to KICKER_NEWS_FEED_URL. "
            "Bearer token is read from KICKER_NEWS_FEED_TOKEN."
        ),
    )
    parser.add_argument(
        "--news-token-env",
        default="KICKER_NEWS_FEED_TOKEN",
        help="Environment variable containing the optional central feed bearer token",
    )
    parser.add_argument(
        "--require-news-snapshot",
        action="store_true",
        help="Stop unless a fresh central news snapshot is available",
    )
    parser.add_argument(
        "--require-news-coverage",
        action="store_true",
        help="Stop unless every selected player has a provider mapping",
    )
    parser.add_argument(
        "--allow-news-conflicts",
        action="store_true",
        help="Technical override after conflicts were manually resolved; never use silently",
    )
    parser.add_argument(
        "--budget",
        type=int,
        help=(
            "Budget in whole euros; defaults to the fixed Kicker competition "
            "budget (Bundesliga 42.5m, 2. Bundesliga 10m, 3. Liga 6m)"
        ),
    )
    parser.add_argument(
        "--min-spend-ratio",
        type=float,
        default=None,
        help=(
            "Minimum fraction of budget to spend; defaults to 1.0 for final "
            "recommendations and 0 for technical smoke tests"
        ),
    )
    parser.add_argument("--goalkeepers", type=int, default=3)
    parser.add_argument(
        "--mixed-goalkeepers",
        action="store_true",
        help="Allow goalkeepers from different clubs; default is one club block",
    )
    parser.add_argument("--defenders", type=int, default=7)
    parser.add_argument("--midfielders", type=int, default=7)
    parser.add_argument("--forwards", type=int, default=5)
    parser.add_argument("--profile", default="reliable", choices=sorted(PROFILE_ALIASES))
    parser.add_argument("--maintenance", default="low", choices=sorted(MAINTENANCE_ALIASES))
    parser.add_argument("--variation", default="medium", choices=sorted(VARIATION_ALIASES))
    parser.add_argument("--seed", type=int, help="Reproducible variation seed")
    parser.add_argument(
        "--new-variant",
        action="store_true",
        help=(
            "Advance the anonymous local variant for this league, season and "
            "strategy; use when the user asks for another squad"
        ),
    )
    parser.add_argument(
        "--variation-state",
        type=Path,
        help=(
            "Advanced override for the private local variation state path; "
            f"defaults to {VARIATION_STATE_ENV}, CODEX_HOME or the user profile"
        ),
    )
    parser.add_argument(
        "--portfolio-size",
        type=int,
        default=1,
        help=(
            "Generate a reproducible diversified group portfolio of this size; "
            "use the same seed for every member"
        ),
    )
    parser.add_argument(
        "--portfolio-index",
        type=int,
        help=(
            "Select the one-based member slot from the diversified portfolio; "
            "defaults to a seed-derived slot"
        ),
    )
    parser.add_argument(
        "--max-anchor-exposure",
        type=int,
        default=1,
        help=(
            "Maximum number of coordinated portfolio squads containing the "
            "same reliable anchor; default 1"
        ),
    )
    parser.add_argument(
        "--min-reliable-anchors",
        type=int,
        help=(
            "Minimum repeatable premium field-player anchors; default 4 for "
            "a final reliable squad and 0 otherwise"
        ),
    )
    parser.add_argument(
        "--min-attacking-anchors",
        type=int,
        help=(
            "Minimum reliable anchors in midfield or attack; default 3 for "
            "a final reliable squad and 0 otherwise"
        ),
    )
    parser.add_argument(
        "--min-core-budget-share",
        type=float,
        help=(
            "Minimum share of total squad cost assigned to the best legal "
            "starting eleven; default 0.55 for every low-maintenance profile"
        ),
    )
    parser.add_argument(
        "--target-core-budget-share",
        type=float,
        help=(
            "Desired starting-eleven budget share before applying the current "
            "market's positional price ceiling; default 0.80 for every "
            "low-maintenance profile"
        ),
    )
    parser.add_argument(
        "--min-offensive-premium-anchors",
        type=int,
        help=(
            "Minimum evidence-derived multi-season premium scorers or creators "
            "inside the best legal starting eleven; default 1 for a final "
            "reliable low-maintenance squad and 0 otherwise"
        ),
    )
    parser.add_argument(
        "--min-qualified-potential-core",
        type=int,
        help=(
            "Minimum qualified U23 potential players in the extended core; "
            "a positive minimum also requires one of them in the starting "
            "eleven. Default 1 for a final reliable low-maintenance squad"
        ),
    )
    parser.add_argument(
        "--target-qualified-potential-core",
        type=int,
        help=(
            "Desired number of qualified U23 potential players in the same "
            "extended core; default 2 for a final reliable low-maintenance "
            "squad"
        ),
    )
    parser.add_argument(
        "--max-outfield-per-club",
        type=int,
        help="Maximum outfield players from one club",
    )
    parser.add_argument(
        "--avoid-roster",
        type=Path,
        action="append",
        default=[],
        help="Prior optimizer JSON whose players should be de-emphasized; repeatable",
    )
    parser.add_argument(
        "--shortlist-only",
        action="store_true",
        help="Emit a research shortlist and skip final optimization",
    )
    parser.add_argument(
        "--allow-unannotated",
        action="store_true",
        help="Allow incomplete current annotations for technical smoke tests only",
    )
    parser.add_argument(
        "--exact-counterfactuals",
        action="store_true",
        help=(
            "Run a separate full optimization for every near-miss. The fast "
            "default evaluates the best legal direct replacement instead."
        ),
    )
    parser.add_argument(
        "--optimizer-cache",
        type=Path,
        default=default_optimizer_cache_path(),
        help=(
            "Directory for checksum-bound seed-independent optima; defaults "
            "to the local Codex cache"
        ),
    )
    parser.add_argument(
        "--no-optimizer-cache",
        action="store_const",
        const=None,
        dest="optimizer_cache",
        help="Disable the local seed-independent optimum cache",
    )
    parser.add_argument("--format", choices=("json", "text"), default="text")
    parser.add_argument("--output", type=Path, help="Optional output file")
    args = parser.parse_args()
    if not args.players and not args.market_snapshot and args.competition and args.season:
        args.market_snapshot = DEFAULT_MARKET_FEEDS.get(
            (args.competition, args.season)
        )
    if not args.news_snapshot and args.competition and args.season:
        args.news_snapshot = DEFAULT_NEWS_FEEDS.get(
            (args.competition, args.season)
        )
    if (
        not args.players
        and not args.quality_snapshot
        and args.competition
        and args.season
    ):
        args.quality_snapshot = DEFAULT_QUALITY_FEEDS.get(
            (args.competition, args.season)
        )
    args.profile = PROFILE_ALIASES[args.profile]
    args.maintenance = MAINTENANCE_ALIASES[args.maintenance]
    args.variation = VARIATION_ALIASES[args.variation]
    expected_budget = COMPETITION_BUDGETS.get(args.competition)
    if args.budget is None:
        if expected_budget is None:
            parser.error(
                "--budget is required when no competition is supplied"
            )
        args.budget = expected_budget
    elif (
        expected_budget is not None
        and args.budget != expected_budget
        and not args.allow_unannotated
    ):
        parser.error(
            f"--budget must be {expected_budget} for {args.competition}; "
            "competition budgets are fixed Kicker rules"
        )
    if args.players and args.market_snapshot:
        parser.error("--players and --market-snapshot cannot be combined")
    if not args.players and not args.market_snapshot:
        parser.error(
            "set --players or --market-snapshot, or use a competition and "
            "season with a configured central market"
        )
    if args.require_market_snapshot and not args.market_snapshot:
        parser.error(
            "--require-market-snapshot cannot be used with only a local CSV"
        )
    if args.require_quality_snapshot and not args.quality_snapshot:
        parser.error(
            "--require-quality-snapshot needs a central quality snapshot"
        )
    if args.players and args.quality_snapshot:
        parser.error(
            "--quality-snapshot can only be combined with --market-snapshot"
        )
    if args.max_outfield_per_club is None:
        args.max_outfield_per_club = DEFAULT_CLUB_CAP[args.profile]
    if args.max_outfield_per_club < 1:
        parser.error("--max-outfield-per-club must be positive")
    if args.portfolio_size < 1:
        parser.error("--portfolio-size must be positive")
    if args.max_anchor_exposure < 1:
        parser.error("--max-anchor-exposure must be positive")
    if args.seed is not None and args.new_variant:
        parser.error("--new-variant cannot be combined with an explicit --seed")
    if args.portfolio_index is not None and not (
        1 <= args.portfolio_index <= args.portfolio_size
    ):
        parser.error("--portfolio-index must be inside --portfolio-size")
    if args.portfolio_size > 1 and args.variation == "none":
        parser.error("--portfolio-size greater than one requires variation")
    if args.min_reliable_anchors is None:
        args.min_reliable_anchors = (
            4
            if args.profile == "reliable" and not args.allow_unannotated
            else 0
        )
    if args.min_attacking_anchors is None:
        args.min_attacking_anchors = (
            3
            if args.profile == "reliable" and not args.allow_unannotated
            else 0
        )
    if args.min_core_budget_share is None:
        args.min_core_budget_share = (
            0.55
            if (
                args.maintenance == "low"
                and not args.allow_unannotated
            )
            else 0.0
        )
    if args.target_core_budget_share is None:
        args.target_core_budget_share = (
            max(0.80, args.min_core_budget_share)
            if (
                args.maintenance == "low"
                and not args.allow_unannotated
            )
            else 0.0
        )
    if args.min_spend_ratio is None:
        args.min_spend_ratio = (
            0.0
            if args.allow_unannotated or args.shortlist_only
            else 1.0
        )
    if args.min_offensive_premium_anchors is None:
        args.min_offensive_premium_anchors = (
            1
            if (
                args.profile == "reliable"
                and args.maintenance == "low"
                and not args.allow_unannotated
            )
            else 0
        )
    if args.min_qualified_potential_core is None:
        args.min_qualified_potential_core = (
            1
            if (
                args.profile == "reliable"
                and args.maintenance == "low"
                and not args.allow_unannotated
            )
            else 0
        )
    if args.target_qualified_potential_core is None:
        args.target_qualified_potential_core = (
            2
            if (
                args.profile == "reliable"
                and args.maintenance == "low"
                and not args.allow_unannotated
            )
            else args.min_qualified_potential_core
        )
    if args.min_reliable_anchors < 0:
        parser.error("--min-reliable-anchors cannot be negative")
    if args.min_attacking_anchors < 0:
        parser.error("--min-attacking-anchors cannot be negative")
    if args.min_offensive_premium_anchors < 0:
        parser.error("--min-offensive-premium-anchors cannot be negative")
    if args.min_qualified_potential_core < 0:
        parser.error("--min-qualified-potential-core cannot be negative")
    if args.target_qualified_potential_core < 0:
        parser.error("--target-qualified-potential-core cannot be negative")
    if (
        args.target_qualified_potential_core
        < args.min_qualified_potential_core
    ):
        parser.error(
            "--target-qualified-potential-core cannot be below "
            "--min-qualified-potential-core"
        )
    if not 0.0 <= args.min_core_budget_share <= 1.0:
        parser.error("--min-core-budget-share must be between 0 and 1")
    if not 0.0 <= args.target_core_budget_share <= 1.0:
        parser.error("--target-core-budget-share must be between 0 and 1")
    if args.target_core_budget_share < args.min_core_budget_share:
        parser.error(
            "--target-core-budget-share cannot be below "
            "--min-core-budget-share"
        )
    if not 0.0 <= args.min_spend_ratio <= 1.0:
        parser.error("--min-spend-ratio must be between 0 and 1")
    if (
        not args.allow_unannotated
        and not args.shortlist_only
        and args.min_spend_ratio != 1.0
    ):
        parser.error(
            "--min-spend-ratio must be 1.0 for final recommendations; "
            "lower values are only allowed with --allow-unannotated or "
            "--shortlist-only"
        )
    args.slots = {
        "GOALKEEPER": args.goalkeepers,
        "DEFENDER": args.defenders,
        "MIDFIELDER": args.midfielders,
        "FORWARD": args.forwards,
    }
    if any(value < 1 for value in args.slots.values()):
        parser.error("all positional slot counts must be positive")
    field_slots = (
        args.slots["DEFENDER"]
        + args.slots["MIDFIELDER"]
        + args.slots["FORWARD"]
    )
    if args.min_reliable_anchors > field_slots:
        parser.error("--min-reliable-anchors exceeds the number of field slots")
    if args.min_attacking_anchors > (
        args.slots["MIDFIELDER"] + args.slots["FORWARD"]
    ):
        parser.error(
            "--min-attacking-anchors exceeds midfield and forward slots"
        )
    if args.min_attacking_anchors > args.min_reliable_anchors:
        parser.error(
            "--min-attacking-anchors cannot exceed --min-reliable-anchors"
        )
    if args.min_offensive_premium_anchors > args.min_attacking_anchors:
        parser.error(
            "--min-offensive-premium-anchors cannot exceed "
            "--min-attacking-anchors"
        )
    return args


def exclude_unresolved_role_research(
    players: list[Player],
) -> tuple[list[Player], list[dict[str, Any]]]:
    """Keep one unresolved transfer role from blocking the entire league."""

    unresolved = [
        player
        for player in players
        if (
            player.role_research.get("required") is True
            and str(player.role_research.get("priority", "")).casefold()
            == "high"
        )
    ]
    unresolved_ids = {player.player_id for player in unresolved}
    exclusions = [
        {
            "annotation_key": player.player_id,
            "reason": (
                "Vorübergehend nicht auswählbar: Nach dem Vereinswechsel "
                "fehlen belastbare aktuelle Belege für Startwahrscheinlichkeit "
                "und Verantwortlichkeiten."
            ),
            "benchmark": player.benchmark,
            "evidence": list(player.evidence),
            "temporary_role_research_exclusion": True,
            "player_name": player.name,
            "club": player.club,
        }
        for player in unresolved
    ]
    return (
        [
            player
            for player in players
            if player.player_id not in unresolved_ids
        ],
        exclusions,
    )


def main() -> int:
    args = parse_args()
    variation_source = "explicit"
    variation_generation: int | None = None
    variation_state_path = (
        args.variation_state or default_variation_state_path()
    )
    if args.seed is not None:
        seed = args.seed
    else:
        variation_source = "automatic_local"
        try:
            seed, variation_generation = automatic_variation_seed(
                state_path=variation_state_path,
                competition=args.competition,
                season=args.season,
                profile=args.profile,
                maintenance=args.maintenance,
                variation=args.variation,
                budget=args.budget,
                slots=args.slots,
                new_variant=args.new_variant,
            )
        except VariationStateError as error:
            print(f"Automatic variation stopped: {error}", file=sys.stderr)
            return 2
    portfolio_index = args.portfolio_index or (seed % args.portfolio_size) + 1
    if variation_source == "automatic_local":
        print(
            "Variation seed: "
            f"{seed} (automatic local variant {variation_generation})",
            file=sys.stderr,
            flush=True,
        )
    else:
        print(f"Variation seed: {seed}", file=sys.stderr, flush=True)
    if args.portfolio_size > 1:
        print(
            "Portfolio slot: "
            f"{portfolio_index}/{args.portfolio_size}",
            file=sys.stderr,
            flush=True,
        )
    local_annotations = load_annotations(args.annotations)
    annotations = local_annotations
    quality_audit: dict[str, Any] = {
        "status": "not_configured",
        "required": bool(args.require_quality_snapshot),
    }
    market_audit: dict[str, Any]
    if args.market_snapshot:
        try:
            market_payload = load_market_snapshot(
                args.market_snapshot,
                token_env=args.market_token_env,
            )
        except (MarketSnapshotError, OSError) as error:
            print(
                f"Central market loading stopped optimization: {error}",
                file=sys.stderr,
            )
            return 2
        if (
            args.competition
            and market_payload["competition"] != args.competition
        ):
            print(
                "Central market loading stopped optimization: snapshot "
                f"competition {market_payload['competition']!r} does not "
                f"match {args.competition!r}.",
                file=sys.stderr,
            )
            return 2
        if args.season and market_payload["season"] != args.season:
            print(
                "Central market loading stopped optimization: snapshot "
                f"season {market_payload['season']!r} does not match "
                f"{args.season!r}.",
                file=sys.stderr,
            )
            return 2
        annotations = dict(market_payload.get("annotations", {}))
        if args.quality_snapshot:
            try:
                quality_payload = load_quality_snapshot(
                    args.quality_snapshot,
                    token_env=args.quality_token_env,
                )
            except (QualitySnapshotError, OSError) as error:
                print(
                    f"Central quality loading stopped optimization: {error}",
                    file=sys.stderr,
                )
                return 2
            if quality_payload["competition"] != market_payload["competition"]:
                print(
                    "Central quality loading stopped optimization: competition "
                    "does not match the market snapshot.",
                    file=sys.stderr,
                )
                return 2
            if quality_payload["season"] != market_payload["season"]:
                print(
                    "Central quality loading stopped optimization: season does "
                    "not match the market snapshot.",
                    file=sys.stderr,
                )
                return 2
            current_market_sha = market_canonical_sha256(market_payload)
            if quality_payload["market_sha256"] != current_market_sha:
                print(
                    "Central quality loading stopped optimization: quality pool "
                    "was built for a different market snapshot.",
                    file=sys.stderr,
                )
                return 2
            annotations = merge_annotations(
                annotations,
                quality_payload["annotations"],
            )
            quality_audit = quality_snapshot_audit(quality_payload)
            quality_audit["required"] = bool(args.require_quality_snapshot)
        elif args.require_quality_snapshot:
            print(
                "Final optimization requires a fresh central quality snapshot.",
                file=sys.stderr,
            )
            return 2
        annotations = merge_annotations(annotations, local_annotations)
        players, annotated_count, annotated_by_position = (
            load_players_from_rows(
                market_csv_rows(market_payload),
                annotations,
            )
        )
        market_audit = market_snapshot_audit(market_payload)
        market_audit["required"] = bool(args.require_market_snapshot)
    else:
        if args.require_market_snapshot:
            print(
                "Final optimization requires a fresh central market snapshot.",
                file=sys.stderr,
            )
            return 2
        players, annotated_count, annotated_by_position = load_players(
            args.players,
            annotations,
        )
        market_audit = {
            "status": "local_csv",
            "required": False,
            "player_count": len(players),
        }
    hard_exclusions = [
        {
            "annotation_key": key,
            "reason": str(annotation.get("note", "")).strip(),
            "benchmark": bool(annotation.get("benchmark", False)),
            "evidence": (
                annotation.get("evidence", [])
                if isinstance(annotation.get("evidence", []), list)
                else []
            ),
        }
        for key, annotation in annotations.items()
        if bool(annotation.get("exclude", False))
    ]
    news_audit: dict[str, Any] = {
        "status": "not_configured",
        "required": bool(args.require_news_snapshot),
    }
    if not args.news_snapshot and args.require_news_snapshot:
        print(
            "Final optimization requires a fresh central news snapshot. Set "
            "--news-snapshot or KICKER_NEWS_FEED_URL.",
            file=sys.stderr,
        )
        return 2
    if args.news_snapshot:
        try:
            news_payload = load_snapshot(
                args.news_snapshot,
                token_env=args.news_token_env,
            )
        except (NewsSnapshotError, OSError) as error:
            print(f"News hardening stopped optimization: {error}", file=sys.stderr)
            return 2
        if (
            args.competition
            and news_payload["competition"] != args.competition
        ):
            print(
                "News hardening stopped optimization: snapshot competition "
                f"{news_payload['competition']!r} does not match "
                f"{args.competition!r}.",
                file=sys.stderr,
            )
            return 2
        if args.season and news_payload["season"] != args.season:
            print(
                "News hardening stopped optimization: snapshot season "
                f"{news_payload['season']!r} does not match {args.season!r}.",
                file=sys.stderr,
            )
            return 2
        players, news_audit, news_exclusions = apply_news_snapshot(
            players,
            news_payload,
        )
        hard_exclusions.extend(news_exclusions)
    if args.require_news_coverage:
        coverage_cleared_ids = set(
            news_audit.get(
                "coverage_cleared_player_ids",
                news_audit.get("provider_mapped_player_ids", []),
            )
        )
        players = [
            player
            for player in players
            if player.player_id in coverage_cleared_ids
        ]
    if not args.shortlist_only and not args.allow_unannotated:
        players, role_research_exclusions = (
            exclude_unresolved_role_research(players)
        )
        hard_exclusions.extend(role_research_exclusions)
        unresolved_role_research = sorted(
            exclusion["annotation_key"]
            for exclusion in role_research_exclusions
        )
        news_audit["role_research_excluded_player_ids"] = (
            unresolved_role_research
        )
    else:
        unresolved_role_research = []
    if unresolved_role_research:
        print(
            "Role research temporarily excluded unresolved transfer-role "
            "candidates while continuing with the fully cleared pool: "
            f"{unresolved_role_research}.",
            file=sys.stderr,
        )
    raw_scores = score_players(players, args.profile, args.maintenance)
    if args.shortlist_only:
        payload = shortlist_payload(
            players,
            raw_scores,
            args.profile,
            args.slots,
            market_audit,
        )
        payload["quality_audit"] = quality_audit
        rendered = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        print(rendered)
        return 0

    undocumented_benchmark_exclusions = [
        key
        for key, annotation in annotations.items()
        if (
            bool(annotation.get("exclude", False))
            and bool(annotation.get("benchmark", False))
            and (
                not str(annotation.get("note", "")).strip()
                or not evidence_is_complete(annotation)
            )
        )
    ]
    if undocumented_benchmark_exclusions and not args.allow_unannotated:
        print(
            "Excluded benchmark players need a concrete reason and current "
            "evidence before final optimization: "
            f"{sorted(undocumented_benchmark_exclusions)}.",
            file=sys.stderr,
        )
        return 2

    required_annotations = annotation_minimums(args.slots)
    missing_annotations = {
        position: {
            "actual": annotated_by_position[position],
            "required": minimum,
        }
        for position, minimum in required_annotations.items()
        if annotated_by_position[position] < minimum
    }
    researched_goalkeepers_by_club: dict[str, int] = {}
    for player in players:
        if player.position == "GOALKEEPER" and player.researched:
            researched_goalkeepers_by_club[player.club] = (
                researched_goalkeepers_by_club.get(player.club, 0) + 1
            )
    annotated_goalkeeper_blocks = sum(
        count >= args.slots["GOALKEEPER"]
        for count in researched_goalkeepers_by_club.values()
    )
    goalkeeper_blocks_missing = (
        not args.mixed_goalkeepers and annotated_goalkeeper_blocks < 2
    )
    if (missing_annotations or goalkeeper_blocks_missing) and not args.allow_unannotated:
        goalkeeper_status = (
            "mixed-goalkeeper mode requested"
            if args.mixed_goalkeepers
            else f"complete goalkeeper blocks: {annotated_goalkeeper_blocks}/2"
        )
        print(
            "Current annotations are incomplete. Research and annotate the shortlist "
            f"before final optimization: {missing_annotations}; "
            f"{goalkeeper_status}. "
            "Use --allow-unannotated only for a technical smoke test.",
            file=sys.stderr,
        )
        return 2

    eligible_players = (
        players
        if args.allow_unannotated
        else [player for player in players if player.researched]
    )
    if not args.mixed_goalkeepers:
        (
            eligible_players,
            goalkeeper_hierarchy_exclusions,
            hierarchy_safe_goalkeeper_blocks,
        ) = filter_goalkeeper_blocks_by_hierarchy(
            eligible_players,
            raw_scores,
            count=args.slots["GOALKEEPER"],
            maintenance=args.maintenance,
            require_hierarchy=(
                not args.allow_unannotated
                and quality_audit.get("model_version")
                == GOALKEEPER_HIERARCHY_MODEL
            ),
        )
        hard_exclusions.extend(goalkeeper_hierarchy_exclusions)
        annotated_goalkeeper_blocks = hierarchy_safe_goalkeeper_blocks
        if (
            hierarchy_safe_goalkeeper_blocks < 2
            and not args.allow_unannotated
        ):
            print(
                "Goalkeeper hierarchy research is incomplete: "
                f"only {hierarchy_safe_goalkeeper_blocks} blocks satisfy the "
                f"{args.maintenance!r} maintenance profile. Resolve the "
                "number-one competition and possible external signings for "
                "at least two clubs before optimization.",
                file=sys.stderr,
            )
            return 2
    eligible_raw_scores = {
        player.player_id: raw_scores[player.player_id]
        for player in eligible_players
    }
    if args.profile == "reliable" and not args.allow_unannotated:
        benchmark_counts = {
            position: sum(
                player.benchmark
                for player in eligible_players
                if player.position == position
            )
            for position in ("DEFENDER", "MIDFIELDER", "FORWARD")
        }
        missing_benchmarks = {
            position: {"actual": count, "required": 2}
            for position, count in benchmark_counts.items()
            if count < 2
        }
        if missing_benchmarks:
            print(
                "Reliable-profile premium audit is incomplete. Mark and fully "
                "annotate at least two established benchmark candidates per field "
                f"position before optimization: {missing_benchmarks}.",
                file=sys.stderr,
            )
            return 2
    anchor_candidates = sum(
        player.reliable_anchor
        for player in eligible_players
        if player.position != "GOALKEEPER"
    )
    if anchor_candidates < args.min_reliable_anchors:
        print(
            "Reliable-anchor research is incomplete: "
            f"required={args.min_reliable_anchors}, eligible={anchor_candidates}. "
            "Expand or correct the researched premium pool; the policy is not "
            "relaxed automatically.",
            file=sys.stderr,
        )
        return 2
    attacking_anchor_candidates = sum(
        player.reliable_anchor
        for player in eligible_players
        if player.position in {"MIDFIELDER", "FORWARD"}
    )
    if attacking_anchor_candidates < args.min_attacking_anchors:
        print(
            "Attacking-anchor research is incomplete: "
            f"required={args.min_attacking_anchors}, "
            f"eligible={attacking_anchor_candidates}. Research established "
            "multi-season scorers, creators and set-piece leaders instead of "
            "filling the pool with similarly priced depth.",
            file=sys.stderr,
        )
        return 2
    offensive_premium_candidates = sum(
        is_offensive_premium_anchor(player)
        for player in eligible_players
    )
    if (
        offensive_premium_candidates
        < args.min_offensive_premium_anchors
    ):
        print(
            "Offensive premium-anchor research is incomplete: "
            f"required={args.min_offensive_premium_anchors}, "
            f"eligible={offensive_premium_candidates}. Research more "
            "multi-season scorers, creators and set-piece leaders with "
            "currently secure roles instead of hard-coding famous names.",
            file=sys.stderr,
        )
        return 2
    eligible_utility_scores, core_multipliers = core_weighted_scores(
        eligible_players,
        eligible_raw_scores,
        args.profile,
        args.maintenance,
    )
    args.price_ceiling_core_budget_share_target = (
        market_core_budget_share_target(
            eligible_players,
            args.budget,
            args.target_core_budget_share,
        )
    )
    args.effective_core_budget_share_target = (
        args.price_ceiling_core_budget_share_target
    )
    avoid_exposure = load_avoid_exposure(args.avoid_roster)
    local_variation_exposure: Counter[str] = Counter()
    recent_variation_squads: list[frozenset[str]] = []
    if (
        variation_source == "automatic_local"
        and variation_generation is not None
        and variation_generation > 0
    ):
        try:
            local_variation_exposure = automatic_variation_exposure(
                state_path=variation_state_path,
                competition=args.competition,
                season=args.season,
                profile=args.profile,
                maintenance=args.maintenance,
                variation=args.variation,
                budget=args.budget,
                slots=args.slots,
                generation=variation_generation,
            )
            recent_variation_squads = automatic_variation_recent_squads(
                state_path=variation_state_path,
                competition=args.competition,
                season=args.season,
                profile=args.profile,
                maintenance=args.maintenance,
                variation=args.variation,
                budget=args.budget,
                slots=args.slots,
                generation=variation_generation,
            )
            avoid_exposure.update(local_variation_exposure)
        except VariationStateError as error:
            print(
                f"Automatic variation stopped: {error}",
                file=sys.stderr,
            )
            return 2
    minimum_spend = math.ceil(args.budget * args.min_spend_ratio)
    portfolio_audit: dict[str, Any] | None = None
    try:
        if args.portfolio_size > 1:
            (
                squad,
                optimum,
                distance,
                variation_target_met,
                portfolio_audit,
            ) = varied_portfolio(
                players=eligible_players,
                budget=args.budget,
                base_scores=eligible_utility_scores,
                profile=args.profile,
                variation=args.variation,
                seed=seed,
                club_cap=args.max_outfield_per_club,
                minimum_spend=minimum_spend,
                slots=args.slots,
                avoid_exposure=avoid_exposure,
                portfolio_size=args.portfolio_size,
                portfolio_index=portfolio_index,
                maintenance=args.maintenance,
                same_club_goalkeepers=not args.mixed_goalkeepers,
                min_reliable_anchors=args.min_reliable_anchors,
                min_attacking_anchors=args.min_attacking_anchors,
                min_core_budget_share=args.min_core_budget_share,
                target_core_budget_share=(
                    args.effective_core_budget_share_target
                ),
                min_offensive_premium_anchors=(
                    args.min_offensive_premium_anchors
                ),
                min_qualified_potential_core=(
                    args.min_qualified_potential_core
                ),
                target_qualified_potential_core=(
                    args.target_qualified_potential_core
                ),
                core_scores=eligible_raw_scores,
                technical_smoke=args.allow_unannotated,
                max_reliable_anchor_exposure=args.max_anchor_exposure,
                optimizer_cache=args.optimizer_cache,
            )
        else:
            prepared_context = prepare_variation_context(
                players=eligible_players,
                budget=args.budget,
                base_scores=eligible_utility_scores,
                profile=args.profile,
                variation=args.variation,
                club_cap=args.max_outfield_per_club,
                minimum_spend=minimum_spend,
                slots=args.slots,
                same_club_goalkeepers=not args.mixed_goalkeepers,
                min_reliable_anchors=args.min_reliable_anchors,
                technical_smoke=args.allow_unannotated,
                optimizer_cache=args.optimizer_cache,
            )
            initial_protected_premium_ids = (
                protected_reliable_premium_anchor_ids(
                    eligible_players,
                    eligible_raw_scores,
                    prepared_context["optimum"].ids,
                )
                if (
                    args.profile == "reliable"
                    and args.maintenance == "low"
                    and not args.allow_unannotated
                )
                else frozenset()
            )
            squad, optimum, distance, variation_target_met = varied_squad(
                players=eligible_players,
                budget=args.budget,
                base_scores=eligible_utility_scores,
                profile=args.profile,
                variation=args.variation,
                seed=seed,
                club_cap=args.max_outfield_per_club,
                minimum_spend=minimum_spend,
                slots=args.slots,
                avoid_ids=avoid_exposure,
                same_club_goalkeepers=not args.mixed_goalkeepers,
                min_reliable_anchors=args.min_reliable_anchors,
                technical_smoke=args.allow_unannotated,
                prepared_context=prepared_context,
                protected_ids=initial_protected_premium_ids,
                exposure_strength=max(
                    1.0,
                    float(
                        VARIATION_CONFIG[args.variation].get(
                            "history_strength",
                            0.0,
                        )
                    ),
                ),
                optimizer_cache=args.optimizer_cache,
            )
            if args.min_core_budget_share > 0:
                optimum = finalize_reliable_core_architecture(
                    optimum,
                    eligible_players,
                    eligible_utility_scores,
                    eligible_raw_scores,
                    budget=args.budget,
                    club_cap=args.max_outfield_per_club,
                    min_reliable_anchors=args.min_reliable_anchors,
                    min_attacking_anchors=args.min_attacking_anchors,
                    min_core_budget_share=args.min_core_budget_share,
                    target_core_budget_share=(
                        args.effective_core_budget_share_target
                    ),
                    minimum_spend=minimum_spend,
                    min_offensive_premium_anchors=(
                        args.min_offensive_premium_anchors
                    ),
                    min_qualified_potential_core=(
                        args.min_qualified_potential_core
                    ),
                    target_qualified_potential_core=(
                        args.target_qualified_potential_core
                    ),
                    maintenance=args.maintenance,
                    same_club_goalkeepers=not args.mixed_goalkeepers,
                    protected_player_ids=initial_protected_premium_ids,
                    search_premium_restarts=True,
                )
                # Keep the premium-protection contract stable across both
                # optimization phases. Recomputing it from the finalized
                # optimum could turn a newly selected player into a surprise
                # mandatory anchor after the variant had already been formed.
                protected_premium_ids = initial_protected_premium_ids
                variation_distance_target = int(
                    VARIATION_CONFIG[args.variation]["distance"]
                )
                variation_reference_optimum_ids = optimum.ids
                variation_reference_squads = [
                    variation_reference_optimum_ids,
                    *recent_variation_squads,
                ]
                variation_reference_squads = list(
                    dict.fromkeys(variation_reference_squads)
                )
                architecture_variation_rng = random.Random(
                    seed ^ 0x6B69636B6572
                )
                architecture_variation_preferences = {
                    player.player_id: architecture_variation_rng.uniform(
                        -1.75,
                        1.75,
                    )
                    for player in sorted(
                        eligible_players,
                        key=lambda item: (item.player_id, item.name),
                    )
                }
                squad = finalize_reliable_core_architecture(
                    # Branch only from the already legal reference
                    # architecture. A random raw squad can contain several
                    # simultaneous structural violations and force the local
                    # repair search back to the optimum. Seeded preferences
                    # and exposure history now choose among legal swap paths.
                    optimum,
                    eligible_players,
                    eligible_utility_scores,
                    eligible_raw_scores,
                    budget=args.budget,
                    club_cap=args.max_outfield_per_club,
                    min_reliable_anchors=args.min_reliable_anchors,
                    min_attacking_anchors=args.min_attacking_anchors,
                    min_core_budget_share=args.min_core_budget_share,
                    target_core_budget_share=(
                        args.effective_core_budget_share_target
                    ),
                    minimum_spend=minimum_spend,
                    min_offensive_premium_anchors=(
                        args.min_offensive_premium_anchors
                    ),
                    min_qualified_potential_core=(
                        args.min_qualified_potential_core
                    ),
                    target_qualified_potential_core=(
                        args.target_qualified_potential_core
                    ),
                    maintenance=args.maintenance,
                    same_club_goalkeepers=not args.mixed_goalkeepers,
                    protected_player_ids=protected_premium_ids,
                    variation_exposure=avoid_exposure,
                    variation_exposure_strength=float(
                        VARIATION_CONFIG[args.variation].get(
                            "history_strength",
                            0.0,
                        )
                    ),
                    variation_reference_squads=(
                        variation_reference_squads
                        if args.variation != "none"
                        else ()
                    ),
                    minimum_variation_distance=(
                        max(0, variation_distance_target - 1)
                        if args.variation != "none"
                        else 0
                    ),
                    maximum_variation_distance=(
                        variation_distance_target + 1
                        if args.variation != "none"
                        else None
                    ),
                    variation_preferences=(
                        architecture_variation_preferences
                        if args.variation != "none"
                        else None
                    ),
                )
                squad_final_objective, squad_final_valid = (
                    finalized_squad_objective(
                        squad,
                        eligible_players,
                        eligible_utility_scores,
                        eligible_raw_scores,
                        args,
                    )
                )
                optimum_final_objective, optimum_final_valid = (
                    finalized_squad_objective(
                        optimum,
                        eligible_players,
                        eligible_utility_scores,
                        eligible_raw_scores,
                        args,
                    )
                )
                if (
                    squad_final_valid
                    and (
                        not optimum_final_valid
                        or squad_final_objective
                        > optimum_final_objective + 1e-9
                    )
                ):
                    optimum = squad
                    optimum_final_objective = squad_final_objective
                    optimum_final_valid = True
                    protected_premium_ids = initial_protected_premium_ids
                profile_factor = (
                    1.20 if args.profile == "breakout" else 1.0
                )
                final_quality_floor = optimum_final_objective * (
                    1.0
                    - VARIATION_CONFIG[args.variation]["gap"]
                    * profile_factor
                )
                if (
                    not squad_final_valid
                    or not optimum_final_valid
                    or not protected_premium_ids.issubset(squad.ids)
                    or squad_final_objective + 1e-9
                    < final_quality_floor
                    or (
                        len(
                            variation_reference_optimum_ids.symmetric_difference(
                                squad.ids
                            )
                        )
                        // 2
                        > int(
                            VARIATION_CONFIG[
                                args.variation
                            ]["distance"]
                        )
                        + 1
                    )
                ):
                    rejection_reasons = []
                    if not squad_final_valid:
                        rejection_reasons.append("architecture")
                    if not optimum_final_valid:
                        rejection_reasons.append("reference-architecture")
                    if not protected_premium_ids.issubset(squad.ids):
                        rejection_reasons.append("premium-protection")
                    if squad_final_objective + 1e-9 < final_quality_floor:
                        rejection_reasons.append("quality-corridor")
                    if (
                        len(
                            variation_reference_optimum_ids.symmetric_difference(
                                squad.ids
                            )
                        )
                        // 2
                        > int(VARIATION_CONFIG[args.variation]["distance"]) + 1
                    ):
                        rejection_reasons.append("maximum-distance")
                    print(
                        "Variant finalization fell back to the reference "
                        f"roster: {', '.join(rejection_reasons)}.",
                        file=sys.stderr,
                    )
                    squad = optimum
                distance = len(
                    variation_reference_optimum_ids.symmetric_difference(
                        squad.ids
                    )
                ) // 2
                variation_target_met = variation_distance_met(
                    args.variation,
                    distance,
                )
    except ValueError as error:
        print(f"Optimization stopped: {error}", file=sys.stderr)
        return 2
    if squad.architecture_diagnostics:
        args.effective_core_budget_share_target = float(
            squad.architecture_diagnostics.get(
                "optimizer_reachable_core_budget_share_target",
                args.effective_core_budget_share_target,
            )
        )
    if squad.cost < minimum_spend:
        print(
            "Optimization stopped: the post-processing step left budget "
            f"unused (spent={squad.cost}, required={minimum_spend}). "
            "Budget use has priority over low-maintenance bench shaping.",
            file=sys.stderr,
        )
        return 2
    if (
        not args.allow_unannotated
        and not args.shortlist_only
        and squad.cost != args.budget
    ):
        print(
            "Optimization stopped: final recommendations must spend the full "
            f"budget (spent={squad.cost}, budget={args.budget}).",
            file=sys.stderr,
        )
        return 2
    if (
        not args.allow_unannotated
        and args.min_core_budget_share > 0
    ):
        _, final_architecture_valid = finalized_squad_objective(
            squad,
            eligible_players,
            eligible_utility_scores,
            eligible_raw_scores,
            args,
        )
        if not final_architecture_valid:
            defender_audit = squad.architecture_diagnostics.get(
                "defender_architecture",
                {},
            )
            midfield_audit = squad.architecture_diagnostics.get(
                "midfield_architecture",
                {},
            )
            forward_audit = squad.architecture_diagnostics.get(
                "forward_reserve_architecture",
                {},
            )
            print(
                "Optimization stopped: the final squad violates a hard "
                "architecture gate. The optimizer must repair the starting "
                "core, qualified-potential floor and positional reserve "
                "playability "
                "before a recommendation can be published. "
                f"Defender audit={defender_audit}; "
                f"midfield audit={midfield_audit}; "
                f"forward audit={forward_audit}.",
                file=sys.stderr,
            )
            return 2
    selected_ids = squad.ids
    selected_news_blockers = sorted(
        selected_ids
        & set(news_audit.get("selection_blocked_player_ids", []))
    )
    news_audit["final_selection_gate"] = {
        "status": "passed" if not selected_news_blockers else "blocked",
        "checked_players": len(selected_ids),
        "blocked_player_ids": selected_news_blockers,
        "automatic_reoptimization": bool(
            news_audit.get("automatic_reoptimization", False)
        ),
    }
    if selected_news_blockers:
        print(
            "News hardening stopped optimization: the final 22-player gate "
            f"still contains blocked transfer cases: {selected_news_blockers}.",
            file=sys.stderr,
        )
        return 2
    news_conflicts = {
        player_id: reasons
        for player_id, reasons in news_audit.get("conflicts", {}).items()
        if player_id in selected_ids
    }
    if news_conflicts and not args.allow_news_conflicts:
        print(
            "News hardening stopped optimization: selected players have unresolved "
            f"provider or identity conflicts: {news_conflicts}. Verify them in "
            "current primary sources before changing Chrome.",
            file=sys.stderr,
        )
        return 2
    if args.require_news_coverage:
        coverage_cleared = set(
            news_audit.get(
                "coverage_cleared_player_ids",
                news_audit.get("provider_mapped_player_ids", []),
            )
        )
        missing_news_coverage = sorted(selected_ids - coverage_cleared)
        if missing_news_coverage:
            print(
                "News hardening stopped optimization: selected players lack a "
                "verified provider mapping or a fresh complete manual clearance: "
                f"{missing_news_coverage}. Research them manually or extend "
                "the central mapping before changing Chrome.",
                file=sys.stderr,
            )
            return 2
    if args.min_core_budget_share > 0:
        core_audit = reliable_core_audit(
            squad,
            eligible_raw_scores,
            args.min_reliable_anchors,
            args.min_attacking_anchors,
            args.min_core_budget_share,
            args.min_offensive_premium_anchors,
        )
        if args.profile == "reliable" and args.min_reliable_anchors > 0:
            core_anchor_count = core_audit["reliable_anchors"]
            if core_anchor_count < args.min_reliable_anchors:
                print(
                    "Optimization stopped: the squad-level anchor floor cannot be "
                    "placed inside one legal starting formation. Recalibrate the "
                    "anchor pool instead of treating bench anchors as the reliable core.",
                    file=sys.stderr,
                )
                return 2
            core_attacking_anchors = core_audit["attacking_anchors"]
            if core_attacking_anchors < args.min_attacking_anchors:
                print(
                    "Optimization stopped: the legal starting core contains only "
                    f"{core_attacking_anchors} reliable midfield/forward anchors; "
                    f"{args.min_attacking_anchors} are required. Strengthen the "
                    "multi-season scorer and creator pool before changing Chrome.",
                    file=sys.stderr,
                )
                return 2
            core_offensive_premium_anchors = core_audit[
                "offensive_premium_anchors"
            ]
            if (
                core_offensive_premium_anchors
                < args.min_offensive_premium_anchors
            ):
                print(
                    "Optimization stopped: the legal starting core contains "
                    f"only {core_offensive_premium_anchors} evidence-derived "
                    "offensive premium anchors; "
                    f"{args.min_offensive_premium_anchors} are required. "
                    "Fund a multi-season scorer, creator or set-piece leader "
                    "instead of carrying equivalent reserve depth.",
                    file=sys.stderr,
                )
                return 2
        core_budget_share = core_audit["core_budget_share"]
        if core_budget_share < args.min_core_budget_share:
            print(
                "Optimization stopped: too much squad value remains on the "
                f"bench. Starting-core share={core_budget_share:.1%}, "
                f"required={args.min_core_budget_share:.1%}. Replace expensive "
                "reserve depth with cheap playable cover and fund proven "
                "starters instead.",
                file=sys.stderr,
            )
            return 2
    recent_variant_distances = [
        len(squad.ids.symmetric_difference(previous_ids)) // 2
        for previous_ids in recent_variation_squads
    ]
    minimum_recent_variant_distance = (
        min(recent_variant_distances)
        if recent_variant_distances
        else None
    )
    recent_variant_distance_target = int(
        VARIATION_CONFIG[args.variation].get("history_distance", 0)
    )
    recent_variant_distance_target_met = (
        minimum_recent_variant_distance is None
        or minimum_recent_variant_distance
        >= recent_variant_distance_target
    )
    variation_target_met = (
        variation_target_met
        and recent_variant_distance_target_met
    )
    payload = output_payload(
        squad=squad,
        optimum=optimum,
        players=eligible_players,
        raw_scores=eligible_raw_scores,
        utility_scores=eligible_utility_scores,
        core_multipliers=core_multipliers,
        args=args,
        seed=seed,
        distance=distance,
        variation_target_met=variation_target_met,
        annotated_count=annotated_count,
        annotated_by_position=annotated_by_position,
        annotation_requirements=required_annotations,
        annotated_goalkeeper_blocks=annotated_goalkeeper_blocks,
        hard_exclusions=hard_exclusions,
        news_audit=news_audit,
        portfolio_audit=portfolio_audit,
        market_audit=market_audit,
    )
    payload["quality_audit"] = quality_audit
    payload["variation_identity"] = {
        "mode": variation_source,
        "generation": variation_generation,
        "new_variant_supported": True,
        "private_installation_id_exposed": False,
        "prior_local_variant_exposure_count": sum(
            local_variation_exposure.values()
        ),
        "recent_completed_variant_count": len(
            recent_variation_squads
        ),
        "minimum_distance_to_recent_variants": (
            minimum_recent_variant_distance
        ),
        "recent_variant_distance_target": (
            recent_variant_distance_target
        ),
        "recent_variant_distance_target_met": (
            recent_variant_distance_target_met
        ),
    }
    if (
        variation_source == "automatic_local"
        and variation_generation is not None
    ):
        try:
            record_automatic_variation_squad(
                state_path=variation_state_path,
                competition=args.competition,
                season=args.season,
                profile=args.profile,
                maintenance=args.maintenance,
                variation=args.variation,
                budget=args.budget,
                slots=args.slots,
                generation=variation_generation,
                player_ids=squad.ids,
            )
        except VariationStateError as error:
            print(
                f"Automatic variation stopped: {error}",
                file=sys.stderr,
            )
            return 2
    rendered = (
        json.dumps(payload, ensure_ascii=False, indent=2)
        if args.format == "json"
        else None
    )
    if args.output:
        args.output.write_text(
            rendered
            if rendered is not None
            else json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if rendered is not None:
        print(rendered)
    else:
        print_text(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
