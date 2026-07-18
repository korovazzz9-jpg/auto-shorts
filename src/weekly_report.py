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
        v["subs"] = int(r.get("subs", 0) or 0)  # subscribersGained — подписки С этого видео
    return videos


DROP_OFF_SAMPLE = 10  # худших видео недели (2026-07-08: 5->10 — retention-кривая теперь реально
# отдаёт данные на видео от ~500 просмотров, не только на единичных случаях, есть смысл смотреть шире)
DROPOFF_STATS_FILE = os.path.join(os.path.dirname(__file__), "..", f"dropoff_stats_{CHANNEL}.json")
MIN_DROPOFF_SAMPLE = 3  # меньше видео с кривыми — сигнал шумный, файл не пишем


SPIKE_DIE_MIN_AGE_DAYS = 6    # младше — рано, day1 ещё не «устоялся»
SPIKE_DIE_MAX_AGE_DAYS = 10   # старше — не «эта неделя», не показываем повторно
SPIKE_DIE_SAMPLE = 5          # доп. Analytics-запросы (тот же паттерн, что DROP_OFF_SAMPLE)
SPIKE_DIE_MIN_DAY1_VIEWS = 100  # отсекаем шум — 3 просмотра в день 1 из 4 не «взлёт»
SPIKE_DIE_DAY1_SHARE = 0.6    # день 1 даёт ≥60% ВСЕХ просмотров когорты — явный «взлёт и тишина»


def _daily_views_curve(analytics, video_id: str, start: str, end: str) -> list[tuple[str, int]]:
    """День → просмотры для ОДНОГО видео. Тот же принцип, что `_retention_curve` — эндпоинт
    Analytics не батчится по video==, тянем точечно (см. SPIKE_DIE_SAMPLE)."""
    try:
        resp = analytics.reports().query(
            ids="channel==MINE", startDate=start, endDate=end,
            metrics="views", dimensions="day", filters=f"video=={video_id}", sort="day",
        ).execute()
    except Exception:
        return []
    return [(r[0], int(r[1])) for r in resp.get("rows", []) or []]


def _age_days(v: dict) -> int:
    from datetime import datetime
    published = datetime.fromisoformat(v["published"])
    return (datetime.now() - published).days


def find_spike_and_die(analytics, videos: list[dict]) -> list[dict]:
    """«Почти вирусные» (2026-07-08): не топ по абсолютным просмотрам и не худшие по retention —
    отдельная категория: видео резко выросло в день 1 (алгоритм реально протолкнул), а потом
    рост почти остановился. Отличается от «просто слабого» видео (то никогда и не росло) —
    здесь явно виден момент, когда алгоритм «разочаровался» (обычно: слабый payoff/середина/
    длина). Когорта — видео 6-10 дней от роду (данные уже устоялись, но это ещё «эта неделя»),
    сэмпл ограничен (не батчится, как `_retention_curve`/`_add_drop_offs`)."""
    cohort = [v for v in videos if SPIKE_DIE_MIN_AGE_DAYS <= _age_days(v) <= SPIKE_DIE_MAX_AGE_DAYS]
    cohort.sort(key=lambda v: -v.get("views", 0))

    results = []
    for v in cohort[:SPIKE_DIE_SAMPLE]:
        curve = _daily_views_curve(analytics, v["id"], v["published"], date.today().isoformat())
        if len(curve) < 3:
            continue
        day1 = curve[0][1]
        total = sum(c[1] for c in curve)
        if day1 < SPIKE_DIE_MIN_DAY1_VIEWS or total <= 0:
            continue
        day1_share = day1 / total
        if day1_share >= SPIKE_DIE_DAY1_SHARE:
            results.append({"title": v["title"], "id": v["id"], "day1": day1,
                             "total": total, "day1_share": round(day1_share, 2)})
    return results


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


