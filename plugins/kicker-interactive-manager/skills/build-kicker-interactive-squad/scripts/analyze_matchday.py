#!/usr/bin/env python3
"""Apply short-lived opponent context to a proposed starting lineup."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from competition_strategy import architecture_policy, home_advantage_bonus
from matchday_snapshot import load_snapshot


def adjustment(
    position: str,
    context: dict[str, Any],
    competition: str | None = None,
) -> float:
    if position in {"GOALKEEPER", "DEFENDER"}:
        raw = 0.12 * (50.0 - float(context["opponent_attack"]))
    else:
        raw = 0.12 * (50.0 - float(context["opponent_defense"]))
    if context.get("venue") == "home":
        raw += home_advantage_bonus(competition, position)
    return round(max(-6.0, min(6.0, raw)), 2)


def analyze(
    roster: list[dict[str, Any]],
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    players = []
    for player in roster:
        club = str(player.get("club", "")).strip()
        position = str(player.get("position", "")).strip().upper()
        context = snapshot.get("teams", {}).get(club)
        players.append(
            {
                **player,
                "matchday_adjustment": (
                    adjustment(position, context, snapshot["competition"])
                    if isinstance(context, dict)
                    else 0.0
                ),
                "opponent_context": context,
            }
        )
    return {
        "competition": snapshot["competition"],
        "season": snapshot["season"],
        "snapshot_status": snapshot["status"],
        "home_advantage_mode": architecture_policy(
            snapshot["competition"]
        )["home_advantage_mode"],
        "players": players,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roster", type=Path, required=True)
    parser.add_argument("--matchday", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    raw = json.loads(args.roster.read_text(encoding="utf-8"))
    roster = raw.get("players", raw) if isinstance(raw, dict) else raw
    if not isinstance(roster, list):
        parser.error("roster must be a list or an object with players")
    result = analyze(roster, load_snapshot(args.matchday))
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
