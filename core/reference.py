# -*- coding: utf-8 -*-
"""Еталонна статистика для Burrows' Delta.

Класичний Delta нормує частоти слів середніми й відхиленнями, порахованими по
самому порівнюваному набору текстів. Тоді значення залежать від того, що ще
лежить у наборі, а для двох джерел z-оцінки завжди ±1 і Delta ≈ 2,0 незалежно
від схожості текстів. Тут словник і статистики беруться з великого еталонного
корпусу мови (як `z.scores.both.sets = FALSE` у пакеті stylo): кожен текст
отримує ті самі z-оцінки, хоч з чим би його порівнювали.

Еталон — JSON-файл у `Data/reference/<мова>.json`, який будує
`tools/build_reference.py`. Окрім словника й статистик, файл містить розподіли
відстаней для випадкових пар текстів різної довжини: з них рахується, наскільки
пара ближча за типову пару незалежних текстів цієї мови.
"""

from __future__ import annotations

import bisect
import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

REFERENCE_DIR = Path(__file__).resolve().parent.parent / "Data" / "reference"
REFERENCE_FORMAT = 1

# Мінімальна частка слів тексту, що мають бути зі словника мови, щоб вважати
# текст написаним цією мовою (для порівняння: службові слова зазвичай дають
# 30–50 % слів тексту).
MIN_COVERAGE = 0.15
LANG_PROBE_WORDS = 100


@dataclass
class Reference:
    language: str
    vocab_id: str
    tokenizer_version: str
    words: list[str]
    mean: list[float]
    sd: list[float]
    sd_ddof: int
    chunk_tokens: int
    n_chunks: int
    n_docs: int
    source: str = ""
    licence: str = ""
    built_at: str = ""
    # Старі еталони відкалібровані за першими 100 ознаками.
    calibration_features: int = 100
    # {"burrows"|"cosine": {"<tokens>": [відсортовані відстані випадкових пар]}}
    random_pairs: dict = field(default_factory=dict)
    format: int = REFERENCE_FORMAT

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: dict) -> "Reference":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    # ── застосування ────────────────────────────────────────────────────────
    def features(self, n: int) -> list[str]:
        return self.words[: max(1, min(n, len(self.words)))]

    def zscores(self, tf: pd.DataFrame) -> pd.DataFrame:
        """z-оцінки відносних частот за еталонними середніми й відхиленнями."""
        idx = {w: i for i, w in enumerate(self.words)}
        cols = list(tf.columns)
        mean = np.array([self.mean[idx[w]] for w in cols])
        sd = np.array([self.sd[idx[w]] for w in cols])
        sd = np.where(sd > 0, sd, 1.0)
        return (tf - mean) / sd

    def coverage(self, tokens: list[str]) -> float:
        if not tokens:
            return 0.0
        probe = set(self.words[:LANG_PROBE_WORDS])
        return sum(t in probe for t in tokens) / len(tokens)

    def percentile(self, distance: float, metric: str, tokens: int,
                   n_features: int | None = None) -> float | None:
        """Частка випадкових пар (0–100), що стоять БЛИЖЧЕ за цю пару.

        Мале значення = пара ближча, ніж майже всі незалежні тексти мови.
        Розподіл береться для найближчої довжини текстів, порахованої в еталоні.
        """
        dist = self._dist_for(metric, tokens, n_features)
        if not dist:
            return None
        return round(100.0 * bisect.bisect_left(dist, distance) / len(dist), 1)

    def _dist_for(self, metric: str, tokens: int, n_features: int | None = None) -> list[float]:
        if n_features is not None and n_features != self.calibration_features:
            return []
        by_len = self.random_pairs.get(metric) or {}
        if not by_len:
            return []
        lengths = sorted(int(k) for k in by_len)
        best = min(lengths, key=lambda L: abs(np.log(L) - np.log(max(tokens, 1))))
        return by_len[str(best)]

    def threshold_for(self, tokens: int, metric: str, pct: float,
                      n_features: int | None = None) -> float | None:
        """Відстань, ближче за яку стоять лише pct % випадкових пар текстів такої довжини."""
        dist = self._dist_for(metric, tokens, n_features)
        if not dist:
            return None
        return float(np.percentile(dist, pct))


def load_references(directory: Path = REFERENCE_DIR) -> dict[str, Reference]:
    refs: dict[str, Reference] = {}
    if not directory.exists():
        return refs
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("format") != REFERENCE_FORMAT:
            continue
        ref = Reference.from_dict(data)
        refs[ref.language] = ref
    return refs


def choose_reference(
    tokenised: dict[str, list[str]],
    refs: dict[str, Reference],
    tokenizer_version: str,
) -> tuple[Reference | None, dict]:
    """Обирає еталон мови, до якої належать УСІ тексти; інакше пояснює чому ні."""
    usable = {k: r for k, r in refs.items() if r.tokenizer_version == tokenizer_version}
    if not usable:
        return None, {"used": False, "reason": "no_reference"}
    per_doc: dict[str, str | None] = {}
    for label, tokens in tokenised.items():
        scores = {lang: r.coverage(tokens) for lang, r in usable.items()}
        lang, cov = max(scores.items(), key=lambda kv: kv[1])
        per_doc[label] = lang if cov >= MIN_COVERAGE else None
    langs = set(per_doc.values())
    if None in langs:
        return None, {"used": False, "reason": "unknown_language", "languages": per_doc}
    if len(langs) > 1:
        return None, {"used": False, "reason": "mixed_languages", "languages": per_doc}
    ref = usable[langs.pop()]
    return ref, {
        "used": True,
        "language": ref.language,
        "vocab_id": ref.vocab_id,
        "n_chunks": ref.n_chunks,
        "chunk_tokens": ref.chunk_tokens,
        "source": ref.source,
        "licence": ref.licence,
    }


