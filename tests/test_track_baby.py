"""Офлайн-тесты трекера канала «малышка и щенок»: разбор ответов YouTube (подменные клиенты),
дописывание CSV без дублей, сводка по типам на выдуманных данных, выход без секрета."""
import csv
from datetime import datetime, timedelta, timezone
import io
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import httplib2
from googleapiclient.errors import HttpError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import track_baby as tb
import track_baby_report as rep

NOW = datetime(2026, 10, 12, 7, 41, tzinfo=timezone.utc)


class Call:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class Resource:
    def __init__(self, fn):
        self.fn = fn

    def list(self, **kw):
        return Call(lambda: self.fn(**kw))


class FakeYouTube:
    """channels/playlistItems/videos.list с разбором по страницам и пачкам по 50."""
    def __init__(self, items):
        self.items = items  # ответы videos.list, новые первыми
        self.video_calls = []

    def channels(self):
        return Resource(lambda **kw: {"items": [{"id": "UCbaby", "contentDetails": {"relatedPlaylists": {"uploads": "UUbaby"}}}]})

    def playlistItems(self):
        def page(pageToken=None, **kw):
            start = int(pageToken or 0)
            chunk = self.items[start:start + 50]
            resp = {"items": [{"snippet": {"resourceId": {"videoId": v["id"]}}} for v in chunk]}
            if start + 50 < len(self.items):
                resp["nextPageToken"] = str(start + 50)
            return resp
        return Resource(page)

    def videos(self):
        def lookup(id, **kw):
            ids = id.split(",")
            self.video_calls.append(len(ids))
            return {"items": [v for v in self.items if v["id"] in ids]}
        return Resource(lookup)


class FakeAnalytics:
    def __init__(self, stats, impressions=None):
        self.stats, self.impressions, self.queries = stats, impressions, []

    def reports(self):
        return self

    def query(self, **kw):
        self.queries.append(kw)
        ids = kw["filters"].removeprefix("video==").split(",")
        metrics = kw["metrics"].split(",")

        def run():
            if "videoThumbnailImpressions" in metrics and self.impressions is None:
                raise HttpError(httplib2.Response({"status": 400}), b'{"error": "Unknown identifier"}')
            source = self.impressions if "videoThumbnailImpressions" in metrics else self.stats
            rows = [[vid] + [source[vid][m] for m in metrics] for vid in ids if vid in source]
            return {"columnHeaders": [{"name": "video"}] + [{"name": m} for m in metrics], "rows": rows}
        return Call(run)


def api_video(vid, published, views, tags=(), description="", likes=5, comments=1):
    return {"id": vid,
            "snippet": {"title": f"Title {vid}", "publishedAt": published, "tags": list(tags), "description": description},
            "statistics": {"viewCount": str(views), "likeCount": str(likes), "commentCount": str(comments)},
            "contentDetails": {"duration": "PT14S"}}


