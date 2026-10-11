#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_ias_service.py
=========================
Тести інтеграційного сервісу DIMS ↔ ІАС: безстанова оцінка події,
REST API v1 (автентифікація, валідація) і повний цикл сканера на тестовій
SQLite-БД, що імітує БД модуля моніторингу ІАС.

Запуск:  .venv/bin/python -m pytest tests/test_ias_service.py -q
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
from core.ias_scanner import SqlEventSource, materials_fingerprint, run_once
from core.ias_service import AssessmentError, assess_event, decide_alert
from core.ias_store import IasStore

POLICY = {"min_grade": "S", "min_coord": 0.40, "min_copy_sources": 3,
          "copy_paste_standalone": True}

_VOCAB = ("влада армія фронт мобілізація партнери гроші переговори санкції "
          "енергетика вибори реформа суд закон бюджет допомога союзники "
          "заява міністр депутат регіон кордон безпека економіка ціни").split()


def _text(seed: int, n: int = 300) -> str:
    """Детермінований псевдотекст: різні seed → різні частотні профілі."""
    words = []
    for i in range(n):
        words.append(_VOCAB[(i * (seed + 3) + seed * 7) % len(_VOCAB)])
        if i % 9 == 0:
            words.append(["і", "та", "але", "що", "як", "не"][(i + seed) % 6])
    return " ".join(words) + "."


def _material(mid, source, text, ts="2026-10-10T10:00:00", **kw):
    return {"id": mid, "source": source, "text": text, "published_at": ts, **kw}


# ── assess_event ────────────────────────────────────────────────────────────

def test_assess_event_basic_structure_and_ranges():
    mats = [_material(f"m{i}", f"src{i}", _text(i)) for i in range(4)]
    r = assess_event(mats, event_id="e1", alert_policy=POLICY)
    assert r["event_id"] == "e1"
    assert 0.0 <= r["r_dims"] <= 1.0
    assert r["grade"]["grade"] in {"F", "B", "S", "SS", "SSS"}
    assert set(r["indicators"]) == {"I_content", "I_coord", "I_dynamics", "I_impact", "I_source"}
    assert all(0.0 <= v <= 1.0 for v in r["indicators"].values())
    assert r["stats"]["n_sources"] == 4
    assert r["coordination"]["assessable"] is True
    assert r["confidence"].get("lo") is not None


def test_posts_of_one_channel_are_aggregated_into_one_document():
    mats = [_material(f"a{k}", "chan_a", _text(10 + k, 80)) for k in range(3)]
    mats += [_material(f"b{k}", "chan_b", _text(20 + k, 80)) for k in range(2)]
    r = assess_event(mats, alert_policy=POLICY)
    assert r["stats"]["n_sources"] == 2
    assert r["stats"]["sources"] == {"chan_a": 3, "chan_b": 2}


def test_copy_paste_is_deduplicated_but_reported_and_alerts():
    same = _text(1)
    mats = [_material(f"c{i}", f"chan{i}", same, ts=f"2026-10-10T10:0{i}:00") for i in range(4)]
    mats.append(_material("x", "other", _text(5)))
    r = assess_event(mats, alert_policy=POLICY)
    assert r["stats"]["n_unique_materials"] == 2       # копії не йдуть у стилометрію
    cluster = r["coordination"]["copy_clusters"][0]
    assert cluster["n_sources"] == 4
    assert cluster["first_source"] == "chan0"           # найраніша публікація
    assert r["alert"]["is_alert"] and "copy_paste" in r["alert"]["kinds"]


def test_copy_paste_standalone_can_be_disabled():
    same = _text(1)
    mats = [_material(f"c{i}", f"chan{i}", same) for i in range(4)]
    mats.append(_material("x", "other", _text(5)))
    r = assess_event(mats, alert_policy={**POLICY, "copy_paste_standalone": False})
    assert "copy_paste" not in r["alert"]["kinds"]


def test_single_source_does_not_fake_coordination():
    r = assess_event([_material("m1", "only", _text(3))], alert_policy=POLICY)
    assert r["coordination"]["assessable"] is False
    assert r["coordination"]["flagged_pairs"] == []
    assert r["warnings"]


def test_formula_unchanged_r_dims_equals_weighted_sum():
    mats = [_material(f"m{i}", f"src{i}", _text(i)) for i in range(3)]
    r = assess_event(mats, alert_policy=POLICY)
    w, ind = r["weights"], r["indicators"]
    expected = sum(w[k] * ind[f"I_{k}"] for k in w)
    assert abs(expected - r["r_dims"]) < 1e-3


