"""Offline checks for the Telegram summary; no YouTube or Telegram calls."""
import ast
from datetime import date, timedelta
from pathlib import Path
import unittest
from unittest.mock import Mock


source = (Path(__file__).resolve().parents[1] / "src" / "weekly_report.py").read_text(encoding="utf-8")
function = next(node for node in ast.parse(source).body
                if isinstance(node, ast.FunctionDef) and node.name == "build_report")
module = ast.Module(body=[function], type_ignores=[])
namespace = {"date": date, "timedelta": timedelta, "CFG": {"channel_name": "Datos en 30s"}}
exec(compile(ast.fix_missing_locations(module), "<weekly_report>", "exec"), namespace)
build_report = namespace["build_report"]


class WeeklyReportTests(unittest.TestCase):
    def video(self, number, days_ago=1, views=100, pct=70, topic="ocean", drop=None):
        return {"id": str(number), "title": f"Video {number}",
                "published": (date.today() - timedelta(days=days_ago)).isoformat(),
                "views": views, "pct": pct, "topic": topic, "drop": drop}

    def test_only_recent_videos_count_and_no_old_leader(self):
        videos = [self.video(1, views=300), self.video(2, views=200),
                  self.video(3, days_ago=30, views=10000)]
        report = build_report(videos)
        self.assertIn("2 видео · 2 с данными · 500 просмотров", report)
        self.assertNotIn("Video 3", report)
        self.assertIn("youtube.com/shorts/1", report)

    def test_lag_and_no_recent_videos(self):
        self.assertEqual(build_report([self.video(1, days_ago=10)]), "")
        report = build_report([self.video(1, views=0, pct=0)])
        self.assertIn("Данные YouTube Analytics ещё не появились", report)

    def test_small_topic_sample_not_called_trend(self):
        report = build_report([self.video(1), self.video(2)])
        self.assertNotIn("Тема для следующего теста", report)
        report = build_report([self.video(1), self.video(2), self.video(3)])
        self.assertIn("ocean", report)

    def test_main_sends_one_report_and_saves_feedback(self):
        main_node = next(node for node in ast.parse(source).body
                         if isinstance(node, ast.FunctionDef) and node.name == "main")
        main_module = ast.Module(body=[main_node], type_ignores=[])
        video = self.video(1)
        send = Mock()
        save_hook = Mock()
        save_dropoff = Mock()
        save_tone = Mock()
        local = {"_videos_with_retention": lambda: [video],
                 "get_analytics_client": Mock(),
                 "_add_drop_offs": Mock(),
                 "build_report": build_report,
                 "notify": send,
                 "save_hook_stats": save_hook,
                 "save_dropoff_stats": save_dropoff,
                 "save_tone_stats": save_tone,
                 "enrich_with_performance": Mock(return_value=1),
                 "CHANNEL": "es", "print": Mock()}
        exec(compile(ast.fix_missing_locations(main_module), "<weekly_main>", "exec"), local)
        local["main"]()
        send.assert_called_once()
        save_hook.assert_called_once_with([video])
        save_dropoff.assert_called_once_with([video])
        save_tone.assert_called_once_with([video])

    def test_weak_video_and_message_fit(self):
        videos = [self.video(i, views=100 + i, pct=80) for i in range(40)]
        videos[0]["pct"] = 30
        videos[0]["drop"] = {"second": 6, "drop_pct": 12}
        report = build_report(videos)
        self.assertIn("резкий спад ~6-я сек.", report)
        self.assertLess(len(report), 4000)


if __name__ == "__main__":
    unittest.main()
