"""Офлайн-тесты правок аудита 2026-09: повтор загрузки на YouTube, сверка эпизода, застрявшего
в «publishing», и повтор push при сохранении состояния. Без сети и без платных вызовов."""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

import httplib2
from googleapiclient.errors import HttpError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import upload_youtube as uy
from episode_recovery import EpisodeRecovery


def http_error(status):
    return HttpError(httplib2.Response({"status": status}), b"{}")


class FakeRequest:
    """next_chunk() по сценарию: исключение или (status, response)."""
    def __init__(self, *steps):
        self.steps = list(steps)
        self.calls = 0

    def next_chunk(self):
        self.calls += 1
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


class ResumableUploadTests(unittest.TestCase):
    def test_transient_5xx_and_network_errors_are_retried(self):
        request = FakeRequest(http_error(503), ConnectionResetError("reset"), (None, None), (None, {"id": "vid"}))
        sleep = Mock()
        self.assertEqual(uy.resumable_upload(request, sleep=sleep), {"id": "vid"})
        self.assertEqual(request.calls, 4)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [2, 4])

    def test_client_error_is_not_retried(self):
        request = FakeRequest(http_error(403))
        sleep = Mock()
        with self.assertRaises(HttpError):
            uy.resumable_upload(request, sleep=sleep)
        self.assertEqual(request.calls, 1)
        sleep.assert_not_called()

    def test_gives_up_after_retry_budget(self):
        request = FakeRequest(*[http_error(500)] * 4)
        with self.assertRaises(HttpError):
            uy.resumable_upload(request, retries=3, sleep=Mock())
        self.assertEqual(request.calls, 4)

    def test_upload_video_goes_through_resumable_upload(self):
        youtube = Mock()
        youtube.videos().insert.return_value = FakeRequest((None, {"id": "abc"}))
        with tempfile.NamedTemporaryFile(suffix=".mp4") as f, \
                unittest.mock.patch.object(uy, "get_client", return_value=youtube):
            vid = uy.upload_video(f.name, "Título <b>", "desc", ["t"], ["#x"])
        self.assertEqual(vid, "abc")
        body = youtube.videos().insert.call_args.kwargs["body"]
        self.assertEqual(body["snippet"]["title"], "Título b")


def fake_channel(items):
    yt = Mock()
    yt.channels().list().execute.return_value = {
        "items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU1"}}}]}
    yt.playlistItems().list().execute.return_value = {"items": items}
    return yt


def upload_item(title, published, vid):
    return {"snippet": {"title": title, "publishedAt": published, "resourceId": {"videoId": vid}}}


