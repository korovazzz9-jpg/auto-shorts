"""Офлайн-тесты выкладки Nora & Maple (src/publish_baby.py) на подставных файлах репозитория AI:
разбор выпуска из CHANNEL_PACK.md, тело запроса, расписание будни/выходные, перестановка одинаковых
типов, пропуск выложенного и отсутствующего, чужой канал (подменный клиент), --dry ничего не пишет."""
import csv
import datetime as dt
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import publish_baby as pb

MSK = pb.MSK
NOW = dt.datetime(2026, 9, 30, 12, 0, tzinfo=MSK)  # среда

# order, name, type
SHORTS = [
    (1, "serious_lecture", "разговор"),
    (2, "sit_means_flop", "разговор"),
    (3, "banana_big_bite", "еда"),
    (4, "toy_phone_call", "разговор"),
    (5, "bedtime_story", "сон"),
    (6, "rice_cake_crunch", "еда"),
]

PACK = """# Пакет канала

## Описания, теги, обложки

**1. Baby Gives Her Puppy a Very Serious Lecture 🐶**
- Описание: Nora explains the rules. Maple listens very carefully. / Nora & Maple — an AI-generated short series.
- Теги: #goldenretriever #puppy #babyandpuppy #toddler #aivideo #shorts
- Обложка: малышка грозит пальчиком.

**2. Baby Gives a Strict Command… Puppy Flops on His Belly**
- Описание: Nora raises one finger and gives Maple a very firm command,
  twice. / Nora & Maple — an AI-generated short series.
- Теги: #goldenretriever #puppy #babyandpuppy #puppytraining #aivideo #shorts
- Обложка: пальчик вверх.

**3. One Big Bite of Banana… and the Puppy Gets the Rest 🍌**
- Описание: Nora takes a huge bite. / Nora & Maple — an AI-generated short series.
- Теги: #goldenretriever #puppy #babyandpuppy #banana #aivideo #shorts
- Обложка: банан.

**4. Baby Calls Her Puppy on a Toy Phone… and He Answers 📞**
- Описание: Nora has an important call. / Nora & Maple — an AI-generated short series.
- Теги: #goldenretriever #puppy #babyandpuppy #pretendplay #aivideo #shorts
- Обложка: телефон.

**5. Bedtime Story for the Puppy… He Falls Asleep First 😴**
- Описание: Nora reads to Maple. / Nora & Maple — an AI-generated short series.
- Теги: #goldenretriever #puppy #babyandpuppy #naptime #aivideo #shorts
- Обложка: книжка.

**6. She Shares Her Rice Cake… He Crunches It Way Louder**
- Описание: Every bite gets a head tilt. / Nora & Maple — an AI-generated short series.
- Теги: #goldenretriever #puppy #babyandpuppy #snacktime #aivideo #shorts
- Обложка: хлебец.

---

Во всех описаниях — пометка про ИИ.
"""


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
    """channels.list (название канала + uploads-плейлист), playlistItems.list, videos.list — как у
    track_baby.fetch_videos. videos[i] = {"id", "tags"}."""

    def __init__(self, title="Nora & Maple", videos=()):
        self.title, self.items = title, list(videos)

    def channels(self):
        return Resource(lambda **kw: {"items": [{
            "id": "UCbaby", "snippet": {"title": self.title},
            "contentDetails": {"relatedPlaylists": {"uploads": "UUbaby"}}}]})

    def playlistItems(self):
        return Resource(lambda **kw: {"items": [{"snippet": {"resourceId": {"videoId": v["id"]}}}
                                                for v in self.items]})

    def videos(self):
        def lookup(id, **kw):
            ids = id.split(",")
            return {"items": [{"id": v["id"], "snippet": {"title": "", "tags": v.get("tags", []),
                                                          "publishedAt": "2026-09-29T16:30:00Z"},
                               "statistics": {}, "contentDetails": {"duration": "PT20S"}}
                              for v in self.items if v["id"] in ids]}
        return Resource(lookup)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.baby = self.tmp / "AI" / "video_gen" / "ui" / "_cp77_series" / "baby01"
        (self.baby / "batch").mkdir(parents=True)
        shorts = [{"order": o, "num": o, "name": n, "type": t} for o, n, t in SHORTS]
        (self.baby / "shorts.json").write_text(json.dumps(shorts, ensure_ascii=False), encoding="utf-8")
        (self.baby / "CHANNEL_PACK.md").write_text(PACK, encoding="utf-8")
        for _, n, _ in SHORTS:
            (self.baby / "batch" / f"{n}.mp4").write_bytes(b"fake mp4")
        self.published = self.tmp / "stats" / "baby" / "published.csv"
        self.uploads = []
        for p in (patch.object(pb, "BABY", self.baby), patch.object(pb, "PUBLISHED", self.published),
                  patch.object(pb, "_now", lambda: NOW)):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fake_upload(self, youtube, body, video):
        self.uploads.append((body, Path(video).name))
        return f"vid{len(self.uploads)}"

    def run_main(self, *argv, youtube=None):
        out = io.StringIO()
        with patch.object(pb, "connect", lambda: youtube or FakeYouTube()), \
                patch.object(pb, "upload", self.fake_upload), redirect_stdout(out):
            code = pb.main(list(argv))
        return code, out.getvalue()

    def published_rows(self):
        with self.published.open(encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))

    def write_published(self, rows):
        self.published.parent.mkdir(parents=True, exist_ok=True)
        with self.published.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(pb.PUBLISHED_FIELDS)
            w.writerows(rows)


