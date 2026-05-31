#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/calibration_comparison.py
===============================
Відтворюваний скрипт для двох наукових артефактів DIMS:

  A. AHP-калібрування вагів (Analytic Hierarchy Process, Saaty):
     матриця попарних порівнянь → вектор пріоритетів (середнє геометричне)
     → λmax, індекс узгодженості CI, коефіцієнт узгодженості CR.
     Виводить ваги w1..w5 та підваги I_source, перевіряє CR < 0.10.

  B. Абляційне порівняння «до/після» (контрольований сценарій):
     на реальному обчисленні моделі показує внесок удосконалень
     (стилометрія Burrows → I_coord; ризик джерела → I_source) у R_DIMS і
     підсумковий грейд. НЕ є польовою статистичною валідацією (для неї
     потрібен розмічений набір — окремий крок); це демонстрація механізму
     та внеску компонентів на реальних текстах.

Запуск:
    .venv/bin/python tools/calibration_comparison.py

Виходи:
    - таблиці/числа в stdout (Markdown);
    - PNG-графіки у output/calibration/.
"""
from __future__ import annotations

import os
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
os.environ.setdefault("MPLBACKEND", "Agg")

import sys
from itertools import combinations
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from core.analysis import (
    tokenise_corpus, find_mfw, build_tf_matrix, zscore_matrix, burrows_delta,
    build_dims_assessment, classify_interest_grade,
    DEFAULT_WEIGHTS, SOURCE_COMPONENT_WEIGHTS, GRADE_THRESHOLDS,
)

CLEAN = BASE / "output" / "clean_texts"
# Графіки зберігаємо в docs/img/ (відстежується git; output/ у .gitignore).
OUT = BASE / "docs" / "img"
OUT.mkdir(parents=True, exist_ok=True)

# Saaty Random Index (середні CI випадкових матриць) для n = 1..10
SAATY_RI = {1: 0.0, 2: 0.0, 3: 0.58, 4: 0.90, 5: 1.12,
            6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45, 10: 1.49}


# ─────────────────────────────────────────────────────────────────────────────
#  A. AHP
# ─────────────────────────────────────────────────────────────────────────────
def ahp(matrix: np.ndarray) -> dict:
    """AHP за методом середнього геометричного рядків.
    Повертає priority vector, λmax, CI, CR."""
    n = matrix.shape[0]
    # Вектор пріоритетів — нормоване середнє геометричне рядків.
    gm = np.prod(matrix, axis=1) ** (1.0 / n)
    w = gm / gm.sum()
    # λmax: середнє відношення (A·w)_i / w_i.
    aw = matrix @ w
    lam_max = float(np.mean(aw / w))
    ci = (lam_max - n) / (n - 1) if n > 2 else 0.0
    ri = SAATY_RI.get(n, 1.49)
    cr = ci / ri if ri > 0 else 0.0
    return {"weights": w, "lambda_max": lam_max, "CI": ci, "RI": ri, "CR": cr}


def print_matrix(title: str, labels: list[str], M: np.ndarray) -> None:
    print(f"\n**{title}** (матриця попарних порівнянь, шкала Сааті 1–9):\n")
    head = "| | " + " | ".join(labels) + " |"
    sep = "|" + "---|" * (len(labels) + 1)
    print(head)
    print(sep)
    for i, lab in enumerate(labels):
        row = " | ".join(f"{M[i, j]:.3g}" for j in range(len(labels)))
        print(f"| **{lab}** | {row} |")


def run_ahp_block() -> dict:
    print("\n# A. AHP-калібрування вагів\n")

    # ── A.1 Головні індикатори R_DIMS ──────────────────────────────────────
    # Попарні судження експерта (наскільки індикатор i важливіший за j),
    # узгоджені з пріоритетами чинної експертної моделі:
    # content ≳ source > coord ≈ impact > dynamics.
    main_labels = ["content", "coord", "dynamics", "impact", "source"]
    M_main = np.array([
        # content coord dyn  impact source
        [1,      2,    4,    2,     1],     # content
        [1/2,    1,    3,    1,     1/2],   # coord
        [1/4,    1/3,  1,    1/3,   1/4],   # dynamics
        [1/2,    1,    3,    1,     1/2],   # impact
        [1,      2,    4,    2,     1],     # source
    ], dtype=float)
    res_main = ahp(M_main)
    print_matrix("A.1 Головні індикатори", main_labels, M_main)

    # ── A.2 Підкомпоненти I_source ─────────────────────────────────────────
    src_labels = ["domain", "owner", "cred", "policy", "finance", "ethics", "original"]
    M_src = np.array([
        # dom  own  cred pol  fin  eth  orig
        [1,    3,    3,   4,   4,   5,   8],   # domain
        [1/3,  1,    1,   2,   2,   2,   3],   # owner
        [1/3,  1,    1,   1,   1,   2,   3],   # cred
        [1/4,  1/2,  1,   1,   1,   1,   2],   # policy
        [1/4,  1/2,  1,   1,   1,   1,   2],   # finance
        [1/5,  1/2,  1/2, 1,   1,   1,   2],   # ethics
        [1/8,  1/3,  1/3, 1/2, 1/2, 1/2, 1],   # original
    ], dtype=float)
    res_src = ahp(M_src)
    print_matrix("A.2 Підкомпоненти I_source", src_labels, M_src)

    def cmp_table(title, labels, derived, current):
        print(f"\n**{title} — AHP vs чинні значення:**\n")
        print("| Компонент | AHP-ваг | Чинна ваг | Δ |")
        print("|---|---|---|---|")
        for lab in labels:
            d = derived[lab]
            c = current[lab]
            print(f"| {lab} | {d:.3f} | {c:.3f} | {d-c:+.3f} |")

    w_main = {lab: float(res_main["weights"][i]) for i, lab in enumerate(main_labels)}
    w_src = {lab: float(res_src["weights"][i]) for i, lab in enumerate(src_labels)}

    cmp_table("A.1 Головні ваги", main_labels, w_main, DEFAULT_WEIGHTS)
    print(f"\nλmax = {res_main['lambda_max']:.4f}, CI = {res_main['CI']:.4f}, "
          f"RI = {res_main['RI']}, **CR = {res_main['CR']:.4f}** "
          f"({'УЗГОДЖЕНО ✅ (<0.10)' if res_main['CR'] < 0.10 else 'НЕузгоджено ❌'})")

    cmp_table("A.2 Підваги I_source", src_labels, w_src, SOURCE_COMPONENT_WEIGHTS)
    print(f"\nλmax = {res_src['lambda_max']:.4f}, CI = {res_src['CI']:.4f}, "
          f"RI = {res_src['RI']}, **CR = {res_src['CR']:.4f}** "
          f"({'УЗГОДЖЕНО ✅ (<0.10)' if res_src['CR'] < 0.10 else 'НЕузгоджено ❌'})")

    # Графік: AHP vs чинні (головні ваги)
    fig, ax = plt.subplots(figsize=(8, 4.5))
    x = np.arange(len(main_labels))
    ax.bar(x - 0.2, [w_main[l] for l in main_labels], 0.4, label="AHP", color="#2b6cb0")
    ax.bar(x + 0.2, [DEFAULT_WEIGHTS[l] for l in main_labels], 0.4, label="Чинні", color="#dd6b20")
    ax.set_xticks(x); ax.set_xticklabels(main_labels)
    ax.set_ylabel("Вага"); ax.set_title(f"AHP vs чинні ваги (CR={res_main['CR']:.3f})")
    ax.legend(); fig.tight_layout()
    fig.savefig(OUT / "ahp_main_weights.png", dpi=150); plt.close(fig)

    return {"main": res_main, "source": res_src, "w_main": w_main, "w_src": w_src}


# ─────────────────────────────────────────────────────────────────────────────
#  B. Абляція
# ─────────────────────────────────────────────────────────────────────────────
def _grade(r: float) -> str:
    return classify_interest_grade(r)["grade"]


def indicators_for(corpus: dict[str, str], source_meta: dict[str, dict],
                   threshold: float = 0.8) -> dict:
    """Мінімальний конвеєр → 5 індикаторів (без bootstrap/графіків)."""
    tokenised = tokenise_corpus(corpus)
    mfw = find_mfw(tokenised, n=100, min_doc_freq=2)
    tf = build_tf_matrix(tokenised, mfw)
    z = zscore_matrix(tf)
    dist_df = burrows_delta(z)
    labels = dist_df.index.tolist()
    all_pairs = [(a, b, float(dist_df.loc[a, b])) for a, b in combinations(labels, 2)]
    flagged = [p for p in all_pairs if p[2] < threshold]
    assess = build_dims_assessment(
        tokenised=tokenised, dist_df=dist_df, threshold=threshold,
        flagged_pairs=len(flagged), n_pairs=len(all_pairs),
        source_meta=source_meta, corpus=corpus, manifestation=None,
    )
    ind = assess["indicators"]
    return {
        "content": ind["I_content"], "coord": ind["I_coord"],
        "dynamics": ind["I_dynamics"], "impact": ind["I_impact"],
        "source": ind["I_source"],
    }


# Конфігурації абляції: активні індикатори (підмножина вагів, ренормована).
ABLATION_CONFIGS = {
    "Базовий (зміст+вплив)":        ["content", "impact"],
    "+ Координація (Burrows)":      ["content", "impact", "coord"],
    "+ Ризик джерела":              ["content", "impact", "coord", "source"],
    "Повний DIMS":                  ["content", "coord", "dynamics", "impact", "source"],
}


def r_dims_config(ind: dict, active: list[str]) -> float:
    """R_DIMS на підмножині індикаторів з ренормуванням чинних вагів."""
    wsum = sum(DEFAULT_WEIGHTS[k] for k in active)
    return float(sum(DEFAULT_WEIGHTS[k] / wsum * ind[k] for k in active))


def load(name: str) -> str:
    return (CLEAN / name).read_text(encoding="utf-8")


def run_ablation_block() -> dict:
    print("\n\n# B. Абляційне порівняння «до/після» (контрольований сценарій)\n")
    print("> Це демонстрація внеску компонентів на реальному обчисленні моделі, "
          "а НЕ польова статистична валідація. Домени призначено відповідно до "
          "категорії джерела для ілюстрації механізму. Повна валідація — на "
          "розміченому наборі (наступний крок).\n")

    # Сценарій 1: координований проросійський вкид.
    # Два майже-дублікати (стилометрична близькість → I_coord) + проросійські домени.
    sc1_files = {
        "source_C_disinfo1.txt":   "de.rt.com",
        "source_C_disinfo1_1.txt": "sputniknews.ru",
        "source_D_disinfo2.txt":   "ria.ru",
    }
    # Сценарій 2: легітимне різнопланове висвітлення.
    sc2_files = {
        "source_E_official.txt": "ukrinform.ua",
        "source_A_news.txt":     "suspilne.media",
        "source_F_analytics.txt": "nv.ua",
    }

    scenarios = {
        "Координований проросійський вкид": sc1_files,
        "Легітимне висвітлення": sc2_files,
    }

    results = {}
    for sc_name, files in scenarios.items():
        corpus = {Path(f).stem: load(f) for f in files}
        meta = {Path(f).stem: {"domain": dom, "type": "url"} for f, dom in files.items()}
        ind = indicators_for(corpus, meta)
        rows = []
        for cfg_name, active in ABLATION_CONFIGS.items():
            r = r_dims_config(ind, active)
            rows.append((cfg_name, r, _grade(r)))
        results[sc_name] = {"ind": ind, "rows": rows, "domains": list(files.values())}

        print(f"\n## Сценарій: {sc_name}")
        print(f"Джерела (домени): {', '.join(files.values())}")
        print(f"\nІндикатори: I_content={ind['content']:.3f}, I_coord={ind['coord']:.3f}, "
              f"I_dynamics={ind['dynamics']:.3f}, I_impact={ind['impact']:.3f}, "
              f"**I_source={ind['source']:.3f}**\n")
        print("| Конфігурація | R_DIMS | Грейд |")
        print("|---|---|---|")
        for cfg, r, g in rows:
            print(f"| {cfg} | {r:.3f} | **{g}** |")

    # Матриця переходів грейдів (база → повний)
    print("\n## Матриця переходів грейду (базовий → повний DIMS)\n")
    print("| Сценарій | Грейд (базовий) | Грейд (повний DIMS) | Зміна |")
    print("|---|---|---|---|")
    for sc_name, data in results.items():
        g_base = data["rows"][0][2]
        g_full = data["rows"][-1][2]
        arrow = "↑ підвищено" if g_base != g_full else "= без змін"
        print(f"| {sc_name} | {g_base} | {g_full} | {arrow} |")

    # Графік: R_DIMS по конфігураціях × сценаріях
    fig, ax = plt.subplots(figsize=(9, 5))
    cfg_names = list(ABLATION_CONFIGS.keys())
    x = np.arange(len(cfg_names))
    width = 0.38
    colors = {"Координований проросійський вкид": "#c53030",
              "Легітимне висвітлення": "#2f855a"}
    for i, (sc_name, data) in enumerate(results.items()):
        vals = [r for _, r, _ in data["rows"]]
        ax.bar(x + (i - 0.5) * width, vals, width, label=sc_name,
               color=colors.get(sc_name, "#666"))
    for thr, lbl in [(0.2, "F|B"), (0.4, "B|S"), (0.6, "S|SS"), (0.8, "SS|SSS")]:
        ax.axhline(thr, ls="--", lw=0.7, color="#888")
        ax.text(len(cfg_names) - 0.5, thr + 0.005, lbl, fontsize=8, color="#888")
    ax.set_xticks(x); ax.set_xticklabels(cfg_names, rotation=15, ha="right", fontsize=9)
    ax.set_ylabel("R_DIMS"); ax.set_ylim(0, 1)
    ax.set_title("Абляція: внесок удосконалень у R_DIMS")
    ax.legend(); fig.tight_layout()
    fig.savefig(OUT / "ablation_rdims.png", dpi=150); plt.close(fig)

    return results


def main():
    print("# DIMS — калібрування вагів (AHP) та порівняння «до/після» (абляція)")
    run_ahp_block()
    run_ablation_block()
    print(f"\n\n✅ Графіки збережено у: {OUT}")
    print("   - ahp_main_weights.png")
    print("   - ablation_rdims.png")


if __name__ == "__main__":
    main()
