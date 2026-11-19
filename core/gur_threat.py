#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/gur_threat.py
==================
Макрорівень оцінювання: від DIMS-оцінок окремих подій до форми ведення
інформаційної боротьби (ІБ) та рівня інформаційної загрози (ІЗ) за напрямами
й сферами за період.

Прототип — «Методика виявлення, аналізу та оцінювання інформаційних загроз
державі у воєнній сфері» (ГУР МО України, 2016), блок аналізу ІЗ, етапи 1–4:

    K_i   — рівень інтенсивності негативного ІВ: частка негативних повідомлень
            від загальної кількості за період;
    K_т   — тривалість, K_т = x / (x + a); a = 40,56 для x ≤ 365 дн., інакше 19,21
            (формули 1–3, табл. 4);
    K_д   — поширеність джерел: місцевий 0,25; + регіональний 0,5;
            + загальнодержавний 0,75; + міжнародний 1,0;
    K_о   — масштабність об'єктів ІВ: одиночний 0,1–0,3; груповий 0,31–0,7;
            масовий 0,71–1,0 (експертна оцінка);
    K_j^н = (K_i + K_т + K_д + K_о) / 4                       (формула 4);
    форма реалізації ІЗ (атака / акція / операція / кампанія) — табл. 5;
    Z_k^c = Σ K_j^н / N за напрямами сфери k                  (формула 5);
    рівень ІЗ — табл. 6.

Чотири доповнення автора дисертації повертаються ОКРЕМИМИ полями, щоб
порівняння «прототип ↔ удосконалена методика» було видно в результаті:

    instruments      — інструменти впливу: залучені джерела й особи (зокрема
                       зі стилометричних пар і кластерів технічних копій DIMS), ЗМІ;
    target_audience  — цільова аудиторія (ЦА) поряд із K_о;
    facts            — факти, на яких ґрунтується висновок про форму;
    trend            — прогноз: зменшення / збільшення / продовження на тому ж рівні.

Відповідь на зауваження «немає можливості» отримати кількісні значення базових
показників: кожен показник має позначку джерела —
    auto      обчислено з даних моніторингу;
    expert    введено аналітиком;
    proxy     провізорний замінник (наприклад, K_i з грейдів DIMS);
    fallback  обчислено з неповних даних (наприклад, дата оцінки замість дат публікацій).

Відступи від прототипу (правила реалізації, НЕ положення ГУР-2016):
    * табл. 5 має перекриття (акція 0,37–0,69 / операція 0,62–0,88 /
      кампанія 0,69–1,0) і розрив 0,34–0,37 — форма визначається за мінімальною
      інтервальною відстанню до профілю табл. 5, а неоднозначність явно
      позначається (ambiguous + candidates);
    * межі табл. 6 і рівнів інтенсивності (0–0,25 / 0,26–0,5 …) трактуються
      як напіввідкриті інтервали (lo; hi];
    * «змістовні взаємозв'язки» між напрямами / сферами (с. 28) апроксимуються
      спільними джерелами — це організаційна, а не змістова ознака (proxy);
    * Z_k^c — точно за формулою 5 (середнє); додатково повертається
      попереджувальна ознака critical_direction, бо середнє «розчиняє»
      окремий критичний напрям.

Формула R_DIMS і шкала грейдів F…SSS (Наказ МО № 46) тут не змінюються.
Модуль — чисті функції без I/O.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

# ─────────────────────────────────────────────────────────────────────────────
#  Довідники прототипу
# ─────────────────────────────────────────────────────────────────────────────

# Сфери життєдіяльності — табл. 1 методики (8 сфер). У табл. 3 перелік інший
# (зокрема є «інформаційна»), тому невідомі коди сфер приймаються як є.
SPHERES = {
    "foreign_policy": "Зовнішньополітична",
    "state_security": "Державної безпеки",
    "military": "Воєнна",
    "domestic_policy": "Внутрішньополітична",
    "economic": "Економічна",
    "social_humanitarian": "Соціальна та гуманітарна",
    "science_tech": "Науково-технологічна",
    "ecological": "Екологічна",
}
_SPHERE_ALIASES = {
    "зовнішньополітична": "foreign_policy", "державної безпеки": "state_security",
    "державна безпека": "state_security", "воєнна": "military", "військова": "military",
    "внутрішньополітична": "domestic_policy", "економічна": "economic",
    "соціальна та гуманітарна": "social_humanitarian", "соціальна": "social_humanitarian",
    "гуманітарна": "social_humanitarian", "науково-технологічна": "science_tech",
    "екологічна": "ecological",
}
DEFAULT_SPHERE = "military"