class FindRecentUploadTests(unittest.TestCase):
    since = "2026-09-18T20:24:00+00:00"

    def test_finds_same_title_after_publishing_started(self):
        yt = fake_channel([upload_item("Otro", "2026-09-18T20:25:00Z", "x"),
                           upload_item("El volcán 😱", "2026-09-18T20:24:30Z", "vid1")])
        self.assertEqual(uy.find_recent_upload("El volcán 😱", self.since, youtube=yt), "vid1")

    def test_title_is_compared_after_youtube_sanitizing(self):
        """На канале лежит заголовок уже без угловых скобок — сверка должна их тоже снять."""
        yt = fake_channel([upload_item("Mito o verdad", "2026-09-18T20:24:30Z", "vid2")])
        self.assertEqual(uy.find_recent_upload("Mito <o> verdad", self.since, youtube=yt), "vid2")
        yt = fake_channel([upload_item("Mito o verdad", "2026-09-18T20:24:30Z", "vid2")])
        self.assertIsNone(uy.find_recent_upload("Mito y verdad", self.since, youtube=yt))

    def test_older_video_with_same_title_does_not_count(self):
        yt = fake_channel([upload_item("El volcán", "2026-09-17T20:24:00Z", "old")])
        self.assertIsNone(uy.find_recent_upload("El volcán", self.since, youtube=yt))


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = {"topic": "birds", "title": "A bird", "script": "A bird hunts."}

    def stuck(self, minutes_ago):
        rec = EpisodeRecovery("es", self.tmp.name)
        rec.prepare(self.data, None, False)
        rec.publishing()
        rec.state["pending"]["publishing_at"] = (
            datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
        rec.save()

    def test_publishing_records_start_time(self):
        rec = EpisodeRecovery("es", self.tmp.name)
        rec.prepare(self.data, None, False)
        rec.publishing()
        stored = EpisodeRecovery("es", self.tmp.name).state["pending"]
        self.assertEqual(stored["status"], "publishing")
        self.assertIn("publishing_at", stored)

    def test_found_on_channel_closes_episode_without_reupload(self):
        self.stuck(120)
        reconcile = Mock(return_value="vid9")
        rec = EpisodeRecovery("es", self.tmp.name, reconcile=reconcile)
        self.assertIsNone(rec.pending())
        self.assertEqual(reconcile.call_args.args[0], "A bird")
        self.assertIsNone(EpisodeRecovery("es", self.tmp.name).state["pending"])

    def test_absent_after_grace_goes_back_to_publishing(self):
        self.stuck(120)
        item = EpisodeRecovery("es", self.tmp.name, reconcile=Mock(return_value=None)).pending()
        self.assertEqual(item["status"], "prepared")
        self.assertEqual(item["data"]["title"], "A bird")
        self.assertEqual(EpisodeRecovery("es", self.tmp.name).state["pending"]["reconciled"], "absent")

    def test_absent_but_too_fresh_still_stops(self):
        self.stuck(5)
        with self.assertRaisesRegex(RuntimeError, "unknown outcome"):
            EpisodeRecovery("es", self.tmp.name, reconcile=Mock(return_value=None)).pending()
        self.assertEqual(EpisodeRecovery("es", self.tmp.name).state["pending"]["status"], "publishing")

    def test_lookup_failure_keeps_the_stop(self):
        self.stuck(120)
        with self.assertRaisesRegex(OSError, "network"):
            EpisodeRecovery("es", self.tmp.name, reconcile=Mock(side_effect=OSError("network"))).pending()
        self.assertEqual(EpisodeRecovery("es", self.tmp.name).state["pending"]["status"], "publishing")

    def test_without_reconcile_behaviour_is_unchanged(self):
        self.stuck(120)
        with self.assertRaisesRegex(RuntimeError, "unknown outcome"):
            EpisodeRecovery("es", self.tmp.name).pending()


@unittest.skipUnless(shutil.which("git") and shutil.which("bash"), "нужны git и bash")
class GitPersistTests(unittest.TestCase):
    """scripts/git_persist.sh на настоящих локальных репозиториях: bare-«origin» и два клона."""
    script = str(ROOT / "scripts" / "git_persist.sh")

    def git(self, cwd, *args):
        return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.origin, self.a, self.b = base / "origin.git", base / "a", base / "b"
        self.env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
                    "PERSIST_SLEEP": "0", "GIT_CONFIG_GLOBAL": str(base / "gitconfig")}
        (base / "gitconfig").write_text("[init]\n\tdefaultBranch = master\n")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "master", str(self.origin)], check=True, env=self.env)
        for clone in (self.a, self.b):
            subprocess.run(["git", "clone", "-q", str(self.origin), str(clone)], check=True, env=self.env,
                           capture_output=True)
        (self.a / "queue_es.json").write_text("[]")
        (self.a / "other.txt").write_text("x")
        subprocess.run(["git", "add", "."], cwd=self.a, check=True, env=self.env)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=self.a, check=True, env=self.env)
        subprocess.run(["git", "push", "-q", "origin", "master"], cwd=self.a, check=True, env=self.env)
        subprocess.run(["git", "pull", "-q", "origin", "master"], cwd=self.b, check=True, env=self.env,
                       capture_output=True)

    def persist(self, cwd, *files, attempts="4"):
        env = {**self.env, "PERSIST_ATTEMPTS": attempts}
        return subprocess.run(["bash", self.script, "chore: state", *files], cwd=cwd, env=env,
                              capture_output=True, text=True)

    def test_push_race_is_retried(self):
        """Чужой push успевает между нашими pull и push: первая попытка отбита, вторая проходит."""
        hook = self.a / ".git" / "hooks" / "pre-push"
        flag = Path(self.tmp.name) / "raced"
        hook.write_text(f"""#!/usr/bin/env bash
if [ ! -e "{flag}" ]; then
  touch "{flag}"
  cd "{self.b}" && echo other > other.txt && git commit -qam other && git push -q origin master
fi
""")
        hook.chmod(0o755)
        (self.a / "queue_es.json").write_text('["next"]')
        result = self.persist(self.a, "queue_es.json", "missing_es.json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("persisted on attempt 2", result.stdout)
        log = self.git(self.origin, "log", "--format=%s", "master")
        self.assertEqual(log.split("\n")[:2], ["chore: state", "other"])

    def test_no_changes_is_success(self):
        result = self.persist(self.a, "queue_es.json", "missing_es.json")
        self.assertEqual(result.returncode, 0)
        self.assertIn("no changes", result.stdout)

    def test_content_conflict_fails_after_attempts(self):
        (self.b / "queue_es.json").write_text('["theirs"]')
        subprocess.run(["git", "commit", "-qam", "theirs"], cwd=self.b, check=True, env=self.env)
        subprocess.run(["git", "push", "-q", "origin", "master"], cwd=self.b, check=True, env=self.env)
        (self.a / "queue_es.json").write_text('["ours"]')
        result = self.persist(self.a, "queue_es.json", attempts="2")
        self.assertEqual(result.returncode, 1)
        self.assertIn("failed after 2 attempts", result.stdout)
        self.assertFalse((self.a / ".git" / "rebase-merge").exists())


if __name__ == "__main__":
    unittest.main()
