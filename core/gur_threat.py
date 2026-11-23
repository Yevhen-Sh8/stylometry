#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/gur_threat.py
==================
Макрорівень оцінювання: від DIMS-оцінок окремих подій до форми реалізації
інформаційної загрози (ІЗ) — вона ж форма ведення інформаційної боротьби (ІБ) —
та рівня ІЗ за напрямами й сферами за період.

Прототип — «Методика виявлення, аналізу та оцінювання інформаційних загроз
державі у воєнній сфері» (ГУР МО України, 2016), блок аналізу ІЗ, етапи 1–4
(позначення в тексті ↔ ключі в коді: K_i, K_т↔K_t, K_д↔K_d, K_о↔K_o, K_j^н↔K_n):

    K_i   — рівень інтенсивності: частка негативних повідомлень за період (с. 24);
    K_т   — тривалість, K_т = x / (x + a); a = 40,56 для x ≤ 365 дн., інакше 19,21
            (формули 1–3, табл. 4);
    K_д   — поширеність джерел: 0,25 / 0,5 / 0,75 / 1,0 (с. 26);
    K_о   — масштабність об'єктів: 0,1–0,3 / 0,31–0,7 / 0,71–1,0 (с. 25–26);
    K_j^н = (K_i + K_т + K_д + K_о) / 4                       (формула 4);
    форма реалізації ІЗ — табл. 5 (с. 27);
    Z_k^c = Σ K_j^н / N                                       (формула 5);
    рівень ІЗ — табл. 6 (с. 28).

Результат містить ДВА шари:

    prototype — те, що дає прототип без правил реалізації: форми напрямів, чий
                діапазон K_j^н за табл. 5 містить значення, Z_k^c і рівень;
    improved  — удосконалення автора дисертації:
                * розв'язання неоднозначностей табл. 5 (перекриття й розрив);
                * узагальнена форма сфери з правилом с. 28;
                * instruments — інструменти впливу: джерела, скоординовані джерела
                  (стилометричні пари з вердиктом strong і кластери технічних копій),
                  залучені особи;
                * target_audience — цільова аудиторія (ЦА) поряд із K_о;
                * facts — факти, на яких ґрунтується висновок про форму;
                * trend — оцінка тенденції: зменшення / збільшення / продовження
                  на тому ж рівні.

Позначки походження кожного базового показника показують, що обчислено з даних,
а що введено людиною: auto, fallback, expert, expert_subset, expert_midpoint,
registry, proxy. З даних моніторингу автоматично обчислюється лише K_т; K_i, K_д,
K_о у відповідному прототипу режимі вводить аналітик або реєстр джерел.

Відповідність прототипу (conformant) — лише коли всі чотири показники наявні,
K_i — expert, K_т — auto. Інакше значення провізорні й не можуть слугувати
підтвердженням методики (у режимі proxy K_i макрорівень залежить від R_DIMS).

Формула R_DIMS і шкала грейдів F…SSS тут не змінюються. Модуль — чисті функції
без I/O. Правила реалізації описано в docs/gur2016_macro_level_ua.md (розд. 5).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

# ─────────────────────────────────────────────────────────────────────────────
#  Довідники прототипу
# ─────────────────────────────────────────────────────────────────────────────

# Сфери — табл. 1 прототипу (8 сфер). У табл. 3 перелік інший (є «інформаційна»),
# тому власні коди сфер також приймаються (нормалізуються до нижнього регістру).
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

# Рівень інтенсивності K_i (с. 24): (lo; hi].
INTENSITY_LEVELS = [
    (0.20, "low", "низька"),
    (0.40, "medium", "середня"),
    (0.60, "elevated", "підвищена"),
    (0.80, "high", "висока"),
    (1.00, "critical", "критична"),
]

DURATION_A_UP_TO_YEAR = 40.56
DURATION_A_OVER_YEAR = 19.21

REACH_VALUES = {"local": 0.25, "regional": 0.50, "national": 0.75, "international": 1.00}
_REACH_ALIASES = {
    "місцевий": "local", "регіональний": "regional",
    "загальнодержавний": "national", "національний": "national",
    "міжнародний": "international",
}

OBJECT_SCALES = {"single": (0.10, 0.30), "group": (0.31, 0.70), "mass": (0.71, 1.00)}
_OBJECT_ALIASES = {"одиночний": "single", "груповий": "group", "масовий": "mass"}
OBJECT_SCALE_LABELS = {"single": "одиночний об'єкт", "group": "груповий об'єкт",
                       "mass": "масовий об'єкт"}

