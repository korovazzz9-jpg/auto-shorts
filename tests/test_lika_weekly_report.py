"""Offline checks for the multi-platform Telegram digest."""
import ast
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock


SOURCE = (Path(__file__).resolve().parents[1] / "src" / "lika_weekly_report.py").read_text(encoding="utf-8")
NAMES = {"_since", "_published", "_recent", "fetch_facebook", "baseline", "load_history", "save_snapshot", "render", "main"}
TREE = ast.Module(body=[node for node in ast.parse(SOURCE).body
                        if isinstance(node, ast.FunctionDef) and node.name in NAMES], type_ignores=[])
NS = {"datetime": datetime, "timedelta": timedelta, "timezone": timezone,
      "json": json, "os": os, "HISTORY": Path("unused.json"),
      "MIN_RANK_AGE": timedelta(hours=24), "PAGE_ID": "123", "PAGE_NAME": "Lika"}
exec(compile(ast.fix_missing_locations(TREE), "<lika_report>", "exec"), NS)


class LikaReportTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 19, 9, 37, tzinfo=timezone.utc)
        self.history = [{"at": "2026-10-12T09:37:00+00:00",
                         "followers": {"youtube": 100, "instagram": 20, "facebook": 10}}]

    def test_recent_excludes_old_and_future(self):
        items = [{"published_at": "2026-10-18T12:00:00Z"},
                 {"published_at": "2026-10-01T12:00:00Z"},
                 {"published_at": "2026-10-26T12:00:00Z"}]
        self.assertEqual(NS["_recent"](items, self.now), items[:1])

    def test_report_shows_growth_and_extremes_without_fake_zero(self):
        results = {"youtube": {"followers": 105, "videos": [
                       {"views": 900, "title": "Лучший", "url": "https://youtube.com/shorts/a", "published_at": "2026-10-17T09:00:00Z"},
                       {"views": 100, "title": "Худший", "url": "https://youtube.com/shorts/b", "published_at": "2026-10-16T09:00:00Z"}],
                       "views_status": None},
                   "instagram": {"followers": 22, "videos": [{"title": "Reel", "published_at": "2026-10-16T09:00:00Z"}],
                                 "views_status": "нет доступа к просмотрам Reels"},
                   "facebook": {"followers": 12, "videos": [], "views_status": None}}
        report = NS["render"](results, self.history, self.now)
        self.assertIn("Подписчики: +5 с 2026-10-12 (100 → 105)", report)
        self.assertIn("Самый просматриваемый: 900", report)
        self.assertIn("Наименее просматриваемый: 100", report)
        self.assertIn("нет доступа к просмотрам Reels", report)
        self.assertNotIn("Наименее просматриваемый: 0", report)
        self.assertLess(len(report), 4000)

    def test_first_run_has_no_invented_growth(self):
        result = {key: {"followers": 10, "videos": [], "views_status": None}
                  for key in ("youtube", "instagram", "facebook")}
        report = NS["render"](result, [], self.now)
        self.assertEqual(report.count("первый замер"), 3)

    def test_partial_facebook_views_do_not_claim_extremes(self):
        results = {"youtube": {"followers": 1, "videos": [], "views_status": None},
                   "instagram": {"followers": 1, "videos": [], "views_status": None},
                   "facebook": {"followers": 1, "videos": [
                       {"views": 493, "title": "Доступен", "url": "/reel/a", "published_at": "2026-10-16T09:00:00Z"},
                       {"views": None, "title": "Неизвестен", "url": "/reel/b", "published_at": "2026-10-16T09:00:00Z"}],
                       "views_status": "нет доступа к просмотрам Reels"}}
        report = NS["render"](results, [], self.now)
        self.assertIn("просмотры доступны для 1/2 зрелых роликов", report)
        self.assertNotIn("Самый просматриваемый:", report)
        self.assertNotIn("Наименее просматриваемый:", report)

    def test_new_video_counts_but_cannot_be_worst(self):
        results = {key: {"followers": 1, "videos": [], "views_status": None}
                   for key in ("youtube", "instagram", "facebook")}
        results["youtube"]["videos"] = [
            {"views": 100, "title": "Вчера", "url": "a", "published_at": "2026-10-17T09:00:00Z"},
            {"views": 1, "title": "Час назад", "url": "b", "published_at": "2026-10-19T08:37:00Z"}]
        report = NS["render"](results, [], self.now)
        self.assertIn("Опубликовано роликов: 2", report)
        self.assertIn("Наименее просматриваемый: 100", report)
        self.assertNotIn("Час назад", report)

    def test_facebook_excludes_scheduled_videos(self):
        old_token = os.environ.get("IG_ACCESS_TOKEN_HUMOR")
        os.environ["IG_ACCESS_TOKEN_HUMOR"] = "test-token"
        context = dict(NS)
        def items(path, token, fields, now):
            if path == "me/accounts":
                return [{"id": "123", "name": "Lika", "access_token": "page-token"}]
            self.assertIn("published", fields)
            return [{"id": "live", "description": "Live", "created_time": "2026-10-18T09:00:00Z",
                     "published": True, "views": 10, "permalink_url": "/reel/live/"},
                    {"id": "scheduled", "description": "Scheduled", "created_time": "2026-10-18T10:00:00Z",
                     "published": False, "views": 0}]
        context["_page_items"] = items
        context["_graph"] = lambda *args, **kwargs: {"followers_count": 2}
        facebook = next(n for n in ast.parse(SOURCE).body
                        if isinstance(n, ast.FunctionDef) and n.name == "fetch_facebook")
        exec(compile(ast.fix_missing_locations(ast.Module(body=[facebook], type_ignores=[])),
                     "<lika_facebook>", "exec"), context)
        try:
            result = context["fetch_facebook"](self.now)
        finally:
            if old_token is None:
                os.environ.pop("IG_ACCESS_TOKEN_HUMOR", None)
            else:
                os.environ["IG_ACCESS_TOKEN_HUMOR"] = old_token
        self.assertEqual([v["id"] for v in result["videos"]], ["live"])
        self.assertEqual(result["videos"][0]["url"], "https://www.facebook.com/reel/live/")

    def test_snapshot_replaces_same_day_only(self):
        workspace = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=workspace) as folder:
            self.assertTrue(Path(folder).resolve().is_relative_to(workspace))
            path = Path(folder) / "followers.json"
            path.write_text(json.dumps({"snapshots": self.history}), encoding="utf-8")
            results = {"youtube": {"followers": 105}, "instagram": "недоступно"}
            NS["save_snapshot"](results, self.now, path)
            NS["save_snapshot"]({"youtube": {"followers": 106}}, self.now, path)
            rows = NS["load_history"](path)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[-1]["followers"], {"youtube": 106})

    def test_main_sends_then_saves(self):
        calls = []
        context = dict(NS)
        context.update({"_load_env": Mock(), "load_history": lambda: [],
                        "fetch_youtube": lambda now: {"followers": 1, "videos": []},
                        "fetch_instagram": lambda now: {"followers": 2, "videos": []},
                        "fetch_facebook": lambda now: {"followers": 3, "videos": []},
                        "send_telegram": lambda message: calls.append("sent"),
                        "save_snapshot": lambda results, now: calls.append("saved"),
                        "print": Mock()})
        main = next(n for n in ast.parse(SOURCE).body
                    if isinstance(n, ast.FunctionDef) and n.name == "main")
        exec(compile(ast.fix_missing_locations(ast.Module(body=[main], type_ignores=[])),
                     "<lika_main>", "exec"), context)
        context["main"]()
        self.assertEqual(calls, ["sent", "saved"])


if __name__ == "__main__":
    unittest.main()
