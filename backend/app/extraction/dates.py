"""Deadline extraction (FR-06/07, DR-07).

Policy: a date becomes a deadline candidate only when a deadline cue is attached to it. Dates without a cue
(start dates, internship periods, publication dates) are ignored, so no deadline is ever invented.

* strong cue   "срок подачи заявок", "дедлайн", "apply by", "өтінім қабылдау ... дейін"   -> 0.95
* weak cue     bare "до" / "until" / "by" right before the date, with application words nearby -> 0.80
                (without application words: 0.45, i.e. below threshold -> Unknown + review)
* no year      year inferred from the posting date                                           -> x0.9
* in the past  relative to the posting date                                                  -> x0.5
* relative     "до конца месяца", "rolling basis"                                            -> value None, 0.3
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from app.extraction.types import TEXT, TEXT_STRONG, Candidate

_MONTH_FORMS: dict[int, tuple[list[str], list[str]]] = {
    # month: (ru/en exact forms, kk stems that take suffixes)
    1: (["января", "январь", "january", "jan"], ["қаңтар"]),
    2: (["февраля", "февраль", "february", "feb"], ["ақпан"]),
    3: (["марта", "март", "march", "mar"], ["наурыз"]),
    4: (["апреля", "апрель", "april", "apr"], ["сәуір"]),
    5: (["мая", "май", "may"], ["мамыр"]),
    6: (["июня", "июнь", "june", "jun"], ["маусым"]),
    7: (["июля", "июль", "july", "jul"], ["шілде"]),
    8: (["августа", "август", "august", "aug"], ["тамыз"]),
    9: (["сентября", "сентябрь", "september", "sept", "sep"], ["қыркүйек"]),
    10: (["октября", "октябрь", "october", "oct"], ["қазан"]),
    11: (["ноября", "ноябрь", "november", "nov"], ["қараша"]),
    12: (["декабря", "декабрь", "december", "dec"], ["желтоқсан"]),
}

_forms = []
for _exact, _stems in _MONTH_FORMS.values():
    _forms += [re.escape(f) + r"\.?(?![\w])" for f in _exact]
    _forms += [re.escape(s) + r"\w*" for s in _stems]
_forms.sort(key=len, reverse=True)
MONTH = "(?P<mon>" + "|".join(_forms) + ")"


def month_number(word: str) -> int | None:
    w = word.lower().rstrip(".")
    for num, (exact, stems) in _MONTH_FORMS.items():
        if w in exact or any(w.startswith(s) for s in stems):
            return num
    return None


_YEAR_SUFFIX = r"(?:\s*(?:г\.|года|г(?![\w])|ж\.|жылғы|жыл\w*))?"
DATE_PATTERNS = [
    re.compile(r"(?<!\d)(?P<y>20\d{2})-(?P<m>\d{2})-(?P<d>\d{2})(?!\d)"),
    re.compile(r"(?<![\d.])(?P<d>\d{1,2})[./](?P<m>\d{1,2})(?:[./](?P<y>\d{4}|\d{2}))?(?!\d|\.\d)" + _YEAR_SUFFIX),
    re.compile(r"(?<!\d)(?P<y>20\d{2})\s*(?:ж\.|жылғы|жыл)?\s*(?P<d>\d{1,2})(?:-?(?:ші|шы|сі|сы))?\s+" + MONTH, re.I),
    re.compile(
        r"(?<!\d)(?P<d>\d{1,2})(?:-?(?:го|ое|th|st|nd|rd))?\s+(?:of\s+)?"
        + MONTH
        + r"(?:,?\s+(?P<y>20\d{2}))?"
        + _YEAR_SUFFIX,
        re.I,
    ),
    re.compile(MONTH + r"\s+(?P<d>\d{1,2})(?:st|nd|rd|th)?(?!\d)(?:,?\s+(?P<y>20\d{2}))?", re.I),
]


@dataclass
class DateMatch:
    start: int
    end: int
    day: int
    month: int
    year: int | None


def find_dates(text: str) -> list[DateMatch]:
    found: list[DateMatch] = []
    for pattern in DATE_PATTERNS:
        for m in pattern.finditer(text):
            gd = m.groupdict()
            month = int(gd["m"]) if gd.get("m") else month_number(gd.get("mon") or "")
            if month is None:
                continue
            day = int(gd["d"])
            year = gd.get("y")
            year_num = None if not year else (int(year) + 2000 if len(year) == 2 else int(year))
            if not (1 <= month <= 12 and 1 <= day <= 31):
                continue
            found.append(DateMatch(m.start(), m.end(), day, month, year_num))
    # Drop matches contained in a longer one.
    found.sort(key=lambda d: (d.start, -(d.end - d.start)))
    result: list[DateMatch] = []
    for d in found:
        if result and d.start < result[-1].end:
            continue
        result.append(d)
    return result


STRONG_CUE = re.compile(
    r"""(
      срок\w*\s+(?:подачи|при[её]ма|регистрац)\w*
    | при[её]м\w*\s+(?:заявок|заявлений|резюме|документов|анкет)\w*
    | (?:заявки|резюме|документы|анкеты)\s+принима\w*
    | подать\s+(?:заявку|резюме|документы|анкету)
    | подач\w*\s+(?:заявок|заявлений|резюме|документов|анкет)\w*
    | регистраци\w*\s+(?:открыта|продлится|до)
    | дедлайн | deadline | крайн\w*\s+срок\w*
    | последн\w*\s+день\s+(?:подачи|при[её]ма|регистрации)\w*
    | apply\s+(?:by|before|until|till)
    | applications?\s+(?:close|closes|closing|due|deadline|(?:are\s+)?(?:accepted|open)\s+(?:until|till|through))
    | closing\s+date | submission\s+deadline
    | register\s+(?:by|before|until) | registration\s+(?:closes|deadline|is\s+open\s+until)
    | соңғы\s+мерзім\w*
    | өтінім\w*(?:\s+\w+){0,2}\s+қабылда\w*
    | құжат\w*(?:\s+\w+){0,2}\s+қабылда\w*
    | тіркеу\w*(?:\s+\w+){0,2}\s+(?:мерзімі|аяқталады)
    )""",
    re.I | re.X,
)
WEAK_CUE_BEFORE = re.compile(r"(?:^|\W)(?:до|until|till|by|before|не\s+позднее|no\s+later\s+than)\s*$", re.I)
KK_AFTER = re.compile(r"^\s*(?:ж\.?|жылғы|жылға)?\s*(?:-?[а-яәғқңөұүһі]{1,3})?\s*дейін", re.I)
APP_CONTEXT = re.compile(
    r"заявк|заявлен|резюме|отклик|подать|подач|принима|регистрац|анкет|отбор|apply|application|submit|"
    r"regist|\bcv\b|selection|өтінім|тіркел|құжат|қабылда|іріктеу",
    re.I,
)
PERIOD_START = re.compile(r"(?:^|\W)(?:с|со|from|since|between)\s*$", re.I)
RELATIVE = re.compile(
    r"до\s+конца\s+(?:месяца|недели|года|(?:январ|феврал|март|апрел|ма|июн|июл|август|сентябр|октябр|ноябр|декабр)\w*)"
    r"|(?:until|by)\s+the\s+end\s+of\s+(?:the\s+)?(?:month|week|year|january|february|march|april|may|june|july|"
    r"august|september|october|november|december)"
    r"|ай(?:дың)?\s+соңына\s+дейін|rolling\s+(?:basis|admissions?)|бессрочн\w*",
    re.I,
)
SENTENCE_BREAK = re.compile(r"[.!?]\s|\n\s*\n|[;•]")


def _sentence_window(text: str, start: int, end: int, radius: int = 120) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    before = text[left:start]
    breaks = list(SENTENCE_BREAK.finditer(before))
    if breaks:
        before = before[breaks[-1].end() :]
    after = text[end:right]
    m = SENTENCE_BREAK.search(after)
    if m:
        after = after[: m.start()]
    return before + " " + after


def _resolve_year(dm: DateMatch, ref: date | None) -> tuple[date | None, bool]:
    if dm.year is not None:
        try:
            return date(dm.year, dm.month, dm.day), False
        except ValueError:
            return None, False
    base = ref or date.today()
    try:
        d = date(base.year, dm.month, dm.day)
        if d < base - timedelta(days=60):
            d = date(base.year + 1, dm.month, dm.day)
    except ValueError:
        return None, True
    return d, True


def deadline_candidates(text: str, ref: date | None) -> list[Candidate]:
    candidates: list[Candidate] = []
    dates = find_dates(text)
    prev_end = 0
    for i, dm in enumerate(dates):
        window_start = max(prev_end, dm.start - 90)
        before = text[window_start : dm.start]
        # The cue must be in the same sentence as the date.
        breaks = list(SENTENCE_BREAK.finditer(before))
        if breaks:
            before = before[breaks[-1].end() :]
        prev_end = dm.end

        confidence = 0.0
        method = None
        if STRONG_CUE.search(before):
            confidence, method = 0.95, "rule:deadline_cue"
        elif KK_AFTER.match(text[dm.end : dm.end + 25]):
            ctx = _sentence_window(text, dm.start, dm.end)
            confidence, method = (
                (0.9, "rule:deadline_kk_dein") if APP_CONTEXT.search(ctx) else (0.45, "rule:deadline_kk_dein_noctx")
            )
        elif WEAK_CUE_BEFORE.search(before):
            # "с 1 июня до 31 августа" / "from June 1 until August 31" is a period, not a deadline.
            if i > 0:
                prev = dates[i - 1]
                gap = text[prev.end : dm.start]
                if len(gap) <= 12 and PERIOD_START.search(text[max(0, prev.start - 8) : prev.start]):
                    continue
            ctx = _sentence_window(text, dm.start, dm.end)
            confidence, method = (
                (0.8, "rule:deadline_until") if APP_CONTEXT.search(ctx) else (0.45, "rule:deadline_until_noctx")
            )
        else:
            continue

        value, inferred_year = _resolve_year(dm, ref)
        if value is None:
            continue
        details: dict = {}
        if inferred_year:
            confidence *= 0.9
            details["year_inferred"] = True
        if ref is not None and value < ref - timedelta(days=1):
            confidence *= 0.5
            details["before_posting_date"] = True
        candidates.append(
            Candidate(
                value=value.isoformat(),
                confidence=confidence,
                method=method,
                span=(dm.start, dm.end),
                priority=TEXT_STRONG if confidence >= 0.8 else TEXT,
                details=details,
            )
        )

    for m in RELATIVE.finditer(text):
        candidates.append(
            Candidate(
                value=None, confidence=0.3, method="rule:deadline_relative", span=m.span(), details={"relative": True}
            )
        )
    return candidates
