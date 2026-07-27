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
from pathlib import Path
from typing import Any, Iterable

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
VARIATION_STATE_SCHEMA_VERSION = 1
OPTIMIZER_CACHE_ENV = "KICKER_OPTIMIZER_CACHE"
OPTIMIZER_CACHE_SCHEMA_VERSION = 1
OPTIMIZER_ALGORITHM_VERSION = "exact-dp-v3"
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
    if (
        payload.get("schema_version") != VARIATION_STATE_SCHEMA_VERSION
        or not isinstance(installation_id, str)
        or re.fullmatch(r"[0-9a-f]{48}", installation_id) is None
        or not isinstance(contexts, dict)
        or any(
            not isinstance(key, str)
            or not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
            for key, value in contexts.items()
        )
    ):
        raise VariationStateError(
            f"local variation state has an unsupported format at {path}"
        )
    return payload


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
    generation = int(state["contexts"].get(context_key, 0))
    if new_variant:
        generation += 1
    state["contexts"][context_key] = generation
    _save_variation_state(state_path, state)
    digest = hashlib.sha256(
        (
            f"{state['installation_id']}\0{context}\0{generation}"
        ).encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], "big") % (2**31), generation

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
    "none": {"noise": 0.0, "gap": 0.0, "distance": 0, "avoid": 0.0},
    "low": {"noise": 1.5, "gap": 0.02, "distance": 2, "avoid": 0.8},
    "medium": {"noise": 3.5, "gap": 0.05, "distance": 4, "avoid": 1.8},
    "high": {"noise": 6.0, "gap": 0.08, "distance": 6, "avoid": 3.0},
}
DEFAULT_CLUB_CAP = {"reliable": 4, "balanced": 4, "breakout": 3}
OFFENSIVE_PREMIUM_ANCHOR_MINIMUM = 14.0


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


