"""Independent review requires an actual web search and a supported verdict."""

import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.modules.setdefault("anthropic", types.ModuleType("anthropic"))
sys.modules["anthropic"].Anthropic = lambda **kwargs: None

from fact_review import verify_es_script


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


if __name__ == "__main__":
    unittest.main()
