#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/analysis.py
================
Importable Burrows' Delta stylometric pipeline.

All functions are pure (no side-effects) except the save_* helpers that
write files.  The top-level run_pipeline() orchestrates the full analysis.
"""

from __future__ import annotations

import base64
import string
from collections import Counter
from itertools import combinations
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# Cyrillic-safe font selection
_CANDIDATES = ["DejaVu Sans", "Liberation Sans", "FreeSans", "Arial Unicode MS"]
for _f in _CANDIDATES:
    if any(_f.lower() in f.name.lower() for f in fm.fontManager.ttflist):
        plt.rcParams["font.family"] = _f
        break

plt.rcParams.update({
    "figure.dpi":    150,
    "savefig.dpi":   150,
    "font.size":     10,
    "axes.titlesize": 13,
    "axes.labelsize": 11,
})

from scipy.cluster.hierarchy import linkage, dendrogram, fcluster
from scipy.spatial.distance import squareform, cdist
from sklearn.decomposition import PCA


SHORT_TEXT_WARNING_TOKENS = 500
DEFAULT_WEIGHTS = {
    "content": 0.28,
    "coord": 0.20,
    "dynamics": 0.08,
    "impact": 0.20,
    "source": 0.24,
}
GRADE_THRESHOLDS = [
    ("F", 0.20, "Малий інтерес"),
    ("B", 0.40, "Точковий інтерес"),
    ("S", 0.60, "Однозначний інтерес"),
    ("SS", 0.80, "Вагомий інтерес"),
    ("SSS", float("inf"), "Критичний інтерес"),
]
CONTENT_MARKERS = {
    "фейк", "фейки", "маніпуляція", "маніпуляції", "маніпулятивний",
    "дезінформація", "дезінформації", "пропаганда", "конспірологія",
    "сенсація", "сенсаційний", "інсайд", "змова", "паніка", "панічний",
    "вкид", "вкиди", "дискредитація", "брехня", "наратив", "наративи",
    "фейк", "фейки", "манипуляция", "манипуляции", "манипулятивный",
    "дезинформация", "пропаганда", "конспирология", "сенсация", "сенсационный",
    "инсайд", "заговор", "паника", "вброс", "вбросы", "дискредитация",
    "ложь", "лживый", "нарратив", "нарративы", "постановка", "провокация",
    "fake", "fakes", "manipulation", "manipulative", "disinformation", "propaganda",
    "conspiracy", "panic", "narrative", "narratives", "provocation", "provocations",
    "manipulation", "manipulationen", "propaganda", "desinformation", "falschmeldung",
    "falschmeldungen", "narrativ", "narrative", "panik", "provokation", "eskalation",
    "eskalationstreiber", "manipuliert", "manipulationstechniken",
    "désinformation", "propagande", "narratif", "narratifs", "panique",
    "provocation", "provocations", "manipulation", "conspiration",
}
IMPACT_MARKERS = {
    "війна", "війни", "безпека", "безпеки", "загроза", "загрози", "атака",
    "удар", "мобілізація", "оборона", "оборони", "зсу", "моу", "рнбо",
    "нато", "ракета", "ракети", "криза", "кризи", "україна", "санкції",
    "война", "безопасность", "угроза", "угрозы", "атака", "удар", "мобилизация",
    "оборона", "сво", "украина", "нато", "ракета", "ракеты", "кризис",
    "санкции", "фронт", "армия", "всу", "минобороны", "теракт",
    "war", "security", "threat", "threats", "attack", "missile", "missiles", "crisis",
    "nato", "ukraine", "sanctions", "front", "army", "mobilization", "defense",
    "krieg", "sicherheit", "bedrohung", "angriff", "angriffe", "ukraine", "nato",
    "sanktionen", "front", "armee", "rakete", "raketen", "eskalation", "waffenlieferungen",
    "neutralität", "waffen", "konflikt", "frieden", "sicherheitsgarantien",
    "guerre", "sécurité", "menace", "menaces", "attaque", "ukraine", "otan",
    "sanctions", "missile", "missiles", "crise", "armée", "front", "cessezlefeu",
    "cessez", "feu", "négociations",
}
MEDIUM_RISK_DOMAIN_TOKENS = {
    "sputnik", "ria", "tass", "zvezda", "tsargrad", "news-front", "pravda",
}
BASE_DIR = Path(__file__).resolve().parent.parent
HIGH_RISK_DOMAINS_FILE = BASE_DIR / "Data" / "high_risk_domains_case1.txt"


def _normalise_domain(value: str) -> str:
    value = (value or "").strip().lower()
    if not value:
        return ""
    if "://" in value:
        value = urlparse(value).netloc or value
    value = value.split("/")[0].split(":")[0].strip(".")
    if value.startswith("www."):
        value = value[4:]
    return value


def _load_high_risk_domains(path: Path) -> set[str]:
    if not path.exists():
        return set()
    domains: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        domains.add(_normalise_domain(line))
    return {d for d in domains if d}


HIGH_RISK_DOMAINS = _load_high_risk_domains(HIGH_RISK_DOMAINS_FILE)


# ─────────────────────────────────────────────────────────────────────────────
#  TOKENISATION
# ─────────────────────────────────────────────────────────────────────────────

_STRIP_TABLE = str.maketrans(
    "", "",
    string.punctuation + string.digits + "«»—–„""''…·•№₴€$%°±×÷"
)


def clean_and_tokenise(text: str) -> list[str]:
    """Lowercase, strip punctuation/digits, return alphabetic tokens (len≥2)."""
    text = text.lower().translate(_STRIP_TABLE)
    return [t for t in text.split() if t.isalpha() and len(t) > 1]


def tokenise_corpus(corpus: dict[str, str]) -> dict[str, list[str]]:
    """Apply tokenisation to every document in the corpus."""
    return {label: clean_and_tokenise(text) for label, text in corpus.items()}


# ─────────────────────────────────────────────────────────────────────────────
#  MFW
# ─────────────────────────────────────────────────────────────────────────────

def find_mfw(tokenised: dict[str, list[str]], n: int = 100) -> list[str]:
    """Return the top-*n* most frequent word types across the corpus."""
    global_counts: Counter[str] = Counter()
    for tokens in tokenised.values():
        global_counts.update(tokens)
    return [w for w, _ in global_counts.most_common(n)]


# ─────────────────────────────────────────────────────────────────────────────
#  TERM-FREQUENCY MATRIX
# ─────────────────────────────────────────────────────────────────────────────

def build_tf_matrix(
    tokenised: dict[str, list[str]],
    mfw: list[str],
) -> pd.DataFrame:
    """Relative term frequencies: count(word)/total_words per document."""
    records = {}
    for label, tokens in tokenised.items():
        total  = len(tokens)
        if total == 0:
            raise ValueError(f"Джерело '{label}' не містить придатних для аналізу токенів.")
        counts = Counter(tokens)
        records[label] = {w: counts.get(w, 0) / total for w in mfw}
    return pd.DataFrame.from_dict(records, orient="index")[mfw]


# ─────────────────────────────────────────────────────────────────────────────
#  Z-SCORE NORMALISATION
# ─────────────────────────────────────────────────────────────────────────────

def zscore_matrix(tf: pd.DataFrame) -> pd.DataFrame:
    """Column-wise Z-scores; population std (Burrows' convention); zero-std guard."""
    means = tf.mean(axis=0)
    stds  = tf.std(axis=0, ddof=0).replace(0.0, 1.0)
    return (tf - means) / stds


# ─────────────────────────────────────────────────────────────────────────────
#  BURROWS' DELTA
# ─────────────────────────────────────────────────────────────────────────────

def burrows_delta(z: pd.DataFrame) -> pd.DataFrame:
    """
    Burrows' Delta = mean |z_A - z_B| over all MFW features.
    Vectorised via scipy cdist (city-block / Manhattan distance / n_features).
    """
    labels     = z.index.tolist()
    n_features = z.shape[1]
    raw        = cdist(z.values.astype(float), z.values.astype(float), metric="cityblock")
    return pd.DataFrame(raw / n_features, index=labels, columns=labels)


# ─────────────────────────────────────────────────────────────────────────────
#  CLUSTERING HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _build_linkage(dist_df: pd.DataFrame):
    """Distance matrix → average linkage; robust for precomputed Burrows' Delta."""
    return linkage(squareform(dist_df.values, checks=False), method="average")


def _color_threshold(Z_link) -> float:
    return 0.7 * float(Z_link[:, 2].max())


# ─────────────────────────────────────────────────────────────────────────────
#  VISUALISATIONS
# ─────────────────────────────────────────────────────────────────────────────

def save_dendrogram(dist_df: pd.DataFrame, output_path: Path) -> None:
    """Average-linkage dendrogram → PNG file."""
    Z_link   = _build_linkage(dist_df)
    c_thresh = _color_threshold(Z_link)
    n        = len(dist_df)
    short_labels = [f"S{i + 1}" for i in range(n)]

    fig_width = min(max(7.2, n * 0.62), 11.0)
    fig, ax = plt.subplots(figsize=(fig_width, 4.8))
    dendrogram(
        Z_link,
        labels=short_labels,
        leaf_rotation=0,
        leaf_font_size=9,
        color_threshold=c_thresh,
        ax=ax,
    )
    ax.axhline(c_thresh, linestyle="--", color="grey", linewidth=0.8,
               label=f"Поріг кластеризації ({c_thresh:.3f})")
    ax.set_title("Дендрограма стилометричної близькості",
                 fontweight="bold")
    ax.set_ylabel("Відстань Δ_Burrows")
    ax.set_xlabel("Ідентифікатори джерел")
    ax.grid(axis="y", linestyle=":", linewidth=0.5, alpha=0.45)
    ax.tick_params(axis="x", labelsize=8)
    ax.legend(fontsize=8, loc="upper left", frameon=False)
    fig.tight_layout()
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def save_pca_plot(
    z: pd.DataFrame,
    dist_df: pd.DataFrame,
    output_path: Path,
) -> None:
    """2-D PCA scatter, cluster-coloured, → PNG file."""
    if len(z) < 2:
        return

    n_comp = min(2, len(z) - 1, z.shape[1])
    pca    = PCA(n_components=n_comp)
    coords = pca.fit_transform(z.values)
    var    = pca.explained_variance_ratio_ * 100

    if coords.shape[1] == 1:
        coords = np.column_stack([coords, np.zeros(len(coords))])
        var    = np.append(var, [0.0])

    Z_link      = _build_linkage(dist_df)
    cluster_ids = fcluster(Z_link, t=_color_threshold(Z_link), criterion="distance")
    n_clusters  = len(set(cluster_ids))
    cmap        = plt.get_cmap("tab10")
    palette     = {cid: cmap(i / max(n_clusters, 1))
                   for i, cid in enumerate(sorted(set(cluster_ids)))}

    fig, ax = plt.subplots(figsize=(10, 7))
    for cid in sorted(set(cluster_ids)):
        mask = cluster_ids == cid
        ax.scatter(
            coords[mask, 0], coords[mask, 1],
            color=palette[cid], s=90, edgecolors="k",
            linewidths=0.6, zorder=3, label=f"Кластер {cid}",
        )
    for idx, label in enumerate(z.index):
        ax.annotate(label, (coords[idx, 0], coords[idx, 1]),
                    textcoords="offset points", xytext=(6, 6),
                    fontsize=8, color=palette[cluster_ids[idx]])

    total_var = float(sum(var[:2]))
    ax.set_xlabel(f"PC1 ({var[0]:.1f}% дисперсії)")
    ax.set_ylabel(f"PC2 ({var[1]:.1f}% дисперсії)")
    ax.set_title(
        f"PCA-проєкція стилометричних ознак (пояснено {total_var:.1f}%)",
        fontweight="bold",
    )
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.legend(loc="best", fontsize=9, framealpha=0.8)

    if total_var < 60:
        ax.text(0.01, 0.01,
                f"⚠ {total_var:.0f}% — дендрограма надійніша",
                transform=ax.transAxes, fontsize=7, color="grey",
                verticalalignment="bottom")
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)


