"""Field extraction entry point.

    result = extract(PostingText(title=..., description=..., ...))
    result.public("deadline")       # what students see: None unless confident and unambiguous
    result.fields["deadline"]       # full FieldResult with status, confidence, method and evidence (provenance)

The current extractor is rule-based ("rules-1"). A multilingual language-model extractor can be added later
as another candidate source; `resolve_*` already arbitrates between candidates by priority and confidence.
"""

from __future__ import annotations

from app.config import get_settings
from app.extraction import rules
from app.extraction.dates import deadline_candidates
from app.extraction.normalize import normalize_text
from app.extraction.salary import salary_candidates, salary_key
from app.extraction.types import (
    MISSING,
    OK,
    Candidate,
    ExtractionResult,
    FieldResult,
    PostingText,
    evidence_snippet,
    resolve_multi,
    resolve_single,
)

EXTRACTOR_VERSION = "rules-1"

FIELD_NAMES = (
    "posting_language",
    "is_internship",
    "level",
    "skills",
    "cities",
    "work_format",
    "deadline",
    "salary",
    "languages",
    "eligibility",
    "apply_url",
)

# Fields worth an administrator's attention when uncertain (FR-27 review queue).
REVIEWABLE_FIELDS = ("level", "cities", "work_format", "deadline", "salary", "eligibility")


def _eligibility_key(value: dict | None) -> tuple | None:
    if not value:
        return None
    return (value.get("min_year"), value.get("max_year"), value.get("graduates"), tuple(value.get("degrees") or ()))


def _resolve_first(name: str, candidates: list[Candidate], text: str, threshold: float) -> FieldResult:
    """For fields where several values are normal (application links): best tier, then earliest in text."""
    if not candidates:
        return FieldResult(name, MISSING)
    best = sorted(candidates, key=lambda c: (-c.priority, -c.confidence, c.span[0] if c.span else 10**9))[0]
    return FieldResult(
        name,
        OK if best.confidence >= threshold else "low_confidence",
        value=best.value,
        confidence=round(best.confidence, 3),
        method=best.method,
        evidence=evidence_snippet(text, best.span),
        span=best.span,
        details={"alternatives": [c.value for c in candidates if c is not best][:5]},
    )


def build_text(posting: PostingText) -> tuple[str, int]:
    title = normalize_text(posting.title)
    description = normalize_text(posting.description)
    return f"{title}\n\n{description}", len(title)


def extract(posting: PostingText, threshold: float | None = None) -> ExtractionResult:
    if threshold is None:
        threshold = get_settings().confidence_threshold
    text, title_end = build_text(posting)
    src = posting.source_fields or {}
    fields: dict[str, FieldResult] = {}

    body = text[title_end:]
    lang, lang_conf = rules.detect_language(body if len(body) >= 80 else text)
    fields["posting_language"] = resolve_single(
        "posting_language", [Candidate(lang, lang_conf, "rule:script_stats")] if lang else [], text, threshold
    )

    intern_cands, level_cands, level_details = rules.internship_and_level(text, title_end, src)
    fields["is_internship"] = resolve_single("is_internship", intern_cands, text, threshold)
    fields["level"] = resolve_single("level", level_cands, text, threshold)
    fields["level"].details.update(level_details)

    fields["skills"] = resolve_multi("skills", rules.skills(text, title_end, src), text, threshold, union_tiers=True)
    fields["cities"] = resolve_multi("cities", rules.cities(text, title_end, src), text, threshold, union_tiers=False)
    fields["work_format"] = resolve_single("work_format", rules.work_format(text, title_end, src), text, threshold)

    deadline = deadline_candidates(text, posting.reference_date)
    if src.get("deadline"):
        deadline.append(Candidate(str(src["deadline"]), 0.97, "source:deadline", priority=3))
    fields["deadline"] = resolve_single("deadline", deadline, text, threshold)

    fields["salary"] = resolve_single("salary", salary_candidates(text, src), text, threshold, key=salary_key)
    fields["languages"] = resolve_multi("languages", rules.languages(text), text, threshold, union_tiers=True)
    fields["eligibility"] = resolve_single(
        "eligibility", rules.eligibility(text), text, threshold, key=_eligibility_key
    )
    fields["apply_url"] = _resolve_first(
        "apply_url", rules.apply_url(text, posting.url, posting.apply_url), text, threshold
    )
    return ExtractionResult(fields=fields, version=EXTRACTOR_VERSION)
