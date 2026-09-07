"""Скачивает вертикальные стоковые видеоклипы по ключевым словам через Pexels API (бесплатно)."""
from __future__ import annotations

import json
import os
import re
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
# 2026-09-07: версия схемы отбора. Записи, сделанные ПРЕЖНИМ принудительным отбором («выбери
# лучший из этих», без права отказа), не должны проходить как одобренные новым фильтром — TTL
# 7 дней иначе тащил бы старые решения ещё неделю и смазал бы замер эффекта. Бампать при
# КАЖДОМ изменении промпта отбора, иначе эксперимент меряет смесь старого и нового.
_VISION_CACHE_VERSION = 2


def _load_vision_cache() -> dict:
    try:
        with open(_VISION_CACHE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _vision_cache_get(query: str, candidates: list[dict]) -> list[dict] | None:
    """Одобренные клипы из кэша, в порядке предпочтения. Запись чужой версии отбора — miss."""
    entry = _load_vision_cache().get(query)
    if not isinstance(entry, dict) or entry.get("v") != _VISION_CACHE_VERSION:
        return None
    try:
        age = time.time() - float(entry.get("ts", 0))
    except (TypeError, ValueError):
        return None
    if age > _VISION_CACHE_TTL_DAYS * 86400:
        return None
    # Клипы должны быть среди ТЕКУЩИХ кандидатов (used_ids уже отфильтрованы) — иначе miss.
    by_id = {c["id"]: c for c in candidates}
    hits = [by_id[i] for i in entry.get("ids", []) if i in by_id]
    return hits or None


def _vision_cache_put(query: str, clip_ids: list) -> None:
    cache = _load_vision_cache()
    cache[query] = {"ids": list(clip_ids), "ts": time.time(), "v": _VISION_CACHE_VERSION}
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


def _accepted_clips(candidates: list[dict], query: str) -> list[dict]:
    """Клипы, которые Haiku признал показывающими `query`, в порядке предпочтения. Отбор идёт
    по poster-кадрам (Pexels image URL), БЕЗ скачивания видео.

    Пустой список = ни один кандидат не подходит. 2026-09-07: раньше такого исхода не было —
    промпт требовал «pick the one that best fits», и модель обязана была назвать номер, даже
    когда все клипы мимо (отсюда жираф в ролике про птицу, охотящуюся на змей).

    Возвращаем ВСЕ одобренные, а не одного победителя: `fetch_clips` при битом файле берёт
    следующего из списка, и при возврате одного победителя запасные шли в ролик вообще без
    проверки — дыра ровно того же размера, что и исходная (найдено на ревью 2026-09-07)."""
    if not candidates:
        return []

    # Vision требует preview-кадра (есть у Pexels, нет у Pixabay). Раньше при <2 превью
    # брали первый ВСЛЕПУЮ — теперь одиночного кандидата тоже показываем модели: проверить
    # «то или не то» можно и на одном, это дешевле одного мимо-кадра в ролике.
    with_preview = [c for c in candidates if c.get("preview")]
    if not with_preview:
        return candidates  # проверять нечем — отдаём порядок релевантности стока

    cached = _vision_cache_get(query, with_preview)
    if cached:
        print(f"  Vision cache hit for '{query}' — без вызова Haiku")
        return cached

    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    content = [{"type": "text", "text": (
        f"I need a stock video clip that visually shows: \"{query}\"\n\n"
        f"Here are {len(with_preview)} candidate clips (numbered 1 to {len(with_preview)}).\n"
        "Reply with the numbers of EVERY clip that genuinely shows that subject or scene, "
        "best first, comma-separated (for example: 3,1).\n"
        "If NONE of them do — if the closest match is merely a loosely related or generic "
        "scene — reply 0 instead. A wrong clip is worse than no clip here: a clip showing the "
        "wrong animal or object breaks the promise the narration just made."
    )}]
    for idx, c in enumerate(with_preview, 1):
        content.append({"type": "text", "text": f"Clip {idx}:"})
        content.append({"type": "image", "source": {"type": "url", "url": c["preview"]}})

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=20,
            messages=[{"role": "user", "content": content}],
        )
        raw = response.content[0].text.strip()
    except Exception as e:
        # Сбой API — это отсутствие информации, а не суждение «не подходит». Держим прежнее
        # поведение (порядок стока), но НЕ молча: раньше эта ветка была невидима.
        print(f"  (vision-отбор для '{query}' упал: {e} — берём порядок релевантности)")
        return with_preview

    # Полные числа, а не первый символ: `int(raw[0])` ломался на ответе вида "Clip 3"
    # (ValueError → тихий фолбэк на первый клип) и прочитал бы "10" как "1".
    nums = [int(n) for n in re.findall(r"\d+", raw)]
    if not nums:
        print(f"  (vision вернул неразбираемое '{raw}' для '{query}' — порядок релевантности)")
        return with_preview
    if nums[0] == 0:
        print(f"  Vision: ни один из {len(with_preview)} клипов не показывает '{query}'")
        return []

    seen, accepted = set(), []
    for n in nums:
        if 1 <= n <= len(with_preview) and n not in seen:
            seen.add(n)
            accepted.append(with_preview[n - 1])
    if not accepted:
        print(f"  (vision назвал только номера вне диапазона ('{raw}') для '{query}' — порядок релевантности)")
        return with_preview

    print(f"  Vision одобрил {len(accepted)}/{len(with_preview)} клипов для '{query}'")
    try:  # кэшируем только реальный vision-выбор (не фолбэки) — сбой кэша не роняет пайплайн
        _vision_cache_put(query, [c["id"] for c in accepted])
    except Exception as e:
        print(f"  (vision cache write failed: {e})")
    return accepted