# Області значень показників — для інтервалу K_j^н, коли показника бракує.
INDICATOR_DOMAINS = {"K_i": (0.0, 1.0), "K_t": (0.0, 1.0), "K_d": (0.25, 1.0),
                     "K_o": (0.10, 1.0)}

# Рівень ІЗ — табл. 6: (lo; hi], 0 належить «низькому».
THREAT_LEVELS = [
    (0.25, "low", "низький"),
    (0.50, "elevated", "підвищений"),
    (0.75, "high", "високий"),
    (1.00, "critical", "критичний"),
]

# Форми — табл. 5 (с. 27): межі базових показників і K_j^н (замкнені інтервали).
# Розриви покомпонентних діапазонів (напр. K_т між 0,15 і 0,26) — властивість прототипу.
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

_GRADE_ORDER = ["F", "B", "S", "SS", "SSS"]
_GRADE_RANK = {g: i for i, g in enumerate(_GRADE_ORDER)}

# ── Провізорні параметри реалізації (рішення автора; калібруються апробацією) ──
PROXY_NEGATIVE_MIN_GRADE = "S"   # proxy K_i: матеріали події з грейдом ≥ S — «негативні»
EPISODE_GAP_DAYS = 30            # розрив активності напряму, що починає новий епізод ІВ (K_т)
DEFAULT_WINDOW_DAYS = 7          # мінімальний період узагальнення за прототипом (с. 5)
DEFAULT_TREND_DELTA = 0.05       # поріг нахилу Z для тенденції
DEFAULT_FORM_TIE_TOL = 0.05      # допуск рівновіддаленості профілів у зонах перекриття
CRITICAL_DIRECTION_LEVEL = "critical"
_TREND_POINTS = 4
_MAX_LIST = 50

TREND_LABELS = {
    "increase": "збільшення",
    "decrease": "зменшення",
    "stable": "продовження на тому ж рівні",
    "insufficient": "недостатньо даних",
}
GUR_KEYS = ("direction", "direction_label", "sphere", "target_scale", "target_value",
            "target_audience", "reach", "source_reach", "registry_reach",
            "n_negative", "n_total", "persons")


# ─────────────────────────────────────────────────────────────────────────────
#  Елементарні показники
# ─────────────────────────────────────────────────────────────────────────────

def duration_coefficient(days: float) -> float:
    """K_т = x / (x + a) — формули 1–3 прототипу. Дві константи a відтворено
    як є; через це на межі року функція має стрибок (властивість прототипу).
    Значення табл. 4 відтворюються з точністю до округлення прототипу."""
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
    return {"key": table[-1][1], "label": table[-1][2]}


def intensity_level(k_i: float) -> dict:
    """Рівень інтенсивності K_i (с. 24): (lo; hi]."""
    return _level(k_i, INTENSITY_LEVELS)


def threat_level(z: float) -> dict:
    """Рівень ІЗ за табл. 6: [0; 0,25] низький, (0,25; 0,5] підвищений,
    (0,5; 0,75] високий, (0,75; 1,0] критичний."""
    return _level(z, THREAT_LEVELS)


def reach_value(level: str) -> float:
    return REACH_VALUES[_canon(level, REACH_VALUES, _REACH_ALIASES, "рівень поширеності")]


def object_scale_value(scale: str, value: float | None = None) -> tuple[float, str]:
    """K_о: явне експертне значення або (якщо його немає) середина діапазону
    категорії — останнє є припущенням реалізації (expert_midpoint)."""
    key = _canon(scale, OBJECT_SCALES, _OBJECT_ALIASES, "масштабність об'єктів")
    lo, hi = OBJECT_SCALES[key]
    if value is not None:
        return float(value), "expert"
    return round((lo + hi) / 2, 4), "expert_midpoint"


def normalized_indicator(k_i, k_t, k_d, k_o) -> tuple[float | None, list[str], tuple]:
    """K_j^н за формулою 4. Якщо показника бракує, K_j^н не визначається
    (None), а повертається інтервал можливих значень за областями відсутніх
    показників: прототип вимагає всіх чотирьох."""
    parts = {"K_i": k_i, "K_t": k_t, "K_d": k_d, "K_o": k_o}
    missing = [k for k, v in parts.items() if v is None]
    lo = sum(v if v is not None else INDICATOR_DOMAINS[k][0] for k, v in parts.items()) / 4
    hi = sum(v if v is not None else INDICATOR_DOMAINS[k][1] for k, v in parts.items()) / 4
    if missing:
        return None, missing, (round(lo, 4), round(hi, 4))
    return lo, [], (round(lo, 4), round(lo, 4))


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
    v = str(value or "").strip().lower()
    if not v:
        return DEFAULT_SPHERE
    if v in SPHERES:
        return v
    if v in _SPHERE_ALIASES:
        return _SPHERE_ALIASES[v]
    if len(v) > 64:
        raise ValueError("sphere: не довше 64 символів.")
    return v


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


