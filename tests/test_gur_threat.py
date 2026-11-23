#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_gur_threat.py
========================
Макрорівень за прототипом ГУР-2016 (core/gur_threat.py): відтворення формул і
таблиць прототипу (з точністю до округлення прототипу), шар prototype vs
improved, правила реалізації та доповнення автора (інструменти, ЦА, факти,
оцінка тенденції). Кейси К1–К4, С1–С3, С13 — з рецензії krytyk.

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
      sources=None, pairs=(), clusters=(), dated=True, **gur):
    """Мінімальна збережена DIMS-оцінка події з метаданими ГУР."""
    last = first if last is None else last
    meta = {"direction": direction, "sphere": sphere, **gur}
    a = {
        "event_id": eid,
        "assessed_at": f"{_d(last)}T12:00:00+00:00",
        "r_dims": 0.5,
        "grade": {"grade": grade},
        "stats": {"n_materials": n, "n_unique_materials": n,
                  "sources": sources or {"src_a": 2, "src_b": 2}},
        "coordination": {"flagged_pairs": list(pairs), "copy_clusters": list(clusters)},
        "gur": g.normalise_gur_meta(meta),
    }
    if dated:
        a["period"] = {"first_published": f"{_d(first)}T08:00:00",
                       "last_published": f"{_d(last)}T20:00:00"}
    return a


def STRONG(a, b):
    return [{"a": a, "b": b, "delta": 0.3, "verdict": "strong"}]


def sphere(res, key="military"):
    return next(s for s in res["spheres"] if s["sphere"] == key)


# ── формули і таблиці прототипу ─────────────────────────────────────────────
@pytest.mark.parametrize("days,expected", [
    (7, 0.15), (14, 0.26), (31, 0.43), (92, 0.70), (273, 0.87), (365, 0.90), (730, 0.97),
])
def test_duration_reproduces_table_4_to_prototype_rounding(days, expected):
    assert g.duration_coefficient(days) == pytest.approx(expected, abs=0.01)


def test_duration_has_prototype_jump_at_one_year():
    assert g.duration_coefficient(366) - g.duration_coefficient(365) > 0.04
    assert g.duration_coefficient(0) == 0.0


@pytest.mark.parametrize("z,key", [
    (0.0, "low"), (0.25, "low"), (0.26, "elevated"), (0.5, "elevated"),
    (0.51, "high"), (0.75, "high"), (0.755, "critical"), (1.0, "critical"),
])
def test_threat_level_table_6_half_open(z, key):
    assert g.threat_level(z)["key"] == key


@pytest.mark.parametrize("k,key", [(0.2, "low"), (0.21, "medium"), (0.6, "elevated"),
                                   (0.61, "high"), (0.81, "critical")])
def test_intensity_levels_page_24(k, key):
    assert g.intensity_level(k)["key"] == key


def test_reach_and_object_scale():
    assert g.reach_value("міжнародний") == 1.0
    assert g.object_scale_value("group") == (0.505, "expert_midpoint")
    assert g.object_scale_value("масовий", 0.9) == (0.9, "expert")


def test_normalized_indicator_formula_4_and_range_when_missing():
    k, missing, rng = g.normalized_indicator(0.4, 0.2, 0.75, 0.5)
    assert k == pytest.approx(0.4625) and missing == [] and rng == (0.4625, 0.4625)
    k2, missing2, rng2 = g.normalized_indicator(0.4, 0.2, None, 0.5)
    assert k2 is None and missing2 == ["K_d"]
    assert rng2 == (pytest.approx((0.4 + 0.2 + 0.25 + 0.5) / 4), pytest.approx((0.4 + 0.2 + 1.0 + 0.5) / 4))


# ── валідація і злиття метаданих ────────────────────────────────────────────
def test_normalise_gur_meta_canonical():
    m = g.normalise_gur_meta({"direction": " M3 ", "sphere": "Воєнна", "target_scale": "груповий",
                              "target_value": 0.5, "reach": "загальнодержавний",
                              "target_audience": "військовослужбовці; родини",
                              "n_negative": 3, "n_total": 10, "unknown": 1})
    assert m["direction"] == "m3" and m["sphere"] == "military"
    assert m["target_scale"] == "group" and m["reach"] == "national"
    assert m["target_audience"] == ["військовослужбовці", "родини"] and "unknown" not in m