def save_distance_matrix(dist_df: pd.DataFrame, output_path: Path) -> None:
    dist_df.to_csv(output_path, float_format="%.6f")


# ─────────────────────────────────────────────────────────────────────────────
#  SEVERITY CLASSIFICATION
# ─────────────────────────────────────────────────────────────────────────────

def classify_severity(delta: float, threshold: float) -> dict:
    """Return severity label + CSS class for a Delta value."""
    crit = threshold * 0.30
    high = threshold * 0.60
    if delta < crit:
        return {"label": "Критичний", "en": "Critical", "css": "critical",
                "color": "#dc2626", "icon": "🔴"}
    if delta < high:
        return {"label": "Високий",   "en": "High",     "css": "high",
                "color": "#ea580c", "icon": "🟠"}
    return     {"label": "Помірний",  "en": "Moderate", "css": "moderate",
                "color": "#ca8a04", "icon": "🟡"}


def _marker_score(tokens: list[str], markers: set[str], scale: float) -> float:
    total = len(tokens)
    if total == 0:
        return 0.0
    hits = [t for t in tokens if t in markers]
    freq_score = min(1.0, (len(hits) / total) * scale)
    diversity_score = min(1.0, len(set(hits)) / max(1, min(len(markers), 8)))
    return float(0.7 * freq_score + 0.3 * diversity_score)


