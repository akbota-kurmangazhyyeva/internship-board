"""Metric definitions (documented in evaluation/README.md).

Single-valued slot (level, deadline, salary, ...), per posting:
    TP  prediction non-null and equal to a non-null gold value
    FP  prediction non-null but gold is null or different
    FN  gold non-null but prediction null or different
    (a wrong value counts as both FP and FN: the standard slot-filling convention)
Set-valued field (skills, cities, languages): item-level TP/FP/FN summed over postings (micro-average).
Macro-F1 = mean F1 over the extraction fields that have any gold or predicted values.
Duplicate detection: pairwise precision/recall/F1 over all unordered posting pairs.
Ranking: Precision@k, Recall@k (relevant = grade >= 2), NDCG@k with gain 2^grade - 1.
"""

from __future__ import annotations

import math
from collections.abc import Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations
from typing import Any


@dataclass
class PRF:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    def __iadd__(self, other: PRF) -> PRF:
        self.tp += other.tp
        self.fp += other.fp
        self.fn += other.fn
        return self

    @property
    def evaluable(self) -> bool:
        return (self.tp + self.fp + self.fn) > 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else (1.0 if self.fn == 0 else 0.0)

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else (1.0 if self.fp == 0 else 0.0)

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
        }


def single_counts(gold: Any, pred: Any) -> PRF:
    if pred is not None and gold is not None and pred == gold:
        return PRF(tp=1)
    return PRF(fp=int(pred is not None), fn=int(gold is not None))


def set_counts(gold: Iterable[Hashable], pred: Iterable[Hashable]) -> PRF:
    g, p = set(gold), set(pred)
    return PRF(tp=len(g & p), fp=len(p - g), fn=len(g - p))


def macro_f1(per_field: Mapping[str, PRF]) -> float | None:
    scores = [prf.f1 for prf in per_field.values() if prf.evaluable]
    return sum(scores) / len(scores) if scores else None


def pairwise(
    gold_groups: Mapping[Hashable, Hashable | None], pred_groups: Mapping[Hashable, Hashable]
) -> tuple[PRF, list, list]:
    """Returns (counts, false-positive pairs, false-negative pairs). A gold group of None is a singleton."""
    ids = sorted(set(gold_groups) & set(pred_groups), key=str)
    gold = {i: (gold_groups[i] if gold_groups[i] is not None else ("__single__", i)) for i in ids}
    prf = PRF()
    fps, fns = [], []
    for a, b in combinations(ids, 2):
        same_gold = gold[a] == gold[b]
        same_pred = pred_groups[a] == pred_groups[b]
        if same_gold and same_pred:
            prf.tp += 1
        elif same_pred:
            prf.fp += 1
            fps.append((a, b))
        elif same_gold:
            prf.fn += 1
            fns.append((a, b))
    return prf, fps, fns


def precision_at_k(ranked: Sequence[Hashable], relevant: set[Hashable], k: int) -> float:
    return sum(1 for x in ranked[:k] if x in relevant) / k


def recall_at_k(ranked: Sequence[Hashable], relevant: set[Hashable], k: int) -> float | None:
    if not relevant:
        return None
    return sum(1 for x in ranked[:k] if x in relevant) / len(relevant)


def ndcg_at_k(ranked: Sequence[Hashable], grades: Mapping[Hashable, int], k: int) -> float | None:
    def dcg(gs: Sequence[int]) -> float:
        return sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(gs[:k]))

    ideal = dcg(sorted(grades.values(), reverse=True))
    if ideal == 0:
        return None
    return dcg([grades.get(x, 0) for x in ranked]) / ideal


def mean(values: Iterable[float | None]) -> float | None:
    vs = [v for v in values if v is not None]
    return sum(vs) / len(vs) if vs else None