# Напрями реалізації ІЗ у воєнній сфері — табл. 2 (стислі формулювання).
# Дозволено й власні коди напрямів (рядок до 64 символів).
MILITARY_DIRECTIONS = {
    "m1": "Дискредитація військового керівництва та збройних сил",
    "m2": "Дискредитація операції заявами посадових осіб іноземних держав",
    "m3": "Деморалізація особового складу силових структур",
    "m4": "Підбурювання до зриву мобілізаційних заходів",
    "m5": "Дискредитація військових формувань, служби та військового обов'язку",
    "m6": "Протидія наданню військової допомоги Україні",
    "m7": "Звинувачення особового складу в незаконних діях у зоні конфлікту",
}
UNASSIGNED_DIRECTION = "unassigned"

# Рівень інтенсивності K_i (с. 24): верхні межі напіввідкритих інтервалів.
INTENSITY_LEVELS = [
    (0.20, "low", "низький"),
    (0.40, "medium", "середній"),
    (0.60, "elevated", "підвищений"),
    (0.80, "high", "високий"),
    (1.00, "critical", "критичний"),
]

# Тривалість K_т (формули 1–3).
DURATION_A_UP_TO_YEAR = 40.56
DURATION_A_OVER_YEAR = 19.21

# Поширеність джерел K_д (с. 26) — береться найширший досягнутий рівень.
REACH_VALUES = {"local": 0.25, "regional": 0.50, "national": 0.75, "international": 1.00}
_REACH_ALIASES = {
    "місцевий": "local", "регіональний": "regional",
    "загальнодержавний": "national", "національний": "national",
    "міжнародний": "international",
}

# Масштабність об'єктів K_о (с. 25–26) — експертні межі.
OBJECT_SCALES = {"single": (0.10, 0.30), "group": (0.31, 0.70), "mass": (0.71, 1.00)}
_OBJECT_ALIASES = {"одиночний": "single", "груповий": "group", "масовий": "mass"}
OBJECT_SCALE_LABELS = {"single": "одиночний об'єкт", "group": "груповий об'єкт",
                       "mass": "масовий об'єкт"}

# Рівень ІЗ — табл. 6 (верхні межі напіввідкритих інтервалів).
THREAT_LEVELS = [
    (0.25, "low", "низький"),
    (0.50, "elevated", "підвищений"),
    (0.75, "high", "високий"),
    (1.00, "critical", "критичний"),
]
CRITICAL_DIRECTION_THRESHOLD = 0.76

# Форми ведення ІБ — табл. 5 (числові межі показників і K_j^н).
FORMS = ["attack", "action", "operation", "campaign"]
FORM_RANK = {f: i for i, f in enumerate(FORMS)}
FORM_PROFILES = {
    "attack": {
        "label": "Інформаційна атака", "directions": "один напрям",
        "K_i": (0.20, 0.40), "K_t": (0.00, 0.15), "K_d": (0.25, 0.50),
        "K_o": (0.10, 0.30), "K_n": (0.00, 0.34),
    },
    "action": {
        "label": "Інформаційна акція", "directions": "один напрям",
        "K_i": (0.40, 0.60), "K_t": (0.26, 0.70), "K_d": (0.51, 0.75),
        "K_o": (0.10, 0.70), "K_n": (0.37, 0.69),
    },
    "operation": {
        "label": "Інформаційна операція", "directions": "один або декілька напрямів в одній сфері",
        "K_i": (0.40, 0.80), "K_t": (0.43, 0.70), "K_d": (0.76, 1.00),
        "K_o": (0.31, 1.00), "K_n": (0.62, 0.88),
    },
    "campaign": {
        "label": "Інформаційна кампанія", "directions": "декілька напрямів у декількох сферах",
        "K_i": (0.61, 1.00), "K_t": (0.71, 0.97), "K_d": (0.76, 1.00),
        "K_o": (0.71, 1.00), "K_n": (0.69, 1.00),
    },
}

# Грейди DIMS (Наказ МО № 46) — без імпорту core.analysis (модуль має бути легким).
_GRADE_ORDER = ["F", "B", "S", "SS", "SSS"]
_GRADE_RANK = {g: i for i, g in enumerate(_GRADE_ORDER)}
# Провізорний замінник K_i: матеріали події з грейдом ≥ S вважаються негативними.
PROXY_NEGATIVE_MIN_GRADE = "S"

# Провізорні параметри реалізації (калібруються апробацією).
DEFAULT_WINDOW_DAYS = 7          # мінімальний період узагальнення за ГУР-2016 (с. 5)
DEFAULT_TREND_DELTA = 0.05       # поріг зміни Z для тренду
DEFAULT_FORM_TIE_TOL = 0.05      # допуск рівновіддаленості профілів форм
_TREND_POINTS = 4                # вікон для нахилу тренду
_MAX_LIST = 50

TREND_LABELS = {
    "increase": "збільшення",
    "decrease": "зменшення",
    "stable": "продовження на тому ж рівні",
    "insufficient": "недостатньо даних",
}


# ─────────────────────────────────────────────────────────────────────────────
#  Елементарні показники
# ─────────────────────────────────────────────────────────────────────────────