class PackTests(Base):
    def test_entry_from_channel_pack(self):
        e = pb.pack_entry(2)
        self.assertEqual(e["title"], "Baby Gives a Strict Command… Puppy Flops on His Belly")
        self.assertEqual(e["description"], "Nora raises one finger and gives Maple a very firm command, twice."
                                           "\n\nNora & Maple — an AI-generated short series.")
        self.assertEqual(e["hashtags"], ["#goldenretriever", "#puppy", "#babyandpuppy", "#puppytraining",
                                         "#aivideo", "#shorts"])

    def test_last_entry_stops_at_rule_and_missing_entry_fails(self):
        self.assertEqual(pb.pack_entry(6)["hashtags"][-1], "#shorts")
        self.assertNotIn("Во всех", pb.pack_entry(6)["description"])
        with self.assertRaises(SystemExit):
            pb.pack_entry(7)


class BodyTests(Base):
    def test_scheduled_body(self):
        body = pb.build_body("sit_means_flop", pb.pack_entry(2), dt.datetime(2026, 10, 1, 19, 30, tzinfo=MSK))
        self.assertEqual(body["status"], {"selfDeclaredMadeForKids": False, "containsSyntheticMedia": True,
                                          "privacyStatus": "private", "publishAt": "2026-10-01T16:30:00Z"})
        tags = body["snippet"]["tags"]
        self.assertEqual(tags[0], "s-sit_means_flop")
        self.assertEqual(tags[1:6], pb.BASE_TAGS)
        self.assertIn("puppytraining", tags)
        self.assertNotIn("shorts", tags)
        self.assertEqual(len(tags), len(set(tags)))
        self.assertEqual(body["snippet"]["categoryId"], "15")
        self.assertTrue(body["snippet"]["description"].endswith("#aivideo #shorts"))

    def test_now_body_is_public(self):
        body = pb.build_body("serious_lecture", pb.pack_entry(1), None)
        self.assertEqual(body["status"]["privacyStatus"], "public")
        self.assertNotIn("publishAt", body["status"])


class ScheduleTests(unittest.TestCase):
    def test_weekdays_1930_weekends_1700(self):
        slots = pb.schedule(dt.date(2026, 10, 2), 4)  # пятница
        self.assertEqual([(s.date().isoformat(), s.strftime("%H:%M")) for s in slots],
                         [("2026-10-02", "19:30"), ("2026-10-03", "17:00"),
                          ("2026-10-04", "17:00"), ("2026-10-05", "19:30")])
        self.assertTrue(all(s.utcoffset() == dt.timedelta(hours=3) for s in slots))

    def test_taken_days_are_skipped(self):
        slots = pb.schedule(dt.date(2026, 10, 1), 2, taken={dt.date(2026, 10, 2)})
        self.assertEqual([s.date().isoformat() for s in slots], ["2026-10-01", "2026-10-03"])

    def test_same_type_neighbours_are_split(self):
        items = [{"order": o, "type": t} for o, t in [(1, "a"), (2, "a"), (3, "b"), (4, "c"), (5, "c"), (6, "a")]]
        self.assertEqual([s["order"] for s in pb.plan_order(items)], [1, 3, 2, 4, 6, 5])

    def test_order_kept_when_nothing_to_swap(self):
        items = [{"order": o, "type": "a"} for o in (3, 1, 2)]
        self.assertEqual([s["order"] for s in pb.plan_order(items)], [1, 2, 3])
        items = [{"order": 1, "type": "a"}, {"order": 2, "type": "b"}]
        self.assertEqual([s["order"] for s in pb.plan_order(items)], [1, 2])

    def test_previous_published_type_counts(self):
        items = [{"order": 1, "type": "a"}, {"order": 2, "type": "b"}]
        self.assertEqual([s["order"] for s in pb.plan_order(items, prev_type="a")], [2, 1])

    def test_bad_range(self):
        self.assertEqual(pb.parse_range("11-40"), (11, 40))
        for bad in ("40-11", "11", "a-b"):
            with self.assertRaises(SystemExit):
                pb.parse_range(bad)


