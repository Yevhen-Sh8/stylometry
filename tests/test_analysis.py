#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_analysis.py
======================
Детермінований regression-набір для наукового ядра DIMS (core/analysis.py)
та допоміжних модулів. Закріплює інваріанти методики, які легко зламати при
правках: суми вагів = 1, нормування індикаторів у [0,1], порядок грейдів,
правило «табу→SS», облік заперечення, функціонально-словниковий режим,
S_time у I_coord, довірчий інтервал R_DIMS, SimHash near-duplicate.

Запуск (без pytest):  .venv/bin/python tests/test_analysis.py
Запуск (з pytest):    .venv/bin/python -m pytest tests/test_analysis.py -q
"""
from __future__ import annotations

import os
import sys
from itertools import combinations
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.analysis as a
from core.monitoring_log import simhash, hamming


# ── helpers ──────────────────────────────────────────────────────────────────
def _assess(corpus, meta=None, feature_type="word", with_z=False, manifestation=None):
    """Мінімальний конвеєр → build_dims_assessment (як у продукті)."""
    tok = a.tokenise_corpus(corpus, feature_type=feature_type)
    mfw = a.find_mfw(tok, n=80, min_doc_freq=1)
    tf = a.build_tf_matrix(tok, mfw)
    z = a.zscore_matrix(tf)
    dist = a.burrows_delta(z)
    pairs = [(x, y, float(dist.loc[x, y])) for x, y in combinations(dist.index, 2)]
    flagged = [p for p in pairs if p[2] < 0.8]
    return a.build_dims_assessment(
        tokenised=tok, dist_df=dist, threshold=0.8,
        flagged_pairs=len(flagged), n_pairs=len(pairs),
        source_meta=meta, corpus=corpus, manifestation=manifestation,
        z=(z if with_z else None),
    )


# ── ваги ─────────────────────────────────────────────────────────────────────
def test_default_weights_sum_to_one():
    assert abs(sum(a.DEFAULT_WEIGHTS.values()) - 1.0) < 1e-9
    assert all(w >= 0 for w in a.DEFAULT_WEIGHTS.values())


def test_source_component_weights_sum_to_one():
    assert abs(sum(a.SOURCE_COMPONENT_WEIGHTS.values()) - 1.0) < 1e-9
    assert all(w >= 0 for w in a.SOURCE_COMPONENT_WEIGHTS.values())


# ── шкала грейдів ────────────────────────────────────────────────────────────
def test_grade_thresholds_order_and_values():
    grades = [g for g, _, _ in a.GRADE_THRESHOLDS]
    uppers = [u for _, u, _ in a.GRADE_THRESHOLDS]
    assert grades == ["F", "B", "S", "SS", "SSS"]
    assert uppers[:4] == [0.20, 0.40, 0.60, 0.80]
    assert uppers[4] == float("inf")


def test_classify_grade_boundaries():
    assert a.classify_interest_grade(0.10)["grade"] == "F"
    assert a.classify_interest_grade(0.30)["grade"] == "B"
    assert a.classify_interest_grade(0.50)["grade"] == "S"
    assert a.classify_interest_grade(0.70)["grade"] == "SS"
    assert a.classify_interest_grade(0.90)["grade"] == "SSS"


def test_taboo_forces_at_least_ss():
    # табу піднімає низький грейд до SS…
    assert a.classify_interest_grade(0.05, manifestation="taboo")["grade"] == "SS"
    # …але не знижує вищий
    assert a.classify_interest_grade(0.95, manifestation="taboo")["grade"] == "SSS"
    # звичайний вид прояву на бали/грейд не впливає
    assert a.classify_interest_grade(0.05, manifestation="fake")["grade"] == "F"


# ── змістовий індикатор: нормування + заперечення ────────────────────────────
def test_marker_score_bounds_and_empty():
    assert a._marker_score([], a.CONTENT_MARKERS, a._CONTENT_DENSITY_REF) == 0.0
    for toks in ([], ["x"] * 50, ["фейк"] + ["x"] * 49, ["фейк", "пропаганда", "брехня"]):
        s = a._marker_score(toks, a.CONTENT_MARKERS, a._CONTENT_DENSITY_REF)
        assert 0.0 <= s <= 1.0


def test_negation_lowers_marker_score():
    plain = a._marker_score(["це", "фейк", "пропаганда"], a.CONTENT_MARKERS, a._CONTENT_DENSITY_REF)
    negated = a._marker_score(["це", "не", "фейк", "і", "не", "пропаганда"], a.CONTENT_MARKERS, a._CONTENT_DENSITY_REF)
    assert negated < plain


# ── токенізація: сміття та функціональні слова ───────────────────────────────
def test_clean_and_tokenise_strips_urls_and_boilerplate():
    toks = a.clean_and_tokenise("Посол заявив. Читайте також https://t.me/x Реклама editor@site.com")
    assert "посол" in toks and "заявив" in toks
    for junk in ("httpstmex", "реклама", "читайте", "editorsitecom"):
        assert junk not in toks


def test_function_word_tokens_keep_only_function_words_incl_single_char():
    ft = a._function_word_tokens("Посол Росії заявив, що ракета не влучила в ціль")
    assert all(t in a.FUNCTION_WORDS for t in ft)
    for fw in ("що", "не", "в"):           # включно з однолітерними службовими
        assert fw in ft
    for content in ("посол", "росії", "ракета", "ціль"):
        assert content not in ft


def test_tokenise_corpus_function_mode():
    corpus = {"a": "Він заявив, що це сталося, бо вони не змогли", "b": "На думку експертів, у країні триває криза"}
    tok = a.tokenise_corpus(corpus, feature_type="function")
    assert all(all(t in a.FUNCTION_WORDS for t in toks) for toks in tok.values())


# ── координація: 4 фактори + S_time ──────────────────────────────────────────
def test_coordination_score_bounds_and_time_renorm():
    import pandas as pd
    labels = ["a", "b"]
    dist = pd.DataFrame([[0, 0.1], [0.1, 0]], index=labels, columns=labels)
    tok = {"a": ["війна", "ракета"], "b": ["війна", "ракета"]}
    meta_no = {"a": {"domain": "pravda.ru"}, "b": {"domain": "ria.ru"}}
    s = a._coordination_score(dist, 0.8, tokenised=tok, source_meta=meta_no)
    assert 0.0 <= s <= 1.0
    # S_time відсутній → виключається; з датами — присутній, межі тримаються
    meta_t = {"a": {"domain": "pravda.ru", "timestamp": "2026-05-01T10:00:00"},
              "b": {"domain": "ria.ru", "timestamp": "2026-05-01T11:00:00"}}
    assert a._time_sync_score(meta_no) is None
    assert 0.0 <= a._time_sync_score(meta_t) <= 1.0


def test_dynamics_score_bounds_and_saturation():
    assert a._dynamics_score(0) == 0.0
    assert a._dynamics_score(100) == 1.0
    assert 0.0 <= a._dynamics_score(4) <= 1.0


# ── інтегральна збірка + довірчий інтервал ───────────────────────────────────
def test_build_assessment_indicators_bounded_and_grade_valid():
    corpus = {"a": "війна ракета атака нато оборона " * 25, "b": "мирні переговори дипломатія саміт " * 25}
    r = _assess(corpus, meta={"a": {"domain": "pravda.ru"}, "b": {"domain": "bbc.com"}})
    assert 0.0 <= r["r_dims"] <= 1.0
    assert all(0.0 <= v <= 1.0 for v in r["indicators"].values())
    assert r["grade"]["grade"] in ("F", "B", "S", "SS", "SSS")


def test_confidence_interval_present_and_grade_probs_sum_to_one():
    corpus = {"a": "війна ракета атака нато оборона загроза " * 25,
              "b": "війна ракета атака нато оборона загроза " * 25,
              "d": "переговори дипломатія компроміс саміт " * 25}
    r = _assess(corpus, meta={k: {"domain": "x"} for k in "abd"}, with_z=True)
    ci = r["confidence"]
    assert ci and 0.0 <= ci["lo"] <= ci["hi"] <= 1.0
    assert abs(sum(ci["grade_prob"].values()) - 1.0) < 1e-6


# ── SimHash near-duplicate ───────────────────────────────────────────────────
def test_simhash_separates_copy_from_distinct():
    base = "Росія завдала ракетного удару по інфраструктурі міста вночі " * 8
    copy_footer = base + " Підписатись на канал. Читайте також."
    distinct = "Мирні переговори у Стамбулі завершилися без результату сторони " * 8
    assert hamming(simhash(base), simhash(copy_footer)) <= 10   # технічна копія
    assert hamming(simhash(base), simhash(distinct)) > 10       # різний зміст


# ── standalone runner (без pytest) ───────────────────────────────────────────
def _run_standalone():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed, failed = 0, 0
    for fn in fns:
        try:
            fn()
            passed += 1
            print(f"  ✓ {fn.__name__}")
        except Exception as exc:
            failed += 1
            print(f"  ✗ {fn.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{passed} passed, {failed} failed з {len(fns)} тестів")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if _run_standalone() else 1)
