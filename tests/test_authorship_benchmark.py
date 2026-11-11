import xml.etree.ElementTree as ET

import pandas as pd
import pytest

from tools import authorship_benchmark as b


def work(wid, author, text="а слово і текст " * 100):
    return b.Work(wid, author, wid, text, wid, wid, wid, b.LICENCE)


def test_alias_and_author_disjoint_partitions():
    assert b.canonical_author("Яковенко, О. (Кониський, Олександр)") == b.canonical_author("Кониський, Олександр (1836-1900)")
    works = [work(str(i), name) for i, name in enumerate(b.TEST_PREFIXES)]
    works += [work("r" + str(i), "Other " + str(i // 2)) for i in range(8)]
    groups = b.split_authors(works)
    authors = [{w.author for w in group} for group in groups.values()]
    assert all(not x & y for i, x in enumerate(authors) for y in authors[i + 1:])
    assert sum(map(len, groups.values())) == len(works)
    reversed_groups = b.split_authors(list(reversed(works)))
    assert {k: {w.id for w in v} for k, v in groups.items()} == {k: {w.id for w in v} for k, v in reversed_groups.items()}
    assert {w.id for w in groups["evaluation"]} == {str(i) for i in range(7)}


def test_aligned_nonoverlapping_samples_keep_single_letters():
    works = [work("one", "Author")]
    default, singles = [b.samples(works, 100, v) for v in ("default", "keep_single")]
    assert [s["id"] for s in default] == [s["id"] for s in singles]
    assert len(default) == 3
    assert all(y["raw_start"] - x["raw_start"] >= 100 for x, y in zip(default, default[1:]))
    assert all(len(s["tokens"]) < len(t["tokens"]) for s, t in zip(default, singles))


def test_pairs_exclude_same_work_and_calibration_same_author():
    sample = [{"id": str(i), "work": w, "author": author} for i, (w, author) in
              enumerate([("w1", "A"), ("w1", "A"), ("w2", "A"), ("w3", "B")])]
    distances = pd.DataFrame(1.0, index=list("0123"), columns=list("0123"))
    evaluation = b.pair_rows(sample, distances, calibration=False)
    calibration = b.pair_rows(sample, distances, calibration=True)
    assert len(evaluation) == 5
    assert sum(p["same_author"] for p in evaluation) == 2
    assert len(calibration) == 3
    assert all(not p["same_author"] and p["work_a"] != p["work_b"] for p in calibration)


def test_metrics_and_strict_threshold():
    rows = [{"same_author": same, "distance": d, "author_a": "A", "author_b": author}
            for same, d, author in [(True, 0.1, "A"), (True, 0.5, "A"),
                                    (False, 0.5, "B"), (False, 0.9, "C")]]
    result = b.summarize(rows, 0.5)
    assert result["true_positive_rate"] == 0.5
    assert result["false_positive_rate"] == 0
    assert result["roc_auc"] == 0.875


def test_editorial_material_removed_dialogue_preserved():
    body = ET.fromstring('<body><head>Editor heading</head><p>Start <note>note</note> dialogue <quote>borrowed</quote> end.</p></body>')
    assert b.body_text(body) == "Start dialogue end."


def test_corpus_rejects_unapproved_licence(tmp_path, monkeypatch):
    monkeypatch.setattr(b.subprocess, "check_output", lambda *args, **kwargs: b.CORPUS_REVISION)
    directory = tmp_path / "level1"
    directory.mkdir()
    (directory / "bad.xml").write_text('''<TEI xmlns="http://www.tei-c.org/ns/1.0" xml:id="bad" xml:lang="uk">
      <teiHeader><fileDesc><titleStmt><title>Title</title><author>Author</author></titleStmt>
      <publicationStmt><availability><licence target="unknown"/></availability></publicationStmt>
      </fileDesc></teiHeader><text><body><p>Text</p></body></text></TEI>''')
    with pytest.raises(ValueError, match="Unapproved licence"):
        b.load_corpus(tmp_path)
