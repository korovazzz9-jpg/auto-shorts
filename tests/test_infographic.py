"""The generic ES cards must not introduce a new visible claim."""

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
        # Stable excerpts from three sourced drafts; the live queue is routinely empty.
        cls.queue = [
            {"script": ("En 1992, un contenedor con patitos de goma cayó al Pacífico Norte. "
                        "Flotaron con las corrientes y llegaron a distintas costas."),
             "video_queries": ["toys", "ship", "ocean"]},
            {"script": ("Surtsey surgió frente a Islandia en 1963. Las olas cambiaron sus "
                        "costas durante décadas."),
             "video_queries": ["island", "waves", "coast"]},
            {"script": ("En 1980, el monte Santa Helena perdió cuatrocientos metros de su "
                        "parte superior. Donde antes había una cumbre quedó un cráter con "
                        "forma de herradura."),
             "video_queries": ["volcano", "avalanche", "crater"]},
        ]

    def test_live_paraphrase_uses_spoken_words(self):
        script = ("Mount St. Helens, Washington, 1980: su cima era perfecta, nevada, "
                  "imponente. Donde había una punta simétrica quedó un cráter en "
                  "forma de herradura abierto hacia el norte.")
        card = {"type": "before_after", "subject": "cima de Mount St. Helens",
                "items": ["Punta simétrica nevada", "Cráter en herradura"],
                "after_query": 3}
        result = normalize_card(card, script, ["one", "two", "three"])
        self.assertEqual(result["subject"], "Mount St. Helens")
        self.assertEqual(result["items"], ["punta simétrica", "cráter en forma de herradura"])

    def test_before_after_drops_unspoken_adjective(self):
        script = ("El Monte Santa Helena perdió su cumbre entera y la convirtió "
                  "en un cráter en forma de herradura.")
        card = {"type": "before_after", "subject": "Monte Santa Helena",
                "items": ["cumbre intacta", "cráter en herradura"],
                "after_query": 3}
        result = normalize_card(card, script, ["one", "two", "three"])
        self.assertEqual(result["items"], ["cumbre", "cráter en forma de herradura"])
        card["items"][0] = "veinte metros"
        self.assertIsNone(normalize_card(card, script, ["one", "two", "three"]))

    def test_new_or_mistimed_claim_is_not_rendered(self):
        video = self.queue[2]
        card = {"type": "comparison", "subject": "monte Santa Helena",
                "items": ["cuatrocientos metros", "trescientos metros"], "after_query": 3}
        self.assertIsNone(normalize_card(card, video["script"], video["video_queries"]))
        card["items"][1] = "un cráter"
        card["after_query"] = 2
        self.assertIsNone(normalize_card(card, video["script"], video["video_queries"]))
        card["after_query"] = 3
        card["items"] = ["un cráter", "un cráter"]
        self.assertIsNone(normalize_card(card, video["script"], video["video_queries"]))

    def test_eight_card_types_render_at_shorts_size(self):
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
            ({"type": "cause_effect", "subject": "la erupción",
              "items": ["hielo derretido", "alud de barro"], "after_query": 3},
             {"script": "La erupción derritió hielo. El hielo derretido provocó un alud de barro.",
              "video_queries": ["volcano", "ice", "mud"]}),
            ({"type": "layers", "subject": "La Tierra",
              "items": ["corteza", "manto", "núcleo"], "after_query": 3},
             {"script": "La Tierra tiene corteza sobre manto y núcleo.",
              "video_queries": ["earth", "rock", "core"]}),
            ({"type": "cycle", "subject": "El agua",
              "items": ["se evapora", "forma nubes", "lluvia"], "after_query": 3},
             {"script": "El agua se evapora, forma nubes, cae como lluvia y vuelve a evaporarse.",
              "video_queries": ["water", "cloud", "rain"]}),
            ({"type": "part_whole", "subject": "El corazón",
              "items": ["El corazón", "ventrículo izquierdo"], "after_query": 3},
             {"script": "El corazón tiene cuatro cámaras. El ventrículo izquierdo es una de ellas.",
              "video_queries": ["heart", "anatomy", "ventricle"]}),
        ]
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            for index, (card, video) in enumerate(examples):
                path = str(Path(tmp) / f"card-{index}.png")
                render_card(card, video["script"], video["video_queries"], path)
                with Image.open(path) as image:
                    self.assertEqual((1080, 1920), image.size)


if __name__ == "__main__":
    unittest.main()
