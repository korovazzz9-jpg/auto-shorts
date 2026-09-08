"""Free stock adapters and fixed-size blended selection; no external calls."""
import json
import os
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
import unittest
import requests
import test_clip_selection_offline as base
stock = base.stock


def response(payload):
    return NS(json=lambda: payload, raise_for_status=lambda: None)


def pix(id=7, thumbnail="https://invalid/poster.jpg", width=1080, height=1920):
    return {"id": id, "videos": {"large": {"url": "https://invalid/video.mp4", "width": width,
            "height": height, "thumbnail": thumbnail}}}


class StockSourcesTests(unittest.TestCase):
    setUp = base.SelectionTests.setUp
    response = base.SelectionTests.response

    def test_pixabay_uses_thumbnail_and_namespaces_ids(self):
        with patch.object(stock, "LANDSCAPE", False), patch.object(stock.requests, "get", return_value=response({"hits": [pix()]})):
            rows = stock._search_pixabay("bird", "dummy", {7}, 4)
        self.assertEqual(rows[0]["id"], "pixabay:7")
        self.assertEqual(rows[0]["preview"], "https://invalid/poster.jpg")
        create = self.response('{"approved":[1]}')
        self.assertEqual(stock._accepted_clips(rows, "bird")[1], "vetted")
        create.assert_called_once()

    def test_pixabay_fallback_thumbnail_same_clip(self):
        hit = pix(thumbnail=None)
        hit["videos"]["tiny"] = {"url": "https://invalid/tiny", "width": 270, "height": 480, "thumbnail": "https://invalid/tiny.jpg"}
        with patch.object(stock, "LANDSCAPE", False), patch.object(stock.requests, "get", return_value=response({"hits": [hit]})):
            rows = stock._search_pixabay("bird", "dummy", set(), 4)
        self.assertEqual(rows[0]["preview"], "https://invalid/tiny.jpg")
        self.assertEqual(rows[0]["link"], "https://invalid/video.mp4")

    def test_sources_share_four_posters_and_one_vision_call(self):
        def pool(source, query, key, fn):
            return [dict(id=f"{source}:{i}", source=source, link=f"https://invalid/{source}/{i}", preview="https://invalid/p") for i in range(5)]
        with patch.dict(os.environ, {"PEXELS_API_KEY": "p", "PIXABAY_API_KEY": "x", "COVERR_API_KEY": "c"}), patch.object(stock, "_source_pool", side_effect=pool):
            rows = stock._get_candidates("bird", set())
        self.assertEqual([r["source"] for r in rows], ["pexels", "pixabay", "coverr", "pexels"])
        create = self.response('{"approved":[1,2,3,4]}')
        stock._accepted_clips(rows, "bird")
        create.assert_called_once()
        content = create.call_args.kwargs["messages"][0]["content"]
        self.assertEqual(sum(c["type"] == "image" for c in content), 4)

    def test_one_provider_error_does_not_block_another(self):
        def pool(source, *args):
            if source == "pexels":
                raise requests.HTTPError("secret URL must not leak")
            return [dict(id="pixabay:7", link="https://invalid/v", preview="https://invalid/p")]
        with patch.dict(os.environ, {"PEXELS_API_KEY": "p", "PIXABAY_API_KEY": "x", "COVERR_API_KEY": ""}), patch.object(stock, "_source_pool", side_effect=pool), patch("builtins.print") as log:
            rows = stock._get_candidates("bird", set())
        self.assertEqual(rows[0]["id"], "pixabay:7")
        self.assertEqual(stock.selection_stats()["source_errors"], {"pexels": 1})
        self.assertNotIn("secret URL", str(log.call_args_list))

    def test_24_hour_cache_excludes_keys_and_used_ids_later(self):
        file = str(Path(self.tmp.name) / "search.json")
        search = Mock(return_value=[dict(id="pixabay:7", preview="https://invalid/p", link="https://invalid/v")])
        with patch.object(stock, "_STOCK_CACHE_FILE", file):
            stock._source_pool("pixabay", "bird", "secret-key", search)
            stock._source_pool("pixabay", "bird", "secret-key", search)
            search.assert_called_once()
            self.assertNotIn("secret-key", Path(file).read_text())
            payload = json.loads(Path(file).read_text())
            for entry in payload.values(): entry["ts"] -= 86401
            Path(file).write_text(json.dumps(payload))
            stock._source_pool("pixabay", "bird", "secret-key", search)
            self.assertEqual(search.call_count, 2)

    def test_missing_coverr_key_means_no_call(self):
        with patch.dict(os.environ, {"PEXELS_API_KEY": "", "PIXABAY_API_KEY": "", "COVERR_API_KEY": ""}), patch.object(stock, "_source_pool") as pool:
            self.assertEqual(stock._get_candidates("bird", set()), [])
        pool.assert_not_called()

    def test_coverr_persists_no_signed_download_url(self):
        hit = {"id": "abc", "poster": "https://invalid/poster", "max_width": 1080, "max_height": 1920,
               "urls": {"mp4_download": "https://invalid/video?token=secret"}}
        with patch.object(stock, "LANDSCAPE", False), patch.object(stock.requests, "get", return_value=response({"hits": [hit]})) as get:
            rows = stock._search_coverr("bird", "key", set(), 4)
        self.assertNotIn("token=", json.dumps(rows))
        self.assertNotIn("urls", get.call_args.kwargs["params"])
        self.assertEqual(rows[0]["id"], "coverr:abc")
        with patch.dict(os.environ, {"COVERR_API_KEY": "key"}), patch.object(stock.requests, "get", return_value=response(hit)) as get:
            self.assertEqual(stock._download_url(rows[0]), hit["urls"]["mp4_download"])
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer key")

    def test_missing_posters_are_filtered_before_budget(self):
        def pool(source, *args):
            return [dict(id=i, preview=None, link="bad") for i in range(4)] + [dict(id=8, preview="https://invalid/p", link="good")]
        with patch.dict(os.environ, {"PEXELS_API_KEY": "p", "PIXABAY_API_KEY": "", "COVERR_API_KEY": ""}), patch.object(stock, "_source_pool", side_effect=pool):
            self.assertEqual(stock._get_candidates("bird", {9})[0]["id"], 8)


if __name__ == "__main__":
    unittest.main()
