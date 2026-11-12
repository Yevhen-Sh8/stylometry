# -*- coding: utf-8 -*-
"""Еталонна статистика: результат пари не залежить від решти набору."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from core import analysis as a  # noqa: E402
from core import reference as r  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"


def _corpus(lang: str, labels: str = "abcde") -> dict[str, str]:
    return {k: (FIX / lang / f"{k}.txt").read_text(encoding="utf-8") for k in labels}


def _run(corpus: dict[str, str], **kw) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        return a.run_pipeline(corpus, Path(tmp), bootstrap_iterations=0, **kw)


def _d(res: dict, x: str, y: str) -> float:
    return float(res["dist_df"].loc[x, y])


def test_references_ship_for_all_site_languages():
    refs = r.load_references()
    assert {"uk", "ru", "en", "pl", "de"} <= set(refs)
    for ref in refs.values():
        assert ref.tokenizer_version == a.TOKENIZER_VERSION
        assert len(ref.words) == len(ref.mean) == len(ref.sd) >= 100
        for dist in ref.random_pairs["burrows"].values():
            assert dist == sorted(dist)


def test_two_sources_are_no_longer_stuck_at_two():
    """Головна вада: без еталона пара з двох джерел завжди дає ≈2,0."""
    pair = _corpus("uk", "ab")
    old = _run(pair, reference=None)
    assert _d(old, "a", "b") == pytest.approx(2.0, abs=0.05)
    new = _run(pair)
    assert new["reference"]["used"] and new["reference"]["language"] == "uk"
    assert _d(new, "a", "b") < 0.5


@pytest.mark.parametrize("lang", ["uk", "en"])
def test_pair_distance_does_not_depend_on_other_sources(lang):
    full = _run(_corpus(lang))
    for x, y in (("a", "b"), ("d", "e"), ("a", "d")):
        alone = _run(_corpus(lang, x + y))
        assert _d(alone, x, y) == pytest.approx(_d(full, x, y), abs=1e-9)


def test_same_author_pair_is_closer_than_random_pairs():
    res = _run(_corpus("uk"))
    pct = res["pair_percentile"]
    assert pct["a||b"] is not None and pct["a||b"] < 1.0
    assert pct.get("a||d", pct.get("d||a")) > 10.0
    flagged = {frozenset((x, y)) for x, y, _, _ in res["flagged"]}
    assert frozenset("ab") in flagged and frozenset("ad") not in flagged
    assert res["threshold_source"] == "reference"


def test_mixed_languages_fall_back_to_in_set_statistics():
    corpus = {"uk": _corpus("uk", "a")["a"], "en": _corpus("en", "a")["a"],
              "uk2": _corpus("uk", "b")["b"]}
    res = _run(corpus)
    assert res["reference"] == {"used": False, "reason": "mixed_languages",
                                "languages": {"uk": "uk", "en": "en", "uk2": "uk"}}
    assert res["threshold"] == a.DEFAULT_THRESHOLD and res["threshold_source"] == "default"


def test_manual_threshold_is_respected():
    res = _run(_corpus("uk"), threshold=0.5)
    assert res["threshold"] == 0.5 and res["threshold_source"] == "manual"


def test_cosine_delta_is_scale_free_and_symmetric():
    res = _run(_corpus("uk"), metric="cosine")
    d = res["dist_df"]
    assert (d.values >= -1e-12).all() and (d.values <= 2 + 1e-12).all()
    assert (d.values == d.values.T).all()
    assert _d(res, "a", "b") < _d(res, "a", "d")


def test_non_word_features_do_not_use_reference():
    res = _run(_corpus("uk"), feature_type="char")
    assert res["reference"] == {"used": False, "reason": "feature_type"}


def test_build_reference_shapes_and_language_choice():
    rng_words = ["alpha", "beta", "gamma", "delta", "eps", "zeta", "eta", "theta"]
    docs = [[rng_words[(i * 7 + j * (i % 5 + 1)) % len(rng_words)] for j in range(3000)]
            for i in range(30)]
    ref = r.build_reference(docs, language="xx", vocab_id="xx-test",
                            tokenizer_version=a.TOKENIZER_VERSION, n_words=6,
                            chunk_tokens=500, pair_lengths=(250, 500), max_pairs=200)
    assert len(ref.words) == 6 and ref.sd_ddof == 1
    assert set(ref.random_pairs["burrows"]) == {"250", "500"}
    chosen, info = r.choose_reference({"t": docs[0][:400]}, {"xx": ref}, a.TOKENIZER_VERSION)
    assert chosen is ref and info["language"] == "xx"
    none, info = r.choose_reference({"t": ["слово"] * 50}, {"xx": ref}, a.TOKENIZER_VERSION)
    assert none is None and info["reason"] == "unknown_language"
