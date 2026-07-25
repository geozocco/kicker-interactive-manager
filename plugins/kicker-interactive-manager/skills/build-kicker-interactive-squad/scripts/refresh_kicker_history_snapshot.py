#!/usr/bin/env python3
"""Append the current official Kicker market to its longitudinal snapshot."""

from __future__ import annotations

import argparse
import json
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kicker_history_snapshot import (
    SCHEMA_VERSION,
    KickerHistorySnapshotError,
    canonical_sha256,
    load_snapshot as load_history_snapshot,
    validate_snapshot,
)
from market_snapshot import (
    canonical_sha256 as market_sha256,
    load_snapshot as load_market_snapshot,
)


def load_previous(
    location: str | None,
    *,
    competition: str,
    season: str,
) -> dict[str, Any] | None:
    if not location:
        return None
    try:
        payload = load_history_snapshot(location)
    except (
        FileNotFoundError,
        urllib.error.HTTPError,
        KickerHistorySnapshotError,
    ) as error:
        if isinstance(error, urllib.error.HTTPError) and error.code != 404:
            raise
        if isinstance(error, KickerHistorySnapshotError) and "404" not in str(error):
            raise
        return None
    if (
        payload["competition"] != competition
        or payload["season"] != season
    ):
        return None
    return payload


def build_snapshot(
    market_payload: dict[str, Any],
    previous: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
    maximum_observations: int = 400,
) -> dict[str, Any]:
    generated = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    observed_on = generated.date().isoformat()
    previous_players = (previous or {}).get("players", {})
    players: dict[str, Any] = {}
    for market_player in market_payload["players"]:
        player_id = str(market_player["id"])
        observations = list(
            previous_players.get(player_id, {}).get("observations", [])
        )
        observation = {
            "observed_on": observed_on,
            "market_value": int(market_player["market_value"]),
            "points": float(market_player.get("points", 0)),
            "average_grade": float(
                market_player.get("average_grade", 0)
            ),
            "available": bool(market_player.get("available", True)),
        }
        by_date = {
            str(item["observed_on"]): item
            for item in observations
            if isinstance(item, dict) and item.get("observed_on")
        }
        by_date[observed_on] = observation
        players[player_id] = {
            "name": str(market_player["name"]),
            "club": str(market_player["club"]),
            "position": str(market_player["position"]),
            "observations": [
                by_date[key]
                for key in sorted(by_date)[-maximum_observations:]
            ],
        }
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated.isoformat().replace("+00:00", "Z"),
        "competition": market_payload["competition"],
        "season": market_payload["season"],
        "market_sha256": market_sha256(market_payload),
        "source": {
            "provider": "kicker",
            "url": market_payload["source"]["url"],
        },
        "players": players,
    }
    payload["content_sha256"] = canonical_sha256(payload)
    return validate_snapshot(payload)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", required=True)
    parser.add_argument("--previous")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--maximum-observations", type=int, default=400)
    args = parser.parse_args()
    if not 2 <= args.maximum_observations <= 1_000:
        parser.error("--maximum-observations must be between 2 and 1000")
    return args


def main() -> int:
    args = parse_args()
    market_payload = load_market_snapshot(args.market)
    previous = load_previous(
        args.previous,
        competition=str(market_payload["competition"]),
        season=str(market_payload["season"]),
    )
    payload = build_snapshot(
        market_payload,
        previous,
        maximum_observations=args.maximum_observations,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(f"{args.output.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(args.output)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "competition": payload["competition"],
                "players": len(payload["players"]),
                "observed_on": payload["generated_at"][:10],
                "previous_loaded": previous is not None,
                "content_sha256": payload["content_sha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
