from __future__ import annotations

import json
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = (
    REPOSITORY_ROOT
    / "plugins"
    / "kicker-interactive-manager"
    / ".codex-plugin"
    / "plugin.json"
)


class PluginPromptTests(unittest.TestCase):
    def test_three_scannable_starters_cover_help_review_and_setup(self) -> None:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        prompts = manifest["interface"]["defaultPrompt"]

        self.assertEqual(3, len(prompts))
        self.assertTrue(all(1 <= len(prompt) <= 128 for prompt in prompts))
        self.assertIn("Modi und Beispielprompts", prompts[0])
        self.assertIn("Bewerte", prompts[1])
        self.assertIn("verändere nichts", prompts[1])
        self.assertIn("Liga, Strategie, Variabilität", prompts[2])


if __name__ == "__main__":
    unittest.main()
