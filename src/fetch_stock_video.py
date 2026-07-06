"""Скачивает вертикальные стоковые видеоклипы по ключевым словам через Pexels API (бесплатно)."""
from __future__ import annotations

import json
import os
import tempfile
import time

import requests
from anthropic import Anthropic

PEXELS_SEARCH_URL = "https://api.pexels.com/videos/search"
PIXABAY_SEARCH_URL = "https://pixabay.com/api/videos/"
RESULTS_PER_QUERY = 10
VISION_CANDIDATES = 4  # сколько клипов скачиваем для vision-отбора
MIN_HEIGHT = 960  # ниже этого — слишком мутно для полноэкранного Shorts-видео
MIN_WIDTH = 1280  # для горизонтального лонгформа — минимум по ширине

# Кэш vision-выбора: запрос → id уже одобренного Haiku клипа. Стоковые запросы повторяются
# между видео ("ocean waves", "ancient ruins"...) — не дёргаем vision заново за тот же выбор.
# Vision — главный Claude-расход после генерации скриптов; кэш срезает повторные вызовы с
# нулевым риском качества. TTL 7 дней — чтобы визуал не прирастал к одному клипу навечно.
# Файл персистится через actions/cache (та же связка, что titles/topics cache).
_VISION_CACHE_FILE = os.path.join(os.path.dirname(__file__), "vision_cache.json")
_VISION_CACHE_TTL_DAYS = 7
_VISION_CACHE_MAX = 300


