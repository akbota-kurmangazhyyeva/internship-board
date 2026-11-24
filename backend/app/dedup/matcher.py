"""Duplicate detection and canonical grouping (FR-08, FR-09, NFR-05).

Pure functions, no database: the pipeline and the evaluation scripts share exactly the same logic.

1. Blocking (`is_candidate`): only compare postings with the same normalised employer (or one employer
   missing and similar titles, or the same specific application link) published within a time window.
2. Scoring (`pair_score`): weighted title-token Jaccard (with a ru/kk/en synonym map), character 4-gram
   cosine of the transliterated description, and Jaccard of extracted skills (language-independent).
3. Vetoes: known-but-different cities, deadlines or levels never merge. A false merge hides a real
   opportunity, so precision wins over recall.
4. Assignment (`assign`): attach a posting to the best existing group scoring >= merge threshold; groups
   scoring between the review and merge thresholds are reported as suspected duplicates for an admin.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Hashable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime

# --------------------------------------------------------------------------- text helpers

_TRANSLIT = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "i",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "kh",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "sh",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
        "ә": "a",
        "ғ": "g",
        "қ": "k",
        "ң": "n",
        "ө": "o",
        "ұ": "u",
        "ү": "u",
        "һ": "h",
        "і": "i",
    }
)


def translit(s: str) -> str:
    return s.lower().translate(_TRANSLIT)


_LEGAL_FORMS = re.compile(
    r"(?<![\w])(?:тоо|ао|ип|ооо|зао|пао|жшс|ақ|кх|llp|jsc|llc|ltd|inc|corp|plc|gmbh|"
    r"товарищество\s+с\s+ограниченной\s+ответственностью|акционерное\s+общество|"
    r"жауапкершілігі\s+шектеулі\s+серіктестік|акционерлік\s+қоғам|"
    r"limited\s+liability\s+partnership|joint\s+stock\s+company)(?![\w])",
    re.I,
)


def employer_key(name: str | None) -> str | None:
    """'ТОО «Kaspi.kz»' -> 'kaspi'; 'АО "Дала Софт"' -> 'dala soft'."""
    if not name:
        return None
    s = _LEGAL_FORMS.sub(" ", name)
    s = re.sub(r"\.(?:kz|com|org|net|io|ru)(?![\w])", " ", s, flags=re.I)
    s = translit(s)
    s = re.sub(r"[^\w]+", " ", s).strip()
    return s or None


_TITLE_SYNONYMS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(p, re.I), canon)
    for p, canon in [
        (r"^(?:стаж[её]р|стажир|intern|trainee|тағылымдам|практикант|internship)", "intern"),
        (r"^(?:разработчик|developer|программист|әзірлеуші|dev$)", "developer"),
        (r"^(?:инженер|engineer|инженері)", "engineer"),
        (r"^(?:аналитик|analyst|талдаушы|analytics)", "analyst"),
        (r"^(?:маркетолог|маркетинг|marketing|marketer)", "marketing"),
        (r"^(?:дизайнер|designer|дизайн|design)", "design"),
        (r"^(?:тестировщик|tester|qa$|тестирован)", "qa"),
        (r"^(?:бухгалтер|accountant|accounting)", "accounting"),
        (r"^(?:менеджер|manager|менеджмент|management)", "manager"),
        (r"^(?:данн|data$|деректер)", "data"),
        (r"^(?:junior|младш|джун)", "junior"),
        (r"^(?:юрист|lawyer|legal|заңгер)", "legal"),
        (r"^(?:финанс|finance|financial|қаржы)", "finance"),
        (r"^(?:продаж|sales|сату)", "sales"),
        (r"^(?:hr$|рекрут|recruit|кадр)", "hr"),
        (r"^(?:backend|бэкенд|бекенд)", "backend"),
        (r"^(?:frontend|фронтенд)", "frontend"),
        (r"^(?:fullstack|фулстек)", "fullstack"),
        (r"^(?:мобильн|mobile)", "mobile"),
        (r"^(?:веб|web)", "web"),
        (r"^(?:бизнес|business|бизнес)", "business"),
        (r"^(?:поддержк|support|қолдау)", "support"),
    ]
]
_TITLE_STOP = {
    "в",
    "на",
    "и",
    "по",
    "для",
    "с",
    "the",
    "a",
    "an",
    "of",
    "for",
    "in",
    "and",
    "with",
    "to",
    "at",
    "or",
    "бойынша",
    "және",
    "job",
    "vacancy",
    "вакансия",
    "позиция",
    "position",
    "kz",
    "remote",
    "удаленно",
}


def title_tokens(title: str) -> frozenset[str]:
    out = set()
    for tok in re.findall(r"[\w+#.]+", title.lower()):
        tok = tok.strip(".")
        if not tok or tok in _TITLE_STOP or tok.isdigit():
            continue
        for pattern, canon in _TITLE_SYNONYMS:
            if pattern.search(tok):
                tok = canon
                break
        else:
            tok = translit(tok)
        out.add(tok)
    return frozenset(out)


def char_ngrams(text: str, n: int = 4, limit: int = 5000) -> Counter[str]:
    s = re.sub(r"[^\w]+", " ", translit(text[:limit])).strip()
    return Counter(s[i : i + n] for i in range(max(0, len(s) - n + 1)))


def cosine(a: Counter[str], b: Counter[str]) -> float:
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def jaccard(a: Iterable[Hashable], b: Iterable[Hashable]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


_GENERIC_URL = re.compile(r"^https?://[^/]+/?(?:careers?|jobs|vacancies)?/?$", re.I)


def _url_key(url: str | None) -> str | None:
    if not url:
        return None
    u = url.strip().lower().split("#")[0].split("?")[0].rstrip("/")
    if _GENERIC_URL.match(u + "/"):
        return None  # a company's generic careers page says nothing about which vacancy
    return u


# --------------------------------------------------------------------------- features


@dataclass
class DedupRecord:
    """The facts dedup needs about one posting. Structured fields should be extractor *public* values."""

    id: Hashable
    title: str
    description: str
    employer: str | None = None
    published_at: datetime | None = None
    cities: list[str] = field(default_factory=list)
    level: str | None = None
    deadline: date | None = None
    skills: list[str] = field(default_factory=list)
    apply_url: str | None = None


@dataclass
class Features:
    record: DedupRecord
    employer_key: str | None
    title_tokens: frozenset[str]
    title_grams: Counter[str]
    desc_grams: Counter[str]
    apply_key: str | None

    @classmethod
    def of(cls, rec: DedupRecord) -> Features:
        return cls(
            record=rec,
            employer_key=employer_key(rec.employer),
            title_tokens=title_tokens(rec.title),
            title_grams=char_ngrams(rec.title, n=3),
            desc_grams=char_ngrams(rec.description) if len(rec.description) >= 80 else Counter(),
            apply_key=_url_key(rec.apply_url),
        )


@dataclass
class PairScore:
    score: float
    components: dict[str, float]
    vetoes: list[str]

    @property
    def mergeable(self) -> bool:
        return not self.vetoes


WEIGHTS = {"title": 0.35, "description": 0.40, "skills": 0.25}


def is_candidate(a: Features, b: Features, window_days: int) -> bool:
    ra, rb = a.record, b.record
    if (
        ra.published_at
        and rb.published_at
        and abs((ra.published_at - rb.published_at).total_seconds()) > window_days * 86400
    ):
        return False
    if a.employer_key and b.employer_key:
        return a.employer_key == b.employer_key or (a.apply_key is not None and a.apply_key == b.apply_key)
    if a.apply_key is not None and a.apply_key == b.apply_key:
        return True
    return jaccard(a.title_tokens, b.title_tokens) >= 0.5


def pair_score(a: Features, b: Features) -> PairScore:
    ra, rb = a.record, b.record
    vetoes: list[str] = []
    if ra.cities and rb.cities and not set(ra.cities) & set(rb.cities):
        vetoes.append("different_city")
    if ra.deadline and rb.deadline and abs((ra.deadline - rb.deadline).days) > 3:
        vetoes.append("different_deadline")
    if ra.level and rb.level and ra.level != rb.level:
        vetoes.append("different_level")
    if a.employer_key and b.employer_key and a.employer_key != b.employer_key:
        vetoes.append("different_employer")

    # Employer names inside titles ("Python стажер в Дала Софт") say nothing about the role itself.
    employer_words = set((a.employer_key or "").split()) | set((b.employer_key or "").split())
    title_a, title_b = a.title_tokens - employer_words, b.title_tokens - employer_words
    components: dict[str, float] = {"title": max(jaccard(title_a, title_b), cosine(a.title_grams, b.title_grams))}
    if a.desc_grams and b.desc_grams:
        components["description"] = cosine(a.desc_grams, b.desc_grams)
    if ra.skills and rb.skills:
        # Mean of Jaccard and overlap coefficient: a short repost listing fewer skills isn't over-penalised.
        sa, sb = set(ra.skills), set(rb.skills)
        components["skills"] = (jaccard(sa, sb) + len(sa & sb) / min(len(sa), len(sb))) / 2

    total_w = sum(WEIGHTS[k] for k in components)
    score = sum(WEIGHTS[k] * v for k, v in components.items()) / total_w
    if a.apply_key is not None and a.apply_key == b.apply_key and components["title"] >= 0.5:
        score = min(1.0, score + 0.1)
        components["same_apply_url"] = 1.0
    return PairScore(round(score, 4), {k: round(v, 4) for k, v in components.items()}, vetoes)


# --------------------------------------------------------------------------- assignment & clustering


@dataclass
class Decision:
    group_id: Hashable | None  # None -> start a new canonical vacancy
    score: float | None
    suspected: list[tuple[Hashable, float]]  # (group, score) pairs for the review queue


def assign(
    new: Features,
    groups: Mapping[Hashable, list[Features]],
    *,
    merge_threshold: float,
    review_threshold: float,
    window_days: int,
) -> Decision:
    best: tuple[Hashable, float] | None = None
    suspected: list[tuple[Hashable, float]] = []
    for gid, members in groups.items():
        if not any(is_candidate(new, m, window_days) for m in members):
            continue
        scores = [pair_score(new, m) for m in members]
        if any(s.vetoes for s in scores):
            continue
        top = max(s.score for s in scores)
        if top >= merge_threshold:
            if best is None or top > best[1]:
                best = (gid, top)
        elif top >= review_threshold:
            suspected.append((gid, top))
    if best is not None:
        return Decision(best[0], best[1], suspected)
    return Decision(None, None, suspected)


def cluster(
    records: list[DedupRecord],
    *,
    merge_threshold: float,
    review_threshold: float,
    window_days: int,
) -> dict[Hashable, Hashable]:
    """Batch version used by evaluation: replays postings in arrival order through `assign`.

    Returns {record id: group id}, where a group id is the id of the group's first record.
    """
    ordered = sorted(
        records, key=lambda r: (r.published_at is None, r.published_at.timestamp() if r.published_at else 0, str(r.id))
    )
    groups: dict[Hashable, list[Features]] = {}
    out: dict[Hashable, Hashable] = {}
    for rec in ordered:
        feats = Features.of(rec)
        decision = assign(
            feats, groups, merge_threshold=merge_threshold, review_threshold=review_threshold, window_days=window_days
        )
        gid = decision.group_id if decision.group_id is not None else rec.id
        groups.setdefault(gid, []).append(feats)
        out[rec.id] = gid
    return out