@pytest.mark.parametrize("bad", [None, [], [{"text": "без джерела"}], "рядок"])
def test_invalid_materials_rejected(bad):
    with pytest.raises(AssessmentError):
        assess_event(bad, alert_policy=POLICY)


def test_invalid_params_rejected():
    mats = [_material(f"m{i}", f"s{i}", _text(i)) for i in range(2)]
    with pytest.raises(AssessmentError):
        assess_event(mats, mfw_n=5)
    with pytest.raises(AssessmentError):
        assess_event(mats, manifestation="невідомо")


def test_decide_alert_requires_grade_and_signal():
    base = {"grade": {"grade": "S"}, "indicators": {"I_coord": 0.5}}
    assert decide_alert(base, 0, [], POLICY)["kinds"] == ["dims"]
    low = {"grade": {"grade": "B"}, "indicators": {"I_coord": 0.9}}
    assert decide_alert(low, 3, [], POLICY)["is_alert"] is False
    no_signal = {"grade": {"grade": "SS"}, "indicators": {"I_coord": 0.1}}
    assert decide_alert(no_signal, 0, [], POLICY)["is_alert"] is False


# ── REST API v1 ─────────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DIMS_SERVICE_TOKENS", "tok-1, tok-2")
    monkeypatch.setattr(api_v1, "_STORE", IasStore(str(tmp_path / "ias.db")))
    import app as webapp
    webapp.app.config["TESTING"] = True
    return webapp.app.test_client()


AUTH = {"Authorization": "Bearer tok-2"}


def test_api_requires_configured_tokens(client, monkeypatch):
    monkeypatch.delenv("DIMS_SERVICE_TOKENS")
    assert client.get("/api/v1/status", headers=AUTH).status_code == 503


def test_api_rejects_missing_or_wrong_token(client):
    assert client.get("/api/v1/status").status_code == 401
    assert client.get("/api/v1/status", headers={"Authorization": "Bearer nope"}).status_code == 401
    # Адмін-токен вебзастосунку не відкриває API v1, і навпаки.
    assert client.get("/api/v1/status", headers={"X-DIMS-Admin-Token": "tok-1"}).status_code == 401


def test_api_v1_not_blocked_by_web_admin_token(client, monkeypatch):
    monkeypatch.setenv("DIMS_ADMIN_TOKEN", "admin-secret")
    mats = [_material(f"m{i}", f"s{i}", _text(i)) for i in range(3)]
    resp = client.post("/api/v1/assess", json={"materials": mats}, headers=AUTH)
    assert resp.status_code == 200


def test_web_admin_token_not_accepted_from_query_string(client, monkeypatch):
    monkeypatch.setenv("DIMS_ADMIN_TOKEN", "admin-secret")
    resp = client.post("/api/clear?admin_token=admin-secret")
    assert resp.status_code == 401


def test_api_assess_ok_and_validation(client):
    mats = [_material(f"m{i}", f"s{i}", _text(i)) for i in range(3)]
    resp = client.post("/api/v1/assess", json={"event_id": 42, "materials": mats}, headers=AUTH)
    body = resp.get_json()
    assert resp.status_code == 200 and body["ok"]
    assert body["assessment"]["event_id"] == "42"
    assert client.post("/api/v1/assess", json={"materials": []}, headers=AUTH).status_code == 422
    assert client.post("/api/v1/assess", data="x", headers=AUTH).status_code == 400
    bad = client.post("/api/v1/assess", json={"materials": mats, "params": {"mfw_n": "abc"}},
                      headers=AUTH)
    assert bad.status_code == 400


# ── Сканер БД ІАС (повний цикл) ─────────────────────────────────────────────

CHANGED_SQL = ("SELECT event_id, MAX(updated_at) AS updated_at FROM materials "
               "WHERE updated_at >= :since GROUP BY event_id")
MATERIALS_SQL = ("SELECT id, channel AS source, platform, url, published_at, body AS text "
                 "FROM materials WHERE event_id = :event_id")