def build_report(videos: list[dict], spike_die: list[dict] | None = None) -> str:
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

    # Тип структуры скрипта (2026-07-13, ротация против «mass-produced»-паттерна — см.
    # STRUCTURES в generate_script.py): какой формат лучше удерживает на ЭТОМ канале.
    formats = [(k, a, n) for k, a, n in _avg_by(videos, "structure") if k != "—"]
    if formats:
        lines.append("\nТип структуры:")
        for name, avg, n in formats:
            lines.append(f"  {avg:5.1f}%  ({n:2})  {name}")

    # Стиль заголовка: вопрос vs утверждение (2026-07-17, CurioShock outlier-анализ показал
    # утверждения сильнее вопросов в разы на похожем контенте — проверяем на своей аудитории).
    title_styles = [(k, a, n) for k, a, n in _avg_by(videos, "title_style") if k != "—"]
    if title_styles:
        lines.append("\nСтиль заголовка:")
        for name, avg, n in title_styles:
            lines.append(f"  {avg:5.1f}%  ({n:2})  {name}")

    # Сила неожиданности действия в заголовке (2026-07-18, CurioShock-инсайт: топы всегда
    # берут самое шоковое/конкретное действие, не мягкую формулировку) — self-report модели.
    title_intensities = [(k, a, n) for k, a, n in _avg_by(videos, "title_intensity") if k != "—"]
    if title_intensities:
        lines.append("\nСила заголовка:")
        for name, avg, n in title_intensities:
            lines.append(f"  {avg:5.1f}%  ({n:2})  {name}")

    # Раскраска хук-плашки (2026-07-18, Noxterra-стиль: жёлтый→белый→красный vs белый).
    hook_styles = [(k, a, n) for k, a, n in _avg_by(videos, "hook_style") if k != "—"]
    if hook_styles:
        lines.append("\nХук-плашка:")
        for name, avg, n in hook_styles:
            lines.append(f"  {avg:5.1f}%  ({n:2})  {name}")

    # Цвет субтитров (2026-07-10, см. CAPTION_COLORS в build_video.py) — независимая от
    # контента ось оформления, ротируется случайно ради вариативности между видео.
    colors = [(k, a, n) for k, a, n in _avg_by(videos, "caption_color") if k != "—"]
    if colors:
        lines.append("\nЦвет субтитров:")
        for name, avg, n in colors:
            lines.append(f"  {avg:5.1f}%  ({n:2})  {name}")

    # TTS-голос (2026-07-10, см. voices в config.py) — ротируется случайно между видео.
    voices = [(k, a, n) for k, a, n in _avg_by(videos, "voice") if k != "—"]
    if voices:
        lines.append("\nГолос озвучки:")
        for name, avg, n in voices:
            lines.append(f"  {avg:5.1f}%  ({n:2})  {name}")

    # Пары (2026-07-10): часть A с этой даты несёт подписной тизер (pair_cta_phrases в
    # config) — меряем, что он реально даёт: retention + сколько подписок принесли pair-a
    # видео против остальных. ⚠️ pair-a-видео, вышедшие ДО 2026-07-10, тизера не имели —
    # первые пару недель сравнение смешанное, честным станет по мере обновления выборки.
    pair_groups = (("часть A (тизер)", [v for v in videos if v.get("pair") == "a"]),
                   ("часть B", [v for v in videos if v.get("pair") == "b"]),
                   ("без пары", [v for v in videos if v.get("pair") == "no"]))
    if any(g for label, g in pair_groups[:2]):
        lines.append("\nПары (подписной тизер на A):")
        for label, group in pair_groups:
            if not group:
                continue
            with_pct = [v["pct"] for v in group if v.get("pct", 0) > 0]
            avg_pct = sum(with_pct) / len(with_pct) if with_pct else 0.0
            subs = sum(v.get("subs", 0) for v in group)
            lines.append(f"  {avg_pct:5.1f}%  ({len(group):2})  {label} — подписок: +{subs}")

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

    # «Почти вирусные» (2026-07-08, find_spike_and_die) — не топ, не худшие: видео резко
    # выросло в день 1, потом почти остановилось. Момент, где алгоритм «разочаровался».
    if spike_die:
        lines.append("\n🚀📉 Взлетели и затихли (не топ, не худшие — отдельная категория):")
        for v in spike_die:
            lines.append(f"  «{v['title'][:40]}» — день 1: {v['day1']} из {v['total']} всего "
                          f"({v['day1_share']:.0%} просмотров пришлось на первый день)")

    return "\n".join(lines)


def main() -> None:
    videos = _videos_with_retention()
    analytics_client = get_analytics_client()
    try:
        _add_drop_offs(analytics_client, videos)
    except Exception as e:
        print(f"  drop-off анализ пропущен: {e}")
    try:
        spike_die = find_spike_and_die(analytics_client, videos)
    except Exception as e:
        print(f"  spike-and-die анализ пропущен: {e}")
        spike_die = []
    notify(build_report(videos, spike_die))
    save_hook_stats(videos)
    save_dropoff_stats(videos)

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
