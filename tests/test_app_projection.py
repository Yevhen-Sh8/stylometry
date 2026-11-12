#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_app_projection.py
============================
Регресійний тест: вибір методу проєкції у вебінтерфейсі має доходити до
конвеєра аналізу. static/app.js надсилає поле ``projection_method``, а
API-клієнти — ``projection``; /api/analyze мусить приймати обидва імені.

Запуск:  .venv/bin/python -m pytest tests/test_app_projection.py -q
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import app as app_module
import core.monitoring_log as monitoring_log
import core.state_store as state_store

_VOCAB = ("влада армія фронт мобілізація партнери гроші переговори санкції "
          "енергетика вибори реформа суд закон бюджет допомога союзники "
          "заява міністр депутат регіон кордон безпека економіка ціни").split()
_FUNC = ["і", "та", "але", "що", "як", "не"]


def _text(seed: int, n: int = 300) -> str:
    """Детермінований псевдотекст: різні seed → різні частотні профілі."""
    words = []
    for i in range(n):
        words.append(_VOCAB[(i * (seed + 3) + seed * 7) % len(_VOCAB)])
        if i % 9 == 0:
            words.append(_FUNC[(i + seed) % len(_FUNC)])
    return " ".join(words) + "."


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Flask test client з ізольованим станом (SQLite, журнал, output/)."""
    monkeypatch.delenv("DIMS_ADMIN_TOKEN", raising=False)

    # Спільний SQLite-стан → тимчасовий файл; скидаємо кешоване з'єднання.
    old_conn = getattr(state_store._LOCAL, "conn", None)
    monkeypatch.setattr(state_store, "_DB_PATH", str(tmp_path / "state.db"))
    state_store._LOCAL.conn = None

    out_dir = tmp_path / "output"
    monkeypatch.setattr(app_module, "OUTPUT_DIR", out_dir)
    monkeypatch.setattr(app_module, "CLEAN_DIR", out_dir / "clean_texts")
    monkeypatch.setattr(monitoring_log, "LOG_FILE", tmp_path / "monitoring_log.jsonl")

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c

    conn = getattr(state_store._LOCAL, "conn", None)
    if conn is not None:
        conn.close()
    state_store._LOCAL.conn = old_conn


def _add_texts(client, n: int = 3) -> None:
    for i in range(n):
        resp = client.post("/api/add-text",
                           json={"label": f"джерело_{i}", "text": _text(i)})
        body = resp.get_json()
        assert resp.status_code == 200, body
        assert body["ok"] is True, body


def test_analyze_respects_projection_method_from_ui(client):
    _add_texts(client, 3)

    resp = client.post("/api/analyze", json={"projection_method": "mds"})
    body = resp.get_json()
    assert resp.status_code == 200, body
    assert body["ok"] is True, body

    assert body["projection_method"] == "mds"
    meta = body["projection_meta"]
    assert meta["method"] == "mds"
    assert meta["subtitle"].startswith("MDS (stress =")
    # Пояснена дисперсія є лише у PCA.
    assert meta["explained_variance"] is None


def test_analyze_projection_alias_still_works(client):
    """Поле ``projection`` (API-клієнти) лишається робочим і має пріоритет."""
    _add_texts(client, 3)

    resp = client.post("/api/analyze",
                       json={"projection": "mds", "projection_method": "tsne"})
    body = resp.get_json()
    assert resp.status_code == 200, body
    assert body["projection_method"] == "mds"
    assert body["projection_meta"]["method"] == "mds"


def test_analyze_defaults_to_pca(client):
    _add_texts(client, 3)

    resp = client.post("/api/analyze", json={})
    body = resp.get_json()
    assert resp.status_code == 200, body
    assert body["projection_method"] == "pca"
    assert body["projection_meta"]["method"] == "pca"
