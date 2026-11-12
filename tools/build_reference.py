# -*- coding: utf-8 -*-
"""Будує еталонну статистику мови для стилометрії DIMS (Data/reference/<мова>.json).

Приклади:
    python tools/build_reference.py --lang en --conllu path/UD_English-EWT/*.conllu \\
        --source "UD English-EWT" --licence "CC BY-SA 4.0"
    python tools/build_reference.py --lang uk --txt-dir path/brown-uk/data/good \\
        --conllu path/UD_Ukrainian-IU/*.conllu --source "..." --licence "..."
    python tools/build_reference.py --lang uk --jsonl export.jsonl   # {"doc": "...", "text": "..."}

Документ — одиниця, з якої не беруться обидві сторони «випадкової пари».
Короткі сусідні документи склеюються до ~2000 слів.
У CoNLL-U документи розмічені рядками `# newdoc`; якщо їх немає, документом
вважається кожні 40 речень поспіль.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.analysis import TOKENIZER_VERSION, clean_and_tokenise  # noqa: E402
from core.reference import REFERENCE_DIR, build_reference  # noqa: E402

SENTENCES_PER_PSEUDO_DOC = 40
MERGE_TO_TOKENS = 2000


def merge_short(docs: list[list[str]], target: int = MERGE_TO_TOKENS) -> list[list[str]]:
    """Склеює сусідні короткі документи (зазвичай з одного видання) до ~target слів,
    щоб із них можна було брати шматки для статистик і пар."""
    out: list[list[str]] = []
    buf: list[str] = []
    for d in docs:
        buf += d
        if len(buf) >= target:
            out.append(buf)
            buf = []
    if buf:
        out.append(buf)
    return out


def read_conllu(path: Path) -> list[str]:
    docs: list[list[str]] = []
    current: list[str] = []
    has_newdoc = False
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("# newdoc"):
                has_newdoc = True
                if current:
                    docs.append(current)
                current = []
            elif line.startswith("# text ="):
                current.append(line.split("=", 1)[1].strip())
                if not has_newdoc and len(current) >= SENTENCES_PER_PSEUDO_DOC:
                    docs.append(current)
                    current = []
    if current:
        docs.append(current)
    return [" ".join(d) for d in docs]


def read_txt_dir(path: Path) -> list[str]:
    return [p.read_text(encoding="utf-8", errors="replace") for p in sorted(path.glob("*.txt"))]


def read_jsonl(path: Path) -> list[str]:
    grouped: dict[str, list[str]] = {}
    with path.open(encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if not line.strip():
                continue
            row = json.loads(line)
            grouped.setdefault(str(row.get("doc", i)), []).append(row["text"])
    return [" ".join(v) for v in grouped.values()]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lang", required=True, help="код мови: uk, ru, en, pl, de")
    ap.add_argument("--conllu", nargs="*", default=[], type=Path)
    ap.add_argument("--txt-dir", nargs="*", default=[], type=Path)
    ap.add_argument("--jsonl", nargs="*", default=[], type=Path)
    ap.add_argument("--source", default="", help="звідки тексти (для довідки у файлі)")
    ap.add_argument("--licence", default="", help="ліцензія джерела")
    ap.add_argument("--words", type=int, default=500)
    ap.add_argument("--chunk", type=int, default=1000, help="розмір шматка для статистик, слів")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    texts: list[str] = []
    for p in args.conllu:
        texts += read_conllu(p)
    for p in args.txt_dir:
        texts += read_txt_dir(p)
    for p in args.jsonl:
        texts += read_jsonl(p)
    docs = merge_short([t for t in (clean_and_tokenise(x) for x in texts) if t])
    if not docs:
        sys.exit("Немає текстів.")

    built_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ref = build_reference(
        docs,
        language=args.lang,
        vocab_id=f"{args.lang}-{TOKENIZER_VERSION}-{built_at[:10]}",
        tokenizer_version=TOKENIZER_VERSION,
        n_words=args.words,
        chunk_tokens=args.chunk,
        source=args.source,
        licence=args.licence,
        built_at=built_at,
    )
    out = args.out or (REFERENCE_DIR / f"{args.lang}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(ref.to_json() + "\n", encoding="utf-8")
    total = sum(len(d) for d in docs)
    lens = ", ".join(sorted(ref.random_pairs.get("burrows", {}), key=int))
    print(f"{out}: {len(docs)} документів, {total} слів, {ref.n_chunks} шматків, "
          f"{len(ref.words)} слів у словнику; розподіли пар для довжин: {lens or '—'}")


if __name__ == "__main__":
    main()
