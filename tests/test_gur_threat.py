#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_gur_threat.py
========================
Макрорівень за прототипом ГУР-2016 (core/gur_threat.py): точне відтворення
формул і таблиць прототипу + доповнення автора (інструменти, ЦА, факти, тренд).

Запуск:  .venv/bin/python -m pytest tests/test_gur_threat.py -q
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from core import gur_threat as g

D0 = date(2026, 3, 2)


def _d(offset: int) -> str:
    return (D0 + timedelta(days=offset)).isoformat()


def A(eid, first, last=None, *, direction="m1", sphere="military", grade="S", n=4,
      sources=None, pairs=(), clusters=(), **gur):
    """Мінімальна збережена DIMS-оцінка події з метаданими ГУР."""
    last = first if last is None else last
    meta = {"direction": direction, "sphere": sphere, **gur}
    return {
        "event_id": eid,
        "assessed_at": f"{_d(last)}T12:00:00+00:00",
        "r_dims": 0.5,
        "grade": {"grade": grade},
        "period": {"first_published": f"{_d(first)}T08:00:00", "last_published": f"{_d(last)}T20:00:00"},
        "stats": {"n_unique_materials": n, "sources": sources or {"src_a": 2, "src_b": 2}},
        "coordination": {"flagged_pairs": list(pairs), "copy_clusters": list(clusters)},
        "gur": g.normalise_gur_meta(meta),
    }


# ── формули і таблиці прототипу ─────────────────────────────────────────────
@pytest.mark.parametrize("days,expected", [
    (7, 0.15), (14, 0.26), (31, 0.43), (92, 0.70), (273, 0.87), (365, 0.90), (730, 0.97),
])
def test_duration_reproduces_table_4(days, expected):
    assert g.duration_coefficient(days) == pytest.approx(expected, abs=0.01)


def test_duration_has_prototype_jump_at_one_year():
    # дві різні константи a → стрибок на межі року (властивість прототипу)
    assert g.duration_coefficient(366) - g.duration_coefficient(365) > 0.04
    assert g.duration_coefficient(0) == 0.0


@pytest.mark.parametrize("z,key", [
    (0.0, "low"), (0.25, "low"), (0.26, "elevated"), (0.5, "elevated"),
    (0.51, "high"), (0.75, "high"), (0.76, "critical"), (1.0, "critical"),
])
def test_threat_level_table_6_half_open(z, key):
    assert g.threat_level(z)["key"] == key


@pytest.mark.parametrize("k,key", [(0.2, "low"), (0.21, "medium"), (0.6, "elevated"),
                                   (0.61, "high"), (0.81, "critical")])
def test_intensity_levels(k, key):
    assert g.intensity_level(k)["key"] == key


def test_reach_and_object_scale():
    assert g.reach_value("міжнародний") == 1.0
    assert g.reach_value("regional") == 0.5
    assert g.object_scale_value("group") == (0.505, "expert_midpoint")
    assert g.object_scale_value("масовий", 0.9) == (0.9, "expert")


def test_normalized_indicator_is_formula_4():
    k, missing = g.normalized_indicator(0.4, 0.2, 0.75, 0.5)
    assert k == pytest.approx((0.4 + 0.2 + 0.75 + 0.5) / 4)
    assert missing == []
    k2, missing2 = g.normalized_indicator(0.4, 0.2, None, 0.5)
    assert missing2 == ["K_d"] and k2 == pytest.approx((0.4 + 0.2 + 0.5) / 3)


# ── валідація метаданих ─────────────────────────────────────────────────────
def test_normalise_gur_meta_canonical():
    m = g.normalise_gur_meta({"direction": "m3", "sphere": "Воєнна", "target_scale": "груповий",
                              "target_value": 0.5, "reach": "загальнодержавний",
                              "target_audience": "військовослужбовці; родини",
                              "n_negative": 3, "n_total": 10, "unknown": 1})
    assert m["sphere"] == "military" and m["target_scale"] == "group"
    assert m["reach"] == "national" and m["target_audience"] == ["військовослужбовці", "родини"]
    assert "unknown" not in m
    assert g.normalise_gur_meta(None) == {}


