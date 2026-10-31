"""Offline checks for ES topic allocation and age-labelled reach snapshots."""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import generate_script
import track_es_reach
import analytics_retention


class ESReachExperimentTests(unittest.TestCase):
    def test_es_topic_tiers_use_75_20_5(self):
        topics = generate_script.TOPICS_POOL
        medians = {topic: 1000 - i * 10 for i, topic in enumerate(topics)}
        with patch.object(generate_script, "CHANNEL", "es"), \
             patch.object(generate_script, "get_recent_topics", return_value=[]), \
             patch.object(generate_script, "get_topic_median_views", return_value=medians), \
             patch.object(generate_script, "_load_niche_signal", return_value={}), \
             patch.object(generate_script, "_load_saturation", return_value={}), \
             patch.object(generate_script.random, "choice", side_effect=lambda tier: tier[0]):
            with patch.object(generate_script.random, "random", return_value=0.74):
                self.assertIn(generate_script._pick_topic(), topics[:4])
            with patch.object(generate_script.random, "random", return_value=0.76):
                self.assertIn(generate_script._pick_topic(), topics[4:8])
            with patch.object(generate_script.random, "random", return_value=0.96):
                self.assertIn(generate_script._pick_topic(), topics[8:])

    def test_due_excludes_young_old_and_already_sampled(self):
        now = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)
        def row(name, age):
            return {"video_id": name, "published_at": (now - age).isoformat()}
        history = [row("young", timedelta(hours=71)), row("due", timedelta(hours=73)),
                   row("old", timedelta(days=8)), row("sampled", timedelta(days=4))]
        self.assertEqual([x[0]["video_id"] for x in track_es_reach.due(
            history, {"sampled"}, now)], ["due"])

    def test_collect_saves_only_public_video_and_never_invents_analytics(self):
        now = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            history_path = Path(folder) / "history.json"
            output_path = Path(folder) / "reach.csv"
            published = now - timedelta(hours=76)
            history_path.write_text(json.dumps([
                {"video_id": "public", "published_at": published.isoformat(),
                 "topic": "space", "hook_template": "sounds-fake", "clip_selection": None},
                {"video_id": "private", "published_at": published.isoformat()}
            ]), encoding="utf-8")
            videos = Mock()
            videos.videos.return_value.list.return_value.execute.return_value = {"items": [
                {"id": "public", "status": {"privacyStatus": "public"},
                 "statistics": {"viewCount": "500"}},
                {"id": "private", "status": {"privacyStatus": "private"},
                 "statistics": {"viewCount": "2"}},
            ]}
            with patch.object(track_es_reach, "get_client", return_value=videos), \
                 patch.object(track_es_reach, "get_analytics_client", side_effect=OSError("offline")):
                self.assertEqual(track_es_reach.collect(now, history_path, output_path), 1)
            rows = track_es_reach.load_rows(output_path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["video_id"], "public")
            self.assertEqual(rows[0]["views_at_sample"], "500")
            self.assertEqual(rows[0]["sample_age_hours"], "76.0")
            self.assertEqual(rows[0]["engaged_views_3d"], "")
            with patch.object(track_es_reach, "get_client", return_value=videos):
                self.assertEqual(track_es_reach.collect(now, history_path, output_path), 0)
            self.assertEqual(track_es_reach.load_rows(output_path), rows)

    def test_collect_records_engaged_views_with_fixed_calendar_window(self):
        now = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)
        published = now - timedelta(hours=80)
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            history_path = Path(folder) / "history.json"
            output_path = Path(folder) / "reach.csv"
            history_path.write_text(json.dumps([{"video_id": "public",
                                                 "published_at": published.isoformat()}]),
                                    encoding="utf-8")
            youtube = Mock()
            youtube.videos.return_value.list.return_value.execute.return_value = {"items": [
                {"id": "public", "status": {"privacyStatus": "public"},
                 "statistics": {"viewCount": "500"}}]}
            with patch.object(track_es_reach, "get_client", return_value=youtube), \
                 patch.object(track_es_reach, "get_analytics_client", return_value=Mock()), \
                 patch.object(analytics_retention, "video_report", return_value={
                     "public": {"views": 480, "engagedViews": 390}}) as report:
                self.assertEqual(track_es_reach.collect(now, history_path, output_path), 1)
            self.assertEqual(report.call_args.args[2], published.date().isoformat())
            self.assertEqual(report.call_args.args[3],
                             (published.date() + timedelta(days=2)).isoformat())
            row = track_es_reach.load_rows(output_path)[0]
            self.assertEqual(row["engaged_views_3d"], "390")
            self.assertEqual(row["analytics_views_3d"], "480")


if __name__ == "__main__":
    unittest.main()
