#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/scraper.py
===============
Download a web article and extract its main text content.

Strategy:
  1. requests (with browser headers) → HTML
  2. trafilatura.extract on that HTML  (best for news articles)
  3. BeautifulSoup fallback            (article / main / <p> tags)

All paths apply clean_extracted_text() from extractors.py.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse
import warnings

from .extractors import clean_extracted_text

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _UA,
    "Accept-Language": "uk,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    # Do NOT set Accept-Encoding manually — requests sets it to what it can decompress
}
_TIMEOUT = 20
_MIN_WORDS = 30


def _download_html(url: str) -> tuple[str, str]:
    """Fetch URL with browser-like headers. Returns raw HTML and final URL."""
    import requests

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT, allow_redirects=True)
            resp.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else "?"
            if code == 403:
                raise RuntimeError(
                    f"Сайт заблокував доступ (403 Forbidden): {url}\n"
                    "Скопіюйте текст вручну та використайте вкладку «Текст»."
                ) from exc
            if code == 404:
                raise RuntimeError(f"Сторінка не знайдена (404): {url}") from exc
            raise RuntimeError(f"HTTP {code}: {url}") from exc
        except requests.exceptions.ConnectionError as exc:
            message = str(exc)
            if "NameResolutionError" in message or "Failed to resolve" in message:
                host = urlparse(url).netloc or url
                raise RuntimeError(
                    f"Не вдалося визначити IP-адресу домену: {host}.\n"
                    "Ймовірно, домен недоступний з поточного середовища або блокується DNS/мережею.\n"
                    "Відкрийте сторінку у браузері вручну та додайте текст через вкладку «Текст»."
                ) from exc
            raise RuntimeError(f"Не вдалося з'єднатися з сервером: {url}") from exc
        except requests.exceptions.Timeout:
            raise RuntimeError(f"Час очікування вичерпано: {url}")
        except Exception as exc:
            raise RuntimeError(f"Помилка завантаження: {exc}") from exc

    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text, resp.url


def _extract_title(html: str) -> str:
    """Best-effort extraction of a page title from raw HTML."""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
            title = re.sub(r"\s+", " ", title)
            return title[:180]

        og = soup.find("meta", attrs={"property": "og:title"}) or soup.find(
            "meta", attrs={"name": "og:title"}
        )
        if og and og.get("content"):
            return re.sub(r"\s+", " ", og["content"].strip())[:180]
    except Exception:
        pass
    return ""


def scrape_url_payload(url: str) -> dict[str, str]:
    """
    Download *url* and return extracted article payload.

    Raises
    ------
    ValueError   — meaningful text could not be extracted
    RuntimeError — network / HTTP error
    """
    html, final_url = _download_html(url)
    title = _extract_title(html)
    domain = urlparse(final_url).netloc.replace("www.", "")

    # ── Strategy 1: trafilatura (best for news) ───────────────────────────
    try:
        import trafilatura

        text = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
            favor_recall=True,
        )
        if text and len(text.split()) >= _MIN_WORDS:
            return {
                "text": clean_extracted_text(text),
                "title": title,
                "url": final_url,
                "domain": domain,
            }
    except Exception:
        pass

    # ── Strategy 2: BeautifulSoup ─────────────────────────────────────────
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header",
                         "aside", "form", "noscript", "figure"]):
            tag.decompose()

        content = (
            soup.find("article")
            or soup.find("main")
            or soup.find(id=re.compile(r"content|article|text|body", re.I))
            or soup.find(class_=re.compile(r"content|article|text|post|entry", re.I))
        )

        if content:
            raw = content.get_text(separator="\n")
        else:
            paragraphs = soup.find_all("p")
            raw = "\n".join(p.get_text() for p in paragraphs)

        cleaned = clean_extracted_text(raw)
        if len(cleaned.split()) >= _MIN_WORDS:
            return {
                "text": cleaned,
                "title": title,
                "url": final_url,
                "domain": domain,
            }
    except Exception:
        pass

    raise ValueError(
        f"Не вдалося витягти текст зі сторінки '{url}'.\n"
        "Можливо, сайт використовує JavaScript-рендеринг. "
        "Скопіюйте текст вручну та використайте вкладку «Текст»."
    )


def scrape_url(url: str) -> str:
    """Compatibility wrapper returning only article text."""
    return scrape_url_payload(url)["text"]
