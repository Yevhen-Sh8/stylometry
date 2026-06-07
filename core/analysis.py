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
import json
import re
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
from sklearn.manifold import MDS, TSNE


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

# ─────────────────────────────────────────────────────────────────────────────
#  Види прояву DIMs — відповідно до Методики НУЗРКС МОУ № 46 від 28.11.2022,
#  розділ 1. Власне вид прояву на суму балів не впливає. Виняток — «табу»,
#  якому методика приписує автоматичний грейд SS.
# ─────────────────────────────────────────────────────────────────────────────
DIMS_MANIFESTATION_TYPES = {
    "manipulation":   "Маніпуляція",
    "fake":           "Фейк",
    "sandwich":       "Інформаційний сендвіч",
    "conspiracy":     "Конспірологія",
    "insider":        "Інсайд, незаконний «злив» інформації",
    "sensitive":      "Чутлива тема",
    "taboo":          "Табу",
}
_TABOO_FORCED_GRADE = "SS"
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
SOURCE_QUALITY_FILE = BASE_DIR / "Data" / "source_quality_overrides.json"
SOURCE_COMPONENT_WEIGHTS = {
    "domain":   0.40,
    "owner":    0.15,
    "policy":   0.10,
    "finance":  0.10,
    "original": 0.05,
    "cred":     0.12,
    "ethics":   0.08,
}
SOURCE_COMPONENT_LABELS = {
    "domain":   "R_domain",
    "owner":    "R_owner",
    "policy":   "R_policy",
    "finance":  "R_finance",
    "original": "R_original",
    "cred":     "R_cred",
    "ethics":   "R_ethics",
}
SOURCE_COMPONENT_DESCRIPTIONS = {
    "domain":   "Доменний ризик джерела та належність до ризикових медіа.",
    "owner":    "Непрозорість власності, контактів або походження джерела.",
    "policy":   "Відсутність або сумнівність редакційних політик джерела.",
    "finance":  "Непрозорість фінансування або інституційної підзвітності.",
    "original": "Низька частка власного контенту або ознаки компілятивності.",
    "cred":     "Ознаки використання анонімних, ненадійних чи неперевірюваних джерел.",
    "ethics":   "Порушення етичних стандартів (IMI): мова ворожнечі, сексизм, "
                "прихована реклама (джинса), шкідливий контент, порушення приватності.",
}
ANONYMOUS_SOURCE_PATTERNS = (
    "анонімне джерело", "анонімні джерела", "неназване джерело", "неназвані джерела",
    "джерело повідомило", "джерела повідомили", "за словами джерела",
    "анонимный источник", "анонимные источники", "неназванный источник",
    "неназванные источники", "по словам источника", "источник сообщил", "источники сообщили",
    "anonymous source", "anonymous sources", "unnamed source", "unnamed sources",
    "sources said", "according to sources", "source said",
    "anonyme quelle", "sources anonymes", "selon des sources",
    "anonyme quelle", "anonyme quellen", "laut quellen", "anonyme quelle",
)
REPRINT_PATTERNS = (
    "передрук", "передруковано", "передрук з", "за матеріалами", "за матеріалами видання",
    "републікація", "reprint", "republished", "adapted from", "based on materials from",
    "по материалам", "перепечатка", "перепечатано", "adapté de",
    "selon ", "d'après ", "nach material", "übernommen von",
)

# ─────────────────────────────────────────────────────────────────────────────
#  ETHICS LEXICONS  (IMI methodology — 3rd block: ethical standards)
#  Terms are kept short & lowercase; _pattern_risk uses simple `in` substring
#  match after .lower() — so stems cover word-forms (укр/рос mova).
# ─────────────────────────────────────────────────────────────────────────────

# Hate speech / xenophobic labels (IMI 3-3: мова ворожнечі)
HATE_SPEECH_PATTERNS = (
    # UA derogatory / dehumanising labels
    "москаль", "кацап", "орки ", "орк ", "чурк", "хохл", "жид", "бандерівськ",
    "укроп", "укропи", "нацисти київ", "неонаци", "підараси", "піндос",
    # RU derogatory labels commonly seen in propagandistic content
    "хохлы", "хохол", "хохлушк", "укры ", "укроп", "бандеров", "нацики",
    "пиндос", "гейроп", "гейропа", "либераст", "жидобандер", "жиды",
    # EN
    "subhuman", "vermin", "cockroach", "parasites ", "race traitor",
    "kike", "nigger", "faggot",
)

# Sexism / misogyny & gender stereotypes (IMI 3-4)
SEXISM_PATTERNS = (
    "бабське діло", "жіноча справа", "місце жінки", "слабка стать",
    "женская логика", "бабская логика", "место женщины", "слабый пол",
    "женское дело", "не женское дело", "бабьё",
    "a woman's place", "weaker sex", "hysterical woman",
)

# Harmful content: war glorification, drug promo, suicide, gambling, terror praise
HARMFUL_CONTENT_PATTERNS = (
    "слава війні", "смерть усім", "прославляємо смерть",
    "героизм смерти", "слава войне", "смерть всем",
    "как покончить с собой", "способы суицида", "how to commit suicide",
    "где купить наркотик", "купити наркотики", "закладк", "соль меф",
    "букмекер бонус", "промокод казино", "100% выигрыш",
    "glorify violence", "incite violence",
)

# Hidden advertising / «джинса» (IMI 3-1)
JINSA_PATTERNS = (
    "на правах реклами", "на правах рекламы", "замовна стаття", "замовний матеріал",
    "заказной материал", "заказная статья", "материал партнёра",
    "матеріал партнера", "партнёрский материал", "партнерський матеріал",
    "sponsored content", "paid partnership", "advertorial",
    "бренд-контент", "brand content",
)

# Privacy / children / victims of violence (IMI 3-5, 3-6)
PRIVACY_VIOLATION_PATTERNS = (
    "повне ім'я неповнолітн", "фото постраждалої дитини", "ім'я жертви зґвалтування",
    "полное имя несовершеннолетн", "фото пострадавшего ребенка",
    "имя жертвы изнасилован", "адрес потерпевш",
    "full name of the minor", "identify the minor victim",
)


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


def _load_source_quality_profiles(path: Path) -> dict[str, dict[str, float]]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    profiles: dict[str, dict[str, float]] = {}
    if not isinstance(raw, dict):
        return profiles
    for domain, profile in raw.items():
        norm = _normalise_domain(domain)
        if not norm or not isinstance(profile, dict):
            continue
        profiles[norm] = {
            key: float(np.clip(profile.get(key, 0.0), 0.0, 1.0))
            for key in SOURCE_COMPONENT_WEIGHTS
            if key != "domain"
        }
    return profiles


