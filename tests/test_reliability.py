# -*- coding: utf-8 -*-
"""Обсяг тексту, довірчий інтервал за текстом і вердикт пари.

Перенесено з рушія комерційної гілки; перевірки сервісного API замінено
перевірками run_pipeline та оцінки подій ІАС (core/ias_service.py).
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from core import analysis as a  # noqa: E402
from core import reference as r  # noqa: E402
from core.ias_service import assess_event  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"


def _text(k: str) -> str:
    return (FIX / "uk" / f"{k}.txt").read_text(encoding="utf-8")


def _run(corpus: dict[str, str], **kw) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        return a.run_pipeline(corpus, Path(tmp), **kw)


@pytest.mark.parametrize("tokens,level", [
    (0, "too_short"), (499, "too_short"), (500, "preliminary"),
    (2499, "preliminary"), (2500, "reliable"), (10000, "reliable"),
])
def test_length_level(tokens, level):
    assert a.length_level(tokens) == level


@pytest.mark.parametrize("d,hi,n,verdict", [
    (0.9, 0.95, 3000, "none"),        # не ближче за поріг
    (0.3, 0.6, 3000, "strong"),       # і з похибкою нижче порогу, тексту досить
    (0.3, 0.9, 3000, "possible"),     # похибка заходить за поріг
    (0.3, 0.6, 200, "possible"),      # замало тексту
    (0.3, None, 3000, "possible"),    # інтервалу немає
])
def test_pair_verdict(d, hi, n, verdict):
    assert a.pair_verdict(d, 0.8, hi, n) == verdict


def _ci(tokenised):
    ref = r.load_references()["uk"]
    feats = ref.features(100)
    ix = {w: i for i, w in enumerate(ref.words)}
    mean = np.array([ref.mean[ix[w]] for w in feats])
    sd = np.array([ref.sd[ix[w]] for w in feats])
    ci = a.bootstrap_text_ci(tokenised, feats, mean, sd, n_iterations=100)
    z = ref.zscores(a.build_tf_matrix(tokenised, feats))
    return ci, a.burrows_delta(z)


def test_text_ci_is_centred_on_observed_distance():
    tok = {k: a.clean_and_tokenise(_text(k)) for k in "ade"}
    ci, d = _ci(tok)
    for (x, y), c in ci.items():
        assert c["mean"] == pytest.approx(d.loc[x, y])
        assert c["lo"] <= d.loc[x, y] <= c["hi"] and c["lo"] >= 0


def test_text_ci_narrows_with_more_text():
    long_a = " ".join(_text(k) for k in "abc") * 6
    long_d = " ".join(_text(k) for k in "de") * 9
    tok_long = {"x": a.clean_and_tokenise(long_a), "y": a.clean_and_tokenise(long_d)}
    tok_short = {"x": tok_long["x"][:150], "y": tok_long["y"][:150]}
    width = lambda ci: next(iter(ci[0].values()))["hi"] - next(iter(ci[0].values()))["lo"]  # noqa: E731
    assert width(_ci(tok_long)) < width(_ci(tok_short))


def test_pipeline_reports_length_and_verdicts():
    out = _run({k: _text(k) for k in "abcde"}, bootstrap_iterations=100)
    assert set(out["doc_length_level"].values()) == {"too_short"}
    assert out["threshold_source"] == "reference" and out["reference"]["language"] == "uk"
    key = "a||b" if "a||b" in out["pair_verdict"] else "b||a"
    assert out["dist_df"].loc["a", "b"] < out["pair_threshold"][key]
    assert out["pair_verdict"][key] == "possible"          # близько, але текстів замало
    lo, hi = out["pair_percentile_range"][key]
    assert lo <= out["pair_percentile"][key] <= hi
    flagged = {f"{x}||{y}" for x, y, _, _ in out["flagged"]}
    assert all(v == "none" for k, v in out["pair_verdict"].items() if k not in flagged)


def test_long_near_identical_sources_get_strong_verdict():
    base = " ".join(_text(k) for k in "abc")
    out = _run({"x": base * 5, "y": base * 5 + " " + _text("a"),
                "z": " ".join(_text(k) for k in "de") * 8}, bootstrap_iterations=100)
    key = "x||y" if "x||y" in out["pair_verdict"] else "y||x"
    assert min(out["doc_tokens"]["x"], out["doc_tokens"]["y"]) >= 500
    assert out["pair_verdict"][key] == "strong"


def test_ias_event_uses_reference_threshold_and_reports_pair_verdicts():
    mats = [{"id": k, "source": f"chan_{k}", "text": _text(k)} for k in "abcde"]
    res = assess_event(mats)
    assert res["params"]["threshold_source"] == "reference"
    assert res["params"]["reference"]["language"] == "uk"
    pairs = res["coordination"]["flagged_pairs"]
    assert pairs, "фікстури a/b навмисно близькі"
    for p in pairs:
        assert p["delta"] < p["threshold"]
        assert p["verdict"] in {"strong", "possible"}
        assert p["ci"]["lo"] <= p["delta"] <= p["ci"]["hi"]
        assert 0 <= p["percentile"] <= 100
    assert any("2500" in w for w in res["warnings"])


def test_ias_event_manual_threshold_and_cosine():
    mats = [{"id": k, "source": f"chan_{k}", "text": _text(k)} for k in "abcde"]
    manual = assess_event(mats, threshold=0.8)
    assert manual["params"]["threshold_source"] == "manual"
    assert all(p["threshold"] == 0.8 for p in manual["coordination"]["flagged_pairs"])
    cos = assess_event(mats, metric="cosine")
    assert cos["params"]["metric"] == "cosine"
    assert cos["params"]["threshold"] < 1.0   # інший масштаб, ніж у Burrows
