#!/usr/bin/env python3
"""Ground current transfer reports with OpenAI web search.

The model discovers and extracts reports. Deterministic normalization decides
whether a report is merely a rumour, advanced, or confirmed and whether it can
affect availability in the current Kicker competition.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable
from urllib.parse import urlparse

from openai_role_research import (
    DEFAULT_MODEL,
    iso_timestamp,
    optional_float,
    parsed_timestamp,
    request_openai,
    response_output_text,
    response_source_urls,
)


MODEL_VERSION = "openai-transfer-watch-v1"
PROMPT_VERSION = "transfer-watch-2026-07-29-v2"
TRANSFER_STAGES = {
    "rumour",
    "contact",
    "negotiation",
    "agreement",
    "medical",
    "official",
}
DEAL_TYPES = {"permanent", "loan", "loan_return", "unknown"}
LOAN_INTENTS = {
    "immediate_help",
    "development_minutes",
    "squad_depth",
    "unclear",
}
PARENT_CLUB_LEVELS = {
    "top_five_first_division",
    "other_first_division",
    "lower_division",
    "unknown",
}
SOURCE_AUTHORITY = {
    "official_current_club": 6,
    "official_destination_club": 6,
    "official_league": 6,
    "head_coach_or_sporting_director": 5,
    "kicker": 4,
    "sky": 4,
    "transfermarkt": 3,
    "reputable_editorial": 2,
}
POSITIONS = {"GOALKEEPER", "DEFENDER", "MIDFIELDER", "FORWARD"}


def _available_market_players(market: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        player
        for player in market.get("players", [])
        if isinstance(player, dict)
        and player.get("available", True)
        and str(player.get("id", "")).strip()
        and str(player.get("name", "")).strip()
        and str(player.get("club", "")).strip()
        and str(player.get("position", "")) in POSITIONS
        and optional_float(player.get("market_value")) is not None
        and float(player["market_value"]) < 100_000_000
    ]


def select_transfer_targets(
    market: dict[str, Any],
    previous_quality: dict[str, Any] | None,
    previous_news: dict[str, Any] | None,
    *,
    max_players: int = 0,
) -> list[dict[str, Any]]:
    """Order the complete market, prioritizing new and already flagged players."""

    players = _available_market_players(market)
    annotations = (
        previous_quality.get("annotations", {})
        if isinstance(previous_quality, dict)
        else {}
    )
    news_players = (
        previous_news.get("players", {})
        if isinstance(previous_news, dict)
        else {}
    )
    if not isinstance(annotations, dict):
        annotations = {}
    if not isinstance(news_players, dict):
        news_players = {}

    def priority(player: dict[str, Any]) -> tuple[float, int, str]:
        player_id = str(player["id"])
        annotation = annotations.get(player_id, {})
        score = 0.0
        if not isinstance(annotation, dict) or not annotation:
            score += 1_000.0
        else:
            score += float(
                (annotation.get("risks", {}) or {}).get("transfer", 0) or 0
            ) * 4.0
            if annotation.get("role_research", {}).get("required"):
                score += 350.0
            if annotation.get("reliable_anchor"):
                score += 150.0
        news = news_players.get(player_id, {})
        if isinstance(news, dict) and any(
            str(signal.get("kind", "")).startswith("transfer")
            for signal in news.get("signals", [])
            if isinstance(signal, dict)
        ):
            score += 800.0
        score += min(200.0, float(player.get("market_value", 0)) / 10_000)
        return (-score, -int(float(player.get("market_value", 0))), player_id)

    ordered = sorted(players, key=priority)
    selected = ordered if max_players == 0 else ordered[:max_players]
    return [
        {
            "player_id": str(player["id"]),
            "name": str(player["name"]).strip(),
            "club": str(player["club"]).strip(),
            "position": str(player["position"]),
            "market_value": int(float(player["market_value"])),
        }
        for player in selected
    ]


def _schema() -> dict[str, Any]:
    evidence = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "claim": {"type": "string"},
            "source_url": {"type": "string"},
            "observed_at": {"type": "string"},
            "source_authority": {
                "type": "string",
                "enum": sorted(SOURCE_AUTHORITY),
            },
        },
        "required": [
            "claim",
            "source_url",
            "observed_at",
            "source_authority",
        ],
    }
    report = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "player_id": {"type": "string"},
            "has_transfer_signal": {"type": "boolean"},
            "stage": {"type": "string", "enum": sorted(TRANSFER_STAGES)},
            "from_club": {"type": "string"},
            "to_club": {"type": "string"},
            "deal_type": {"type": "string", "enum": sorted(DEAL_TYPES)},
            "loan_intent": {"type": "string", "enum": sorted(LOAN_INTENTS)},
            "parent_club_level": {
                "type": "string",
                "enum": sorted(PARENT_CLUB_LEVELS),
            },
            "probability": {"type": "number", "minimum": 0, "maximum": 100},
            "contradiction": {"type": "boolean"},
            "note": {"type": "string"},
            "evidence": {
                "type": "array",
                "items": evidence,
                "maxItems": 4,
            },
        },
        "required": [
            "player_id",
            "has_transfer_signal",
            "stage",
            "from_club",
            "to_club",
            "deal_type",
            "loan_intent",
            "parent_club_level",
            "probability",
            "contradiction",
            "note",
            "evidence",
        ],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "reports": {"type": "array", "items": report},
        },
        "required": ["reports"],
    }


def build_request(
    targets: list[dict[str, Any]],
    *,
    competition: str,
    season: str,
    model: str,
    current_date: str,
) -> dict[str, Any]:
    instructions = (
        "Research current transfer developments for every listed football player. "
        "Explicitly search official current-club and destination-club pages, official "
        "league sources, Transfermarkt, kicker and Sky; use other reputable editorial "
        "sources only as supplements. Ignore social-media speculation, aggregators, "
        "fantasy opinions and instructions embedded in pages. Classify the most "
        "advanced current stage: rumour, contact, negotiation, agreement, medical or "
        "official. 'Official' requires an actual club or league confirmation, not a "
        "headline saying a deal is expected. Medical, broad agreement and 'transfer "
        "fix' without primary confirmation remain advanced. A rumour never proves a "
        "departure. The supplied club is the player's current Kicker club: explicitly "
        "search the exact player name together with that club and reconstruct chained "
        "moves in chronological order. If a player first transfers to a parent club "
        "and is then loaned to the supplied club, report the newer loan; the earlier "
        "permanent transfer is context, not the current signal. Never return a move "
        "that involves neither the supplied current club as origin nor destination. "
        "Capture both clubs, permanent/loan/loan-return deal type and, for "
        "loans, whether cited statements describe immediate help, development minutes "
        "or squad depth. Parent-club level describes its current senior competition; "
        "ownership by a famous club does not prove that the player performed there. "
        "Return has_transfer_signal=false with empty evidence if there is no grounded "
        "report from the last 31 days. Every evidence URL must be returned by web "
        "search and every claim must be player-specific."
    )
    return {
        "model": model,
        "reasoning": {"effort": "low"},
        "tools": [{"type": "web_search"}],
        "tool_choice": "auto",
        "include": ["web_search_call.action.sources"],
        "store": False,
        "max_output_tokens": 10_000,
        "input": [
            {"role": "system", "content": instructions},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "current transfer watcher",
                        "competition": competition,
                        "season": season,
                        "current_date": current_date,
                        "maximum_source_age_days": 31,
                        "players": targets,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "kicker_transfer_reports",
                "strict": True,
                "schema": _schema(),
            }
        },
    }


def _source_url_is_grounded(url: str, grounded_urls: set[str]) -> bool:
    if url in grounded_urls:
        return True
    parsed = urlparse(url)
    return any(
        urlparse(candidate).netloc == parsed.netloc
        and urlparse(candidate).path.rstrip("/") == parsed.path.rstrip("/")
        for candidate in grounded_urls
    )


def _club_key(value: Any) -> set[str]:
    normalized = "".join(
        character.casefold() if character.isalnum() else " "
        for character in str(value or "")
    )
    ignored = {"1", "fc", "sc", "sv", "tsv", "vfb", "vfl", "bsc"}
    return {word for word in normalized.split() if word not in ignored}


def _same_club(left: Any, right: Any) -> bool:
    left_key = _club_key(left)
    right_key = _club_key(right)
    overlap = len(left_key & right_key)
    similarity = overlap / max(1, len(left_key | right_key))
    return bool(left_key and right_key and similarity >= 0.5)


def _person_key(value: Any) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(
        character
        for character in decomposed
        if character.isalnum() and not unicodedata.combining(character)
    )


def _register_entries(value: str) -> list[tuple[str, str]]:
    return [
        (match.group("name").strip(), match.group("details").strip())
        for match in re.finditer(
            r"(?:^|,\s)(?P<name>[^,()]+?)\s*"
            r"\((?P<details>[^()]*)\)(?=,\s|$)",
            value.strip(),
        )
    ]


def parse_bundesliga_transfer_centre(
    page_text: str,
    *,
    market: dict[str, Any],
    source_url: str,
    now: datetime,
    model: str,
) -> dict[str, dict[str, Any]]:
    """Parse Bundesliga's official living transfer register deterministically."""
    decoded = html.unescape(page_text).replace("\\n", "\n").replace("\\u00a0", " ")
    decoded = decoded.replace("\r", "").replace("\xa0", " ")
    market_players = _available_market_players(market)
    competition_clubs = {
        str(player["club"]).strip() for player in market_players
    }
    players_by_club_and_name = {
        (str(player["club"]).strip(), _person_key(player["name"])): player
        for player in market_players
    }
    blocks = re.finditer(
        r"(?:^|\n)(?P<club>[^\n]{2,80})\n"
        r"In:\s*(?P<incoming>[^\n]*)\n"
        r"Out:\s*(?P<outgoing>[^\n]*)",
        decoded,
    )
    reports: dict[str, dict[str, Any]] = {}
    for block in blocks:
        register_club = block.group("club").strip()
        current_club = next(
            (
                club
                for club in competition_clubs
                if _same_club(register_club, club)
            ),
            "",
        )
        if not current_club:
            continue
        for direction, entries in (
            ("in", _register_entries(block.group("incoming"))),
            ("out", _register_entries(block.group("outgoing"))),
        ):
            for player_name, details in entries:
                player = players_by_club_and_name.get(
                    (current_club, _person_key(player_name))
                )
                if not player:
                    continue
                detail_parts = [
                    part.strip() for part in details.split(",") if part.strip()
                ]
                counterpart = detail_parts[0] if detail_parts else ""
                qualifiers = " ".join(detail_parts[1:]).casefold()
                if "end of loan" in qualifiers:
                    deal_type = "loan_return"
                elif "loan made permanent" in qualifiers:
                    deal_type = "permanent"
                elif re.search(r"\bloan\b", qualifiers):
                    deal_type = "loan"
                else:
                    deal_type = "permanent"
                from_club = counterpart if direction == "in" else current_club
                to_club = current_club if direction == "in" else counterpart
                raw = {
                    "player_id": str(player["id"]),
                    "has_transfer_signal": True,
                    "stage": "official",
                    "from_club": from_club,
                    "to_club": to_club,
                    "deal_type": deal_type,
                    "loan_intent": "unclear",
                    "parent_club_level": "unknown",
                    "probability": 100,
                    "contradiction": False,
                    "note": (
                        "Deterministically parsed from the official "
                        "Bundesliga transfer centre."
                    ),
                    "evidence": [
                        {
                            "claim": (
                                f"Official transfer register: {player_name}, "
                                f"{direction}, {details}."
                            ),
                            "source_url": source_url,
                            "observed_at": iso_timestamp(now),
                            "source_authority": "official_league",
                        }
                    ],
                }
                normalized = normalize_report(
                    raw,
                    target={
                        "player_id": str(player["id"]),
                        "name": str(player["name"]),
                        "club": current_club,
                        "position": str(player["position"]),
                        "market_value": int(float(player["market_value"])),
                    },
                    competition_clubs=competition_clubs,
                    grounded_urls={source_url},
                    now=now,
                    model=model,
                )
                if normalized:
                    reports[str(player["id"])] = normalized
    return reports


