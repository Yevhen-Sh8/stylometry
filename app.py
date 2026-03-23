#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py  —  Flask web application for stylometric analysis
==========================================================

Run:
    source .venv/bin/activate
    python app.py
    # then open http://localhost:5000 in your browser

Routes
------
GET  /                  → main UI (index.html)
POST /api/upload        → upload files (multipart/form-data)
POST /api/add-url       → scrape article from URL
POST /api/add-text      → add pasted text with a custom label
POST /api/remove        → remove one source by label
POST /api/clear         → remove all sources
POST /api/analyze       → run full pipeline, store results
GET  /report            → render HTML supervisor report
GET  /output/<filename> → serve output files (CSV, PNG)
"""

from __future__ import annotations

import json
import os
import traceback
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from flask import (Flask, jsonify, render_template, request,
                   send_from_directory)

from core.extractors import (SUPPORTED_EXTENSIONS, clean_extracted_text,
                              extract_from_file)
from core.scraper import scrape_url_payload
from core.analysis import run_pipeline

# ─────────────────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB upload limit

BASE_DIR   = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
CLEAN_DIR  = OUTPUT_DIR / "clean_texts"

# In-memory source store  {label: clean_text}
# For a local single-user app this is sufficient.
SOURCES: dict[str, str] = {}
SOURCE_META: dict[str, dict] = {}

# Last analysis results (for /report)
LAST_RESULTS: dict = {}


# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _save_clean_text(label: str, text: str) -> None:
    """Persist a clean-text version to output/clean_texts/<label>.txt"""
    CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    safe_label = "".join(c if c.isalnum() or c in "-_ " else "_" for c in label)
    (CLEAN_DIR / f"{safe_label}.txt").write_text(text, encoding="utf-8")


def _safe_output_name(label: str) -> str:
    return "".join(c if c.isalnum() or c in "-_ " else "_" for c in label)


def _token_count(text: str) -> int:
    """Rough token count: alphabetic words of length ≥ 2."""
    return sum(1 for t in text.lower().split() if t.isalpha() and len(t) > 1)


def _derive_display_title(text: str, fallback: str, preferred: str = "") -> str:
    if preferred:
        return preferred[:180]

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if lines:
        first = lines[0]
        if len(first.split()) >= 4:
            return first[:180]

    words = text.replace("\n", " ").split()
    if words:
        return " ".join(words[:14])[:180]
    return fallback[:180]


def _derive_title_from_html(html: str, fallback: str = "") -> str:
    lower = html.lower()
    start = lower.find("<title>")
    end = lower.find("</title>")
    if start != -1 and end != -1 and end > start:
        title = html[start + 7:end].strip()
        title = " ".join(title.split())
        if title:
            return title[:180]
    return fallback[:180]


def _build_source_meta(
    label: str,
    text: str,
    source_type: str = "",
    *,
    display_title: str = "",
    original_name: str = "",
    url: str = "",
) -> dict:
    tokens = _token_count(text)
    domain = urlparse(url).netloc.replace("www.", "") if url else ""
    output_name = _safe_output_name(label)
    local_text_url = f"/output/clean_texts/{output_name}.txt"
    return {
        "label": label,
        "display_title": _derive_display_title(text, fallback=label, preferred=display_title),
        "tokens": tokens,
        "type": source_type,
        "preview": text[:220].replace("\n", " "),
        "warn": tokens < 500,
        "url": url,
        "domain": domain,
        "original_name": original_name,
        "local_text_url": local_text_url,
    }


def _register_source(
    label: str,
    clean_text: str,
    source_type: str = "",
    *,
    display_title: str = "",
    original_name: str = "",
    url: str = "",
) -> dict:
    SOURCES[label] = clean_text
    _save_clean_text(label, clean_text)
    meta = _build_source_meta(
        label,
        clean_text,
        source_type,
        display_title=display_title,
        original_name=original_name,
        url=url,
    )
    SOURCE_META[label] = meta
    return meta


def _source_lookup(label: str) -> dict:
    meta = SOURCE_META.get(label)
    if meta:
        return meta
    text = SOURCES.get(label, "")
    return _build_source_meta(label, text)


def _source_breakdown_rows(
    source_breakdown: dict[str, float],
    source_details: dict[str, dict] | None = None,
) -> list[dict]:
    rows = []
    for label, score in sorted(source_breakdown.items(), key=lambda item: item[1], reverse=True):
        source = _source_lookup(label)
        details = (source_details or {}).get(label, {})
        rows.append({
            "label": label,
            "score": score,
            "source": source,
            "components": details,
        })
    return rows


def _err(msg: str, code: int = 400):
    return jsonify({"ok": False, "error": msg}), code


def _ok(**kwargs):
    return jsonify({"ok": True, **kwargs})


def _parse_analysis_params(data: dict) -> tuple[int, float]:
    try:
        mfw_n = int(data.get("mfw", 100))
        threshold = float(data.get("threshold", 0.8))
    except (TypeError, ValueError) as exc:
        raise ValueError("Некоректні параметри аналізу.") from exc

    if not 20 <= mfw_n <= 500:
        raise ValueError("Параметр MFW має бути в діапазоні 20-500.")
    if not 0.1 <= threshold <= 2.0:
        raise ValueError("Поріг Delta має бути в діапазоні 0.1-2.0.")
    return mfw_n, threshold


# ─────────────────────────────────────────────────────────────────────────────
#  ROUTES
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/upload")
def upload():
    """
    Accept one or more files (multipart/form-data key: 'files').
    Extract, clean, save to clean_texts/, add to SOURCES.
    """
    files = request.files.getlist("files")
    if not files:
        return _err("Файли не знайдено у запиті.")

    added   = []
    skipped = []

    for f in files:
        if not f.filename:
            continue

        fpath = Path(f.filename)
        ext   = fpath.suffix.lower()

        if ext not in SUPPORTED_EXTENSIONS:
            skipped.append(f.filename)
            continue

        # Save temp file
        tmp = OUTPUT_DIR / f"_tmp_{fpath.name}"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        f.save(tmp)

        try:
            raw   = extract_from_file(tmp)
            clean = clean_extracted_text(raw)
        except Exception as exc:
            skipped.append(f"{f.filename} ({exc})")
            tmp.unlink(missing_ok=True)
            continue
        finally:
            tmp.unlink(missing_ok=True)

        if not clean.strip():
            skipped.append(f"{f.filename} (порожній текст після очищення)")
            continue

        label = fpath.stem
        # De-duplicate labels
        base, n = label, 1
        while label in SOURCES:
            label = f"{base}_{n}"
            n += 1

        added.append(
            _register_source(
                label,
                clean,
                ext.lstrip("."),
                display_title=fpath.stem,
                original_name=f.filename,
            )
        )

    return _ok(added=added, skipped=skipped)


@app.post("/api/add-url")
def add_url():
    """Scrape a URL and add its article text as a source."""
    data  = request.get_json(silent=True) or {}
    url   = (data.get("url") or "").strip()
    label = (data.get("label") or "").strip()

    if not url:
        return _err("URL не вказано.")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        payload = scrape_url_payload(url)
        clean = payload["text"]
    except (ValueError, RuntimeError) as exc:
        return _err(str(exc))
    except Exception as exc:
        return _err(f"Помилка при завантаженні: {exc}")

    if not label:
        label = payload["domain"] or urlparse(url).netloc.replace("www.", "")

    base, n = label, 1
    while label in SOURCES:
        label = f"{base}_{n}"
        n += 1

    return _ok(source=_register_source(
        label,
        clean,
        "url",
        display_title=payload["title"] or label,
        url=payload["url"],
    ))


@app.post("/api/add-text")
def add_text():
    """Add a pasted / typed text block with a custom label."""
    data  = request.get_json(silent=True) or {}
    label = (data.get("label") or "").strip()
    text  = (data.get("text")  or "").strip()

    if not text:
        return _err("Текст не може бути порожнім.")
    if not label:
        label = f"текст_{len(SOURCES) + 1}"

    clean = clean_extracted_text(text)
    if not clean:
        return _err("Текст порожній після очищення.")

    base, n = label, 1
    while label in SOURCES:
        label = f"{base}_{n}"
        n += 1

    return _ok(source=_register_source(
        label,
        clean,
        "text",
        display_title=label,
    ))


@app.post("/api/add-html")
def add_html():
    """Add a raw HTML page manually and clean it into analysable text."""
    data = request.get_json(silent=True) or {}
    label = (data.get("label") or "").strip()
    html = (data.get("html") or "").strip()
    url = (data.get("url") or "").strip()

    if not html:
        return _err("HTML не може бути порожнім.")
    if url and not url.startswith(("http://", "https://")):
        url = "https://" + url

    clean = clean_extracted_text(html)
    if not clean:
        return _err("Після очищення HTML не містить придатного тексту.")

    html_title = _derive_title_from_html(html)
    if not label:
        label = html_title or (urlparse(url).netloc.replace("www.", "") if url else f"html_{len(SOURCES) + 1}")

    base, n = label, 1
    while label in SOURCES:
        label = f"{base}_{n}"
        n += 1

    return _ok(source=_register_source(
        label,
        clean,
        "html",
        display_title=html_title or label,
        url=url,
    ))


@app.post("/api/remove")
def remove_source():
    data  = request.get_json(silent=True) or {}
    label = data.get("label", "")
    SOURCES.pop(label, None)
    SOURCE_META.pop(label, None)
    return _ok(removed=label)


@app.post("/api/clear")
def clear_sources():
    global LAST_RESULTS
    SOURCES.clear()
    SOURCE_META.clear()
    LAST_RESULTS = {}
    return _ok()


@app.get("/api/sources")
def list_sources():
    return _ok(sources=[
        _source_lookup(lbl) for lbl in SOURCES
    ])


@app.post("/api/analyze")
def analyze():
    """Run the full Burrows' Delta pipeline on the current SOURCES."""
    global LAST_RESULTS

    if len(SOURCES) < 2:
        return _err("Потрібно щонайменше 2 джерела для аналізу.")

    data = request.get_json(silent=True) or {}
    try:
        mfw_n, threshold = _parse_analysis_params(data)
    except ValueError as exc:
        return _err(str(exc))

    try:
        results = run_pipeline(
            corpus=dict(SOURCES),
            output_dir=OUTPUT_DIR,
            mfw_n=mfw_n,
            threshold=threshold,
            source_meta=dict(SOURCE_META),
        )
    except Exception as exc:
        traceback.print_exc()
        return _err(f"Помилка аналізу: {exc}", code=500)

    # Store for /report
    LAST_RESULTS = results
    LAST_RESULTS["timestamp"] = datetime.now().strftime("%d.%m.%Y %H:%M")

    # Build JSON-serialisable summary
    flagged_summary = [
        {
            "a": a, "b": b,
            "a_meta": _source_lookup(a),
            "b_meta": _source_lookup(b),
            "delta": round(d, 4),
            "severity": sev,
        }
        for a, b, d, sev in results["flagged"]
    ]
    top5 = [
        {
            "a": a,
            "b": b,
            "a_meta": _source_lookup(a),
            "b_meta": _source_lookup(b),
            "delta": round(d, 4),
        }
        for a, b, d in results["all_pairs"][:5]
    ]

    return _ok(
        n_sources=results["n_docs"],
        n_pairs=results["n_pairs"],
        n_flagged=len(results["flagged"]),
        flagged=flagged_summary,
        top5_similar=top5,
        delta_stats=results["delta_stats"],
        dims_assessment=results["dims_assessment"],
        source_breakdown=_source_breakdown_rows(
            results["dims_assessment"].get("source_breakdown", {}),
            results["dims_assessment"].get("source_details", {}),
        ),
        mfw_n=mfw_n,
        threshold=threshold,
    )


