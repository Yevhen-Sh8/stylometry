#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/ias_service.py
===================
Безстанова (stateless) оцінка ОДНІЄЇ інформаційної події за методикою DIMS —
ядро для інтеграції з ІАС як окремого сервісу.

На відміну від вебзастосунку (спільний корпус SOURCES, аналіз у два кроки),
тут уся подія передається одним викликом:

    materials (тексти + метадані з модуля моніторингу ІАС)
      → дедуплікація технічних копій (SHA-256 + SimHash)
      → агрегація матеріалів за джерелом (канал / акаунт / домен)
      → Burrows' Delta + build_dims_assessment (формула R_DIMS НЕ змінюється)
      → рішення про сповіщення («ознаки скоординованої атаки»).

Агрегація за джерелом відповідає методичній рекомендації для коротких текстів
(Telegram, X, TikTok-описи): Δ-Burrows ненадійна на окремих постах, тому пости
одного каналу об'єднуються в один документ.

Технічні копії (copy-paste того самого тексту різними джерелами) НЕ подаються
до стилометрії (інакше Δ ≈ 0 штучно завищує I_coord), але фіксуються окремо
як самостійна, легко пояснювана ознака координації.
"""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations

import pandas as pd

from core.analysis import (
    DIMS_MANIFESTATION_TYPES,
    GRADE_THRESHOLDS,
    SHORT_TEXT_WARNING_TOKENS,
    build_dims_assessment,
    build_tf_matrix,
    burrows_delta,
    classify_severity,
    detect_corpus_languages,
    find_mfw,
    tokenise_corpus,
    zscore_matrix,
)
from core.monitoring_log import hamming, simhash, text_fingerprint

GRADES = [g for g, _, _ in GRADE_THRESHOLDS]          # F, B, S, SS, SSS
GRADE_RANK = {g: i for i, g in enumerate(GRADES)}

# Той самий поріг, що й у вебзастосунку (app._NEAR_DUP_HAMMING).
NEAR_DUP_HAMMING = 10

# Захисні ліміти на одну подію (захист від надмірних запитів).
MAX_MATERIALS_PER_EVENT = int(os.environ.get("DIMS_MAX_MATERIALS_PER_EVENT", "500"))
MAX_TEXT_CHARS = int(os.environ.get("DIMS_MAX_TEXT_CHARS", "200000"))

FEATURE_TYPES = {"word", "function", "char"}

# Походження тексту: написаний текст чи ШІ-транскрипт відео/аудіо.
# Транскрипт — усне мовлення після розпізнавання; його «стиль» частково
# відображає модальність (усна vs письмова мова) і систему розпізнавання,
# а не автора. Тому пари «транскрипт ↔ текст» позначаються окремо.
TEXT_ORIGINS = {"text", "transcript"}


def _transcript_platforms() -> set[str]:
    """Платформи, матеріали яких без явного text_origin вважаються транскриптами."""
    raw = os.environ.get("DIMS_TRANSCRIPT_PLATFORMS", "youtube,tiktok")
    return {p.strip().lower() for p in raw.split(",") if p.strip()}


class AssessmentError(ValueError):
    """Некоректні вхідні дані події (повідомлення придатне для показу клієнту)."""


# ─────────────────────────────────────────────────────────────────────────────
#  Правило сповіщення
# ─────────────────────────────────────────────────────────────────────────────

def alert_policy_from_env() -> dict:
    """Пороги сповіщення. ПРОВІЗОРНІ — підлягають калібруванню за результатами
    дослідної експлуатації (ROC/Youden, docs/validation_protocol_ua.md)."""
    min_grade = os.environ.get("DIMS_ALERT_MIN_GRADE", "S").strip().upper()
    if min_grade not in GRADE_RANK:
        min_grade = "S"
    return {
        "min_grade": min_grade,
        "min_coord": float(os.environ.get("DIMS_ALERT_MIN_COORD", "0.40")),
        "min_copy_sources": int(os.environ.get("DIMS_ALERT_MIN_COPY_SOURCES", "3")),
        # Операційне доповнення до методики: масове тиражування ідентичного
        # тексту сповіщає незалежно від грейду (після дедуплікації такі копії
        # не потрапляють у R_DIMS, тож грейд їх не відображає).
        "copy_paste_standalone": os.environ.get(
            "DIMS_ALERT_COPY_PASTE_STANDALONE", "1").strip() not in {"0", "false", "no"},
    }


def decide_alert(assessment: dict, n_flagged: int, copy_clusters: list[dict],
                 policy: dict | None = None) -> dict:
    """Чи є підстави сповістити про скоординовану інформаційну атаку.

    Тип «dims» (за методикою): грейд ≥ min_grade (за Наказом № 46 грейд S —
    «опрацювання + пропозиції щодо реагування») ТА принаймні одна ознака
    координації:
      • I_coord ≥ min_coord;
      • є пари джерел зі стилометричною близькістю Δ < θ;
      • той самий текст (технічна копія) поширили ≥ min_copy_sources джерел.

    Тип «copy_paste» (операційне доповнення, вимикається
    DIMS_ALERT_COPY_PASTE_STANDALONE=0): ідентичний текст поширили
    ≥ min_copy_sources джерел — незалежно від грейду.
    """
    policy = policy or alert_policy_from_env()
    grade = assessment["grade"]["grade"]
    i_coord = float(assessment["indicators"]["I_coord"])
    max_copy = max((c["n_sources"] for c in copy_clusters), default=0)

    reasons: list[str] = []
    if i_coord >= policy["min_coord"]:
        reasons.append(f"I_coord = {i_coord:.2f} ≥ {policy['min_coord']:.2f}")
    if n_flagged:
        reasons.append(f"стилометрично близьких пар джерел (Δ < θ): {n_flagged}")
    if max_copy >= policy["min_copy_sources"]:
        reasons.append(f"ідентичний текст поширили {max_copy} джерел(а)")

    grade_ok = GRADE_RANK[grade] >= GRADE_RANK[policy["min_grade"]]
    kinds = []
    if grade_ok and reasons:
        kinds.append("dims")
    if policy.get("copy_paste_standalone") and max_copy >= policy["min_copy_sources"]:
        kinds.append("copy_paste")
    return {
        "is_alert": bool(kinds),
        "kinds": kinds,
        "grade_ok": grade_ok,
        "coordination_signals": reasons,
        "policy": policy,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Підготовка матеріалів
# ─────────────────────────────────────────────────────────────────────────────

def _normalise_materials(materials) -> list[dict]:
    if not isinstance(materials, list) or not materials:
        raise AssessmentError("Поле materials має бути непорожнім списком.")
    if len(materials) > MAX_MATERIALS_PER_EVENT:
        raise AssessmentError(
            f"Забагато матеріалів у події ({len(materials)} > {MAX_MATERIALS_PER_EVENT})."
        )
    out = []
    transcript_platforms = _transcript_platforms()
    for i, m in enumerate(materials):
        if not isinstance(m, dict):
            raise AssessmentError(f"materials[{i}] має бути об'єктом.")
        text = m.get("text")
        if not isinstance(text, str) or not text.strip():
            continue  # порожні матеріали (лише відео без транскрипту тощо) пропускаємо
        source = str(m.get("source") or m.get("domain") or "").strip()
        if not source:
            raise AssessmentError(
                f"materials[{i}]: потрібне поле source (канал / акаунт / домен)."
            )
        platform = str(m.get("platform") or "").strip().lower()
        origin = str(m.get("text_origin") or "").strip().lower()
        if not origin:
            origin = "transcript" if platform in transcript_platforms else "text"
        if origin not in TEXT_ORIGINS:
            raise AssessmentError(
                f"materials[{i}]: text_origin має бути 'text' або 'transcript'."
            )
        out.append({
            "id": str(m.get("id") or f"m{i + 1}"),
            "source": source,
            "platform": platform,
            "text_origin": origin,
            "domain": str(m.get("domain") or "").strip(),
            "url": str(m.get("url") or "").strip(),
            "published_at": str(m.get("published_at") or "").strip(),
            "text": text[:MAX_TEXT_CHARS],
        })
    if not out:
        raise AssessmentError("У події немає жодного матеріалу з текстом.")
    return out


def _dedupe(materials: list[dict]) -> tuple[list[dict], list[dict]]:
    """Відсіює технічні копії. Повертає (унікальні матеріали, кластери копій).

    Кластер копій = група матеріалів із однаковим SHA-256 або SimHash-відстанню
    ≤ NEAR_DUP_HAMMING. Для звіту важливо, скільки РІЗНИХ джерел його поширили.
    """
    reps: list[dict] = []           # представники кластерів
    clusters: list[list[dict]] = []
    for m in sorted(materials, key=lambda x: x["published_at"] or "~"):
        fp = text_fingerprint(m["text"])
        sh = simhash(m["text"])
        for idx, rep in enumerate(reps):
            if fp == rep["_fp"] or hamming(sh, rep["_sh"]) <= NEAR_DUP_HAMMING:
                clusters[idx].append(m)
                break
        else:
            reps.append({**m, "_fp": fp, "_sh": sh})
            clusters.append([m])

    unique = [{k: v for k, v in r.items() if not k.startswith("_")} for r in reps]
    copy_clusters = []
    for members in clusters:
        if len(members) < 2:
            continue
        sources = sorted({x["source"] for x in members})
        copy_clusters.append({
            "first_material_id": members[0]["id"],
            "first_source": members[0]["source"],
            "material_ids": [x["id"] for x in members],
            "sources": sources,
            "n_sources": len(sources),
            "text_origins": sorted({x["text_origin"] for x in members}),
            "first_published_at": members[0]["published_at"] or None,
            "last_published_at": members[-1]["published_at"] or None,
        })
    copy_clusters.sort(key=lambda c: -c["n_sources"])
    return unique, copy_clusters


def _aggregate_by_source(materials: list[dict]) -> tuple[dict[str, str], dict[str, dict]]:
    """Об'єднує матеріали одного джерела в один документ для Burrows' Delta."""
    texts: dict[str, list[str]] = defaultdict(list)
    meta: dict[str, dict] = {}
    for m in sorted(materials, key=lambda x: x["published_at"] or "~"):
        src = m["source"]
        texts[src].append(m["text"])
        if src not in meta:
            meta[src] = {
                "domain": m["domain"] or src,
                "type": "url" if m["url"] else "text",
                "platform": m["platform"],
                "n_materials": 0,
                "_origins": set(),
            }
            if m["published_at"]:
                # Найраніша поява джерела в події — для S_time.
                meta[src]["timestamp"] = m["published_at"]
        meta[src]["n_materials"] += 1
        meta[src]["_origins"].add(m["text_origin"])
    for m in meta.values():
        origins = m.pop("_origins")
        m["text_origin"] = origins.pop() if len(origins) == 1 else "mixed"
    corpus = {src: "\n\n".join(parts) for src, parts in texts.items()}
    return corpus, meta


# ─────────────────────────────────────────────────────────────────────────────
#  Оцінка події
# ─────────────────────────────────────────────────────────────────────────────

def assess_event(
    materials: list[dict],
    *,
    event_id: str | None = None,
    manifestation: str | None = None,
    mfw_n: int = 100,
    threshold: float = 0.8,
    feature_type: str = "word",
    with_confidence: bool = True,
    alert_policy: dict | None = None,
) -> dict:
    """Повна DIMS-оцінка однієї події. Чиста функція: не пише файлів і стану."""
    if feature_type not in FEATURE_TYPES:
        raise AssessmentError("feature_type має бути 'word', 'function' або 'char'.")
    if not 20 <= int(mfw_n) <= 500:
        raise AssessmentError("mfw_n має бути в діапазоні 20-500.")
    if not 0.1 <= float(threshold) <= 2.0:
        raise AssessmentError("threshold має бути в діапазоні 0.1-2.0.")
    manifestation = (manifestation or "").strip().lower() or None
    if manifestation and manifestation not in DIMS_MANIFESTATION_TYPES:
        raise AssessmentError(
            "Невідомий manifestation. Допустимі: " + ", ".join(DIMS_MANIFESTATION_TYPES)
        )

    items = _normalise_materials(materials)
    unique, copy_clusters = _dedupe(items)
    corpus, meta = _aggregate_by_source(unique)

    warnings: list[str] = []
    coordination_assessable = len(corpus) >= 2
    flagged: list[dict] = []
    z = None

    if coordination_assessable:
        tok = tokenise_corpus(corpus, feature_type=feature_type)
        mfw = find_mfw(tok, n=int(mfw_n), min_doc_freq=2) or find_mfw(tok, n=int(mfw_n), min_doc_freq=1)
        if not mfw:
            raise AssessmentError("Тексти не мають спільних ознак для стилометрії.")
        z = zscore_matrix(build_tf_matrix(tok, mfw))
        dist = burrows_delta(z)
        for a, b in combinations(dist.index.tolist(), 2):
            d = float(dist.loc[a, b])
            if d < threshold:
                sev = classify_severity(d, threshold)
                oa, ob = meta[a]["text_origin"], meta[b]["text_origin"]
                flagged.append({"a": a, "b": b, "delta": round(d, 4),
                                "severity": sev["en"].lower(),
                                "cross_origin": oa != ob or "mixed" in (oa, ob)})
        flagged.sort(key=lambda p: p["delta"])
    else:
        # Одне джерело: Δ-Burrows неможлива; стилометрична частина I_coord = 0.
        warnings.append(
            "Після дедуплікації подію представляє одне джерело — стилометричну "
            "координацію оцінити неможливо (I_coord враховує лише інші фактори)."
        )
        only_label, only_text = next(iter(corpus.items()))
        tok = tokenise_corpus({only_label: only_text}, feature_type=feature_type)
        # Фіктивна матриця «далеких» документів: стилометрична складова = 0
        # (Δ = 0 між копією самого себе дало б хибну «координацію»).
        dist = pd.DataFrame([[0.0, 10.0], [10.0, 0.0]],
                            index=[only_label, "_"], columns=[only_label, "_"])

    assessment = build_dims_assessment(
        tokenised=tok, dist_df=dist, threshold=float(threshold),
        source_meta=meta, corpus=corpus, manifestation=manifestation,
        z=z if with_confidence else None,
    )

    short = [s for s, t in corpus.items() if len(t.split()) < SHORT_TEXT_WARNING_TOKENS]
    if short and coordination_assessable:
        warnings.append(
            f"{len(short)} із {len(corpus)} джерел мають < {SHORT_TEXT_WARNING_TOKENS} слів "
            "навіть після агрегації; Δ-Burrows на коротких текстах нестійка "
            "(Eder 2015: надійно від ~2500 слів) — орієнтуйтеся на довірчий інтервал."
        )
    origins = {m["text_origin"] for m in meta.values()}
    if coordination_assessable and len(origins) > 1:
        warnings.append(
            "Подія поєднує написані тексти та ШІ-транскрипти відео — стилометрична "
            "відстань між ними частково відображає різницю усної/письмової мови й "
            "розпізнавання; пари з cross_origin=true інтерпретуйте обережно."
        )
    lang = detect_corpus_languages(corpus)
    if lang.get("is_mixed"):
        warnings.append("Змішані системи письма в корпусі — стилометрія менш достовірна.")

    decision = decide_alert(assessment, len(flagged), copy_clusters, alert_policy)

    return {
        "event_id": event_id,
        "assessed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "r_dims": assessment["r_dims"],
        "grade": assessment["grade"],
        "indicators": assessment["indicators"],
        "weights": assessment["weights"],
        "confidence": assessment.get("confidence") or {},
        "alert": decision,
        "coordination": {
            "assessable": coordination_assessable,
            "flagged_pairs": flagged,
            "copy_clusters": copy_clusters,
        },
        "manifestation": assessment["manifestation"]["key"],
        "stats": {
            "n_materials": len(items),
            "n_unique_materials": len(unique),
            "n_sources": len(corpus),
            "sources": {s: m["n_materials"] for s, m in meta.items()},
            "text_origins": {s: m["text_origin"] for s, m in meta.items()},
        },
        "params": {"mfw_n": int(mfw_n), "threshold": float(threshold),
                   "feature_type": feature_type},
        "source_breakdown": assessment["source_breakdown"],
        "warnings": warnings,
        "methodology": "DIMS (Шерстюк Є.І., НУОУ); пороги сповіщення провізорні",
    }
