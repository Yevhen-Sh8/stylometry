#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_landing.py
=====================
Інваріанти статичного лендингу (landing/): переклади мають однакову структуру,
зібраний dist/ відповідає джерелам, усі відносні посилання ведуть на наявні
файли, сторінки не звертаються до сторонніх хостів, а кольори матриці Δ
збігаються з класифікацією в core.analysis.

Запуск (без pytest):  .venv/bin/python tests/test_landing.py
Запуск (з pytest):    .venv/bin/python -m pytest tests/test_landing.py -q
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

_spec = importlib.util.spec_from_file_location("landing_build", REPO / "landing" / "build.py")
lb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lb)

LINK_RE = re.compile(r'\b(?:href|src)="([^"]+)"')
CSS_URL_RE = re.compile(r"url\(([^)]+)\)")


def _cfg() -> dict:
    return lb.load_json(lb.ROOT / "config.json")


def _html_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.html"))


# ── переклади ────────────────────────────────────────────────────────────────
def test_translations_share_one_structure():
    data = lb.load_translations(_cfg())  # SystemExit, якщо структура різниться
    assert set(data) == set(_cfg()["languages"])


def test_unknown_placeholder_is_rejected():
    try:
        lb.fill({"a": "Ціна {no_such_var}"}, {"early_price": "9 $"})
    except SystemExit:
        return
    raise AssertionError("fill() мав відхилити невідому змінну")


# ── збірка ───────────────────────────────────────────────────────────────────
def test_dist_is_up_to_date():
    problems = lb.check()
    assert not problems, "landing/dist застарів: " + "; ".join(problems[:5])


def test_rendered_pages_have_no_raw_placeholders_or_external_hosts():
    with tempfile.TemporaryDirectory() as tmp:
        lb.render_site(Path(tmp))
        for page in _html_files(Path(tmp)):
            html = page.read_text(encoding="utf-8")
            assert not re.search(r"\{[a-z_]+\}", html), f"сирий плейсхолдер у {page.name}"
            assert "googleapis" not in html and "gstatic" not in html, f"Google Fonts у {page}"
            assert re.search(r'<html lang="[a-z]{2}">', html), f"немає lang у {page}"


def test_relative_links_resolve_to_files():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        lb.render_site(root)
        targets = [(p, LINK_RE.findall(p.read_text(encoding="utf-8"))) for p in _html_files(root)]
        css = root / "static" / "fonts.css"
        targets.append((css, CSS_URL_RE.findall(css.read_text(encoding="utf-8"))))
        for page, links in targets:
            if page.name == "404.html":
                continue  # посилання від кореня сайту, перевіряється окремо
            for link in links:
                parts = urlsplit(link)
                if parts.scheme or link.startswith(("#", "mailto:")):
                    continue
                target = (page.parent / parts.path).resolve()
                if parts.path.endswith("/") or target.is_dir():
                    target = target / "index.html"
                assert target.is_file(), f"{page.relative_to(root)} → {link}: файлу немає"


def test_flat_preview_build_links_resolve():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        lb.render_site(root, flat=True)
        assert (root / "index.html").is_file() and (root / "en.html").is_file()
        for page in _html_files(root):
            for link in LINK_RE.findall(page.read_text(encoding="utf-8")):
                parts = urlsplit(link)
                if parts.scheme or link.startswith(("#", "mailto:")):
                    continue
                assert (root / parts.path).is_file(), f"{page.name} → {link}"


# ── дані матриці ─────────────────────────────────────────────────────────────
def test_demo_matrix_is_symmetric_with_zero_diagonal():
    m = _cfg()["demo_matrix"]["values"]
    for i, row in enumerate(m):
        assert row[i] == 0.0
        for j, v in enumerate(row):
            assert v == m[j][i]


def test_matrix_colours_follow_app_severity():
    import core.analysis as a
    thr = _cfg()["demo_matrix"]["threshold"]
    for k in range(0, 300):
        d = k / 100
        app = a.classify_severity(d, thr)["css"] if d < thr else "clear"
        assert lb.severity(d, thr) == app, f"Δ={d}"


def _run_standalone():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed, failed = 0, 0
    for fn in fns:
        try:
            fn()
            passed += 1
            print(f"  ✓ {fn.__name__}")
        except Exception as exc:
            failed += 1
            print(f"  ✗ {fn.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{passed} passed, {failed} failed з {len(fns)} тестів")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if _run_standalone() else 1)
