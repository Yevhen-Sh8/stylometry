#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/ias_scanner.py
===================
Періодичний сканер БД модуля моніторингу ІАС.

Цикл:
  1. Знайти події, матеріали яких додано / змінено після водяного знака
     (SQL-запит DIMS_SOURCE_CHANGED_EVENTS_SQL).
  2. Для кожної події завантажити всі її матеріали (DIMS_SOURCE_EVENT_MATERIALS_SQL).
  3. Якщо склад події змінився — оцінити за DIMS (core.ias_service.assess_event).
  4. За ознак скоординованої атаки — створити сповіщення та надіслати webhook.

Доступ до БД ІАС — лише на читання, через SQLAlchemy (PostgreSQL, MySQL,
MS SQL, Oracle, SQLite — потрібен лише відповідний драйвер). Схема БД ІАС
сервісу невідома, тому відповідність полів задається SQL-запитами в
конфігурації (див. docs/ias_integration_ua.md).

Запуск:
    python -m core.ias_scanner --once
    python -m core.ias_scanner --interval 300
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import signal
import time
from datetime import date, datetime, timedelta, timezone

import requests

from core.ias_service import GRADE_RANK, AssessmentError, assess_event
from core.ias_store import IasStore

log = logging.getLogger("dims.ias_scanner")

WATERMARK_KEY = "watermark"

# Обов'язкові колонки результатів запитів.
CHANGED_EVENTS_COLUMNS = {"event_id", "updated_at"}
MATERIAL_COLUMNS = {"source", "text"}