@pytest.mark.parametrize("bad", [
    {"target_scale": "single", "target_value": 0.9},
    {"n_negative": 5, "n_total": 3},
    {"n_negative": 2},                       # частка без знаменника не визначена (С8)
    {"reach": "galactic"},
    {"registry_reach": {"x": "galactic"}},
    {"target_value": "abc"},
    "not a dict",
])
def test_normalise_gur_meta_rejects(bad):
    with pytest.raises(ValueError):
        g.normalise_gur_meta(bad)


def test_merge_gur_expert_values_win_over_ias_db():
    prev = g.merge_gur({"direction": "m5"}, {"direction": "m2", "target_audience": ["резервісти"]},
                       expert=True)
    assert prev["expert_keys"] == ["direction", "target_audience"]
    after_scan = g.merge_gur(prev, {"direction": "m5", "reach": "regional"}, expert=False)
    assert after_scan["direction"] == "m2"                 # експерт має пріоритет
    assert after_scan["reach"] == "regional"               # нове з БД ІАС додано
    cleared = g.merge_gur(after_scan, {"target_audience": None}, expert=True)
    assert "target_audience" not in cleared and cleared["expert_keys"] == ["direction"]


# ── форма за табл. 5 (К1) ───────────────────────────────────────────────────
def test_classify_attack_unambiguous():
    ind = {"K_i": 0.3, "K_t": 0.15, "K_d": 0.25, "K_o": 0.2}
    r = g.classify_form(ind, sum(ind.values()) / 4)
    assert r["form"] == "attack" and r["rule"] == "prototype_K_n" and not r["ambiguous"]


@pytest.mark.parametrize("ind,expected", [
    ({"K_i": 0.3, "K_t": 0.15, "K_d": 1.0, "K_o": 0.71}, "action"),   # K_n 0,54 — лише акція
    ({"K_i": 0.9, "K_t": 0.15, "K_d": 0.25, "K_o": 0.2}, "action"),   # K_n 0,375 — лише акція
])
def test_prototype_k_n_range_is_not_overridden_by_profile(ind, expected):
    r = g.classify_form(ind, sum(ind.values()) / 4)
    assert r["prototype_forms"] == [expected] and r["form"] == expected


def test_overlap_resolved_by_profile_and_flagged():
    ind = {"K_i": 0.5, "K_t": 0.6, "K_d": 0.75, "K_o": 0.75}     # K_n 0,65: акція ∩ операція
    r = g.classify_form(ind, sum(ind.values()) / 4)
    assert set(r["prototype_forms"]) == {"action", "operation"}
    assert r["rule"] == "profile_distance_in_overlap" and r["form"] in {"action", "operation"}


def test_gap_between_attack_and_action():
    r = g.classify_form({"K_i": 0.3, "K_t": 0.1, "K_d": 0.5, "K_o": 0.52}, 0.355)
    assert r["in_K_n_gap"] and r["prototype_forms"] == [] and r["form"] in {"attack", "action"}


# ── наскрізна оцінка ────────────────────────────────────────────────────────
def test_single_attack_conformant_with_two_layers():
    res = g.assess_threat([A("e1", 0, 2, reach="local", target_scale="single",
                             n_negative=1, n_total=4, target_audience=["ВПО"],
                             persons=["блогер Х"])], start=_d(0), end=_d(6))
    s = sphere(res)
    d = s["directions"][0]
    assert d["indicators"]["K_i"] == 0.25 and d["indicator_details"]["episode_days"] == 3
    assert d["indicator_sources"] == {"K_i": "expert", "K_t": "auto", "K_d": "expert",
                                      "K_o": "expert_midpoint"}
    assert d["conformant"] and d["form"]["form"] == "attack"
    assert s["prototype"]["level"]["key"] == "low" and s["prototype"]["conformant"]
    assert s["prototype"]["direction_forms"] == {"m1": ["attack"]}
    assert d["target_audience"]["audiences"][0]["audience"] == "ВПО"
    assert d["instruments"]["persons"][0]["person"] == "блогер Х"
    assert "_coord" not in d