def _make_ias_db(path: Path) -> None:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE materials (id TEXT, event_id TEXT, channel TEXT, platform TEXT, "
                "url TEXT, published_at TEXT, body TEXT, updated_at TEXT)")
    same = _text(1)
    rows = [(f"m{i}", "ev-copy", f"chan{i}", "telegram", "", f"2026-10-10T10:0{i}:00",
             same, "2026-10-10T10:10:00") for i in range(4)]
    rows += [("n1", "ev-calm", "news1", "web", "", "2026-10-10T09:00:00", _text(30),
              "2026-10-10T09:30:00"),
             ("n2", "ev-calm", "news2", "web", "", "2026-10-10T11:00:00", _text(31),
              "2026-10-10T11:30:00")]
    con.executemany("INSERT INTO materials VALUES (?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()


class _FakeNotifier:
    def __init__(self, ok=True):
        self.ok, self.sent = ok, []

    def send(self, alert_id, result):
        self.sent.append((alert_id, result["event_id"]))
        return self.ok


@pytest.fixture
def scanner_env(tmp_path):
    db = tmp_path / "ias_source.db"
    _make_ias_db(db)
    source = SqlEventSource(f"sqlite:///{db}", CHANGED_SQL, MATERIALS_SQL)
    store = IasStore(str(tmp_path / "svc.db"))
    store.set_state("watermark", "2026-10-10T00:00:00")
    return db, source, store


def test_scanner_full_cycle_alerts_once_and_is_idempotent(scanner_env):
    db, source, store = scanner_env
    notifier = _FakeNotifier()
    stats = run_once(source, store, notifier, alert_policy=POLICY)
    assert stats["changed_events"] == 2 and stats["assessed"] == 2 and stats["errors"] == 0
    assert stats["alerts"] == 1 and notifier.sent == [(1, "ev-copy")]
    assert store.get_assessment("ev-calm") is not None
    assert stats["watermark"] == "2026-10-10T11:30:00"

    # Повторний прохід: нічого не змінилось → без повторних оцінок і сповіщень.
    stats2 = run_once(source, store, notifier, alert_policy=POLICY)
    assert stats2["assessed"] == 0 and stats2["alerts"] == 0
    assert len(notifier.sent) == 1


def test_scanner_reassesses_event_when_new_material_arrives(scanner_env):
    db, source, store = scanner_env
    run_once(source, store, None, alert_policy=POLICY)
    con = sqlite3.connect(db)
    con.execute("INSERT INTO materials VALUES ('n3','ev-calm','news3','web','',"
                "'2026-10-10T12:00:00',?, '2026-10-10T12:05:00')", (_text(32),))
    con.commit()
    con.close()
    stats = run_once(source, store, None, alert_policy=POLICY)
    assert stats["assessed"] == 1
    assert store.get_assessment("ev-calm")["stats"]["n_sources"] == 3


def test_scanner_retries_failed_webhook_on_next_run(scanner_env):
    _, source, store = scanner_env
    failing = _FakeNotifier(ok=False)
    run_once(source, store, failing, alert_policy=POLICY)
    assert store.unnotified_alerts()
    ok = _FakeNotifier(ok=True)
    stats = run_once(source, store, ok, alert_policy=POLICY)
    assert stats["notified"] == 1 and not store.unnotified_alerts()


def test_alert_review_feeds_validation_feedback(scanner_env, client):
    _, source, store = scanner_env
    run_once(source, store, None, alert_policy=POLICY)
    api_v1._STORE = store
    alerts = client.get("/api/v1/alerts?status=open", headers=AUTH).get_json()["alerts"]
    assert len(alerts) == 1 and alerts[0]["kinds"] == ["copy_paste"]
    aid = alerts[0]["id"]
    bad = client.post(f"/api/v1/alerts/{aid}/review", json={"status": "confirmed",
                                                           "expert_grade": "Z"}, headers=AUTH)
    assert bad.status_code == 400
    ok = client.post(f"/api/v1/alerts/{aid}/review",
                     json={"status": "confirmed", "expert_grade": "SS", "comment": "кампанія"},
                     headers=AUTH)
    assert ok.status_code == 200 and ok.get_json()["alert"]["expert_grade"] == "SS"
    fb = client.get("/api/v1/feedback", headers=AUTH).get_json()["feedback"]
    assert fb[0]["event_id"] == "ev-copy" and fb[0]["expert_grade"] == "SS"
    assert client.get("/api/v1/alerts/999", headers=AUTH).status_code == 404


def test_fingerprint_changes_with_text():
    a = [{"id": "1", "source": "s", "text": "a"}]
    b = [{"id": "1", "source": "s", "text": "b"}]
    assert materials_fingerprint(a) != materials_fingerprint(b)


def test_source_requires_parameters():
    with pytest.raises(ValueError):
        SqlEventSource("sqlite://", "SELECT 1", MATERIALS_SQL)
    with pytest.raises(ValueError):
        SqlEventSource("sqlite://", CHANGED_SQL, "SELECT 1")


def test_status_reports_last_run_as_json(scanner_env, client):
    _, source, store = scanner_env
    run_once(source, store, None, alert_policy=POLICY)
    api_v1._STORE = store
    st = client.get("/api/v1/status", headers=AUTH).get_json()["scanner"]
    assert st["last_run_stats"]["assessed"] == 2
    assert st["watermark"] == "2026-10-10T11:30:00"


# ── ШІ-транскрипти відео ────────────────────────────────────────────────────

def test_video_platforms_default_to_transcript_and_pairs_are_marked():
    mats = [_material("y1", "yt_chan", _text(2), platform="youtube"),
            _material("t1", "tg_chan", _text(4), platform="telegram"),
            _material("t2", "tg_other", _text(3), platform="telegram")]
    r = assess_event(mats, alert_policy=POLICY, threshold=2.0)
    assert r["stats"]["text_origins"] == {"yt_chan": "transcript", "tg_chan": "text",
                                          "tg_other": "text"}
    assert any("транскрипт" in w for w in r["warnings"])
    origins = r["stats"]["text_origins"]
    pairs = r["coordination"]["flagged_pairs"]
    assert pairs  # при θ = 2.0 є пари для перевірки
    for p in pairs:
        assert p["cross_origin"] is (origins[p["a"]] != origins[p["b"]])


def test_explicit_text_origin_overrides_platform_and_is_validated():
    mats = [_material("y1", "yt", _text(2), platform="youtube", text_origin="text"),
            _material("t1", "tg", _text(3), platform="telegram")]
    r = assess_event(mats, alert_policy=POLICY)
    assert set(r["stats"]["text_origins"].values()) == {"text"}
    assert not any("транскрипт" in w for w in r["warnings"])
    with pytest.raises(AssessmentError):
        assess_event([_material("x", "s", _text(1), text_origin="audio")])


def test_source_with_both_origins_is_mixed():
    mats = [_material("a", "chan", _text(2), platform="youtube"),
            _material("b", "chan", _text(3), platform="telegram"),
            _material("c", "other", _text(4))]
    r = assess_event(mats, alert_policy=POLICY)
    assert r["stats"]["text_origins"]["chan"] == "mixed"


# ── Webhook у ІАС: підпис та ідемпотентність ────────────────────────────────

def test_webhook_sends_signed_idempotent_request(monkeypatch):
    import json as _json
    from core import ias_scanner
    captured = {}

    class _Resp:
        status_code = 202

    def fake_post(url, data=None, headers=None, timeout=None, verify=None):
        captured.update(url=url, data=data, headers=headers)
        return _Resp()

    monkeypatch.setattr(ias_scanner.requests, "post", fake_post)
    same = _text(1)
    mats = [_material(f"c{i}", f"chan{i}", same) for i in range(3)]
    result = assess_event(mats, event_id="ev-9", alert_policy=POLICY)
    n = ias_scanner.WebhookNotifier("https://ias.local/hook", token="t", secret="s3cret",
                                    public_url="https://dims.local")
    assert n.send(7, result) is True

    h = captured["headers"]
    assert h["X-DIMS-Alert-Id"] == "7" and h["Authorization"] == "Bearer t"
    expected = ias_scanner.sign_payload("s3cret", h["X-DIMS-Timestamp"], captured["data"])
    assert h["X-DIMS-Signature"] == expected
    # Підпис змінюється при будь-якій зміні тіла (захист від підробки).
    assert ias_scanner.sign_payload("s3cret", h["X-DIMS-Timestamp"], captured["data"] + b" ") != expected
    body = _json.loads(captured["data"].decode("utf-8"))
    assert body["alert_id"] == 7 and body["event_id"] == "ev-9"
    assert body["url"] == "https://dims.local/api/v1/alerts/7"
    assert "text" not in _json.dumps(body["copy_clusters"])  # тексти не передаються


def test_webhook_without_secret_has_no_signature(monkeypatch):
    from core import ias_scanner
    captured = {}

    class _Resp:
        status_code = 500

    monkeypatch.setattr(ias_scanner.requests, "post",
                        lambda url, **kw: captured.update(kw) or _Resp())
    mats = [_material(f"m{i}", f"s{i}", _text(i)) for i in range(2)]
    result = assess_event(mats, alert_policy=POLICY)
    assert ias_scanner.WebhookNotifier("https://ias.local/hook").send(1, result) is False
    assert "X-DIMS-Signature" not in captured["headers"]
