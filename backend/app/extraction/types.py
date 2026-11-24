"""Data types shared by all field extractors.

Every rule produces `Candidate`s. `resolve_single` / `resolve_multi` turn them into one `FieldResult` per field,
applying the FR-07 policy:

* below the confidence threshold            -> status "low_confidence", shown to students as Unknown
* two different values above the threshold  -> status "conflict", shown as Unknown, queued for review
* nothing found                             -> status "missing"

`Candidate.priority` encodes trust tiers: structured data supplied by the source (e.g. the hh.kz `salary`
object) outranks free-text rules. Conflicts are only declared between candidates of the same top tier.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.config import KZ_TZ

OK = "ok"
LOW = "low_confidence"
CONFLICT = "conflict"
MISSING = "missing"

# Priority tiers
TEXT = 1
TEXT_STRONG = 2
SOURCE = 3


@dataclass(frozen=True)
class PostingText:
    """What the extractor needs from a posting. Built from a raw snapshot or an evaluation record."""

    title: str
    description: str
    employer: str | None = None
    url: str | None = None
    apply_url: str | None = None
    published_at: datetime | None = None
    collected_at: datetime | None = None
    source_fields: dict[str, Any] = field(default_factory=dict)

    @property
    def reference_date(self) -> date | None:
        """Date used to resolve deadlines written without a year."""
        moment = self.published_at or self.collected_at
        if moment is None:
            return None
        if moment.tzinfo is not None:
            moment = moment.astimezone(KZ_TZ)
        return moment.date()


@dataclass
class Candidate:
    value: Any
    confidence: float
    method: str
    span: tuple[int, int] | None = None
    priority: int = TEXT
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class FieldResult:
    name: str
    status: str
    value: Any = None  # best candidate value, kept even when low-confidence so reviewers can see it
    confidence: float = 0.0
    method: str | None = None
    evidence: str | None = None
    span: tuple[int, int] | None = None
    details: dict[str, Any] = field(default_factory=dict)
    multi: bool = False

    @property
    def public(self) -> Any:
        """The value students see: only confident, non-conflicting values; otherwise Unknown."""
        if self.status == OK:
            return self.value
        return [] if self.multi else None


@dataclass
class ExtractionResult:
    fields: dict[str, FieldResult]
    version: str

    def public(self, name: str) -> Any:
        return self.fields[name].public

    def public_values(self) -> dict[str, Any]:
        return {name: fr.public for name, fr in self.fields.items()}


def evidence_snippet(text: str, span: tuple[int, int] | None, pad: int = 40) -> str | None:
    if span is None:
        return None
    start, end = span
    left = max(0, start - pad)
    right = min(len(text), end + pad)
    snippet = text[left:right].replace("\n", " ⏎ ")
    return ("…" if left > 0 else "") + snippet + ("…" if right < len(text) else "")


def _key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def resolve_single(
    name: str,
    candidates: list[Candidate],
    text: str,
    threshold: float,
    key: Callable[[Any], Any] | None = None,
) -> FieldResult:
    """`key` decides when two values count as "the same" (e.g. salary ignores formatting)."""
    if not candidates:
        return FieldResult(name, MISSING)

    top_priority = max(c.priority for c in candidates)
    tier = [c for c in candidates if c.priority == top_priority]
    overridden = [c for c in candidates if c.priority < top_priority]

    best_by_value: dict[str, Candidate] = {}
    for cand in tier:
        k = _key(key(cand.value) if key else cand.value)
        if k not in best_by_value or cand.confidence > best_by_value[k].confidence:
            best_by_value[k] = cand
    ranked = sorted(best_by_value.values(), key=lambda c: c.confidence, reverse=True)
    best = ranked[0]

    details = dict(best.details)
    if overridden:
        details["overridden"] = [{"value": c.value, "method": c.method} for c in overridden]

    confident = [c for c in ranked if c.confidence >= threshold and c.value is not None]
    if len(confident) > 1:
        return FieldResult(
            name,
            CONFLICT,
            value=None,
            confidence=best.confidence,
            method="conflict",
            evidence=" | ".join(filter(None, (evidence_snippet(text, c.span) for c in confident))) or None,
            details={
                "candidates": [
                    {"value": c.value, "confidence": round(c.confidence, 3), "method": c.method} for c in confident
                ]
            },
        )

    status = OK if best.confidence >= threshold and best.value is not None else LOW
    return FieldResult(
        name,
        status,
        value=best.value,
        confidence=round(best.confidence, 3),
        method=best.method,
        evidence=evidence_snippet(text, best.span),
        span=best.span,
        details=details,
    )


def resolve_multi(
    name: str, candidates: list[Candidate], text: str, threshold: float, *, union_tiers: bool
) -> FieldResult:
    """Multi-valued fields (skills, cities, languages). Each candidate is one item."""
    if not candidates:
        return FieldResult(name, MISSING, value=[], multi=True)

    if not union_tiers:
        top_priority = max(c.priority for c in candidates)
        candidates = [c for c in candidates if c.priority == top_priority]

    best: dict[Any, Candidate] = {}
    for cand in candidates:
        if cand.value not in best or cand.confidence > best[cand.value].confidence:
            best[cand.value] = cand

    accepted = sorted(v for v, c in best.items() if c.confidence >= threshold)
    rejected = sorted(v for v, c in best.items() if c.confidence < threshold)
    items = {
        v: {"confidence": round(c.confidence, 3), "method": c.method, "evidence": evidence_snippet(text, c.span)}
        for v, c in best.items()
    }
    first = best[accepted[0]] if accepted else max(best.values(), key=lambda c: c.confidence)
    confidence = min(best[v].confidence for v in accepted) if accepted else first.confidence
    extra = {k: v for c in best.values() for k, v in c.details.items()}
    return FieldResult(
        name,
        OK if accepted else LOW,
        value=accepted if accepted else rejected,
        confidence=round(confidence, 3),
        method=first.method,
        evidence=evidence_snippet(text, first.span),
        span=first.span,
        details={"items": items, **({"rejected": rejected} if rejected else {}), **extra},
        multi=True,
    )
