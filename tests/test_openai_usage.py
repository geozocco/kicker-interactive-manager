from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIRECTORY = (
    REPOSITORY_ROOT
    / "plugins"
    / "kicker-interactive-manager"
    / "skills"
    / "build-kicker-interactive-squad"
    / "scripts"
)
sys.path.insert(0, str(SCRIPT_DIRECTORY))

from openai_usage import empty_usage, merge_usage, response_usage


class OpenAIUsageTests(unittest.TestCase):
    def test_usage_counts_cache_and_web_search_cost(self) -> None:
        usage = response_usage(
            {
                "usage": {
                    "input_tokens": 2_000,
                    "input_tokens_details": {
                        "cached_tokens": 1_000,
                        "cache_write_tokens": 500,
                    },
                    "output_tokens": 500,
                    "output_tokens_details": {"reasoning_tokens": 100},
                    "total_tokens": 2_500,
                },
                "output": [
                    {"type": "web_search_call"},
                    {"type": "web_search_call"},
                    {"type": "message"},
                ],
            },
            model="gpt-5.6-luna",
        )
        self.assertEqual(2, usage["web_search_calls"])
        self.assertEqual(1_000, usage["cached_input_tokens"])
        self.assertEqual(500, usage["cache_write_tokens"])
        self.assertEqual(0.020845, usage["estimated_total_cost_usd"])

    def test_usage_aggregation_reprices_total(self) -> None:
        total = empty_usage("gpt-5.6-luna")
        first = response_usage(
            {
                "usage": {"input_tokens": 1_000, "output_tokens": 100},
                "output": [{"type": "web_search_call"}],
            },
            model="gpt-5.6-luna",
        )
        merge_usage(total, first)
        merge_usage(total, first)
        self.assertEqual(2, total["responses"])
        self.assertEqual(2, total["web_search_calls"])
        self.assertEqual(0.02064, total["estimated_total_cost_usd"])


if __name__ == "__main__":
    unittest.main()
