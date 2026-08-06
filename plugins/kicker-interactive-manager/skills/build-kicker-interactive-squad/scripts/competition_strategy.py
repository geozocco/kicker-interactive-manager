#!/usr/bin/env python3
"""Competition-specific squad architecture and matchday calibration."""

from __future__ import annotations

from typing import Any


DEFAULT_ARCHITECTURE_POLICY: dict[str, Any] = {
    "model_version": "joint-xi-bench-v16-scorer-defense-gates",
    "formation_gap": 0.05,
    "minimum_near_equivalent_formations": 1,
    "bench_budget_ranges": {},
    "bench_budget_soft_cap": None,
    "home_advantage": {
        "GOALKEEPER": 1.0,
        "DEFENDER": 1.0,
        "MIDFIELDER": 1.0,
        "FORWARD": 1.0,
    },
    "home_advantage_mode": "matchday_only",
}

BUNDESLIGA_ARCHITECTURE_POLICY: dict[str, Any] = {
    "model_version": "bundesliga-architecture-v1",
    "formation_gap": 0.015,
    "minimum_near_equivalent_formations": 2,
    "bench_budget_ranges": {
        "low": (6_500_000, 8_000_000),
        "normal": (7_500_000, 9_000_000),
        "active": (8_000_000, 10_000_000),
    },
    "bench_budget_soft_cap": 10_000_000,
    "home_advantage": {
        "GOALKEEPER": 0.0,
        "DEFENDER": 1.3,
        "MIDFIELDER": 1.3,
        "FORWARD": 1.6,
    },
    "home_advantage_mode": "matchday_tiebreak_only",
}


def architecture_policy(competition: str | None) -> dict[str, Any]:
    """Return an isolated policy so callers cannot mutate shared constants."""

    selected = (
        BUNDESLIGA_ARCHITECTURE_POLICY
        if competition == "Bundesliga"
        else DEFAULT_ARCHITECTURE_POLICY
    )
    return {
        **selected,
        "bench_budget_ranges": dict(selected["bench_budget_ranges"]),
        "home_advantage": dict(selected["home_advantage"]),
    }


def home_advantage_bonus(
    competition: str | None,
    position: str,
) -> float:
    """Return the short-lived home bonus; never use it for squad selection."""

    return float(
        architecture_policy(competition)["home_advantage"].get(
            position,
            0.0,
        )
    )