def resolve_snapshot_entry(
    player: Player,
    entries: dict[str, Any],
) -> tuple[str | None, dict[str, Any] | None, list[str]]:
    direct = entries.get(player.player_id)
    if isinstance(direct, dict):
        return player.player_id, direct, []

    candidates: list[tuple[int, str, dict[str, Any]]] = []
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
        candidates.append((name_score, str(snapshot_key), raw_entry))
    if not candidates:
        return None, None, []
    best_score = max(item[0] for item in candidates)
    best = [item for item in candidates if item[0] == best_score]
    if len(best) != 1:
        return None, None, [
            "multiple central news identities match this Kicker player"
        ]
    _, snapshot_key, entry = best[0]
    return snapshot_key, entry, []


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
    conflicts: dict[str, list[str]] = {}
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
        confidence = str(consensus.get("confidence", "low"))
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
    audit.update(
        {
            "applied_player_ids": sorted(applied_ids),
            "provider_mapped_player_ids": sorted(provider_mapped_ids),
            "unmapped_csv_player_ids": sorted(csv_ids - set(provider_mapped_ids)),
            "snapshot_only_player_ids": sorted(
                set(entries) - matched_snapshot_keys
            ),
            "identity_bindings": identity_bindings,
            "conflicts": conflicts,
            "hard_exclusions": len(excluded),
        }
    )
    return updated, audit, excluded


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
    """Rate repeatable attacking excellence without using names or benchmark flags."""

    if (
        player.position not in {"MIDFIELDER", "FORWARD"}
        or not player.reliable_anchor
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


def effective_weights(profile: str, maintenance: str) -> dict[str, float]:
    weights = {key: float(value) for key, value in PROFILE_WEIGHTS[profile].items()}
    if maintenance == "low":
        weights["minutes"] += 5
        weights["role"] += 2
        weights["stability"] += 4
        weights["upside"] -= 7
        weights["value"] -= 4
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
        scores[player.player_id] = component_score - risk_penalty
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
        tuple[int, int, int, int, int],
        tuple[float, frozenset[str]],
    ] = {(0, 0, 0, 0, 0): (0.0, frozenset())}
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
            new_key = (
                counts[0],
                counts[1],
                counts[2],
                anchors,
                premium_anchors,
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


def reliable_core_audit(
    squad: Squad,
    scores: dict[str, float],
    min_reliable_anchors: int,
    min_attacking_anchors: int,
    min_core_budget_share: float,
    min_offensive_premium_anchors: int = 0,
) -> dict[str, Any]:
    """Measure whether a conservative squad actually funds its scoring core."""

    formation, core_ids = best_starting_lineup(
        squad.players,
        scores,
        min_reliable_anchors,
        2 if min_core_budget_share > 0 else 1,
        4 if min_core_budget_share > 0 else 5,
        min_offensive_premium_anchors,
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
    core_budget = sum(player.cost for player in core_players)
    core_budget_share = core_budget / max(squad.cost, 1)
    return {
        "formation": formation,
        "player_ids": core_ids,
        "reliable_anchors": reliable_anchors,
        "attacking_anchors": attacking_anchors,
        "offensive_premium_anchors": offensive_premium_anchors,
        "core_budget": core_budget,
        "core_budget_share": core_budget_share,
        "passes": (
            reliable_anchors >= min_reliable_anchors
            and attacking_anchors >= min_attacking_anchors
            and offensive_premium_anchors
            >= min_offensive_premium_anchors
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
FORWARD_CORE_BUDGET_TARGETS = {
    "low": 0.75,
    "normal": 0.65,
    "active": 0.55,
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
) -> dict[str, Any]:
    """Value starters at full use and reserves at expected positional use."""

    audit = reliable_core_audit(
        squad,
        dict(raw_scores),
        min_reliable_anchors,
        min_attacking_anchors,
        min_core_budget_share,
        min_offensive_premium_anchors,
    )
    core_ids = set(audit["player_ids"])
    player_usage_weights = bench_player_usage_weights(
        squad,
        core_ids,
        raw_scores,
        maintenance,
    )
    player_contributions: dict[str, float] = {}
    for player in squad.players:
        player_contributions[player.player_id] = (
            raw_scores[player.player_id]
            * player_usage_weights[player.player_id]
        )
    expected_contribution = sum(player_contributions.values())
    target_gap = max(
        0.0,
        target_core_budget_share - audit["core_budget_share"],
    )
    # A ten-point core-share gap is worth twelve model points. This makes
    # concentration material, but never strong enough to replace several
    # genuinely better starters merely because they are cheaper.
    concentration_adjustment = -120.0 * target_gap
    forward_players = [
        player
        for player in squad.players
        if player.position == "FORWARD"
    ]
    forward_spend = sum(player.cost for player in forward_players)
    forward_core_spend = sum(
        player.cost
        for player in forward_players
        if player.player_id in core_ids
    )
    forward_core_budget_share = (
        forward_core_spend / forward_spend
        if forward_spend
        else 0.0
    )
    forward_core_budget_target = FORWARD_CORE_BUDGET_TARGETS.get(
        maintenance,
        FORWARD_CORE_BUDGET_TARGETS["normal"],
    )
    # A ten-point shortfall costs 32 model points: enough to prefer a real
    # starter upgrade over a second similarly priced reserve, while the first
    # usable backup still retains its role-weighted contribution.
    forward_concentration_adjustment = -320.0 * max(
        0.0,
        forward_core_budget_target - forward_core_budget_share,
    )
    return {
        **audit,
        "expected_contribution": expected_contribution,
        "concentration_adjustment": concentration_adjustment,
        "forward_concentration_adjustment": (
            forward_concentration_adjustment
        ),
        "forward_core_spend": forward_core_spend,
        "forward_reserve_spend": forward_spend - forward_core_spend,
        "forward_core_budget_share": forward_core_budget_share,
        "forward_core_budget_target": forward_core_budget_target,
        "forward_core_budget_target_met": (
            forward_core_budget_share + 1e-9
            >= forward_core_budget_target
        ),
        "architecture_objective": (
            expected_contribution
            + concentration_adjustment
            + forward_concentration_adjustment
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


def _architecture_candidate_is_legal(
    players: list[Player],
    *,
    budget: int,
    club_cap: int,
    min_reliable_anchors: int,
) -> bool:
    if len(players) != len({player.player_id for player in players}):
        return False
    if sum(player.cost for player in players) != budget:
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


def forward_roster_packages(
    candidates: list[Player],
    raw_scores: Mapping[str, float],
    *,
    count: int,
    total_cost: int,
    maintenance: str,
    limit: int = 300,
) -> list[tuple[Player, ...]]:
    """Find strong full-forward packages without brute-forcing the market."""

    if count <= 0 or total_cost <= 0 or limit <= 0:
        return []
    by_cost: dict[int, list[Player]] = {}
    for player in candidates:
        if player.position == "FORWARD":
            by_cost.setdefault(player.cost, []).append(player)
    for cost, players_at_cost in by_cost.items():
        by_cost[cost] = sorted(
            players_at_cost,
            key=lambda player: (
                -raw_scores[player.player_id],
                player.player_id,
            ),
        )[:8]
    costs = sorted(by_cost)
    if not costs:
        return []

    target = FORWARD_CORE_BUDGET_TARGETS.get(
        maintenance,
        FORWARD_CORE_BUDGET_TARGETS["normal"],
    )
    reserve_weights = BENCH_SLOT_USAGE_WEIGHTS.get(
        maintenance,
        BENCH_SLOT_USAGE_WEIGHTS["normal"],
    )["FORWARD"]
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
        for option_parts in itertools.product(*tier_options):
            package = tuple(
                player
                for option in option_parts
                for player in option
            )
            ordered = sorted(
                package,
                key=lambda player: (
                    -raw_scores[player.player_id],
                    player.player_id,
                ),
            )
            starter_count = min(3, len(ordered))
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
            proxy = expected_contribution - 320.0 * max(
                0.0,
                target - core_share,
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
    quality_loss_limit: float = 0.05,
    max_iterations: int = 5,
    same_club_goalkeepers: bool = True,
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

    current_metrics = squad_architecture_metrics(
        current,
        raw_scores,
        maintenance=maintenance,
        min_reliable_anchors=min_reliable_anchors,
        min_attacking_anchors=min_attacking_anchors,
        min_core_budget_share=min_core_budget_share,
        target_core_budget_share=target_core_budget_share,
        min_offensive_premium_anchors=min_offensive_premium_anchors,
    )
    maximum_reachable_core_share = current_metrics["core_budget_share"]
    evaluated_rosters = 1
    completed_iterations = 0
    forward_packages_by_cost: dict[
        tuple[int, int], list[tuple[Player, ...]]
    ] = {}
    for iteration in range(max_iterations):
        selected_ids = current.ids
        alternatives: list[
            tuple[float, float, float, Squad, dict[str, Any]]
        ] = []
        seen_rosters: set[frozenset[str]] = set()

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
            ):
                return
            replacement_quality = sum(
                quality_scores[player.player_id]
                for player in replacement_players
            )
            if replacement_quality < quality_floor:
                return
            replacement = Squad(
                replacement_players,
                replacement_quality,
            )
            metrics = squad_architecture_metrics(
                replacement,
                raw_scores,
                maintenance=maintenance,
                min_reliable_anchors=min_reliable_anchors,
                min_attacking_anchors=min_attacking_anchors,
                min_core_budget_share=min_core_budget_share,
                target_core_budget_share=target_core_budget_share,
                min_offensive_premium_anchors=(
                    min_offensive_premium_anchors
                ),
            )
            evaluated_rosters += 1
            if not metrics["passes"]:
                return
            maximum_reachable_core_share = max(
                maximum_reachable_core_share,
                metrics["core_budget_share"],
            )
            alternatives.append(
                (
                    metrics["architecture_objective"],
                    metrics["expected_contribution"],
                    metrics["core_budget_share"],
                    replacement,
                    metrics,
                )
            )

        field_players = [
            player
            for player in current.players
            if player.position != "GOALKEEPER"
        ]
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
            for first_replacement, second_replacement in pair_packages.get(
                package_key,
                [],
            )[:16]:
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
                consider(
                    [
                        replacement_map.get(player.player_id, player)
                        for player in current.players
                    ]
                )

        current_forwards = [
            player
            for player in current.players
            if player.position == "FORWARD"
        ]
        forward_package_key = (
            len(current_forwards),
            sum(player.cost for player in current_forwards),
        )
        if forward_package_key not in forward_packages_by_cost:
            forward_packages_by_cost[forward_package_key] = (
                forward_roster_packages(
                    candidate_by_position["FORWARD"],
                    raw_scores,
                    count=forward_package_key[0],
                    total_cost=forward_package_key[1],
                    maintenance=maintenance,
                )
            )
        current_forward_ids = {
            player.player_id for player in current_forwards
        }
        non_forwards = [
            player
            for player in current.players
            if player.position != "FORWARD"
        ]
        for package in forward_packages_by_cost[forward_package_key]:
            if {
                player.player_id for player in package
            } == current_forward_ids:
                continue
            consider([*non_forwards, *package])

        if not alternatives:
            break
        best = max(
            alternatives,
            key=lambda item: (item[0], item[1], item[2]),
        )
        if best[0] <= current_metrics["architecture_objective"] + 1e-9:
            break
        current = best[3]
        current_metrics = best[4]
        completed_iterations = iteration + 1

    optimizer_reachable_target = min(
        target_core_budget_share,
        maximum_reachable_core_share,
    )
    current.architecture_diagnostics = {
        "model_version": "joint-xi-bench-v2",
        "expected_contribution": round(
            current_metrics["expected_contribution"],
            6,
        ),
        "architecture_objective": round(
            current_metrics["architecture_objective"],
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
        "player_contributions": current_metrics[
            "player_contributions"
        ],
        "player_usage_weights": current_metrics["player_usage_weights"],
        "evaluated_rosters": evaluated_rosters,
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
    maintenance: str = "low",
    same_club_goalkeepers: bool = True,
) -> Squad:
    """Apply the same core-first architecture to a squad and its reference."""

    current = squad
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
            candidates,
            quality_scores,
            core_scores,
            club_cap=club_cap,
            min_reliable_anchors=min_reliable_anchors,
            min_attacking_anchors=min_attacking_anchors,
            min_core_budget_share=min_core_budget_share,
            quality_floor=float("-inf"),
            minimum_spend=minimum_spend,
            min_offensive_premium_anchors=0,
        )
        if repaired is not None:
            current = repaired
    current = upgrade_core_with_remaining_budget(
        current,
        candidates,
        quality_scores,
        core_scores,
        budget=budget,
        club_cap=club_cap,
        min_reliable_anchors=min_reliable_anchors,
        min_attacking_anchors=min_attacking_anchors,
        min_core_budget_share=min_core_budget_share,
        min_offensive_premium_anchors=min_offensive_premium_anchors,
    )
    return optimize_joint_squad_architecture(
        current,
        candidates,
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
        same_club_goalkeepers=same_club_goalkeepers,
    )


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

    optimum = optimize(
        players,
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

    profile_factor = (
        0.75
        if profile == "reliable"
        else (1.20 if profile == "breakout" else 1.0)
    )
    allowed_gap = config["gap"] * profile_factor
    target_distance = int(config["distance"])
    variation_players = (
        technical_variation_pool(players, base_scores, optimum, slots)
        if technical_smoke
        else players
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
    seeded_buckets = optimize_distance_buckets(
        variation_players,
        budget,
        seeded_scores,
        club_cap,
        minimum_spend,
        slots,
        optimum.ids,
        distance_cap,
        same_club_goalkeepers,
        min_reliable_anchors,
    )
    seeded_candidate = seeded_buckets[chosen_bucket]
    seeded_baseline_score = sum(
        base_scores[player.player_id] for player in seeded_candidate.players
    )
    if seeded_baseline_score < quality_floor:
        chosen = Squad(base_candidate.players, base_candidate_score)
    else:
        chosen = Squad(seeded_candidate.players, seeded_baseline_score)

    distance = len(optimum.ids.symmetric_difference(chosen.ids)) // 2
    if variation_target_met and distance != target_distance:
        raise RuntimeError("distance-aware optimizer violated the exact target distance")
    if not variation_target_met and distance != chosen_bucket:
        raise RuntimeError("distance-aware optimizer returned the wrong distance bucket")
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
    squad_score = sum(utility_scores[player.player_id] for player in squad.players)
    optimum_score = sum(utility_scores[player.player_id] for player in optimum.players)
    raw_squad_score = sum(
        round(raw_scores[player.player_id], 3) for player in squad.players
    )
    raw_optimum_score = sum(raw_scores[player.player_id] for player in optimum.players)
    visible_squad_utility = sum(
        round(utility_scores[player.player_id], 3) for player in squad.players
    )
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
            counterfactual_scope = "best_feasible_pool_squad_with_candidate"
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
            counterfactual_scope = "best_feasible_direct_replacement"
        forced_utility = sum(
            utility_scores[forced_player.player_id]
            for forced_player in forced.players
        )
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
        if not architecture_audit.get(
            "forward_core_budget_target_met",
            True,
        ):
            warnings.append(
                "The forward budget is still spread too evenly across all "
                "five slots; prefer one or two stronger starting attackers "
                "and cheaper fourth/fifth forwards."
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
        "quality_gap_metric": "model_utility",
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
    if args.min_reliable_anchors < 0:
        parser.error("--min-reliable-anchors cannot be negative")
    if args.min_attacking_anchors < 0:
        parser.error("--min-attacking-anchors cannot be negative")
    if args.min_offensive_premium_anchors < 0:
        parser.error("--min-offensive-premium-anchors cannot be negative")
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


def main() -> int:
    args = parse_args()
    variation_source = "explicit"
    variation_generation: int | None = None
    if args.seed is not None:
        seed = args.seed
    else:
        variation_source = "automatic_local"
        try:
            seed, variation_generation = automatic_variation_seed(
                state_path=args.variation_state or default_variation_state_path(),
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
        provider_mapped_ids = set(
            news_audit.get("provider_mapped_player_ids", [])
        )
        players = [
            player
            for player in players
            if player.player_id in provider_mapped_ids
        ]
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
                core_scores=eligible_raw_scores,
                technical_smoke=args.allow_unannotated,
                max_reliable_anchor_exposure=args.max_anchor_exposure,
                optimizer_cache=args.optimizer_cache,
            )
        else:
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
                    maintenance=args.maintenance,
                    same_club_goalkeepers=not args.mixed_goalkeepers,
                )
                squad = finalize_reliable_core_architecture(
                    squad,
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
                    maintenance=args.maintenance,
                    same_club_goalkeepers=not args.mixed_goalkeepers,
                )
                distance = len(
                    optimum.ids.symmetric_difference(squad.ids)
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
    selected_ids = squad.ids
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
        provider_mapped = set(
            news_audit.get("provider_mapped_player_ids", [])
        )
        missing_news_coverage = sorted(selected_ids - provider_mapped)
        if missing_news_coverage:
            print(
                "News hardening stopped optimization: selected players lack a "
                f"verified provider mapping: {missing_news_coverage}. Research "
                "them manually or extend the central mapping before changing Chrome.",
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
    }
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
