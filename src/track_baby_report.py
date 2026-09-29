"""Недельная сводка канала «малышка и щенок» по типам завязок -> stats/baby/weekly.md.

Берёт снимки stats/baby/daily.csv (их пишет track_baby.py) и типы завязок из
stats/baby/shorts_types.csv (выгрузка shorts.json репозитория AI: name,type,risk).
По каждому типу: число роликов, медиана просмотров к 48 ч и к 7 дням, средний % досмотра,
лучший и худший ролик. В конце — какие типы снимать больше.

Просмотры «к 48 ч / к 7 дням» — линейная интерполяция между ежедневными снимками по возрасту
ролика (снимок раз в сутки попадает на 48 ч лишь случайно). Ролик, ещё не доживший до
отметки, в медиану этой отметки не входит.

Запуск: python track_baby_report.py  (из каталога src; сети не нужно).
"""
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from track_baby import STATS_DIR, load_types, read_csv

MIN_PER_TYPE = 2   # меньше роликов в типе — вывод по нему не делаем
MORE, LESS = 1.2, 0.8  # порог «заметно выше/ниже» медианы канала


def _f(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def views_at(points: list[tuple[float, float]], hours: float) -> float | None:
    """Просмотры к возрасту `hours` по снимкам [(возраст_ч, просмотры)]. Точка (0, 0) неявная.
    None — ролик до этого возраста ещё не наблюдался."""
    pts = sorted([(0.0, 0.0)] + [(a, v) for a, v in points if a is not None and v is not None])
    if pts[-1][0] < hours:
        return None
    for (a0, v0), (a1, v1) in zip(pts, pts[1:]):
        if a0 <= hours <= a1:
            return v0 if a1 == a0 else v0 + (v1 - v0) * (hours - a0) / (a1 - a0)
    return None


def per_video(daily: list[dict]) -> dict:
    """{video_id: {name, published_at, views, pct, sec, subs, v48, v7d}} — последнее состояние
    плюс просмотры к 48 ч и 7 дням."""
    by_id: dict[str, list[dict]] = {}
    for row in daily:
        by_id.setdefault(row["video_id"], []).append(row)
    out = {}
    for vid, rows in by_id.items():
        rows.sort(key=lambda r: r["date"])
        last = rows[-1]
        points = [(_f(r.get("age_hours")), _f(r.get("views"))) for r in rows]
        out[vid] = {"video_id": vid, "name": last.get("name") or "", "published_at": last.get("published_at", ""),
                    "views": _f(last.get("views")), "pct": _f(last.get("avg_view_pct")),
                    "sec": _f(last.get("avg_view_sec")), "subs": _f(last.get("subs_gained")),
                    "v48": views_at(points, 48), "v7d": views_at(points, 24 * 7)}
    return out


def _median(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def _mean(values):
    values = [v for v in values if v is not None]
    return statistics.mean(values) if values else None


def by_type(videos: dict, types: dict) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for v in videos.values():
        kind = types.get(v["name"], {}).get("type") or ("без метки" if not v["name"] else "нет в списке")
        groups.setdefault(kind, []).append(v)
    rows = []
    for kind, vs in groups.items():
        rank = sorted(vs, key=lambda v: (v["v7d"] if v["v7d"] is not None else -1,
                                         v["v48"] if v["v48"] is not None else -1,
                                         v["views"] or 0), reverse=True)
        rows.append({"type": kind, "n": len(vs),
                     "n7d": sum(1 for v in vs if v["v7d"] is not None),
                     "med48": _median(v["v48"] for v in vs), "med7d": _median(v["v7d"] for v in vs),
                     "pct": _mean(v["pct"] for v in vs), "best": rank[0], "worst": rank[-1]})
    rows.sort(key=lambda r: (r["med7d"] if r["med7d"] is not None else -1,
                             r["med48"] if r["med48"] is not None else -1), reverse=True)
    return rows


def recommend(rows: list[dict], videos: dict, types: dict) -> list[str]:
    """Типы заметно выше/ниже медианы канала. Основа — просмотры к 7 дням; пока 7-дневных
    данных мало, — к 48 ч (с пометкой). Типы с одним роликом не судим."""
    key = "med7d" if sum(1 for r in rows if r["n7d"] >= MIN_PER_TYPE) >= 2 else "med48"
    field = "v7d" if key == "med7d" else "v48"
    label = "7 дней" if key == "med7d" else "48 ч (7-дневных данных пока мало)"
    channel = _median(v[field] for v in videos.values())
    judged = [r for r in rows if r["type"] not in ("без метки", "нет в списке") and r[key] is not None
              and sum(1 for v in videos.values()
                      if types.get(v["name"], {}).get("type") == r["type"] and v[field] is not None) >= MIN_PER_TYPE]
    lines = []
    if channel is None or len(judged) < 2:
        lines.append(f"Данных мало для вывода: нужно хотя бы два типа по {MIN_PER_TYPE}+ ролика с цифрами к 48 ч.")
    else:
        more = [r for r in judged if r[key] >= MORE * channel]
        less = [r for r in judged if r[key] <= LESS * channel]
        fmt = lambda rs: ", ".join(f"{r['type']} ({r[key]:.0f})" for r in rs)
        lines.append(f"Мерка — медиана просмотров к {label}; по каналу {channel:.0f}.")
        lines.append(f"Снимать больше: {fmt(more)}." if more else "Типов заметно выше медианы канала нет.")
        if less:
            lines.append(f"Снимать меньше: {fmt(less)}.")
    shot = {types.get(v["name"], {}).get("type") for v in videos.values()}
    untried = sorted({t["type"] for t in types.values()} - shot)
    if untried:
        lines.append(f"Ещё не снимались: {', '.join(untried)}.")
    return lines


def _n(value, digits=0):
    return "—" if value is None else f"{value:.{digits}f}"


def render(daily: list[dict], types: dict, now: datetime) -> str:
    videos = per_video(daily)
    lines = [f"# Канал «малышка и щенок»: сводка на {now.date().isoformat()}", ""]
    if not videos:
        lines += ["Снимков ещё нет: трекер не подключён или канал пуст (см. docs/SETUP_BABY.md)."]
        return "\n".join(lines) + "\n"
    week_ago = (now - timedelta(days=7)).isoformat()
    fresh = [v for v in videos.values() if v["published_at"] >= week_ago[:19]]
    unmapped = [v for v in videos.values() if not v["name"]]
    lines += [f"Роликов на канале: {len(videos)}, за 7 дней вышло {len(fresh)}. "
              f"Без метки завязки: {len(unmapped)}.", ""]
    rows = by_type(videos, types)
    lines += ["| тип | роликов | медиана к 48 ч | медиана к 7 дн | ср. досмотр, % | лучший | худший |",
              "|---|---|---|---|---|---|---|"]
    for r in rows:
        best, worst = r["best"], r["worst"]
        cell = lambda v: f"{v['name'] or v['video_id']} ({_n(v['v7d'] if v['v7d'] is not None else v['views'])})"
        lines.append(f"| {r['type']} | {r['n']} | {_n(r['med48'])} | {_n(r['med7d'])} | {_n(r['pct'], 1)} | "
                     f"{cell(best)} | {cell(worst) if r['n'] > 1 else '—'} |")
    lines += ["", "## Что снимать", ""] + [f"- {s}" for s in recommend(rows, videos, types)]
    if unmapped:
        lines += ["", "## Без метки завязки", "",
                  "Добавить в stats/baby/mapping.csv или тег `s-<name>` в ролике:", ""]
        lines += [f"- {v['video_id']} ({v['published_at'][:10]})" for v in unmapped]
    return "\n".join(lines) + "\n"


def main(stats_dir: Path = STATS_DIR, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    text = render(read_csv(stats_dir / "daily.csv"), load_types(stats_dir), now)
    path = stats_dir / "weekly.md"
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
