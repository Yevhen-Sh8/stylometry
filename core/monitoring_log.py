#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/monitoring_log.py
======================
Протокол моніторингу відкритих джерел.

Забезпечує:

1. Формування запису про кожне введене до корпусу джерело (URL, файл,
   вставлений текст, результат пошуку новин) із зазначенням часу,
   способу отримання, домену, обсягу та хеш-суми тексту.
2. Накопичення записів у файлі ``Data/monitoring_log.jsonl`` — журналі
   JSON Lines, придатному для подальшого експорту та використання в
   додатках до дисертації.
3. Перевірку наявності дубліката за SHA-256 хешем нормалізованого
   тексту з метою недопущення штучного завищення координаційного
   індикатора I_coord при повторному імпорті одного й того ж тексту.

Модуль не містить мережевих викликів і не залежить від Flask —
його може використовувати будь-який викликач із застосунку.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable

BASE_DIR = Path(__file__).resolve().parent.parent
# DIMS_DATA_DIR дозволяє винести журнал на постійний диск (напр. Render Disk),
# щоб він НЕ стирався при перезапуску. За замовчуванням — тека Data/ у проєкті.
import os as _os
DATA_DIR = Path(_os.environ.get("DIMS_DATA_DIR") or (BASE_DIR / "Data"))
LOG_FILE = DATA_DIR / "monitoring_log.jsonl"

_WHITESPACE_RE = re.compile(r"\s+")


def _normalise(text: str) -> str:
    """Нормалізація тексту для обчислення стійкого відбитка.

    Використовується виключно для хеш-порівняння: регістр, пробіли та
    контрольні символи уніфікуються, щоб уникнути хибних «нових»
    записів при дрібних типографських відмінностях.
    """
    if not text:
        return ""
    collapsed = _WHITESPACE_RE.sub(" ", text).strip().lower()
    return collapsed


def text_fingerprint(text: str) -> str:
    """Повертає SHA-256 хеш нормалізованого тексту у вигляді рядка hex."""
    digest = hashlib.sha256(_normalise(text).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def simhash(text: str, bits: int = 64) -> int:
    """64-бітний SimHash нормалізованого тексту за словесними 3-грамами.

    Майже-дублікатні тексти (той самий матеріал з іншими футерами, обрізкою,
    службовими рядками «Підписатись») мають малу відстань Геммінга між
    SimHash'ами. Використовується для блокування технічних копій ПЕРЕД
    стилометричним аналізом — інакше Δ-Burrows ≈ 0 між копіями штучно
    завищує координаційний індикатор I_coord."""
    norm = _normalise(text)
    words = norm.split()
    if not words:
        return 0
    shingles = [" ".join(words[i:i + 3]) for i in range(max(1, len(words) - 2))]
    vector = [0] * bits
    for sh in shingles:
        h = int.from_bytes(hashlib.blake2b(sh.encode("utf-8"), digest_size=8).digest(), "big")
        for b in range(bits):
            vector[b] += 1 if (h >> b) & 1 else -1
    out = 0
    for b in range(bits):
        if vector[b] > 0:
            out |= (1 << b)
    return out


def hamming(a: int, b: int) -> int:
    """Відстань Геммінга між двома SimHash-відбитками (к-ть різних бітів)."""
    return bin(a ^ b).count("1")


def _iter_records() -> Iterable[dict]:
    if not LOG_FILE.exists():
        return []
    records: list[dict] = []
    with LOG_FILE.open("r", encoding="utf-8") as handle:
        for raw in handle:
            raw = raw.strip()
            if not raw:
                continue
            try:
                records.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
    return records


def find_duplicate(fingerprint: str) -> dict | None:
    """Повертає попередній запис із вказаним відбитком або ``None``."""
    for record in _iter_records():
        if record.get("fingerprint") == fingerprint:
            return record
    return None


def append_record(
    *,
    label: str,
    source_type: str,
    url: str = "",
    domain: str = "",
    extractor: str = "",
    language: str = "",
    words: int = 0,
    fingerprint: str = "",
    original_name: str = "",
    display_title: str = "",
    note: str = "",
) -> dict:
    """Дописує запис до протоколу моніторингу та повертає його як ``dict``."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "label": label,
        "source_type": source_type,
        "url": url,
        "domain": domain,
        "extractor": extractor,
        "language": language,
        "words": int(words or 0),
        "fingerprint": fingerprint,
        "original_name": original_name,
        "display_title": display_title,
        "note": note,
    }
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def load_records() -> list[dict]:
    """Повертає всі записи протоколу (для експорту або відображення)."""
    return list(_iter_records())
