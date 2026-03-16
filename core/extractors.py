#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/extractors.py
==================
Multi-format text extraction and cleaning.

Supported formats: .txt, .pdf, .docx, .rtf, .html, .htm, .md
Each extractor returns a raw string; call clean_extracted_text() afterwards.
"""

from __future__ import annotations

import html as html_module
import re
import string
import subprocess
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
SUPPORTED_EXTENSIONS = {".txt", ".pdf", ".docx", ".rtf", ".html", ".htm", ".md"}


# ─────────────────────────────────────────────────────────────────────────────
#  RAW TEXT EXTRACTORS  (format-specific)
# ─────────────────────────────────────────────────────────────────────────────

def extract_text_from_txt(filepath: Path) -> str:
    """Read a plain-text or Markdown file; try common encodings."""
    for enc in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
        try:
            return filepath.read_text(encoding=enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return filepath.read_text(encoding="utf-8", errors="replace")


def extract_text_from_pdf(filepath: Path) -> str:
    """Extract text from a PDF using pdfplumber (preferred) or PyPDF2."""
    try:
        import pdfplumber
        pages = []
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages.append(text)
        return "\n".join(pages)
    except ImportError:
        pass

    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(str(filepath))
        return "\n".join(
            p.extract_text() for p in reader.pages if p.extract_text()
        )
    except ImportError:
        raise RuntimeError(
            f"Cannot read PDF '{filepath.name}': install pdfplumber."
        )


def extract_text_from_docx(filepath: Path) -> str:
    """Extract text from a .docx file using python-docx."""
    try:
        from docx import Document
        doc = Document(str(filepath))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except ImportError:
        raise RuntimeError(
            f"Cannot read DOCX '{filepath.name}': install python-docx."
        )


def extract_text_from_rtf(filepath: Path) -> str:
    """Extract text from an RTF file using striprtf."""
    try:
        from striprtf.striprtf import rtf_to_text
        raw = filepath.read_bytes()
        for enc in ("utf-8", "cp1251", "latin-1"):
            try:
                return rtf_to_text(raw.decode(enc))
            except Exception:
                continue
        return rtf_to_text(raw.decode("utf-8", errors="replace"))
    except ImportError:
        raise RuntimeError(
            f"Cannot read RTF '{filepath.name}': install striprtf."
        )


def _strip_html_tags(text: str) -> str:
    """Remove HTML/XML tags and decode entities."""
    # Use [^<]* instead of .*? to avoid catastrophic backtracking (ReDoS)
    text = re.sub(r"<script[^>]*>[^<]*(?:<(?!/script>)[^<]*)*</script>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<style[^>]*>[^<]*(?:<(?!/style>)[^<]*)*</style>",   " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return html_module.unescape(text)


def extract_text_from_html(filepath: Path) -> str:
    """Extract visible text from an HTML file."""
    raw = extract_text_from_txt(filepath)
    return _strip_html_tags(raw)


# Dispatcher: extension → extractor function
EXTRACTORS: dict = {
    ".txt":  extract_text_from_txt,
    ".md":   extract_text_from_txt,
    ".pdf":  extract_text_from_pdf,
    ".docx": extract_text_from_docx,
    ".rtf":  extract_text_from_rtf,
    ".html": extract_text_from_html,
    ".htm":  extract_text_from_html,
}


def extract_from_file(filepath: Path) -> str:
    """
    Convenience: dispatch to the right extractor based on file extension.
    Returns raw text (not yet cleaned).  Raises ValueError for unsupported types.
    """
    ext = filepath.suffix.lower()
    extractor = EXTRACTORS.get(ext)
    if extractor is None:
        raise ValueError(
            f"Unsupported file type '{ext}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )
    return extractor(filepath)


# ─────────────────────────────────────────────────────────────────────────────
#  ARTEFACT CLEANING  (format-agnostic)
# ─────────────────────────────────────────────────────────────────────────────

def _strip_code_blocks(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`[^`]+`", " ", text)
    return text


def _strip_urls(text: str) -> str:
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"www\.\S+",     " ", text)
    return text


def _strip_emails(text: str) -> str:
    return re.sub(r"\S+@\S+\.\S+", " ", text)


def _strip_encoding_artefacts(text: str) -> str:
    """Remove zero-width chars, BOM, and lines with too few alphabetic chars."""
    text = re.sub(r"[\u200b-\u200f\u202a-\u202e\ufeff\u00ad]", "", text)
    text = re.sub(r"[{}\[\]\\|<>=;]{3,}", " ", text)
    lines_out = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            lines_out.append(line)
            continue
        alpha = sum(1 for c in stripped if c.isalpha())
        if alpha / len(stripped) >= 0.40:
            lines_out.append(line)
    return "\n".join(lines_out)


def clean_extracted_text(text: str) -> str:
    """
    Master cleaning pipeline.

    Strips HTML tags, code blocks, URLs, email addresses, encoding artefacts,
    then normalises whitespace.  Returns clean plain text suitable for
    stylometric tokenisation.
    """
    text = _strip_html_tags(text)
    text = _strip_code_blocks(text)
    text = _strip_urls(text)
    text = _strip_emails(text)
    text = _strip_encoding_artefacts(text)
    text = re.sub(r"[ \t]+",  " ",  text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