def retention(pct, sec, subs):
    return {"averageViewPercentage": pct, "averageViewDuration": sec, "subscribersGained": subs}


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        shutil.copy(ROOT / "stats" / "baby" / "shorts_types.csv", self.dir / "shorts_types.csv")
        tb.write_csv(self.dir / "mapping.csv", tb.MAPPING_FIELDS, [])
        self.items = [
            api_video("v3", "2026-10-11T15:00:00Z", 900, tags=["baby", "s-banana_big_bite"]),
            api_video("v2", "2026-10-10T15:00:00Z", 4000, description="Puppy!\n#s:serious_lecture"),
            api_video("v1", "2026-10-09T15:00:00Z", 120),
        ]
        self.stats = {"v1": retention(61.5, 8.6, 0), "v2": retention(88.0, 12.3, 7), "v3": retention(74.2, 10.4, 2)}

    def rows(self, name):
        with (self.dir / name).open(encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))

    def run_track(self, youtube=None, analytics=None, now=NOW):
        with redirect_stdout(io.StringIO()) as out:
            summary = tb.track(youtube or FakeYouTube(self.items), analytics or FakeAnalytics(self.stats),
                               self.dir, now=now)
        return summary, out.getvalue()

    def test_parses_api_responses_into_videos_csv(self):
        summary, out = self.run_track()
        videos = {r["video_id"]: r for r in self.rows("videos.csv")}
        self.assertEqual(set(videos), {"v1", "v2", "v3"})
        v2 = videos["v2"]
        self.assertEqual((v2["name"], v2["type"], v2["risk"]), ("serious_lecture", "разговор", "низкий"))
        self.assertEqual((v2["views"], v2["likes"], v2["comments"], v2["duration_s"]), ("4000", "5", "1", "14"))
        self.assertEqual((v2["avg_view_pct"], v2["avg_view_sec"], v2["subs_gained"]), ("88.0", "12.3", "7"))
        self.assertEqual((v2["impressions"], v2["ctr"]), ("", ""))  # API не знает метрику — пусто, не падение
        self.assertEqual(videos["v3"]["type"], "еда")
        self.assertEqual(videos["v1"]["name"], "")
        self.assertEqual(summary, {"videos": 3, "mapped": 2, "new_mappings": 2, "impressions": False, "unknown_names": []})
        self.assertIn("показы/CTR недоступны", out)

    def test_impressions_and_ctr_when_api_gives_them(self):
        impressions = {vid: {"videoThumbnailImpressions": 1000 * i, "videoThumbnailImpressionsClickRate": 3.5 + i}
                       for i, vid in enumerate(["v1", "v2", "v3"], 1)}
        summary, _ = self.run_track(analytics=FakeAnalytics(self.stats, impressions))
        v2 = {r["video_id"]: r for r in self.rows("videos.csv")}["v2"]
        self.assertTrue(summary["impressions"])
        self.assertEqual((v2["impressions"], v2["ctr"]), ("2000", "5.5"))

    def test_mapping_from_marks_is_saved_and_manual_row_wins(self):
        tb.write_csv(self.dir / "mapping.csv", tb.MAPPING_FIELDS, [{"video_id": "v3", "name": "grumpy_then_hug"}])
        self.run_track()
        mapping = {r["video_id"]: r["name"] for r in self.rows("mapping.csv")}
        self.assertEqual(mapping, {"v3": "grumpy_then_hug", "v2": "serious_lecture"})
        self.assertEqual({r["video_id"]: r["name"] for r in self.rows("videos.csv")}["v3"], "grumpy_then_hug")

    def test_unknown_setup_name_is_reported(self):
        self.items[0]["snippet"]["tags"] = ["s-no_such_setup"]
        summary, out = self.run_track()
        self.assertEqual(summary["unknown_names"], ["no_such_setup"])
        self.assertIn("no_such_setup", out)

    def test_daily_csv_has_no_duplicates_within_a_day(self):
        self.run_track()
        self.items[1]["statistics"]["viewCount"] = "4500"
        self.run_track(now=NOW + timedelta(hours=3))  # тот же день, повторный запуск
        rows = self.rows("daily.csv")
        self.assertEqual(len(rows), 3)
        self.assertEqual({r["video_id"]: r["views"] for r in rows}["v2"], "4500")
        self.run_track(now=NOW + timedelta(days=1))  # следующий день — дописывается
        rows = self.rows("daily.csv")
        self.assertEqual(len(rows), 6)
        self.assertEqual(sorted({r["date"] for r in rows}), ["2026-10-12", "2026-10-13"])
        self.assertEqual(len({(r["date"], r["video_id"]) for r in rows}), 6)

    def test_age_hours_is_measured_from_publication(self):
        self.run_track()
        ages = {r["video_id"]: float(r["age_hours"]) for r in self.rows("daily.csv")}
        self.assertEqual(ages["v3"], 16.7)
        self.assertEqual(ages["v1"], 64.7)

    def test_pages_and_batches_all_uploads(self):
        items = [api_video(f"x{i:03d}", "2026-10-01T00:00:00Z", i) for i in range(120)]
        youtube = FakeYouTube(items)
        summary, _ = self.run_track(youtube=youtube, analytics=FakeAnalytics({}))
        self.assertEqual(summary["videos"], 120)
        self.assertEqual(youtube.video_calls, [50, 50, 20])


