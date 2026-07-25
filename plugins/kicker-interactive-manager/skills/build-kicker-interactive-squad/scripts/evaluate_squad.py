#!/usr/bin/env python3
"""Evaluate a visible Kicker Interactive squad without changing the browser."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

import optimize_squad as optimizer
from news_snapshot import NewsSnapshotError, load_snapshot


def load_roster(path: Path) -> list[Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    entries = payload.get("players", payload.get("squad", payload))
    if not isinstance(entries, list):
        raise ValueError("roster JSON must contain a list named 'players' or 'squad'")
    return entries


def resolve_roster(
    entries: list[Any],
    players: list[optimizer.Player],
) -> tuple[list[optimizer.Player], list[str]]:
    by_id = {player.player_id: player for player in players}
    selected: list[optimizer.Player] = []
    errors: list[str] = []
    selected_ids: set[str] = set()
    for index, raw_entry in enumerate(entries):
        if isinstance(raw_entry, str):
            entry = {"id": raw_entry, "name": raw_entry}
        elif isinstance(raw_entry, dict):
            entry = raw_entry
        else:
            errors.append(f"roster entry {index + 1} is neither text nor an object")
            continue

        requested_id = str(
            entry.get("id") or entry.get("player_id") or ""
        ).strip()
        candidate = by_id.get(requested_id)
        if candidate is not None and isinstance(raw_entry, dict):
            mismatches: list[str] = []
            requested_name = str(entry.get("name", "")).strip()
            if (
                requested_name
                and optimizer.player_name_match_score(
                    requested_name,
                    candidate.name,
                )
                < 2
            ):
                mismatches.append("name")
            requested_club = str(entry.get("club", "")).strip()
            if (
                requested_club
                and not optimizer.clubs_match(
                    requested_club,
                    candidate.club,
                )
            ):
                mismatches.append("club")
            requested_position = str(
                entry.get("position", "")
            ).upper().strip()
            if requested_position and requested_position != candidate.position:
                mismatches.append("position")
            requested_cost = entry.get("cost")
            if requested_cost not in (None, ""):
                try:
                    if int(requested_cost) != candidate.cost:
                        mismatches.append("cost")
                except (TypeError, ValueError):
                    mismatches.append("cost")
            if mismatches:
                errors.append(
                    f"Kicker ID {requested_id!r} conflicts with visible "
                    f"{', '.join(mismatches)}"
                )
                continue
        if candidate is None:
            requested_name = str(entry.get("name", "")).strip()
            candidates = [
                player
                for player in players
                if (
                    requested_name
                    and optimizer.player_name_match_score(
                        requested_name,
                        player.name,
                    )
                    >= 2
                )
            ]
            requested_club = str(entry.get("club", "")).strip()
            if requested_club:
                candidates = [
                    player
                    for player in candidates
                    if optimizer.clubs_match(requested_club, player.club)
                ]
            requested_position = str(entry.get("position", "")).upper().strip()
            if requested_position:
                candidates = [
                    player
                    for player in candidates
                    if player.position == requested_position
                ]
            requested_cost = entry.get("cost")
            if requested_cost not in (None, ""):
                try:
                    expected_cost = int(requested_cost)
                except (TypeError, ValueError):
                    errors.append(
                        f"roster entry {index + 1} has an invalid cost"
                    )
                    continue
                candidates = [
                    player for player in candidates if player.cost == expected_cost
                ]
            if len(candidates) == 1:
                candidate = candidates[0]
            elif not candidates:
                label = requested_name or requested_id or f"entry {index + 1}"
                errors.append(f"no official Kicker player matches {label!r}")
                continue
            else:
                errors.append(
                    f"multiple official Kicker players match {requested_name!r}; "
                    "include club, position and cost"
                )
                continue

        if candidate.player_id in selected_ids:
            errors.append(f"duplicate roster player: {candidate.name}")
            continue
        selected_ids.add(candidate.player_id)
        selected.append(candidate)
    return selected, errors


def evidence_age_days(player: optimizer.Player, today: date) -> int | None:
    checked_dates: list[date] = []
    for item in player.evidence:
        if not isinstance(item, dict):
            continue
        raw_checked_at = str(item.get("checked_at", "")).strip()
        if not raw_checked_at:
            continue
        try:
            checked_dates.append(
                datetime.fromisoformat(
                    raw_checked_at.replace("Z", "+00:00")
                ).date()
            )
        except ValueError:
            try:
                checked_dates.append(date.fromisoformat(raw_checked_at[:10]))
            except ValueError:
                continue
    if not checked_dates:
        return None
    latest = max(checked_dates)
    if latest > today:
        return None
    return (today - latest).days


def compact_player(
    player: optimizer.Player,
    scores: dict[str, float],
    core_ids: frozenset[str],
) -> dict[str, Any]:
    return {
        "id": player.player_id,
        "name": player.name,
        "club": player.club,
        "position": player.position,
        "cost": player.cost,
        "score": round(scores[player.player_id], 3),
        "selection_role": (
            "core" if player.player_id in core_ids else "bench"
        ),
        "reliable_anchor": player.reliable_anchor,
        "risks": {
            key: round(player.risks[key], 1) for key in optimizer.RISKS
        },
        "fitness": round(player.components["fitness"], 1),
        "note": player.note,
        "evidence": list(player.evidence),
    }


def add_alert(
    alerts: list[dict[str, Any]],
    severity: str,
    category: str,
    message: str,
    player: optimizer.Player | None = None,
    evidence: list[Any] | tuple[Any, ...] = (),
) -> None:
    alert: dict[str, Any] = {
        "severity": severity,
        "category": category,
        "message": message,
    }
    if player is not None:
        alert.update(
            {
                "player_id": player.player_id,
                "player": player.name,
            }
        )
    if evidence:
        alert["evidence"] = list(evidence)
    alerts.append(alert)


def rating_label(rating: float | None) -> str:
    if rating is None:
        return "Keine belastbare Bewertung"
    if rating >= 80:
        return "Sehr gut"
    if rating >= 70:
        return "Gut"
    if rating >= 60:
        return "Solide"
    if rating >= 50:
        return "Riskant"
    return "Kritisch"


def evaluate(
    *,
    selected: list[optimizer.Player],
    candidate_pool: list[optimizer.Player],
    scores: dict[str, float],
    slots: dict[str, int],
    budget: int,
    profile: str,
    maintenance: str,
    club_cap: int,
    news_audit: dict[str, Any],
    news_exclusions: list[dict[str, Any]],
    annotation_excluded_ids: set[str],
    resolution_errors: list[str],
    require_news_coverage: bool,
    max_evidence_age_days: int,
    today: date,
) -> dict[str, Any]:
    alerts: list[dict[str, Any]] = []
    strengths: list[str] = []
    selected_ids = {player.player_id for player in selected}
    expected_count = sum(slots.values())
    position_counts = Counter(player.position for player in selected)
    roster_valid = True

    for error in resolution_errors:
        roster_valid = False
        add_alert(alerts, "critical", "roster_identity", error)
    if len(selected) != expected_count:
        roster_valid = False
        add_alert(
            alerts,
            "critical",
            "roster_size",
            f"Kader enthält {len(selected)} statt {expected_count} Spieler.",
        )
    for position, required in slots.items():
        actual = position_counts.get(position, 0)
        if actual != required:
            roster_valid = False
            add_alert(
                alerts,
                "critical",
                "position_count",
                f"{position}: {actual} statt {required} Spieler.",
            )
    total_cost = sum(player.cost for player in selected)
    remaining_budget = budget - total_cost
    if remaining_budget < 0:
        roster_valid = False
        add_alert(
            alerts,
            "critical",
            "budget",
            f"Der Kader überschreitet das Budget um {-remaining_budget}.",
        )

    goalkeeper_clubs = {
        player.club
        for player in selected
        if player.position == "GOALKEEPER"
    }
    if len(goalkeeper_clubs) == 1 and position_counts.get("GOALKEEPER", 0):
        selected_goalkeepers = [
            player
            for player in selected
            if player.position == "GOALKEEPER"
        ]
        if any(
            player.goalkeeper_outlook
            for player in selected_goalkeepers
        ):
            allowed, reasons, primary = (
                optimizer.goalkeeper_block_assessment(
                    selected_goalkeepers,
                    scores,
                    maintenance,
                    require_hierarchy=True,
                )
            )
            if allowed:
                probability = float(
                    primary.goalkeeper_outlook["starter_probability"]
                )
                strengths.append(
                    "Vollständiger Torwartblock mit "
                    f"{primary.name} als belastbarer Nummer eins "
                    f"({probability:.0f}% Saisonprognose)."
                )
            else:
                add_alert(
                    alerts,
                    "high" if maintenance == "low" else "medium",
                    "goalkeeper_hierarchy",
                    "Der Torwartblock ist vollständig, aber die Nummer eins "
                    "ist nicht ausreichend abgesichert: "
                    + "; ".join(reasons)
                    + ".",
                )
        else:
            strengths.append("Vollständiger Torwartblock aus einem Verein.")
    elif len(goalkeeper_clubs) > 1:
        add_alert(
            alerts,
            "medium",
            "goalkeeper_block",
            "Die Torhüter stammen aus mehreren Vereinen und sichern Ausfälle "
            "dadurch meist schlechter ab.",
        )

    outfield_counts = Counter(
        player.club
        for player in selected
        if player.position != "GOALKEEPER"
    )
    overloaded = {
        club: count for club, count in outfield_counts.items() if count > club_cap
    }
    for club, count in overloaded.items():
        add_alert(
            alerts,
            "medium",
            "club_concentration",
            f"{count} Feldspieler von {club} bündeln Form-, Trainer- und "
            "Spielausfallrisiko.",
        )
    if not overloaded:
        strengths.append("Keine übermäßige Häufung von Feldspielern eines Vereins.")

    stale_or_missing = []
    for player in selected:
        age = evidence_age_days(player, today)
        if not player.researched or age is None or age > max_evidence_age_days:
            stale_or_missing.append(player)
    for player in stale_or_missing:
        add_alert(
            alerts,
            "critical",
            "research_coverage",
            "Rolle, Fitness und Transferlage sind nicht aktuell genug belegt.",
            player,
            player.evidence,
        )

    conflicts = news_audit.get("conflicts", {})
    if not isinstance(conflicts, dict):
        conflicts = {}
    for player in selected:
        reasons = conflicts.get(player.player_id)
        if reasons:
            add_alert(
                alerts,
                "critical",
                "news_conflict",
                "Widersprüchliche News- oder Identitätsdaten: "
                + "; ".join(str(reason) for reason in reasons),
                player,
                player.evidence,
            )

    mapped_ids = set(news_audit.get("provider_mapped_player_ids", []))
    missing_news_coverage = (
        sorted(selected_ids - mapped_ids)
        if require_news_coverage
        else []
    )
    for player in selected:
        if player.player_id in missing_news_coverage:
            add_alert(
                alerts,
                "critical",
                "news_coverage",
                "Keine verifizierte Provider-Zuordnung; vor einer Bestätigung "
                "manuell in aktuellen Primärquellen prüfen.",
                player,
            )

    excluded_names = {
        str(item.get("player", "")).strip()
        for item in news_exclusions
        if isinstance(item, dict)
    }
    excluded_ids = {
        str(item.get("annotation_key", "")).strip()
        for item in news_exclusions
        if isinstance(item, dict)
    } | annotation_excluded_ids
    for player in selected:
        if player.player_id in excluded_ids or player.name in excluded_names:
            matching_evidence = [
                evidence
                for item in news_exclusions
                if isinstance(item, dict)
                and (
                    item.get("annotation_key") == player.player_id
                    or item.get("player") == player.name
                )
                for evidence in item.get("evidence", [])
            ]
            add_alert(
                alerts,
                "critical",
                "unavailable",
                "Aktuell bestätigter Ausschluss, Abgang oder Nichtverfügbarkeit.",
                player,
                matching_evidence or player.evidence,
            )

    for player in selected:
        if player.risks["injury"] >= 60 or player.components["fitness"] < 50:
            add_alert(
                alerts,
                "high",
                "injury",
                f"Erhöhtes Verletzungs-/Fitnessrisiko "
                f"({player.risks['injury']:.0f}/100, "
                f"Fitness {player.components['fitness']:.0f}/100).",
                player,
                player.evidence,
            )
        elif player.risks["injury"] >= 40 or player.components["fitness"] < 65:
            add_alert(
                alerts,
                "medium",
                "injury",
                "Fitness oder Verletzungsrisiko sollte vor dem Spieltag "
                "noch einmal geprüft werden.",
                player,
                player.evidence,
            )
        if player.risks["transfer"] >= 60:
            add_alert(
                alerts,
                "high",
                "transfer",
                f"Hohes aktuelles Wechselrisiko "
                f"({player.risks['transfer']:.0f}/100).",
                player,
                player.evidence,
            )
        elif player.risks["transfer"] >= 40:
            add_alert(
                alerts,
                "medium",
                "transfer",
                "Offene Transfersituation kann Rolle oder Verfügbarkeit ändern.",
                player,
                player.evidence,
            )
        if (
            player.risks["rotation"] >= 60
            or player.risks["unknown_role"] >= 60
        ):
            add_alert(
                alerts,
                "high",
                "role",
                "Hohes Startelf- oder Rollenrisiko.",
                player,
                player.evidence,
            )
        elif (
            player.risks["rotation"] >= 45
            or player.risks["unknown_role"] >= 45
        ):
            add_alert(
                alerts,
                "medium",
                "role",
                "Einsatz- oder Rollenrisiko ist noch nicht vollständig geklärt.",
                player,
                player.evidence,
            )

    squad = optimizer.Squad(
        selected,
        sum(scores[player.player_id] for player in selected),
    )
    min_anchors = 4 if profile == "reliable" else 0
    min_attacking_anchors = 3 if profile == "reliable" else 0
    min_core_share = (
        0.70 if profile == "reliable" and maintenance == "low" else 0.0
    )
    core_audit = optimizer.reliable_core_audit(
        squad,
        scores,
        min_anchors,
        min_attacking_anchors,
        min_core_share,
    )
    core_ids = frozenset(core_audit["player_ids"])
    core_budget_share = float(core_audit["core_budget_share"])
    if min_anchors and core_audit["reliable_anchors"] < min_anchors:
        add_alert(
            alerts,
            "high",
            "anchors",
            f"Die stärkste Startelf enthält nur "
            f"{core_audit['reliable_anchors']} von {min_anchors} "
            "mehrjährig bestätigten Ankern.",
        )
    elif min_anchors:
        strengths.append(
            f"{core_audit['reliable_anchors']} bestätigte Anker in der "
            "stärksten Startelf."
        )
    if (
        min_attacking_anchors
        and core_audit["attacking_anchors"] < min_attacking_anchors
    ):
        add_alert(
            alerts,
            "high",
            "attacking_anchors",
            f"Nur {core_audit['attacking_anchors']} von "
            f"{min_attacking_anchors} geforderten Ankern stehen in "
            "Mittelfeld oder Sturm.",
        )
    if core_budget_share < min_core_share:
        add_alert(
            alerts,
            "high",
            "budget_architecture",
            f"Nur {core_budget_share:.1%} des Kaderwerts stecken in der "
            f"stärksten Startelf; Ziel sind mindestens {min_core_share:.0%}.",
        )
    elif min_core_share:
        strengths.append(
            f"{core_budget_share:.1%} des Kaderwerts finanzieren die "
            "stärkste Startelf."
        )
    if budget > 0 and remaining_budget > budget * 0.10:
        add_alert(
            alerts,
            "medium",
            "unused_budget",
            f"{remaining_budget / budget:.1%} des Budgets bleiben ungenutzt.",
        )

    available_ids = {
        player.player_id for player in candidate_pool
    } - excluded_ids
    safe_candidates = [
        player
        for player in candidate_pool
        if (
            player.researched
            and player.player_id in available_ids
            and player.player_id not in selected_ids
            and player.components["fitness"] >= 50
            and player.risks["injury"] < 60
            and player.risks["transfer"] < 60
            and player.risks["rotation"] < 60
            and player.player_id not in conflicts
            and (
                not require_news_coverage
                or player.player_id in mapped_ids
            )
        )
    ]
    alternatives: list[dict[str, Any]] = []
    used_alternatives: set[str] = set()
    weakest_first = sorted(
        selected,
        key=lambda player: (
            scores[player.player_id],
            -player.cost,
            player.name,
        ),
    )
    for current in weakest_first:
        affordable = [
            candidate
            for candidate in safe_candidates
            if (
                candidate.position == current.position
                and candidate.player_id not in used_alternatives
                and candidate.cost <= current.cost + max(remaining_budget, 0)
                and scores[candidate.player_id]
                >= scores[current.player_id] + 3.0
            )
        ]
        if not affordable:
            continue
        alternative = max(
            affordable,
            key=lambda candidate: (
                scores[candidate.player_id] - scores[current.player_id],
                -candidate.cost,
                candidate.name,
            ),
        )
        used_alternatives.add(alternative.player_id)
        alternatives.append(
            {
                "replace": {
                    "id": current.player_id,
                    "name": current.name,
                    "cost": current.cost,
                    "score": round(scores[current.player_id], 3),
                },
                "with": {
                    "id": alternative.player_id,
                    "name": alternative.name,
                    "club": alternative.club,
                    "cost": alternative.cost,
                    "score": round(scores[alternative.player_id], 3),
                },
                "cost_delta": alternative.cost - current.cost,
                "score_delta": round(
                    scores[alternative.player_id] - scores[current.player_id],
                    3,
                ),
                "reason": (
                    "Bezahlbare Ein-zu-eins-Alternative im aktuell "
                    "recherchierten Kandidatenpool."
                ),
            }
        )
        if len(alternatives) >= 5:
            break

    data_blockers = [
        alert
        for alert in alerts
        if (
            alert["severity"] == "critical"
            and alert["category"]
            in {
                "research_coverage",
                "news_coverage",
                "news_conflict",
                "roster_identity",
            }
        )
    ]
    severity_penalty = {
        "critical": 12.0,
        "high": 6.0,
        "medium": 2.5,
        "low": 1.0,
    }
    base_rating = (
        sum(scores[player.player_id] for player in selected) / len(selected)
        if selected
        else 0.0
    )
    calculated_rating = max(
        0.0,
        min(
            100.0,
            base_rating
            - sum(
                severity_penalty.get(alert["severity"], 0.0)
                for alert in alerts
            ),
        ),
    )
    rating: float | None = (
        None if data_blockers else round(calculated_rating, 1)
    )
    critical_count = sum(
        alert["severity"] == "critical" for alert in alerts
    )
    high_count = sum(alert["severity"] == "high" for alert in alerts)
    avoidable_error_free = (
        roster_valid
        and not data_blockers
        and critical_count == 0
        and high_count == 0
    )
    if data_blockers:
        status = "blocked"
    elif critical_count:
        status = "critical"
    elif high_count:
        status = "attention"
    else:
        status = "ready"
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    alerts.sort(
        key=lambda item: (
            severity_order.get(item["severity"], 9),
            item["category"],
            item.get("player", ""),
        )
    )
    bench_players = [
        player for player in selected if player.player_id not in core_ids
    ]
    return {
        "mode": "evaluate_current_squad",
        "status": status,
        "avoidable_error_free": avoidable_error_free,
        "rating": rating,
        "rating_label": rating_label(rating),
        "confidence": "limited" if data_blockers else "high",
        "scope": (
            "Current visible squad and currently researched candidate pool; "
            "no Chrome changes performed."
        ),
        "profile": profile,
        "maintenance": maintenance,
        "roster": {
            "valid": roster_valid,
            "players": len(selected),
            "expected_players": expected_count,
            "positions": {
                position: position_counts.get(position, 0)
                for position in slots
            },
            "expected_positions": slots,
            "cost": total_cost,
            "budget": budget,
            "remaining_budget": remaining_budget,
        },
        "starting_lineup": {
            "formation": core_audit["formation"],
            "player_ids": sorted(core_ids),
            "budget": core_audit["core_budget"],
            "budget_share_percent": round(100.0 * core_budget_share, 1),
            "reliable_anchors": core_audit["reliable_anchors"],
            "attacking_anchors": core_audit["attacking_anchors"],
        },
        "bench": {
            "players": len(bench_players),
            "cost": sum(player.cost for player in bench_players),
            "budget_share_percent": round(
                100.0
                * sum(player.cost for player in bench_players)
                / max(total_cost, 1),
                1,
            ),
        },
        "strengths": strengths,
        "alerts": alerts,
        "alternatives": alternatives,
        "news_audit": {
            **news_audit,
            "selected_provider_coverage": (
                len(selected_ids & mapped_ids)
                if require_news_coverage
                else None
            ),
            "selected_players": len(selected_ids),
            "selected_missing_provider_ids": missing_news_coverage,
        },
        "players": [
            compact_player(player, scores, core_ids)
            for player in sorted(
                selected,
                key=lambda player: (
                    optimizer.POSITION_ORDER[player.position],
                    player.name,
                ),
            )
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    player_source = parser.add_mutually_exclusive_group()
    player_source.add_argument("--players", type=Path)
    player_source.add_argument(
        "--market-snapshot",
        default=os.environ.get("KICKER_MARKET_FEED_URL"),
    )
    parser.add_argument(
        "--market-token-env",
        default="KICKER_MARKET_FEED_TOKEN",
    )
    parser.add_argument("--require-market-snapshot", action="store_true")
    parser.add_argument("--roster", type=Path, required=True)
    parser.add_argument("--annotations", type=Path)
    parser.add_argument(
        "--quality-snapshot",
        default=os.environ.get("KICKER_QUALITY_FEED_URL"),
    )
    parser.add_argument(
        "--quality-token-env",
        default="KICKER_QUALITY_FEED_TOKEN",
    )
    parser.add_argument("--require-quality-snapshot", action="store_true")
    parser.add_argument(
        "--competition",
        choices=("Bundesliga", "2. Bundesliga", "3. Liga"),
        required=True,
    )
    parser.add_argument("--season", required=True)
    parser.add_argument(
        "--news-snapshot",
        default=os.environ.get("KICKER_NEWS_FEED_URL"),
    )
    parser.add_argument(
        "--news-token-env",
        default="KICKER_NEWS_FEED_TOKEN",
    )
    parser.add_argument("--require-news-snapshot", action="store_true")
    parser.add_argument("--require-news-coverage", action="store_true")
    parser.add_argument("--budget", type=int, required=True)
    parser.add_argument("--goalkeepers", type=int, default=3)
    parser.add_argument("--defenders", type=int, default=7)
    parser.add_argument("--midfielders", type=int, default=7)
    parser.add_argument("--forwards", type=int, default=5)
    parser.add_argument(
        "--profile",
        default="reliable",
        choices=sorted(optimizer.PROFILE_ALIASES),
    )
    parser.add_argument(
        "--maintenance",
        default="low",
        choices=sorted(optimizer.MAINTENANCE_ALIASES),
    )
    parser.add_argument("--max-outfield-per-club", type=int)
    parser.add_argument("--max-evidence-age-days", type=int, default=1)
    parser.add_argument("--format", choices=("json", "text"), default="json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    args.profile = optimizer.PROFILE_ALIASES[args.profile]
    args.maintenance = optimizer.MAINTENANCE_ALIASES[args.maintenance]
    if args.max_outfield_per_club is None:
        args.max_outfield_per_club = optimizer.DEFAULT_CLUB_CAP[args.profile]
    if args.budget <= 0:
        parser.error("--budget must be positive")
    if args.max_evidence_age_days < 0:
        parser.error("--max-evidence-age-days cannot be negative")
    args.slots = {
        "GOALKEEPER": args.goalkeepers,
        "DEFENDER": args.defenders,
        "MIDFIELDER": args.midfielders,
        "FORWARD": args.forwards,
    }
    if any(value < 1 for value in args.slots.values()):
        parser.error("all positional slot counts must be positive")
    if not args.news_snapshot:
        args.news_snapshot = optimizer.DEFAULT_NEWS_FEEDS.get(
            (args.competition, args.season)
        )
    if not args.players and not args.market_snapshot:
        args.market_snapshot = optimizer.DEFAULT_MARKET_FEEDS.get(
            (args.competition, args.season)
        )
    if not args.players and not args.quality_snapshot:
        args.quality_snapshot = optimizer.DEFAULT_QUALITY_FEEDS.get(
            (args.competition, args.season)
        )
    if not args.players and not args.market_snapshot:
        parser.error(
            "set --players or use a competition and season with a configured "
            "central market"
        )
    if args.players and args.market_snapshot:
        parser.error("--players and --market-snapshot cannot be combined")
    if args.require_market_snapshot and not args.market_snapshot:
        parser.error(
            "--require-market-snapshot cannot be used with only a local CSV"
        )
    if args.require_quality_snapshot and not args.quality_snapshot:
        parser.error("--require-quality-snapshot needs a quality snapshot")
    if args.players and args.quality_snapshot:
        parser.error(
            "--quality-snapshot can only be combined with --market-snapshot"
        )
    return args


def render_text(payload: dict[str, Any]) -> str:
    rating = (
        "nicht belastbar"
        if payload["rating"] is None
        else f"{payload['rating']:.1f}/100 ({payload['rating_label']})"
    )
    lines = [
        f"Kaderbewertung: {rating}",
        f"Status: {payload['status']}",
        (
            "Keine vermeidbaren Fehler erkannt."
            if payload["avoidable_error_free"]
            else "Vor einer Bestätigung sind die folgenden Punkte zu prüfen."
        ),
    ]
    for alert in payload["alerts"]:
        player = f" – {alert['player']}" if alert.get("player") else ""
        lines.append(
            f"- {alert['severity'].upper()} {alert['category']}{player}: "
            f"{alert['message']}"
        )
    if payload["alternatives"]:
        lines.append("Bezahlbare Alternativen:")
        for alternative in payload["alternatives"]:
            lines.append(
                f"- {alternative['replace']['name']} -> "
                f"{alternative['with']['name']} "
                f"(Score {alternative['score_delta']:+.1f}, "
                f"Kosten {alternative['cost_delta']:+d})"
            )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    local_annotations = optimizer.load_annotations(args.annotations)
    annotations = local_annotations
    quality_audit: dict[str, Any] = {
        "status": "not_configured",
        "required": bool(args.require_quality_snapshot),
    }
    if args.market_snapshot:
        try:
            market_payload = optimizer.load_market_snapshot(
                args.market_snapshot,
                token_env=args.market_token_env,
            )
            if market_payload["competition"] != args.competition:
                raise optimizer.MarketSnapshotError(
                    "market snapshot competition does not match the visible "
                    "Kicker league"
                )
            if market_payload["season"] != args.season:
                raise optimizer.MarketSnapshotError(
                    "market snapshot season does not match the visible "
                    "Kicker season"
                )
        except (optimizer.MarketSnapshotError, OSError) as error:
            print(
                f"Central market loading stopped squad evaluation: {error}",
                file=sys.stderr,
            )
            return 2
        annotations = dict(market_payload.get("annotations", {}))
        if args.quality_snapshot:
            try:
                quality_payload = optimizer.load_quality_snapshot(
                    args.quality_snapshot,
                    token_env=args.quality_token_env,
                )
                if (
                    quality_payload["competition"]
                    != market_payload["competition"]
                    or quality_payload["season"] != market_payload["season"]
                ):
                    raise optimizer.QualitySnapshotError(
                        "quality snapshot competition or season does not match"
                    )
                if (
                    quality_payload["market_sha256"]
                    != optimizer.market_canonical_sha256(market_payload)
                ):
                    raise optimizer.QualitySnapshotError(
                        "quality snapshot was built for a different market"
                    )
            except (optimizer.QualitySnapshotError, OSError) as error:
                print(
                    f"Central quality loading stopped squad evaluation: {error}",
                    file=sys.stderr,
                )
                return 2
            annotations = optimizer.merge_annotations(
                annotations,
                quality_payload["annotations"],
            )
            quality_audit = optimizer.quality_snapshot_audit(quality_payload)
            quality_audit["required"] = bool(args.require_quality_snapshot)
        elif args.require_quality_snapshot:
            print(
                "Squad evaluation requires a fresh central quality snapshot.",
                file=sys.stderr,
            )
            return 2
        annotations = optimizer.merge_annotations(annotations, local_annotations)
        market_audit = optimizer.market_snapshot_audit(market_payload)
        market_audit["required"] = bool(args.require_market_snapshot)
        players, _, _ = optimizer.load_players_from_rows(
            optimizer.market_csv_rows(market_payload),
            {
                key: {**annotation, "exclude": False}
                for key, annotation in annotations.items()
            },
        )
    else:
        market_audit = {
            "status": "local_csv",
            "required": False,
        }
        players, _, _ = optimizer.load_players(
            args.players,
            {
                key: {**annotation, "exclude": False}
                for key, annotation in annotations.items()
            },
        )
    roster_entries = load_roster(args.roster)
    selected_before_news, resolution_errors = resolve_roster(
        roster_entries,
        players,
    )
    annotation_excluded_ids = {
        player.player_id
        for player in players
        if bool(
            (
                annotations.get(player.player_id)
                or annotations.get(player.name)
                or {}
            ).get("exclude", False)
        )
    }
    news_audit: dict[str, Any] = {
        "status": "not_configured",
        "required": bool(args.require_news_snapshot),
    }
    news_exclusions: list[dict[str, Any]] = []
    updated_players = players
    if args.news_snapshot:
        try:
            news_payload = load_snapshot(
                args.news_snapshot,
                token_env=args.news_token_env,
            )
            if news_payload["competition"] != args.competition:
                raise NewsSnapshotError(
                    "snapshot competition does not match the visible Kicker league"
                )
            if news_payload["season"] != args.season:
                raise NewsSnapshotError(
                    "snapshot season does not match the visible Kicker season"
                )
            updated_players, news_audit, news_exclusions = (
                optimizer.apply_news_snapshot(players, news_payload)
            )
        except (NewsSnapshotError, OSError) as error:
            if args.require_news_snapshot:
                print(
                    f"News hardening stopped squad evaluation: {error}",
                    file=sys.stderr,
                )
                return 2
            news_audit = {
                "status": "unavailable",
                "required": False,
                "error": str(error),
            }
    elif args.require_news_snapshot:
        print(
            "Squad evaluation requires a fresh central news snapshot.",
            file=sys.stderr,
        )
        return 2

    updated_by_id = {
        player.player_id: player for player in updated_players
    }
    selected = [
        updated_by_id.get(player.player_id, player)
        for player in selected_before_news
    ]
    candidate_pool = list(updated_players)
    scores = optimizer.score_players(
        [*candidate_pool, *(
            player
            for player in selected
            if player.player_id not in updated_by_id
        )],
        args.profile,
        args.maintenance,
    )
    payload = evaluate(
        selected=selected,
        candidate_pool=candidate_pool,
        scores=scores,
        slots=args.slots,
        budget=args.budget,
        profile=args.profile,
        maintenance=args.maintenance,
        club_cap=args.max_outfield_per_club,
        news_audit=news_audit,
        news_exclusions=news_exclusions,
        annotation_excluded_ids=annotation_excluded_ids,
        resolution_errors=resolution_errors,
        require_news_coverage=args.require_news_coverage,
        max_evidence_age_days=args.max_evidence_age_days,
        today=datetime.now(timezone.utc).date(),
    )
    payload["market_audit"] = market_audit
    payload["quality_audit"] = quality_audit
    rendered = (
        json.dumps(payload, ensure_ascii=False, indent=2)
        if args.format == "json"
        else render_text(payload)
    )
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