def _reach_map(value, what: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{what} має бути об'єктом {{джерело: рівень}}.")
    return {str(k)[:200]: _canon(v, REACH_VALUES, _REACH_ALIASES, what)
            for k, v in list(value.items())[:500]}


def normalise_gur_meta(meta) -> dict:
    """Валідує й нормалізує метадані події для макрорівня. Повертає {} для
    порожнього вводу. Невідомі ключі ігноруються. Помилки — ValueError."""
    if meta is None or meta == {}:
        return {}
    if not isinstance(meta, dict):
        raise ValueError("gur має бути об'єктом.")
    out: dict = {}
    direction = str(meta.get("direction") or "").strip().lower()
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
    for key in ("source_reach", "registry_reach"):
        if meta.get(key):
            out[key] = _reach_map(meta[key], f"gur.{key}")
    for key in ("n_negative", "n_total"):
        if meta.get(key) is not None and meta.get(key) != "":
            try:
                n = int(meta[key])
            except (TypeError, ValueError):
                raise ValueError(f"gur.{key} має бути цілим ≥ 0.")
            if n < 0:
                raise ValueError(f"gur.{key} має бути цілим ≥ 0.")
            out[key] = n
    if "n_negative" in out and "n_total" not in out:
        raise ValueError("gur.n_negative потребує gur.n_total — загальної кількості "
                         "повідомлень (з копіями) за період, від якої рахується частка.")
    if "n_negative" in out and out["n_negative"] > out["n_total"]:
        raise ValueError("gur.n_negative не може перевищувати gur.n_total.")
    persons = _str_list(meta.get("persons"), "gur.persons")
    if persons:
        out["persons"] = persons
    ek = meta.get("expert_keys")
    if ek:
        if not isinstance(ek, list):
            raise ValueError("gur.expert_keys має бути списком.")
        out["expert_keys"] = sorted({k for k in ek if k in GUR_KEYS and k in out})
        if not out["expert_keys"]:
            out.pop("expert_keys")
    return out


def merge_gur(previous: dict | None, incoming: dict | None, *, expert: bool) -> dict:
    """Злиття метаданих. Значення, введені аналітиком (expert_keys), мають
    пріоритет над даними БД ІАС; ввід аналітика (expert=True) позначає свої
    ключі як експертні. Ключ зі значенням None видаляється."""
    prev = dict(previous or {})
    inc = dict(incoming or {})
    expert_keys = set(prev.get("expert_keys") or [])
    merged = {**prev, **inc}
    if expert:
        expert_keys |= {k for k, v in inc.items() if v is not None and k in GUR_KEYS}
        expert_keys -= {k for k, v in inc.items() if v is None}
    else:
        for k in expert_keys:
            if k in prev:
                merged[k] = prev[k]
    merged = {k: v for k, v in merged.items() if v is not None}
    merged["expert_keys"] = sorted(expert_keys)
    return normalise_gur_meta(merged)


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
    n_mat = int(stats.get("n_materials") or stats.get("n_unique_materials") or 0)
    direction = str(gur.get("direction") or "").strip().lower() or UNASSIGNED_DIRECTION
    return {
        "event_id": str(a["event_id"]),
        "sphere": canon_sphere(gur.get("sphere")),
        "sphere_assumed": not gur.get("sphere"),
        "direction": direction,
        "direction_label": gur.get("direction_label"),
        "first": min(first, last),
        "last": max(first, last),
        "dates_source": dates_source,
        "grade": grade,
        "n_materials": n_mat,
        "sources": dict(stats.get("sources") or {}),
        "flagged_pairs": list(coord.get("flagged_pairs") or []),
        "copy_clusters": list(coord.get("copy_clusters") or []),
        "gur": gur,
    }


def _overlaps(e: dict, start: date, end: date) -> bool:
    return e["first"] <= end and e["last"] >= start


# ─────────────────────────────────────────────────────────────────────────────
#  Базові показники напряму (етап 2)
# ─────────────────────────────────────────────────────────────────────────────

def _coordinated_sources(events: list[dict]) -> Counter:
    """Скоординовані джерела: стилометричні пари з вердиктом strong (надійні за
    похибкою й обсягом тексту) і кластери технічних копій щонайменше з двох
    джерел. Пари possible до координації не зараховуються."""
    c: Counter = Counter()
    for e in events:
        for p in e["flagged_pairs"]:
            if p.get("verdict") == "strong":
                for s in (p.get("a"), p.get("b")):
                    if s:
                        c[s] += 1
        for cl in e["copy_clusters"]:
            if int(cl.get("n_sources") or len(cl.get("sources") or [])) >= 2:
                for s in cl.get("sources") or []:
                    c[s] += 1
    return c


def _episode_days(intervals: list[tuple[date, date]], end: date, gap: int) -> tuple[int, date]:
    """Тривалість поточного епізоду ІВ на дату end: інтервали активності
    напряму зливаються, якщо розрив між ними не більший за gap днів; береться
    останній епізод, що почався не пізніше end. x — календарні дні включно."""
    ivs = sorted((a, min(b, end)) for a, b in intervals if a <= end)
    ep_start, ep_end = ivs[0]
    for a, b in ivs[1:]:
        if (a - ep_end).days > gap:
            ep_start, ep_end = a, b
        else:
            ep_end = max(ep_end, b)
    return (ep_end - ep_start).days + 1, ep_start


def _direction_indicators(events: list[dict], history: list[dict], end: date,
                          gap: int, k_t_override: float | None = None) -> dict:
    # K_i — частка негативних повідомлень: лише лічильники аналітика; інакше proxy
    expert = [e for e in events if e["gur"].get("n_negative") is not None]
    if expert:
        neg = sum(e["gur"]["n_negative"] for e in expert)
        tot = sum(e["gur"]["n_total"] for e in expert)
        k_i_src = "expert" if len(expert) == len(events) else "expert_subset"
    else:
        neg = tot = 0
        for e in events:
            is_neg = _GRADE_RANK.get(e["grade"] or "", -1) >= _GRADE_RANK[PROXY_NEGATIVE_MIN_GRADE]
            tot += e["n_materials"]
            neg += e["n_materials"] if is_neg else 0
        k_i_src = "proxy"
    k_i = (neg / tot) if tot else None

    # K_т — тривалість поточного епізоду ІВ напряму (з урахуванням історії)
    days, ep_start = _episode_days([(e["first"], e["last"]) for e in history], end, gap)
    k_t = duration_coefficient(days) if k_t_override is None else k_t_override
    k_t_src = "fallback" if any(e["dates_source"] == "fallback" for e in history) else "auto"

    # K_д — найширший досягнутий рівень (тлумачення реалізації: максимум)
    expert_levels, registry_levels = [], []
    for e in events:
        g = e["gur"]
        if g.get("reach"):
            expert_levels.append(g["reach"])
        expert_levels.extend((g.get("source_reach") or {}).values())
        registry_levels.extend((g.get("registry_reach") or {}).values())
    levels = expert_levels + registry_levels
    k_d = max((REACH_VALUES[r] for r in levels), default=None)
    widest = max(levels, key=lambda r: REACH_VALUES[r]) if levels else None
    k_d_src = None if k_d is None else ("expert" if expert_levels else "registry")

    # K_о — найбільша масштабність серед подій (явні значення й середини категорій)
    cand = []
    for e in events:
        g = e["gur"]
        if g.get("target_value") is not None:
            cand.append((g["target_value"], "expert"))
        elif g.get("target_scale"):
            cand.append(object_scale_value(g["target_scale"]))
    k_o, k_o_src = max(cand, key=lambda t: t[0]) if cand else (None, None)
    scale = None if k_o is None else next(
        (s for s, (lo, hi) in OBJECT_SCALES.items() if lo - 1e-9 <= k_o <= hi + 1e-9), None)

    return {
        "K_i": None if k_i is None else round(k_i, 4),
        "K_t": round(k_t, 4),
        "K_d": k_d,
        "K_o": None if k_o is None else round(k_o, 4),
        "sources": {"K_i": k_i_src if k_i is not None else None, "K_t": k_t_src,
                    "K_d": k_d_src, "K_o": k_o_src},
        "details": {
            "negative_messages": neg, "total_messages": tot,
            "intensity_level": intensity_level(k_i)["label"] if k_i is not None else None,
            "episode_days": days, "episode_start": ep_start.isoformat(),
            "episode_gap_days": gap,
            "widest_reach": widest, "target_scale": scale,
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


def profile_distance(indicators: dict, form: str) -> float:
    """Сума інтервальних відстаней базових показників до профілю форми (табл. 5)."""
    prof = FORM_PROFILES[form]
    return round(sum(_gap(float(indicators[k]), *prof[k])
                     for k in ("K_i", "K_t", "K_d", "K_o") if indicators.get(k) is not None), 4)


def classify_form(indicators: dict, k_n: float, tie_tol: float = DEFAULT_FORM_TIE_TOL) -> dict:
    """Форма напряму за табл. 5.

    Прототип: форма — та, чий діапазон K_j^н містить значення (prototype_forms).
    Якщо така форма одна — вона і є результатом. Правило реалізації діє лише
    там, де прототип неоднозначний: у перекриттях (0,62–0,69; 0,69–0,88) і в
    розриві 0,34–0,37 обирається форма з найменшою відстанню базових показників
    до профілю; форми в межах tie_tol від неї лишаються кандидатами."""
    by_kn = [f for f in FORMS
             if FORM_PROFILES[f]["K_n"][0] - 1e-9 <= k_n <= FORM_PROFILES[f]["K_n"][1] + 1e-9]
    distance = {f: profile_distance(indicators, f) for f in FORMS}
    if len(by_kn) == 1:
        form, cands, rule = by_kn[0], by_kn, "prototype_K_n"
    else:
        pool = by_kn or ["attack", "action"]          # розрив 0,34–0,37 між атакою й акцією
        form = min(pool, key=lambda f: (distance[f], FORM_RANK[f]))
        cands = sorted((f for f in pool if distance[f] - distance[form] <= tie_tol + 1e-12),
                       key=FORM_RANK.get)
        rule = "profile_distance_in_overlap" if by_kn else "profile_distance_in_gap"
    return {
        "form": form,
        "form_label": FORM_PROFILES[form]["label"],
        "prototype_forms": by_kn,
        "candidates": cands,
        "ambiguous": len(cands) > 1,
        "in_K_n_gap": not by_kn,
        "rule": rule,
        "distance": distance,
    }


def _linked(coord_a: set[str], coord_b: set[str]) -> bool:
    """Зв'язок між напрямами/сферами — proxy «змістовних взаємозв'язків» (с. 28):
    спільне СКООРДИНОВАНЕ джерело (пара strong або кластер копій). Звичайні
    спільні джерела не враховуються: великі ЗМІ присутні в усіх тематиках."""
    return bool(coord_a & coord_b)


# ─────────────────────────────────────────────────────────────────────────────
#  Оцінка напряму і сфери
# ─────────────────────────────────────────────────────────────────────────────

def _direction_result(sphere: str, direction: str, events: list[dict], history: list[dict],
                      end: date, gap: int, k_t_override: float | None = None) -> dict:
    ind = _direction_indicators(events, history, end, gap, k_t_override)
    k_n, missing, k_n_range = normalized_indicator(ind["K_i"], ind["K_t"], ind["K_d"], ind["K_o"])
    conformant = (not missing and ind["sources"]["K_i"] == "expert"
                  and ind["sources"]["K_t"] == "auto")
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
    pairs, clusters = [], []
    for e in events:
        for p in e["flagged_pairs"]:
            pairs.append({"event_id": e["event_id"], "a": p.get("a"), "b": p.get("b"),
                          "delta": p.get("delta"), "verdict": p.get("verdict")})
        for c in e["copy_clusters"]:
            clusters.append({"event_id": e["event_id"], "sources": c.get("sources"),
                             "n_sources": c.get("n_sources"),
                             "first_source": c.get("first_source"),
                             "first_published_at": c.get("first_published_at")})
    pairs.sort(key=lambda p: (p["verdict"] != "strong",
                              p["delta"] if p["delta"] is not None else 9e9))
    clusters.sort(key=lambda c: -(c["n_sources"] or 0))
    grades = [e["grade"] for e in events if e["grade"] in _GRADE_RANK]
    label = labels[0] if labels else (MILITARY_DIRECTIONS.get(direction) if sphere == "military" else None)
    if direction == UNASSIGNED_DIRECTION:
        label = "Напрям не визначено (потрібне тегування аналітиком)"

    return {
        "direction": direction,
        "direction_label": label,
        "tagged": direction != UNASSIGNED_DIRECTION,
        "indicators": {k: ind[k] for k in ("K_i", "K_t", "K_d", "K_o")},
        "indicator_sources": ind["sources"],
        "indicator_details": ind["details"],
        "K_n": None if k_n is None else round(k_n, 4),
        "K_n_range": k_n_range,
        "missing_indicators": missing,
        "conformant": conformant,
        "form": form,
        "instruments": {
            "sources": [{"source": s, "materials": n} for s, n in src_counter.most_common(_MAX_LIST)],
            "coordinated_sources": [{"source": s, "links": n} for s, n in coord.most_common(_MAX_LIST)],
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
            "first_seen": min(e["first"] for e in events).isoformat(),
            "last_seen": max(e["last"] for e in events).isoformat(),
            "n_materials": sum(e["n_materials"] for e in events),
            "n_flagged_pairs": len(pairs),
            "n_strong_pairs": sum(1 for p in pairs if p["verdict"] == "strong"),
            "n_copy_clusters": len(clusters),
            "max_grade": max(grades, key=_GRADE_RANK.get) if grades else None,
            "closest_pairs": pairs[:5],
            "largest_copy_clusters": clusters[:5],
        },
        "_coord": set(coord),
    }


def _sphere_form(directions: list[dict], cross_sphere_linked: bool) -> dict:
    """Узагальнена форма сфери — об'єкт удосконаленої методики (у прототипі
    форма належить напряму, рівень — сфері).

    Правила:
      * за основу береться найвища форма серед тегованих напрямів;
      * с. 28 прототипу застосовується лише до неоднозначності «операція/
        кампанія» (основна форма — операція чи кампанія або обидві серед
        кандидатів): кампанія — якщо є зв'язок з іншою сферою І базові
        показники напряму відповідають профілю кампанії; інакше — операція;
      * кількість напрямів форму не підвищує (табл. 5 називає її необхідною,
        але не достатньою ознакою операції) — зв'язки напрямів лише звітуються."""
    scored = [d for d in directions if d["form"] and d["tagged"]]
    if not scored:
        return {"form": None, "form_label": None, "ambiguous": False,
                "basis": "немає тегованих напрямів з повним набором базових показників"}
    top = max(scored, key=lambda d: (FORM_RANK[d["form"]["form"]], d["K_n"]))
    form = top["form"]["form"]
    basis = [f"найвища форма серед напрямів — «{FORM_PROFILES[form]['label']}» "
             f"(напрям {top['direction']})"]
    heavy = [d for d in scored if d["form"]["form"] in ("operation", "campaign")
             or {"operation", "campaign"} <= set(d["form"]["candidates"])]
    if heavy:
        campaign_fit = [d for d in heavy
                        if profile_distance(d["indicators"], "campaign") <= DEFAULT_FORM_TIE_TOL]
        if cross_sphere_linked and campaign_fit:
            form = "campaign"
            basis.append("с. 28: є зв'язок з іншою сферою (спільні скоординовані джерела) "
                         "і показники відповідають профілю кампанії")
        else:
            form = "operation"
            why = ("немає зв'язку з іншими сферами" if not cross_sphere_linked
                   else "показники не відповідають профілю кампанії")
            basis.append(f"с. 28: {why} → операція")
    linked_dirs = any(_linked(a["_coord"], b["_coord"])
                      for i, a in enumerate(scored) for b in scored[i + 1:])
    return {
        "form": form,
        "form_label": FORM_PROFILES[form]["label"],
        "basis": "; ".join(basis),
        "ambiguous": any(d["form"]["ambiguous"] for d in scored),
        "linked_directions": linked_dirs,
        "linked_other_spheres": cross_sphere_linked,
    }


def _sphere_z(directions: list[dict]) -> dict:
    """Z_k^c за формулою 5. N — кількість тегованих напрямів сфери з повним
    набором базових показників за період (тлумачення реалізації)."""
    usable = [d for d in directions if d["tagged"] and d["K_n"] is not None]
    excluded = [d["direction"] for d in directions if d not in usable]
    if not usable:
        return {"Z": None, "N": 0, "level": None, "conformant": False, "excluded": excluded}
    z = sum(d["K_n"] for d in usable) / len(usable)
    return {"Z": round(z, 4), "N": len(usable), "level": threat_level(z),
            "conformant": all(d["conformant"] for d in usable) and not excluded,
            "excluded": excluded}


def _evaluate_period(events: list[dict], history: list[dict], start: date, end: date,
                     spheres: list[str] | None, gap: int,
                     k_t_override: dict | None = None) -> dict:
    by_sphere: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        by_sphere[e["sphere"]].append(e)
    coord_by_sphere = {s: set(_coordinated_sources(evs)) for s, evs in by_sphere.items()}
    out = {}
    for s, evs in sorted(by_sphere.items()):
        if spheres and s not in spheres:
            continue
        linked = sorted(o for o in by_sphere if o != s and _linked(coord_by_sphere[s], coord_by_sphere[o]))
        by_dir: dict[str, list[dict]] = defaultdict(list)
        for e in evs:
            by_dir[e["direction"]].append(e)
        directions = []
        for d, devs in sorted(by_dir.items()):
            hist = [e for e in history if e["sphere"] == s and e["direction"] == d]
            override = (k_t_override or {}).get((s, d))
            directions.append(_direction_result(s, d, devs, hist, end, gap, override))
        zinfo = _sphere_z(directions)
        crit = [d["direction"] for d in directions
                if d["tagged"] and d["K_n"] is not None
                and threat_level(d["K_n"])["key"] == CRITICAL_DIRECTION_LEVEL]
        out[s] = {
            "sphere": s,
            "sphere_label": SPHERES.get(s, s),
            "n_directions": len(directions),
            "prototype": {
                "Z": zinfo["Z"], "N": zinfo["N"], "level": zinfo["level"],
                "conformant": zinfo["conformant"],
                "excluded_directions": zinfo["excluded"],
                "direction_forms": {d["direction"]: (d["form"] or {}).get("prototype_forms")
                                    for d in directions},
            },
            "improved": {
                "form": _sphere_form(directions, bool(linked)),
                "critical_direction": {
                    "flag": bool(crit) and (zinfo["level"] or {}).get("key") != "critical",
                    "directions": crit,
                    "note": ("K_j^н напряму в критичній зоні табл. 6 (перенесення шкали Z на "
                             "напрям); середнє за формулою 5 його «розчиняє» — ознака "
                             "попереджувальна, Z не змінює"),
                },
            },
            "linked_spheres": linked,
            "directions": directions,
        }
    return out


# ─────────────────────────────────────────────────────────────────────────────
#  Оцінка тенденції (доповнення автора)
# ─────────────────────────────────────────────────────────────────────────────

def _slope(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den if den else 0.0


def trend_forecast(points: list[tuple[int, float]], delta: float = DEFAULT_TREND_DELTA) -> dict:
    """Оцінка тенденції за рядом (індекс вікна, Z) — лише повні вікна.

    Нахил МНК за останніми (до 4) вікнами з реальними індексами: > δ —
    збільшення, < −δ — зменшення, інакше — продовження на тому ж рівні.
    Лінійна екстраполяція на одне вікно без довірчого інтервалу; δ провізорний."""
    pts = points[-_TREND_POINTS:]
    if len(pts) < 2:
        return {"key": "insufficient", "label": TREND_LABELS["insufficient"],
                "n_windows": len(pts), "delta": delta}
    xs = [float(i) for i, _ in pts]
    ys = [z for _, z in pts]
    slope = _slope(xs, ys)
    key = "increase" if slope > delta else ("decrease" if slope < -delta else "stable")
    projected = min(1.0, max(0.0, ys[-1] + slope))
    return {
        "key": key, "label": TREND_LABELS[key],
        "slope_per_window": round(slope, 4),
        "projected_window_Z": round(projected, 4),
        "projected_window_level": threat_level(projected),
        "scale_note": "прогнозоване Z стосується наступного вікна, а не всього періоду",
        "n_windows": len(pts), "delta": delta,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Головна функція
# ─────────────────────────────────────────────────────────────────────────────

def assess_threat(assessments: list[dict], *, start=None, end=None,
                  spheres: list[str] | None = None,
                  window_days: int = DEFAULT_WINDOW_DAYS,
                  delta: float = DEFAULT_TREND_DELTA,
                  episode_gap_days: int = EPISODE_GAP_DAYS) -> dict:
    """Макрооцінка за період [start; end] на основі збережених DIMS-оцінок.

    * Подія належить періоду (і вікну), якщо інтервал її публікацій перетинається
      з ним; тривала подія потрапляє в усі вікна, які охоплює.
    * Події, раніші за start, — історія для K_т (епізод ІВ напряму).
    * Тенденція: для кожного повного вікна оцінка повторюється на подіях вікна
      з K_т, зафіксованим на рівні основного періоду (щоб «старіння» напряму
      не давало штучного зростання Z). Вікно без подій має Z = 0 («ІВ не
      виявлено»); неповне останнє вікно в тенденцію не входить.
    """
    if window_days < 1:
        raise ValueError("window_days має бути ≥ 1.")
    req_start, req_end = _parse_date(start), _parse_date(end)
    if req_start and req_end and req_end < req_start:
        raise ValueError("Кінець періоду раніший за початок.")
    spheres = [canon_sphere(s) for s in spheres] if spheres else None
    events_all = [e for e in (_event_from_assessment(a) for a in assessments or []) if e]
    if not events_all:
        return {"ok": True, "period": None, "spheres": [], "warnings": ["Немає оцінених подій."],
                "params": _params(delta, episode_gap_days, window_days),
                "methodology": _METHODOLOGY}
    start_d = req_start or min(e["first"] for e in events_all)
    end_d = req_end or max(e["last"] for e in events_all)

    history = [e for e in events_all if e["first"] <= end_d]
    events = [e for e in history if _overlaps(e, start_d, end_d)]
    days = (end_d - start_d).days + 1
    warnings: list[str] = []
    if days < DEFAULT_WINDOW_DAYS:
        warnings.append(f"Період {days} дн. коротший за тиждень — за прототипом за менший "
                        "період неможливо виявити системність ІВ і визначити форму (с. 5).")
    if window_days < DEFAULT_WINDOW_DAYS:
        warnings.append(f"Вікно тенденції {window_days} дн. коротше за мінімальний період "
                        "прототипу (7 дн.).")
    if any(e["direction"] == UNASSIGNED_DIRECTION for e in events):
        warnings.append("Частина подій без напряму ІВ — показані як «unassigned», але не "
                        "входять у Z і правила форми; потрібне тегування аналітиком.")
    if any(e["sphere_assumed"] for e in events):
        warnings.append("Для частини подій сферу не вказано — прийнято воєнну (типова "
                        "сфера прототипу).")
    if any(e["dates_source"] == "fallback" for e in events):
        warnings.append("Для частини подій немає дат публікацій — використано дату оцінки; "
                        "K_т може бути завищений, результат не відповідає прототипу.")

    result = _evaluate_period(events, history, start_d, end_d, spheres, episode_gap_days)
    k_t_main = {(s, d["direction"]): d["indicators"]["K_t"]
                for s, r in result.items() for d in r["directions"]}

    # Тенденція за вікнами
    windows = []
    ws = start_d
    while ws <= end_d:
        we = ws + timedelta(days=window_days - 1)
        windows.append((ws, min(we, end_d), we <= end_d))
        ws = we + timedelta(days=1)
    series: dict[str, list[dict]] = defaultdict(list)
    for idx, (ws, we, full) in enumerate(windows):
        win_events = [e for e in events if _overlaps(e, ws, we)]
        win_hist = [e for e in history if e["first"] <= we]
        win_res = (_evaluate_period(win_events, win_hist, ws, we, spheres, episode_gap_days,
                                    k_t_main) if win_events else {})
        for s in result:
            r = win_res.get(s)
            z = r["prototype"]["Z"] if r else None
            no_events = r is None
            series[s].append({"index": idx, "start": ws.isoformat(), "end": we.isoformat(),
                              "full": full, "no_events": no_events,
                              "Z": 0.0 if no_events else z,
                              "level": (r["prototype"]["level"] or {}).get("label") if r else None})

    spheres_out = []
    for s, r in result.items():
        pts = [(p["index"], p["Z"]) for p in series[s] if p["full"] and p["Z"] is not None]
        r["improved"]["trend"] = trend_forecast(pts, delta=delta)
        r["improved"]["series"] = series[s]
        if not r["prototype"]["conformant"]:
            warnings.append(f"Сфера {r['sphere_label']}: результат не відповідає прототипу "
                            "(неповні показники, proxy K_i або нетеговані напрями) — провізорний.")
        spheres_out.append(_strip_private(r))

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
        "params": _params(delta, episode_gap_days, window_days),
        "methodology": _METHODOLOGY,
    }


def _params(delta, gap, window_days) -> dict:
    return {"trend_delta": delta, "form_tie_tol": DEFAULT_FORM_TIE_TOL,
            "episode_gap_days": gap, "window_days": window_days,
            "proxy_negative_min_grade": PROXY_NEGATIVE_MIN_GRADE, "provisional": True}


def _strip_private(obj):
    if isinstance(obj, dict):
        return {k: _strip_private(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [_strip_private(x) for x in obj]
    return obj


_METHODOLOGY = ("Прототип: Методика виявлення, аналізу та оцінювання інформаційних загроз "
                "державі у воєнній сфері (ГУР МО України, 2016). Удосконалення (Шерстюк Є.І., "
                "НУОУ): формалізований алгоритм агрегації, позначки походження показників, "
                "автоматичне обчислення K_т, розв'язання неоднозначностей табл. 5, "
                "ідентифікація інструментів впливу стилометрією, ЦА, факти, оцінка тенденції. "
                "Параметри реалізації провізорні.")