class ReportTests(unittest.TestCase):
    types = {"a1": {"type": "еда", "risk": "низкий"}, "a2": {"type": "еда", "risk": "низкий"},
             "b1": {"type": "сон", "risk": "низкий"}, "b2": {"type": "сон", "risk": "средний"},
             "c1": {"type": "звук", "risk": "высокий"}, "c2": {"type": "звук", "risk": "низкий"},
             "d1": {"type": "вода", "risk": "высокий"}}

    @staticmethod
    def snapshots(vid, name, per_day, days=8, published="2026-10-01T00:00:00Z"):
        """Ежедневные снимки: возраст 24, 48… ч, просмотры растут на per_day в сутки."""
        return [{"date": f"2026-10-{d + 1:02d}", "video_id": vid, "name": name, "published_at": published,
                 "age_hours": str(24 * d), "views": str(per_day * d), "avg_view_pct": "80", "avg_view_sec": "10",
                 "subs_gained": "1"} for d in range(1, days + 1)]

    def test_views_at_interpolates_between_snapshots(self):
        points = [(20.0, 100.0), (44.0, 300.0), (68.0, 500.0)]
        self.assertEqual(rep.views_at(points, 48), 300 + 200 * 4 / 24)
        self.assertEqual(rep.views_at(points, 10), 50.0)  # до первого снимка — от (0, 0)
        self.assertIsNone(rep.views_at(points, 24 * 7))    # ещё не дожил

    def test_summary_by_type_and_recommendation(self):
        daily = (self.snapshots("A1", "a1", 1000) + self.snapshots("A2", "a2", 1200)
                 + self.snapshots("B1", "b1", 400) + self.snapshots("B2", "b2", 500)
                 + self.snapshots("C1", "c1", 700) + self.snapshots("C2", "c2", 800)
                 + self.snapshots("U1", "", 50, days=3))
        text = rep.render(daily, self.types, datetime(2026, 10, 9, tzinfo=timezone.utc))
        rows = {r["type"]: r for r in rep.by_type(rep.per_video(daily), self.types)}
        self.assertEqual(rows["еда"]["n"], 2)
        self.assertEqual(rows["еда"]["med48"], 2200)        # медиана из 2000 и 2400
        self.assertEqual(rows["еда"]["med7d"], 7700)        # медиана из 7000 и 8400
        self.assertEqual(rows["еда"]["best"]["name"], "a2")
        self.assertEqual(rows["сон"]["worst"]["name"], "b1")
        self.assertIsNone(rows["без метки"]["med7d"])
        self.assertIn("| еда | 2 | 2200 | 7700 | 80.0 | a2 (8400) | a1 (7000) |", text)
        self.assertIn("Снимать больше: еда (7700).", text)
        self.assertIn("Снимать меньше: сон (3150).", text)
        self.assertIn("Ещё не снимались: вода.", text)
        self.assertIn("- U1 (2026-10-01)", text)

    def test_few_data_gives_no_verdict(self):
        daily = self.snapshots("A1", "a1", 1000, days=1) + self.snapshots("B1", "b1", 10, days=1)
        text = rep.render(daily, self.types, datetime(2026, 10, 2, tzinfo=timezone.utc))
        self.assertIn("Данных мало для вывода", text)

    def test_empty_report_and_file_written(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with redirect_stdout(io.StringIO()):
            rep.main(Path(tmp.name), now=NOW)
        self.assertIn("Снимков ещё нет", (Path(tmp.name) / "weekly.md").read_text(encoding="utf-8"))

    def test_report_reads_tracker_output(self):
        tracker = TrackerTests("test_parses_api_responses_into_videos_csv")
        tracker.setUp()
        self.addCleanup(tracker.tmp.cleanup)
        tracker.run_track()
        with redirect_stdout(io.StringIO()):
            rep.main(tracker.dir, now=NOW)
        text = (tracker.dir / "weekly.md").read_text(encoding="utf-8")
        self.assertIn("Роликов на канале: 3", text)
        self.assertIn("| разговор | 1 |", text)


class NoSecretTests(unittest.TestCase):
    def test_main_exits_cleanly_without_token(self):
        env = {k: v for k, v in os.environ.items() if k != "YT_TOKEN_BABY"}
        with patch.dict(os.environ, env, clear=True), patch.object(tb, "_load_env"), \
                patch("youtube_auth.get_client", side_effect=AssertionError("no API without token")), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(tb.main([]), 0)
        self.assertIn("канал не подключён", out.getvalue())

    def gate_script(self):
        """Тело шага `id: gate` из track-baby.yml (без PyYAML: блок `run: |` по отступу)."""
        lines = (ROOT / ".github/workflows/track-baby.yml").read_text(encoding="utf-8").splitlines()
        start = next(i for i, l in enumerate(lines) if l.strip() == "id: gate")
        run = next(i for i in range(start, len(lines)) if lines[i].strip() == "run: |")
        indent = len(lines[run + 1]) - len(lines[run + 1].lstrip())
        body = []
        for line in lines[run + 1:]:
            if line.strip() and len(line) - len(line.lstrip()) < indent:
                break
            body.append(line[indent:])
        return "\n".join(body)

    @unittest.skipUnless(shutil.which("bash"), "нужен bash")
    def test_workflow_gate_without_secret_succeeds_and_disables(self):
        self.assertIn("echo \"enabled=false\"", self.gate_script())
        for token, expected in (("", "enabled=false"), ("secret-value", "enabled=true")):
            with tempfile.NamedTemporaryFile("r", suffix=".out") as output:
                env = {"PATH": os.environ["PATH"], "GITHUB_OUTPUT": output.name, "YT_TOKEN_BABY": token}
                result = subprocess.run(["bash", "-e", "-c", self.gate_script()], env=env,
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(output.read().strip(), expected)
                self.assertEqual("канал не подключён" in result.stdout, not token)
                self.assertNotIn("secret-value", result.stdout + result.stderr)

    def test_later_steps_are_gated(self):
        text = (ROOT / ".github/workflows/track-baby.yml").read_text(encoding="utf-8")
        steps = re.split(r"\n      - ", text.split("steps:", 1)[1])[1:]
        self.assertTrue(steps[0].startswith("name: Check channel is connected"))
        for step in steps[1:]:
            self.assertIn("steps.gate.outputs.enabled == 'true'", step, step.splitlines()[0])


if __name__ == "__main__":
    unittest.main()
