from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    REPOSITORY_ROOT
    / "plugins"
    / "kicker-interactive-manager"
    / "skills"
    / "build-kicker-interactive-squad"
    / "scripts"
    / "optimize_squad.py"
)
SPEC = importlib.util.spec_from_file_location("bundesliga_optimizer", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load optimize_squad.py")
optimizer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = optimizer
SPEC.loader.exec_module(optimizer)


class BundesligaSupportTests(unittest.TestCase):
    def load_config(self, category: str) -> dict[str, object]:
        return json.loads(
            (REPOSITORY_ROOT / "config" / category / "bundesliga.json").read_text(
                encoding="utf-8"
            )
        )

    def test_bundesliga_has_all_central_feed_defaults(self) -> None:
        key = ("Bundesliga", "2026/27")
        self.assertEqual(
            "https://geozocco.github.io/kicker-interactive-manager/v1/market/bundesliga.json",
            optimizer.DEFAULT_MARKET_FEEDS[key],
        )
        self.assertEqual(
            "https://geozocco.github.io/kicker-interactive-manager/v1/news/bundesliga.json",
            optimizer.DEFAULT_NEWS_FEEDS[key],
        )
        self.assertEqual(
            "https://geozocco.github.io/kicker-interactive-manager/v1/quality/bundesliga.json",
            optimizer.DEFAULT_QUALITY_FEEDS[key],
        )
        self.assertEqual(42_500_000, optimizer.COMPETITION_BUDGETS["Bundesliga"])

    def test_bundesliga_pipeline_configuration_is_complete(self) -> None:
        market = self.load_config("market")
        news = self.load_config("news")
        preseason = self.load_config("preseason")
        history = self.load_config("history")
        quality = self.load_config("quality")

        for config in (market, news, preseason, history, quality):
            self.assertEqual("Bundesliga", config["competition"])
            self.assertEqual("2026/27", config["season"])
        self.assertEqual(
            "https://www.kicker-libero.de/api/sportsdata/v1/players-details/se-k00012026.csv",
            market["source_url"],
        )
        self.assertEqual(18, market["expected_team_count"])
        self.assertEqual(78, news["api_sports"]["league_id"])
        self.assertEqual("2026-08-28", preseason["window"]["season_start"])
        self.assertEqual("L1", history["transfermarkt_competition_id"])
        self.assertEqual(1.0, history["target_strength"])
        self.assertGreaterEqual(quality["minimum_candidates"], 60)
        self.assertGreaterEqual(quality["minimum_goalkeeper_blocks"], 6)

    def test_workflow_publishes_every_bundesliga_snapshot(self) -> None:
        workflow = (
            REPOSITORY_ROOT / ".github" / "workflows" / "update-news-feed.yml"
        ).read_text(encoding="utf-8")
        for relative_path in (
            "market/bundesliga.json",
            "news/bundesliga.json",
            "preseason/bundesliga.json",
            "history/bundesliga.json",
            "kicker-history/bundesliga.json",
            "quality/bundesliga.json",
            "matchday/bundesliga.json",
        ):
            self.assertIn(relative_path, workflow)
        self.assertIn("identities/bundesliga.json", workflow)
        self.assertIn("performance/bundesliga.json.gz", workflow)


if __name__ == "__main__":
    unittest.main()