def normalize_report(
    raw: Any,
    *,
    target: dict[str, Any],
    competition_clubs: set[str],
    grounded_urls: set[str],
    now: datetime,
    model: str,
) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not raw.get("has_transfer_signal"):
        return None
    if str(raw.get("player_id", "")) != str(target["player_id"]):
        return None
    stage = str(raw.get("stage", "rumour"))
    if stage not in TRANSFER_STAGES:
        return None

    evidence: list[dict[str, Any]] = []
    for item in raw.get("evidence", []):
        if not isinstance(item, dict):
            continue
        claim = str(item.get("claim", "")).strip()
        source_url = str(item.get("source_url", "")).strip()
        observed = parsed_timestamp(item.get("observed_at"))
        authority = str(item.get("source_authority", ""))
        if (
            not claim
            or len(claim) > 360
            or authority not in SOURCE_AUTHORITY
            or not _source_url_is_grounded(source_url, grounded_urls)
            or observed is None
            or observed > now + timedelta(days=1)
            or observed < now - timedelta(days=31)
        ):
            continue
        evidence.append(
            {
                "claim": claim,
                "source_url": source_url,
                "observed_at": iso_timestamp(observed),
                "source_authority": authority,
            }
        )
    if not evidence:
        return None

    strongest = max(SOURCE_AUTHORITY[item["source_authority"]] for item in evidence)
    official = strongest >= 6
    independent_hosts = {urlparse(item["source_url"]).netloc for item in evidence}
    contradiction = bool(raw.get("contradiction"))
    if stage == "official" and not official:
        stage = "agreement"
    status = (
        "confirmed"
        if stage == "official" and official and not contradiction
        else "advanced"
        if stage in {"agreement", "medical", "official"}
        else "rumour"
    )
    confidence = (
        "high"
        if official and not contradiction
        else "medium"
        if strongest >= 4 or len(independent_hosts) >= 2
        else "low"
    )
    if contradiction:
        status = "rumour"
        confidence = "low"

    current_club = str(target["club"])
    from_club = str(raw.get("from_club", "")).strip()
    to_club = str(raw.get("to_club", "")).strip()
    league_destination = any(
        _same_club(to_club, club) for club in competition_clubs
    )
    if _same_club(to_club, current_club):
        direction = "in"
    elif _same_club(from_club, current_club):
        direction = "within_competition" if league_destination else "out"
    else:
        return None

    deal_type = str(raw.get("deal_type", "unknown"))
    if deal_type not in DEAL_TYPES:
        deal_type = "unknown"
    loan_intent = str(raw.get("loan_intent", "unclear"))
    if loan_intent not in LOAN_INTENTS or deal_type != "loan":
        loan_intent = "unclear"
    parent_level = str(raw.get("parent_club_level", "unknown"))
    if parent_level not in PARENT_CLUB_LEVELS or deal_type != "loan":
        parent_level = "unknown"

    requested_probability = optional_float(raw.get("probability")) or 0.0
    stage_bounds = {
        "rumour": (5.0, 45.0),
        "contact": (15.0, 55.0),
        "negotiation": (30.0, 70.0),
        "agreement": (65.0, 90.0),
        "medical": (78.0, 96.0),
        "official": (100.0, 100.0),
    }
    lower, upper = stage_bounds[stage]
    probability = max(lower, min(upper, requested_probability))
    observed_at = max(parsed_timestamp(item["observed_at"]) for item in evidence)
    assert observed_at is not None
    refresh_hours = 6 if status in {"advanced", "confirmed"} else 12
    expires_at = observed_at + timedelta(days=31)
    if expires_at <= now + timedelta(minutes=1):
        return None
    refresh_after = min(
        now + timedelta(hours=refresh_hours),
        expires_at - timedelta(minutes=1),
    )
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "prompt": PROMPT_VERSION,
                "model": model,
                "target": target,
                "status": status,
                "evidence": evidence,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "model_version": MODEL_VERSION,
        "prompt_version": PROMPT_VERSION,
        "research_model": model,
        "research_fingerprint": fingerprint,
        "status": status,
        "stage": stage,
        "direction": direction,
        "from_club": from_club,
        "to_club": to_club,
        "deal_type": deal_type,
        "loan_intent": loan_intent,
        "parent_club_level": parent_level,
        "probability": round(probability, 2),
        "confidence": confidence,
        "contradiction": contradiction,
        "observed_at": iso_timestamp(observed_at),
        "refresh_after": iso_timestamp(refresh_after),
        "expires_at": iso_timestamp(expires_at),
        "fresh": observed_at <= now < expires_at,
        "evidence": evidence,
        "note": str(raw.get("note", "")).strip()[:500],
    }


