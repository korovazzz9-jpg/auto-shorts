"""Скачивает вертикальные стоковые видеоклипы по ключевым словам через Pexels API (бесплатно)."""
from __future__ import annotations

import os
import random

import requests

PEXELS_SEARCH_URL = "https://api.pexels.com/videos/search"
PIXABAY_SEARCH_URL = "https://pixabay.com/api/videos/"
RESULTS_PER_QUERY = 10
MIN_HEIGHT = 960  # ниже этого — слишком мутно для полноэкранного Shorts-видео


def _best_vertical_file(video: dict) -> dict | None:
    files = [
        f for f in video["video_files"]
        if f.get("height", 0) >= f.get("width", 1) and f.get("height", 0) >= MIN_HEIGHT
    ]
    if not files:
        return None
    files.sort(key=lambda f: abs(f.get("height", 0) - 1920))
    return files[0]


def _search_pexels(query: str, api_key: str) -> dict | None:
    # Pexels returns the same top results for a given query every time, so picking
    # a random candidate (instead of always the first) keeps opening frames from
    # repeating across videos that use similar search terms.
    response = requests.get(
        PEXELS_SEARCH_URL,
        params={"query": query, "orientation": "portrait", "per_page": RESULTS_PER_QUERY},
        headers={"Authorization": api_key},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    candidates = [_best_vertical_file(v) for v in data.get("videos", [])]
    candidates = [c for c in candidates if c]
    if not candidates:
        return None
    return {"link": random.choice(candidates)["link"]}


def _best_pixabay_variant(hit: dict) -> dict | None:
    variants = [v for v in hit.get("videos", {}).values() if v.get("url")]
    variants = [v for v in variants if v.get("height", 0) >= v.get("width", 1) and v.get("height", 0) >= MIN_HEIGHT]
    if not variants:
        return None
    variants.sort(key=lambda v: abs(v.get("height", 0) - 1920))
    return variants[0]


def _search_pixabay(query: str, api_key: str) -> dict | None:
    response = requests.get(
        PIXABAY_SEARCH_URL,
        params={"key": api_key, "q": query, "per_page": RESULTS_PER_QUERY, "safesearch": "true"},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    candidates = [_best_pixabay_variant(hit) for hit in data.get("hits", [])]
    candidates = [c for c in candidates if c]
    if not candidates:
        return None
    return {"link": random.choice(candidates)["url"]}


def _search(query: str) -> dict | None:
    pexels_key = os.environ.get("PEXELS_API_KEY")
    if pexels_key:
        result = _search_pexels(query, pexels_key)
        if result:
            return result

    pixabay_key = os.environ.get("PIXABAY_API_KEY")
    if pixabay_key:
        result = _search_pixabay(query, pixabay_key)
        if result:
            print(f"  (fallback to Pixabay for '{query}')")
            return result

    return None


def fetch_clips(queries: list[str], out_dir: str) -> list[str]:
    paths = []
    for i, query in enumerate(queries):
        file_info = _search(query)
        if not file_info:
            continue
        out_path = os.path.join(out_dir, f"clip_{i}.mp4")
        video_response = requests.get(file_info["link"], timeout=60)
        video_response.raise_for_status()
        with open(out_path, "wb") as f:
            f.write(video_response.content)
        paths.append(out_path)
    return paths


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        print(fetch_clips(["ocean waves", "ancient ruins"], tmp))