class PlanTests(Base):
    def test_batch_uploads_in_schedule_order_and_records(self):
        code, out = self.run_main("--plan", "1-6", "--start", "2026-10-02", "--yes")
        self.assertEqual(code, 0)
        # 1 разговор, 3 еда, 2 разговор, 5 сон, 4 разговор, 6 еда — одинаковые типы не рядом
        names = [b["snippet"]["tags"][0] for b, _ in self.uploads]
        self.assertEqual(names, ["s-serious_lecture", "s-banana_big_bite", "s-sit_means_flop",
                                 "s-bedtime_story", "s-toy_phone_call", "s-rice_cake_crunch"])
        self.assertEqual([b["status"]["publishAt"] for b, _ in self.uploads],
                         ["2026-10-02T16:30:00Z", "2026-10-03T14:00:00Z", "2026-10-04T14:00:00Z",
                          "2026-10-05T16:30:00Z", "2026-10-06T16:30:00Z", "2026-10-07T16:30:00Z"])
        rows = self.published_rows()
        self.assertEqual([r["name"] for r in rows], [n[2:] for n in names])
        self.assertEqual(rows[0]["video_id"], "vid1")
        self.assertEqual(rows[0]["publish_at_utc"], "2026-10-02T16:30:00Z")
        self.assertEqual(rows[0]["at"], "2026-09-30T09:00:00Z")
        self.assertIn("2026-10-03 сб 17:00 МСК  #3", out)

    def test_published_on_channel_and_missing_are_skipped(self):
        self.write_published([["sit_means_flop", "old1", "2026-10-02T16:30:00Z", "2026-09-29T10:00:00Z"]])
        (self.baby / "batch" / "bedtime_story.mp4").unlink()
        youtube = FakeYouTube(videos=[{"id": "old2", "tags": ["s-toy_phone_call", "toddler"]},
                                      {"id": "x", "tags": ["unrelated"]}])
        code, out = self.run_main("--plan", "1-6", "--start", "2026-10-02", "--yes", youtube=youtube)
        self.assertEqual(code, 0)
        self.assertEqual([v for _, v in self.uploads],
                         ["banana_big_bite.mp4", "serious_lecture.mp4", "rice_cake_crunch.mp4"])
        self.assertIn("пропуск #2 sit_means_flop: уже выложен", out)
        self.assertIn("пропуск #4 toy_phone_call: уже на канале", out)
        self.assertIn("пропуск #5 bedtime_story: нет ролика", out)
        # 2 октября занято выложенным раньше — пачка идёт с 3-го; последний выложенный — «разговор»
        self.assertEqual([(b["snippet"]["tags"][0], b["status"]["publishAt"]) for b, _ in self.uploads],
                         [("s-banana_big_bite", "2026-10-03T14:00:00Z"),
                          ("s-serious_lecture", "2026-10-04T14:00:00Z"),
                          ("s-rice_cake_crunch", "2026-10-05T16:30:00Z")])
        self.assertEqual(len(self.published_rows()), 4)

    def test_nothing_left(self):
        self.write_published([[n, f"v{o}", "2026-09-20T16:30:00Z", ""] for o, n, _ in SHORTS[:2]])
        code, out = self.run_main("--plan", "1-2", "--start", "2026-10-02", "--yes")
        self.assertEqual((code, self.uploads), (0, []))
        self.assertIn("выкладывать нечего", out)

    def test_upload_error_stops_and_rerun_continues(self):
        def flaky(youtube, body, video):
            if len(self.uploads) == 2:
                raise RuntimeError("quotaExceeded")
            return self.fake_upload(youtube, body, video)

        out = io.StringIO()
        with patch.object(pb, "connect", FakeYouTube), patch.object(pb, "upload", flaky), redirect_stdout(out):
            code = pb.main(["--plan", "1-4", "--start", "2026-10-02", "--yes"])
        self.assertEqual(code, 1)
        self.assertIn("остановлено: выложено 2 из 4", out.getvalue())
        self.assertEqual([r["name"] for r in self.published_rows()], ["serious_lecture", "banana_big_bite"])
        self.uploads.clear()
        code, _ = self.run_main("--plan", "1-4", "--start", "2026-10-02", "--yes")
        self.assertEqual(code, 0)
        self.assertEqual([(b["snippet"]["tags"][0], b["status"]["publishAt"]) for b, _ in self.uploads],
                         [("s-sit_means_flop", "2026-10-04T14:00:00Z"),
                          ("s-toy_phone_call", "2026-10-05T16:30:00Z")])

    def test_answer_no_uploads_nothing(self):
        with patch("builtins.input", return_value="n"):
            code, out = self.run_main("--plan", "1-3", "--start", "2026-10-02")
        self.assertEqual((code, self.uploads), (0, []))
        self.assertIn("Расписание (3)", out)
        self.assertIn("отменено", out)
        self.assertFalse(self.published.exists())

    def test_answer_yes_uploads(self):
        with patch("builtins.input", return_value="y"):
            self.run_main("--plan", "1-3", "--start", "2026-10-02")
        self.assertEqual(len(self.uploads), 3)

    def test_start_in_the_past(self):
        with self.assertRaises(SystemExit):
            self.run_main("--plan", "1-3", "--start", "2026-09-29", "--yes")
        self.assertEqual(self.uploads, [])

    def test_dry_writes_nothing_and_skips_network(self):
        def snapshot():
            return {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in self.tmp.rglob("*")}

        def no_network(*a, **kw):
            raise AssertionError("--dry не должен ходить в YouTube")

        before = snapshot()
        out = io.StringIO()
        with patch.object(pb, "connect", no_network), patch.object(pb, "upload", no_network), \
                patch("builtins.input", no_network), redirect_stdout(out):
            code = pb.main(["--plan", "1-6", "--start", "2026-10-02", "--dry"])
        self.assertEqual(code, 0)
        self.assertEqual(snapshot(), before)
        self.assertFalse(self.published.exists())
        text = out.getvalue()
        self.assertIn("Расписание (6)", text)
        self.assertIn('"publishAt": "2026-10-02T16:30:00Z"', text)
        self.assertEqual(text.count('"containsSyntheticMedia": true'), 6)


