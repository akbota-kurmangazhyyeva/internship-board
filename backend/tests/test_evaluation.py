"""Metric definitions and the evaluation tooling (split, validate, freeze, scripts)."""

import json
import shutil
from pathlib import Path

import pytest

from evaluation import eval_dedup, eval_extraction, eval_ranking, freeze, make_split
from evaluation.io import Dataset
from evaluation.metrics import (
    PRF,
    macro_f1,
    ndcg_at_k,
    pairwise,
    precision_at_k,
    recall_at_k,
    set_counts,
    single_counts,
)
from evaluation.validate import validate

EXAMPLE = Path(__file__).resolve().parent.parent / "evaluation" / "example"


# --------------------------------------------------------------------------- metrics


def test_single_slot_counting():
    assert single_counts("intern", "intern") == PRF(tp=1)
    assert single_counts("intern", "junior") == PRF(fp=1, fn=1)  # wrong value: both FP and FN
    assert single_counts(None, "2026-12-01") == PRF(fp=1)  # fabricated
    assert single_counts("2026-12-01", None) == PRF(fn=1)  # missed
    assert single_counts(None, None) == PRF()


def test_set_counting_and_macro():
    c = set_counts({"python", "sql"}, {"python", "git"})
    assert (c.tp, c.fp, c.fn) == (1, 1, 1) and c.f1 == pytest.approx(0.5)
    assert macro_f1({"a": PRF(tp=1), "b": PRF(fp=1, fn=1), "unused": PRF()}) == pytest.approx(0.5)


def test_pairwise_duplicates():
    gold = {"a": "g1", "b": "g1", "c": None, "d": None}
    pred = {"a": 1, "b": 1, "c": 1, "d": 4}  # c wrongly merged into a/b
    prf, fps, fns = pairwise(gold, pred)
    assert (prf.tp, prf.fp, prf.fn) == (1, 2, 0) and len(fps) == 2 and not fns


def test_ranking_metrics():
    ranked = ["x", "y", "z", "w"]
    assert precision_at_k(ranked, {"y", "w"}, 2) == 0.5
    assert recall_at_k(ranked, {"y", "w"}, 2) == 0.5
    assert ndcg_at_k(["a", "b"], {"a": 3, "b": 0}, 10) == pytest.approx(1.0)
    assert ndcg_at_k(["b", "a"], {"a": 3, "b": 0}, 10) < 1.0
    assert ndcg_at_k(["a"], {"a": 0}, 10) is None


# --------------------------------------------------------------------------- scripts on the synthetic example


def test_example_dataset_is_valid():
    assert validate(EXAMPLE) == ([], [])


def test_eval_scripts_run_on_example():
    ds = Dataset(EXAMPLE)
    ext = eval_extraction.evaluate(ds)
    assert ext["n_labelled"] == 8 and ext["macro_f1"] is not None and "by_language" in ext
    dd = eval_dedup.evaluate(ds, eval_dedup.records(ds), 0.75, 0.55, 60)
    assert dd["gold_duplicate_pairs"] == 1
    rk = eval_ranking.evaluate(ds, 10)
    assert set(rk["summary"]) == {"personalised", "chronological"}


def test_fabricated_values_are_reported(tmp_path):
    shutil.copytree(EXAMPLE, tmp_path / "ds")
    labels = tmp_path / "ds" / "labels.jsonl"
    rows = [json.loads(line) for line in labels.read_text().splitlines()]
    rows[0]["deadline"] = None  # pretend e01 states no deadline: the extractor's date becomes a fabrication
    labels.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    report = eval_extraction.evaluate(Dataset(tmp_path / "ds"))
    assert [f["posting_id"] for f in report["fabricated"]] == ["e01"]
    assert report["targets"]["no_fabricated_deadline_or_salary"] is False


# --------------------------------------------------------------------------- freeze guard


def test_freeze_detects_edits_and_requires_reason_to_refreeze(tmp_path, capsys):
    ds = tmp_path / "test"
    shutil.copytree(EXAMPLE, ds)
    assert freeze.main([str(ds)]) == 0
    assert freeze.verify(ds) == []
    with (ds / "labels.jsonl").open("a") as fh:
        fh.write("\n")
    assert freeze.verify(ds) == ["labels.jsonl changed since freezing"]
    with pytest.raises(SystemExit):
        freeze.main([str(ds)])
    assert freeze.main([str(ds), "--refreeze", "--reason", "test"]) == 0
    manifest = json.loads((ds / "FROZEN.json").read_text())
    assert manifest["reason"] == "test" and len(manifest["history"]) == 1


def test_sweep_refused_on_frozen_set(tmp_path):
    ds = tmp_path / "test"
    shutil.copytree(EXAMPLE, ds)
    freeze.main([str(ds)])
    with pytest.raises(SystemExit, match="refusing"):
        eval_dedup.main(["--data", str(ds), "--sweep", "--no-save"])


# --------------------------------------------------------------------------- split


def test_make_split_keeps_employers_together_and_is_deterministic(tmp_path):
    base = [json.loads(line) for line in (EXAMPLE / "postings.jsonl").read_text().splitlines()]
    seed = []
    for i in range(70):
        row = dict(base[i % len(base)])
        row.pop("posting_id")
        row["external_id"] = f"x{i}"
        row["employer"] = f"Company {i // 2}"  # pairs of postings share an employer
        seed.append(row)
    seed_path = tmp_path / "seed.jsonl"
    seed_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in seed))

    def split(out):
        make_split.main([str(seed_path), "--n", "40", "--test-dir", str(out / "test"), "--dev-dir", str(out / "dev")])
        read = lambda p: [json.loads(line) for line in p.read_text().splitlines()]  # noqa: E731
        return read(out / "test" / "postings.jsonl"), read(out / "dev" / "postings.jsonl")

    test, dev = split(tmp_path / "a")
    assert len(test) == 40 and len(dev) == 30
    assert not {r["employer"] for r in test} & {r["employer"] for r in dev}
    assert [r["posting_id"] for r in split(tmp_path / "b")[0]] == [r["posting_id"] for r in test]