def _load_vision_cache() -> dict:
    try:
        with open(_VISION_CACHE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _vision_cache_get(query: str, candidates: list[dict]) -> dict | None:
    entry = _load_vision_cache().get(query)
    if not isinstance(entry, dict):
        return None
    try:
        age = time.time() - float(entry.get("ts", 0))
    except (TypeError, ValueError):
        return None
    if age > _VISION_CACHE_TTL_DAYS * 86400:
        return None
    # Клип должен быть среди ТЕКУЩИХ кандидатов (used_ids уже отфильтрованы) — иначе miss.
    return next((c for c in candidates if c["id"] == entry.get("id")), None)


def _vision_cache_put(query: str, clip_id) -> None:
    cache = _load_vision_cache()
    cache[query] = {"id": clip_id, "ts": time.time()}
    if len(cache) > _VISION_CACHE_MAX:  # не даём файлу расти бесконечно
        for k, _ in sorted(cache.items(), key=lambda kv: kv[1].get("ts", 0))[:len(cache) - _VISION_CACHE_MAX]:
            del cache[k]
    with open(_VISION_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

# Ориентация скачиваемых клипов. По умолчанию вертикаль (Shorts); fetch_clips(landscape=True)
# переключает на горизонталь (лонгформ 16:9). Модульный флаг, чтобы не тащить параметр
# через всю цепочку поиска.
LANDSCAPE = False


def _orientation_ok(w: int, h: int) -> bool:
    if LANDSCAPE:
        return w >= h and w >= MIN_WIDTH
    return h >= w and h >= MIN_HEIGHT


def _long_side(f: dict) -> int:
    return f.get("width", 0) if LANDSCAPE else f.get("height", 0)


def _best_vertical_file(video: dict) -> dict | None:
    files = [
        f for f in video["video_files"]
        if _orientation_ok(f.get("width", 1), f.get("height", 0))
    ]
    if not files:
        return None
    files.sort(key=lambda f: abs(_long_side(f) - 1920))
    return files[0]


def _search_pexels(query: str, api_key: str, used_ids: set, limit: int) -> list[dict]:
    response = requests.get(
        PEXELS_SEARCH_URL,
        params={"query": query, "orientation": "landscape" if LANDSCAPE else "portrait",
                "per_page": RESULTS_PER_QUERY},
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
    variants = [v for v in variants if _orientation_ok(v.get("width", 1), v.get("height", 0))]
    if not variants:
        return None
    variants.sort(key=lambda v: abs(_long_side(v) - 1920))
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

    cached = _vision_cache_get(query, with_preview)
    if cached:
        print(f"  Vision cache hit for '{query}' — без вызова Haiku")
        return cached

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
        try:  # кэшируем только реальный vision-выбор (не фолбэки) — сбой кэша не роняет пайплайн
            _vision_cache_put(query, with_preview[pick]["id"])
        except Exception as e:
            print(f"  (vision cache write failed: {e})")
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


# Залипательные («satisfying») фоны для VN-формата random-facts. Все запросы проверены
# по Pexels-API (отдают 15/15 вертикальных клипов ≥960px). Фон НЕ обязан совпадать с темой
# факта — берём любой залипательный, он держит completion (главный сигнал TikTok-алгоритма).
SATISFYING_QUERIES = [
    # Оригинальный набор (проверен на Pexels).
    "kinetic sand cutting", "slime", "paint mixing", "soap cutting", "fluid art",
    "marble run", "ink in water", "honey pouring", "sand art", "color paint swirl",
    "glass blowing", "water ripple", "lava lamp", "cake icing", "candle making",
    "pottery clay wheel", "powder explosion color", "oddly satisfying", "liquid paint flow",
    # Расширение 2026-07-06 (пул был мал → фоны повторялись): краски/жидкости,
    # ремёсла, природа-текстуры, еда-процессы. Все — обобщённые satisfying-запросы,
    # массово представленные вертикальными клипами на Pexels/Pixabay.
    "acrylic pour painting", "oil and water macro", "colored smoke", "bubbles macro",
    "water drop slow motion", "milk swirl", "watercolor bleeding", "resin art pouring",
    "melting wax", "molten glass", "metal casting", "blacksmith forging",
    "latte art pouring", "chocolate melting", "caramel drizzle", "dough kneading",
    "espresso pouring", "icing cookies", "sushi rolling", "knife sharpening",
    "wood carving", "wood shaving", "leather tooling", "calligraphy writing",
    "spray paint art", "sand falling", "hydraulic press crushing", "gears turning",
    "domino falling", "zen sand garden", "flower blooming timelapse", "jelly wobble",
    "foam texture", "honey dripping macro", "clay sculpting hands", "neon lights bokeh",
]


def fetch_satisfying_clips(count: int, out_dir: str) -> list[str]:
    """Качает `count` залипательных вертикальных клипов из случайных satisfying-запросов
    (vision-отбор выбирает лучший по постер-кадру). Для VN random-facts формата."""
    import random
    n = min(count, len(SATISFYING_QUERIES))
    queries = random.sample(SATISFYING_QUERIES, n)
    return fetch_clips(queries, out_dir)


def fetch_clips(queries: list[str], out_dir: str, landscape: bool = False) -> list[str]:
    global LANDSCAPE
    LANDSCAPE = landscape
    paths = []
    used_ids: set = set()
    for i, query in enumerate(queries):
        file_info = _search_with_fallback(query, used_ids)
        if not file_info:
            print(f"  (no clip found for '{query}', skipping)")
            continue
        used_ids.add(file_info["id"])
        out_path = os.path.join(out_dir, f"clip_{i}.mp4")
        # Скачивание одного клипа изолировано: транзиентный сбой CDN на одном клипе не должен
        # ронять весь fetch_clips (иначе теряется всё видео из-за одного битого клипа). Пустой
        # итоговый список ловит guard в build_video/_build_background с понятной ошибкой.
        try:
            video_response = requests.get(file_info["link"], timeout=60)
            video_response.raise_for_status()
            with open(out_path, "wb") as f:
                f.write(video_response.content)
            paths.append(out_path)
        except Exception as e:
            print(f"  (не скачался клип для '{query}': {e}, пропускаем)")
            continue
    return paths


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        print(fetch_clips(["ocean waves", "ancient ruins"], tmp))
