"""Rejected ES drafts may use a checked reserve, never bypass fact review."""

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from es_script_fallback import choose_fallback


class ESFallbackTests(unittest.TestCase):
    def test_uses_next_approved_queue_entry_without_generation(self):
        items = iter([{"title": "bad"}, {"title": "good"}])
        generate = Mock()
        result = choose_fallback(lambda: next(items), generate,
                                 lambda data: (data["title"] == "good", "unverified"))
        self.assertEqual(result["title"], "good")
        generate.assert_not_called()

    def test_empty_queue_gets_one_checked_live_candidate(self):
        generate = Mock(return_value={"title": "new"})
        result = choose_fallback(lambda: None, generate,
                                 lambda data: (True, "supported"))
        self.assertEqual(result["title"], "new")
        generate.assert_called_once_with()

    def test_rejected_reserve_and_live_candidate_still_fail(self):
        items = iter([{"title": "bad"}, None])
        generate = Mock(return_value={"title": "also bad"})
        with self.assertRaisesRegex(RuntimeError, "failed independent fact review"):
            choose_fallback(lambda: next(items), generate,
                            lambda data: (False, "unsupported"))
        generate.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
