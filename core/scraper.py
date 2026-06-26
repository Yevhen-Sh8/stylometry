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

import ipaddress
import re
import socket
from urllib.parse import urlparse, urlsplit, urlunsplit, quote
import warnings

from .extractors import clean_extracted_text


_MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MB cap for any external fetch


_NAT64_PREFIX = ipaddress.ip_network("64:ff9b::/96")  # RFC 6052 well-known NAT64 prefix


def _is_private_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True only for genuinely non-routable addresses.
    NAT64 (64:ff9b::/96) maps to public IPv4 — we extract and check the embedded address."""
    if isinstance(ip, ipaddress.IPv6Address) and ip in _NAT64_PREFIX:
        # Extract embedded IPv4 from the last 32 bits of the NAT64 address
        packed = ip.packed  # 16 bytes
        embedded = ipaddress.IPv4Address(packed[12:])
        return _is_private_ip(embedded)
    return (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_multicast or ip.is_reserved)


def _assert_public_url(url: str) -> str:
    """Reject non-http(s) schemes and URLs that resolve to private/loopback IPs.
    Returns a sanitised URL (with CR/LF stripped, reassembled)."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        raise RuntimeError(f"Недопустима схема URL: {parts.scheme!r}")
    if not parts.hostname:
        raise RuntimeError("URL без хоста.")
    try:
        infos = socket.getaddrinfo(parts.hostname, None)
    except socket.gaierror:
        raise RuntimeError(f"Не вдалося визначити IP: {parts.hostname}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if _is_private_ip(ip):
            raise RuntimeError(f"URL вказує на приватну/службову адресу: {ip}")
    return urlunsplit((parts.scheme, parts.netloc, quote(parts.path, safe="/%:@"),
                       parts.query, parts.fragment))


def _read_capped(resp) -> bytes:
    buf = bytearray()
    for chunk in resp.iter_content(65536):
        buf.extend(chunk)
        if len(buf) > _MAX_RESPONSE_BYTES:
            resp.close()
            raise RuntimeError(f"Сторінка більша за ліміт {_MAX_RESPONSE_BYTES // 1024 // 1024} МБ.")
    return bytes(buf)

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

    url = _assert_public_url(url)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT,
                                allow_redirects=True, stream=True)
            resp.raise_for_status()
            # Re-check final URL after redirects
            _assert_public_url(resp.url)
            body = _read_capped(resp)
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

    declared = (resp.encoding or "").lower() if resp.encoding else ""
    if not declared or declared == "iso-8859-1":
        resp.encoding = resp.apparent_encoding or "utf-8"
    try:
        text = body.decode(resp.encoding, errors="replace")
    except (LookupError, TypeError):
        text = body.decode("utf-8", errors="replace")
    return text, resp.url


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


def _extract_from_html(html: str, url: str) -> str:
    """Run trafilatura + BeautifulSoup on raw HTML. Returns cleaned text or ''."""
    try:
        import trafilatura
        text = trafilatura.extract(
            html, url=url,
            include_comments=False, include_tables=False,
            include_links=False, include_images=False,
            no_fallback=False, favor_precision=True,
        )
        if text and len(text.split()) >= _MIN_WORDS:
            return clean_extracted_text(text)
    except Exception:
        pass

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
            raw = "\n".join(p.get_text() for p in soup.find_all("p"))
        cleaned = clean_extracted_text(raw)
        if len(cleaned.split()) >= _MIN_WORDS:
            return cleaned
    except Exception:
        pass
    return ""


def _try_jina(url: str) -> str:
    """Use Jina Reader (r.jina.ai) — free, handles JS/paywalls/403."""
    import requests
    try:
        safe = _assert_public_url(url)
    except RuntimeError:
        return ""
    try:
        r = requests.get(
            "https://r.jina.ai/" + safe,
            headers={"User-Agent": _UA, "Accept": "text/plain",
                     "X-Return-Format": "text"},
            timeout=30, stream=True,
        )
        r.raise_for_status()
        body = _read_capped(r)
        text = clean_extracted_text(body.decode("utf-8", errors="replace"))
        if text and len(text.split()) >= _MIN_WORDS:
            return text
    except Exception:
        pass
    return ""


def _try_wayback(url: str) -> tuple[str, str]:
    """Fetch latest snapshot from archive.org. Returns (text, snapshot_url)."""
    import requests
    try:
        probe = requests.get(
            "https://archive.org/wayback/available",
            params={"url": url}, timeout=10,
            headers={"User-Agent": _UA},
        )
        probe.raise_for_status()
        data = probe.json()
        snap = (data.get("archived_snapshots") or {}).get("closest") or {}
        if not snap.get("available") or not snap.get("url"):
            return "", url
        snap_url = _assert_public_url(snap["url"])
        page = requests.get(snap_url, timeout=_TIMEOUT,
                            headers={"User-Agent": _UA}, stream=True)
        page.raise_for_status()
        body = _read_capped(page)
        page.encoding = page.apparent_encoding or "utf-8"
        text = _extract_from_html(body.decode(page.encoding, errors="replace"), snap_url)
        if text:
            return text, snap_url
    except Exception:
        pass
    return "", url


def scrape_url_payload(url: str) -> dict[str, str]:
    """Download *url* → extracted article payload, with fallback chain:
       1. requests + trafilatura/BS4
       2. Jina Reader (r.jina.ai)
       3. Wayback Machine
    """
    final_url = url
    title = ""
    layer1_err: str = ""

    # ── Layer 1: requests → trafilatura/BS4 ───────────────────────────────
    try:
        html, final_url = _download_html(url)
        title = _extract_title(html)
        text = _extract_from_html(html, url)
        if text:
            return {"text": text, "title": title, "url": final_url,
                    "domain": urlparse(final_url).netloc.replace("www.", "")}
        layer1_err = "Текст не вдалося виділити зі сторінки (можливо, контент завантажується через JS)."
    except RuntimeError as exc:
        layer1_err = str(exc)
        # Для мережевих помилок (DNS, timeout, 403) одразу підніматись —
        # Jina/Wayback не допоможуть якщо сервер просто недоступний.
        _msg = layer1_err.lower()
        if any(k in _msg for k in ("dns", "не вдалося визначити ip", "ймовірно, домен",
                                   "не вдалося з'єднатися", "час очікування",
                                   "заблокував доступ (403)")):
            raise ValueError(layer1_err) from exc
    except Exception as exc:
        layer1_err = f"Помилка завантаження: {exc}"

    # ── Layer 2: Jina Reader ──────────────────────────────────────────────
    text = _try_jina(url)
    if text:
        return {"text": text, "title": title, "url": final_url or url,
                "domain": urlparse(final_url or url).netloc.replace("www.", "")}

    # ── Layer 3: Wayback Machine ──────────────────────────────────────────
    text, wb_url = _try_wayback(url)
    if text:
        return {"text": text, "title": title, "url": wb_url,
                "domain": urlparse(url).netloc.replace("www.", "")}

    host = urlparse(url).netloc or url
    raise ValueError(
        f"{layer1_err}\n"
        f"Всі три методи (requests, Jina Reader, Wayback Machine) не дали результату для {host}.\n"
        "Альтернативи: скористайтеся RSS-стрічкою або Telegram-каналом цього ресурсу; "
        "або відкрийте сторінку в браузері, скопіюйте текст і вставте у вкладку «Текст»."
    )
