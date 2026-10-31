"""Offline checks for the ES batch fact gate and the queue's fail-open fallback."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from script_facts import check_consistency, check_source
import script_queue


class ScriptFactTests(unittest.TestCase):
    def test_title_year_and_subject(self):
        item = {"title": "La tormenta de 1972 en Sahara", "script": "En 1979 nevó en Sahara."}
        self.assertIn("title years absent from script: 1972", check_consistency(item))
        self.assertEqual([], check_consistency({"title": "Terremoto de 1700 en Cascadia",
                                                "script": "En 1700 Cascadia sufrió un terremoto."}))

    def test_quote_must_be_on_trusted_page_and_match_anchors(self):
        item = {"title": "Terremoto de 1700 en Cascadia",
                "source_url": "https://www.usgs.gov/example",
                "source_quote": "The 1700 Cascadia earthquake shook the Pacific Northwest coast."}
        page = "<html><script>fake</script><p>The 1700 Cascadia earthquake shook the Pacific Northwest coast.</p></html>"
        self.assertEqual([], check_source(item, fetch=lambda _: page))
        self.assertIn("source quote not found on cited page",
                      check_source(item, fetch=lambda _: "<p>Other event</p>"))
        self.assertIn("missing trusted HTTPS source URL",
                      check_source({**item, "source_url": "https://example.com/story"},
                                   fetch=lambda _: page))
        self.assertIn("source quote omits title year",
                      check_source({**item, "source_quote": "Cascadia earthquake shook the Pacific Northwest coast."},
                                   fetch=lambda _: page))

    def test_es_queue_skips_unverified_and_uses_verified(self):
        old_file, old_channel = script_queue.QUEUE_FILE, script_queue.CHANNEL
        try:
            with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as tmp:
                script_queue.QUEUE_FILE = str(Path(tmp) / "queue.json")
                script_queue.CHANNEL = "es"
                script_queue.save_queue([
                    {"title": "Unverified", "script": "Bad"},
                    {"title": "Terremoto de 1700 en Cascadia", "script": "En 1700 Cascadia tembló.",
                     "source_verified": True},
                ])
                item = script_queue.pop_next()
                self.assertEqual("Terremoto de 1700 en Cascadia", item["title"])
                self.assertEqual([], json.loads(Path(script_queue.QUEUE_FILE).read_text(encoding="utf-8")))
        finally:
            script_queue.QUEUE_FILE, script_queue.CHANNEL = old_file, old_channel


if __name__ == "__main__":
    unittest.main()
