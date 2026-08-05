#!/usr/bin/env python3
"""Refresh upcoming fixtures and contextual opponent strength."""

from __future__ import annotations

import argparse
import json
import os
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from matchday_snapshot import SCHEMA_VERSION, canonical_sha256, validate_snapshot
from quality_snapshot import load_snapshot as load_quality_snapshot
from refresh_news_snapshot import api_sports_pages, is_api_sports_rate_limit


API_URL = "https://v3.football.api-sports.io/fixtures"
GENERIC_CLUB_TOKENS = {
    "1",
    "club",
    "fc",
    "fsv",
    "sc",
    "sv",
    "tsv",
    "vfl",
    "vfb",
}


def clamp(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 50.0
    return round(max(0.0, min(100.0, number)), 2)


def club_tokens(value: Any) -> tuple[str, ...]:
    # Unicode normalization does not decompose German sharp-s. Normalize it
    # explicitly so provider spellings such as ``Grossaspach`` and
    # ``Rot-Weiss`` resolve to Kicker's ``Großaspach`` and ``Rot-Weiß``.
    text = unicodedata.normalize(
        "NFKD",
        str(value or "").replace("ß", "ss").replace("ẞ", "ss"),
    )
    ascii_text = text.encode("ascii", "ignore").decode("ascii").casefold()
    return tuple(
        token
        for token in re.findall(r"[a-z0-9]+", ascii_text)
        if token not in GENERIC_CLUB_TOKENS
    )


def resolve_quality_club(
    provider_name: str,
    quality_clubs: set[str],
) -> str | None:
    """Resolve provider team names conservatively to canonical Kicker clubs."""

    provider_tokens = set(club_tokens(provider_name))
    if not provider_tokens:
        return None
    exact = [
        club
        for club in quality_clubs
        if set(club_tokens(club)) == provider_tokens
    ]
    if len(exact) == 1:
        return exact[0]
    candidates: list[tuple[float, str]] = []
    for club in quality_clubs:
        candidate_tokens = set(club_tokens(club))
        if not candidate_tokens:
            continue
        overlap = len(provider_tokens & candidate_tokens)
        union = len(provider_tokens | candidate_tokens)
        score = overlap / max(1, union)
        if overlap >= 1 and (
            provider_tokens <= candidate_tokens
            or candidate_tokens <= provider_tokens
            or score >= 0.66
        ):
            candidates.append((score, club))
    candidates.sort(key=lambda item: (-item[0], item[1]))
    if not candidates:
        return None
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
        return None
    return candidates[0][1]


def team_strengths(quality: dict[str, Any]) -> dict[str, dict[str, float]]:
    values: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for annotation in quality.get("annotations", {}).values():
        if not isinstance(annotation, dict):
            continue
        club = str(annotation.get("club", "")).strip()
        projection = annotation.get("advanced_signals", {}).get(
            "team_projection",
            {},
        )
        if club and isinstance(projection, dict):
            values[club].append(projection)
    return {
        club: {
            key: round(
                sum(float(item.get(key, 50)) for item in projections)
                / len(projections),
                2,
            )
            for key in (
                "attack_strength",
                "defense_strength",
                "chance_creation",
                "clean_sheet_outlook",
            )
        }
        for club, projections in values.items()
    }


def build_snapshot(
    mapping: dict[str, Any],
    quality: dict[str, Any],
    *,
    token: str,
    ttl_hours: int = 12,
) -> dict[str, Any]:
    generated = datetime.now(timezone.utc).replace(microsecond=0)
    strengths = team_strengths(quality)
    fixtures: list[dict[str, Any]] = []
    status = "ok"
    provider_error = ""
    try:
        pages = api_sports_pages(
            API_URL,
            query={
                "league": int(mapping["api_sports"]["league_id"]),
                "season": int(mapping["api_sports"]["season"]),
                "next": 30,
            },
            headers={"x-apisports-key": token},
            paginate=False,
        )
        response = [
            item
            for page in pages
            for item in page.get("response", [])
            if isinstance(item, dict)
        ]
        for item in response:
            provider_home = str(
                item.get("teams", {}).get("home", {}).get("name", "")
            )
            provider_away = str(
                item.get("teams", {}).get("away", {}).get("name", "")
            )
            if not provider_home or not provider_away:
                continue
            home = resolve_quality_club(provider_home, set(strengths))
            away = resolve_quality_club(provider_away, set(strengths))
            fixtures.append(
                {
                    "fixture_id": item.get("fixture", {}).get("id"),
                    "date": str(item.get("fixture", {}).get("date", "")),
                    "round": str(item.get("league", {}).get("round", "")),
                    "home": home or provider_home,
                    "away": away or provider_away,
                    "provider_home": provider_home,
                    "provider_away": provider_away,
                }
            )
    except RuntimeError as error:
        status = "unavailable"
        provider_error = (
            "rate_limited"
            if is_api_sports_rate_limit(error)
            or "request limit for the day" in str(error).casefold()
            else "provider_error"
        )
    teams: dict[str, dict[str, Any]] = {}
    for fixture in fixtures:
        for club, opponent, venue in (
            (fixture["home"], fixture["away"], "home"),
            (fixture["away"], fixture["home"], "away"),
        ):
            if club not in strengths:
                continue
            opponent_strength = strengths.get(
                opponent,
                {
                    "attack_strength": 50.0,
                    "defense_strength": 50.0,
                    "chance_creation": 50.0,
                },
            )
            difficulty = clamp(
                0.45 * opponent_strength["attack_strength"]
                + 0.45 * opponent_strength["defense_strength"]
                + 0.10 * opponent_strength["chance_creation"]
                - (3.0 if venue == "home" else 0.0)
            )
            current = teams.get(club)
            candidate = {
                "opponent": opponent,
                "venue": venue,
                "date": fixture["date"],
                "round": fixture["round"],
                "fixture_difficulty": difficulty,
                "opponent_attack": opponent_strength["attack_strength"],
                "opponent_defense": opponent_strength["defense_strength"],
            }
            if current is None or candidate["date"] < current["date"]:
                teams[club] = candidate
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated.isoformat().replace("+00:00", "Z"),
        "expires_at": (
            generated + timedelta(hours=ttl_hours)
        ).isoformat().replace("+00:00", "Z"),
        "competition": quality["competition"],
        "season": quality["season"],
        "quality_sha256": quality["content_sha256"],
        "status": status,
        "provider_error": provider_error,
        "fixtures": fixtures,
        "teams": teams,
    }
    payload["content_sha256"] = canonical_sha256(payload)
    return validate_snapshot(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--quality", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ttl-hours", type=int, default=12)
    args = parser.parse_args()
    mapping = json.loads(args.mapping.read_text(encoding="utf-8"))
    quality = load_quality_snapshot(args.quality)
    payload = build_snapshot(
        mapping,
        quality,
        token=os.environ.get("API_SPORTS_KEY", "").strip(),
        ttl_hours=args.ttl_hours,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "status": payload["status"],
                "fixtures": len(payload["fixtures"]),
                "teams": len(payload["teams"]),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
