#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
Stylometric Analysis for Detecting Coordinated Information Operations  (v3)
================================================================================

Method:   Burrows' Delta (Manhattan distance on Z-scored word frequencies)
Purpose:  PhD Dissertation — Decision Support Systems
Version:  3.0 — canonical, .txt-only, publication-quality output

Pipeline
--------
 1. Ingest  .txt files from ./data   (one file = one source)
 2. Clean   text (lowercase, strip punctuation/digits, tokenise)
 3. Select  top-N Most Frequent Words (MFW) across the corpus
 4. Build   Term-Frequency matrix  (documents × MFW)
 5. Compute Z-scores per feature (column-wise normalisation)
 6. Compute pairwise Burrows' Delta → distance matrix
 7. Run     Hierarchical Agglomerative Clustering (Ward) → dendrogram.png
 8. Run     PCA (2-D, cluster-coloured) → pca_plot.png
 9. Export  pairwise distance matrix → distance_matrix.csv
10. Print & save coordination report → report.txt

Usage
-----
    python stylometry_v3.py [--data ./data] [--output ./output]
                            [--mfw 100]  [--threshold 0.8]
"""

from __future__ import annotations

import argparse
import string
import sys
from collections import Counter
from datetime import datetime
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

# ── Matplotlib: headless backend, Cyrillic-safe font ─────────────────────────
import matplotlib
matplotlib.use("Agg")   # must be before pyplot import (safe for servers/CI)
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# Try to select a font that renders Cyrillic correctly.
# DejaVu Sans ships with matplotlib; Liberation Sans is common on Linux.
_CYRILLIC_CANDIDATES = ["DejaVu Sans", "Liberation Sans", "FreeSans", "Arial Unicode MS"]
_chosen_font = None
for _fname in _CYRILLIC_CANDIDATES:
    if any(_fname.lower() in f.name.lower() for f in fm.fontManager.ttflist):
        _chosen_font = _fname
        break

if _chosen_font:
    plt.rcParams["font.family"] = _chosen_font
else:
    # Fall back to the matplotlib default; Cyrillic may render as boxes on some
    # systems — user should install DejaVu Sans (bundled with most matplotlib).
    print("[WARN] No Cyrillic-safe font found; labels may not render correctly.")

# Publication-quality defaults
plt.rcParams.update({
    "figure.dpi":    300,
    "savefig.dpi":   300,
    "font.size":     10,
    "axes.titlesize": 13,
    "axes.labelsize": 11,
})

from scipy.cluster.hierarchy import linkage, dendrogram, fcluster
from scipy.spatial.distance import squareform, cdist
from sklearn.decomposition import PCA


# ════════════════════════════════════════════════════════════════════════════
#  MODULE 1 — TEXT INGESTION
# ════════════════════════════════════════════════════════════════════════════

def _resolve_data_dir(data_dir: str | Path) -> Path:
    """
    Return a valid Path to the data directory.
    If *data_dir* doesn't exist but its Title-cased variant does, use that
    and warn the user (handles ./data vs ./Data discrepancy).
    """
    p = Path(data_dir)
    if p.is_dir():
        return p
    # Try common capitalisation variants
    for variant in [p.parent / p.name.capitalize(),
                    p.parent / p.name.upper(),
                    p.parent / p.name.lower()]:
        if variant.is_dir():
            print(f"[WARN] '{data_dir}' not found; using '{variant}' instead.")
            return variant
    sys.exit(f"[ERROR] Data directory not found: {data_dir}")


def load_corpus(data_dir: str | Path) -> dict[str, str]:
    """
    Load every .txt file in *data_dir*.

    Returns
    -------
    dict[str, str]
        Mapping {file-stem → raw text}.  Sorted by filename for reproducibility.

    Tries encodings in order: UTF-8, UTF-8-BOM, Windows-1251, Latin-1.
    """
    data_dir = _resolve_data_dir(data_dir)
    files = sorted(data_dir.glob("*.txt"))

    if not files:
        sys.exit(
            f"[ERROR] No .txt files found in {data_dir}\n"
            f"        Place your source texts there and re-run."
        )

    corpus: dict[str, str] = {}
    for fpath in files:
        text = None
        for enc in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
            try:
                text = fpath.read_text(encoding=enc)
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        if text is None:
            text = fpath.read_text(encoding="utf-8", errors="replace")
            print(f"  [WARN] Encoding issues in {fpath.name}; replaced bad bytes.")

        corpus[fpath.stem] = text
        print(f"  [READ] {fpath.name}  ({len(text):,} chars)")

    print(f"[INFO] Loaded {len(corpus)} document(s) from '{data_dir}'")
    return corpus


# ════════════════════════════════════════════════════════════════════════════
#  MODULE 2 — TEXT CLEANING & TOKENISATION
# ════════════════════════════════════════════════════════════════════════════

# Translation table: deletes ASCII punctuation, digits, and common
# Ukrainian typographic characters in a single pass.
_STRIP_TABLE = str.maketrans(
    "", "",
    string.punctuation + string.digits + "«»—–„""''…·•№₴€$%°±×÷"
)


def clean_and_tokenise(text: str) -> list[str]:
    """
    Normalise one document into a list of word tokens.

    Steps:
      1. Lowercase
      2. Remove punctuation, digits, and special typographic characters
      3. Split on whitespace
      4. Keep only fully-alphabetic tokens of length ≥ 2
         (handles Cyrillic, Latin, and mixed scripts correctly)
    """
    text = text.lower()
    text = text.translate(_STRIP_TABLE)
    tokens = [t for t in text.split() if t.isalpha() and len(t) > 1]
    return tokens


def tokenise_corpus(corpus: dict[str, str]) -> dict[str, list[str]]:
    """Apply *clean_and_tokenise* to every document; print token counts."""
    tokenised: dict[str, list[str]] = {}
    for label, text in corpus.items():
        tokens = clean_and_tokenise(text)
        tokenised[label] = tokens
        warn = "  ⚠ <500 tokens — results may be less reliable" if len(tokens) < 500 else ""
        print(f"  [{label}] → {len(tokens):,} tokens{warn}")
    return tokenised


# ════════════════════════════════════════════════════════════════════════════
#  MODULE 3 — MOST FREQUENT WORDS (MFW)
# ════════════════════════════════════════════════════════════════════════════

def find_mfw(
    tokenised: dict[str, list[str]],
    n: int = 100,
) -> list[str]:
    """
    Identify the top-*n* most frequent word types across the entire corpus.

    Combining counts from all documents gives a corpus-level frequency table;
    the top-N entries become the stylometric feature set.  Functional words
    (prepositions, conjunctions, particles) naturally dominate this list and
    are the most style-diagnostic features.

    Returns
    -------
    list[str]
        Ordered list of MFW (most frequent first).
    """
    global_counts: Counter[str] = Counter()
    for tokens in tokenised.values():
        global_counts.update(tokens)

    mfw = [word for word, _ in global_counts.most_common(n)]
    print(f"[INFO] Top-{n} MFW selected — leading words: {mfw[:5]}")
    return mfw


# ════════════════════════════════════════════════════════════════════════════
#  MODULE 4 — TERM-FREQUENCY MATRIX
# ════════════════════════════════════════════════════════════════════════════

def build_tf_matrix(
    tokenised: dict[str, list[str]],
    mfw: list[str],
) -> pd.DataFrame:
    """
    Build a document × MFW matrix of **relative** term frequencies.

    TF(word, doc) = count(word in doc) / total_words_in_doc

    Relative (rather than raw) frequencies are used so that documents of
    different lengths are comparable.

    Returns
    -------
    pd.DataFrame
        Shape (n_docs, n_mfw).  Index = source labels; columns = MFW.
    """
    records: dict[str, dict[str, float]] = {}
    for label, tokens in tokenised.items():
        total = len(tokens)
        counts = Counter(tokens)
        records[label] = {w: counts.get(w, 0) / total for w in mfw}

    tf = pd.DataFrame.from_dict(records, orient="index")[mfw]
    print(f"[INFO] TF matrix shape: {tf.shape}  (documents × MFW features)")
    return tf


# ════════════════════════════════════════════════════════════════════════════
#  MODULE 5 — Z-SCORE NORMALISATION
# ════════════════════════════════════════════════════════════════════════════

def zscore_matrix(tf: pd.DataFrame) -> pd.DataFrame:
    """
    Column-wise Z-score normalisation (Burrows' convention).

    Z(word, doc) = (TF(word, doc) − mean_corpus(word)) / std_corpus(word)

    Uses **population** standard deviation (ddof=0) as per Burrows (2002).
    Features with zero variance are assigned std=1 to avoid division by zero
    (they contribute zero to Delta regardless).

    Returns
    -------
    pd.DataFrame
        Same shape as *tf*; values are Z-scores.
    """
    means = tf.mean(axis=0)
    stds  = tf.std(axis=0, ddof=0)
    stds  = stds.replace(0.0, 1.0)   # guard: zero-variance features
    return (tf - means) / stds


# ════════════════════════════════════════════════════════════════════════════
#  MODULE 6 — BURROWS' DELTA (PAIRWISE DISTANCES)
# ════════════════════════════════════════════════════════════════════════════

def burrows_delta(z: pd.DataFrame) -> pd.DataFrame:
    """
    Compute the classic Burrows' Delta between every pair of documents.

        Delta(A, B) = (1/n) × Σᵢ |z_Aᵢ − z_Bᵢ|

    This is the mean absolute difference of Z-scores — equivalent to the
    L1 (Manhattan / city-block) distance normalised by the number of features.

    Implementation: ``scipy.spatial.distance.cdist`` with ``metric='cityblock'``
    for vectorised computation (no Python-level double loop).

    Returns
    -------
    pd.DataFrame
        Symmetric distance matrix; shape (n_docs, n_docs); diagonal = 0.
    """
    labels     = z.index.tolist()
    n_features = z.shape[1]
    z_vals     = z.values.astype(float)

    # cdist returns the full pairwise L1 matrix; divide by n to get Delta
    raw = cdist(z_vals, z_vals, metric="cityblock")
    dist = raw / n_features

    df = pd.DataFrame(dist, index=labels, columns=labels)
    n  = len(labels)
    print(f"[INFO] Burrows' Delta matrix: {n}×{n}  "
          f"(min={dist[dist > 0].min():.4f}, max={dist.max():.4f})")
    return df


# ════════════════════════════════════════════════════════════════════════════
#  MODULE 7 — HIERARCHICAL CLUSTERING → DENDROGRAM
# ════════════════════════════════════════════════════════════════════════════

def _build_linkage(dist_df: pd.DataFrame):
    """Convert a square distance matrix to a scipy linkage array (Ward)."""
    condensed = squareform(dist_df.values, checks=False)
    return linkage(condensed, method="ward")


def save_dendrogram(dist_df: pd.DataFrame, output_path: Path) -> None:
    """
    Perform Ward's Hierarchical Agglomerative Clustering and save a dendrogram.

    Ward's method minimises within-cluster variance at each merge step,
    producing compact, well-separated clusters — well suited to stylometric
    similarity data.

    The colour threshold is set at 70% of the maximum merge height,
    visually separating major stylistic clusters.
    """
    Z       = _build_linkage(dist_df)
    c_thresh = 0.7 * float(Z[:, 2].max())

    n_docs  = len(dist_df)
    fig_w   = max(10, n_docs * 1.0)
    fig, ax = plt.subplots(figsize=(fig_w, 6))

    dendrogram(
        Z,
        labels=dist_df.index.tolist(),
        leaf_rotation=45,
        leaf_font_size=9,
        color_threshold=c_thresh,
        ax=ax,
    )

    ax.axhline(c_thresh, linestyle="--", color="grey", linewidth=0.8,
               label=f"Поріг кольору ({c_thresh:.3f})")
    ax.set_title("Стилометрична дендрограма (Burrows' Delta, Ward's method)",
                 fontweight="bold")
    ax.set_ylabel("Відстань (Delta)")
    ax.set_xlabel("Джерела / Sources")
    ax.legend(fontsize=8, loc="upper right")

    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)
    print(f"[INFO] Dendrogram saved      → {output_path}")


# ════════════════════════════════════════════════════════════════════════════
#  MODULE 8 — PCA SCATTER PLOT (CLUSTER-COLOURED)
# ════════════════════════════════════════════════════════════════════════════

def save_pca_plot(
    z: pd.DataFrame,
    dist_df: pd.DataFrame,
    output_path: Path,
) -> None:
    """
    Reduce stylometric features to 2-D with PCA and save a scatter plot.

    Points are coloured by HAC cluster membership (same colour threshold as
    the dendrogram), so the PCA and dendrogram visualisations are consistent.
    A legend maps cluster number → colour.

    Notes
    -----
    If total explained variance (PC1 + PC2) < 60%, the 2-D projection may
    not fully represent the data structure — the dendrogram is more reliable.
    """
    if len(z) < 2:
        print("[WARN] PCA requires ≥ 2 documents — skipping.")
        return

    # ── PCA ──────────────────────────────────────────────────────────────
    n_components = min(2, len(z) - 1, z.shape[1])
    pca    = PCA(n_components=n_components)
    coords = pca.fit_transform(z.values)
    var    = pca.explained_variance_ratio_ * 100

    # Pad to 2 columns if corpus has exactly 2 documents
    if coords.shape[1] == 1:
        coords = np.column_stack([coords, np.zeros(len(coords))])
        var    = np.append(var, [0.0])

    # ── Cluster colours (derived from dendrogram) ─────────────────────────
    Z_link   = _build_linkage(dist_df)
    c_thresh = 0.7 * float(Z_link[:, 2].max())
    cluster_ids = fcluster(Z_link, t=c_thresh, criterion="distance")
    n_clusters  = len(set(cluster_ids))

    cmap    = plt.get_cmap("tab10")
    palette = {cid: cmap(i / max(n_clusters, 1))
               for i, cid in enumerate(sorted(set(cluster_ids)))}
    colors  = [palette[cid] for cid in cluster_ids]

    # ── Plot ──────────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(10, 7))

    # Scatter: one point per document, coloured by cluster
    for cid in sorted(set(cluster_ids)):
        mask = cluster_ids == cid
        ax.scatter(
            coords[mask, 0], coords[mask, 1],
            color=palette[cid],
            s=90, edgecolors="k", linewidths=0.6,
            zorder=3,
            label=f"Кластер {cid}",
        )

    # Text labels for each document
    for idx, label in enumerate(z.index):
        ax.annotate(
            label,
            (coords[idx, 0], coords[idx, 1]),
            textcoords="offset points",
            xytext=(6, 6),
            fontsize=8,
            color=colors[idx],
        )

    total_var = sum(var[:2])
    ax.set_xlabel(f"PC1 ({var[0]:.1f}% дисперсії)", fontsize=11)
    ax.set_ylabel(f"PC2 ({var[1]:.1f}% дисперсії)", fontsize=11)
    ax.set_title(
        f"PCA-проєкція стилометричних ознак\n"
        f"(пояснена дисперсія: {total_var:.1f}%)",
        fontweight="bold",
    )
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.legend(loc="best", fontsize=9, framealpha=0.8)

    if total_var < 60:
        ax.text(
            0.01, 0.01,
            f"⚠ PC1+PC2 пояснюють лише {total_var:.0f}% дисперсії — "
            "дендрограма надійніша",
            transform=ax.transAxes, fontsize=7, color="grey",
            verticalalignment="bottom",
        )

    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)
    print(f"[INFO] PCA plot saved        → {output_path}")


# ════════════════════════════════════════════════════════════════════════════
#  MODULE 9 — DISTANCE MATRIX CSV
# ════════════════════════════════════════════════════════════════════════════

def save_distance_matrix(dist_df: pd.DataFrame, output_path: Path) -> None:
    """Export the full pairwise Burrows' Delta matrix as a CSV file."""
    dist_df.to_csv(output_path, float_format="%.6f")
    print(f"[INFO] Distance matrix saved → {output_path}")


# ════════════════════════════════════════════════════════════════════════════
#  MODULE 10 — COORDINATION REPORT
# ════════════════════════════════════════════════════════════════════════════

def _hr(char: str = "═", width: int = 74) -> str:
    return char * width


def generate_report(
    dist_df:    pd.DataFrame,
    threshold:  float,
    output_path: Path,
    tokenised:  dict[str, list[str]],
    mfw:        list[str],
    n_mfw:      int,
    data_dir:   str,
) -> None:
    """
    Build, print to console, and save a plain-text analysis report.

    The report covers:
      - Parameters used
      - Corpus statistics (token counts, short-document warnings)
      - Top-20 MFW with corpus-wide frequencies
      - Descriptive statistics of the Delta distribution
      - All flagged pairs (Delta < threshold), ranked by distance,
        labelled "Potentially Coordinated" with severity tiers
      - Interpretation guidance for dissertation use
    """
    labels  = dist_df.index.tolist()
    n_docs  = len(labels)
    n_pairs = len(list(combinations(labels, 2)))
    ts      = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── Precompute all pairs and flagged subset ───────────────────────────
    all_pairs: list[tuple[str, str, float]] = []
    for a, b in combinations(labels, 2):
        all_pairs.append((a, b, dist_df.loc[a, b]))
    all_pairs.sort(key=lambda x: x[2])

    flagged = [(a, b, d) for a, b, d in all_pairs if d < threshold]

    all_deltas = np.array([d for _, _, d in all_pairs])

    # ── Severity tiers based on threshold ────────────────────────────────
    crit_limit = threshold * 0.30
    high_limit = threshold * 0.60

    def severity(d: float) -> str:
        if d < crit_limit:
            return "КРИТИЧНИЙ / CRITICAL"
        if d < high_limit:
            return "ВИСОКИЙ / HIGH"
        return "ПОМІРНИЙ / MODERATE"

    # ── Corpus-level MFW frequencies for the report table ────────────────
    global_counts: Counter[str] = Counter()
    for tokens in tokenised.values():
        global_counts.update(tokens)

    # ── Build report lines ────────────────────────────────────────────────
    L: list[str] = []

    # Header
    L += [
        _hr(),
        "  ЗВІТ СТИЛОМЕТРИЧНОГО АНАЛІЗУ / STYLOMETRIC ANALYSIS REPORT",
        "  Метод / Method: Burrows' Delta (Burrows 2002)",
        "  Застосування / Application: Виявлення координованих інформаційних операцій",
        f"  Дата / Date: {ts}",
        _hr(),
        "",
    ]

    # Section 1 — Parameters
    L += [
        "── РОЗДІЛ 1: ПАРАМЕТРИ АНАЛІЗУ / ANALYSIS PARAMETERS ──",
        "",
        f"  Директорія даних / Data directory:  {data_dir}",
        f"  Кількість MFW (N):                  {n_mfw}",
        f"  Поріг Delta (threshold):             {threshold:.2f}",
        f"  Завантажено документів:              {n_docs}",
        f"  Порівнюваних пар:                   {n_pairs}",
        "",
    ]

    # Section 2 — Corpus statistics
    L += [
        "── РОЗДІЛ 2: СТАТИСТИКА КОРПУСУ / CORPUS STATISTICS ──",
        "",
        f"  {'Джерело / Source':<45s}  {'Токенів / Tokens':>14s}",
        "  " + "─" * 62,
    ]
    total_tokens = 0
    for label in labels:
        n_tok = len(tokenised[label])
        total_tokens += n_tok
        warn = "  ⚠" if n_tok < 500 else ""
        L.append(f"  {label:<45s}  {n_tok:>14,d}{warn}")
    L += [
        "  " + "─" * 62,
        f"  {'РАЗОМ / TOTAL':<45s}  {total_tokens:>14,d}",
        f"  {'Середнє / Average':<45s}  {total_tokens // n_docs:>14,d}",
        "",
        "  ⚠ = менше 500 токенів; результати можуть бути менш надійними",
        "",
    ]

    # Section 3 — Top-20 MFW
    L += [
        f"── РОЗДІЛ 3: ТОП-20 MFW (із {n_mfw}) / TOP-20 MFW ──",
        "",
        f"  {'#':<5s}  {'Слово / Word':<20s}  {'Частота / Corpus freq':>22s}",
        "  " + "─" * 52,
    ]
    for rank, word in enumerate(mfw[:20], start=1):
        freq = global_counts[word]
        L.append(f"  {rank:<5d}  {word:<20s}  {freq:>22,d}")
    L.append("")

    # Section 4 — Delta statistics
    L += [
        "── РОЗДІЛ 4: СТАТИСТИКА DELTA / DELTA DISTRIBUTION ──",
        "",
        f"  Мінімальна Delta:    {all_deltas.min():.4f}",
        f"  Максимальна Delta:   {all_deltas.max():.4f}",
        f"  Середня / Mean:      {all_deltas.mean():.4f}",
        f"  Медіана / Median:    {np.median(all_deltas):.4f}",
        f"  Ст. відхилення / SD: {all_deltas.std():.4f}",
        "",
    ]

    # Section 5 — Flagged pairs
    L += [
        _hr("─"),
        f"  РОЗДІЛ 5: ПОТЕНЦІЙНО СКООРДИНОВАНІ ПАРИ / POTENTIALLY COORDINATED PAIRS",
        f"  Поріг / Threshold: Delta < {threshold:.2f}",
        _hr("─"),
        "",
        f"  Знайдено підозрілих пар: {len(flagged)} із {n_pairs}",
        "",
    ]

    if flagged:
        for rank, (a, b, d) in enumerate(flagged, start=1):
            sev = severity(d)
            L += [
                f"  [{rank}] ⚑  {a}",
                f"       ↔  {b}",
                f"       Delta = {d:.4f}   |   Рівень / Severity: {sev}",
                "",
            ]
        L += [
            "  Шкала рівнів / Severity scale:",
            f"    КРИТИЧНИЙ  Delta < {crit_limit:.2f}  — висока ймовірність координації",
            f"    ВИСОКИЙ    Delta {crit_limit:.2f}–{high_limit:.2f}  — значна стилістична подібність",
            f"    ПОМІРНИЙ   Delta {high_limit:.2f}–{threshold:.2f}  — потребує перевірки",
            "",
        ]
    else:
        L += [
            "  ✅ Жодна пара не має Delta нижче порогу.",
            "     Ознак стилістичної координації не виявлено.",
            "",
        ]

    # Section 6 — Top-5 most similar pairs (for reference)
    L += [
        "── РОЗДІЛ 6: НАЙ ПОДІБНІШІ ПАРИ / MOST SIMILAR PAIRS (top-5) ──",
        "",
    ]
    for a, b, d in all_pairs[:5]:
        L.append(f"  {a}  ↔  {b}   │  Delta = {d:.4f}")
    L.append("")

    # Section 7 — Interpretation
    L += [
        "── РОЗДІЛ 7: ІНТЕРПРЕТАЦІЯ / INTERPRETATION ──",
        "",
        "  Burrows' Delta вимірює стилістичну відстань між текстами на основі",
        "  відносних частот найуживаніших слів (переважно функціональних).",
        "  Менше значення Delta → більша стилістична подібність.",
        "",
        "  Ключові принципи для дисертації:",
        "  • Координовані джерела несвідомо демонструють схожі частотні паттерни",
        "    функціональних слів навіть при різних темах публікацій.",
        "  • Delta < 0.5 між різними джерелами є аномально низькою.",
        "  • Результати є індикативними; потрібна додаткова верифікація.",
        "  • Рекомендується повторити аналіз з N = 50, 100, 200, 500 MFW.",
        "  • Тексти однієї мови дають надійніші результати.",
        "",
    ]

    # Footer
    L += [
        _hr(),
        f"  Файли результатів / Output files:",
        f"  • dendrogram.png       — дендрограма ієрархічної кластеризації",
        f"  • pca_plot.png         — PCA-проєкція (2D, кольори = кластери)",
        f"  • distance_matrix.csv  — повна матриця відстаней Burrows' Delta",
        f"  • report.txt           — цей звіт",
        _hr(),
    ]

    report = "\n".join(L)

    # Print to console (as required)
    print("\n" + report)

    # Save to file (as required)
    output_path.write_text(report, encoding="utf-8")
    print(f"\n[INFO] Report saved         → {output_path}")


# ════════════════════════════════════════════════════════════════════════════
#  CLI + MAIN PIPELINE
# ════════════════════════════════════════════════════════════════════════════

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Stylometric analysis v3 — Burrows' Delta for detecting "
            "coordinated information operations in Ukrainian texts."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--data", default="./data",
        help="Directory containing .txt source files (one file = one source)",
    )
    p.add_argument(
        "--output", default="./output",
        help="Directory for output files (created if absent)",
    )
    p.add_argument(
        "--mfw", type=int, default=100,
        help="Number of Most Frequent Words to use as features",
    )
    p.add_argument(
        "--threshold", type=float, default=0.8,
        help="Burrows' Delta threshold below which pairs are flagged",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    out  = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    print(_hr())
    print("  Stylometric Analysis v3 — Burrows' Delta Pipeline")
    print(f"  MFW={args.mfw}  |  threshold={args.threshold}  |  out={out.resolve()}")
    print(_hr())

    # ── Step 1: Load corpus ───────────────────────────────────────────────
    corpus    = load_corpus(args.data)

    # ── Step 2: Clean & tokenise ──────────────────────────────────────────
    tokenised = tokenise_corpus(corpus)

    # ── Step 3: Most Frequent Words ───────────────────────────────────────
    mfw       = find_mfw(tokenised, n=args.mfw)

    # ── Step 4: Term-Frequency matrix ─────────────────────────────────────
    tf        = build_tf_matrix(tokenised, mfw)

    # ── Step 5: Z-score normalisation ─────────────────────────────────────
    z         = zscore_matrix(tf)

    # ── Step 6: Burrows' Delta distance matrix ────────────────────────────
    dist_df   = burrows_delta(z)

    # ── Step 7: Dendrogram (Ward clustering) ──────────────────────────────
    save_dendrogram(dist_df, out / "dendrogram.png")

    # ── Step 8: PCA scatter plot (cluster-coloured) ───────────────────────
    save_pca_plot(z, dist_df, out / "pca_plot.png")

    # ── Step 9: Distance matrix CSV ───────────────────────────────────────
    save_distance_matrix(dist_df, out / "distance_matrix.csv")

    # ── Step 10: Coordination report (print + save) ───────────────────────
    generate_report(
        dist_df=dist_df,
        threshold=args.threshold,
        output_path=out / "report.txt",
        tokenised=tokenised,
        mfw=mfw,
        n_mfw=args.mfw,
        data_dir=args.data,
    )

    print(f"\n✅ Аналіз завершено / Analysis complete. Results in: {out.resolve()}")


if __name__ == "__main__":
    main()