def test_proxy_k_i_is_labelled_non_conformant():
    res = g.assess_threat([A("e1", 0, 6, grade="SS", reach="local", target_scale="single")])
    s = sphere(res)
    d = s["directions"][0]
    assert d["indicator_sources"]["K_i"] == "proxy" and not d["conformant"]
    assert not s["prototype"]["conformant"]
    assert any("не відповідає прототипу" in w for w in res["warnings"])


def test_expert_subset_is_not_mixed_with_proxy():
    res = g.assess_threat([A("e1", 0, 3, reach="local", target_scale="single", n_negative=1, n_total=10),
                           A("e2", 1, 4, grade="SSS", reach="local", target_scale="single")])
    d = sphere(res)["directions"][0]
    assert d["indicators"]["K_i"] == 0.1 and d["indicator_sources"]["K_i"] == "expert_subset"


def test_missing_reach_gives_range_and_no_form_or_level():
    res = g.assess_threat([A("e1", 0, 6, target_scale="single", n_negative=1, n_total=2)])
    s = sphere(res)
    d = s["directions"][0]
    assert d["K_n"] is None and d["missing_indicators"] == ["K_d"] and d["form"] is None
    assert d["K_n_range"][0] < d["K_n_range"][1]
    assert s["prototype"]["Z"] is None and s["prototype"]["excluded_directions"] == ["m1"]


def test_k_o_takes_max_over_values_and_categories():
    res = g.assess_threat([A("e1", 0, 3, reach="local", target_scale="single", target_value=0.2),
                           A("e2", 1, 4, reach="local", target_scale="mass")])
    d = sphere(res)["directions"][0]
    assert d["indicators"]["K_o"] == 0.855 and d["indicator_sources"]["K_o"] == "expert_midpoint"


def test_registry_reach_is_labelled_registry():
    res = g.assess_threat([A("e1", 0, 3, target_scale="single", n_negative=1, n_total=2,
                             registry_reach={"chan": "regional"})])
    d = sphere(res)["directions"][0]
    assert d["indicators"]["K_d"] == 0.5 and d["indicator_sources"]["K_d"] == "registry"


def test_linked_directions_do_not_raise_form():                         # К2
    evs = [A("e1", 0, 5, direction="m1", reach="local", target_scale="single",
             n_negative=1, n_total=4, pairs=STRONG("chan_x", "chan_y")),
           A("e2", 1, 6, direction="m4", reach="local", target_scale="single",
             n_negative=1, n_total=4, pairs=STRONG("chan_x", "chan_y"))]
    form = sphere(g.assess_threat(evs, start=_d(0), end=_d(6)))["improved"]["form"]
    assert form["form"] == "attack" and form["linked_directions"]


def _heavy(eid, sphere_key, direction, pairs=()):
    return A(eid, 0, 100, sphere=sphere_key, direction=direction, reach="international",
             target_scale="mass", n_negative=8, n_total=10, pairs=pairs)


def test_cross_sphere_strong_links_and_campaign_profile_make_campaign():
    evs = [_heavy("e1", "military", "m1", STRONG("rt", "tass")),
           _heavy("e2", "domestic_policy", "dp1", STRONG("rt", "tass"))]
    res = g.assess_threat(evs, start=_d(94), end=_d(100))
    mil = sphere(res)
    assert mil["linked_spheres"] == ["domestic_policy"]
    assert mil["improved"]["form"]["form"] == "campaign"


def test_possible_pairs_do_not_link_spheres():                          # С13
    weak = [{"a": "rt", "b": "tass", "delta": 0.7, "verdict": "possible"}]
    evs = [_heavy("e1", "military", "m1", weak), _heavy("e2", "domestic_policy", "dp1", weak)]
    mil = sphere(g.assess_threat(evs, start=_d(94), end=_d(100)))
    assert mil["linked_spheres"] == [] and mil["improved"]["form"]["form"] == "operation"


def test_campaign_without_other_spheres_becomes_operation():
    form = sphere(g.assess_threat([_heavy("e1", "military", "m1")],
                                  start=_d(94), end=_d(100)))["improved"]["form"]
    assert form["form"] == "operation" and "немає зв'язку" in form["basis"]


