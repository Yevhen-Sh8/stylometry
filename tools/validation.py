#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/validation.py
===================
Фаза 2 — статистична валідація DIMS на РОЗМІЧЕНОМУ наборі подій.

Дає відповідь на головний закид експертної ради: «рівномірні пороги грейдів
(0,20/0,40/0,60/0,80) довільні» і «немає підтвердження точності методики».
Обчислює:
  • матрицю плутанини (5×5) та точність;
  • зважену κ Коена (quadratic) — узгодженість на ПОРЯДКОВІЙ шкалі;
  • MAE за індексом грейду;
  • ROC/Youden-оптимальні пороги θ₁..θ₄ (data-driven альтернатива рівномірним);
  • порівняння «чинні vs ROC-калібровані пороги».

ВАЖЛИВО: скрипт НЕ містить і НЕ вигадує даних. Він працює лише з тим набором,
який надасть автор (manifest). Прапорець --selftest генерує СИНТЕТИЧНІ дані
ВИКЛЮЧНО для перевірки працездатності коду (це не валідація методики).

Формат розмітки (manifest, JSONL — по одному об'єкту-події на рядок):
    {
      "event_id": "ev001",
      "grade": "S",                       # експертний грейд F/B/S/SS/SSS
      "manifestation": "fake",            # опц.; "taboo" → авто-SS
      "sources": [
        {"text_path": "Data/val/ev001/a.txt", "domain": "ria.ru",
         "published": "2026-05-01T10:00:00"},
        {"text": "повний текст замість файлу...", "domain": "bbc.com"}
      ]
    }

Запуск:
    .venv/bin/python tools/validation.py --manifest Data/validation_set.jsonl
    .venv/bin/python tools/validation.py --selftest        # перевірка коду
"""
from __future__ import annotations

import os
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
os.environ.setdefault("MPLBACKEND", "Agg")

import argparse
import json
import random
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
    build_dims_assessment, classify_interest_grade, GRADE_THRESHOLDS,
)

GRADES = [g for g, _, _ in GRADE_THRESHOLDS]        # ["F","B","S","SS","SSS"]
GRADE_IDX = {g: i for i, g in enumerate(GRADES)}
# Поточні (рівномірні) верхні межі грейдів — для порівняння з ROC.
CURRENT_UPPERS = [u for _, u, _ in GRADE_THRESHOLDS if u != float("inf")]  # 0.2,0.4,0.6,0.8
OUT = BASE / "docs" / "img"
OUT.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
#  Обчислення R_DIMS для однієї події
# ─────────────────────────────────────────────────────────────────────────────
def _event_r_dims(sources: list[dict], manifestation: str | None,
                  threshold: float = 0.8) -> tuple[float, str]:
    """Мінімальний конвеєр DIMS для однієї події → (R_DIMS, передбачений грейд)."""
    corpus, meta = {}, {}
    for i, s in enumerate(sources):
        label = s.get("label") or f"s{i+1}"
        text = s.get("text")
        if text is None and s.get("text_path"):
            p = Path(s["text_path"])
            if not p.is_absolute():
                p = BASE / p
            text = p.read_text(encoding="utf-8", errors="replace")
        corpus[label] = text or ""
        m = {"domain": s.get("domain", ""), "type": "url"}
        if s.get("published"):
            m["timestamp"] = s["published"]
        meta[label] = m

    if len(corpus) < 2:
        # Burrows потребує ≥2 документів; одиничну подію оцінюємо без I_coord.
        only = next(iter(corpus.values()), "")
        tok = tokenise_corpus({"s1": only, "s2": only})
        mfw = find_mfw(tok, n=100, min_doc_freq=1)
        tf = build_tf_matrix(tok, mfw); z = zscore_matrix(tf); dist = burrows_delta(z)
        assess = build_dims_assessment(tokenised=tok, dist_df=dist, threshold=threshold,
                                       source_meta=meta, corpus=corpus,
                                       manifestation=manifestation)
        return assess["r_dims"], assess["grade"]["grade"]

    tok = tokenise_corpus(corpus)
    mfw = find_mfw(tok, n=100, min_doc_freq=2)
    if not mfw:
        mfw = find_mfw(tok, n=100, min_doc_freq=1)
    tf = build_tf_matrix(tok, mfw); z = zscore_matrix(tf); dist = burrows_delta(z)
    assess = build_dims_assessment(tokenised=tok, dist_df=dist, threshold=threshold,
                                   source_meta=meta, corpus=corpus,
                                   manifestation=manifestation)
    return assess["r_dims"], assess["grade"]["grade"]


# ─────────────────────────────────────────────────────────────────────────────
#  Метрики
# ─────────────────────────────────────────────────────────────────────────────
def quadratic_weighted_kappa(y_true: list[int], y_pred: list[int], k: int) -> float:
    """Зважена κ Коена (квадратичні ваги) для порядкової шкали з k рівнями."""
    n = len(y_true)
    if n == 0:
        return float("nan")
    O = np.zeros((k, k))
    for t, p in zip(y_true, y_pred):
        O[t, p] += 1
    W = np.array([[((i - j) ** 2) / ((k - 1) ** 2) for j in range(k)] for i in range(k)])
    act = np.bincount(y_true, minlength=k)
    pred = np.bincount(y_pred, minlength=k)
    E = np.outer(act, pred) / n
    denom = (W * E).sum()
    return float(1.0 - (W * O).sum() / denom) if denom > 0 else float("nan")


def youden_thresholds(r_dims: list[float], y_true_idx: list[int]) -> dict:
    """ROC/Youden-оптимальні пороги θ_k для кожної межі грейдів (≥ грейд k).
    Повертає {boundary_label: {"theta": ..., "auc": ..., "youden_j": ...}}."""
    try:
        from sklearn.metrics import roc_curve, roc_auc_score
    except Exception:
        return {}
    r = np.asarray(r_dims, dtype=float)
    y = np.asarray(y_true_idx, dtype=int)
    out = {}
    for k in range(1, len(GRADES)):           # межі: B|S=2? — k = індекс «≥ цей грейд»
        y_bin = (y >= k).astype(int)
        label = f"{GRADES[k-1]}|{GRADES[k]}"
        if y_bin.sum() == 0 or y_bin.sum() == len(y_bin):
            out[label] = {"theta": None, "auc": None, "note": "обидва класи не представлені"}
            continue
        fpr, tpr, thr = roc_curve(y_bin, r)
        j = tpr - fpr
        best = int(np.argmax(j))
        out[label] = {
            "theta": round(float(thr[best]), 4),
            "youden_j": round(float(j[best]), 4),
            "auc": round(float(roc_auc_score(y_bin, r)), 4),
        }
    return out


def confusion_matrix(y_true: list[int], y_pred: list[int], k: int) -> np.ndarray:
    M = np.zeros((k, k), dtype=int)
    for t, p in zip(y_true, y_pred):
        M[t, p] += 1
    return M


# ─────────────────────────────────────────────────────────────────────────────
#  Звіт
# ─────────────────────────────────────────────────────────────────────────────
def run(manifest: list[dict]) -> dict:
    rows = []
    for ev in manifest:
        grade_true = ev["grade"].strip()
        if grade_true not in GRADE_IDX:
            print(f"⚠ подія {ev.get('event_id')}: невідомий грейд '{grade_true}' — пропущено")
            continue
        r, grade_pred = _event_r_dims(ev.get("sources", []), ev.get("manifestation"))
        rows.append({"event_id": ev.get("event_id"), "r_dims": r,
                     "true": grade_true, "pred": grade_pred})

    if len(rows) < 2:
        print("⚠ замало розмічених подій для метрик (потрібно ≥ кілька десятків).")
        return {"n": len(rows), "rows": rows}

    yt = [GRADE_IDX[r["true"]] for r in rows]
    yp = [GRADE_IDX[r["pred"]] for r in rows]
    k = len(GRADES)
    n = len(rows)
    acc = sum(1 for a, b in zip(yt, yp) if a == b) / n
    adj = sum(1 for a, b in zip(yt, yp) if abs(a - b) <= 1) / n   # ±1 рівень
    kappa = quadratic_weighted_kappa(yt, yp, k)
    mae = float(np.mean([abs(a - b) for a, b in zip(yt, yp)]))
    cm = confusion_matrix(yt, yp, k)
    thr = youden_thresholds([r["r_dims"] for r in rows], yt)

    # ── Друк ──
    print(f"\n# Валідація DIMS на {n} розмічених подіях\n")
    print(f"- Точність (exact): **{acc:.3f}**")
    print(f"- Точність ±1 рівень: **{adj:.3f}**")
    print(f"- Зважена κ Коена (quadratic): **{kappa:.3f}**")
    print(f"- MAE (індекс грейду): **{mae:.3f}**")

    print("\n## Матриця плутанини (рядки — експерт, стовпці — DIMS)\n")
    print("| | " + " | ".join(GRADES) + " |")
    print("|" + "---|" * (k + 1))
    for i, g in enumerate(GRADES):
        print(f"| **{g}** | " + " | ".join(str(cm[i, j]) for j in range(k)) + " |")

    print("\n## ROC/Youden-калібровані пороги (data-driven) vs чинні (рівномірні)\n")
    print("| Межа | Чинний θ | ROC θ | AUC | Youden J |")
    print("|---|---|---|---|---|")
    for i, (label, info) in enumerate(thr.items()):
        cur = CURRENT_UPPERS[i] if i < len(CURRENT_UPPERS) else "—"
        if info.get("theta") is None:
            print(f"| {label} | {cur} | — | — | {info.get('note','')} |")
        else:
            print(f"| {label} | {cur} | {info['theta']} | {info['auc']} | {info['youden_j']} |")

    # ── Графіки ──
    fig, ax = plt.subplots(figsize=(5.5, 4.5))
    im = ax.imshow(cm, cmap="Blues")
    ax.set_xticks(range(k)); ax.set_xticklabels(GRADES)
    ax.set_yticks(range(k)); ax.set_yticklabels(GRADES)
    ax.set_xlabel("DIMS (передбачено)"); ax.set_ylabel("Експерт (істина)")
    ax.set_title(f"Матриця плутанини (n={n}, κ={kappa:.2f})")
    for i in range(k):
        for j in range(k):
            ax.text(j, i, cm[i, j], ha="center", va="center",
                    color="white" if cm[i, j] > cm.max() / 2 else "black")
    fig.colorbar(im, fraction=0.046); fig.tight_layout()
    fig.savefig(OUT / "validation_confusion.png", dpi=150); plt.close(fig)

    return {"n": n, "accuracy": acc, "accuracy_pm1": adj, "kappa_quad": kappa,
            "mae": mae, "confusion": cm.tolist(), "roc_thresholds": thr, "rows": rows}


# ─────────────────────────────────────────────────────────────────────────────
#  Selftest (синтетика ВИКЛЮЧНО для перевірки коду; НЕ валідація)
# ─────────────────────────────────────────────────────────────────────────────
def _selftest_manifest(n: int = 60) -> list[dict]:
    rng = random.Random(42)
    risky = ["ria.ru", "tass.ru", "pravda.ru", "sputniknews.ru"]
    legit = ["bbc.com", "suspilne.media", "ukrinform.ua", "nv.ua"]
    war = "війна ракета атака нато оборона загроза удар фронт армія ппо".split()
    peace = "переговори дипломатія компроміс саміт нейтралітет гарантії мир".split()
    man = []
    for i in range(n):
        # «висока загроза» — координовані ризикові джерела на воєнну тему
        high = rng.random() < 0.5
        pool = war if high else peace
        doms = risky if high else legit
        nsrc = rng.randint(2, 4)
        text = " ".join(rng.choice(pool + [f"w{j}" for j in range(6)]) for _ in range(120))
        srcs = [{"text": (text if high else
                          " ".join(rng.choice(pool + [f"u{i}{j}{x}" for j in range(20)]) for _ in range(120))),
                 "domain": rng.choice(doms)} for x in range(nsrc)]
        grade = rng.choice(["S", "SS", "SSS"] if high else ["F", "B", "S"])
        man.append({"event_id": f"syn{i:03d}", "grade": grade, "sources": srcs})
    return man


def main():
    ap = argparse.ArgumentParser(description="DIMS статистична валідація (Фаза 2)")
    ap.add_argument("--manifest", help="JSONL з розміченими подіями")
    ap.add_argument("--selftest", action="store_true",
                    help="згенерувати СИНТЕТИЧНІ дані для перевірки коду (НЕ валідація)")
    args = ap.parse_args()

    if args.selftest:
        print(">>> SELFTEST: синтетичні дані лише для перевірки працездатності коду.")
        print(">>> Це НЕ валідація методики — реальні висновки лише на розміченому корпусі.\n")
        report = run(_selftest_manifest())
    elif args.manifest:
        with open(args.manifest, encoding="utf-8") as f:
            manifest = [json.loads(line) for line in f if line.strip()
                        and not line.lstrip().startswith("//")]
        report = run(manifest)
    else:
        ap.error("вкажіть --manifest <файл.jsonl> або --selftest")

    print(f"\n✅ Звіт сформовано. Графік: {OUT/'validation_confusion.png'}")


if __name__ == "__main__":
    main()
