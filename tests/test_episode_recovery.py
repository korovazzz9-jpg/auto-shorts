"""Offline recovery tests: no paid calls, rendering or uploads."""
import ast
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import sys
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import fetch_stock_video as stock
from episode_recovery import EpisodeRecovery, reliability_report
import test_clip_selection_offline as base
CANDIDATES = base.CANDIDATES


class RetryAndFillTests(unittest.TestCase):
    setUp = base.SelectionTests.setUp
    response = base.SelectionTests.response
    def error(self, status=529, retry_after="0"):
        return stock.APIStatusError("temporary", response=httpx.Response(status,
            headers={"retry-after": retry_after}, request=httpx.Request("POST", "https://invalid")), body=None)

    def test_overload_recovers_once_with_usage(self):
        create = self.response('{"approved":[1]}')
        response = create.return_value
        create.side_effect = [self.error(), response]
        with patch.object(stock.time, "sleep") as sleep:
            clips, outcome = stock._accepted_clips(CANDIDATES, "bird")
        self.assertEqual(outcome, "vetted")
        self.assertEqual(len(clips), 1)
        self.assertEqual(create.call_count, 2)
        sleep.assert_called_once_with(0)
        stats = stock.selection_stats()
        self.assertEqual((stats["retries"], stats["retry_recovered"], stats["unknown_usage_attempts"]), (1, 1, 1))
        self.assertEqual(stats["retry_input_tokens"], 123)

    def test_connection_timeout_retries_once(self):
        create = self.response('{"approved":[1]}')
        response = create.return_value
        create.side_effect = [stock.APIConnectionError(request=httpx.Request("POST", "https://invalid")), response]
        with patch.object(stock.time, "sleep") as sleep:
            self.assertEqual(stock._accepted_clips(CANDIDATES, "bird")[1], "vetted")
        sleep.assert_called_once_with(5.0)
        self.assertEqual(create.call_count, 2)

    def test_retry_after_http_date(self):
        from email.utils import format_datetime
        from datetime import timedelta
        create = self.response('{"approved":[1]}')
        response = create.return_value
        date = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=20))
        create.side_effect = [self.error(429, date), response]
        with patch.object(stock.time, "sleep") as sleep:
            stock._accepted_clips(CANDIDATES, "bird")
        self.assertGreater(sleep.call_args.args[0], 15)
        self.assertLessEqual(sleep.call_args.args[0], 20)

    def test_permanent_error_and_long_cooldown_not_retried(self):
        for error in [self.error(401), self.error(429, "120")]:
            create = self.response('{"approved":[1]}')
            create.side_effect = error
            with patch.object(stock.time, "sleep") as sleep:
                self.assertEqual(stock._accepted_clips(CANDIDATES, "bird"), ([], "api_error"))
            create.assert_called_once()
            sleep.assert_not_called()

    def test_retry_exhaustion_is_bounded(self):
        create = self.response('{"approved":[1]}')
        create.side_effect = self.error()
        with patch.object(stock.time, "sleep"):
            self.assertEqual(stock._accepted_clips(CANDIDATES, "bird"), ([], "api_error"))
        self.assertEqual(create.call_count, 2)
        self.assertEqual(stock.selection_stats()["retry_recovered"], 0)

    def download(self, url, **kwargs):
        return NS(content=url.encode(), raise_for_status=lambda: None)

    def test_one_primary_becomes_three_from_approved_reserve(self):
        saved = {}
        with patch.object(stock, "_search_with_fallback", return_value=CANDIDATES[:3]) as search, patch.object(stock.requests, "get", side_effect=self.download), patch.object(stock, "_is_valid_clip", return_value=True):
            paths = stock.fetch_clips(["bird"], self.tmp.name, narration="A bird hunts.", min_scenes=3, saved_selections=saved)
        self.assertEqual(len(paths), 3)
        search.assert_called_once()
        self.assertEqual(stock.selection_stats()["backup_scenes"], 2)
        with patch.object(stock, "_search_with_fallback", side_effect=AssertionError("must reuse")), patch.object(stock.requests, "get", side_effect=self.download), patch.object(stock, "_is_valid_clip", return_value=True):
            self.assertEqual(len(stock.fetch_clips(["bird"], self.tmp.name, narration="A bird hunts.", min_scenes=3, saved_selections=saved)), 3)
        self.assertEqual(stock.selection_stats()["vision_calls"], 0)

    def test_extra_search_fills_without_reusing_ids(self):
        with patch.object(stock, "_search_with_fallback", side_effect=[CANDIDATES[:1], CANDIDATES]) as search, patch.object(stock.requests, "get", side_effect=self.download), patch.object(stock, "_is_valid_clip", return_value=True):
            paths = stock.fetch_clips(["bird"], self.tmp.name, narration="A bird hunts.", min_scenes=3)
        self.assertEqual(len(paths), 3)
        self.assertEqual(search.call_count, 2)
        self.assertIn("A bird hunts.", search.call_args.args[2])

    def test_six_distinct_clips_from_two_approved_groups(self):
        more = [dict(id=i, link=f"https://invalid/clip{i}", preview=f"https://invalid/poster{i}") for i in range(5, 9)]
        with patch.object(stock, "_search_with_fallback", side_effect=[CANDIDATES, more]) as search, patch.object(stock.requests, "get", side_effect=self.download), patch.object(stock, "_is_valid_clip", return_value=True):
            paths = stock.fetch_clips(["bird", "bird hunting"], self.tmp.name, narration="A bird hunts.", min_scenes=6)
        self.assertEqual(len(paths), 6)
        self.assertEqual(len({Path(p).read_bytes() for p in paths}), 6)
        self.assertEqual(search.call_count, 2)
        self.assertEqual(stock.selection_stats()["extra_searches"], 0)

    def test_same_bytes_do_not_count_as_multiple_scenes(self):
        with patch.object(stock, "_search_with_fallback", return_value=CANDIDATES), patch.object(stock.requests, "get", return_value=NS(content=b"same", raise_for_status=lambda: None)), patch.object(stock, "_is_valid_clip", return_value=True):
            paths = stock.fetch_clips(["bird"], self.tmp.name, min_scenes=3)
        self.assertEqual(len(paths), 1)


class PipelineRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.recovery = EpisodeRecovery("es", self.tmp.name, slots=[(0,17)])
        self.data = {"topic": "birds", "title": "A bird", "script": "A bird hunts.", "video_queries": ["bird"] * 6}
        tree = ast.parse((Path(__file__).resolve().parents[1] / "src/pipeline.py").read_text(encoding="utf-8"))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_run")
        self.env = {"os": os, "tempfile": tempfile, "datetime": datetime, "timezone": timezone, "random": random,
                    "CHANNEL": "es", "CFG": {"channel_name": "Datos en 30s"}, "_verify_channel": Mock(),
                    "pop_next": Mock(return_value=self.data), "generate_script": Mock(side_effect=AssertionError("no generation")),
                    "fetch_clips": Mock(return_value=["one.mp4"]), "selection_stats": Mock(return_value=dict(stock._STATS_TEMPLATE)),
                    "text_to_speech": Mock(return_value=([], "voice")), "build_video": Mock(return_value=("video", "thumb", "white")),
                    "pick_cta_phrase": Mock(return_value=("cta", "topic")), "notify": Mock(), "_alert": Mock(),
                    "publish": Mock(return_value="yt-id")}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "pipeline", "exec"), self.env)

    def test_failure_preserves_script_and_resume_does_not_pop_queue(self):
        with self.assertRaisesRegex(RuntimeError, "1/6"):
            self.env["_run"](self.recovery)
        self.env["text_to_speech"].assert_not_called()
        self.env["publish"].assert_not_called()
        resumed = EpisodeRecovery("es", self.tmp.name)
        self.env["pop_next"].reset_mock()
        self.env["fetch_clips"].return_value = [f"clip{i}" for i in range(6)]
        self.env["publish"].side_effect = lambda **kw: (kw["on_youtube_uploaded"]("yt-id") or "yt-id")
        self.env["_run"](resumed)
        self.env["pop_next"].assert_not_called()
        self.env["generate_script"].assert_not_called()
        self.env["publish"].assert_called_once()
        resumed.finish("published", {})
        self.assertIsNone(EpisodeRecovery("es", self.tmp.name).pending())
        self.assertIn("восстановлено выпусков 1", reliability_report("es", self.tmp.name))

    def test_unknown_upload_is_not_republished(self):
        self.recovery.prepare(self.data, None, False)
        self.recovery.publishing()
        with self.assertRaisesRegex(RuntimeError, "unknown outcome"):
            EpisodeRecovery("es", self.tmp.name).pending()

    def test_failed_slot_and_recovered_episode_reported_separately(self):
        from datetime import timedelta
        self.recovery.prepare(self.data, None, False)
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        self.recovery.slot = old
        self.recovery.finish("deferred", {"retries": 1, "retry_reasons": {"529": 1}, "unknown_usage_attempts": 2})
        resumed = EpisodeRecovery("es", self.tmp.name)
        resumed.uploaded("yt-id")
        resumed.finish("published", {"retry_input_tokens": 123})
        report = reliability_report("es", self.tmp.name)
        self.assertIn("слотов без публикации среди записанных 1", report)
        self.assertIn("восстановлено выпусков 1", report)
        self.assertIn("529", report)
        self.assertIn("неизвестным расходом: 2", report)

    def test_saved_approval_and_pair_context_round_trip(self):
        pending = self.recovery.prepare(self.data, {"id": "pair", "claim": "claim"}, True)
        pending["selections"]["key"] = CANDIDATES
        self.recovery.save()
        resumed = EpisodeRecovery("es", self.tmp.name).pending()
        self.assertEqual(resumed["selections"]["key"], CANDIDATES)
        self.assertEqual(resumed["pending_pair"]["id"], "pair")
        self.assertTrue(resumed["pair_start_mode"])


if __name__ == "__main__":
    unittest.main()