def test_critical_direction_flag_does_not_change_z():
    evs = [_heavy("e1", "military", "m1"),
           A("e2", 94, 100, direction="m6", reach="local", target_scale="single",
             n_negative=0, n_total=10, sources={"other": 1})]
    s = sphere(g.assess_threat(evs, start=_d(94), end=_d(100)))
    kns = [d["K_n"] for d in s["directions"]]
    assert s["prototype"]["Z"] == pytest.approx(sum(kns) / 2, abs=1e-4)      # формула 5
    assert s["improved"]["critical_direction"]["flag"]
    assert s["improved"]["critical_direction"]["directions"] == ["m1"]


@pytest.mark.parametrize("gap,days", [(30, 3), (90, 63)])               # К4
def test_episode_gap_rule_for_duration(gap, days):
    evs = [A("old", 0, 1, reach="local", target_scale="single", n_negative=1, n_total=2),
           A("new", 60, 62, reach="local", target_scale="single", n_negative=1, n_total=2)]
    res = g.assess_threat(evs, start=_d(56), end=_d(62), episode_gap_days=gap)
    d = sphere(res)["directions"][0]
    assert d["facts"]["event_ids"] == ["new"]
    assert d["indicator_details"]["episode_days"] == days


def test_unassigned_direction_excluded_from_z():
    a = A("e1", 0, 6, reach="local", target_scale="single", n_negative=1, n_total=2)
    a["gur"].pop("direction")
    res = g.assess_threat([a], start=_d(0), end=_d(6))
    s = sphere(res)
    assert s["directions"][0]["direction"] == g.UNASSIGNED_DIRECTION
    assert s["prototype"]["Z"] is None and s["prototype"]["excluded_directions"] == ["unassigned"]
    assert any("без напряму" in w for w in res["warnings"])


def test_fallback_dates_warn():
    res = g.assess_threat([A("e1", 0, 0, dated=False, reach="local", target_scale="single",
                             n_negative=1, n_total=2)])
    d = sphere(res)["directions"][0]
    assert d["indicator_sources"]["K_t"] == "fallback" and not d["conformant"]
    assert any("дату оцінки" in w for w in res["warnings"])


# ── оцінка тенденції (С1–С3) ────────────────────────────────────────────────
def _weekly(neg_by_week, weeks=None):
    weeks = weeks or range(len(neg_by_week))
    return [A(f"w{i}", 7 * i + 1, 7 * i + 2, reach="regional", target_scale="group",
              n_negative=k, n_total=10) for i, k in zip(weeks, neg_by_week)]


@pytest.mark.parametrize("negs,key", [([1, 5, 9], "increase"), ([9, 5, 1], "decrease"),
                                      ([5, 5, 5], "stable")])
def test_trend(negs, key):
    res = g.assess_threat(_weekly(negs), start=_d(0), end=_d(20))
    t = sphere(res)["improved"]["trend"]
    assert t["key"] == key and t["label"] == g.TREND_LABELS[key]


def test_stable_intensity_has_no_age_drift():
    t = sphere(g.assess_threat(_weekly([5, 5, 5, 5]), start=_d(0), end=_d(27)))["improved"]["trend"]
    assert t["slope_per_window"] == pytest.approx(0.0, abs=1e-9)


def test_empty_window_is_zero_and_partial_window_excluded():
    res = g.assess_threat(_weekly([5, 5], weeks=[0, 2]), start=_d(0), end=_d(24))
    series = sphere(res)["improved"]["series"]
    assert [p["full"] for p in series] == [True, True, True, False]
    assert series[1]["no_events"] and series[1]["Z"] == 0.0
    assert sphere(res)["improved"]["trend"]["n_windows"] == 3


def test_long_event_counts_in_every_window_it_spans():
    res = g.assess_threat([A("long", 0, 13, reach="regional", target_scale="group",
                             n_negative=5, n_total=10)], start=_d(0), end=_d(13))
    series = sphere(res)["improved"]["series"]
    assert all(not p["no_events"] for p in series)


def test_trend_insufficient_with_one_window():
    res = g.assess_threat(_weekly([5]), start=_d(0), end=_d(6))
    assert sphere(res)["improved"]["trend"]["key"] == "insufficient"


def test_short_period_and_empty_and_bad_period():
    res = g.assess_threat(_weekly([5]), start=_d(0), end=_d(2))
    assert any("коротший за тиждень" in w for w in res["warnings"])
    assert g.assess_threat([])["spheres"] == []
    with pytest.raises(ValueError):
        g.assess_threat([], start=_d(5), end=_d(1))
