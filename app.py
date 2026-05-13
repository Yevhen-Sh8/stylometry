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
from core.analysis import (DIMS_MANIFESTATION_TYPES, detect_script,
                            run_pipeline)
from core.monitoring_log import (append_record, find_duplicate, load_records,
                                  text_fingerprint)
from core.monitoring_forms import build_daily_monitoring_form

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
    extractor: str = "",
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

    # Запис у протокол моніторингу (Результат №1, логічне завершення).
    try:
        fingerprint = text_fingerprint(clean_text)
        meta["fingerprint"] = fingerprint
        append_record(
            label=label,
            source_type=source_type,
            url=url,
            domain=meta.get("domain", ""),
            extractor=extractor,
            language=detect_script(clean_text),
            words=meta.get("tokens", 0),
            fingerprint=fingerprint,
            original_name=original_name,
            display_title=meta.get("display_title", ""),
        )
    except Exception:
        # Протокол не повинен переривати імпорт джерела.
        traceback.print_exc()
    return meta


def _check_duplicate(clean_text: str) -> dict | None:
    """Повертає попередній запис протоколу з тим самим відбитком, якщо є."""
    if not clean_text:
        return None
    fingerprint = text_fingerprint(clean_text)
    record = find_duplicate(fingerprint)
    if not record:
        return None
    # Запис вважається дублікатом лише тоді, коли відповідне джерело
    # досі присутнє у поточній сесії (тобто не було видалене).
    previous_label = record.get("label")
    if previous_label and previous_label in SOURCES:
        return record
    return None


def _source_lookup(label: str) -> dict:
    meta = SOURCE_META.get(label)
    if meta:
        out = dict(meta)
    else:
        out = _build_source_meta(label, SOURCES.get(label, ""))
    keys = list(SOURCES.keys())
    out["alias"] = f"S{keys.index(label) + 1}" if label in keys else ""
    return out


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