@pytest.mark.parametrize("bad", [
    {"target_scale": "single", "target_value": 0.9},     # значення поза категорією
    {"n_negative": 5, "n_total": 3},
    {"reach": "galactic"},
    {"target_value": "abc"},
    {"n_total": -1},
    "not a dict",
])
def test_normalise_gur_meta_rejects(bad):
    with pytest.raises(ValueError):
        g.normalise_gur_meta(bad)


# ── форма за табл. 5 ────────────────────────────────────────────────────────
def test_classify_attack_unambiguous():
    ind = {"K_i": 0.3, "K_t": 0.15, "K_d": 0.25, "K_o": 0.2}
    r = g.classify_form(ind, sum(ind.values()) / 4)
    assert r["form"] == "attack" and not r["ambiguous"]


def test_classify_overlap_is_flagged():
    # 0,65 входить і в акцію (0,37–0,69), і в операцію (0,62–0,88)
    r = g.classify_form({}, 0.65)
    assert set(r["by_K_n"]) == {"action", "operation"}
    assert r["ambiguous"]


def test_classify_gap_between_attack_and_action():
    r = g.classify_form({}, 0.355)
    assert r["in_K_n_gap"] and r["by_K_n"] == []


# ── наскрізна оцінка ────────────────────────────────────────────────────────
def test_single_attack_end_to_end():
    res = g.assess_threat([A("e1", 0, 2, reach="local", target_scale="single",
                             n_negative=1, n_total=4, target_audience=["ВПО"],
                             persons=["блогер Х"])],
                          start=_d(0), end=_d(6))
    s = res["spheres"][0]
    d = s["directions"][0]
    assert d["indicators"]["K_i"] == 0.25
    assert d["indicator_details"]["duration_days"] == 3
    assert d["indicator_sources"] == {"K_i": "expert", "K_t": "auto", "K_d": "expert",
                                      "K_o": "expert_midpoint"}
    assert d["form"]["form"] == "attack"
    assert s["level"]["key"] == "low"
    # доповнення автора — окремими полями
    assert d["target_audience"]["audiences"][0]["audience"] == "ВПО"
    assert d["instruments"]["persons"][0]["person"] == "блогер Х"
    assert d["facts"]["event_ids"] == ["e1"]
    assert "_sources" not in d and "_coord" not in d


def test_k_i_proxy_from_dims_grades_is_labelled():
    hi = g.assess_threat([A("e1", 0, 6, grade="SS", reach="local", target_scale="single")])
    lo = g.assess_threat([A("e1", 0, 6, grade="F", reach="local", target_scale="single")])
    d_hi, d_lo = hi["spheres"][0]["directions"][0], lo["spheres"][0]["directions"][0]
    assert d_hi["indicator_sources"]["K_i"] == "proxy"
    assert d_hi["indicators"]["K_i"] == 1.0 and d_lo["indicators"]["K_i"] == 0.0


def test_missing_reach_marks_partial():
    res = g.assess_threat([A("e1", 0, 6, target_scale="single", n_negative=1, n_total=2)])
    d = res["spheres"][0]["directions"][0]
    assert d["missing_indicators"] == ["K_d"] and d["K_n_partial"]
    assert res["spheres"][0]["Z_partial"]
    assert any("неповних" in w for w in res["warnings"])


def test_linked_directions_in_one_sphere_raise_to_operation():
    pair = [{"a": "chan_x", "b": "chan_y", "delta": 0.3}]
    evs = [A("e1", 0, 5, direction="m1", reach="local", target_scale="single",
             n_negative=1, n_total=4, pairs=pair),
           A("e2", 1, 6, direction="m4", reach="local", target_scale="single",
             n_negative=1, n_total=4, pairs=pair)]
    s = g.assess_threat(evs, start=_d(0), end=_d(6))["spheres"][0]
    assert all(d["form"]["form"] == "attack" for d in s["directions"])
    assert s["form"]["form"] == "operation" and s["form"]["linked_directions"]


