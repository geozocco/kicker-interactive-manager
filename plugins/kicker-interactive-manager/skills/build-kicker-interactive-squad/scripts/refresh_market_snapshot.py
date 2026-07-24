#!/usr/bin/env python3
"""Build a central market snapshot from an official Kicker player CSV."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from market_snapshot import (
    SCHEMA_VERSION,
    canonical_sha256,
    validate_snapshot,
)


USER_AGENT = "kicker-interactive-manager-market-refresh/1"
MAX_CSV_BYTES = 5_000_000
REQUIRED_COLUMNS = {
    "ID",
    "Angezeigter Name (kurz)",
    "Angezeigter Name",
    "Verein",
    "Position",
    "Marktwert",
    "Punkte",
    "Notendurchschnitt",
}


def numeric(value: Any) -> float:
    text = str(value or "").strip().replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return 0.0


def validate_official_csv_url(url: str) -> None:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {
            "kicker-libero.de",
            "www.kicker-libero.de",
        }
        or not parsed.path.startswith(
            "/api/sportsdata/v1/players-details/"
        )
        or not parsed.path.endswith(".csv")
    ):
        raise ValueError(
            "market source must be an official Kicker players-details HTTPS CSV"
        )


def fetch_official_csv(
    url: str,
    *,
    timeout: float = 30.0,
    attempts: int = 3,
) -> bytes:
    validate_official_csv_url(url)
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "Accept": "text/csv,*/*;q=0.1",
                    "User-Agent": USER_AGENT,
                },
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                validate_official_csv_url(response.geturl())
                raw = response.read(MAX_CSV_BYTES + 1)
                if len(raw) > MAX_CSV_BYTES:
                    raise ValueError("official Kicker CSV exceeds 5 MB")
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
    raise ValueError(f"could not download official Kicker CSV: {last_error}")


def parse_players(raw: bytes) -> list[dict[str, Any]]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("official Kicker CSV is not UTF-8") from error
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    if not reader.fieldnames or not REQUIRED_COLUMNS.issubset(reader.fieldnames):
        raise ValueError("official Kicker CSV columns are incomplete")
    players: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in reader:
        player_id = str(row.get("ID", "")).strip()
        name = str(row.get("Angezeigter Name", "")).strip()
        club = str(row.get("Verein", "")).strip()
        position = str(row.get("Position", "")).strip().upper()
        market_value = int(numeric(row.get("Marktwert")))
        if (
            not player_id
            or player_id in seen_ids
            or not name
            or not club
            or market_value <= 0
        ):
            raise ValueError(
                "official Kicker CSV contains an invalid or duplicate player"
            )
        seen_ids.add(player_id)
        players.append(
            {
                "id": player_id,
                "short_name": str(
                    row.get("Angezeigter Name (kurz)", "")
                ).strip()
                or name,
                "name": name,
                "club": club,
                "position": position,
                "market_value": market_value,
                "points": numeric(row.get("Punkte")),
                "average_grade": numeric(
                    row.get("Notendurchschnitt")
                ),
            }
        )
    return sorted(players, key=lambda player: player["id"])


def build_snapshot(
    config: dict[str, Any],
    raw: bytes,
    *,
    annotations: dict[str, Any] | None = None,
    ttl_hours: int = 18,
    now: datetime | None = None,
) -> dict[str, Any]:
    players = parse_players(raw)
    minimum_players = int(config.get("minimum_player_count", 1))
    maximum_players = int(config.get("maximum_player_count", 2_000))
    if not minimum_players <= len(players) <= maximum_players:
        raise ValueError(
            "official Kicker player count is outside configured bounds: "
            f"{len(players)} not in {minimum_players}..{maximum_players}"
        )
    clubs = {player["club"] for player in players}
    expected_team_count = int(config.get("expected_team_count", 0))
    if len(clubs) != expected_team_count:
        raise ValueError(
            "official Kicker club count is incomplete: "
            f"expected={expected_team_count}, actual={len(clubs)}"
        )
    annotations = annotations or {}
    player_ids = {player["id"] for player in players}
    unknown_annotation_ids = set(annotations) - player_ids
    if unknown_annotation_ids:
        raise ValueError(
            "central annotations reference players outside the current market"
        )
    generated_at = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    expires_at = generated_at + timedelta(hours=ttl_hours)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
        "competition": str(config["competition"]),
        "season": str(config["season"]),
        "expected_team_count": expected_team_count,
        "source": {
            "provider": "kicker",
            "url": str(config["source_url"]),
            "csv_sha256": hashlib.sha256(raw).hexdigest(),
        },
        "players": players,
        "annotations": annotations,
    }
    payload["content_sha256"] = canonical_sha256(payload)
    return validate_snapshot(payload)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--annotations", type=Path)
    parser.add_argument("--ttl-hours", type=int, default=18)
    args = parser.parse_args()
    if not 1 <= args.ttl_hours <= 72:
        parser.error("--ttl-hours must be between 1 and 72")
    return args


def main() -> int:
    args = parse_args()
    config = json.loads(args.mapping.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise SystemExit("market mapping must be a JSON object")
    if config.get("competition") not in {
        "Bundesliga",
        "2. Bundesliga",
        "3. Liga",
    }:
        raise SystemExit(
            "market competition must be Bundesliga, 2. Bundesliga or 3. Liga"
        )
    for field_name in (
        "competition",
        "season",
        "source_url",
        "expected_team_count",
    ):
        if field_name not in config:
            raise SystemExit(f"market mapping field {field_name!r} is required")
    annotations: dict[str, Any] = {}
    if args.annotations:
        annotation_payload = json.loads(
            args.annotations.read_text(encoding="utf-8")
        )
        annotations = annotation_payload.get(
            "players",
            annotation_payload,
        )
        if not isinstance(annotations, dict):
            raise SystemExit("central annotations must be a JSON object")
    raw = fetch_official_csv(str(config["source_url"]))
    payload = build_snapshot(
        config,
        raw,
        annotations=annotations,
        ttl_hours=args.ttl_hours,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(f"{args.output.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(args.output)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "competition": payload["competition"],
                "season": payload["season"],
                "players": len(payload["players"]),
                "clubs": len(
                    {player["club"] for player in payload["players"]}
                ),
                "content_sha256": payload["content_sha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
