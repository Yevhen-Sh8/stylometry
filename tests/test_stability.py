# -*- coding: utf-8 -*-
"""Рішення щодо пари мають залежати лише від самої пари (еталон, власний поріг,
незалежна перевибірка), а не від решти набору чи порядку джерел.

Перенесено з рушія комерційної гілки; перевірку сервісного API замінено
перевіркою run_pipeline з бутстрепом.
"""
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from core import analysis as a, reference as r  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


def text(lang, label):
    return (FIX / lang / f"{label}.txt").read_text(encoding="utf-8")


def run(corpus, bootstrap_iterations=0, **params):
    with TemporaryDirectory() as tmp:
        return a.run_pipeline(corpus, Path(tmp), bootstrap_iterations=bootstrap_iterations,
                              **params)


@pytest.mark.parametrize("metric", ["burrows", "cosine"])
def test_pair_decision_does_not_change_with_long_extra_sources(metric):
    pair = {k: text("en", k) for k in "de"}
    extra = text("en", "a") * 15
    alone = run(pair, metric=metric)
    full = run({**pair, "long1": extra, "long2": extra, "long3": extra}, metric=metric)
    assert alone["reference"]["language"] == full["reference"]["language"] == "en"
    assert alone["dist_df"].loc["d", "e"] == pytest.approx(full["dist_df"].loc["d", "e"])
    assert alone["pair_threshold"]["d||e"] == full["pair_threshold"]["d||e"]
    assert alone["pair_verdict"]["d||e"] == full["pair_verdict"]["d||e"]
    if metric == "burrows":
        assert alone["pair_verdict"]["d||e"] == "possible"


def test_uncalibrated_features_require_manual_threshold_and_have_no_percentile():
    ref = r.load_references()["en"]
    assert ref.threshold_for(125, "burrows", 1, n_features=100) is not None
    assert ref.threshold_for(125, "burrows", 1, n_features=50) is None
    assert ref.percentile(0.5, "burrows", 125, n_features=50) is None
    pair = {k: text("en", k) for k in "de"}
    with pytest.raises(ValueError, match="калібрування"):
        run(pair, mfw_n=50)
    manual = run(pair, mfw_n=50, threshold=0.8)
    assert set(manual["pair_threshold"].values()) == {0.8}
    assert all(v is None for v in manual["pair_percentile"].values())


def ci(tokens):
    ref = r.load_references()["uk"]
    features = ref.features(100)
    indices = {w: i for i, w in enumerate(ref.words)}
    mean = np.array([ref.mean[indices[w]] for w in features])
    sd = np.array([ref.sd[indices[w]] for w in features])
    return a.bootstrap_text_ci(tokens, features, mean, sd, n_iterations=100)


def test_ci_is_stable_with_short_extra_source_and_reordering():
    tokens = {"x": a.clean_and_tokenise(text("uk", "a") * 10),
              "y": a.clean_and_tokenise(text("uk", "d") * 10)}
    alone = ci(tokens)
    extra = {**tokens, "short": a.clean_and_tokenise(text("uk", "a"))[:30]}
    full = ci(extra)
    reordered = ci({"y": tokens["y"], "short": extra["short"], "x": tokens["x"]})
    for key in ("lo", "hi", "mean", "std"):
        assert alone[("x", "y")][key] == pytest.approx(full[("x", "y")][key])
        assert alone[("x", "y")][key] == pytest.approx(reordered[("y", "x")][key])


def test_identical_sources_are_resampled_independently():
    tokens = a.clean_and_tokenise(text("uk", "a") + text("uk", "d"))
    assert ci({"x": tokens, "y": tokens})[("x", "y")]["std"] > 0


def test_pipeline_pair_decision_and_ci_stay_stable():
    pair = {k: text("en", k) for k in "de"}
    alone = run(pair, bootstrap_iterations=40)
    extra = {f"long{i}": text("en", "a") * 15 for i in range(3)}
    full = run({**extra, "e": pair["e"], "d": pair["d"]}, bootstrap_iterations=40)
    k1 = "d||e"
    k2 = k1 if k1 in full["pair_verdict"] else "e||d"
    assert alone["dist_df"].loc["d", "e"] == pytest.approx(full["dist_df"].loc["d", "e"])
    for field in ("pair_threshold", "pair_percentile", "pair_verdict", "pair_percentile_range"):
        assert alone[field][k1] == full[field][k2]
    for key in ("lo", "hi", "mean", "std"):
        assert alone["pair_ci"][k1][key] == pytest.approx(full["pair_ci"][k2][key])
