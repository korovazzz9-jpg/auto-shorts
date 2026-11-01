"""Independent review requires an actual web search and a supported verdict."""

import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.modules.setdefault("anthropic", types.ModuleType("anthropic"))
sys.modules["anthropic"].Anthropic = lambda **kwargs: None

from fact_review import repair_es_script, verify_es_script


class FakeClient:
    def __init__(self, blocks):
        self.blocks = blocks
        self.messages = self

    def create(self, **kwargs):
        return types.SimpleNamespace(content=self.blocks)


class FactReviewTests(unittest.TestCase):
    def test_rejects_claim_without_search_even_if_model_says_yes(self):
        blocks = [types.SimpleNamespace(type="text", text='{"supported":true,"reason":"yes"}')]
        approved, _ = verify_es_script({"title": "Tornado", "script": "Fire"}, FakeClient(blocks))
        self.assertFalse(approved)

    def test_rejects_unsupported_mechanism(self):
        blocks = [types.SimpleNamespace(type="server_tool_use", name="web_search"),
                  types.SimpleNamespace(type="text", text='{"supported":false,"reason":"fires followed damage"}')]
        approved, reason = verify_es_script({"title": "Tornado", "script": "Fire"}, FakeClient(blocks))
        self.assertFalse(approved)
        self.assertIn("fires followed", reason)

    def test_accepts_grounded_verdict(self):
        blocks = [types.SimpleNamespace(type="server_tool_use", name="web_search"),
                  types.SimpleNamespace(type="text", text='{"supported":true,"reason":"primary source"}')]
        approved, _ = verify_es_script({"title": "Tornado", "script": "Fire"}, FakeClient(blocks))
        self.assertTrue(approved)

    def test_repair_keeps_loop_and_removes_false_claim(self):
        import config
        from unittest.mock import patch

        original = {
            "title": "La catarata mueve el agua que bebes",
            "script": "El agua que bebes pasó por esta catarata. Y así es como.",
            "video_queries": ["drinking water"], "source_url": "https://oceanservice.noaa.gov/facts/largest-waterfall.html",
            "topic": "the ocean", "has_loop": True,
        }
        fixed = {
            "title": "La catarata más grande está bajo el océano",
            "script": ("La catarata más grande del mundo está escondida bajo el mar. "
                       "En el estrecho de Dinamarca, entre Groenlandia e Islandia, el agua fría "
                       "y densa desciende bajo otra masa de agua más cálida. La caída alcanza "
                       "unos 3,500 metros: más de tres veces la altura del Salto Ángel. "
                       "No verás espuma desde un barco, porque toda la corriente se mueve "
                       "bajo la superficie. ¿Te imaginabas una cascada de ese tamaño sin verla?"),
            "video_queries": ["Denmark strait ocean", "underwater current"],
            "hook_text": "LA MAYOR CASCADA ES INVISIBLE",
            "search_summary": "La catarata del estrecho de Dinamarca cae bajo el océano.",
            "comment_question": "¿Te imaginabas una catarata bajo el mar?",
        }
        blocks = [types.SimpleNamespace(type="text", text=__import__("json").dumps(fixed))]
        with patch.object(config, "CFG", config.CONFIGS["es"]):
            revised = repair_es_script(original, "Drinking water claim unsupported", FakeClient(blocks))
        self.assertTrue(revised["script"].endswith("Y así es como."))
        self.assertNotIn("agua que bebes", revised["script"])
        self.assertEqual(revised["source_url"], original["source_url"])
        self.assertEqual(revised["video_queries"], fixed["video_queries"])


if __name__ == "__main__":
    unittest.main()
