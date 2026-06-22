"""Скачивает вертикальные стоковые видеоклипы по ключевым словам через Pexels API (бесплатно)."""
from __future__ import annotations

import os

import requests

SEARCH_URL = "https://api.pexels.com/videos/search"


def _best_vertical_file(video: dict) -> dict | None:
    files = [f for f in video["video_files"] if f.get("height", 0) >= f.get("width", 1)]
    if not files:
        return None
    files.sort(key=lambda f: abs(f.get("height", 0) - 1920))
    return files[0]


def _search(query: str, api_key: str) -> dict | None:
    response = requests.get(
        SEARCH_URL,
        params={"query": query, "orientation": "portrait", "per_page": 5},
        headers={"Authorization": api_key},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    for video in data.get("videos", []):
        chosen = _best_vertical_file(video)
        if chosen:
            return chosen
    return None


def fetch_clips(queries: list[str], out_dir: str) -> list[str]:
    api_key = os.environ["PEXELS_API_KEY"]
    paths = []
    for i, query in enumerate(queries):
        file_info = _search(query, api_key)
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
