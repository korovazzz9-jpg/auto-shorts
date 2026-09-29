"""Еженедельная retention-сводка (хук-шаблоны, петля, темы) в Telegram.
Не тратит Claude — только YouTube Analytics/Data API (переиспользует
_recent_videos/_retention из analytics_retention.py). Запуск:
  python weekly_report.py            # EN
  CHANNEL=es python weekly_report.py # ES
"""
import json
import os
from datetime import date, timedelta

from dotenv import load_dotenv

from analytics_retention import _recent_videos, _retention, _retention_curve, biggest_drop
from config import CFG, CHANNEL
from notify import notify
from video_history import enrich_with_performance
from youtube_auth import get_analytics_client, get_client

load_dotenv()

HOOK_STATS_FILE = os.path.join(os.path.dirname(__file__), "..", f"hook_stats_{CHANNEL}.json")
MIN_HOOK_SAMPLE = 5  # меньше видео на шаблон — рано делать выводы, файл не пишем
TONE_STATS_FILE = os.path.join(os.path.dirname(__file__), "..", f"tone_stats_{CHANNEL}.json")
MIN_TONE_SAMPLE = 5  # тот же порог, что MIN_HOOK_SAMPLE
MIN_TONE_GAP = 5.0  # п.п. отставания от среднего по остальным тонам — меньше = шум, не сигнал


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
        v["subs"] = int(r.get("subs", 0) or 0)  # subscribersGained — подписки С этого видео
    return videos


DROP_OFF_SAMPLE = 10  # худших видео недели (2026-07-08: 5->10 — retention-кривая теперь реально
# отдаёт данные на видео от ~500 просмотров, не только на единичных случаях, есть смысл смотреть шире)
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


def save_tone_stats(videos: list[dict]) -> None:
    """Слабейший по retention эмоциональный тон недели → tone_stats_<channel>.json (коммитит
    weekly-report.yml). generate_script._tone_note() читает файл и мягко советует не форсировать
    этот тон. Тот же паттерн, что save_hook_stats, но с обратным знаком — тонов много (8),
    «лучший» неустойчиво прыгает между ними на малых выборках, а вот стабильно ХУДШИЙ на фоне
    остальных — сигнал понадёжнее (2026-08-21, найдено на ES: impossible 67.8% против 80%+ у
    creepy/awe/fear)."""
    tones = [(k, avg, n) for k, avg, n in _avg_by(videos, "emotional_tone")
             if k not in ("—", "other") and n >= MIN_TONE_SAMPLE]
    if len(tones) < 2:
        print(f"  tone_stats: <2 тонов с ≥{MIN_TONE_SAMPLE} видео — данных мало, файл не трогаем.")
        return
    worst_tone, worst_avg, worst_n = tones[-1]  # _avg_by сортирует по убыванию — последний слабейший
    rest_avg = sum(a for _, a, _ in tones[:-1]) / (len(tones) - 1)
    if rest_avg - worst_avg < MIN_TONE_GAP:
        print(f"  tone_stats: разброс тонов <{MIN_TONE_GAP:.0f} п.п. — не пишем, шум.")
        return
    with open(TONE_STATS_FILE, "w", encoding="utf-8") as f:
        json.dump({"avoid_tone": worst_tone, "avg_pct": round(worst_avg, 1), "videos": worst_n,
                   "rest_avg_pct": round(rest_avg, 1), "updated": date.today().isoformat()},
                   f, ensure_ascii=False, indent=2)
    print(f"  tone_stats: avoid {worst_tone} ({worst_avg:.1f}% vs rest {rest_avg:.1f}%, n={worst_n})")


def save_dropoff_stats(videos: list[dict]) -> None:
    """Замыкает петлю drop-off → промпт (2026-07-05): ЗОНА обрыва по худшим видео недели (доля
    длины видео, где кривая retention падает сильнее всего) пишется в dropoff_stats_<channel>.json
    (коммитит weekly-report.yml). generate_script._dropoff_note() читает файл и добавляет модели
    зонную подсказку (слабый хук / затянутый reveal / провал середины). Обрывы в концовке
    (>70% длины) — норма для Shorts (CTA), подсказка не нужна.

    2026-07-08: медиана теперь ВЗВЕШЕНА по величине обрыва (drop_pct). Раньше −19 п.п. (реальный
    провал) и −6 п.п. (пологая убыль) весили одинаково — обычная медиана позиций теряла сигнал о
    том, где сливаемся СИЛЬНЕЕ всего. Взвешенная медиана находит долю длины, до которой набирается
    половина всей «массы обрыва»: видео с резкими обрывами тянут зону к своей позиции сильнее."""
    weighted = []  # (ratio позиции обрыва, вес = drop_pct)
    for v in videos:
        d = v.get("drop")
        # Обрывы слабее 5 п.п. — шум, не сигнал.
        if d and v.get("length") and d.get("drop_pct", 0) >= 5:
            weighted.append((min(d["second"] / v["length"], 1.0), d["drop_pct"]))
    if len(weighted) < MIN_DROPOFF_SAMPLE:
        print(f"  dropoff_stats: <{MIN_DROPOFF_SAMPLE} видео с кривыми — данных мало, файл не трогаем.")
        return
    weighted.sort()  # по позиции обрыва
    total_w = sum(w for _, w in weighted)
    acc, median = 0.0, weighted[-1][0]
    for ratio, w in weighted:
        acc += w
        if acc >= total_w / 2:  # взвешенная медиана: половина суммарной величины обрывов — до сюда
            median = ratio
            break
    zone = "hook" if median < 0.15 else "reveal" if median < 0.40 else "middle" if median < 0.70 else "ending"
    with open(DROPOFF_STATS_FILE, "w", encoding="utf-8") as f:
        json.dump({"zone": zone, "median_ratio": round(median, 3), "videos": len(weighted),
                   "updated": date.today().isoformat()}, f, ensure_ascii=False, indent=2)
    print(f"  dropoff_stats: zone={zone} (взвеш. медиана {median:.0%} длины, n={len(weighted)})")