def _document_signal_scores(tokenised: dict[str, list[str]]) -> dict[str, dict[str, float]]:
    scores: dict[str, dict[str, float]] = {}
    for label, tokens in tokenised.items():
        scores[label] = {
            "content": _marker_score(tokens, CONTENT_MARKERS, scale=40.0),
            "impact": _marker_score(tokens, IMPACT_MARKERS, scale=28.0),
            "tokens": float(len(tokens)),
        }
    return scores


def _domain_risk_score(domain: str) -> float:
    domain = _normalise_domain(domain)
    if not domain:
        return 0.0
    if domain in HIGH_RISK_DOMAINS:
        return 0.9
    if any(domain.endswith(f".{risk}") for risk in HIGH_RISK_DOMAINS):
        return 0.85
    if any(domain.endswith(f".{tld}") for tld in ("ru", "su", "xn--p1ai")):
        return 0.55
    if any(token in domain for token in MEDIUM_RISK_DOMAIN_TOKENS):
        return 0.7
    return 0.0


def _source_score(source_meta: dict[str, dict] | None) -> tuple[float, dict[str, float]]:
    if not source_meta:
        return 0.0, {}
    per_source = {
        label: _domain_risk_score((meta or {}).get("domain", ""))
        for label, meta in source_meta.items()
    }
    if not per_source:
        return 0.0, {}
    return float(np.mean(list(per_source.values()))), per_source


