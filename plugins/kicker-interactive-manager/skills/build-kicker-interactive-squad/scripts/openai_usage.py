#!/usr/bin/env python3
"""Aggregate OpenAI response usage without exposing request contents."""

from __future__ import annotations

from typing import Any


PRICING_VERSION = "2026-08-05"
WEB_SEARCH_USD_PER_CALL = 0.01
MODEL_PRICES_PER_MILLION = {
    "gpt-5.6-sol": {
        "input": 5.0,
        "cached_input": 0.5,
        "cache_write": 6.25,
        "output": 30.0,
    },
    "gpt-5.6-terra": {
        "input": 2.0,
        "cached_input": 0.2,
        "cache_write": 2.5,
        "output": 12.0,
    },
    "gpt-5.6-luna": {
        "input": 0.2,
        "cached_input": 0.02,
        "cache_write": 0.25,
        "output": 1.2,
    },
}


def empty_usage(model: str) -> dict[str, Any]:
    return {
        "model": model,
        "pricing_version": PRICING_VERSION,
        "responses": 0,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "cache_write_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
        "web_search_calls": 0,
        "estimated_token_cost_usd": 0.0,
        "estimated_web_search_cost_usd": 0.0,
        "estimated_total_cost_usd": 0.0,
    }


def response_usage(response: dict[str, Any], *, model: str) -> dict[str, Any]:
    result = empty_usage(model)
    result["responses"] = 1
    usage = response.get("usage", {})
    if not isinstance(usage, dict):
        usage = {}
    input_details = usage.get("input_tokens_details", {})
    if not isinstance(input_details, dict):
        input_details = {}
    output_details = usage.get("output_tokens_details", {})
    if not isinstance(output_details, dict):
        output_details = {}
    result.update(
        {
            "input_tokens": int(usage.get("input_tokens", 0) or 0),
            "cached_input_tokens": int(
                input_details.get("cached_tokens", 0) or 0
            ),
            "cache_write_tokens": int(
                input_details.get("cache_write_tokens", 0) or 0
            ),
            "output_tokens": int(usage.get("output_tokens", 0) or 0),
            "reasoning_tokens": int(
                output_details.get("reasoning_tokens", 0) or 0
            ),
            "total_tokens": int(usage.get("total_tokens", 0) or 0),
            "web_search_calls": sum(
                isinstance(item, dict)
                and item.get("type") == "web_search_call"
                for item in response.get("output", [])
            ),
        }
    )
    _price(result)
    return result


def merge_usage(
    target: dict[str, Any],
    addition: dict[str, Any],
) -> dict[str, Any]:
    for field in (
        "responses",
        "input_tokens",
        "cached_input_tokens",
        "cache_write_tokens",
        "output_tokens",
        "reasoning_tokens",
        "total_tokens",
        "web_search_calls",
    ):
        target[field] = int(target.get(field, 0) or 0) + int(
            addition.get(field, 0) or 0
        )
    _price(target)
    return target


def _price(usage: dict[str, Any]) -> None:
    prices = MODEL_PRICES_PER_MILLION.get(str(usage.get("model", "")))
    if not prices:
        usage["estimated_token_cost_usd"] = None
        usage["estimated_web_search_cost_usd"] = round(
            int(usage.get("web_search_calls", 0) or 0)
            * WEB_SEARCH_USD_PER_CALL,
            6,
        )
        usage["estimated_total_cost_usd"] = None
        return
    input_tokens = int(usage.get("input_tokens", 0) or 0)
    cached = min(
        input_tokens,
        int(usage.get("cached_input_tokens", 0) or 0),
    )
    cache_write = min(
        max(0, input_tokens - cached),
        int(usage.get("cache_write_tokens", 0) or 0),
    )
    uncached = max(0, input_tokens - cached - cache_write)
    token_cost = (
        uncached * prices["input"]
        + cached * prices["cached_input"]
        + cache_write * prices["cache_write"]
        + int(usage.get("output_tokens", 0) or 0) * prices["output"]
    ) / 1_000_000
    web_cost = (
        int(usage.get("web_search_calls", 0) or 0)
        * WEB_SEARCH_USD_PER_CALL
    )
    usage["estimated_token_cost_usd"] = round(token_cost, 6)
    usage["estimated_web_search_cost_usd"] = round(web_cost, 6)
    usage["estimated_total_cost_usd"] = round(token_cost + web_cost, 6)