def build_report(videos: list[dict]) -> str:
    """Короткий Telegram-отчёт только по выпускам последних 7 дней.

    Срез последних 50 загрузок нужен для обучающих JSON, но в сообщении он
    не должен называться «неделей». Значения retention на момент отчёта.
    """
    cutoff = (date.today() - timedelta(days=7)).isoformat()
    recent = [v for v in videos if v.get("published", "") >= cutoff]
    if not recent:
        return ""

    measured = [v for v in recent if v.get("pct", 0) > 0 and v.get("views", 0) > 0]
    lines = [f"📊 {CFG['channel_name']} · выпуски за 7 дней", "Просмотры — с публикации роликов."]
    if not measured:
        return "\n".join(lines + [f"Новых видео: {len(recent)}. Данные YouTube Analytics ещё не появились."])

    views = sum(v["views"] for v in measured)
    avg_pct = sum(v["pct"] for v in measured) / len(measured)
    lines.append(f"{len(recent)} видео · {len(measured)} с данными · {views:,} просмотров · досмотр {avg_pct:.0f}%")
    if len(measured) < len(recent):
        lines.append(f"Без данных пока: {len(recent) - len(measured)}.")

    lines.append("\nЛучшие по просмотрам:")
    for v in sorted(measured, key=lambda v: -v["views"])[:2]:
        lines.append(f"• {v['title'][:65]} — {v['views']:,} просмотров, досмотр {v['pct']:.0f}%\n  https://youtube.com/shorts/{v['id']}")

    # Не делаем вывод по ролику, который Analytics почти не показывал.
    eligible = [v for v in measured if v["views"] >= 100]
    if eligible:
        weakest = min(eligible, key=lambda v: v["pct"])
        drop = weakest.get("drop")
        detail = f"; резкий спад ~{drop['second']}-я сек." if drop else ""
        lines.append(f"\nПроверить монтаж: {weakest['title'][:65]} — досмотр {weakest['pct']:.0f}%{detail}\n"
                     f"https://youtube.com/shorts/{weakest['id']}")

    # Малые группы и отдельные выбросы не выдаём за устойчивые тенденции.
    topics: dict[str, list[int]] = {}
    for v in measured:
        if v.get("topic") not in (None, "—"):
            topics.setdefault(v["topic"], []).append(v["views"])
    comparable = [(name, sum(counts) / len(counts), len(counts))
                  for name, counts in topics.items() if len(counts) >= 3]
    if comparable:
        best = max(comparable, key=lambda row: row[1])
        lines.append(f"\nТема для следующего теста: {best[0]} — в среднем {best[1]:.0f} просмотров "
                     f"({best[2]} видео).")

    return "\n".join(lines)


def main() -> None:
    videos = _videos_with_retention()
    analytics_client = get_analytics_client()
    try:
        _add_drop_offs(analytics_client, videos)
    except Exception as e:
        print(f"  drop-off анализ пропущен: {e}")
    report = build_report(videos)
    if report:
        notify(report)
    save_hook_stats(videos)
    save_dropoff_stats(videos)
    save_tone_stats(videos)

    # Дозаполняем video_history_<channel>.json просмотрами/retention/лайками (2026-07-06) —
    # эти же данные уже получены выше через _videos_with_retention(), лишних вызовов нет.
    try:
        stats_by_id = {v["id"]: {"views": v.get("views"), "pct": v.get("pct"),
                                  "subs": v.get("subs")} for v in videos}
        n = enrich_with_performance(CHANNEL, stats_by_id)
        print(f"  video_history: дозаполнено {n} записей.")
    except Exception as e:
        print(f"  video_history enrich пропущен: {e}")


if __name__ == "__main__":
    from notify import guard_main
    guard_main(f"weekly-report {CHANNEL}", main)
