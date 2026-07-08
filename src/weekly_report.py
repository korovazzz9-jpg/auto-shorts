"""Еженедельная retention-сводка (хук-шаблоны, петля, темы) в Telegram.
Не тратит Claude — только YouTube Analytics/Data API (переиспользует
_recent_videos/_retention из analytics_retention.py). Запуск:
  python weekly_report.py            # EN
  CHANNEL=es python weekly_report.py # ES
"""
import json
import os
from datetime import date

from dotenv import load_dotenv

from analytics_retention import _recent_videos, _retention, _retention_curve, biggest_drop, retention_threshold
from config import CFG, CHANNEL
from notify import notify
from video_history import enrich_with_performance
from youtube_auth import get_analytics_client, get_client

load_dotenv()

HOOK_STATS_FILE = os.path.join(os.path.dirname(__file__), "..", f"hook_stats_{CHANNEL}.json")
MIN_HOOK_SAMPLE = 5  # меньше видео на шаблон — рано делать выводы, файл не пишем


def _avg_by(videos: list[dict], key: str, min_pct: float = 0.0) -> list[tuple[str, float, int]]:
    """Средний % досмотра, сгруппированный по video[key]. Видео без данных (pct<=min_pct)
    исключены — иначе свежие ролики (лаг Analytics) занижают среднее нулями."""
    groups: dict[str, list[float]] = {}
    for v in videos:
        if v["pct"] > min_pct:
            groups.setdefault(v[key], []).append(v["pct"])
    return sorted(
        ((k, sum(p) / len(p), len(p)) for k, p in groups.items()),
        key=lambda kv: -kv[1],
    )


def _videos_with_retention() -> list[dict]:
    youtube = get_client()
    analytics = get_analytics_client()
    videos = _recent_videos(youtube)
    if not videos:
        return []
    start = min(v["published"] for v in videos)
    end = date.today().isoformat()
    ret = _retention(analytics, [v["id"] for v in videos], start, end)
    for v in videos:
        r = ret.get(v["id"], {})
        v["pct"] = float(r.get("pct", 0) or 0)
        v["views"] = int(r.get("views", 0) or 0)
    return videos


DROP_OFF_SAMPLE = 5  # худших видео недели, на которые тратим доп. Analytics-запросы (дёшево, но не для всех 50)
DROPOFF_STATS_FILE = os.path.join(os.path.dirname(__file__), "..", f"dropoff_stats_{CHANNEL}.json")
MIN_DROPOFF_SAMPLE = 3  # меньше видео с кривыми — сигнал шумный, файл не пишем


def _add_drop_offs(analytics, videos: list[dict]) -> None:
    """Для нескольких худших по retention видео недели тянет посекундную кривую
    (analytics_retention._retention_curve — эндпоинт принимает только 1 video== за раз,
    поэтому не батчится, берём точечно) и находит момент наибольшего обрыва зрителя.
    Мутирует videos на месте, добавляя v['drop']. Не критично к сбоям — одно упавшее
    видео не должно рушить весь отчёт."""
    scored = sorted((v for v in videos if v.get("pct", 0) > 0), key=lambda v: v["pct"])
    for v in scored[:DROP_OFF_SAMPLE]:
        try:
            curve = _retention_curve(analytics, v["id"], v["published"], date.today().isoformat())
            v["drop"] = biggest_drop(curve, v.get("length", 0))
        except Exception as e:
            print(f"  drop-off для '{v['title'][:40]}' не получен: {e}")


def save_hook_stats(videos: list[dict]) -> None:
    """Лучший по retention хук-шаблон недели → hook_stats_<channel>.json (коммитит
    weekly-report.yml). generate_script._hook_preference() читает его и мягко подсказывает
    модели предпочтительный шаблон — данные аналитики замыкаются обратно в генерацию."""
    hooks = [(k, avg, n) for k, avg, n in _avg_by(videos, "hook")
             if k not in ("—", "other") and n >= MIN_HOOK_SAMPLE]
    if not hooks:
        print(f"  hook_stats: <{MIN_HOOK_SAMPLE} видео на шаблон — данных мало, файл не трогаем.")
        return
    best_template, avg, n = hooks[0]
    with open(HOOK_STATS_FILE, "w", encoding="utf-8") as f:
        json.dump({"best_template": best_template, "avg_pct": round(avg, 1), "videos": n,
                   "updated": date.today().isoformat()}, f, ensure_ascii=False, indent=2)
    print(f"  hook_stats: {best_template} ({avg:.1f}%, n={n})")