SOURCE_QUALITY_PROFILES = _load_source_quality_profiles(SOURCE_QUALITY_FILE)


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


_UA_SPECIFIC = set("іїєґІЇЄҐ")
_RU_SPECIFIC = set("ыъэЫЪЭёЁ")


def detect_script(text: str) -> str:
    """Повертає домінуючий скрипт: 'ua', 'ru', 'cyrillic', 'latin', 'mixed' або 'unknown'."""
    if not text:
        return "unknown"
    cyr = lat = ua = ru = 0
    for ch in text:
        if ch.isalpha():
            if ch in _UA_SPECIFIC:
                ua += 1
                cyr += 1
            elif ch in _RU_SPECIFIC:
                ru += 1
                cyr += 1
            elif "\u0400" <= ch <= "\u04FF":
                cyr += 1
            elif ch.isascii():
                lat += 1
    total = cyr + lat
    if total == 0:
        return "unknown"
    cyr_ratio = cyr / total
    if cyr_ratio > 0.7:
        if ua > 0 and ua >= ru * 2:
            return "ua"
        if ru > 0 and ru >= ua * 2:
            return "ru"
        return "cyrillic"
    if cyr_ratio < 0.3:
        return "latin"
    return "mixed"


_CYRILLIC_FAMILY = {"ru", "ua", "cyrillic"}

def detect_corpus_languages(corpus: dict[str, str]) -> dict:
    """Виявляє скрипти корпусу. Повертає dict з per-doc scripts та попередженням,
    якщо корпус змішаний (стилометричні порівняння різномовних текстів
    недостовірні — див. дисертацію 2.5.6).

    «cyrillic» (недостатньо маркерів для розрізнення ru/ua) не є окремою
    мовою — це та сама кирилична родина. Попередження виникає лише при
    реальному змішуванні сімей (кирилиця + латиниця) або явному «mixed».
    """
    per_doc = {label: detect_script(text) for label, text in corpus.items()}
    unique = {s for s in per_doc.values() if s != "unknown"}
    # Тільки кирилична родина — не вважається змішаним корпусом
    is_mixed = not (unique <= _CYRILLIC_FAMILY) or "mixed" in unique
    warnings: list[str] = []
    if is_mixed:
        warnings.append(
            f"Виявлено різні мовні родини ({', '.join(sorted(unique))}). "
            "Результати стилометрії можуть бути недостовірними: "
            "рекомендується аналізувати одномовні корпуси."
        )
    # Попередження про короткі тексти
    short_docs = [lbl for lbl, txt in corpus.items() if len(txt.split()) < 500]
    if short_docs:
        warnings.append(
            f"Короткі тексти ({len(short_docs)} із {len(corpus)}): "
            "надійний Burrows Delta потребує ≥ 500 слів (Burrows 2002, Eder 2013). "
            "Telegram-пости та новинні нотатки дають ненадійні результати."
        )
    warning = " | ".join(warnings) if warnings else None
    return {
        "per_document": per_doc,
        "scripts": sorted(unique),
        "is_mixed": is_mixed,
        "warning": warning,
    }


def char_ngrams(text: str, n: int = 3) -> list[str]:
    """Character n-grams with whitespace normalisation.

    Рекомендовано для коротких текстів (<500 токенів) та міжмовних порівнянь
    (Kestemont 2014, "Function Words in Authorship Attribution").
    Пунктуація і цифри видаляються, пробіли колапсуються у одинарний ' '.
    """
    if n < 2:
        raise ValueError("n має бути ≥ 2 для char-n-gram режиму.")
    cleaned = text.lower().translate(_STRIP_TABLE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) < n:
        return []
    return [cleaned[i:i + n] for i in range(len(cleaned) - n + 1)]


def tokenise_corpus(
    corpus: dict[str, str],
    feature_type: str = "word",
    char_n: int = 3,
) -> dict[str, list[str]]:
    """Apply tokenisation to every document in the corpus.

    feature_type: "word" (default) → clean_and_tokenise;
                  "char"           → char_ngrams(text, n=char_n).
    """
    if feature_type == "char":
        return {label: char_ngrams(text, n=char_n) for label, text in corpus.items()}
    if feature_type != "word":
        raise ValueError(f"Невідомий feature_type: {feature_type!r}")
    return {label: clean_and_tokenise(text) for label, text in corpus.items()}


# ─────────────────────────────────────────────────────────────────────────────
#  MFW
# ─────────────────────────────────────────────────────────────────────────────

def find_mfw(
    tokenised: dict[str, list[str]],
    n: int = 100,
    min_doc_freq: int = 2,
) -> list[str]:
    """Return the top-*n* most frequent word types across the corpus.

    Culling (min_doc_freq) виключає слова, що трапляються у меншій кількості
    документів, ніж *min_doc_freq*. Це стандарт Stylo-R: усуває hapax
    legomena та тематично-специфічну лексику, посилюючи авторський сигнал.
    Якщо корпус містить < min_doc_freq документів, culling не застосовується.
    """
    global_counts: Counter[str] = Counter()
    doc_freq: Counter[str] = Counter()
    for tokens in tokenised.values():
        global_counts.update(tokens)
        doc_freq.update(set(tokens))

    effective_min = max(1, min(min_doc_freq, len(tokenised)))
    if effective_min > 1:
        eligible = {w for w, df in doc_freq.items() if df >= effective_min}
        ranked = [(w, c) for w, c in global_counts.most_common() if w in eligible]
    else:
        ranked = global_counts.most_common()
    return [w for w, _ in ranked[:n]]


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