def _cache_record(
    target: dict[str, Any],
    *,
    now: datetime,
    model: str,
    status: str,
    reason: str = "",
) -> dict[str, Any]:
    refresh_after = (
        now + timedelta(hours=24)
        if status == "no_grounded_transfer_signal"
        else now + timedelta(minutes=5)
    )
    expires_at = (
        now + timedelta(days=7)
        if status == "no_grounded_transfer_signal"
        else now + timedelta(days=2)
    )
    record = {
        "status": status,
        "model_version": MODEL_VERSION,
        "prompt_version": PROMPT_VERSION,
        "research_model": model,
        "checked_at": iso_timestamp(now),
        "refresh_after": iso_timestamp(refresh_after),
        "expires_at": iso_timestamp(expires_at),
    }
    if reason:
        record["reason"] = str(reason)[:160]
    record["research_fingerprint"] = hashlib.sha256(
        json.dumps(
            {"target": target, **record},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return record


def _reusable(value: Any, *, now: datetime, model: str) -> bool:
    if (
        not isinstance(value, dict)
        or value.get("model_version") != MODEL_VERSION
        or value.get("prompt_version") != PROMPT_VERSION
        or value.get("research_model") != model
    ):
        return False
    refresh_after = parsed_timestamp(value.get("refresh_after"))
    expires_at = parsed_timestamp(value.get("expires_at"))
    return bool(refresh_after and expires_at and now < refresh_after and now < expires_at)


def chunks(
    values: list[dict[str, Any]],
    size: int,
) -> Iterable[list[dict[str, Any]]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


def research_transfer_reports(
    targets: list[dict[str, Any]],
    *,
    competition: str,
    season: str,
    competition_clubs: set[str],
    previous_reports: dict[str, Any] | None,
    previous_abstentions: dict[str, Any] | None,
    api_key: str,
    model: str = DEFAULT_MODEL,
    now: datetime | None = None,
    batch_size: int = 8,
    max_workers: int = 4,
    requester: Callable[..., dict[str, Any]] = request_openai,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    previous = previous_reports if isinstance(previous_reports, dict) else {}
    previous_empty = (
        previous_abstentions if isinstance(previous_abstentions, dict) else {}
    )
    reports: dict[str, dict[str, Any]] = {}
    abstentions: dict[str, dict[str, Any]] = {}
    pending: list[dict[str, Any]] = []
    for target in targets:
        player_id = str(target["player_id"])
        if _reusable(previous.get(player_id), now=current, model=model):
            reports[player_id] = dict(previous[player_id])
        elif _reusable(previous_empty.get(player_id), now=current, model=model):
            abstentions[player_id] = dict(previous_empty[player_id])
        else:
            pending.append(target)

    def research_batch(
        batch: list[dict[str, Any]],
    ) -> tuple[
        dict[str, dict[str, Any]],
        dict[str, dict[str, Any]],
        str,
        int,
        int,
        int,
    ]:
        batch_reports: dict[str, dict[str, Any]] = {}
        batch_abstentions: dict[str, dict[str, Any]] = {}
        completed: set[str] = set()
        raw_by_id: dict[str, Any] = {}
        failure = ""
        researched_count = no_signal_count = inconclusive_count = 0
        try:
            response = requester(
                build_request(
                    batch,
                    competition=competition,
                    season=season,
                    model=model,
                    current_date=current.date().isoformat(),
                ),
                api_key=api_key,
            )
            grounded_urls = response_source_urls(response)
            payload = json.loads(response_output_text(response))
            raw_by_id = {
                str(item.get("player_id", "")): item
                for item in payload.get("reports", [])
                if isinstance(item, dict)
            }
            for target in batch:
                player_id = str(target["player_id"])
                raw = raw_by_id.get(player_id)
                if isinstance(raw, dict) and not raw.get("has_transfer_signal"):
                    batch_abstentions[player_id] = _cache_record(
                        target,
                        now=current,
                        model=model,
                        status="no_grounded_transfer_signal",
                    )
                    completed.add(player_id)
                    no_signal_count += 1
                    continue
                normalized = normalize_report(
                    raw,
                    target=target,
                    competition_clubs=competition_clubs,
                    grounded_urls=grounded_urls,
                    now=current,
                    model=model,
                )
                if normalized:
                    batch_reports[player_id] = normalized
                    completed.add(player_id)
                    researched_count += 1
        except (RuntimeError, json.JSONDecodeError, TypeError, ValueError) as error:
            failure = str(error)[:240]
        for target in batch:
            player_id = str(target["player_id"])
            if player_id in completed:
                continue
            if _reusable(previous.get(player_id), now=current, model=model):
                batch_reports[player_id] = dict(previous[player_id])
                continue
            reason = (
                f"request_failed: {failure}"
                if failure
                else "omitted_from_model_output"
                if player_id not in raw_by_id
                else "invalid_or_ungrounded_output"
            )
            batch_abstentions[player_id] = _cache_record(
                target,
                now=current,
                model=model,
                status="research_inconclusive",
                reason=reason,
            )
            inconclusive_count += 1
        return (
            batch_reports,
            batch_abstentions,
            failure,
            researched_count,
            no_signal_count,
            inconclusive_count,
        )

    failures: list[str] = []
    requests = researched = no_signal = inconclusive = 0
    pending_batches = list(chunks(pending, max(1, min(8, batch_size))))
    worker_count = max(1, min(8, max_workers, len(pending_batches) or 1))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        for (
            batch_reports,
            batch_abstentions,
            failure,
            researched_count,
            no_signal_count,
            inconclusive_count,
        ) in executor.map(research_batch, pending_batches):
            requests += 1
            researched += researched_count
            no_signal += no_signal_count
            inconclusive += inconclusive_count
            reports.update(batch_reports)
            abstentions.update(batch_abstentions)
            if failure:
                failures.append(failure)

    return reports, abstentions, {
        "status": (
            "ok"
            if not failures and not inconclusive
            else "partial"
            if reports or abstentions
            else "unavailable"
        ),
        "model": model,
        "model_version": MODEL_VERSION,
        "prompt_version": PROMPT_VERSION,
        "targets": len(targets),
        "cache_hits": len(targets) - len(pending),
        "workers": worker_count,
        "researched_reports": researched,
        "researched_abstentions": no_signal,
        "researched_inconclusive": inconclusive,
        "requests": requests,
        "failures": failures[:5],
    }