@app.get("/report")
def report():
    """Render the HTML supervisor report with embedded charts."""
    if not LAST_RESULTS:
        return "<h2>Спочатку запустіть аналіз.</h2>", 400

    r = LAST_RESULTS

    # Distance matrix as list-of-dicts for Jinja2
    dist_df = r["dist_df"]
    labels  = dist_df.index.tolist()
    matrix_rows = [
        {
            "label": lbl,
            "source": _source_lookup(lbl),
            "cells": [
                {
                    "col": col,
                    "col_source": _source_lookup(col),
                    "val": round(dist_df.loc[lbl, col], 4),
                }
                for col in labels
            ],
        }
        for lbl in labels
    ]

    # Token stats
    token_stats = [
        {
            "label": lbl,
            "source": _source_lookup(lbl),
            "tokens": len(r["tokenised"][lbl]),
            "warn": len(r["tokenised"][lbl]) < 500,
        }
        for lbl in labels
    ]

    # Top-20 MFW
    mfw_table = [
        {"rank": i + 1, "word": w, "freq": r["global_counts"][w]}
        for i, w in enumerate(r["mfw"][:20])
    ]
    source_aliases = [
        {
            "alias": f"S{i + 1}",
            "source": _source_lookup(lbl),
        }
        for i, lbl in enumerate(labels)
    ]

    flagged_details = [
        {
            "a": a,
            "b": b,
            "a_source": _source_lookup(a),
            "b_source": _source_lookup(b),
            "delta": delta,
            "severity": sev,
        }
        for a, b, delta, sev in r["flagged"]
    ]

    # Max delta for heatmap scaling
    max_delta = r["delta_stats"]["max"] or 1.0

    return render_template(
        "report.html",
        timestamp=r.get("timestamp", ""),
        n_docs=r["n_docs"],
        n_pairs=r["n_pairs"],
        n_flagged=len(r["flagged"]),
        mfw_n=r["mfw_n"],
        threshold=r["threshold"],
        flagged=flagged_details,
        source_lookup={lbl: _source_lookup(lbl) for lbl in labels},
        all_pairs=r["all_pairs"][:10],
        delta_stats=r["delta_stats"],
        matrix_rows=matrix_rows,
        labels=labels,
        token_stats=token_stats,
        mfw_table=mfw_table,
        source_aliases=source_aliases,
        source_breakdown_rows=_source_breakdown_rows(
            r["dims_assessment"].get("source_breakdown", {}),
            r["dims_assessment"].get("source_details", {}),
        ),
        max_delta=max_delta,
        dims_assessment=r["dims_assessment"],
        dendrogram_b64=r.get("dendrogram_b64", ""),
        pca_b64=r.get("pca_b64", ""),
    )


@app.get("/output/<path:filename>")
def output_file(filename):
    # Prevent path traversal: resolve and verify the file is inside OUTPUT_DIR
    resolved = (OUTPUT_DIR / filename).resolve()
    if not str(resolved).startswith(str(OUTPUT_DIR.resolve())):
        return _err("Недопустимий шлях.", 403)
    return send_from_directory(OUTPUT_DIR, filename)


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 60)
    print("  DIMS — Моніторинг інформаційних загроз")
    print("  Відкрийте у браузері: http://localhost:5001")
    print("=" * 60)
    app.run(debug=os.environ.get("FLASK_DEBUG", "0") == "1", port=5001)