# ── побудова еталона ────────────────────────────────────────────────────────

def chunk_documents(docs: list[list[str]], chunk_tokens: int) -> list[tuple[int, list[str]]]:
    """Ріже кожен документ на шматки по chunk_tokens слів; хвіст < половини відкидається."""
    out: list[tuple[int, list[str]]] = []
    for d, tokens in enumerate(docs):
        for i in range(0, len(tokens), chunk_tokens):
            piece = tokens[i:i + chunk_tokens]
            if len(piece) >= chunk_tokens // 2:
                out.append((d, piece))
    return out


def _rel_freq(chunks: list[list[str]], words: list[str]) -> np.ndarray:
    idx = {w: i for i, w in enumerate(words)}
    m = np.zeros((len(chunks), len(words)))
    for r, tokens in enumerate(chunks):
        for t in tokens:
            j = idx.get(t)
            if j is not None:
                m[r, j] += 1
        m[r] /= max(len(tokens), 1)
    return m


def _pair_distances(za: np.ndarray, zb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    burrows = np.abs(za - zb).mean(axis=1)
    na = np.linalg.norm(za, axis=1)
    nb = np.linalg.norm(zb, axis=1)
    cos = (za * zb).sum(axis=1) / np.where(na * nb > 0, na * nb, 1.0)
    return burrows, 1.0 - cos


def build_reference(
    docs: list[list[str]],
    *,
    language: str,
    vocab_id: str,
    tokenizer_version: str,
    n_words: int = 500,
    chunk_tokens: int = 1000,
    min_chunk_share: float = 0.05,
    pair_lengths: tuple[int, ...] = (125, 250, 500, 1000, 2000),
    max_pairs: int = 2000,
    calib_share: float = 0.2,
    seed: int = 13,
    source: str = "",
    licence: str = "",
    built_at: str = "",
) -> Reference:
    """Словник, середні й відхилення (ddof=1) за шматками навчальних документів
    і розподіли відстаней для випадкових пар документів, відкладених на калібрування."""
    rng = random.Random(seed)
    order = list(range(len(docs)))
    rng.shuffle(order)
    n_calib = int(len(order) * calib_share)
    calib_ids, train_ids = set(order[:n_calib]), order[n_calib:]
    train_docs = [docs[i] for i in train_ids]

    chunks = [c for _, c in chunk_documents(train_docs, chunk_tokens)]
    if len(chunks) < 20:
        raise ValueError(f"Замало тексту для еталона: {len(chunks)} шматків по {chunk_tokens} слів.")

    total: dict[str, int] = {}
    in_chunks: dict[str, int] = {}
    for c in chunks:
        for t in c:
            total[t] = total.get(t, 0) + 1
        for t in set(c):
            in_chunks[t] = in_chunks.get(t, 0) + 1
    min_chunks = max(2, int(np.ceil(min_chunk_share * len(chunks))))
    words = [w for w, _ in sorted(total.items(), key=lambda kv: (-kv[1], kv[0]))
             if in_chunks[w] >= min_chunks][:n_words]

    freq = _rel_freq(chunks, words)
    mean = freq.mean(axis=0)
    sd = freq.std(axis=0, ddof=1)

    ref = Reference(
        language=language, vocab_id=vocab_id, tokenizer_version=tokenizer_version,
        words=words, mean=[float(x) for x in mean], sd=[float(x) for x in sd], sd_ddof=1,
        chunk_tokens=chunk_tokens, n_chunks=len(chunks), n_docs=len(train_docs),
        source=source, licence=licence, built_at=built_at,
        calibration_features=min(100, len(words)),
    )

    # Розподіли відстаней для пар шматків з РІЗНИХ відкладених документів.
    calib_docs = [docs[i] for i in sorted(calib_ids)]
    sd_safe = np.where(sd > 0, sd, 1.0)
    random_pairs: dict[str, dict[str, list[float]]] = {"burrows": {}, "cosine": {}}
    for L in pair_lengths:
        pieces = chunk_documents(calib_docs, L)
        pieces = [(d, p) for d, p in pieces if len(p) == L]
        if len(pieces) < 10 or len({d for d, _ in pieces}) < 2:
            continue
        pairs = []
        for _ in range(max_pairs * 3):
            a, b = rng.sample(range(len(pieces)), 2)
            if pieces[a][0] != pieces[b][0]:
                pairs.append((a, b))
            if len(pairs) >= max_pairs:
                break
        if len(pairs) < 50:
            continue
        z = (_rel_freq([p for _, p in pieces], words) - mean) / sd_safe
        za = z[[a for a, _ in pairs]]
        zb = z[[b for _, b in pairs]]
        for n_feat in (ref.calibration_features,):
            bur, cos = _pair_distances(za[:, :n_feat], zb[:, :n_feat])
            random_pairs["burrows"][str(L)] = sorted(round(float(x), 4) for x in bur)
            random_pairs["cosine"][str(L)] = sorted(round(float(x), 4) for x in cos)
    ref.random_pairs = random_pairs
    return ref