def duration_coefficient(days: float) -> float:
    """K_т = x / (x + a) — формули 1–3 прототипу (x — дні негативного ІВ).

    Дві константи a (до року й понад рік) відтворено точно; через це на межі
    року функція має стрибок — властивість прототипу, а не реалізації."""
    x = max(0.0, float(days))
    if x == 0:
        return 0.0
    a = DURATION_A_UP_TO_YEAR if x <= 365 else DURATION_A_OVER_YEAR
    return x / (x + a)


def _level(value: float, table: list[tuple[float, str, str]]) -> dict:
    v = float(value)
    for upper, key, label in table:
        if v <= upper + 1e-12:
            return {"key": key, "label": label}
    key, label = table[-1][1], table[-1][2]
    return {"key": key, "label": label}


def intensity_level(k_i: float) -> dict:
    """Рівень інтенсивності K_i: напіввідкриті інтервали (lo; hi]."""
    return _level(k_i, INTENSITY_LEVELS)


def threat_level(z: float) -> dict:
    """Рівень ІЗ за табл. 6: [0; 0,25] низький, (0,25; 0,5] підвищений,
    (0,5; 0,75] високий, (0,75; 1,0] критичний."""
    return _level(z, THREAT_LEVELS)


def reach_value(level: str) -> float:
    return REACH_VALUES[_canon(level, REACH_VALUES, _REACH_ALIASES, "рівень поширеності")]


def object_scale_value(scale: str, value: float | None = None) -> tuple[float, str]:
    """K_о: явне експертне значення або (якщо його немає) середина діапазону
    категорії — останнє є припущенням реалізації і позначається expert_midpoint."""
    key = _canon(scale, OBJECT_SCALES, _OBJECT_ALIASES, "масштабність об'єктів")
    lo, hi = OBJECT_SCALES[key]
    if value is not None:
        return float(value), "expert"
    return round((lo + hi) / 2, 4), "expert_midpoint"


def normalized_indicator(k_i, k_t, k_d, k_o) -> tuple[float | None, list[str]]:
    """K_j^н за формулою 4. Відсутні показники повертаються в списку missing;
    тоді K_j^н рахується з наявних і позначається як неповний (partial) —
    таке значення НЕ відповідає прототипу й слугує лише орієнтиром."""
    parts = {"K_i": k_i, "K_t": k_t, "K_d": k_d, "K_o": k_o}
    present = [v for v in parts.values() if v is not None]
    missing = [k for k, v in parts.items() if v is None]
    if not present:
        return None, missing
    return sum(present) / (4 if not missing else len(present)), missing


# ─────────────────────────────────────────────────────────────────────────────
#  Метадані ГУР для події (валідація вводу)
# ─────────────────────────────────────────────────────────────────────────────

def _canon(value, valid: dict, aliases: dict, what: str) -> str:
    v = str(value or "").strip().lower()
    if v in valid:
        return v
    if v in aliases:
        return aliases[v]
    raise ValueError(f"Невідоме значення «{value}» для поля {what}: "
                     f"допустимі {sorted(valid)}.")


def canon_sphere(value) -> str:
    v = str(value or "").strip()
    if not v:
        return DEFAULT_SPHERE
    low = v.lower()
    if low in SPHERES:
        return low
    if low in _SPHERE_ALIASES:
        return _SPHERE_ALIASES[low]
    if len(v) > 64:
        raise ValueError("sphere: не довше 64 символів.")
    return v  # власний код сфери (див. розбіжність табл. 1 і табл. 3)


def _str_list(value, what: str, limit: int = _MAX_LIST) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        value = [x for x in (s.strip() for s in value.split(";")) if x]
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ValueError(f"{what}: очікується список рядків.")
    out = [x.strip()[:200] for x in value if x.strip()]
    if len(out) > limit:
        raise ValueError(f"{what}: не більше {limit} елементів.")
    return out