def bootstrap_delta_ci(
    z: pd.DataFrame,
    n_iterations: int = 500,
    confidence: float = 0.95,
    random_state: int | None = 42,
) -> dict[tuple[str, str], dict[str, float]]:
    """Bootstrap 95% CI для Δ-Burrows кожної пари документів.

    На кожній ітерації ресемплюємо MFW-ознаки (колонки) з заміщенням і
    перераховуємо Δ для всіх пар. На виході — словник
    {(a, b): {"lo": ..., "hi": ..., "mean": ..., "std": ...}}.

    Посилання: Eder (2012), "Mind your corpus: systematic errors in
    authorship attribution".
    """
    rng = np.random.default_rng(random_state)
    labels = z.index.tolist()
    values = z.values.astype(float)
    n_docs, n_features = values.shape
    if n_docs < 2 or n_features < 2:
        return {}

    pair_indices = list(combinations(range(n_docs), 2))
    samples = np.empty((n_iterations, len(pair_indices)), dtype=float)

    for it in range(n_iterations):
        cols = rng.integers(0, n_features, size=n_features)
        resampled = values[:, cols]
        dists = cdist(resampled, resampled, metric="cityblock") / n_features
        for k, (i, j) in enumerate(pair_indices):
            samples[it, k] = dists[i, j]

    alpha = (1.0 - confidence) / 2.0
    lo = np.quantile(samples, alpha, axis=0)
    hi = np.quantile(samples, 1.0 - alpha, axis=0)
    mean = samples.mean(axis=0)
    std = samples.std(axis=0, ddof=1) if n_iterations > 1 else np.zeros_like(mean)

    return {
        (labels[i], labels[j]): {
            "lo": float(lo[k]),
            "hi": float(hi[k]),
            "mean": float(mean[k]),
            "std": float(std[k]),
        }
        for k, (i, j) in enumerate(pair_indices)
    }


# ─────────────────────────────────────────────────────────────────────────────
#  CLUSTERING HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _build_linkage(dist_df: pd.DataFrame):
    """Distance matrix → average linkage; robust for precomputed Burrows' Delta."""
    return linkage(squareform(dist_df.values, checks=False), method="average")


def _color_threshold(Z_link) -> float:
    return 0.7 * float(Z_link[:, 2].max())


def _linkage_clades(Z_link, labels: list[str]) -> list[frozenset[str]]:
    """Повертає список clades (множин листків), які з'являються у linkage.
    Використовується для обчислення bootstrap-стабільності гілок.
    """
    n = len(labels)
    membership: list[frozenset[str]] = [frozenset([lab]) for lab in labels]
    clades: list[frozenset[str]] = []
    for row in Z_link:
        i, j = int(row[0]), int(row[1])
        new = membership[i] | membership[j]
        membership.append(new)
        if 1 < len(new) < n:
            clades.append(new)
    return clades


def bootstrap_branch_support(
    z: pd.DataFrame,
    n_iterations: int = 200,
    random_state: int | None = 42,
) -> dict[frozenset[str], float]:
    """Для кожної clade (нелистової гілки дендрограми) повертає частку
    bootstrap-ітерацій (0..1), у яких ця гілка спостерігалася. Використовує
    column resampling MFW-ознак (узгоджено з bootstrap_delta_ci).
    """
    labels = z.index.tolist()
    values = z.values.astype(float)
    n_docs, n_features = values.shape
    if n_docs < 3 or n_features < 2:
        return {}

    rng = np.random.default_rng(random_state)
    support: Counter[frozenset[str]] = Counter()

    for _ in range(n_iterations):
        cols = rng.integers(0, n_features, size=n_features)
        resampled = values[:, cols]
        d = cdist(resampled, resampled, metric="cityblock") / n_features
        try:
            Z_i = linkage(squareform(d, checks=False), method="average")
        except ValueError:
            continue
        for clade in _linkage_clades(Z_i, labels):
            support[clade] += 1

    return {clade: count / n_iterations for clade, count in support.items()}


# ─────────────────────────────────────────────────────────────────────────────
#  VISUALISATIONS
# ─────────────────────────────────────────────────────────────────────────────

def save_dendrogram(
    dist_df: pd.DataFrame,
    output_path: Path,
    branch_support: dict[frozenset[str], float] | None = None,
    also_svg: bool = True,
) -> None:
    """Average-linkage dendrogram → PNG (+ optional SVG).
    Якщо задано branch_support, підписує % стабільності над внутрішніми вузлами.
    """
    Z_link   = _build_linkage(dist_df)
    c_thresh = _color_threshold(Z_link)
    n        = len(dist_df)
    short_labels = [f"S{i + 1}" for i in range(n)]
    labels = dist_df.index.tolist()

    fig_width = min(max(7.2, n * 0.62), 11.0)
    fig, ax = plt.subplots(figsize=(fig_width, 5.0))
    ddata = dendrogram(
        Z_link,
        labels=short_labels,
        leaf_rotation=0,
        leaf_font_size=9,
        color_threshold=c_thresh,
        ax=ax,
    )
    ax.axhline(c_thresh, linestyle="--", color="grey", linewidth=0.8,
               label=f"Поріг кластеризації ({c_thresh:.3f})")

    if branch_support:
        membership: list[frozenset[str]] = [frozenset([lab]) for lab in labels]
        for k, row in enumerate(Z_link):
            i, j = int(row[0]), int(row[1])
            height = float(row[2])
            clade = membership[i] | membership[j]
            membership.append(clade)
            if 1 < len(clade) < n:
                icoord = ddata["icoord"][k]
                x_mid = 0.5 * (icoord[1] + icoord[2])
                support_pct = int(round(100 * branch_support.get(clade, 0.0)))
                ax.annotate(
                    f"{support_pct}%",
                    xy=(x_mid, height),
                    xytext=(0, 3),
                    textcoords="offset points",
                    ha="center", va="bottom",
                    fontsize=7, color="#444",
                )

    title = "Дендрограма стилометричної близькості"
    if branch_support:
        title += "  ·  bootstrap-стабільність (%) над вузлами"
    ax.set_title(title, fontweight="bold")
    ax.set_ylabel("Відстань Δ_Burrows")
    ax.set_xlabel("Ідентифікатори джерел")
    ax.grid(axis="y", linestyle=":", linewidth=0.5, alpha=0.45)
    ax.tick_params(axis="x", labelsize=8)
    ax.legend(fontsize=8, loc="upper left", frameon=False)
    fig.tight_layout()
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    if also_svg:
        fig.savefig(output_path.with_suffix(".svg"), bbox_inches="tight")
    plt.close(fig)


