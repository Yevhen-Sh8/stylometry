#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/ias_store.py
=================
Власне сховище сервісу DIMS для інтеграції з ІАС: стан сканера (водяний знак),
останні оцінки подій, сповіщення та експертний зворотний зв'язок.

Окремий SQLite-файл (не state.db вебзастосунку). Тексти матеріалів НЕ
зберігаються — лише результати оцінки; першоджерело лишається в БД ІАС.
Експертні грейди з підтверджень сповіщень — основа для накопичення
валідаційного набору (docs/validation_protocol_ua.md).
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ALERT_STATUSES = {"open", "confirmed", "rejected"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scan_state (
    k TEXT PRIMARY KEY,
    v TEXT
);
CREATE TABLE IF NOT EXISTS assessments (
    event_id     TEXT PRIMARY KEY,
    fingerprint  TEXT NOT NULL,
    r_dims       REAL,
    grade        TEXT,
    is_alert     INTEGER NOT NULL DEFAULT 0,
    payload      TEXT NOT NULL,
    assessed_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alerts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id      TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    grade         TEXT NOT NULL,
    r_dims        REAL NOT NULL,
    payload       TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'open',
    notified      INTEGER NOT NULL DEFAULT 0,
    reviewed_at   TEXT,
    reviewer      TEXT,
    expert_grade  TEXT,
    comment       TEXT
);
CREATE INDEX IF NOT EXISTS ix_alerts_event ON alerts(event_id);
CREATE INDEX IF NOT EXISTS ix_alerts_status ON alerts(status);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_db_path() -> str:
    env = os.environ.get("DIMS_IAS_DB")
    if env:
        return env
    base = Path(os.environ.get("DIMS_DATA_DIR") or Path(__file__).resolve().parent.parent / "Data")
    base.mkdir(parents=True, exist_ok=True)
    return str(base / "ias_service.db")


class IasStore:
    def __init__(self, path: str | None = None):
        self.path = path or default_db_path()
        with self._conn() as c:
            c.executescript(_SCHEMA)

    @contextmanager
    def _conn(self):
        c = sqlite3.connect(self.path, timeout=15)
        c.row_factory = sqlite3.Row
        try:
            c.execute("PRAGMA journal_mode=WAL;")
            c.execute("PRAGMA busy_timeout=15000;")
            yield c
            c.commit()
        finally:
            c.close()

    # ── стан сканера ─────────────────────────────────────────────────────
    def get_state(self, key: str, default: str | None = None) -> str | None:
        with self._conn() as c:
            row = c.execute("SELECT v FROM scan_state WHERE k=?", (key,)).fetchone()
        return row["v"] if row else default

    def set_state(self, key: str, value: str) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO scan_state(k, v) VALUES(?, ?) "
                      "ON CONFLICT(k) DO UPDATE SET v=excluded.v", (key, value))

    # ── оцінки ───────────────────────────────────────────────────────────
    def get_fingerprint(self, event_id: str) -> str | None:
        with self._conn() as c:
            row = c.execute("SELECT fingerprint FROM assessments WHERE event_id=?",
                            (event_id,)).fetchone()
        return row["fingerprint"] if row else None

    def save_assessment(self, event_id: str, fingerprint: str, result: dict) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO assessments(event_id, fingerprint, r_dims, grade, is_alert, payload, assessed_at) "
                "VALUES(?,?,?,?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET "
                "fingerprint=excluded.fingerprint, r_dims=excluded.r_dims, grade=excluded.grade, "
                "is_alert=excluded.is_alert, payload=excluded.payload, assessed_at=excluded.assessed_at",
                (event_id, fingerprint, result["r_dims"], result["grade"]["grade"],
                 int(result["alert"]["is_alert"]), json.dumps(result, ensure_ascii=False), _now()),
            )

    def get_assessment(self, event_id: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT payload FROM assessments WHERE event_id=?",
                            (event_id,)).fetchone()
        return json.loads(row["payload"]) if row else None

    # ── сповіщення ───────────────────────────────────────────────────────
    def last_alert_for_event(self, event_id: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM alerts WHERE event_id=? ORDER BY id DESC LIMIT 1",
                            (event_id,)).fetchone()
        return self._alert_row(row) if row else None

    def create_alert(self, event_id: str, result: dict) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO alerts(event_id, created_at, grade, r_dims, payload) VALUES(?,?,?,?,?)",
                (event_id, _now(), result["grade"]["grade"], result["r_dims"],
                 json.dumps(result, ensure_ascii=False)),
            )
            return int(cur.lastrowid)

    def mark_notified(self, alert_id: int) -> None:
        with self._conn() as c:
            c.execute("UPDATE alerts SET notified=1 WHERE id=?", (alert_id,))

    def unnotified_alerts(self, limit: int = 50) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM alerts WHERE notified=0 ORDER BY id LIMIT ?",
                             (limit,)).fetchall()
        return [self._alert_row(r) for r in rows]

    def get_alert(self, alert_id: int) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone()
        return self._alert_row(row, full=True) if row else None

    def list_alerts(self, status: str | None = None, since_id: int = 0,
                    limit: int = 50) -> list[dict]:
        sql, args = "SELECT * FROM alerts WHERE id > ?", [since_id]
        if status:
            sql += " AND status = ?"
            args.append(status)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self._conn() as c:
            rows = c.execute(sql, args).fetchall()
        return [self._alert_row(r) for r in rows]

    def review_alert(self, alert_id: int, status: str, expert_grade: str | None,
                     comment: str | None, reviewer: str | None) -> dict | None:
        with self._conn() as c:
            cur = c.execute(
                "UPDATE alerts SET status=?, expert_grade=?, comment=?, reviewer=?, reviewed_at=? "
                "WHERE id=?",
                (status, expert_grade, comment, reviewer, _now(), alert_id),
            )
            if cur.rowcount == 0:
                return None
        return self.get_alert(alert_id)

    def feedback(self) -> list[dict]:
        """Пари «грейд DIMS ↔ експертний грейд» — заготовка валідаційного набору."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, event_id, grade, r_dims, status, expert_grade, reviewed_at "
                "FROM alerts WHERE reviewed_at IS NOT NULL ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def counts(self) -> dict:
        with self._conn() as c:
            n_assess = c.execute("SELECT COUNT(*) FROM assessments").fetchone()[0]
            by_status = {r[0]: r[1] for r in c.execute(
                "SELECT status, COUNT(*) FROM alerts GROUP BY status").fetchall()}
        return {"assessments": n_assess, "alerts": by_status}

    @staticmethod
    def _alert_row(row: sqlite3.Row, full: bool = False) -> dict:
        d = dict(row)
        payload = json.loads(d.pop("payload"))
        d["notified"] = bool(d["notified"])
        d["kinds"] = payload.get("alert", {}).get("kinds", [])
        d["signals"] = payload.get("alert", {}).get("coordination_signals", [])
        d["confidence"] = payload.get("confidence", {})
        if full:
            d["assessment"] = payload
        return d
