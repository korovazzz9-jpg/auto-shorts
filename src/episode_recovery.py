"""Durable per-channel episode checkpoint and bounded attempt ledger."""
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path


class EpisodeRecovery:
    def __init__(self, channel, root=None, slots=()):
        self.path = Path(root or Path(__file__).resolve().parents[1]) / f"recovery_{channel}.json"
        self.state = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {"pending": None, "attempts": []}
        self.started = datetime.now(timezone.utc).isoformat()
        self.attempt_id = os.environ.get("GITHUB_RUN_ID", self.started) + ":" + os.environ.get("GITHUB_RUN_ATTEMPT", "1")
        self.resumed = bool(self.state.get("pending"))
        now = datetime.fromisoformat(self.started)
        candidates = [now.replace(hour=h, minute=m, second=0, microsecond=0) - timedelta(days=d)
                      for h, m in slots for d in (0, 1)]
        self.slot = max((t for t in candidates if t <= now), default=now).isoformat()

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def pending(self):
        item = self.state.get("pending")
        if item and item.get("status") == "publishing":
            raise RuntimeError("Previous YouTube upload has unknown outcome; reconcile before retry to avoid duplicate.")
        if item and item.get("status") == "published":
            self.state["pending"] = None
            self.save()
            return None
        return item

    def prepare(self, data, pending_pair, pair_start_mode):
        self.state["pending"] = {"data": data, "pending_pair": pending_pair,
                                 "pair_start_mode": pair_start_mode, "selections": {},
                                 "status": "prepared", "created": self.started}
        self.save()
        return self.state["pending"]

    def publishing(self):
        self.state["pending"]["status"] = "publishing"
        self.save()

    def uploaded(self, video_id):
        self.state["pending"].update(status="published", video_id=video_id)
        self.save()

    def finish(self, outcome, stats, error=None):
        pending = self.state.get("pending") or {}
        if pending.get("video_id"):
            outcome = "published"
        self.state["attempts"].append({"id": self.attempt_id, "at": self.started,
            "outcome": outcome, "resumed": self.resumed, "title": pending.get("data", {}).get("title"),
            "episode": pending.get("created"), "slot": self.slot, "video_id": pending.get("video_id"),
            "selection": stats, "error": str(error)[:500] if error else None})
        self.state["attempts"] = self.state["attempts"][-300:]
        if outcome == "published":
            self.state["pending"] = None
        self.save()


def reliability_report(channel, root=None):
    recovery = EpisodeRecovery(channel, root)
    cutoff = datetime.now(timezone.utc).timestamp() - 7 * 86400
    rows = [r for r in recovery.state["attempts"] if datetime.fromisoformat(r["at"]).timestamp() >= cutoff]
    if not rows:
        return ""
    total = lambda key: sum(r.get("selection", {}).get(key, 0) or 0 for r in rows)
    published = sum(r["outcome"] == "published" for r in rows)
    recovered = sum(r["outcome"] == "published" and r["resumed"] for r in rows)
    failures = sum(r["outcome"] != "published" for r in rows)
    slot_rows = {}
    for row in rows:
        slot_rows.setdefault(row.get("slot", row["at"]), []).append(row)
    lost = sum(not any(r["outcome"] == "published" for r in group)
               and (datetime.now(timezone.utc) - datetime.fromisoformat(slot)).total_seconds() > 2700
               for slot, group in slot_rows.items())
    reasons = {}
    for row in rows:
        for reason, count in (row.get("selection", {}).get("retry_reasons") or {}).items():
            reasons[reason] = reasons.get(reason, 0) + count
    return (f"\n🛠 Надёжность за 7 дней: опубликовано {published}, восстановлено выпусков {recovered}, "
            f"неудачных попыток {failures}, слотов без публикации среди записанных {lost}, ожидает добора {int(bool(recovery.state.get('pending')))}."
            f"\nПовторы API: {total('retries')}, восстановлено ответов: {total('retry_recovered')}."
            f"\nТокены повторов (вход/выход): {total('retry_input_tokens')}/{total('retry_output_tokens')}; "
            f"попыток с неизвестным расходом: {total('unknown_usage_attempts')}."
            f"\nДобор: {total('extra_searches')} поисков, токены вход/выход {total('extra_input_tokens')}/{total('extra_output_tokens')}."
            f"\nПричины повторов: {reasons}. Токены повторов внутри добора входят в оба счётчика.")