def normalise_gur_meta(meta) -> dict:
    """Валідує й нормалізує метадані події для макрорівня. Повертає {} для
    порожнього вводу. Невідомі ключі ігноруються. Помилки — ValueError."""
    if meta is None or meta == {}:
        return {}
    if not isinstance(meta, dict):
        raise ValueError("gur має бути об'єктом.")
    out: dict = {}
    direction = str(meta.get("direction") or "").strip()
    if direction:
        if len(direction) > 64:
            raise ValueError("gur.direction: не довше 64 символів.")
        out["direction"] = direction
    if meta.get("direction_label"):
        out["direction_label"] = str(meta["direction_label"]).strip()[:200]
    if meta.get("sphere"):
        out["sphere"] = canon_sphere(meta["sphere"])
    if meta.get("target_scale"):
        out["target_scale"] = _canon(meta["target_scale"], OBJECT_SCALES, _OBJECT_ALIASES,
                                     "gur.target_scale")
    if meta.get("target_value") is not None and meta.get("target_value") != "":
        try:
            tv = float(meta["target_value"])
        except (TypeError, ValueError):
            raise ValueError("gur.target_value має бути числом 0,1–1,0.")
        if not 0.1 <= tv <= 1.0:
            raise ValueError("gur.target_value має бути в межах 0,1–1,0.")
        if "target_scale" in out:
            lo, hi = OBJECT_SCALES[out["target_scale"]]
            if not lo - 1e-9 <= tv <= hi + 1e-9:
                raise ValueError(f"gur.target_value {tv} поза межами категорії "
                                 f"{out['target_scale']} ({lo}–{hi}).")
        out["target_value"] = tv
    ta = _str_list(meta.get("target_audience"), "gur.target_audience")
    if ta:
        out["target_audience"] = ta
    if meta.get("reach"):
        out["reach"] = _canon(meta["reach"], REACH_VALUES, _REACH_ALIASES, "gur.reach")
    sr = meta.get("source_reach")
    if sr:
        if not isinstance(sr, dict):
            raise ValueError("gur.source_reach має бути об'єктом {джерело: рівень}.")
        out["source_reach"] = {str(k)[:200]: _canon(v, REACH_VALUES, _REACH_ALIASES,
                                                     "gur.source_reach")
                               for k, v in list(sr.items())[:500]}
    for key in ("n_negative", "n_total"):
        if meta.get(key) is not None and meta.get(key) != "":
            try:
                n = int(meta[key])
            except (TypeError, ValueError):
                raise ValueError(f"gur.{key} має бути цілим ≥ 0.")
            if n < 0:
                raise ValueError(f"gur.{key} має бути цілим ≥ 0.")
            out[key] = n
    if "n_negative" in out and "n_total" in out and out["n_negative"] > out["n_total"]:
        raise ValueError("gur.n_negative не може перевищувати gur.n_total.")
    persons = _str_list(meta.get("persons"), "gur.persons")
    if persons:
        out["persons"] = persons
    return out


# ─────────────────────────────────────────────────────────────────────────────
#  Нормалізація подій (збережених DIMS-оцінок)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_date(value) -> date | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").date()
        except ValueError:
            return None


