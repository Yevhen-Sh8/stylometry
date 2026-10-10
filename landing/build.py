#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
landing/build.py
================
Збирає статичний багатомовний лендинг DIMS із шаблонів (templates/),
перекладів (i18n/*.json) і налаштувань (config.json).

    python3 landing/build.py              # зібрати у landing/dist/
    python3 landing/build.py --check      # перевірити, що dist/ актуальний (CI, тести)
    python3 landing/build.py --flat DIR   # плаский попередній перегляд (uk = index.html)

Результат — чисті статичні файли: їх можна викласти на Vercel, Netlify,
Cloudflare Pages чи GitHub Pages без сервера. Збірка детермінована
(без дат і випадкових значень), тож --check порівнює файли побайтово.

Залежність: jinja2 (вже встановлюється разом із Flask).
"""
from __future__ import annotations

import argparse
import filecmp
import hashlib
import json
import posixpath
import re
import shutil
import sys
import tempfile
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup, escape

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
STATIC = ROOT / "static"
PAGES = ("index", "privacy")
PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")


# ── дані ────────────────────────────────────────────────────────────────────

def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def key_shape(value, prefix: str = "") -> set[str]:
    """Множина шляхів ключів (зі списками за індексами) для порівняння перекладів."""
    paths: set[str] = set()
    if isinstance(value, dict):
        for k, v in value.items():
            paths.add(f"{prefix}.{k}")
            paths |= key_shape(v, f"{prefix}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            paths.add(f"{prefix}[{i}]")
            paths |= key_shape(v, f"{prefix}[{i}]")
    return paths


def load_translations(cfg: dict) -> dict[str, dict]:
    langs = cfg["languages"]
    if cfg["default_lang"] not in langs:
        raise SystemExit(f"default_lang '{cfg['default_lang']}' немає серед languages")
    data = {lang: load_json(ROOT / "i18n" / f"{lang}.json") for lang in langs}
    reference = key_shape(data[langs[0]])
    for lang in langs[1:]:
        shape = key_shape(data[lang])
        if shape != reference:
            missing = sorted(reference - shape)[:10]
            extra = sorted(shape - reference)[:10]
            raise SystemExit(f"i18n/{lang}.json не збігається з {langs[0]}.json: "
                             f"бракує {missing}, зайве {extra}")
    return data


def fill(value, variables: dict):
    """Підставляє {змінні} в усі рядки перекладу; невідома змінна — помилка."""
    if isinstance(value, dict):
        return {k: (v if k == "price_format" else fill(v, variables)) for k, v in value.items()}
    if isinstance(value, list):
        return [fill(v, variables) for v in value]
    if isinstance(value, str):
        def sub(match: re.Match) -> str:
            name = match.group(1)
            if name not in variables:
                raise SystemExit(f"Невідома змінна {{{name}}} у рядку: {value!r}")
            return str(variables[name])
        return PLACEHOLDER_RE.sub(sub, value)
    return value


def severity(delta: float, threshold: float) -> str:
    """Ті самі межі, що й core.analysis.classify_severity (30 % і 60 % порогу)."""
    if delta < threshold * 0.30:
        return "critical"
    if delta < threshold * 0.60:
        return "high"
    if delta < threshold:
        return "moderate"
    return "clear"


def build_matrix(spec: dict) -> dict:
    labels, values, thr = spec["labels"], spec["values"], spec["threshold"]
    n = len(labels)
    rows, flagged = [], 0
    for i in range(n):
        cells = []
        for j in range(n):
            d = values[i][j]
            level = "self" if i == j else severity(d, thr)
            if i < j and d < thr:
                flagged += 1
            cells.append({"level": level, "text": f"{d:.2f}", "index": i * n + j})
        rows.append({"label": labels[i], "cells": cells})
    pairs = sorted(({"a": i, "b": j, "delta": values[i][j], "level": severity(values[i][j], thr)}
                    for i in range(n) for j in range(i + 1, n) if values[i][j] < thr),
                   key=lambda p: p["delta"])
    return {"labels": labels, "rows": rows, "n_pairs": n * (n - 1) // 2,
            "n_flagged": flagged, "threshold_text": f"{thr:g}", "pairs": pairs}


# ── шляхи ───────────────────────────────────────────────────────────────────

class Layout:
    """Де лежить кожна сторінка і як на неї посилатися (відносно чи від кореня)."""

    def __init__(self, flat: bool, main_lang: str, base_path: str = "/"):
        self.flat = flat
        self.main_lang = main_lang
        self.base_path = base_path if base_path.endswith("/") else base_path + "/"

    def page_file(self, lang: str, page: str) -> str:
        if self.flat:
            name = "index" if (page == "index" and lang == self.main_lang) else (
                lang if page == "index" else f"{page}-{lang}")
            return f"{name}.html"
        return f"{lang}/index.html" if page == "index" else f"{lang}/{page}/index.html"

    def asset_file(self, name: str) -> str:
        return f"static/{name}"

    def link(self, from_file: str, to_file: str, absolute: bool = False) -> str:
        if absolute:
            target = self.base_path + to_file
        else:
            target = posixpath.relpath(to_file, posixpath.dirname(from_file) or ".")
        if not self.flat and target.endswith("index.html"):
            target = target[: -len("index.html")] or "./"
        return target

    def public_url(self, site_url: str, file: str) -> str:
        path = file[: -len("index.html")] if file.endswith("index.html") else file
        return site_url.rstrip("/") + "/" + path


def asset_version(name: str) -> str:
    digest = hashlib.sha256((STATIC / name).read_bytes()).hexdigest()
    return digest[:10]


# ── шаблони ─────────────────────────────────────────────────────────────────

def math_filter(text: str) -> Markup:
    """R_DIMS і θΔ у тексті → математичне накреслення бренду."""
    html = str(escape(text))
    html = html.replace("R_DIMS", '<i class="math">R<sub>DIMS</sub></i>')
    html = html.replace("θΔ", '<i class="math">θ<sub>Δ</sub></i>')
    return Markup(html)


def make_env() -> Environment:
    env = Environment(loader=FileSystemLoader(ROOT / "templates"),
                      autoescape=True, undefined=StrictUndefined,
                      trim_blocks=False, lstrip_blocks=False, keep_trailing_newline=True)
    env.filters["math"] = math_filter
    return env


def language_vars(cfg: dict, t: dict) -> dict:
    p = cfg["pricing"]
    money = lambda n: t["price_format"].replace("{n}", f"{n:g}")  # noqa: E731
    provider = cfg["waitlist"].get("provider_name", "")
    matrix = build_matrix(cfg["demo_matrix"])
    return {
        "other_pairs": matrix["n_pairs"] - matrix["n_flagged"],
        "early_limit": p["pro_early_limit"],
        "early_price": money(p["pro_early_price"]),
        "price_year": money(p["pro_price_year"]),
        "price_month": money(p["pro_price_month"]),
        "free_analyses": p["free_analyses_per_month"],
        "free_sources": p["free_max_sources"],
        "pro_sources": p["pro_max_sources"],
        "provider_suffix": f" ({provider})" if provider else "",
        "contact": cfg["contact_email"] or t["privacy"]["contact_fallback"],
    }


def render_site(out: Path, flat: bool = False, only: list[str] | None = None) -> list[Path]:
    cfg = load_json(ROOT / "config.json")
    if only:  # чернетковий перегляд окремих мов
        cfg["languages"] = [l for l in cfg["languages"] if l in only]
        if cfg["default_lang"] not in cfg["languages"]:
            cfg["default_lang"] = cfg["languages"][0]
    raw = load_translations(cfg)
    langs = cfg["languages"]
    site_url = "" if flat else cfg.get("site_url", "").strip()
    layout = Layout(flat=flat, main_lang="uk" if "uk" in langs else langs[0],
                    base_path=cfg.get("base_path", "/"))
    env = make_env()
    matrix = build_matrix(cfg["demo_matrix"])
    versions = {name: asset_version(name) for name in ("fonts.css", "landing.css", "landing.js")}
    written: list[Path] = []

    trans = {}
    for lang in langs:
        t = raw[lang]
        trans[lang] = fill(t, language_vars(cfg, t))
    languages = [{"code": l, "name": trans[l]["lang_name"], "short": trans[l]["lang_short"]}
                 for l in langs]

    def write(rel: str, text: str) -> None:
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        written.append(path)

    def context(lang: str, page: str, file: str, absolute: bool = False) -> dict:
        t = trans[lang]

        def asset(name: str) -> str:
            href = layout.link(file, layout.asset_file(name), absolute)
            return f"{href}?v={versions[name]}" if (name in versions and not flat) else href

        def page_href(target_lang: str, target_page: str) -> str:
            return layout.link(file, layout.page_file(target_lang, target_page), absolute)

        canonical, alternates, og_image = "", [], ""
        if site_url:
            canonical = layout.public_url(site_url, layout.page_file(lang, page))
            alternates = [{"lang": l, "href": layout.public_url(site_url, layout.page_file(l, page))}
                          for l in langs]
            alternates.append({"lang": "x-default", "href": layout.public_url(
                site_url, layout.page_file(cfg["default_lang"], page))})
            if (STATIC / "img" / f"og-{lang}.png").exists():
                og_image = layout.public_url(site_url, layout.asset_file(f"img/og-{lang}.png"))
        return {
            "lang": lang, "page": page, "t": t, "cfg": cfg, "languages": languages,
            "asset": asset, "page_href": page_href, "matrix": matrix,
            "prices": {"early": language_vars(cfg, raw[lang])["early_price"]},
            "canonical": canonical, "alternates": alternates, "og_image": og_image,
            "inline_css": "", "inline_js": "",
        }

    for lang in langs:
        for page in PAGES:
            file = layout.page_file(lang, page)
            write(file, env.get_template(f"{page}.html").render(**context(lang, page, file)))

    # 404: віддається з будь-якої глибини шляху, тому посилання — від кореня сайту.
    ctx = context(cfg["default_lang"], "index", "404.html", absolute=not flat)
    ctx["inline_css"] = Markup((STATIC / "landing.css").read_text(encoding="utf-8"))
    write("404.html", env.get_template("notfound.html").render(**ctx))

    if not flat:
        root_ctx = context(cfg["default_lang"], "index", "index.html")
        root_ctx.update({
            "meta_description": trans[cfg["default_lang"]]["meta"]["description"],
            "lang_codes": langs, "default_lang": cfg["default_lang"],
            "lang_links": {l: layout.link("index.html", layout.page_file(l, "index")) for l in langs},
        })
        if site_url:
            root_ctx["canonical"] = site_url.rstrip("/") + "/"
        write("index.html", env.get_template("root.html").render(**root_ctx))

        robots = "User-agent: *\nAllow: /\n"
        if site_url:
            robots += f"\nSitemap: {site_url.rstrip('/')}/sitemap.xml\n"
            urls = "".join(
                f"  <url><loc>{layout.public_url(site_url, layout.page_file(l, p))}</loc></url>\n"
                for l in langs for p in PAGES)
            write("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n'
                  '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                  f"{urls}</urlset>\n")
        write("robots.txt", robots)

    for src in sorted(STATIC.rglob("*")):
        if src.is_file():
            dst = out / "static" / src.relative_to(STATIC)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            written.append(dst)
    return written


# ── CLI ─────────────────────────────────────────────────────────────────────

def diff_trees(a: Path, b: Path) -> list[str]:
    files_a = {p.relative_to(a).as_posix() for p in a.rglob("*") if p.is_file()}
    files_b = {p.relative_to(b).as_posix() for p in b.rglob("*") if p.is_file()} if b.exists() else set()
    problems = [f"бракує в dist: {f}" for f in sorted(files_a - files_b)]
    problems += [f"зайвий у dist: {f}" for f in sorted(files_b - files_a)]
    problems += [f"застарів: {f}" for f in sorted(files_a & files_b)
                 if not filecmp.cmp(a / f, b / f, shallow=False)]
    return problems


def check() -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        render_site(Path(tmp))
        return diff_trees(Path(tmp), DIST)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Збірка лендингу DIMS")
    parser.add_argument("--check", action="store_true", help="перевірити актуальність dist/")
    parser.add_argument("--flat", metavar="DIR", help="плаский попередній перегляд у DIR")
    parser.add_argument("--out", metavar="DIR", help="зібрати в DIR замість landing/dist")
    parser.add_argument("--langs", metavar="CODES", help="лише ці мови через кому (чернетка)")
    args = parser.parse_args(argv)

    if args.check:
        problems = check()
        for p in problems:
            print(p)
        if problems:
            print("dist/ застарів — запустіть: python3 landing/build.py")
            return 1
        print("dist/ актуальний")
        return 0

    only = args.langs.split(",") if args.langs else None
    if only and not (args.flat or args.out):
        parser.error("--langs потребує --out або --flat, щоб не зіпсувати dist/")
    out = Path(args.flat or args.out) if (args.flat or args.out) else DIST
    if out.exists():
        shutil.rmtree(out)
    files = render_site(out, flat=bool(args.flat), only=only)
    print(f"Зібрано {len(files)} файлів у {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
