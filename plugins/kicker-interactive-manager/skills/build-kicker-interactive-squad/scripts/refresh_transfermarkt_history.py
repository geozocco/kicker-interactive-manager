#!/usr/bin/env python3
"""Build league-contextual Transfermarkt histories for every Kicker player."""

from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import hashlib
import html
import json
import math
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from history_snapshot import (
    SCHEMA_VERSION,
    canonical_sha256,
    load_snapshot as load_history_snapshot,
    parse_timestamp,
    validate_snapshot,
)
from market_snapshot import (
    canonical_sha256 as market_sha256,
    load_snapshot as load_market_snapshot,
)


MODEL_VERSION = "transfermarkt-career-v2-youth-foreign-context"
YOUTH_REFERENCE_STRENGTH = 0.35
BASE_URL = "https://www.transfermarkt.co.uk"
USER_AGENT = (
    "Mozilla/5.0 (compatible; kicker-interactive-manager/1.0; "
    "+https://github.com/geozocco/kicker-interactive-manager)"
)
CLUB_LINK = re.compile(
    r"/startseite/verein/(?P<club_id>\d+)/saison_id/(?P<season>\d+)"
)
PLAYER_LINK = re.compile(r"/profil/spieler/(?P<player_id>\d+)")


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def isoformat(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def clamp(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 2)


def numeric(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def integer(value: Any) -> int:
    return int(numeric(value))


def identity_words(value: str) -> tuple[str, ...]:
    folded = unicodedata.normalize(
        "NFKD",
        html.unescape(value).replace("ß", "ss"),
    ).encode("ascii", "ignore").decode("ascii").casefold()
    return tuple(re.findall(r"[a-z0-9]+", folded))


def identity_key(value: str) -> str:
    return " ".join(identity_words(value))


def club_similarity(left: str, right: str) -> float:
    left_words = set(identity_words(left))
    right_words = set(identity_words(right))
    stopwords = {
        "1",
        "fc",
        "sc",
        "sv",
        "tsv",
        "vfb",
        "vfl",
        "bsc",
        "sg",
        "ev",
    }
    left_core = left_words - stopwords
    right_core = right_words - stopwords
    overlap = len(left_core & right_core) / max(1, len(left_core | right_core))
    sequence = SequenceMatcher(
        None,
        " ".join(sorted(left_core)),
        " ".join(sorted(right_core)),
    ).ratio()
    return max(overlap, sequence)


class AnchorCollector(HTMLParser):
    """Collect href, title and visible text for anchors."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._text: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag != "a" or self._current is not None:
            return
        attributes = {key: value or "" for key, value in attrs}
        href = attributes.get("href", "")
        if not href:
            return
        self._current = {
            "href": href,
            "title": attributes.get("title", ""),
        }
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._current is None:
            return
        value = dict(self._current)
        value["text"] = " ".join("".join(self._text).split())
        self.links.append(value)
        self._current = None
        self._text = []


def request_bytes(
    url: str,
    *,
    accept: str,
    timeout: float,
    attempts: int = 4,
) -> bytes:
    last_error: Exception | None = None
    headers = {
        "Accept": accept,
        "Accept-Language": "en-GB,en;q=0.8,de;q=0.6",
        "User-Agent": USER_AGENT,
    }
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, headers=headers),
                timeout=timeout,
            ) as response:
                return response.read(20_000_001)
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
        ) as error:
            last_error = error
            retryable = not isinstance(
                error,
                urllib.error.HTTPError,
            ) or error.code in {429, 500, 502, 503, 504}
            if not retryable or attempt + 1 >= attempts:
                break
            time.sleep(1.5 * (2**attempt))
    raise RuntimeError(f"could not load {url}: {last_error}")


def request_text(url: str, *, timeout: float) -> str:
    raw = request_bytes(
        url,
        accept="text/html,application/xhtml+xml",
        timeout=timeout,
    )
    return raw.decode("utf-8", "replace")


def request_json(url: str, *, timeout: float) -> dict[str, Any]:
    raw = request_bytes(
        url,
        accept="application/json",
        timeout=timeout,
    )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Transfermarkt returned invalid JSON for {url}") from error
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise RuntimeError(f"Transfermarkt performance response failed for {url}")
    return payload


def parse_clubs(page: str, *, season: int) -> list[dict[str, Any]]:
    parser = AnchorCollector()
    parser.feed(page)
    clubs: dict[int, dict[str, Any]] = {}
    for link in parser.links:
        match = CLUB_LINK.search(link["href"])
        if match is None or int(match.group("season")) != season:
            continue
        club_id = int(match.group("club_id"))
        name = link["title"].strip() or link["text"].strip()
        if not name:
            continue
        clubs.setdefault(
            club_id,
            {
                "club_id": club_id,
                "name": name,
                "href": link["href"],
            },
        )
    return sorted(clubs.values(), key=lambda item: item["club_id"])


def parse_squad(
    page: str,
    *,
    club_id: int,
    club_name: str,
) -> list[dict[str, Any]]:
    parser = AnchorCollector()
    parser.feed(page)
    players: dict[int, dict[str, Any]] = {}
    for link in parser.links:
        match = PLAYER_LINK.search(link["href"])
        if match is None:
            continue
        player_id = int(match.group("player_id"))
        name = link["text"].strip() or link["title"].strip()
        if not name:
            slug = link["href"].strip("/").split("/")[0]
            name = slug.replace("-", " ").title()
        players.setdefault(
            player_id,
            {
                "player_id": player_id,
                "name": name,
                "club_id": club_id,
                "club": club_name,
                "profile_url": f"{BASE_URL}{link['href'].split('?')[0]}",
            },
        )
    return sorted(players.values(), key=lambda item: item["player_id"])


def discover_squads(
    config: dict[str, Any],
    *,
    timeout: float,
    request_delay: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    season = int(config["transfermarkt_season"])
    league_url = (
        f"{BASE_URL}/{config['transfermarkt_competition_slug']}/"
        f"startseite/wettbewerb/{config['transfermarkt_competition_id']}/"
        f"plus/0?saison_id={season}"
    )
    clubs = parse_clubs(
        request_text(league_url, timeout=timeout),
        season=season,
    )
    expected_clubs = int(config["expected_team_count"])
    if len(clubs) != expected_clubs:
        raise RuntimeError(
            f"Transfermarkt league page returned {len(clubs)} clubs, "
            f"{expected_clubs} expected"
        )
    players: list[dict[str, Any]] = []
    for index, club in enumerate(clubs, start=1):
        squad_url = (
            f"{BASE_URL}/_/"
            f"kader/verein/{club['club_id']}/saison_id/{season}"
        )
        squad = parse_squad(
            request_text(squad_url, timeout=timeout),
            club_id=int(club["club_id"]),
            club_name=str(club["name"]),
        )
        if len(squad) < 12:
            raise RuntimeError(
                f"Transfermarkt squad for {club['name']} is incomplete: "
                f"{len(squad)} players"
            )
        players.extend(squad)
        print(
            f"Transfermarkt squad {index}/{len(clubs)}: "
            f"{club['name']} ({len(squad)})",
            file=sys.stderr,
            flush=True,
        )
        if request_delay > 0:
            time.sleep(request_delay)
    return clubs, players


def match_market_player(
    market_player: dict[str, Any],
    squad_players: list[dict[str, Any]],
) -> dict[str, Any]:
    market_name = identity_key(str(market_player["name"]))
    market_words = identity_words(str(market_player["name"]))
    market_club = str(market_player["club"])

    exact = [
        player
        for player in squad_players
        if identity_key(str(player["name"])) == market_name
    ]
    if exact:
        ranked = sorted(
            exact,
            key=lambda player: (
                -club_similarity(market_club, str(player["club"])),
                int(player["player_id"]),
            ),
        )
        top_similarity = club_similarity(market_club, str(ranked[0]["club"]))
        if (
            len(ranked) == 1
            or top_similarity
            > club_similarity(market_club, str(ranked[1]["club"])) + 0.15
        ):
            return {
                "status": "verified" if top_similarity >= 0.45 else "probable",
                "confidence": "high" if top_similarity >= 0.45 else "medium",
                **ranked[0],
                "match_method": "exact_name_and_club"
                if top_similarity >= 0.45
                else "globally_unique_exact_name",
            }
        return {
            "status": "ambiguous",
            "confidence": "none",
            "reason": "multiple_exact_name_matches",
        }

    if not market_words:
        return {
            "status": "unmatched",
            "confidence": "none",
            "reason": "empty_market_name",
        }
    surname = market_words[-1]
    first_initial = market_words[0][0]
    candidates = []
    for player in squad_players:
        words = identity_words(str(player["name"]))
        if (
            not words
            or words[-1] != surname
            or words[0][0] != first_initial
            or club_similarity(market_club, str(player["club"])) < 0.45
        ):
            continue
        market_set = set(market_words)
        player_set = set(words)
        name_overlap = len(market_set & player_set) / max(
            1,
            len(market_set | player_set),
        )
        candidates.append(
            (
                name_overlap,
                club_similarity(market_club, str(player["club"])),
                player,
            )
        )
    candidates.sort(
        key=lambda item: (-item[0], -item[1], int(item[2]["player_id"]))
    )
    if len(candidates) == 1 or (
        len(candidates) > 1
        and candidates[0][0] > candidates[1][0] + 0.2
    ):
        return {
            "status": "probable",
            "confidence": "medium",
            **candidates[0][2],
            "match_method": "unique_surname_initial_and_club",
        }
    if candidates:
        return {
            "status": "ambiguous",
            "confidence": "none",
            "reason": "multiple_surname_initial_matches",
        }
    return {
        "status": "unmatched",
        "confidence": "none",
        "reason": "no_current_squad_match",
    }


def strength_model_sha256(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def competition_rating(
    competition_id: str,
    model: dict[str, Any],
) -> dict[str, Any]:
    exact = model.get("competitions", {}).get(competition_id)
    if isinstance(exact, dict):
        return {
            "kind": str(exact["kind"]),
            "strength_factor": float(exact["strength_factor"]),
            "label": str(exact.get("label", competition_id)),
            "rated": bool(exact.get("rated", True)),
        }
    for rule in model.get("patterns", []):
        if re.search(str(rule["pattern"]), competition_id):
            return {
                "kind": str(rule["kind"]),
                "strength_factor": float(rule["strength_factor"]),
                "label": str(rule.get("label", competition_id)),
                "rated": bool(rule.get("rated", True)),
            }
    return {
        "kind": "unrated",
        "strength_factor": 0.0,
        "label": competition_id,
        "rated": False,
    }


def raw_appearances(payload: dict[str, Any]) -> list[dict[str, Any]]:
    performances = payload.get("data", {}).get("performance", [])
    if not isinstance(performances, list):
        raise RuntimeError("Transfermarkt performance list is missing")
    appearances: list[dict[str, Any]] = []
    for performance in performances:
        if not isinstance(performance, dict):
            continue
        statistics = performance.get("statistics", {})
        general = statistics.get("generalStatistics", {})
        if general.get("participationState") != "played":
            continue
        game = performance.get("gameInformation", {})
        playing_time = statistics.get("playingTimeStatistics", {})
        goals = statistics.get("goalStatistics", {})
        season = integer(game.get("seasonId"))
        competition_id = str(game.get("competitionId", "")).strip()
        if season <= 0 or not competition_id:
            continue
        appearances.append(
            {
                "season": season,
                "competition_id": competition_id,
                "starts": int(bool(playing_time.get("isStarting"))),
                "minutes": integer(playing_time.get("playedMinutes")),
                "goals": integer(goals.get("goalsScoredTotal")),
                "assists": integer(goals.get("assists")),
            }
        )
    return appearances


def season_is_proven(
    position: str,
    *,
    comparable_minutes: float,
    level_adjusted_minutes: float,
    goals: int,
    assists: int,
) -> bool:
    contributions = goals + assists
    if position in {"GOALKEEPER", "DEFENDER"}:
        return (
            comparable_minutes >= 1_000
            and level_adjusted_minutes >= 1_100
        )
    return (
        comparable_minutes >= 800
        and (
            level_adjusted_minutes >= 1_250
            or contributions >= 4
        )
    )


def aggregate_history(
    appearances: list[dict[str, Any]],
    *,
    position: str,
    target_strength: float,
    strength_model: dict[str, Any],
    maximum_seasons: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    grouped: dict[
        int,
        dict[str, dict[str, Any]],
    ] = defaultdict(dict)
    for appearance in appearances:
        season = int(appearance["season"])
        competition_id = str(appearance["competition_id"])
        rating = competition_rating(competition_id, strength_model)
        entry = grouped[season].setdefault(
            competition_id,
            {
                "competition_id": competition_id,
                **rating,
                "appearances": 0,
                "starts": 0,
                "minutes": 0,
                "goals": 0,
                "assists": 0,
            },
        )
        entry["appearances"] += 1
        entry["starts"] += int(appearance["starts"])
        entry["minutes"] += int(appearance["minutes"])
        entry["goals"] += int(appearance["goals"])
        entry["assists"] += int(appearance["assists"])

    selected_seasons = sorted(grouped, reverse=True)[:maximum_seasons]
    seasons: list[dict[str, Any]] = []
    for season_id in selected_seasons:
        competitions = sorted(
            grouped[season_id].values(),
            key=lambda item: (
                -int(item["minutes"]),
                str(item["competition_id"]),
            ),
        )
        totals = {
            "appearances": sum(int(item["appearances"]) for item in competitions),
            "starts": sum(int(item["starts"]) for item in competitions),
            "minutes": sum(int(item["minutes"]) for item in competitions),
            "goals": sum(int(item["goals"]) for item in competitions),
            "assists": sum(int(item["assists"]) for item in competitions),
        }
        level_adjusted_minutes = 0.0
        comparable_minutes = 0.0
        comparable_goals = 0
        comparable_assists = 0
        youth_adjusted_minutes = 0.0
        youth_adjusted_contributions = 0.0
        for item in competitions:
            if not item["rated"]:
                continue
            kind = str(item["kind"])
            factor = float(item["strength_factor"])
            ratio = min(1.35, factor / target_strength)
            if kind == "domestic_league":
                level_adjusted_minutes += int(item["minutes"]) * ratio
                if factor >= target_strength * 0.92:
                    comparable_minutes += int(item["minutes"])
                    comparable_goals += int(item["goals"])
                    comparable_assists += int(item["assists"])
            elif kind in {"continental", "international"}:
                level_adjusted_minutes += int(item["minutes"]) * ratio * 0.45
            elif kind == "youth":
                youth_ratio = min(
                    1.5,
                    factor / YOUTH_REFERENCE_STRENGTH,
                )
                youth_adjusted_minutes += int(item["minutes"]) * youth_ratio
                youth_adjusted_contributions += (
                    int(item["goals"]) + int(item["assists"])
                ) * youth_ratio
        proven = season_is_proven(
            position,
            comparable_minutes=comparable_minutes,
            level_adjusted_minutes=level_adjusted_minutes,
            goals=comparable_goals,
            assists=comparable_assists,
        )
        seasons.append(
            {
                "season": season_id,
                **totals,
                "level_adjusted_minutes": round(level_adjusted_minutes, 1),
                "comparable_minutes": round(comparable_minutes, 1),
                "youth_adjusted_minutes": round(youth_adjusted_minutes, 1),
                "youth_adjusted_contributions": round(
                    youth_adjusted_contributions,
                    2,
                ),
                "proven": proven,
                "competitions": competitions,
            }
        )

    career_totals = {
        field: sum(int(season[field]) for season in seasons)
        for field in (
            "appearances",
            "starts",
            "minutes",
            "goals",
            "assists",
        )
    }
    level_adjusted_minutes = sum(
        float(season["level_adjusted_minutes"]) for season in seasons
    )
    comparable_minutes = sum(
        float(season["comparable_minutes"]) for season in seasons
    )
    proven_seasons = sum(bool(season["proven"]) for season in seasons)
    youth_adjusted_minutes = sum(
        float(season["youth_adjusted_minutes"]) for season in seasons
    )
    youth_adjusted_contributions = sum(
        float(season["youth_adjusted_contributions"]) for season in seasons
    )
    youth_score = clamp(
        min(55, youth_adjusted_minutes / 60)
        + min(40, youth_adjusted_contributions * 1.4)
    )
    recent_adjusted_minutes = sum(
        float(season["level_adjusted_minutes"])
        for season in seasons[:2]
    )
    recent_start_ratio = (
        sum(int(season["starts"]) for season in seasons[:2])
        / max(1, sum(int(season["appearances"]) for season in seasons[:2]))
    )
    contribution_rate = (
        900.0
        * (career_totals["goals"] + career_totals["assists"])
        / max(1.0, level_adjusted_minutes)
    )
    confirmed_score = clamp(
        25
        + 16 * min(4, proven_seasons)
        + min(16, comparable_minutes / 400)
        + min(15, level_adjusted_minutes / 600)
        + min(8, max(0, proven_seasons - 2) * 2)
    )
    recent_minutes_score = clamp(35 + recent_adjusted_minutes / 55)
    if position in {"MIDFIELDER", "FORWARD"}:
        role_score = clamp(
            38 + 28 * recent_start_ratio + min(30, 5.5 * contribution_rate)
        )
    else:
        role_score = clamp(42 + 48 * recent_start_ratio)
    career = {
        **career_totals,
        "level_adjusted_minutes": round(level_adjusted_minutes, 1),
        "comparable_minutes": round(comparable_minutes, 1),
        "proven_seasons": int(proven_seasons),
        "youth_adjusted_minutes": round(youth_adjusted_minutes, 1),
        "youth_adjusted_contributions": round(
            youth_adjusted_contributions,
            2,
        ),
        "youth_score": youth_score,
        "confirmed_score": confirmed_score,
        "recent_minutes_score": recent_minutes_score,
        "role_score": role_score,
    }
    return seasons, career


def empty_career() -> dict[str, Any]:
    return {
        "appearances": 0,
        "starts": 0,
        "minutes": 0,
        "goals": 0,
        "assists": 0,
        "level_adjusted_minutes": 0.0,
        "comparable_minutes": 0.0,
        "proven_seasons": 0,
        "youth_adjusted_minutes": 0.0,
        "youth_adjusted_contributions": 0.0,
        "youth_score": 0.0,
        "confirmed_score": 0.0,
        "recent_minutes_score": 0.0,
        "role_score": 0.0,
    }


def previous_by_transfermarkt_id(
    previous: dict[str, Any] | None,
) -> dict[int, dict[str, Any]]:
    if not previous:
        return {}
    values: dict[int, dict[str, Any]] = {}
    for player in previous["players"].values():
        mapping = player["mapping"]
        transfermarkt_id = mapping.get("transfermarkt_player_id")
        if (
            mapping["status"] in {"verified", "probable"}
            and isinstance(transfermarkt_id, int)
            and player.get("retrieved_at")
        ):
            values[transfermarkt_id] = player
    return values


def load_identity_seed(
    path: Path | None,
    *,
    competition: str | None,
    season: str,
) -> list[dict[str, Any]]:
    if path is None:
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 1
        or (
            competition is not None
            and payload.get("competition") != competition
        )
        or payload.get("season") != season
        or not isinstance(payload.get("players"), list)
    ):
        raise RuntimeError("Transfermarkt identity seed is invalid")
    players: list[dict[str, Any]] = []
    seen: set[int] = set()
    for player in payload["players"]:
        if not isinstance(player, dict):
            raise RuntimeError("Transfermarkt identity seed contains an invalid player")
        player_id = player.get("player_id")
        if (
            isinstance(player_id, bool)
            or not isinstance(player_id, int)
            or player_id <= 0
            or player_id in seen
            or not str(player.get("name", "")).strip()
            or not str(player.get("club", "")).strip()
            or not str(player.get("profile_url", "")).startswith("https://")
        ):
            raise RuntimeError("Transfermarkt identity seed contains an invalid identity")
        seen.add(player_id)
        players.append(
            {
                "player_id": player_id,
                "name": str(player["name"]),
                "club": str(player["club"]),
                "profile_url": str(player["profile_url"]),
            }
        )
    return players


def load_performance_seed(
    path: Path | None,
    *,
    competition: str,
    season: str,
    strength_sha256: str,
    target_strength: float,
) -> dict[int, dict[str, Any]]:
    if path is None:
        return {}
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 1
        or payload.get("competition") != competition
        or payload.get("season") != season
        or payload.get("strength_model_sha256") != strength_sha256
        or not math.isclose(
            float(payload.get("target_strength", 0)),
            target_strength,
        )
        or not isinstance(payload.get("players"), list)
    ):
        raise RuntimeError("Transfermarkt performance seed is invalid")
    players: dict[int, dict[str, Any]] = {}
    for player in payload["players"]:
        if not isinstance(player, dict):
            raise RuntimeError(
                "Transfermarkt performance seed contains an invalid player"
            )
        player_id = player.get("transfermarkt_player_id")
        if (
            isinstance(player_id, bool)
            or not isinstance(player_id, int)
            or player_id <= 0
            or player_id in players
            or not str(player.get("retrieved_at", "")).strip()
            or not isinstance(player.get("seasons"), list)
            or not isinstance(player.get("career"), dict)
        ):
            raise RuntimeError(
                "Transfermarkt performance seed contains an invalid history"
            )
        players[player_id] = {
            "retrieved_at": str(player["retrieved_at"]),
            "seasons": player["seasons"],
            "career": player["career"],
        }
    return players


def identities_from_previous(
    previous: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not previous:
        return []
    values: dict[int, dict[str, Any]] = {}
    for player in previous["players"].values():
        mapping = player["mapping"]
        transfermarkt_id = mapping.get("transfermarkt_player_id")
        if (
            mapping["status"] not in {"verified", "probable"}
            or not isinstance(transfermarkt_id, int)
        ):
            continue
        values[transfermarkt_id] = {
            "player_id": transfermarkt_id,
            "name": str(mapping["transfermarkt_name"]),
            "club": str(mapping.get("transfermarkt_club", player["club"])),
            "profile_url": str(mapping["profile_url"]),
        }
    return sorted(values.values(), key=lambda item: item["player_id"])


def history_is_reusable(
    player: dict[str, Any],
    *,
    now: datetime,
    minimum_refresh_age_hours: int,
) -> bool:
    retrieved = parse_timestamp(player.get("retrieved_at"), "retrieved_at")
    return now - retrieved < timedelta(hours=minimum_refresh_age_hours)


def build_snapshot(
    market_payload: dict[str, Any],
    config: dict[str, Any],
    strength_model: dict[str, Any],
    *,
    previous: dict[str, Any] | None,
    identity_seed: list[dict[str, Any]],
    performance_seed: dict[int, dict[str, Any]],
    ttl_hours: int,
    minimum_refresh_age_hours: int,
    request_delay: float,
    timeout: float,
    workers: int,
) -> dict[str, Any]:
    if market_payload["competition"] != config["competition"]:
        raise RuntimeError("market and history competition do not match")
    if market_payload["season"] != config["season"]:
        raise RuntimeError("market and history season do not match")
    generated = utc_now()
    generated_at = isoformat(generated)
    target_strength = float(config["target_strength"])
    maximum_seasons = int(config["maximum_seasons"])
    current_strength_sha = strength_model_sha256(strength_model)
    if previous and (
        previous.get("strength_model_sha256") != current_strength_sha
        or not math.isclose(
            float(previous.get("target_strength", 0)),
            target_strength,
        )
    ):
        print(
            "Previous Transfermarkt history uses a different strength model; "
            "refreshing performance data.",
            file=sys.stderr,
        )
        previous = None
    try:
        _, squad_players = discover_squads(
            config,
            timeout=timeout,
            request_delay=request_delay,
        )
    except RuntimeError as error:
        squad_players = identity_seed or identities_from_previous(previous)
        if not squad_players:
            raise
        print(
            "Live Transfermarkt squad discovery unavailable; using the "
            f"validated identity bootstrap ({len(squad_players)} players): "
            f"{error}",
            file=sys.stderr,
        )
    market_players = [
        player
        for player in market_payload["players"]
        if int(player.get("market_value", 0)) < 100_000_000
    ]
    mappings = {
        str(player["id"]): match_market_player(player, squad_players)
        for player in market_players
    }
    previous_index = previous_by_transfermarkt_id(previous)
    histories_by_transfermarkt_id: dict[int, dict[str, Any]] = {}
    fetch_ids: list[int] = []
    for mapping in mappings.values():
        if mapping["status"] not in {"verified", "probable"}:
            continue
        transfermarkt_id = int(mapping["player_id"])
        previous_player = previous_index.get(transfermarkt_id)
        if previous_player and history_is_reusable(
            previous_player,
            now=generated,
            minimum_refresh_age_hours=minimum_refresh_age_hours,
        ):
            histories_by_transfermarkt_id[transfermarkt_id] = {
                "retrieved_at": str(previous_player["retrieved_at"]),
                "seasons": previous_player["seasons"],
                "career": previous_player["career"],
            }
        else:
            fetch_ids.append(transfermarkt_id)

    def fetch_history(
        transfermarkt_id: int,
    ) -> tuple[int, list[dict[str, Any]]]:
        payload = request_json(
            f"{BASE_URL}/ceapi/performance-game/{transfermarkt_id}",
            timeout=timeout,
        )
        if request_delay > 0:
            time.sleep(request_delay)
        return transfermarkt_id, raw_appearances(payload)

    failures: dict[int, str] = {}
    unique_fetch_ids = sorted(set(fetch_ids))
    if unique_fetch_ids and performance_seed:
        probe_id = unique_fetch_ids[0]
        try:
            result_id, appearances = fetch_history(probe_id)
            histories_by_transfermarkt_id[result_id] = {
                "retrieved_at": generated_at,
                "appearances": appearances,
            }
            unique_fetch_ids = unique_fetch_ids[1:]
        except Exception as error:  # pragma: no cover - network boundary
            print(
                "Live Transfermarkt performance endpoint unavailable; using "
                f"the validated performance bootstrap: {error}",
                file=sys.stderr,
            )
            for transfermarkt_id in unique_fetch_ids:
                seeded = performance_seed.get(transfermarkt_id)
                if seeded:
                    histories_by_transfermarkt_id[transfermarkt_id] = seeded
                else:
                    failures[transfermarkt_id] = (
                        "missing_from_performance_bootstrap"
                    )
            unique_fetch_ids = []

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max(1, workers),
    ) as executor:
        futures = {
            executor.submit(fetch_history, transfermarkt_id): transfermarkt_id
            for transfermarkt_id in unique_fetch_ids
        }
        for completed, future in enumerate(
            concurrent.futures.as_completed(futures),
            start=1,
        ):
            transfermarkt_id = futures[future]
            try:
                result_id, appearances = future.result()
                histories_by_transfermarkt_id[result_id] = {
                    "retrieved_at": generated_at,
                    "appearances": appearances,
                }
            except Exception as error:  # pragma: no cover - network boundary
                previous_player = previous_index.get(transfermarkt_id)
                seeded = performance_seed.get(transfermarkt_id)
                if previous_player:
                    histories_by_transfermarkt_id[transfermarkt_id] = {
                        "retrieved_at": str(previous_player["retrieved_at"]),
                        "seasons": previous_player["seasons"],
                        "career": previous_player["career"],
                    }
                elif seeded:
                    histories_by_transfermarkt_id[transfermarkt_id] = seeded
                else:
                    failures[transfermarkt_id] = str(error)
            if (
                completed == 1
                or completed == len(futures)
                or completed % 25 == 0
            ):
                print(
                    f"Transfermarkt performance {completed}/{len(futures)}",
                    file=sys.stderr,
                    flush=True,
                )

    players: dict[str, dict[str, Any]] = {}
    for market_player in market_players:
        player_id = str(market_player["id"])
        mapping = mappings[player_id]
        status = str(mapping["status"])
        common = {
            "name": str(market_player["name"]),
            "club": str(market_player["club"]),
            "position": str(market_player["position"]),
        }
        if status not in {"verified", "probable"}:
            players[player_id] = {
                **common,
                "mapping": {
                    "status": status,
                    "confidence": str(mapping["confidence"]),
                    "transfermarkt_player_id": None,
                    "reason": str(mapping.get("reason", "unresolved")),
                },
                "retrieved_at": None,
                "career": empty_career(),
                "seasons": [],
            }
            continue
        transfermarkt_id = int(mapping["player_id"])
        history = histories_by_transfermarkt_id.get(transfermarkt_id)
        if history is None:
            players[player_id] = {
                **common,
                "mapping": {
                    "status": "unmatched",
                    "confidence": "none",
                    "transfermarkt_player_id": None,
                    "reason": (
                        "performance_fetch_failed: "
                        f"{failures.get(transfermarkt_id, 'unknown')}"
                    )[:300],
                },
                "retrieved_at": None,
                "career": empty_career(),
                "seasons": [],
            }
            continue
        retrieved_at = str(history["retrieved_at"])
        if "appearances" in history:
            seasons, career = aggregate_history(
                history["appearances"],
                position=str(market_player["position"]),
                target_strength=target_strength,
                strength_model=strength_model,
                maximum_seasons=maximum_seasons,
            )
        else:
            seasons = history["seasons"]
            career = history["career"]
        players[player_id] = {
            **common,
            "mapping": {
                "status": status,
                "confidence": str(mapping["confidence"]),
                "transfermarkt_player_id": transfermarkt_id,
                "transfermarkt_name": str(mapping["name"]),
                "transfermarkt_club": str(mapping["club"]),
                "profile_url": str(mapping["profile_url"]),
                "match_method": str(mapping["match_method"]),
            },
            "retrieved_at": retrieved_at,
            "career": career,
            "seasons": seasons,
        }

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "expires_at": isoformat(generated + timedelta(hours=ttl_hours)),
        "competition": market_payload["competition"],
        "season": market_payload["season"],
        "market_sha256": market_sha256(market_payload),
        "model_version": MODEL_VERSION,
        "strength_model_sha256": current_strength_sha,
        "target_strength": target_strength,
        "source": {
            "provider": "Transfermarkt",
            "base_url": BASE_URL,
            "competition_id": config["transfermarkt_competition_id"],
            "performance_endpoint": "/ceapi/performance-game/{player_id}",
            "attribution_url": "https://www.transfermarkt.de/",
        },
        "requirements": {
            "player_count": len(market_players),
            "minimum_resolved_percent": float(
                config["minimum_resolved_percent"]
            ),
        },
        "players": players,
    }
    payload["content_sha256"] = canonical_sha256(payload)
    return validate_snapshot(payload)


def load_previous(location: str | None) -> dict[str, Any] | None:
    if not location:
        return None
    try:
        return load_history_snapshot(location, require_fresh=False)
    except Exception as error:
        print(
            f"Previous Transfermarkt history unavailable: {error}",
            file=sys.stderr,
        )
        return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--strengths", type=Path, required=True)
    parser.add_argument("--identity-seed", type=Path)
    parser.add_argument(
        "--additional-identity-seed",
        type=Path,
        action="append",
        default=[],
        help="validated same-season identity catalog from another competition",
    )
    parser.add_argument("--performance-seed", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous")
    parser.add_argument("--ttl-hours", type=int, default=192)
    parser.add_argument("--minimum-refresh-age-hours", type=int, default=144)
    parser.add_argument("--request-delay", type=float, default=0.15)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--workers", type=int, default=4)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = json.loads(args.mapping.read_text(encoding="utf-8"))
    strength_model = json.loads(args.strengths.read_text(encoding="utf-8"))
    market_payload = load_market_snapshot(args.market)
    identity_seed = load_identity_seed(
        args.identity_seed,
        competition=str(config["competition"]),
        season=str(config["season"]),
    )
    additional_identities = [
        player
        for path in args.additional_identity_seed
        for player in load_identity_seed(
            path,
            competition=None,
            season=str(config["season"]),
        )
    ]
    identity_by_id = {
        int(player["player_id"]): player
        for player in [*identity_seed, *additional_identities]
    }
    identity_seed = sorted(
        identity_by_id.values(),
        key=lambda player: int(player["player_id"]),
    )
    current_strength_sha = strength_model_sha256(strength_model)
    performance_seed = load_performance_seed(
        args.performance_seed,
        competition=str(config["competition"]),
        season=str(config["season"]),
        strength_sha256=current_strength_sha,
        target_strength=float(config["target_strength"]),
    )
    payload = build_snapshot(
        market_payload,
        config,
        strength_model,
        previous=load_previous(args.previous),
        identity_seed=identity_seed,
        performance_seed=performance_seed,
        ttl_hours=args.ttl_hours,
        minimum_refresh_age_hours=args.minimum_refresh_age_hours,
        request_delay=args.request_delay,
        timeout=args.timeout,
        workers=args.workers,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    resolved = sum(
        player["mapping"]["status"] in {"verified", "probable"}
        for player in payload["players"].values()
    )
    proven = sum(
        int(player["career"]["proven_seasons"]) >= 2
        for player in payload["players"].values()
    )
    print(
        f"Wrote {len(payload['players'])} player histories, "
        f"{resolved} resolved and {proven} multi-season proven to {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
