#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/state_store.py
===================
Спільний стан застосунку, що переживає кілька робочих процесів gunicorn
та (за наявності постійного диска) перезапуски сервера.

Навіщо: раніше стан (корпус джерел, результати аналізу, налаштування
пошуку) зберігався у звичайних словниках у пам'яті ОДНОГО процесу. На
Render запускається кілька воркерів, які пам'ять не ділять, тож запит на
експорт міг потрапити на «порожній» воркер. Цей модуль виносить стан у
SQLite-файл, спільний для всіх воркерів одного контейнера.

Без зовнішніх залежностей — лише стандартна бібліотека.
"""

from __future__ import annotations

import json
import os
import pickle
import sqlite3
import threading
from collections.abc import MutableMapping
from pathlib import Path


def _resolve_db_path() -> str:
    """Шлях до файлу стану. Пріоритет: env DIMS_STATE_DB → Data/ → /tmp."""
    env = os.environ.get("DIMS_STATE_DB")
    if env:
        return env
    data_dir = os.environ.get("DIMS_DATA_DIR")
    base = Path(data_dir) if data_dir else (Path(__file__).resolve().parent.parent / "Data")
    try:
        base.mkdir(parents=True, exist_ok=True)
        probe = base / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return str(base / "state.db")
    except Exception:
        return "/tmp/dims_state.db"


_DB_PATH = _resolve_db_path()
_LOCAL = threading.local()


def _conn() -> sqlite3.Connection:
    """Одне з'єднання на потік; WAL дає безпечний доступ кільком процесам."""
    c = getattr(_LOCAL, "conn", None)
    if c is None:
        c = sqlite3.connect(_DB_PATH, timeout=15, check_same_thread=False)
        c.execute("PRAGMA journal_mode=WAL;")
        c.execute("PRAGMA busy_timeout=15000;")
        c.execute(
            "CREATE TABLE IF NOT EXISTS kv ("
            "  ns   TEXT NOT NULL,"
            "  k    TEXT NOT NULL,"
            "  v    BLOB,"
            "  PRIMARY KEY (ns, k)"
            ");"
        )
        c.commit()
        _LOCAL.conn = c
    return c


class JsonMap(MutableMapping):
    """Словникоподібне сховище рядкових ключів із JSON-значеннями,
    спільне між процесами. Підходить для SOURCES (label → текст)."""

    def __init__(self, namespace: str):
        self._ns = namespace

    def __getitem__(self, key):
        row = _conn().execute(
            "SELECT v FROM kv WHERE ns=? AND k=?", (self._ns, key)
        ).fetchone()
        if row is None:
            raise KeyError(key)
        return json.loads(row[0])

    def __setitem__(self, key, value):
        c = _conn()
        c.execute(
            "INSERT INTO kv(ns,k,v) VALUES(?,?,?) "
            "ON CONFLICT(ns,k) DO UPDATE SET v=excluded.v",
            (self._ns, key, json.dumps(value, ensure_ascii=False)),
        )
        c.commit()

    def __delitem__(self, key):
        c = _conn()
        cur = c.execute("DELETE FROM kv WHERE ns=? AND k=?", (self._ns, key))
        c.commit()
        if cur.rowcount == 0:
            raise KeyError(key)

    def __iter__(self):
        rows = _conn().execute(
            "SELECT k FROM kv WHERE ns=? ORDER BY rowid", (self._ns,)
        ).fetchall()
        return iter(r[0] for r in rows)

    def __len__(self):
        return _conn().execute(
            "SELECT COUNT(*) FROM kv WHERE ns=?", (self._ns,)
        ).fetchone()[0]

    def clear(self):
        c = _conn()
        c.execute("DELETE FROM kv WHERE ns=?", (self._ns,))
        c.commit()


class Blob:
    """Одиничне значення довільного типу (pickle), спільне між процесами.
    Підходить для LAST_RESULTS (може містити numpy-масиви тощо)."""

    def __init__(self, namespace: str, key: str = "_"):
        self._ns = namespace
        self._k = key

    def get(self, default=None):
        row = _conn().execute(
            "SELECT v FROM kv WHERE ns=? AND k=?", (self._ns, self._k)
        ).fetchone()
        if row is None or row[0] is None:
            return default
        try:
            return pickle.loads(row[0])
        except Exception:
            return default

    def set(self, value) -> None:
        c = _conn()
        c.execute(
            "INSERT INTO kv(ns,k,v) VALUES(?,?,?) "
            "ON CONFLICT(ns,k) DO UPDATE SET v=excluded.v",
            (self._ns, self._k, pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)),
        )
        c.commit()

    def clear(self) -> None:
        c = _conn()
        c.execute("DELETE FROM kv WHERE ns=? AND k=?", (self._ns, self._k))
        c.commit()