def save_dropoff_stats(videos: list[dict]) -> None:
    """Замыкает петлю drop-off → промпт (2026-07-05): медианная ЗОНА обрыва по худшим видео
    недели (доля длины видео, где кривая retention падает сильнее всего) пишется в
    dropoff_stats_<channel>.json (коммитит weekly-report.yml). generate_script._dropoff_note()
    читает файл и добавляет модели зонную подсказку (слабый хук / затянутый reveal / провал
    середины). Обрывы в концовке (>70% длины) — норма для Shorts (CTA), подсказка не нужна."""
    ratios = []
    for v in videos:
        d = v.get("drop")
        # Обрывы слабее 5 п.п. — шум, не сигнал.
        if d and v.get("length") and d.get("drop_pct", 0) >= 5:
            ratios.append(min(d["second"] / v["length"], 1.0))
    if len(ratios) < MIN_DROPOFF_SAMPLE:
        print(f"  dropoff_stats: <{MIN_DROPOFF_SAMPLE} видео с кривыми — данных мало, файл не трогаем.")
        return
    ratios.sort()
    median = ratios[len(ratios) // 2]
    zone = "hook" if median < 0.15 else "reveal" if median < 0.40 else "middle" if median < 0.70 else "ending"
    with open(DROPOFF_STATS_FILE, "w", encoding="utf-8") as f:
        json.dump({"zone": zone, "median_ratio": round(median, 3), "videos": len(ratios),
                   "updated": date.today().isoformat()}, f, ensure_ascii=False, indent=2)
    print(f"  dropoff_stats: zone={zone} (median {median:.0%} длины, n={len(ratios)})")


def build_report(videos: list[dict]) -> str:
    if not videos:
        return f"📊 [{CFG['channel_name']}] Нет видео для отчёта."

    lines = [f"📊 Retention-сводка за неделю: {CFG['channel_name']}"]

    hooks = _avg_by(videos, "hook")
    if hooks:
        lines.append("\nХук-шаблоны:")
        for name, avg, n in hooks[:5]:
            lines.append(f"  {avg:5.1f}%  ({n:2})  {name}")

    loops = _avg_by(videos, "loop")
    loops = [(k, a, n) for k, a, n in loops if k in ("yes", "no")]
    if loops:
        lines.append("\nПетля:")
        for name, avg, n in loops:
            label = "с петлёй" if name == "yes" else "без петли"
            lines.append(f"  {avg:5.1f}%  ({n:2})  {label}")

    # A/B заголовков (2026-07-02): keyword-насыщенный (seo) vs чисто нарративный. См.
    # generate_script.TITLE_SEO_PROBABILITY — 30% видео идут с seo-вариантом.
    titles = _avg_by(videos, "title_variant")
    titles = [(k, a, n) for k, a, n in titles if k in ("seo", "narrative")]
    if titles:
        lines.append("\nЗаголовок (A/B):")
        for name, avg, n in titles:
            lines.append(f"  {avg:5.1f}%  ({n:2})  {name}")

    # Ротация опенеров заголовка (2026-07-03): было 84% "The"/"Your"/"This" на EN-канале —
    # см. TITLE_OPENERS в generate_script.py. "—" (нет тега, старые видео) исключён.
    openers = [(k, a, n) for k, a, n in _avg_by(videos, "title_opener") if k not in ("—", "other")]
    if openers:
        lines.append("\nОпенер заголовка:")
        for name, avg, n in openers[:6]:
            lines.append(f"  {avg:5.1f}%  ({n:2})  {name}")

    # Эмоциональный тон факта (2026-07-03) — независимая от темы ось (EMOTIONAL_TONES).
    tones = [(k, a, n) for k, a, n in _avg_by(videos, "emotional_tone") if k not in ("—", "other")]
    if tones:
        lines.append("\nЭмоциональный тон:")
        for name, avg, n in tones[:6]:
            lines.append(f"  {avg:5.1f}%  ({n:2})  {name}")

    # Стилевая калибровка по нише (2026-07-05): видео, чей промпт получал заголовки чужих
    # выбросов (тег niche-styled), против остальных.
    niche = [(k, a, n) for k, a, n in _avg_by(videos, "niche") if k in ("styled", "plain")]
    if len(niche) == 2:
        lines.append("\nНиша-калибровка (styled vs plain):")
        for name, avg, n in niche:
            lines.append(f"  {avg:5.1f}%  ({n:2})  {name}")

    # «On this day» (2026-07-05): топикал-факты с привязкой к дате против обычных.
    topical = [(k, a, n) for k, a, n in _avg_by(videos, "topical") if k in ("yes", "no")]
    if any(k == "yes" for k, _, _ in topical):
        lines.append("\n«On this day» (топикал vs обычные):")
        for name, avg, n in topical:
            label = "топикал" if name == "yes" else "обычные"
            lines.append(f"  {avg:5.1f}%  ({n:2})  {label}")

    # Пороги retention (2026-07-02, retention_threshold): explore-and-exploit тест YouTube —
    # ниже порога (65% для <30с, 50% для 30-60с) раздача резко сокращается. Не абстрактное
    # "выше/ниже среднего", а конкретный порог из индустриальных 2026-данных.
    threshold_videos = [v for v in videos if v.get("pct", 0) > 0 and v.get("length")]
    if threshold_videos:
        passed = [v for v in threshold_videos if v["pct"] >= retention_threshold(v["length"])]
        lines.append(f"\nПорог retention: {len(passed)}/{len(threshold_videos)} видео прошли "
                      f"(65% для <30с, 50% для 30-60с)")
        failed = sorted((v for v in threshold_videos if v not in passed), key=lambda v: v["pct"])
        for v in failed[:3]:
            lines.append(f"  ниже порога: «{v['title'][:40]}» — {v['pct']:.1f}% "
                          f"(нужно {retention_threshold(v['length']):.0f}%)")

    topics = _avg_by(videos, "topic")
    if topics:
        lines.append("\nТоп-3 темы:")
        for name, avg, n in topics[:3]:
            lines.append(f"  {avg:5.1f}%  ({n:2})  {name}")

    # Слот-анализ: средние просмотры по часу публикации (UTC) — так был найден слабый
    # слот 13:07 EN. Свежие видео с нулём просмотров (лаг Analytics) не учитываем.
    slot_videos = [v for v in videos if v.get("views", 0) > 0 and v.get("published_full")]
    if slot_videos:
        by_slot: dict[str, list[int]] = {}
        for v in slot_videos:
            hour = v["published_full"][11:13]  # "2026-07-01T16:13:08Z" -> "16"
            by_slot.setdefault(f"{hour}:xx UTC", []).append(v["views"])
        lines.append("\nСлоты (ср. просмотры):")
        for slot, views in sorted(by_slot.items(), key=lambda kv: -sum(kv[1]) / len(kv[1])):
            lines.append(f"  {sum(views) / len(views):7.0f}  ({len(views):2})  {slot}")

    by_views = [v for v in videos if v.get("views", 0) > 0]
    if by_views:
        top3 = sorted(by_views, key=lambda v: -v["views"])[:3]
        lines.append("\n🧪 Топ недели — 2 ручных шага в Studio (5 мин):")
        for v in top3:
            lines.append(f"  {v['views']:6} — {v['title']}\n  https://youtube.com/shorts/{v['id']}")
        lines.append(
            "1) Test & Compare (заголовок/тумба)\n"
            "2) Related video → укажи свежий лонгформ (официальная воронка Shorts→длинное, "
            "сильнее ссылки в описании; API её не даёт)"
        )

    # Retention-кривая (не только % досмотра, а В КАКОЙ МОМЕНТ отваливаются) — для худших
    # видео недели. Показывает не «эта тема слабая», а «на 6-й секунде теряем зрителя».
    drops = [v for v in videos if v.get("drop")]
    if drops:
        lines.append("\n📉 Где теряем зрителя (худшие видео недели):")
        for v in drops:
            d = v["drop"]
            lines.append(f"  «{v['title'][:40]}» — обрыв ~{d['second']}s (−{d['drop_pct']} п.п.)")

    return "\n".join(lines)


if __name__ == "__main__":
    videos = _videos_with_retention()
    try:
        _add_drop_offs(get_analytics_client(), videos)
    except Exception as e:
        print(f"  drop-off анализ пропущен: {e}")
    notify(build_report(videos))
    save_hook_stats(videos)
    save_dropoff_stats(videos)

    # Дозаполняем video_history_<channel>.json просмотрами/retention/лайками (2026-07-06) —
    # эти же данные уже получены выше через _videos_with_retention(), лишних вызовов нет.
    try:
        stats_by_id = {v["id"]: {"views": v.get("views"), "pct": v.get("pct")} for v in videos}
        n = enrich_with_performance(CHANNEL, stats_by_id)
        print(f"  video_history: дозаполнено {n} записей.")
    except Exception as e:
        print(f"  video_history enrich пропущен: {e}")