def _event_from_assessment(a: dict) -> dict | None:
    if not isinstance(a, dict) or not a.get("event_id"):
        return None
    gur = a.get("gur") or {}
    period = a.get("period") or {}
    first = _parse_date(period.get("first_published"))
    last = _parse_date(period.get("last_published"))
    dates_source = "auto"
    if first is None and last is None:
        first = last = _parse_date(a.get("assessed_at"))
        dates_source = "fallback"
    elif first is None:
        first = last
    elif last is None:
        last = first
    if first is None:
        return None
    stats = a.get("stats") or {}
    coord = a.get("coordination") or {}
    grade = (a.get("grade") or {}).get("grade") if isinstance(a.get("grade"), dict) else a.get("grade")
    n_unique = int(stats.get("n_unique_materials") or stats.get("n_materials") or 0)
    return {
        "event_id": str(a["event_id"]),
        "sphere": canon_sphere(gur.get("sphere")),
        "sphere_assumed": not gur.get("sphere"),
        "direction": gur.get("direction") or UNASSIGNED_DIRECTION,
        "direction_label": gur.get("direction_label"),
        "first": min(first, last),
        "last": max(first, last),
        "dates_source": dates_source,
        "grade": grade,
        "r_dims": a.get("r_dims"),
        "n_unique": n_unique,
        "sources": dict(stats.get("sources") or {}),
        "flagged_pairs": list(coord.get("flagged_pairs") or []),
        "copy_clusters": list(coord.get("copy_clusters") or []),
        "gur": gur,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Базові показники напряму (етап 2)
# ─────────────────────────────────────────────────────────────────────────────

def _coordinated_sources(events: list[dict]) -> Counter:
    c: Counter = Counter()
    for e in events:
        for p in e["flagged_pairs"]:
            for s in (p.get("a"), p.get("b")):
                if s:
                    c[s] += 1
        for cl in e["copy_clusters"]:
            if int(cl.get("n_sources") or len(cl.get("sources") or [])) >= 2:
                for s in cl.get("sources") or []:
                    c[s] += 1
    return c


def _direction_indicators(events: list[dict], first_seen: date) -> dict:
    """Етап 2 прототипу для одного напряму: K_i, K_т, K_д, K_о з позначками джерел."""
    # K_i — частка негативних повідомлень
    neg = tot = 0
    n_expert = n_proxy = 0
    for e in events:
        g = e["gur"]
        total = g.get("n_total") if g.get("n_total") is not None else e["n_unique"]
        total = max(int(total or 0), 0)
        if g.get("n_negative") is not None:
            n_expert += 1
            neg += min(int(g["n_negative"]), total) if total else int(g["n_negative"])
            tot += max(total, int(g["n_negative"]))
        else:
            n_proxy += 1
            is_neg = _GRADE_RANK.get(e["grade"] or "", -1) >= _GRADE_RANK[PROXY_NEGATIVE_MIN_GRADE]
            neg += total if is_neg else 0
            tot += total
    k_i = (neg / tot) if tot else None
    k_i_src = "expert" if n_proxy == 0 else ("proxy" if n_expert == 0 else "mixed")

    # K_т — тривалість від першої появи напряму до останньої, календарні дні включно
    last = max(e["last"] for e in events)
    days = (last - first_seen).days + 1
    k_t = duration_coefficient(days)
    k_t_src = "fallback" if any(e["dates_source"] == "fallback" for e in events) else "auto"

    # K_д — найширший досягнутий рівень поширеності
    reach_levels = []
    for e in events:
        g = e["gur"]
        if g.get("reach"):
            reach_levels.append(g["reach"])
        reach_levels.extend((g.get("source_reach") or {}).values())
    k_d = max((REACH_VALUES[r] for r in reach_levels), default=None)
    widest = max(reach_levels, key=lambda r: REACH_VALUES[r]) if reach_levels else None

    # K_о — найбільша масштабність об'єктів серед подій напряму
    scales = [e["gur"]["target_scale"] for e in events if e["gur"].get("target_scale")]
    values = [e["gur"]["target_value"] for e in events if e["gur"].get("target_value") is not None]
    k_o, k_o_src, scale = None, None, None
    if values:
        k_o, k_o_src = max(values), "expert"
        scale = next((s for s, (lo, hi) in OBJECT_SCALES.items() if lo - 1e-9 <= k_o <= hi + 1e-9), None)
    elif scales:
        scale = max(scales, key=lambda s: OBJECT_SCALES[s][1])
        k_o, k_o_src = object_scale_value(scale)

    return {
        "K_i": None if k_i is None else round(k_i, 4),
        "K_t": round(k_t, 4),
        "K_d": k_d,
        "K_o": None if k_o is None else round(k_o, 4),
        "sources": {"K_i": k_i_src if k_i is not None else None, "K_t": k_t_src,
                    "K_d": "expert" if k_d is not None else None, "K_o": k_o_src},
        "details": {
            "negative_messages": neg, "total_messages": tot,
            "intensity_level": intensity_level(k_i)["label"] if k_i is not None else None,
            "duration_days": days, "first_seen": first_seen.isoformat(),
            "last_seen": last.isoformat(),
            "widest_reach": widest,
            "target_scale": scale,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Форма реалізації ІЗ (етап 3)
# ─────────────────────────────────────────────────────────────────────────────

def _gap(v: float, lo: float, hi: float) -> float:
    if v < lo:
        return lo - v
    if v > hi:
        return v - hi
    return 0.0


def classify_form(indicators: dict, k_n: float, tie_tol: float = DEFAULT_FORM_TIE_TOL) -> dict:
    """Форма за табл. 5 для одного напряму.

    Правило реалізації (не прототипу): сума інтервальних відстаней наявних
    показників і K_j^н до профілю форми; найближча форма — основна, а всі
    форми в межах tie_tol від неї, а також усі, чий діапазон K_j^н містить
    значення, — кандидати. Більше одного кандидата → ambiguous."""
    by_kn = [f for f in FORMS
             if FORM_PROFILES[f]["K_n"][0] - 1e-9 <= k_n <= FORM_PROFILES[f]["K_n"][1] + 1e-9]
    distance = {}
    for f in FORMS:
        prof = FORM_PROFILES[f]
        d = _gap(k_n, *prof["K_n"])
        for key in ("K_i", "K_t", "K_d", "K_o"):
            v = indicators.get(key)
            if v is not None:
                d += _gap(float(v), *prof[key])
        distance[f] = round(d, 4)
    best = min(FORMS, key=lambda f: (distance[f], FORM_RANK[f]))
    near = [f for f in FORMS if distance[f] - distance[best] <= tie_tol + 1e-12]
    candidates = sorted(set(near) | set(by_kn), key=FORM_RANK.get)
    return {
        "form": best,
        "form_label": FORM_PROFILES[best]["label"],
        "candidates": candidates,
        "ambiguous": len(candidates) > 1,
        "by_K_n": by_kn,
        "in_K_n_gap": not by_kn,
        "distance": distance,
    }


def _linked(sources_a: set[str], coord_a: set[str], sources_b: set[str], coord_b: set[str]) -> bool:
    """Зв'язок між напрямами/сферами (proxy «змістовних взаємозв'язків», с. 28):
    спільне скоординоване джерело (стилометрична пара чи кластер копій) або
    щонайменше два спільні джерела."""
    return bool(coord_a & coord_b) or len(sources_a & sources_b) >= 2


# ─────────────────────────────────────────────────────────────────────────────
#  Оцінка сфери (етапи 1–4 + доповнення автора)
# ─────────────────────────────────────────────────────────────────────────────

def _first_seen_map(history: list[dict]) -> dict[tuple[str, str], date]:
    out: dict[tuple[str, str], date] = {}
    for e in history:
        key = (e["sphere"], e["direction"])
        if key not in out or e["first"] < out[key]:
            out[key] = e["first"]
    return out


def _direction_result(sphere: str, direction: str, events: list[dict], first_seen: date) -> dict:
    ind = _direction_indicators(events, first_seen)
    k_n, missing = normalized_indicator(ind["K_i"], ind["K_t"], ind["K_d"], ind["K_o"])
    form = classify_form(ind, k_n) if k_n is not None else None

    src_counter: Counter = Counter()
    for e in events:
        for s, n in e["sources"].items():
            src_counter[s] += int(n or 1)
    coord = _coordinated_sources(events)
    persons: Counter = Counter()
    audiences: Counter = Counter()
    labels = [e["direction_label"] for e in events if e.get("direction_label")]
    for e in events:
        persons.update(e["gur"].get("persons") or [])
        audiences.update(e["gur"].get("target_audience") or [])

    pairs = []
    clusters = []
    for e in events:
        for p in e["flagged_pairs"]:
            pairs.append({"event_id": e["event_id"], "a": p.get("a"), "b": p.get("b"),
                          "delta": p.get("delta")})
        for c in e["copy_clusters"]:
            clusters.append({"event_id": e["event_id"], "sources": c.get("sources"),
                             "n_sources": c.get("n_sources"),
                             "first_source": c.get("first_source"),
                             "first_published_at": c.get("first_published_at")})
    pairs.sort(key=lambda p: (p["delta"] if p["delta"] is not None else 9e9))
    clusters.sort(key=lambda c: -(c["n_sources"] or 0))
    grades = [e["grade"] for e in events if e["grade"] in _GRADE_RANK]

    label = labels[0] if labels else (
        MILITARY_DIRECTIONS.get(direction) if sphere == "military" else None)
    if direction == UNASSIGNED_DIRECTION:
        label = "Напрям не визначено (потрібне тегування аналітиком)"

    return {
        "direction": direction,
        "direction_label": label,
        "indicators": {k: ind[k] for k in ("K_i", "K_t", "K_d", "K_o")},
        "indicator_sources": ind["sources"],
        "indicator_details": ind["details"],
        "K_n": None if k_n is None else round(k_n, 4),
        "K_n_partial": bool(missing),
        "missing_indicators": missing,
        "form": form,
        # ── доповнення автора ──────────────────────────────────────────────
        "instruments": {
            "sources": [{"source": s, "materials": n} for s, n in src_counter.most_common(_MAX_LIST)],
            "coordinated_sources": [{"source": s, "links": n}
                                    for s, n in coord.most_common(_MAX_LIST)],
            "persons": [{"person": p, "events": n} for p, n in persons.most_common(_MAX_LIST)],
        },
        "target_audience": {
            "scale": ind["details"]["target_scale"],
            "scale_label": OBJECT_SCALE_LABELS.get(ind["details"]["target_scale"] or ""),
            "audiences": [{"audience": a, "events": n} for a, n in audiences.most_common(_MAX_LIST)],
        },
        "facts": {
            "n_events": len(events),
            "event_ids": [e["event_id"] for e in events][:_MAX_LIST],
            "first_seen": ind["details"]["first_seen"],
            "last_seen": ind["details"]["last_seen"],
            "n_materials": sum(e["n_unique"] for e in events),
            "n_flagged_pairs": len(pairs),
            "n_copy_clusters": len(clusters),
            "max_grade": max(grades, key=_GRADE_RANK.get) if grades else None,
            "closest_pairs": pairs[:5],
            "largest_copy_clusters": clusters[:5],
        },
        "_sources": set(src_counter),
        "_coord": set(coord),
    }


def _sphere_form(directions: list[dict], cross_sphere_linked: bool) -> dict:
    """Узагальнена форма для сфери: табл. 5 («кількість напрямів») + с. 28.

    Правила реалізації:
      * кандидатом є операція / кампанія і сфера пов'язана з іншою сферою →
        кампанія (с. 28: є змістовні взаємозв'язки з іншими сферами);
      * кілька пов'язаних між собою напрямів в одній сфері → не нижче операції;
      * кампанія без зв'язків з іншими сферами → операція (кампанія вимагає
        декількох сфер)."""
    scored = [d for d in directions if d["form"]]
    if not scored:
        return {"form": None, "form_label": None, "basis": "недостатньо даних для K_j^н",
                "ambiguous": False, "candidates": []}
    top = max(scored, key=lambda d: FORM_RANK[d["form"]["form"]])
    form = top["form"]["form"]
    candidates = set()
    for d in scored:
        candidates.update(d["form"]["candidates"])
    basis = [f"найвища форма серед напрямів — «{FORM_PROFILES[form]['label']}» "
             f"(напрям {top['direction']})"]

    linked_dirs = False
    for i, a in enumerate(scored):
        for b in scored[i + 1:]:
            if _linked(a["_sources"], a["_coord"], b["_sources"], b["_coord"]):
                linked_dirs = True
    heavy = bool(candidates & {"operation", "campaign"})
    if heavy and cross_sphere_linked:
        form = "campaign"
        basis.append("наявні взаємозв'язки з напрямами інших сфер (с. 28; proxy — спільні джерела)")
    else:
        if len(scored) > 1 and linked_dirs and FORM_RANK[form] < FORM_RANK["operation"]:
            form = "operation"
            basis.append("декілька пов'язаних напрямів в одній сфері (табл. 5)")
        if form == "campaign" and not cross_sphere_linked:
            form = "operation"
            basis.append("кампанія потребує декількох сфер; взаємозв'язків з іншими "
                         "сферами не виявлено (с. 28) → операція")
    candidates.add(form)
    cands = sorted(candidates, key=FORM_RANK.get)
    return {
        "form": form,
        "form_label": FORM_PROFILES[form]["label"],
        "basis": "; ".join(basis),
        "ambiguous": any(d["form"]["ambiguous"] for d in scored),
        "candidates": cands,
        "linked_directions": linked_dirs,
        "linked_other_spheres": cross_sphere_linked,
    }


def _evaluate_sphere(sphere: str, events: list[dict], first_seen: dict,
                     cross_linked: bool) -> dict:
    by_dir: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        by_dir[e["direction"]].append(e)
    directions = [_direction_result(sphere, d, evs, first_seen[(sphere, d)])
                  for d, evs in sorted(by_dir.items())]
    scored = [d for d in directions if d["K_n"] is not None]
    z = sum(d["K_n"] for d in scored) / len(scored) if scored else None
    partial = any(d["K_n_partial"] for d in scored)
    crit = [d["direction"] for d in scored if d["K_n"] >= CRITICAL_DIRECTION_THRESHOLD]
    level = threat_level(z) if z is not None else None
    return {
        "sphere": sphere,
        "sphere_label": SPHERES.get(sphere, sphere),
        "n_directions": len(directions),
        "Z": None if z is None else round(z, 4),
        "Z_partial": partial,
        "level": level,
        "form": _sphere_form(directions, cross_linked),
        "critical_direction": {
            "flag": bool(crit) and (level or {}).get("key") != "critical",
            "directions": crit,
            "note": ("середнє за формулою 5 «розчиняє» критичний напрям — "
                     "попереджувальна ознака, значення Z не змінює"),
        },
        "directions": directions,
    }


def _strip_private(obj):
    if isinstance(obj, dict):
        return {k: _strip_private(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [_strip_private(x) for x in obj]
    return obj


def _sphere_sets(events: list[dict]) -> tuple[set[str], set[str]]:
    srcs, coord = set(), set(_coordinated_sources(events))
    for e in events:
        srcs.update(e["sources"])
    return srcs, coord


def _cross_links(by_sphere: dict[str, list[dict]]) -> dict[str, list[str]]:
    sets = {s: _sphere_sets(evs) for s, evs in by_sphere.items()}
    links: dict[str, list[str]] = {s: [] for s in by_sphere}
    keys = sorted(by_sphere)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            if _linked(sets[a][0], sets[a][1], sets[b][0], sets[b][1]):
                links[a].append(b)
                links[b].append(a)
    return links


def _evaluate_period(events: list[dict], history: list[dict], spheres: list[str] | None) -> dict:
    first_seen = _first_seen_map(history)
    by_sphere: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        by_sphere[e["sphere"]].append(e)
    links = _cross_links(by_sphere)
    out = {}
    for s, evs in sorted(by_sphere.items()):
        if spheres and s not in spheres:
            continue
        out[s] = _evaluate_sphere(s, evs, first_seen, bool(links.get(s)))
        out[s]["linked_spheres"] = links.get(s, [])
    return out


# ─────────────────────────────────────────────────────────────────────────────
#  Тренд і прогноз (доповнення автора)
# ─────────────────────────────────────────────────────────────────────────────

def _slope(points: list[float]) -> float:
    n = len(points)
    if n < 2:
        return 0.0
    xs = range(n)
    mx = (n - 1) / 2
    my = sum(points) / n
    den = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, points)) / den if den else 0.0


def trend_forecast(z_series: list[float | None], delta: float = DEFAULT_TREND_DELTA) -> dict:
    """Прогноз на наступний період за рядом Z по вікнах (без пропусків даних).

    Нахил МНК за останніми (до 4) вікнами: > δ — збільшення, < −δ — зменшення,
    інакше — продовження на тому ж рівні. δ провізорний."""
    pts = [z for z in z_series if z is not None][-_TREND_POINTS:]
    if len(pts) < 2:
        return {"key": "insufficient", "label": TREND_LABELS["insufficient"],
                "n_windows": len(pts), "delta": delta}
    slope = _slope(pts)
    key = "increase" if slope > delta else ("decrease" if slope < -delta else "stable")
    projected = min(1.0, max(0.0, pts[-1] + slope))
    return {
        "key": key, "label": TREND_LABELS[key],
        "slope_per_window": round(slope, 4),
        "last_change": round(pts[-1] - pts[-2], 4),
        "projected_Z": round(projected, 4),
        "projected_level": threat_level(projected),
        "n_windows": len(pts), "delta": delta,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Головна функція
# ─────────────────────────────────────────────────────────────────────────────

def assess_threat(assessments: list[dict], *, start=None, end=None,
                  spheres: list[str] | None = None,
                  window_days: int = DEFAULT_WINDOW_DAYS,
                  delta: float = DEFAULT_TREND_DELTA) -> dict:
    """Макрооцінка за період [start; end] на основі збережених DIMS-оцінок.

    Події, раніші за start, використовуються лише як історія — для першої
    появи напряму (K_т рахується від неї, бо тривалість — властивість ІВ,
    а не вікна спостереження). Подія належить періоду за датою останньої
    публікації. Тренд — за послідовними вікнами по window_days днів; для
    кожного вікна оцінка повторюється на подіях цього вікна з тією ж історією.
    """
    if window_days < 1:
        raise ValueError("window_days має бути ≥ 1.")
    events_all = [e for e in (_event_from_assessment(a) for a in assessments or []) if e]
    warnings: list[str] = []
    if not events_all:
        return {"ok": True, "period": None, "spheres": [], "warnings": ["Немає оцінених подій."],
                "methodology": _METHODOLOGY}
    start_d = _parse_date(start) or min(e["last"] for e in events_all)
    end_d = _parse_date(end) or max(e["last"] for e in events_all)
    if end_d < start_d:
        raise ValueError("Кінець періоду раніший за початок.")
    spheres = [canon_sphere(s) for s in spheres] if spheres else None

    history = [e for e in events_all if e["first"] <= end_d]
    events = [e for e in history if start_d <= e["last"] <= end_d]
    days = (end_d - start_d).days + 1
    if days < DEFAULT_WINDOW_DAYS:
        warnings.append(f"Період {days} дн. коротший за тиждень — за прототипом за менший "
                        "період неможливо виявити системність ІВ і визначити форму ІБ (с. 5).")
    if any(e["direction"] == UNASSIGNED_DIRECTION for e in events):
        warnings.append("Частина подій без напряму ІВ (gur.direction) — згруповані як "
                        "«unassigned»; потрібне тегування аналітиком.")
    if any(e["sphere_assumed"] for e in events):
        warnings.append("Для частини подій сферу не вказано — прийнято воєнну (типова "
                        "сфера прототипу).")

    result = _evaluate_period(events, history, spheres)

    # Тренд: ряд Z по вікнах для кожної сфери.
    windows = []
    ws = start_d
    while ws <= end_d:
        we = min(ws + timedelta(days=window_days - 1), end_d)
        windows.append((ws, we))
        ws = we + timedelta(days=1)
    series: dict[str, list[dict]] = defaultdict(list)
    for ws, we in windows:
        win_events = [e for e in history if ws <= e["last"] <= we]
        win_hist = [e for e in history if e["first"] <= we]
        win_res = _evaluate_period(win_events, win_hist, spheres) if win_events else {}
        for s in result:
            r = win_res.get(s)
            series[s].append({"start": ws.isoformat(), "end": we.isoformat(),
                              "Z": r["Z"] if r else None,
                              "level": (r["level"] or {}).get("label") if r else None,
                              "n_events": sum(d["facts"]["n_events"] for d in r["directions"]) if r else 0})

    spheres_out = []
    for s, r in result.items():
        r["trend"] = trend_forecast([p["Z"] for p in series[s]], delta=delta)
        r["series"] = series[s]
        spheres_out.append(_strip_private(r))
        if r["Z_partial"]:
            warnings.append(f"Сфера {r['sphere_label']}: Z обчислено з неповних базових "
                            "показників — значення не відповідає прототипу.")

    src_counts: Counter = Counter()
    for r in spheres_out:
        for d in r["directions"]:
            for k, v in d["indicator_sources"].items():
                src_counts[f"{k}:{v or 'missing'}"] += 1

    return {
        "ok": True,
        "period": {"start": start_d.isoformat(), "end": end_d.isoformat(), "days": days,
                   "window_days": window_days, "n_events": len(events),
                   "n_history_events": len(history)},
        "spheres": spheres_out,
        "data_quality": dict(sorted(src_counts.items())),
        "warnings": warnings,
        "params": {"trend_delta": delta, "form_tie_tol": DEFAULT_FORM_TIE_TOL,
                   "proxy_negative_min_grade": PROXY_NEGATIVE_MIN_GRADE,
                   "provisional": True},
        "methodology": _METHODOLOGY,
    }


_METHODOLOGY = ("Макрорівень: прототип — Методика виявлення, аналізу та оцінювання "
                "інформаційних загроз державі у воєнній сфері (ГУР МО України, 2016); "
                "доповнення (інструменти впливу, ЦА, факти, прогноз) і автоматизація "
                "базових показників — Шерстюк Є.І., НУОУ. Параметри реалізації провізорні.")