def _iso(value) -> str:
    """Нормалізує позначку часу до ISO-8601 з «T» (щоб рядки коректно
    порівнювались лексикографічно при просуванні водяного знака)."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.isoformat(timespec="seconds")
        return value.astimezone(timezone.utc).isoformat(timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    return str(value) if value is not None else ""


# ─────────────────────────────────────────────────────────────────────────────
#  Джерело даних: БД ІАС
# ─────────────────────────────────────────────────────────────────────────────

class SqlEventSource:
    """Читає події та матеріали з БД ІАС настроюваними SQL-запитами.

    changed_events_sql: параметр :since → колонки event_id, updated_at
    event_materials_sql: параметр :event_id → колонки source, text
        (+ опційно id, platform, domain, url, published_at)
    """

    def __init__(self, db_url: str, changed_events_sql: str, event_materials_sql: str,
                 statement_timeout_s: int = 60):
        from sqlalchemy import create_engine  # імпорт тут: вебчастині не потрібен

        if not db_url:
            raise ValueError("Не задано DIMS_SOURCE_DB_URL.")
        if ":since" not in changed_events_sql:
            raise ValueError("DIMS_SOURCE_CHANGED_EVENTS_SQL має містити параметр :since.")
        if ":event_id" not in event_materials_sql:
            raise ValueError("DIMS_SOURCE_EVENT_MATERIALS_SQL має містити параметр :event_id.")
        self.engine = create_engine(db_url, pool_pre_ping=True)
        self.changed_sql = changed_events_sql
        self.materials_sql = event_materials_sql
        self.timeout = statement_timeout_s

    @classmethod
    def from_env(cls) -> "SqlEventSource":
        return cls(
            os.environ.get("DIMS_SOURCE_DB_URL", ""),
            os.environ.get("DIMS_SOURCE_CHANGED_EVENTS_SQL", ""),
            os.environ.get("DIMS_SOURCE_EVENT_MATERIALS_SQL", ""),
        )

    def _query(self, sql: str, params: dict) -> list[dict]:
        from sqlalchemy import text

        with self.engine.connect() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
        return [dict(r) for r in rows]

    def changed_events(self, since: str) -> list[dict]:
        rows = self._query(self.changed_sql, {"since": since})
        if rows and not CHANGED_EVENTS_COLUMNS <= set(rows[0]):
            raise ValueError(
                f"Запит змінених подій має повертати колонки {sorted(CHANGED_EVENTS_COLUMNS)}."
            )
        return [{"event_id": str(r["event_id"]), "updated_at": _iso(r["updated_at"])}
                for r in rows]

    def event_materials(self, event_id: str) -> list[dict]:
        rows = self._query(self.materials_sql, {"event_id": event_id})
        if rows and not MATERIAL_COLUMNS <= set(rows[0]):
            raise ValueError(f"Запит матеріалів має повертати колонки {sorted(MATERIAL_COLUMNS)}.")
        out = []
        for r in rows:
            out.append({
                "id": str(r.get("id") or r.get("material_id") or ""),
                "source": str(r.get("source") or ""),
                "platform": str(r.get("platform") or ""),
                "domain": str(r.get("domain") or ""),
                "url": str(r.get("url") or ""),
                "published_at": _iso(r.get("published_at")),
                "text": r.get("text") or "",
            })
        return out


# ─────────────────────────────────────────────────────────────────────────────
#  Сповіщення
# ─────────────────────────────────────────────────────────────────────────────

def alert_message(alert_id: int, result: dict, public_url: str = "") -> dict:
    """Компактне повідомлення для webhook (без текстів матеріалів)."""
    coord = result["coordination"]
    msg = {
        "type": "dims.coordinated_activity_alert",
        "alert_id": alert_id,
        "event_id": result["event_id"],
        "grade": result["grade"]["grade"],
        "grade_label": result["grade"]["label"],
        "r_dims": result["r_dims"],
        "confidence": {k: result["confidence"].get(k) for k in ("lo", "hi", "grade_prob")}
        if result.get("confidence") else None,
        "indicators": result["indicators"],
        "kinds": result["alert"].get("kinds", []),
        "signals": result["alert"]["coordination_signals"],
        "top_pairs": coord["flagged_pairs"][:5],
        "copy_clusters": [
            {k: c[k] for k in ("sources", "n_sources", "first_source", "first_published_at")}
            for c in coord["copy_clusters"][:5]
        ],
        "n_sources": result["stats"]["n_sources"],
        "n_materials": result["stats"]["n_materials"],
        "warnings": result["warnings"],
        "assessed_at": result["assessed_at"],
    }
    if public_url:
        msg["url"] = f"{public_url.rstrip('/')}/api/v1/alerts/{alert_id}"
    return msg


class WebhookNotifier:
    def __init__(self, url: str, token: str = "", timeout_s: int = 10,
                 public_url: str = "", verify: bool | str = True):
        self.url = url
        self.token = token
        self.timeout = timeout_s
        self.public_url = public_url
        self.verify = verify

    @classmethod
    def from_env(cls) -> "WebhookNotifier | None":
        url = os.environ.get("DIMS_ALERT_WEBHOOK_URL", "").strip()
        if not url:
            return None
        ca = os.environ.get("DIMS_ALERT_WEBHOOK_CA_BUNDLE", "").strip()
        return cls(url, os.environ.get("DIMS_ALERT_WEBHOOK_TOKEN", "").strip(),
                   public_url=os.environ.get("DIMS_PUBLIC_URL", "").strip(),
                   verify=ca or True)

    def send(self, alert_id: int, result: dict) -> bool:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            resp = requests.post(self.url, json=alert_message(alert_id, result, self.public_url),
                                 headers=headers, timeout=self.timeout, verify=self.verify)
            if 200 <= resp.status_code < 300:
                return True
            log.warning("Webhook відповів %s для сповіщення %s", resp.status_code, alert_id)
        except requests.RequestException as exc:
            log.warning("Webhook недоступний для сповіщення %s: %s", alert_id, exc)
        return False


# ─────────────────────────────────────────────────────────────────────────────
#  Цикл сканування
# ─────────────────────────────────────────────────────────────────────────────

def materials_fingerprint(materials: list[dict]) -> str:
    """Відбиток складу події: змінюється, якщо додано/змінено матеріал."""
    h = hashlib.sha256()
    for m in sorted(materials, key=lambda x: (x["id"], x["source"])):
        h.update(m["id"].encode())
        h.update(b"\x1f")
        h.update(m["source"].encode())
        h.update(b"\x1f")
        h.update(hashlib.sha256(m["text"].encode("utf-8", "replace")).digest())
    return h.hexdigest()


def _should_alert_again(previous: dict | None, result: dict) -> bool:
    """Повторне сповіщення по тій самій події — лише при ескалації: вищий
    грейд або новий тип сповіщення (напр. до copy_paste додався dims)."""
    if previous is None:
        return True
    if GRADE_RANK[result["grade"]["grade"]] > GRADE_RANK[previous["grade"]]:
        return True
    return bool(set(result["alert"].get("kinds", [])) - set(previous.get("kinds", [])))


def assessment_params_from_env() -> dict:
    return {
        "mfw_n": int(os.environ.get("DIMS_MFW", "100")),
        "threshold": float(os.environ.get("DIMS_DELTA_THRESHOLD", "0.8")),
        "feature_type": os.environ.get("DIMS_FEATURE_TYPE", "word").strip().lower(),
    }


def run_once(source, store: IasStore, notifier: WebhookNotifier | None = None,
             *, lookback_hours: int = 24, max_events: int = 200,
             params: dict | None = None, alert_policy: dict | None = None) -> dict:
    """Один прохід сканера. Повертає статистику проходу."""
    params = params or assessment_params_from_env()
    since = store.get_state(WATERMARK_KEY) or (
        datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    ).isoformat(timespec="seconds")

    events = source.changed_events(since)
    events.sort(key=lambda e: e["updated_at"])
    events = events[:max_events]

    stats = {"since": since, "changed_events": len(events), "assessed": 0,
             "unchanged": 0, "skipped": 0, "alerts": 0, "notified": 0, "errors": 0}
    watermark = since
    for ev in events:
        event_id = ev["event_id"]
        try:
            materials = source.event_materials(event_id)
            fp = materials_fingerprint(materials)
            if store.get_fingerprint(event_id) == fp:
                stats["unchanged"] += 1
            else:
                try:
                    result = assess_event(materials, event_id=event_id,
                                          alert_policy=alert_policy, **params)
                except AssessmentError as exc:
                    log.info("Подію %s пропущено: %s", event_id, exc)
                    stats["skipped"] += 1
                else:
                    store.save_assessment(event_id, fp, result)
                    stats["assessed"] += 1
                    if result["alert"]["is_alert"] and _should_alert_again(
                            store.last_alert_for_event(event_id), result):
                        store.create_alert(event_id, result)
                        stats["alerts"] += 1
        except Exception:
            # Помилка доступу до БД або непередбачена: водяний знак далі не
            # просуваємо, щоб подію перевірили в наступному проході.
            log.exception("Помилка обробки події %s", event_id)
            stats["errors"] += 1
            break
        watermark = max(watermark, ev["updated_at"])

    store.set_state(WATERMARK_KEY, watermark)
    store.set_state("last_run_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))

    # Надсилаємо всі ще не доставлені сповіщення (зокрема з минулих проходів).
    if notifier is not None:
        for alert in store.unnotified_alerts():
            full = store.get_alert(alert["id"])
            if notifier.send(alert["id"], full["assessment"]):
                store.mark_notified(alert["id"])
                stats["notified"] += 1

    stats["watermark"] = watermark
    store.set_state("last_run_stats", json.dumps(stats, ensure_ascii=False))
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DIMS: сканер БД модуля моніторингу ІАС")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="один прохід і вихід")
    mode.add_argument("--interval", type=int, help="період сканування, секунд")
    parser.add_argument("--lookback-hours", type=int,
                        default=int(os.environ.get("DIMS_SCAN_LOOKBACK_HOURS", "24")),
                        help="глибина першого сканування (коли водяного знака ще немає)")
    parser.add_argument("--max-events", type=int,
                        default=int(os.environ.get("DIMS_SCAN_MAX_EVENTS", "200")))
    args = parser.parse_args(argv)

    logging.basicConfig(level=os.environ.get("DIMS_LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    source = SqlEventSource.from_env()
    store = IasStore()
    notifier = WebhookNotifier.from_env()
    if notifier is None:
        log.info("DIMS_ALERT_WEBHOOK_URL не задано — сповіщення доступні лише через API.")

    stop = {"flag": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(flag=True))

    while True:
        stats = run_once(source, store, notifier,
                         lookback_hours=args.lookback_hours, max_events=args.max_events)
        log.info("Прохід завершено: %s", stats)
        if args.once or stop["flag"]:
            return 0 if not stats["errors"] else 1
        for _ in range(max(1, args.interval)):
            if stop["flag"]:
                return 0
            time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())