def _coordination_score(dist_df: pd.DataFrame, threshold: float) -> float:
    labels = dist_df.index.tolist()
    deltas = [
        float(dist_df.loc[a, b])
        for a, b in combinations(labels, 2)
    ]
    if not deltas:
        return 0.0
    min_delta = min(deltas)
    closest_score = max(0.0, 1.0 - (min_delta / max(threshold, 1e-6)))
    flagged_ratio = sum(1 for d in deltas if d < threshold) / len(deltas)
    top_k = sorted(deltas)[: min(3, len(deltas))]
    compactness = max(0.0, 1.0 - (float(np.mean(top_k)) / max(threshold, 1e-6)))
    return float(np.clip(0.5 * closest_score + 0.3 * flagged_ratio + 0.2 * compactness, 0.0, 1.0))


def _dynamics_score(n_docs: int, flagged_pairs: int, n_pairs: int) -> float:
    if n_pairs == 0:
        return 0.0
    corpus_intensity = min(1.0, n_docs / 8.0)
    flagged_density = flagged_pairs / n_pairs
    return float(np.clip(0.45 * corpus_intensity + 0.55 * flagged_density, 0.0, 1.0))


def classify_interest_grade(r_dims: float) -> dict[str, str | float]:
    for grade, upper, label in GRADE_THRESHOLDS:
        if r_dims < upper:
            return {"grade": grade, "label": label, "upper_bound": upper}
    return {"grade": "SSS", "label": "Критичний інтерес", "upper_bound": 1.0}


