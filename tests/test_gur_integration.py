#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_gur_integration.py
=============================
Інтеграція макрорівня (прототип ГУР-2016) із сервісом ІАС: метадані gur у
assess_event, REST API v1 (/assess, /events/<id>/gur, /threat-level) і
прокидання колонок gur_* та reach через сканер БД моніторингу.

Запуск:  .venv/bin/python -m pytest tests/test_gur_integration.py -q
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from core import api_v1
from core.ias_scanner import SqlEventSource, run_once
from core.ias_service import AssessmentError, assess_event
from core.ias_store import IasStore

POLICY = {"min_grade": "S", "min_coord": 0.40, "min_copy_sources": 3,
          "copy_paste_standalone": True}
_VOCAB = ("влада армія фронт мобілізація партнери гроші переговори санкції енергетика "
          "вибори реформа суд закон бюджет допомога союзники заява міністр депутат регіон "
          "кордон безпека економіка ціни").split()
AUTH = {"Authorization": "Bearer tok-1"}


def _text(seed: int, n: int = 300) -> str:
    words = []
    for i in range(n):
        words.append(_VOCAB[(i * (seed + 3) + seed * 7) % len(_VOCAB)])
        if i % 9 == 0:
            words.append(["і", "та", "але", "що", "як", "не"][(i + seed) % 6])
    return " ".join(words) + "."


def _mats(ts_first="2026-10-01T09:00:00", ts_last="2026-10-05T18:00:00"):
    return [{"id": "m1", "source": "chan_a", "text": _text(1), "published_at": ts_first},
            {"id": "m2", "source": "chan_b", "text": _text(2), "published_at": ts_last},
            {"id": "m3", "source": "chan_c", "text": _text(3), "published_at": "2026-10-03T12:00:00"}]


# ── assess_event ────────────────────────────────────────────────────────────
def test_assess_event_carries_gur_and_period_without_changing_formula():
    plain = assess_event(_mats(), event_id="e", alert_policy=POLICY)
    tagged = assess_event(_mats(), event_id="e", alert_policy=POLICY,
                          gur={"direction": "m4", "sphere": "воєнна", "reach": "регіональний"})
    assert tagged["gur"] == {"direction": "m4", "sphere": "military", "reach": "regional"}
    assert tagged["period"] == {"first_published": "2026-10-01T09:00:00",
                                "last_published": "2026-10-05T18:00:00"}
    assert tagged["r_dims"] == plain["r_dims"]          # R_DIMS не залежить від gur
    assert plain["gur"] == {}


def test_assess_event_rejects_invalid_gur():
    with pytest.raises(AssessmentError):
        assess_event(_mats(), gur={"target_scale": "single", "target_value": 0.95})


# ── REST API v1 ─────────────────────────────────────────────────────────────
@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("DIMS_SERVICE_TOKENS", "tok-1")
    store = IasStore(str(tmp_path / "ias.db"))
    monkeypatch.setattr(api_v1, "_STORE", store)
    import app as webapp
    webapp.app.config["TESTING"] = True
    return webapp.app.test_client(), store


def test_api_assess_accepts_gur(api):
    client, _ = api
    r = client.post("/api/v1/assess", headers=AUTH,
                    json={"event_id": "e1", "materials": _mats(), "gur": {"direction": "m1"}})
    assert r.status_code == 200 and r.get_json()["assessment"]["gur"] == {"direction": "m1"}
    bad = client.post("/api/v1/assess", headers=AUTH,
                      json={"materials": _mats(), "gur": {"reach": "galactic"}})
    assert bad.status_code == 422


def test_api_expert_gur_and_threat_level(api):
    client, store = api
    result = assess_event(_mats(), event_id="e1", alert_policy=POLICY,
                          gur={"direction": "m3"})
    store.save_assessment("e1", "fp", result)

    # експертне доповнення: злиття з наявним напрямом, валідація цілого блоку
    r = client.post("/api/v1/events/e1/gur", headers=AUTH,
                    json={"reach": "national", "target_scale": "group",
                          "target_audience": ["особовий склад"], "n_negative": 2, "n_total": 3})
    assert r.status_code == 200
    gur = r.get_json()["gur"]
    assert gur["direction"] == "m3" and gur["reach"] == "national"
    assert client.post("/api/v1/events/e1/gur", headers=AUTH,
                       json={"target_value": 0.95}).status_code == 422   # не відповідає group
    assert client.post("/api/v1/events/nope/gur", headers=AUTH, json={}).status_code == 404
    # null видаляє ключ
    r2 = client.post("/api/v1/events/e1/gur", headers=AUTH, json={"n_negative": None,
                                                                   "n_total": None})
    assert "n_negative" not in r2.get_json()["gur"]

    t = client.get("/api/v1/threat-level?from=2026-09-29&to=2026-10-12", headers=AUTH)
    assert t.status_code == 200
    body = t.get_json()
    mil = body["spheres"][0]
    assert mil["sphere"] == "military"
    d = mil["directions"][0]
    assert d["direction"] == "m3" and d["indicator_sources"]["K_d"] == "expert"
    assert d["target_audience"]["audiences"][0]["audience"] == "особовий склад"
    assert mil["level"]["key"] in {"low", "elevated", "high", "critical"}
    assert len(mil["series"]) == 2                       # два тижневі вікна