def _parse_analysis_params(data: dict) -> tuple[int, float, int, str, int, str]:
    try:
        mfw_n = int(data.get("mfw", 100))
        threshold = float(data.get("threshold", 0.8))
        min_doc_freq = int(data.get("min_doc_freq", 2))
        feature_type = str(data.get("feature_type", "word")).lower()
        char_n = int(data.get("char_n", 3))
        projection_method = str(data.get("projection", "pca")).lower()
    except (TypeError, ValueError) as exc:
        raise ValueError("Некоректні параметри аналізу.") from exc

    if not 20 <= mfw_n <= 500:
        raise ValueError("Параметр MFW має бути в діапазоні 20-500.")
    if not 0.1 <= threshold <= 2.0:
        raise ValueError("Поріг Delta має бути в діапазоні 0.1-2.0.")
    if not 1 <= min_doc_freq <= 20:
        raise ValueError("Параметр culling (min_doc_freq) має бути 1-20.")
    if feature_type not in {"word", "char"}:
        raise ValueError("feature_type має бути 'word' або 'char'.")
    if not 2 <= char_n <= 6:
        raise ValueError("char_n має бути в діапазоні 2-6.")
    if projection_method not in {"pca", "mds", "tsne"}:
        raise ValueError("projection має бути 'pca', 'mds' або 'tsne'.")
    return mfw_n, threshold, min_doc_freq, feature_type, char_n, projection_method


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

        duplicate = _check_duplicate(clean)
        if duplicate:
            skipped.append(
                f"{f.filename} (дублікат джерела «{duplicate.get('label')}» — "
                "ідентичний текст уже присутній у корпусі)"
            )
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
                extractor="extract_from_file",
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

    duplicate = _check_duplicate(clean)
    if duplicate:
        return _err(
            "Текст цієї сторінки ідентичний джерелу "
            f"«{duplicate.get('label')}», яке вже присутнє у корпусі. "
            "Повторний імпорт було заблоковано для недопущення "
            "штучного завищення координаційного індикатора."
        )

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
        extractor="scrape_url_payload",
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

    duplicate = _check_duplicate(clean)
    if duplicate:
        return _err(
            "Введений текст є дублікатом джерела "
            f"«{duplicate.get('label')}», уже присутнього у корпусі."
        )

    base, n = label, 1
    while label in SOURCES:
        label = f"{base}_{n}"
        n += 1

    return _ok(source=_register_source(
        label,
        clean,
        "text",
        display_title=label,
        extractor="manual_paste",
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

    duplicate = _check_duplicate(clean)
    if duplicate:
        return _err(
            "Вміст HTML ідентичний джерелу "
            f"«{duplicate.get('label')}», уже присутньому у корпусі."
        )

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
        extractor="manual_html",
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


@app.get("/api/manifestation-types")
def manifestation_types():
    """Повертає перелік видів прояву DIMs відповідно до Методики НУЗРКС МОУ
    № 46 від 28.11.2022 (розділ 1). Виклик інтерфейсом для формування
    випадаючого списку при запуску аналізу."""
    return _ok(
        types=[
            {"key": key, "label": label}
            for key, label in DIMS_MANIFESTATION_TYPES.items()
        ],
    )


@app.get("/api/monitoring-log")
def monitoring_log_view():
    """Повертає повний протокол моніторингу (JSON Lines → JSON масив).

    Використовується для експорту протоколу в інтерфейсі та формування
    додатків до дисертації відповідно до вимог Методики НУЗРКС МОУ
    № 46 від 28.11.2022.
    """
    records = load_records()
    return _ok(records=records, count=len(records))


# ─────────────────────────────────────────────────────────────────────────────
#  NEWS SEARCH (Google News RSS, multi-language)
# ─────────────────────────────────────────────────────────────────────────────
_GN_LOCALES = {
    "uk": {"hl": "uk",    "gl": "UA", "ceid": "UA:uk"},
    "ru": {"hl": "ru",    "gl": "RU", "ceid": "RU:ru"},
    "en": {"hl": "en-US", "gl": "US", "ceid": "US:en"},
    "de": {"hl": "de",    "gl": "DE", "ceid": "DE:de"},
    "fr": {"hl": "fr",    "gl": "FR", "ceid": "FR:fr"},
}


def _resolve_gn_url(gn_url: str, session) -> str | None:
    """Decode Google News redirect URL → real article URL via batch-execute."""
    import re, json

    m = re.search(r'/articles/([^?/]+)', gn_url)
    if not m:
        return None
    article_id = m.group(1)

    try:
        page = session.get(gn_url, timeout=10,
                           headers={"User-Agent": "Mozilla/5.0"})
        html = page.text
    except Exception:
        return None

    sig_m = re.search(r'data-n-a-sg="([^"]+)"', html)
    ts_m  = re.search(r'data-n-a-ts="(\d+)"', html)
    if not sig_m or not ts_m:
        return None
    sig, ts = sig_m.group(1), ts_m.group(1)

    inner = json.dumps([
        "garturlreq",
        [["X","X",["X","X"],None,None,1,1,"US:en",None,1,None,None,None,None,None,0,1],
         "X","X",1,[1,1,1],1,1,None,0,0,None,0],
        article_id, int(ts), sig
    ])
    outer = json.dumps([[["Fbv4je", inner, None, "generic"]]])
    try:
        resp = session.post(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            data={"f.req": outer},
            headers={"User-Agent": "Mozilla/5.0",
                     "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
            timeout=10,
        )
    except Exception:
        return None

    url_m = re.search(r'garturlres\\?",\\?"(https?://[^"\\]+)', resp.text)
    if url_m:
        return url_m.group(1)
    return None


def _fetch_google_news(query: str, lang: str, limit: int = 15) -> list[dict]:
    import urllib.parse
    import xml.etree.ElementTree as ET
    import requests as _rq

    loc = _GN_LOCALES.get(lang)
    if not loc:
        return []
    url = (
        "https://news.google.com/rss/search?"
        + urllib.parse.urlencode({
            "q": query,
            **loc,
        })
    )
    try:
        resp = _rq.get(
            url,
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0 (DIMS research tool)"},
        )
        resp.raise_for_status()
    except Exception:
        return []

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        return []

    raw_items = []
    for item in list(root.iterfind(".//item"))[:limit]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        desc = (item.findtext("description") or "").strip()
        source_el = item.find("source")
        source_name = source_el.text.strip() if source_el is not None and source_el.text else ""
        if title and link:
            raw_items.append((title, link, pub, desc, source_name))

    from concurrent.futures import ThreadPoolExecutor

    items: list[dict] = []
    with _rq.Session() as session:
        session.headers.update({"User-Agent": "Mozilla/5.0 (DIMS)"})

        def _build(row):
            title, link, pub, desc, src = row
            real = _resolve_gn_url(link, session) or link
            return {
                "title": title,
                "url": real,
                "source": src,
                "published": pub,
                "snippet": desc,
                "lang": lang,
            }

        with ThreadPoolExecutor(max_workers=8) as ex:
            for entry in ex.map(_build, raw_items):
                items.append(entry)
    return items


@app.post("/api/evidence")
def evidence():
    """Return token-level evidence for a flagged pair (TabooTrigger / EvidenceDrawer).

    Request JSON:
        a_label     – label of source A
        b_label     – label of source B
        mfw_n       – (optional) number of MFW to compare; default 200
        feature_type– (optional) "word" | "char"; default "word"
        char_n      – (optional) char-n-gram size; default 3

    Response JSON:
        shared_tokens  – [{token, freq_a, freq_b}] sorted by freq_a+freq_b desc
        a_top_tokens   – [{token, freq_a}] distinctive to A (top 30)
        b_top_tokens   – [{token, freq_b}] distinctive to B (top 30)
        overlap_pct    – % of A's MFW that appear in B's top tokens
        a_preview      – first 600 chars of source A text
        b_preview      – first 600 chars of source B text
        feature_type   – echoed
        mfw_n          – echoed
        char_n         – echoed
    """
    from collections import Counter
    from core.analysis import tokenise_corpus, find_mfw, clean_and_tokenise, char_ngrams

    data = request.get_json(silent=True) or {}
    a_label = (data.get("a_label") or "").strip()
    b_label = (data.get("b_label") or "").strip()

    if not a_label or not b_label:
        return _err("a_label та b_label є обов'язковими.")
    if a_label not in SOURCES:
        return _err(f"Джерело «{a_label}» не знайдено у корпусі.")
    if b_label not in SOURCES:
        return _err(f"Джерело «{b_label}» не знайдено у корпусі.")

    mfw_n        = min(int(data.get("mfw_n", 200)), 400)
    feature_type = str(data.get("feature_type", "word")).lower()
    char_n       = int(data.get("char_n", 3))
    if feature_type not in {"word", "char"}:
        feature_type = "word"

    text_a = SOURCES[a_label]
    text_b = SOURCES[b_label]

    # Tokenise both texts
    mini_corpus = {a_label: text_a, b_label: text_b}
    tokenised = tokenise_corpus(mini_corpus, feature_type=feature_type, char_n=char_n)
    tokens_a  = tokenised[a_label]
    tokens_b  = tokenised[b_label]

    counter_a = Counter(tokens_a)
    counter_b = Counter(tokens_b)

    # MFW of the pair (no culling — only 2 docs)
    mfw_list = find_mfw(tokenised, n=mfw_n, min_doc_freq=1)
    mfw_set  = set(mfw_list)

    # Shared: in both MFW lists
    top_a_set = {t for t, _ in counter_a.most_common(mfw_n)}
    top_b_set = {t for t, _ in counter_b.most_common(mfw_n)}
    shared_set = top_a_set & top_b_set

    shared_tokens = sorted(
        [{"token": t, "freq_a": counter_a[t], "freq_b": counter_b[t]}
         for t in shared_set],
        key=lambda x: x["freq_a"] + x["freq_b"],
        reverse=True,
    )[:60]  # cap at 60 for readability

    # Distinctive A: in top-A but NOT in top-B
    a_only = sorted(
        [{"token": t, "freq_a": counter_a[t]}
         for t in (top_a_set - top_b_set)],
        key=lambda x: x["freq_a"],
        reverse=True,
    )[:30]

    # Distinctive B: in top-B but NOT in top-A
    b_only = sorted(
        [{"token": t, "freq_b": counter_b[t]}
         for t in (top_b_set - top_a_set)],
        key=lambda x: x["freq_b"],
        reverse=True,
    )[:30]

    # Overlap %: fraction of A's MFW that appear at all in B
    overlap_pct = (len(shared_set) / max(len(top_a_set), 1)) * 100

    return _ok(
        shared_tokens=shared_tokens,
        a_top_tokens=a_only,
        b_top_tokens=b_only,
        overlap_pct=round(overlap_pct, 1),
        a_preview=text_a[:600].replace("\n", " "),
        b_preview=text_b[:600].replace("\n", " "),
        feature_type=feature_type,
        mfw_n=mfw_n,
        char_n=char_n,
    )


@app.post("/api/fetch-rss")
def fetch_rss():
    """Отримує та парсить RSS/Atom-стрічку. Повертає список статей для імпорту."""
    import xml.etree.ElementTree as ET
    import requests as _req

    data = request.get_json(silent=True) or {}
    feed_url = (data.get("url") or "").strip()
    limit = min(int(data.get("limit") or 30), 50)

    if not feed_url:
        return _err("URL RSS-стрічки порожній.")
    try:
        feed_url = _assert_public_url(feed_url)
    except RuntimeError as exc:
        return _err(str(exc))

    try:
        r = _req.get(feed_url, timeout=20,
                     headers={"User-Agent": "Mozilla/5.0 (DIMS research tool)", "Accept": "application/rss+xml,application/atom+xml,*/*"})
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as exc:
        return _err(f"Не вдалося отримати RSS: {exc}")

    items = []
    _NS = {"atom": "http://www.w3.org/2005/Atom",
           "media": "http://search.yahoo.com/mrss/"}

    def _txt(el, *tags):
        for t in tags:
            v = el.findtext(t, namespaces=_NS)
            if v: return v.strip()
        return ""

    # RSS 2.0
    for item in root.findall(".//item")[:limit]:
        link = _txt(item, "link")
        if not link:
            continue
        title   = _txt(item, "title") or link
        snippet = _txt(item, "description")[:300]
        pub     = _txt(item, "pubDate")
        domain  = urlparse(link).netloc.replace("www.", "")
        items.append({"title": title, "url": link, "snippet": snippet,
                      "published": pub, "source": domain, "lang": ""})

    # Atom (якщо RSS-елементів не було)
    if not items:
        for entry in root.findall("atom:entry", _NS)[:limit]:
            link_el = entry.find("atom:link[@rel='alternate']", _NS) or entry.find("atom:link", _NS)
            link = link_el.get("href", "") if link_el is not None else ""
            if not link:
                continue
            title   = _txt(entry, "atom:title")  or link
            snippet = _txt(entry, "atom:summary", "atom:content")[:300]
            pub     = _txt(entry, "atom:published", "atom:updated")
            domain  = urlparse(link).netloc.replace("www.", "")
            items.append({"title": title, "url": link, "snippet": snippet,
                          "published": pub, "source": domain, "lang": ""})

    if not items:
        return _err("У стрічці не знайдено жодної статті. Перевірте URL і формат (RSS 2.0 / Atom).")
    return _ok(results=items, feed_url=feed_url, count=len(items))


@app.post("/api/fetch-telegram")
def fetch_telegram():
    """Scrape публічного Telegram-каналу через t.me/s/<channel>."""
    import requests as _req
    from bs4 import BeautifulSoup

    data = request.get_json(silent=True) or {}
    raw = (data.get("channel") or "").strip()
    limit = min(int(data.get("limit") or 20), 40)

    if not raw:
        return _err("Назва каналу порожня.")

    # Приводимо до просто назви каналу
    import re as _re
    channel = _re.sub(r'^(https?://)?(t\.me/s?/|telegram\.me/)?@?', '', raw).strip("/").split("/")[0]
    if not channel:
        return _err("Не вдалося розпізнати назву каналу.")

    url = f"https://t.me/s/{channel}"
    try:
        r = _req.get(url, timeout=25, headers={
            "User-Agent": "Mozilla/5.0 (DIMS research tool)",
            "Accept-Language": "ru,uk;q=0.9,de;q=0.8,fr;q=0.7,en;q=0.6",
        })
        r.raise_for_status()
    except Exception as exc:
        return _err(f"Не вдалося завантажити канал @{channel}: {exc}")

    soup = BeautifulSoup(r.text, "html.parser")
    posts = []
    for wrap in soup.select(".tgme_widget_message_wrap")[:limit]:
        text_el = wrap.select_one(".tgme_widget_message_text")
        if not text_el:
            continue
        text = text_el.get_text(separator="\n").strip()
        # Стрипаємо типові boilerplate-footer'и (Підписатись, шаблонні посилання тощо)
        import re as _re2
        text = _re2.sub(
            r'(?i)(подписат[ьься]+\s+на\s+\S+.*|підписат[ьися]+\s+на\s+\S+.*'
            r'|\bтг\b.*|\bзеркало\b.*|\bmax\b\s*$)',
            '', text, flags=_re2.MULTILINE
        ).strip()
        if len(text.split()) < 8:
            continue

        date_el = wrap.select_one("a.tgme_widget_message_date")
        date    = date_el.get("datetime", "") if date_el else ""
        msg_url = date_el.get("href", f"https://t.me/{channel}") if date_el else f"https://t.me/{channel}"

        posts.append({
            "title":     text[:120].replace("\n", " ") + ("…" if len(text) > 120 else ""),
            "full_text": text,
            "url":       msg_url,
            "published": date,
            "source":    f"@{channel}",
            "lang":      "",
        })

    if not posts:
        return _err(
            f"Повідомлень не знайдено у @{channel}. "
            "Переконайтеся що канал публічний і існує (t.me/s/<назва>)."
        )
    return _ok(results=posts, channel=channel, count=len(posts))


@app.post("/api/search-news")
def search_news():
    """Multi-language news search via Google News RSS."""
    from concurrent.futures import ThreadPoolExecutor

    data = request.get_json(silent=True) or {}
    query = (data.get("query") or "").strip()
    langs = data.get("languages") or ["uk", "ru", "en"]
    limit = int(data.get("limit") or 15)

    if not query:
        return _err("Пошуковий запит порожній.")
    langs = [l for l in langs if l in _GN_LOCALES]
    if not langs:
        return _err("Не обрано жодної мови пошуку.")

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=len(langs)) as ex:
        futures = {ex.submit(_fetch_google_news, query, l, limit): l for l in langs}
        for fut in futures:
            try:
                results.extend(fut.result() or [])
            except Exception:
                pass

    seen = set()
    deduped = []
    for r in results:
        key = r["url"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)

    return _ok(results=deduped, query=query, languages=langs, count=len(deduped))


@app.post("/api/analyze")
def analyze():
    """Run the full Burrows' Delta pipeline on the current SOURCES."""
    global LAST_RESULTS

    if len(SOURCES) < 2:
        return _err("Потрібно щонайменше 2 джерела для аналізу.")

    data = request.get_json(silent=True) or {}
    try:
        mfw_n, threshold, min_doc_freq, feature_type, char_n, projection_method = (
            _parse_analysis_params(data)
        )
    except ValueError as exc:
        return _err(str(exc))

    manifestation_raw = (data.get("manifestation") or "").strip().lower()
    manifestation = manifestation_raw if manifestation_raw in DIMS_MANIFESTATION_TYPES else None

    try:
        results = run_pipeline(
            corpus=dict(SOURCES),
            output_dir=OUTPUT_DIR,
            mfw_n=mfw_n,
            threshold=threshold,
            source_meta=dict(SOURCE_META),
            min_doc_freq=min_doc_freq,
            feature_type=feature_type,
            char_n=char_n,
            projection_method=projection_method,
            manifestation=manifestation,
        )
    except Exception as exc:
        traceback.print_exc()
        return _err(f"Помилка аналізу: {exc}", code=500)

    # Store for /report
    LAST_RESULTS = results
    LAST_RESULTS["timestamp"] = datetime.now().strftime("%d.%m.%Y %H:%M")
    LAST_RESULTS["manifestation"] = manifestation

    pair_ci = results.get("pair_ci", {})

    def _ci(a: str, b: str):
        ci = pair_ci.get(f"{a}||{b}") or pair_ci.get(f"{b}||{a}")
        if not ci:
            return None
        return {k: round(v, 4) for k, v in ci.items()}

    # Build JSON-serialisable summary
    flagged_summary = [
        {
            "a": a, "b": b,
            "a_meta": _source_lookup(a),
            "b_meta": _source_lookup(b),
            "delta": round(d, 4),
            "severity": sev,
            "ci": _ci(a, b),
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
            "ci": _ci(a, b),
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
        min_doc_freq=min_doc_freq,
        feature_type=feature_type,
        char_n=char_n,
        projection_method=projection_method,
        projection_meta=results.get("projection_meta", {}),
        branch_support=results.get("branch_support", {}),
        language_report=results.get("language_report", {}),
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

    pair_ci = r.get("pair_ci", {}) or {}

    def _ci_for(a, b):
        return pair_ci.get((a, b)) or pair_ci.get((b, a))

    flagged_details = [
        {
            "a": a,
            "b": b,
            "a_source": _source_lookup(a),
            "b_source": _source_lookup(b),
            "delta": delta,
            "severity": sev,
            "ci": _ci_for(a, b),
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
        heatmap_b64=r.get("heatmap_b64", ""),
        projection_meta=r.get("projection_meta", {}),
        language_report=r.get("language_report", {}),
        branch_support=r.get("branch_support", {}),
        feature_type=r.get("feature_type", "word"),
        char_n=r.get("char_n", 3),
        min_doc_freq=r.get("min_doc_freq", 2),
        bootstrap_iterations=r.get("bootstrap_iterations", 0),
    )


@app.get("/api/export/daily-form")
def export_daily_form():
    """Експорт Анкети добового моніторингу (Додаток 1 Методики НУЗРКС
    МОУ № 46 від 28.11.2022) у форматі .docx.

    Використовує результати останнього аналізу, збережені у
    ``LAST_RESULTS``. Якщо аналіз ще не запускався — повертає помилку.
    """
    from flask import send_file

    if not LAST_RESULTS or "dims_assessment" not in LAST_RESULTS:
        return _err(
            "Немає результатів аналізу для формування Анкети. "
            "Спочатку запустіть аналіз.",
            code=409,
        )

    dims   = LAST_RESULTS["dims_assessment"]
    labels = list(LAST_RESULTS.get("tokenised", {}).keys() or SOURCES.keys())
    sources_payload = [_source_lookup(lbl) for lbl in labels]

    direction            = (request.args.get("direction")      or "").strip()
    custom_recommendation = (request.args.get("recommendation") or "").strip()
    organization         = (request.args.get("organization")   or "").strip()

    # Розклад ризику за джерелами (перетворюємо у список dict для форми)
    raw_breakdown = LAST_RESULTS.get("source_breakdown") or []
    source_breakdown_list: list[dict] = []
    for item in raw_breakdown:
        src  = item.get("source") or {}
        lbl  = item.get("label") or src.get("label") or src.get("alias") or ""
        score = item.get("score")
        if lbl and score is not None:
            source_breakdown_list.append({"label": lbl, "score": float(score)})

    # Підозрілі стилометричні пари
    # LAST_RESULTS["flagged"] зберігає туплі (a, b, delta, severity) з пайплайну;
    # build_daily_monitoring_form очікує список dict з ключами a_source/b_source/delta.
    flagged_raw = LAST_RESULTS.get("flagged") or []
    flagged_pairs: list[dict] = []
    for fp in flagged_raw:
        if isinstance(fp, (list, tuple)):
            a_lbl, b_lbl = fp[0], fp[1]
            flagged_pairs.append({
                "a_source": _source_lookup(a_lbl),
                "b_source": _source_lookup(b_lbl),
                "delta": float(fp[2]),
            })
        elif isinstance(fp, dict):
            flagged_pairs.append(fp)

    buffer = build_daily_monitoring_form(
        grade_info=dims.get("grade") or {},
        r_dims=float(dims.get("r_dims") or 0.0),
        manifestation=dims.get("manifestation") or {},
        indicators=dims.get("indicators") or {},
        sources=sources_payload,
        source_breakdown=source_breakdown_list,
        flagged_pairs=flagged_pairs,
        direction=direction,
        organization=organization or "УПРАВЛІННЯ ЗАБЕЗПЕЧЕННЯ РЕАГУВАННЯ НА КРИЗОВІ СИТУАЦІЇ",
        custom_recommendation=custom_recommendation,
    )

    filename = (
        "anketa_dobovogo_monitoryngu_"
        + datetime.now().strftime("%Y%m%d_%H%M")
        + ".docx"
    )
    return send_file(
        buffer,
        as_attachment=True,
        download_name=filename,
        mimetype=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
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
    print("  DIMS — Інтегральна оцінка дезінформаційних ризиків за стилометричними ознаками")
    print("  Відкрийте у браузері: http://localhost:5001")
    print("=" * 60)
    app.run(debug=os.environ.get("FLASK_DEBUG", "0") == "1", port=5001)
