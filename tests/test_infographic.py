"""The generic ES cards must not introduce a new visible claim."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from infographic import render_card
from infographic_data import normalize_card
from PIL import Image


class InfographicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.queue = json.loads((ROOT / "queue_es.json").read_text(encoding="utf-8"))

    def test_new_or_mistimed_claim_is_not_rendered(self):
        video = self.queue[2]
        card = {"type": "comparison", "subject": "monte Santa Helena",
                "items": ["cuatrocientos metros", "trescientos metros"], "after_query": 3}
        self.assertIsNone(normalize_card(card, video["script"], video["video_queries"]))
        card["items"][1] = "un cráter"
        card["after_query"] = 2
        self.assertIsNone(normalize_card(card, video["script"], video["video_queries"]))

    def test_four_card_types_render_at_shorts_size(self):
        ocean, island, volcano = self.queue
        examples = [
            ({"type": "route", "subject": "patitos de goma",
              "items": ["Pacífico Norte", "distintas costas"], "after_query": 3}, ocean),
            ({"type": "before_after", "subject": "monte Santa Helena",
              "items": ["una cumbre", "forma de herradura"], "after_query": 3}, volcano),
            ({"type": "timeline", "subject": "Surtsey",
              "items": ["1963", "las olas", "durante décadas"], "after_query": 3}, island),
            ({"type": "comparison", "subject": "Dos torres",
              "items": ["100 metros", "200 metros"], "after_query": 3},
             {"script": "Dos torres: la torre A mide 100 metros. La torre B mide 200 metros.",
              "video_queries": ["tower", "tower aerial", "ruler"]}),
        ]
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            for index, (card, video) in enumerate(examples):
                path = str(Path(tmp) / f"card-{index}.png")
                render_card(card, video["script"], video["video_queries"], path)
                with Image.open(path) as image:
                    self.assertEqual((1080, 1920), image.size)


if __name__ == "__main__":
    unittest.main()