def build_dims_assessment(
    tokenised: dict[str, list[str]],
    dist_df: pd.DataFrame,
    threshold: float,
    flagged_pairs: int,
    n_pairs: int,
    source_meta: dict[str, dict] | None = None,
) -> dict:
    doc_scores = _document_signal_scores(tokenised)
    content_score = float(np.mean([v["content"] for v in doc_scores.values()])) if doc_scores else 0.0
    impact_score = float(np.mean([v["impact"] for v in doc_scores.values()])) if doc_scores else 0.0
    coord_score = _coordination_score(dist_df, threshold)
    dynamics_score = _dynamics_score(len(tokenised), flagged_pairs, n_pairs)
    source_score, source_breakdown = _source_score(source_meta)
    r_dims = (
        DEFAULT_WEIGHTS["content"] * content_score
        + DEFAULT_WEIGHTS["coord"] * coord_score
        + DEFAULT_WEIGHTS["dynamics"] * dynamics_score
        + DEFAULT_WEIGHTS["impact"] * impact_score
        + DEFAULT_WEIGHTS["source"] * source_score
    )
    grade = classify_interest_grade(r_dims)
    return {
        "weights": DEFAULT_WEIGHTS,
        "indicators": {
            "I_content": round(content_score, 4),
            "I_coord": round(coord_score, 4),
            "I_dynamics": round(dynamics_score, 4),
            "I_impact": round(impact_score, 4),
            "I_source": round(source_score, 4),
        },
        "r_dims": round(float(r_dims), 4),
        "grade": grade,
        "document_signals": doc_scores,
        "source_breakdown": {k: round(v, 4) for k, v in source_breakdown.items()},
        "notes": [
            "I_content: маркери маніпулятивного змісту у корпусі.",
            "I_coord: стилометрична близькість і щільність підозрілих пар.",
            "I_dynamics: інтенсивність корпусу та щільність координаційних збігів.",
            "I_impact: маркери потенційного впливу на безпекове середовище.",
            "I_source: доменний ризик джерела та належність до ризикових медіа.",
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN PIPELINE
# ─────────────────────────────────────────────────────────────────────────────

def run_pipeline(
    corpus: dict[str, str],
    output_dir: Path,
    mfw_n: int = 100,
    threshold: float = 0.8,
    source_meta: dict[str, dict] | None = None,
) -> dict:
    """
    Run the complete stylometric pipeline.

    Parameters
    ----------
    corpus      : {label: clean_text}  — at least 2 documents required
    output_dir  : directory where PNG / CSV outputs are written
    mfw_n       : number of Most Frequent Words to use as features
    threshold   : Burrows' Delta threshold for flagging coordination

    Returns
    -------
    dict with keys:
        dist_df, mfw, tokenised, tf, z, global_counts,
        flagged, all_pairs, delta_stats,
        dendrogram_path, pca_path, csv_path,
        dendrogram_b64, pca_b64          ← base64 PNGs for HTML report
    """
    if len(corpus) < 2:
        raise ValueError("Потрібно щонайменше 2 джерела для порівняння.")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Pipeline steps ────────────────────────────────────────────────────
    tokenised     = tokenise_corpus(corpus)
    mfw           = find_mfw(tokenised, n=mfw_n)
    tf            = build_tf_matrix(tokenised, mfw)
    z             = zscore_matrix(tf)
    dist_df       = burrows_delta(z)

    dendrogram_path = output_dir / "dendrogram.png"
    pca_path        = output_dir / "pca_plot.png"
    csv_path        = output_dir / "distance_matrix.csv"

    save_dendrogram(dist_df, dendrogram_path)
    save_pca_plot(z, dist_df, pca_path)
    save_distance_matrix(dist_df, csv_path)

    # ── Pair analysis ─────────────────────────────────────────────────────
    labels    = dist_df.index.tolist()
    all_pairs = sorted(
        [(a, b, float(dist_df.loc[a, b])) for a, b in combinations(labels, 2)],
        key=lambda x: x[2],
    )
    flagged = [
        (a, b, d, classify_severity(d, threshold))
        for a, b, d in all_pairs if d < threshold
    ]

    deltas = np.array([d for _, _, d in all_pairs])

    # ── Corpus-level word frequencies (for report MFW table) ─────────────
    global_counts: Counter[str] = Counter()
    for tokens in tokenised.values():
        global_counts.update(tokens)

    dims_assessment = build_dims_assessment(
        tokenised=tokenised,
        dist_df=dist_df,
        threshold=threshold,
        flagged_pairs=len(flagged),
        n_pairs=len(all_pairs),
        source_meta=source_meta,
    )

    # ── Base64-encode chart images for HTML embedding ─────────────────────
    def _b64(path: Path) -> str:
        if path.exists():
            return base64.b64encode(path.read_bytes()).decode()
        return ""

    return {
        "dist_df":         dist_df,
        "mfw":             mfw,
        "tokenised":       tokenised,
        "tf":              tf,
        "z":               z,
        "global_counts":   global_counts,
        "flagged":         flagged,        # list of (a, b, delta, severity_dict)
        "all_pairs":       all_pairs,      # list of (a, b, delta), sorted asc
        "delta_stats": {
            "min":    float(deltas.min()),
            "max":    float(deltas.max()),
            "mean":   float(deltas.mean()),
            "median": float(np.median(deltas)),
            "std":    float(deltas.std()),
        },
        "dendrogram_path": dendrogram_path,
        "pca_path":        pca_path,
        "csv_path":        csv_path,
        "dendrogram_b64":  _b64(dendrogram_path),
        "pca_b64":         _b64(pca_path),
        "dims_assessment": dims_assessment,
        "mfw_n":           mfw_n,
        "threshold":       threshold,
        "n_docs":          len(labels),
        "n_pairs":         len(all_pairs),
    }