def _search_with_fallback(query: str, used_ids: set) -> list[dict]:
    """Только ОДОБРЕННЫЕ vision клипы, в порядке предпочтения (2026-07-13: список, а не один
    победитель — если его файл окажется битым на CDN, нужен запасной, иначе слот публикации
    теряется). 2026-09-07: запасные теперь тоже проходят проверку — раньше сюда добавлялись
    все прочие кандидаты, и при битом победителе в ролик уходил непроверенный клип."""
    short = " ".join(query.split()[:2])
    candidates = _get_candidates(query, used_ids)
    if not candidates and short != query:
        candidates = _get_candidates(short, used_ids)
        if candidates:
            print(f"  (simplified query '{query}' → '{short}')")
    if not candidates:
        return []

    accepted = _accepted_clips(candidates, query)
    # Vision может отвергнуть ВСЕХ. Прежде чем оставлять бит без картинки, пробуем упрощённый
    # запрос — узкий («archerfish spitting water») часто не находится на стоке вовсе, а
    # широкий («archerfish») находится.
    if not accepted and short != query:
        alt = _get_candidates(short, used_ids)
        if alt:
            print(f"  (все клипы мимо, пробуем '{short}')")
            accepted = _accepted_clips(alt, short)
    if not accepted:
        print(f"  (подходящего клипа для '{query}' нет — бит останется без своего плана)")
    return accepted


def _is_valid_clip(path: str) -> bool:
    """Проверяет, что скачанный файл — читаемое видео (2026-07-13, реальный прод-случай:
    CDN отдал битый mp4, HTTP 200 — скачивание «успешно», а MoviePy упал на первом кадре
    уже в сборке, потеряв слот публикации). Открытие VideoFileClip читает первый кадр —
    ровно та же проверка, на которой падала сборка, только теперь в момент скачивания,
    пока ещё есть запасные кандидаты."""
    try:
        from moviepy.editor import VideoFileClip
        clip = VideoFileClip(path)
        ok = (clip.duration or 0) > 0.1
        clip.close()
        return ok
    except Exception as e:
        print(f"  (клип не читается: {e})")
        return False


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
        # Поиск изолирован так же, как скачивание ниже (2026-07-10, фикс с ревью): раньше
        # транзиентный 429/5xx от Pexels/Pixabay (raise_for_status в _search_*) пролетал
        # наверх и ронял ВЕСЬ слот публикации из-за одного неудачного запроса. Пустой
        # итоговый список по-прежнему ловит guard в build_video/_build_background.
        try:
            ranked = _search_with_fallback(query, used_ids)
        except Exception as e:
            print(f"  (поиск стока для '{query}' упал: {e}, пропускаем запрос)")
            continue
        if not ranked:
            print(f"  (no clip found for '{query}', skipping)")
            continue
        out_path = os.path.join(out_dir, f"clip_{i}.mp4")
        # Кандидаты пробуются по порядку (победитель vision → запасные), каждый скачанный
        # файл валидируется чтением первого кадра (2026-07-13): битый файл от CDN больше
        # не долетает до сборки — берём следующего кандидата. id заносится в used_ids для
        # КАЖДОГО испробованного (битый клип не должен достаться другому запросу).
        for n, file_info in enumerate(ranked):
            used_ids.add(file_info["id"])
            try:
                video_response = requests.get(file_info["link"], timeout=60)
                video_response.raise_for_status()
                with open(out_path, "wb") as f:
                    f.write(video_response.content)
            except Exception as e:
                print(f"  (не скачался клип для '{query}': {e}, пробуем следующего кандидата)")
                continue
            if not _is_valid_clip(out_path):
                print(f"  (битый файл клипа {file_info['id']} для '{query}' — пробуем следующего кандидата)")
                try:
                    os.remove(out_path)
                except OSError:
                    pass
                continue
            if n > 0:
                print(f"  ('{query}': победитель не годился, взят запасной кандидат #{n + 1})")
            paths.append(out_path)
            break
        else:
            print(f"  (все кандидаты для '{query}' не скачались/битые, пропускаем запрос)")

    # 2026-09-07: страховка от потери слота. Отказ vision по ОДНОМУ запросу безобиден —
    # `_build_background` делит длительность между оставшимися клипами. Но если отвергнуты
    # ВСЕ, список пуст, и там стоит `raise RuntimeError("Нет стоковых клипов...")` — то есть
    # публикация теряется целиком. Здесь качество уступает выпуску: добираем без вето vision,
    # по порядку релевантности стока, и говорим об этом громко (ролик выйдет с картинкой
    # похуже, но выйдет). Тихо это делать нельзя — иначе замер эффекта фильтра врёт.
    if not paths and queries:
        print("  ⚠️ vision отверг клипы по ВСЕМ запросам — добираем без вето, иначе слот потерян")
        for i, query in enumerate(queries):
            try:
                relaxed = _get_candidates(query, used_ids)
            except Exception as e:
                print(f"  (повторный поиск для '{query}' упал: {e})")
                continue
            for file_info in relaxed:
                used_ids.add(file_info["id"])
                out_path = os.path.join(out_dir, f"clip_relaxed_{i}.mp4")
                try:
                    r = requests.get(file_info["link"], timeout=60)
                    r.raise_for_status()
                    with open(out_path, "wb") as f:
                        f.write(r.content)
                except Exception:
                    continue
                if _is_valid_clip(out_path):
                    paths.append(out_path)
                    break
                try:
                    os.remove(out_path)
                except OSError:
                    pass
            if paths:  # одного клипа достаточно, чтобы сборка не упала
                break
    return paths


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        print(fetch_clips(["ocean waves", "ancient ruins"], tmp))
