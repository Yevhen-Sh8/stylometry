"""Author-disjoint exploratory benchmark on pinned, licensed ELTeC prose.

Run: python tools/authorship_benchmark.py --corpus-dir /path/to/ELTeC-ukr \
     --output-dir /path/to/results
No downloaded texts are committed or included in the production engine image.
This measures pair-distance screening, not the application's bootstrap verdict.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import random
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))
from core import analysis as a, reference as r

CORPUS_REVISION = "a8c3d71301cdba767e33551ff0099da1dc51681a"
CORPUS_URL = "https://github.com/COST-ELTeC/ELTeC-ukr"
LICENCE = "https://creativecommons.org/licenses/by/4.0/"
NS = {"t": "http://www.tei-c.org/ns/1.0"}
TEST_PREFIXES = ("Квітка-Основ'яненко", "Вовчок", "Франко", "Грінченко",
                 "Кобилянська", "Українка", "Кащенко")
EXCLUDED = {"UKR18801": "coauthored by Panas Myrnyi and Ivan Bilyk"}
LENGTHS = (250, 500, 1000, 2500, 5000)
FEATURE_COUNTS = (100, 200, 300, 500)
SEED = 20261014


@dataclass
class Work:
    id: str
    author: str
    title: str
    text: str
    path: str
    xml_sha256: str
    text_sha256: str
    licence: str


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_author(name: str) -> str:
    name = " ".join(name.split())
    if "Кониський" in name:
        return "Кониський, Олександр"
    return re.sub(r"\s*\(\d{4}-\d{4}\)\s*$", "", name).strip()


def body_text(body: ET.Element) -> str:
    """Preserve dialogue; exclude TEI editorial notes, heads and marked quotes."""
    skip = {"note", "head", "fw", "quote"}

    def parts(node):
        if node.text:
            yield node.text
        for child in node:
            if child.tag.rsplit("}", 1)[-1] not in skip:
                yield from parts(child)
            if child.tail:
                yield child.tail
    return " ".join(" ".join(parts(body)).split())


def load_corpus(directory: Path) -> tuple[list[Work], list[dict]]:
    revision = subprocess.check_output(["git", "-C", str(directory), "rev-parse", "HEAD"], text=True).strip()
    if revision != CORPUS_REVISION:
        raise ValueError(f"Expected corpus revision {CORPUS_REVISION}, got {revision}")
    works, excluded, seen = [], [], set()
    for path in sorted((directory / "level1").glob("*.xml")):
        data = path.read_bytes()
        root = ET.fromstring(data)
        wid = root.get("{http://www.w3.org/XML/1998/namespace}id")
        if wid in EXCLUDED:
            excluded.append({"id": wid, "reason": EXCLUDED[wid]})
            continue
        author = root.find("t:teiHeader/t:fileDesc/t:titleStmt/t:author", NS)
        title = root.find("t:teiHeader/t:fileDesc/t:titleStmt/t:title", NS)
        licence = root.find("t:teiHeader/t:fileDesc/t:publicationStmt/t:availability/t:licence", NS)
        body = root.find("t:text/t:body", NS)
        if author is None or title is None or body is None or licence is None:
            raise ValueError(f"Incomplete metadata: {path.name}")
        if licence.get("target") != LICENCE or root.get("{http://www.w3.org/XML/1998/namespace}lang") != "uk":
            raise ValueError(f"Unapproved licence/language: {path.name}")
        text = body_text(body)
        text_hash = digest(text.encode())
        if not wid or wid in seen or text_hash in seen:
            raise ValueError(f"Duplicate identity/text: {path.name}")
        seen.update([wid, text_hash])
        works.append(Work(wid, canonical_author("".join(author.itertext())),
                          " ".join("".join(title.itertext()).split()), text,
                          str(path.relative_to(directory)), digest(data), text_hash, LICENCE))
    if not works:
        raise ValueError("No works found")
    return works, excluded


def split_authors(works: list[Work]) -> dict[str, list[Work]]:
    test_authors = {w.author for w in works if w.author.startswith(TEST_PREFIXES)}
    if len(test_authors) != 7:
        raise ValueError("Expected seven evaluation authors")
    remaining = sorted({w.author for w in works} - test_authors)
    random.Random(SEED).shuffle(remaining)
    training = set(remaining[:len(remaining) // 2])
    calibration = set(remaining[len(remaining) // 2:])
    assert not training & calibration and not (training | calibration) & test_authors
    return {name: [w for w in works if w.author in authors]
            for name, authors in [("reference", training), ("calibration", calibration),
                                  ("evaluation", test_authors)]}


def tokens(raw: list[str], variant: str) -> list[str]:
    return [t for t in raw if t not in a._BOILERPLATE_STOPWORDS
            and (variant == "keep_single" or len(t) > 1)]


def samples(works: list[Work], length: int, variant: str) -> list[dict]:
    result = []
    for work in works:
        raw = a._words(work.text)
        count = min(3, len(raw) // length)
        if not count:
            continue
        starts = np.linspace(0, len(raw) - length, count, dtype=int)
        assert len(starts) < 2 or np.diff(starts).min() >= length
        for start in starts:
            result.append({"id": f"{work.id}:{start}", "work": work.id, "author": work.author,
                           "raw_start": int(start), "raw_length": length,
                           "tokens": tokens(raw[start:start + length], variant)})
    return result


def pair_rows(sample: list[dict], distance: pd.DataFrame, *, calibration: bool) -> list[dict]:
    rows = []
    for x, y in itertools.combinations(sample, 2):
        # Never label excerpts from the same work as a same-author success.
        if x["work"] == y["work"] or (calibration and x["author"] == y["author"]):
            continue
        rows.append({"a": x["id"], "b": y["id"], "work_a": x["work"], "work_b": y["work"],
                     "author_a": x["author"], "author_b": y["author"],
                     "same_author": x["author"] == y["author"],
                     "distance": float(distance.loc[x["id"], y["id"]])})
    return rows


def summarize(rows: list[dict], threshold: float) -> dict:
    frame = pd.DataFrame(rows)
    same = frame.same_author
    flagged = frame.distance < threshold
    positive, negative = int(same.sum()), int((~same).sum())
    tp, fp = int((same & flagged).sum()), int((~same & flagged).sum())
    if not positive or not negative:
        raise ValueError("Evaluation needs both same- and different-author pairs")
    positives = frame[same].assign(hit=flagged[same])
    negatives = frame[~same].assign(hit=flagged[~same])
    negatives["author_pair"] = ["|".join(sorted([x, y])) for x, y in
                                zip(negatives.author_a, negatives.author_b)]
    return {"same_author_pairs": positive, "different_author_pairs": negative,
            "true_positives": tp, "false_positives": fp,
            "true_positive_rate": tp / positive, "false_positive_rate": fp / negative,
            "macro_author_tpr": float(positives.groupby("author_a").hit.mean().mean()),
            "macro_author_pair_fpr": float(negatives.groupby("author_pair").hit.mean().mean()),
            "roc_auc": float(roc_auc_score(same, -frame.distance)),
            "threshold": threshold}


def benchmark(corpus_dir: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    works, excluded = load_corpus(corpus_dir)
    groups = split_authors(works)
    protocol = {"seed": SEED, "raw_word_lengths": LENGTHS, "mfw_counts": FEATURE_COUNTS,
                "variants": ["default", "keep_single"], "metrics": ["burrows", "cosine"],
                "maximum_nonoverlapping_samples_per_work": 3,
                "calibration_negative_quantile": 0.01,
                "calibration_unit": "different-author pairs; no evaluation authors",
                "evaluation_unit": "different works; repeated samples are dependent",
                "scope": "exploratory distance screening; excludes bootstrap/strong verdict"}
    manifest = {"corpus_url": CORPUS_URL, "corpus_revision": CORPUS_REVISION,
                "attribution": "ELTeC-ukr, Dmytro Yesypenko and Mykhailo Nazarenko, 0.5.0 (2021)",
                "doi": "https://doi.org/10.5281/zenodo.4662731", "protocol": protocol,
                "excluded": excluded,
                "engine_source_hashes": {str(p.relative_to(ENGINE)): digest(p.read_bytes())
                                         for p in [ENGINE / "core/analysis.py", ENGINE / "core/reference.py"]},
                "partitions": {name: [{k: v for k, v in vars(w).items() if k != "text"}
                                      for w in group] for name, group in groups.items()}}
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    summary, scores = [], []
    for variant in protocol["variants"]:
        reference_docs = [tokens(a._words(w.text), variant) for w in groups["reference"]]
        ref = r.build_reference(reference_docs, language="uk", vocab_id=f"eltec-{variant}",
                                tokenizer_version=f"{a.TOKENIZER_VERSION}:benchmark:{variant}",
                                calib_share=0, pair_lengths=(), n_words=500,
                                source=CORPUS_URL, licence="CC BY 4.0")
        if len(ref.words) < 500:
            raise ValueError("Insufficient reference vocabulary")
        (output_dir / f"reference-{variant}.json").write_text(ref.to_json())
        for length in LENGTHS:
            calibration = samples(groups["calibration"], length, variant)
            evaluation = samples(groups["evaluation"], length, variant)
            for features in FEATURE_COUNTS:
                vocabulary = ref.features(features)
                matrices = []
                for sample in [calibration, evaluation]:
                    tf = a.build_tf_matrix({s["id"]: s["tokens"] for s in sample}, vocabulary)
                    matrices.append(ref.zscores(tf))
                for metric, distance_fn in [("burrows", a.burrows_delta), ("cosine", a.cosine_delta)]:
                    negative = pair_rows(calibration, distance_fn(matrices[0]), calibration=True)
                    if len(negative) < 100:
                        raise ValueError("Insufficient negative calibration pairs")
                    threshold = float(np.quantile([p["distance"] for p in negative], 0.01))
                    test = pair_rows(evaluation, distance_fn(matrices[1]), calibration=False)
                    config = {"variant": variant, "raw_words": length, "mfw": features, "metric": metric}
                    summary.append({**config, "calibration_pairs": len(negative),
                                    "evaluation_samples": len(evaluation), **summarize(test, threshold)})
                    scores.extend({**config, **p, "threshold": threshold,
                                   "flagged": p["distance"] < threshold} for p in test)
            print(f"Completed {variant}: {length} raw words", flush=True)
    pd.DataFrame(summary).to_csv(output_dir / "summary.csv", index=False)
    pd.DataFrame(scores).to_csv(output_dir / "pair_scores.csv", index=False)
    (output_dir / "results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    benchmark(args.corpus_dir, args.output_dir)