def test_api_threat_level_validation_and_auth(api):
    client, _ = api
    assert client.get("/api/v1/threat-level").status_code == 401
    assert client.get("/api/v1/threat-level?from=bad", headers=AUTH).status_code == 400
    assert client.get("/api/v1/threat-level?window_days=0", headers=AUTH).status_code == 400
    assert client.get("/api/v1/threat-level?from=2026-10-10&to=2026-10-01",
                      headers=AUTH).status_code == 400
    empty = client.get("/api/v1/threat-level", headers=AUTH)
    assert empty.status_code == 200 and empty.get_json()["spheres"] == []


# ── сканер БД моніторингу ІАС ───────────────────────────────────────────────
CHANGED_SQL = ("SELECT e.event_id, MAX(m.updated_at) AS updated_at, e.direction AS gur_direction, "
               "e.sphere AS gur_sphere, e.reach AS gur_reach FROM materials m "
               "JOIN events e ON e.event_id = m.event_id "
               "WHERE m.updated_at >= :since GROUP BY e.event_id")
MATERIALS_SQL = ("SELECT id, channel AS source, published_at, body AS text, reach "
                 "FROM materials WHERE event_id = :event_id")


@pytest.fixture
def ias_db(tmp_path):
    path = tmp_path / "ias_source.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE events (event_id TEXT, direction TEXT, sphere TEXT, reach TEXT)")
    con.execute("CREATE TABLE materials (id TEXT, event_id TEXT, channel TEXT, published_at TEXT, "
                "body TEXT, reach TEXT, updated_at TEXT)")
    con.execute("INSERT INTO events VALUES ('ev1', 'm5', 'воєнна', NULL)")
    con.executemany("INSERT INTO materials VALUES (?,?,?,?,?,?,?)", [
        ("a", "ev1", "chan_a", "2026-10-01T09:00:00", _text(11), "regional", "2026-10-01T10:00:00"),
        ("b", "ev1", "chan_b", "2026-10-02T09:00:00", _text(12), "international", "2026-10-02T10:00:00"),
    ])
    con.commit()
    con.close()
    store = IasStore(str(tmp_path / "svc.db"))
    store.set_state("watermark", "2026-09-30T00:00:00")
    return path, SqlEventSource(f"sqlite:///{path}", CHANGED_SQL, MATERIALS_SQL), store


def test_scanner_passes_gur_columns_and_preserves_expert_input(ias_db):
    path, source, store = ias_db
    stats = run_once(source, store, None, alert_policy=POLICY)
    assert stats["assessed"] == 1 and stats["errors"] == 0
    gur = store.get_assessment("ev1")["gur"]
    assert gur["direction"] == "m5" and gur["sphere"] == "military"
    assert gur["source_reach"] == {"chan_a": "regional", "chan_b": "international"}

    # аналітик додає ЦА через API-рівень сховища; нова публікація → повторна оцінка
    store.set_gur("ev1", {**gur, "target_audience": ["резервісти"]})
    con = sqlite3.connect(path)
    con.execute("INSERT INTO materials VALUES ('c','ev1','chan_c','2026-10-03T09:00:00',?, "
                "NULL,'2026-10-03T10:00:00')", (_text(13),))
    con.commit()
    con.close()
    run_once(source, store, None, alert_policy=POLICY)
    gur2 = store.get_assessment("ev1")["gur"]
    assert gur2["target_audience"] == ["резервісти"]     # експертний ввід збережено
    assert store.get_assessment("ev1")["stats"]["n_sources"] == 3


def test_scanner_invalid_gur_does_not_block_assessment(ias_db):
    path, source, store = ias_db
    con = sqlite3.connect(path)
    con.execute("UPDATE events SET reach = 'galactic'")
    con.commit()
    con.close()
    stats = run_once(source, store, None, alert_policy=POLICY)
    assert stats["assessed"] == 1 and stats["skipped"] == 0
    assert store.get_assessment("ev1")["gur"] == {}       # відхилено, попередніх немає