def _project_coords(
    z: pd.DataFrame,
    dist_df: pd.DataFrame,
    method: str,
) -> tuple[np.ndarray, str, float | None]:
    """Повертає (coords, subtitle, explained_variance_or_None) для заданого методу."""
    n_samples = len(z)
    method = method.lower()

    if method == "pca":
        n_comp = min(2, n_samples - 1, z.shape[1])
        pca = PCA(n_components=n_comp)
        coords = pca.fit_transform(z.values)
        var = pca.explained_variance_ratio_ * 100
        if coords.shape[1] == 1:
            coords = np.column_stack([coords, np.zeros(len(coords))])
            var = np.append(var, [0.0])
        subtitle = f"PC1 {var[0]:.1f}% · PC2 {var[1]:.1f}% (разом {float(sum(var[:2])):.1f}%)"
        return coords, subtitle, float(sum(var[:2]))

    if method == "mds":
        mds = MDS(n_components=2, dissimilarity="precomputed",
                  random_state=42, normalized_stress="auto", n_init=4)
        coords = mds.fit_transform(dist_df.values)
        subtitle = f"MDS (stress = {mds.stress_:.3f}) · відстані збережено"
        return coords, subtitle, None

    if method == "tsne":
        perplexity = max(2, min(30, (n_samples - 1) // 3))
        tsne = TSNE(n_components=2, metric="precomputed", init="random",
                    perplexity=perplexity, random_state=42)
        coords = tsne.fit_transform(dist_df.values)
        subtitle = f"t-SNE (perplexity = {perplexity})"
        return coords, subtitle, None

    raise ValueError(f"Невідомий метод проєкції: {method!r}")


def save_projection_plot(
    z: pd.DataFrame,
    dist_df: pd.DataFrame,
    output_path: Path,
    method: str = "pca",
    also_svg: bool = True,
) -> dict:
    """2-D проєкція (pca | mds | tsne), розфарбована за кластерами. → PNG (+SVG).
    Повертає метадані {method, subtitle, explained_variance}.
    """
    if len(z) < 2:
        return {"method": method, "subtitle": "недостатньо точок"}

    coords, subtitle, explained = _project_coords(z, dist_df, method)

    Z_link      = _build_linkage(dist_df)
    cluster_ids = fcluster(Z_link, t=_color_threshold(Z_link), criterion="distance")
    cmap        = plt.get_cmap("tab10")
    palette     = {cid: cmap(i / max(len(set(cluster_ids)), 1))
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

    method_title = {"pca": "PCA-проєкція", "mds": "MDS-проєкція",
                    "tsne": "t-SNE-проєкція"}.get(method.lower(), method)
    ax.set_xlabel("Вимір 1")
    ax.set_ylabel("Вимір 2")
    ax.set_title(f"{method_title} стилометричних ознак\n{subtitle}",
                 fontweight="bold", fontsize=11)
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.legend(loc="best", fontsize=9, framealpha=0.8)

    if method.lower() == "pca" and explained is not None and explained < 60:
        ax.text(0.01, 0.01,
                f"Увага: {explained:.0f}% — дендрограма/MDS надійніші",
                transform=ax.transAxes, fontsize=7, color="grey",
                verticalalignment="bottom")
    fig.tight_layout()
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    if also_svg:
        fig.savefig(output_path.with_suffix(".svg"), bbox_inches="tight")
    plt.close(fig)
    return {"method": method, "subtitle": subtitle, "explained_variance": explained}


# Backward-compatible alias
def save_pca_plot(z: pd.DataFrame, dist_df: pd.DataFrame, output_path: Path) -> None:
    save_projection_plot(z, dist_df, output_path, method="pca")


def save_distance_heatmap(
    dist_df: pd.DataFrame,
    output_path: Path,
    threshold: float,
    also_svg: bool = True,
) -> None:
    """Теплова карта Δ-Burrows із накладеним порогом як контуром."""
    n = len(dist_df)
    if n < 2:
        return
    fig, ax = plt.subplots(figsize=(max(5.5, n * 0.55), max(5.0, n * 0.5)))
    data = dist_df.values
    im = ax.imshow(data, cmap="viridis_r", aspect="equal")
    labels = [f"S{i + 1}" for i in range(n)]
    ax.set_xticks(range(n)); ax.set_yticks(range(n))
    ax.set_xticklabels(labels, fontsize=9, rotation=45, ha="right")
    ax.set_yticklabels(labels, fontsize=9)

    for i in range(n):
        for j in range(n):
            val = data[i, j]
            if i == j:
                continue
            color = "white" if val < data.max() * 0.55 else "black"
            weight = "bold" if val < threshold else "normal"
            ax.text(j, i, f"{val:.2f}", ha="center", va="center",
                    fontsize=8, color=color, fontweight=weight)
            if val < threshold:
                ax.add_patch(plt.Rectangle(
                    (j - 0.5, i - 0.5), 1, 1,
                    fill=False, edgecolor="#dc2626", linewidth=1.5))

    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label("Δ_Burrows")
    ax.set_title(f"Матриця Δ-Burrows · поріг = {threshold:.2f}",
                 fontweight="bold", fontsize=11)
    fig.tight_layout()
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    if also_svg:
        fig.savefig(output_path.with_suffix(".svg"), bbox_inches="tight")
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
                "color": "#dc2626", "icon": ""}
    if delta < high:
        return {"label": "Високий",   "en": "High",     "css": "high",
                "color": "#ea580c", "icon": ""}
    return     {"label": "Помірний",  "en": "Moderate", "css": "moderate",
                "color": "#ca8a04", "icon": ""}


# Багатомовні маркери заперечення/спростування. Якщо такий токен стоїть
# безпосередньо перед знайденим маркером (вікно 3 токени), маркер НЕ
# зараховується — це усуває хибні спрацювання на кшталт «це не фейк»,
# «спростування пропаганди», «нібито атака».
_NEGATION_CUES = {
    # укр.
    "не", "ні", "без", "спростування", "спростовано", "спростовує", "спростують",
    "нібито", "начебто", "буцімто",
    # рос.
    "нет", "без", "опровержение", "опровергнут", "опроверг", "якобы", "ложь",
    # англ.
    "no", "not", "without", "debunk", "debunked", "debunks", "false", "refute",
    "refuted", "refutes", "denies", "denied",
    # фр.
    "non", "sans", "pas", "ne", "dément", "démenti",
    # нім.
    "kein", "keine", "nicht", "ohne", "dementiert", "widerlegt",
}
# Референсна щільність маркерів (частка токенів-маркерів), за якої частотний
# сигнал виходить на насичення. Інтерпретовний параметр (калібрується),
# замінює непрозорий лінійний множник scale. Гладке насичення 1 − exp(−rate/ref)
# усуває «обрив» жорсткого min(1, …) і робить шкалу безрозмірною й порівнянною.
_CONTENT_DENSITY_REF = 0.018
_IMPACT_DENSITY_REF = 0.026
_NEGATION_WINDOW = 3


def _marker_score(tokens: list[str], markers: set[str], density_ref: float) -> float:
    total = len(tokens)
    if total == 0:
        return 0.0
    hits: list[str] = []
    for i, t in enumerate(tokens):
        if t not in markers:
            continue
        window = tokens[max(0, i - _NEGATION_WINDOW):i]
        if any(w in _NEGATION_CUES for w in window):
            continue  # заперечений маркер не зараховуємо
        hits.append(t)
    rate = len(hits) / total
    # Гладке насичення замість лінійного scale з жорстким відсіканням.
    freq_score = float(1.0 - np.exp(-rate / max(density_ref, 1e-9)))
    diversity_score = min(1.0, len(set(hits)) / max(1, min(len(markers), 8)))
    return float(np.clip(0.7 * freq_score + 0.3 * diversity_score, 0.0, 1.0))


def _document_signal_scores(tokenised: dict[str, list[str]]) -> dict[str, dict[str, float]]:
    scores: dict[str, dict[str, float]] = {}
    for label, tokens in tokenised.items():
        scores[label] = {
            "content": _marker_score(tokens, CONTENT_MARKERS, density_ref=_CONTENT_DENSITY_REF),
            "impact": _marker_score(tokens, IMPACT_MARKERS, density_ref=_IMPACT_DENSITY_REF),
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


def _domain_profile(domain: str) -> dict[str, float]:
    norm = _normalise_domain(domain)
    if not norm:
        return {}
    if norm in SOURCE_QUALITY_PROFILES:
        return SOURCE_QUALITY_PROFILES[norm]
    for candidate, profile in SOURCE_QUALITY_PROFILES.items():
        if norm.endswith(f".{candidate}"):
            return profile
    return {}


def _pattern_risk(text: str, patterns: tuple[str, ...], weight: float) -> float:
    if not text:
        return 0.0
    lower = text.lower()
    hits = 0
    for pattern in patterns:
        if not pattern:
            continue
        idx = lower.find(pattern)
        while idx != -1:
            # Не зараховуємо збіг, якщо безпосередньо перед ним стоїть
            # заперечення/спростування (зменшує хибні спрацювання, особливо
            # для етичних патернів у засуджувальному чи цитувальному контексті).
            pre_words = lower[max(0, idx - 40):idx].split()[-_NEGATION_WINDOW:]
            if not any(w in _NEGATION_CUES for w in pre_words):
                hits += 1
            idx = lower.find(pattern, idx + len(pattern))
    return float(np.clip(hits * weight, 0.0, 1.0))


def _source_component_scores(meta: dict | None, text: str) -> dict[str, float]:
    meta = meta or {}
    domain = (meta.get("domain") or "").strip()
    source_type = (meta.get("type") or "").strip().lower()
    domain_score = _domain_risk_score(domain)
    profile = _domain_profile(domain)

    owner_score = profile.get("owner", 0.0)
    policy_score = profile.get("policy", 0.0)
    finance_score = profile.get("finance", 0.0)
    original_score = profile.get("original", 0.0)
    cred_score = profile.get("cred", 0.0)
    ethics_score = profile.get("ethics", 0.0)

    if not domain:
        owner_score = max(owner_score, 0.35 if source_type in {"text", "html"} else 0.20)
    elif domain_score >= 0.85:
        owner_score = max(owner_score, 0.45)
        policy_score = max(policy_score, 0.35)
        finance_score = max(finance_score, 0.35)
        ethics_score = max(ethics_score, 0.40)
    elif domain_score >= 0.55:
        owner_score = max(owner_score, 0.25)
        ethics_score = max(ethics_score, 0.20)

    original_score = max(original_score, _pattern_risk(text, REPRINT_PATTERNS, 0.20))
    cred_score = max(cred_score, _pattern_risk(text, ANONYMOUS_SOURCE_PATTERNS, 0.28))

    # Ethics: IMI block 3 — hate speech, sexism, hidden ads, harmful content, privacy.
    # Each lexicon contributes its own normalised hit-risk; we take the strongest
    # signal (max) rather than sum — presence of one violation is enough to flag.
    lex_hate    = _pattern_risk(text, HATE_SPEECH_PATTERNS,        0.30)
    lex_sexism  = _pattern_risk(text, SEXISM_PATTERNS,             0.35)
    lex_harm    = _pattern_risk(text, HARMFUL_CONTENT_PATTERNS,    0.40)
    lex_jinsa   = _pattern_risk(text, JINSA_PATTERNS,              0.25)
    lex_privacy = _pattern_risk(text, PRIVACY_VIOLATION_PATTERNS,  0.40)
    lex_ethics  = max(lex_hate, lex_sexism, lex_harm, lex_jinsa, lex_privacy)
    ethics_score = max(ethics_score, lex_ethics)

    components = {
        "domain":   float(np.clip(domain_score, 0.0, 1.0)),
        "owner":    float(np.clip(owner_score, 0.0, 1.0)),
        "policy":   float(np.clip(policy_score, 0.0, 1.0)),
        "finance":  float(np.clip(finance_score, 0.0, 1.0)),
        "original": float(np.clip(original_score, 0.0, 1.0)),
        "cred":     float(np.clip(cred_score, 0.0, 1.0)),
        "ethics":   float(np.clip(ethics_score, 0.0, 1.0)),
    }
    total = float(np.clip(sum(components[key] * SOURCE_COMPONENT_WEIGHTS[key] for key in SOURCE_COMPONENT_WEIGHTS), 0.0, 1.0))
    components["total"] = total
    return components


def _source_score(
    source_meta: dict[str, dict] | None,
    corpus: dict[str, str] | None = None,
) -> tuple[float, dict[str, float], dict[str, dict[str, float]], dict[str, float]]:
    if not source_meta:
        return 0.0, {}, {}, {}

    per_source: dict[str, float] = {}
    source_details: dict[str, dict[str, float]] = {}
    component_lists = {key: [] for key in SOURCE_COMPONENT_WEIGHTS}

    for label, meta in source_meta.items():
        text = (corpus or {}).get(label, "")
        components = _source_component_scores(meta, text)
        per_source[label] = components["total"]
        source_details[label] = components
        for key in SOURCE_COMPONENT_WEIGHTS:
            component_lists[key].append(components[key])

    if not per_source:
        return 0.0, {}, {}, {}

    component_breakdown = {
        key: float(np.mean(values))
        for key, values in component_lists.items()
        if values
    }
    overall = float(np.mean(list(per_source.values())))
    return overall, per_source, source_details, component_breakdown


# Ваги факторів координаційного індикатора I_coord відповідно до означення в
# дисертації (розд. 2.5): I_coord = f(Δ_Burrows, S_time, S_theme, S_source) —
# стилометрична близькість, синхронність появи, тематична повторюваність,
# структурна пов'язаність джерел. Провізорні; калібруються апробацією.
_COORD_FACTOR_WEIGHTS = {"stylo": 0.50, "time": 0.10, "theme": 0.20, "source": 0.20}


def _stylo_coordination(dist_df: pd.DataFrame, threshold: float) -> float:
    """Стилометрична складова I_coord на основі матриці Δ-Burrows."""
    labels = dist_df.index.tolist()
    deltas = [float(dist_df.loc[a, b]) for a, b in combinations(labels, 2)]
    if not deltas:
        return 0.0
    min_delta = min(deltas)
    closest_score = max(0.0, 1.0 - (min_delta / max(threshold, 1e-6)))
    flagged_ratio = sum(1 for d in deltas if d < threshold) / len(deltas)
    top_k = sorted(deltas)[: min(3, len(deltas))]
    compactness = max(0.0, 1.0 - (float(np.mean(top_k)) / max(threshold, 1e-6)))
    return float(np.clip(0.5 * closest_score + 0.3 * flagged_ratio + 0.2 * compactness, 0.0, 1.0))


def _theme_overlap_score(tokenised: dict[str, list[str]] | None, top_n: int = 50) -> float:
    """S_theme — середня попарна тематична подібність (Jaccard за топ-N токенами)."""
    if not tokenised or len(tokenised) < 2:
        return 0.0
    top_sets = []
    for toks in tokenised.values():
        top_sets.append({w for w, _ in Counter(toks).most_common(top_n)} if toks else set())
    sims = []
    for a, b in combinations(top_sets, 2):
        union = a | b
        if union:
            sims.append(len(a & b) / len(union))
    return float(np.clip(np.mean(sims), 0.0, 1.0)) if sims else 0.0


def _source_linkage_score(source_meta: dict[str, dict] | None) -> float:
    """S_source — структурна пов'язаність джерел: частка джерел, що належать до
    спільної мережі підвищеного ризику (проксі мережевої когезії ретрансляції)."""
    if not source_meta or len(source_meta) < 2:
        return 0.0
    risky = sum(
        1 for meta in source_meta.values()
        if _domain_risk_score((meta or {}).get("domain", "")) >= 0.55
    )
    return float(np.clip(risky / len(source_meta), 0.0, 1.0))


def _time_sync_score(source_meta: dict[str, dict] | None) -> float | None:
    """S_time — синхронність появи повідомлень. Потребує позначок часу публікацій.
    Повертає None, якщо їх немає у метаданих (фактор виключається з ренормуванням
    вагів), що чесно відображає поточну доступність даних."""
    if not source_meta:
        return None
    stamps = [(m or {}).get("timestamp") or (m or {}).get("date") for m in source_meta.values()]
    stamps = [s for s in stamps if s]
    if len(stamps) < 2:
        return None
    try:
        from datetime import datetime
        def _parse(s):
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    return datetime.strptime(str(s)[:19], fmt)
                except ValueError:
                    continue
            return None
        dts = [d for d in (_parse(s) for s in stamps) if d]
        if len(dts) < 2:
            return None
        span_h = (max(dts) - min(dts)).total_seconds() / 3600.0
        # Чим тісніше вікно появи, тим вища синхронність (насичення на 48 год).
        return float(np.clip(1.0 - min(span_h, 48.0) / 48.0, 0.0, 1.0))
    except Exception:
        return None


def _coordination_score(
    dist_df: pd.DataFrame,
    threshold: float,
    tokenised: dict[str, list[str]] | None = None,
    source_meta: dict[str, dict] | None = None,
) -> float:
    """I_coord — багатофакторний індикатор координації між джерелами.

    Відповідно до означення в дисертації поєднує: стилометричну близькість
    (Δ-Burrows), синхронність появи (S_time), тематичну повторюваність (S_theme)
    та структурну пов'язаність джерел (S_source). Якщо для якогось фактора немає
    даних (зокрема позначок часу для S_time), він виключається, а ваги решти
    ренормуються — тож I_coord завжди коректно нормований у [0, 1]."""
    factors = {
        "stylo": _stylo_coordination(dist_df, threshold),
        "theme": _theme_overlap_score(tokenised),
        "source": _source_linkage_score(source_meta),
    }
    t = _time_sync_score(source_meta)
    if t is not None:
        factors["time"] = t
    wsum = sum(_COORD_FACTOR_WEIGHTS[k] for k in factors)
    if wsum <= 0:
        return 0.0
    score = sum(_COORD_FACTOR_WEIGHTS[k] / wsum * v for k, v in factors.items())
    return float(np.clip(score, 0.0, 1.0))


# Точка насичення: стільки незалежних джерел, що висвітлюють подію, дає
# повний сигнал інтенсивності. Значення провізорне — калібрується апробацією.
_DYNAMICS_SATURATION_DOCS = 8


def _dynamics_score(n_docs: int) -> float:
    """I_dynamics — інтенсивність (масштаб) висвітлення події, нормована до [0, 1].

    Наукова коректність:
    - НЕ використовує щільність підозрілих пар: цей сигнал належить I_coord,
      і повторне врахування тут спричиняло б подвійний рахунок координації
      в R_DIMS (адитивна модель вимагає розумної незалежності індикаторів).
    - Часова динаміка (синхронність появи, S_time) потребує позначок часу
      публікацій, які наразі не збираються, тому винесена в подальшу роботу
      (див. розділ обмежень моделі). Поточна операціоналізація консервативна —
      лише масштаб незалежного охоплення.
    """
    if n_docs <= 0:
        return 0.0
    return float(np.clip(n_docs / _DYNAMICS_SATURATION_DOCS, 0.0, 1.0))


def dims_sensitivity(
    indicators: dict[str, float],
    weights: dict[str, float],
    perturbation: float = 0.20,
) -> dict:
    """Sensitivity analysis: перебирає ваги ±perturbation для кожного індикатора,
    ренормалізуючи решту. Повертає baseline/min/max R_DIMS та внесок кожного
    індикатора (partial contribution і діапазон варіації).
    """
    keys = list(weights.keys())
    baseline = sum(weights[k] * indicators.get(f"I_{k}", 0.0) for k in keys)

    per_indicator: dict[str, dict[str, float]] = {}
    r_min, r_max = baseline, baseline

    for target in keys:
        variants = []
        for delta in (-perturbation, +perturbation):
            w_target = max(0.0, weights[target] * (1 + delta))
            remaining = sum(weights[k] for k in keys if k != target)
            if remaining <= 0:
                continue
            scale = (1.0 - w_target) / remaining
            new_weights = {
                k: (w_target if k == target else weights[k] * scale)
                for k in keys
            }
            r = sum(new_weights[k] * indicators.get(f"I_{k}", 0.0) for k in keys)
            variants.append(r)
            r_min = min(r_min, r)
            r_max = max(r_max, r)
        if variants:
            per_indicator[target] = {
                "contribution": round(weights[target] * indicators.get(f"I_{target}", 0.0), 4),
                "min": round(min(variants), 4),
                "max": round(max(variants), 4),
                "range": round(max(variants) - min(variants), 4),
            }

    return {
        "perturbation": perturbation,
        "baseline": round(float(baseline), 4),
        "min": round(float(r_min), 4),
        "max": round(float(r_max), 4),
        "range": round(float(r_max - r_min), 4),
        "per_indicator": per_indicator,
    }


_GRADE_ORDER = {g: idx for idx, (g, _, _) in enumerate(GRADE_THRESHOLDS)}


def classify_interest_grade(
    r_dims: float,
    manifestation: str | None = None,
) -> dict[str, str | float]:
    """Обчислення грейду відповідно до GRADE_THRESHOLDS.

    Якщо задано *manifestation* = «табу», результат примусово підіймається
    щонайменше до SS-грейду згідно з Методикою НУЗРКС МОУ № 46 від
    28.11.2022 (розділ 1). Решта видів прояву на оцінку не впливають.
    """
    grade = "SSS"
    label = "Критичний інтерес"
    upper_bound: float = 1.0
    for g, upper, lbl in GRADE_THRESHOLDS:
        if r_dims < upper:
            grade, label, upper_bound = g, lbl, upper
            break

    if manifestation == "taboo" and _GRADE_ORDER.get(grade, 0) < _GRADE_ORDER[_TABOO_FORCED_GRADE]:
        grade = _TABOO_FORCED_GRADE
        for g, upper, lbl in GRADE_THRESHOLDS:
            if g == _TABOO_FORCED_GRADE:
                label, upper_bound = lbl, upper
                break

    return {
        "grade": grade,
        "label": label,
        "upper_bound": upper_bound,
    }


def _r_dims_confidence(
    z: pd.DataFrame,
    threshold: float,
    content_score: float,
    impact_score: float,
    dynamics_score: float,
    source_score: float,
    tokenised: dict[str, list[str]],
    source_meta: dict[str, dict] | None,
    manifestation: str | None = None,
    n_iterations: int = 300,
    confidence: float = 0.95,
    random_state: int = 42,
) -> dict:
    """Bootstrap-довірчий інтервал для R_DIMS.

    Ресемплюємо MFW-ознаки (колонки z) з заміщенням і на кожній ітерації
    перераховуємо стилометричну складову I_coord → I_coord → R_DIMS. Інші
    фактори I_coord (тематична/структурна/часова пов'язаність) та решта
    індикаторів від ресемплу ознак не залежать, тож фіксуються. Повертає
    [lo, hi], середнє та ЙМОВІРНІСТЬ кожного грейду — це дає відповідь на
    закид «точкова оцінка без похибки» і кількісно оцінює стійкість грейду
    на межі (напр. P(грейд ≥ S))."""
    labels = z.index.tolist()
    values = z.values.astype(float)
    n_docs, n_features = values.shape
    if n_docs < 2 or n_features < 2:
        return {}

    # Незмінні (щодо ресемплу ознак) фактори I_coord та фіксована частина R_DIMS.
    theme = _theme_overlap_score(tokenised)
    source_link = _source_linkage_score(source_meta)
    t_sync = _time_sync_score(source_meta)
    w = DEFAULT_WEIGHTS
    fixed_part = (w["content"] * content_score + w["dynamics"] * dynamics_score
                  + w["impact"] * impact_score + w["source"] * source_score)

    rng = np.random.default_rng(random_state)
    samples = np.empty(n_iterations, dtype=float)
    for it in range(n_iterations):
        cols = rng.integers(0, n_features, size=n_features)
        dists = cdist(values[:, cols], values[:, cols], metric="cityblock") / n_features
        stylo = _stylo_coordination(pd.DataFrame(dists, index=labels, columns=labels), threshold)
        factors = {"stylo": stylo, "theme": theme, "source": source_link}
        if t_sync is not None:
            factors["time"] = t_sync
        wsum = sum(_COORD_FACTOR_WEIGHTS[k] for k in factors)
        i_coord = (sum(_COORD_FACTOR_WEIGHTS[k] / wsum * v for k, v in factors.items())
                   if wsum > 0 else 0.0)
        samples[it] = fixed_part + w["coord"] * float(np.clip(i_coord, 0.0, 1.0))

    alpha = (1.0 - confidence) / 2.0
    grades = [classify_interest_grade(float(s), manifestation=manifestation)["grade"]
              for s in samples]
    gc = Counter(grades)
    grade_prob = {g: round(gc.get(g, 0) / n_iterations, 3) for g, _, _ in GRADE_THRESHOLDS}
    return {
        "lo": round(float(np.quantile(samples, alpha)), 4),
        "hi": round(float(np.quantile(samples, 1.0 - alpha)), 4),
        "mean": round(float(samples.mean()), 4),
        "std": round(float(samples.std(ddof=1)) if n_iterations > 1 else 0.0, 4),
        "confidence": confidence,
        "grade_prob": grade_prob,
        "n_iterations": n_iterations,
    }


def build_dims_assessment(
    tokenised: dict[str, list[str]],
    dist_df: pd.DataFrame,
    threshold: float,
    flagged_pairs: int = 0,   # збережено для сумісності API; не використовується
    n_pairs: int = 0,         # (сигнал координації повністю в I_coord)
    source_meta: dict[str, dict] | None = None,
    corpus: dict[str, str] | None = None,
    manifestation: str | None = None,
    z: pd.DataFrame | None = None,
) -> dict:
    _ = (flagged_pairs, n_pairs)  # навмисно не використовуються
    doc_scores = _document_signal_scores(tokenised)
    content_score = float(np.mean([v["content"] for v in doc_scores.values()])) if doc_scores else 0.0
    impact_score = float(np.mean([v["impact"] for v in doc_scores.values()])) if doc_scores else 0.0
    coord_score = _coordination_score(dist_df, threshold, tokenised=tokenised, source_meta=source_meta)
    dynamics_score = _dynamics_score(len(tokenised))
    source_score, source_breakdown, source_details, source_components = _source_score(source_meta, corpus)
    r_dims = (
        DEFAULT_WEIGHTS["content"] * content_score
        + DEFAULT_WEIGHTS["coord"] * coord_score
        + DEFAULT_WEIGHTS["dynamics"] * dynamics_score
        + DEFAULT_WEIGHTS["impact"] * impact_score
        + DEFAULT_WEIGHTS["source"] * source_score
    )
    grade = classify_interest_grade(r_dims, manifestation=manifestation)
    indicators = {
        "I_content": round(content_score, 4),
        "I_coord": round(coord_score, 4),
        "I_dynamics": round(dynamics_score, 4),
        "I_impact": round(impact_score, 4),
        "I_source": round(source_score, 4),
    }
    sensitivity = dims_sensitivity(indicators, DEFAULT_WEIGHTS)
    confidence = (
        _r_dims_confidence(z, threshold, content_score, impact_score,
                           dynamics_score, source_score, tokenised, source_meta,
                           manifestation=manifestation)
        if z is not None else {}
    )
    manifestation_key = manifestation if manifestation in DIMS_MANIFESTATION_TYPES else None
    manifestation_info = {
        "key": manifestation_key,
        "label": DIMS_MANIFESTATION_TYPES.get(manifestation_key, ""),
        "types": DIMS_MANIFESTATION_TYPES,
    }
    return {
        "weights": DEFAULT_WEIGHTS,
        "indicators": indicators,
        "r_dims": round(float(r_dims), 4),
        "confidence": confidence,
        "grade": grade,
        "manifestation": manifestation_info,
        "sensitivity": sensitivity,
        "document_signals": doc_scores,
        "source_breakdown": {k: round(v, 4) for k, v in source_breakdown.items()},
        "source_details": {
            label: {k: round(v, 4) for k, v in values.items()}
            for label, values in source_details.items()
        },
        "source_components": {
            SOURCE_COMPONENT_LABELS[key]: {
                "key": key,
                "score": round(value, 4),
                "weight": round(SOURCE_COMPONENT_WEIGHTS[key], 4),
                "description": SOURCE_COMPONENT_DESCRIPTIONS[key],
            }
            for key, value in source_components.items()
        },
        "notes": [
            "I_content: маркери маніпулятивного змісту у корпусі.",
            "I_coord: багатофакторна координація — Δ-Burrows + тематична подібність + структурна пов'язаність джерел (+ синхронність появи за наявності позначок часу).",
            "I_dynamics: інтенсивність (масштаб) незалежного висвітлення; часова синхронність — напрям подальшої роботи.",
            "I_impact: маркери потенційного впливу на безпекове середовище.",
            "I_source: доменний ризик джерела, прозорість, редакційні ознаки та якість роботи з джерелами.",
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
    min_doc_freq: int = 2,
    bootstrap_iterations: int = 500,
    feature_type: str = "word",
    char_n: int = 3,
    projection_method: str = "pca",
    manifestation: str | None = None,
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
    language_report = detect_corpus_languages(corpus)
    tokenised     = tokenise_corpus(corpus, feature_type=feature_type, char_n=char_n)
    mfw           = find_mfw(tokenised, n=mfw_n, min_doc_freq=min_doc_freq)
    if not mfw:
        raise ValueError(
            "Після culling не залишилось MFW. Зменшіть min_doc_freq або "
            "перевірте, чи тексти мають спільну лексику."
        )
    tf            = build_tf_matrix(tokenised, mfw)
    z             = zscore_matrix(tf)
    dist_df       = burrows_delta(z)

    dendrogram_path = output_dir / "dendrogram.png"
    pca_path        = output_dir / "pca_plot.png"
    heatmap_path    = output_dir / "heatmap.png"
    csv_path        = output_dir / "distance_matrix.csv"

    # ── Bootstrap CI + branch support (stability of each pairwise Δ) ─────
    ci_map: dict[tuple[str, str], dict[str, float]] = {}
    branch_support: dict[frozenset[str], float] = {}
    if bootstrap_iterations and bootstrap_iterations > 0:
        ci_map = bootstrap_delta_ci(z, n_iterations=bootstrap_iterations)
        branch_support = bootstrap_branch_support(
            z, n_iterations=min(bootstrap_iterations, 200)
        )

    save_dendrogram(dist_df, dendrogram_path, branch_support=branch_support)
    projection_meta = save_projection_plot(
        z, dist_df, pca_path, method=projection_method,
    )
    save_distance_heatmap(dist_df, heatmap_path, threshold=threshold)
    save_distance_matrix(dist_df, csv_path)

    def _ci_for(a: str, b: str) -> dict[str, float] | None:
        return ci_map.get((a, b)) or ci_map.get((b, a))

    # Branch support keyed by sorted label tuple (JSON-serialisable)
    branch_support_serialisable = {
        "|".join(sorted(clade)): round(float(support), 3)
        for clade, support in branch_support.items()
    }

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
        corpus=corpus,
        manifestation=manifestation,
        z=z,
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
        "pair_ci":         {f"{a}||{b}": _ci_for(a, b) for a, b, _ in all_pairs if _ci_for(a, b) is not None},
        "bootstrap_iterations": bootstrap_iterations,
        "delta_stats": {
            "min":    float(deltas.min()),
            "max":    float(deltas.max()),
            "mean":   float(deltas.mean()),
            "median": float(np.median(deltas)),
            "std":    float(deltas.std()),
        },
        "dendrogram_path": dendrogram_path,
        "pca_path":        pca_path,
        "heatmap_path":    heatmap_path,
        "csv_path":        csv_path,
        "dendrogram_b64":  _b64(dendrogram_path),
        "pca_b64":         _b64(pca_path),
        "heatmap_b64":     _b64(heatmap_path),
        "projection_meta": projection_meta,
        "branch_support":  branch_support_serialisable,
        "dims_assessment": dims_assessment,
        "mfw_n":           mfw_n,
        "min_doc_freq":    min_doc_freq,
        "feature_type":    feature_type,
        "char_n":          char_n,
        "language_report": language_report,
        "threshold":       threshold,
        "n_docs":          len(labels),
        "n_pairs":         len(all_pairs),
    }
