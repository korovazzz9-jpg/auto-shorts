"""Скачивает вертикальные стоковые видеоклипы по ключевым словам через Pexels API (бесплатно)."""
from __future__ import annotations

import os
import tempfile

import requests
from anthropic import Anthropic

PEXELS_SEARCH_URL = "https://api.pexels.com/videos/search"
PIXABAY_SEARCH_URL = "https://pixabay.com/api/videos/"
RESULTS_PER_QUERY = 10
VISION_CANDIDATES = 4  # сколько клипов скачиваем для vision-отбора
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


def _search_pexels(query: str, api_key: str, used_ids: set, limit: int) -> list[dict]:
    response = requests.get(
        PEXELS_SEARCH_URL,
        params={"query": query, "orientation": "portrait", "per_page": RESULTS_PER_QUERY},
        headers={"Authorization": api_key},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    results = []
    for v in data.get("videos", []):
        if v["id"] in used_ids:
            continue
        file = _best_vertical_file(v)
        if file:
            # v["image"] — готовый poster-кадр клипа, используем для vision-отбора без скачивания.
            results.append({"link": file["link"], "id": v["id"], "preview": v.get("image")})
        if len(results) >= limit:
            break
    return results


def _best_pixabay_variant(hit: dict) -> dict | None:
    variants = [v for v in hit.get("videos", {}).values() if v.get("url")]
    variants = [v for v in variants if v.get("height", 0) >= v.get("width", 1) and v.get("height", 0) >= MIN_HEIGHT]
    if not variants:
        return None
    variants.sort(key=lambda v: abs(v.get("height", 0) - 1920))
    return variants[0]


def _search_pixabay(query: str, api_key: str, used_ids: set, limit: int) -> list[dict]:
    response = requests.get(
        PIXABAY_SEARCH_URL,
        params={"key": api_key, "q": query, "per_page": RESULTS_PER_QUERY, "safesearch": "true"},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    results = []
    for hit in data.get("hits", []):
        if hit["id"] in used_ids:
            continue
        file = _best_pixabay_variant(hit)
        if file:
            # Pixabay не отдаёт прямой poster-URL — preview=None, такие кандидаты в vision не идут.
            results.append({"link": file["url"], "id": hit["id"], "preview": None})
        if len(results) >= limit:
            break
    return results


def _get_candidates(query: str, used_ids: set) -> list[dict]:
    """Собирает до VISION_CANDIDATES кандидатов из Pexels и Pixabay."""
    candidates = []
    pexels_key = os.environ.get("PEXELS_API_KEY")
    if pexels_key:
        candidates += _search_pexels(query, pexels_key, used_ids, VISION_CANDIDATES)

    if len(candidates) < VISION_CANDIDATES:
        pixabay_key = os.environ.get("PIXABAY_API_KEY")
        if pixabay_key:
            need = VISION_CANDIDATES - len(candidates)
            candidates += _search_pixabay(query, pixabay_key, used_ids, need)

    return candidates[:VISION_CANDIDATES]


def _pick_best_clip(candidates: list[dict], query: str) -> dict | None:
    """Отбирает лучший клип по poster-кадрам (Pexels image URL) через Claude Haiku —
    БЕЗ скачивания видео. Качается потом только победитель (в fetch_clips)."""
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    # Vision возможен только если у всех кандидатов есть preview-кадр (Pexels).
    # Если хоть у одного нет (Pixabay) — берём первый по релевантности от стока.
    with_preview = [c for c in candidates if c.get("preview")]
    if len(with_preview) < 2:
        return candidates[0]

    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    content = [{"type": "text", "text": (
        f"I need a stock video clip that visually matches: \"{query}\"\n\n"
        f"Here are {len(with_preview)} candidate clips (numbered 1 to {len(with_preview)}). "
        f"Pick the one whose footage best fits that description. Reply with ONLY the number."
    )}]
    for idx, c in enumerate(with_preview, 1):
        content.append({"type": "text", "text": f"Clip {idx}:"})
        content.append({"type": "image", "source": {"type": "url", "url": c["preview"]}})

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{"role": "user", "content": content}],
        )
        pick = int(response.content[0].text.strip()[0]) - 1
        pick = max(0, min(pick, len(with_preview) - 1))
        print(f"  Vision picked clip {pick + 1}/{len(with_preview)} for '{query}'")
        return with_preview[pick]
    except Exception:
        return with_preview[0]


def _search_with_fallback(query: str, used_ids: set) -> dict | None:
    candidates = _get_candidates(query, used_ids)
    if not candidates:
        short = " ".join(query.split()[:2])
        if short != query:
            candidates = _get_candidates(short, used_ids)
            if candidates:
                print(f"  (simplified query '{query}' → '{short}')")
    if not candidates:
        return None
    return _pick_best_clip(candidates, query)


def fetch_clips(queries: list[str], out_dir: str) -> list[str]:
    paths = []
    used_ids: set = set()
    for i, query in enumerate(queries):
        file_info = _search_with_fallback(query, used_ids)
        if not file_info:
            print(f"  (no clip found for '{query}', skipping)")
            continue
        used_ids.add(file_info["id"])
        out_path = os.path.join(out_dir, f"clip_{i}.mp4")
        video_response = requests.get(file_info["link"], timeout=60)
        video_response.raise_for_status()
        with open(out_path, "wb") as f:
            f.write(video_response.content)
        paths.append(out_path)
    return paths


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        print(fetch_clips(["ocean waves", "ancient ruins"], tmp))