class ChannelTests(Base):
    def test_foreign_channel_is_refused(self):
        with self.assertRaises(SystemExit) as cm:
            pb.check_channel(FakeYouTube(title="Facts Daily"))
        self.assertIn("Facts Daily", str(cm.exception))
        pb.check_channel(FakeYouTube())  # свой — без ошибки

    def test_foreign_token_uploads_nothing(self):
        import youtube_auth
        out = io.StringIO()
        with patch.dict(os.environ, {"YT_TOKEN_BABY": "fake"}), \
                patch.object(youtube_auth, "get_client", lambda token, channel=None: FakeYouTube(title="Datos")), \
                patch.object(pb, "upload", self.fake_upload), redirect_stdout(out):
            with self.assertRaises(SystemExit) as cm:
                pb.main(["--plan", "1-3", "--start", "2026-10-02", "--yes"])
        self.assertIn("другого канала", str(cm.exception))
        self.assertEqual(self.uploads, [])
        self.assertFalse(self.published.exists())

    def test_channel_names_from_tags(self):
        youtube = FakeYouTube(videos=[{"id": "a", "tags": ["s-serious_lecture"]}, {"id": "b", "tags": ["x"]}])
        self.assertEqual(pb.channel_names(youtube), {"serious_lecture"})


class SingleTests(Base):
    def test_single_upload_records_published(self):
        code, out = self.run_main("banana_big_bite", "--at", "2026-10-01 19:30")
        self.assertEqual(code, 0)
        self.assertEqual(self.uploads[0][0]["status"]["publishAt"], "2026-10-01T16:30:00Z")
        self.assertEqual(self.published_rows()[0]["name"], "banana_big_bite")

    def test_single_already_published_or_on_channel(self):
        self.write_published([["banana_big_bite", "v1", "2026-10-01T16:30:00Z", ""]])
        with self.assertRaises(SystemExit):
            self.run_main("banana_big_bite", "--at", "2026-10-02 19:30")
        youtube = FakeYouTube(videos=[{"id": "v2", "tags": ["s-serious_lecture"]}])
        with self.assertRaises(SystemExit):
            self.run_main("serious_lecture", "--now", youtube=youtube)
        self.assertEqual(self.uploads, [])

    def test_single_dry_writes_nothing(self):
        code, out = self.run_main("banana_big_bite", "--at", "2026-10-01 19:30", "--dry")
        self.assertEqual((code, self.uploads), (0, []))
        self.assertIn('"publishAt": "2026-10-01T16:30:00Z"', out)
        self.assertFalse(self.published.exists())

    def test_plan_and_name_conflict(self):
        with redirect_stdout(io.StringIO()), patch("sys.stderr", io.StringIO()):
            for argv in (["banana_big_bite", "--plan", "1-3", "--start", "2026-10-02"],
                         ["--plan", "1-3"], ["--dry"]):
                with self.assertRaises(SystemExit):
                    pb.main(argv)


if __name__ == "__main__":
    unittest.main()