def _heavy(eid, sphere, direction, sources, pairs=()):
    return A(eid, 0, 100, sphere=sphere, direction=direction, reach="international",
             target_scale="mass", n_negative=8, n_total=10, sources=sources, pairs=pairs)


def test_cross_sphere_links_make_campaign():
    pair = [{"a": "rt", "b": "tass", "delta": 0.2}]
    evs = [_heavy("e1", "military", "m1", {"rt": 3, "tass": 3}, pair),
           _heavy("e2", "domestic_policy", "dp1", {"rt": 2, "tass": 2}, pair)]
    res = g.assess_threat(evs, start=_d(94), end=_d(100))
    mil = next(s for s in res["spheres"] if s["sphere"] == "military")
    assert mil["linked_spheres"] == ["domestic_policy"]
    assert mil["form"]["form"] == "campaign"


def test_campaign_without_other_spheres_becomes_operation():
    res = g.assess_threat([_heavy("e1", "military", "m1", {"rt": 3, "tass": 3})],
                          start=_d(94), end=_d(100))
    form = res["spheres"][0]["form"]
    assert form["form"] == "operation" and "кампанія потребує" in form["basis"]


def test_critical_direction_flag_does_not_change_z():
    evs = [_heavy("e1", "military", "m1", {"rt": 3}),
           A("e2", 94, 100, direction="m6", reach="local", target_scale="single",
             n_negative=0, n_total=10, sources={"other": 1})]
    s = g.assess_threat(evs, start=_d(94), end=_d(100))["spheres"][0]
    kns = [d["K_n"] for d in s["directions"]]
    assert s["Z"] == pytest.approx(sum(kns) / 2, abs=1e-4)         # формула 5
    assert s["critical_direction"]["flag"] and s["critical_direction"]["directions"] == ["m1"]


def test_history_before_period_extends_duration():
    evs = [A("old", 0, 1, reach="local", target_scale="single", n_negative=1, n_total=2),
           A("new", 60, 62, reach="local", target_scale="single", n_negative=1, n_total=2)]
    res = g.assess_threat(evs, start=_d(56), end=_d(62))
    d = res["spheres"][0]["directions"][0]
    assert d["facts"]["event_ids"] == ["new"]
    assert d["indicator_details"]["first_seen"] == _d(0)
    assert d["indicator_details"]["duration_days"] == 63


def _weekly(neg_by_week):
    return [A(f"w{i}", 7 * i + 1, 7 * i + 2, reach="regional", target_scale="group",
              n_negative=k, n_total=10) for i, k in enumerate(neg_by_week)]


@pytest.mark.parametrize("negs,key", [([1, 5, 9], "increase"), ([9, 5, 1], "decrease"),
                                      ([5, 5, 5], "stable")])
def test_trend_forecast(negs, key):
    res = g.assess_threat(_weekly(negs), start=_d(0), end=_d(20))
    t = res["spheres"][0]["trend"]
    assert t["key"] == key and t["label"] == g.TREND_LABELS[key]
    assert len(res["spheres"][0]["series"]) == 3


def test_trend_insufficient_with_one_window():
    res = g.assess_threat(_weekly([5]), start=_d(0), end=_d(6))
    assert res["spheres"][0]["trend"]["key"] == "insufficient"


def test_short_period_and_unassigned_warnings():
    a = A("e1", 0, 1, reach="local", target_scale="single")
    a["gur"].pop("direction")
    res = g.assess_threat([a], start=_d(0), end=_d(2))
    assert res["spheres"][0]["directions"][0]["direction"] == g.UNASSIGNED_DIRECTION
    assert any("коротший за тиждень" in w for w in res["warnings"])
    assert any("без напряму" in w for w in res["warnings"])


def test_empty_and_bad_period():
    assert g.assess_threat([])["spheres"] == []
    with pytest.raises(ValueError):
        g.assess_threat([A("e1", 0)], start=_d(5), end=_d(1))
