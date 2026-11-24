"""Salary / stipend extraction (FR-06/07, DR-06).

The amount and currency are kept exactly as stated: no conversion, no guessing. A number only counts as a
salary when it has a currency marker or a salary keyword ("зарплата", "стипендия", "salary", "жалақы", ...)
right before it. Phone numbers, dates, years and counts ("5 000 сотрудников") are rejected.

Value shape: {"min", "max", "currency", "gross_net", "period", "unpaid", "text"}
    exact amount -> min == max;  "от X" -> min only;  "до Y" -> max only;  unpaid -> unpaid=True, no amounts
"""

from __future__ import annotations

import re
from typing import Any

from app.extraction.dates import find_dates
from app.extraction.types import SOURCE, TEXT, TEXT_STRONG, Candidate

NUM = r"(?:\d{1,3}(?:[    .,'’]\d{3})+|\d+(?:[.,]\d+)?)"
CUR = (
    r"(?:₸|тг\.?(?![\w])|тенге|теңге\w*|kzt(?![\w])|\$|usd(?![\w])|долл\w*|dollars?(?![\w])|₽|руб\w*|"
    r"rub(?![\w])|rur(?![\w])|€|eur(?:os?)?(?![\w])|евро(?![\w]))"
)


def _mult(group: str) -> str:
    return rf"(?:\s*(?P<{group}>к|k|тыс\.?|тысяч\w*|thousand|мың|млн\.?|миллион\w*|million|mln)(?![\w]))?"


RANGE = re.compile(
    rf"(?:(?:от|from|between)\s+)?(?P<c1>{CUR})?\s*(?P<a>{NUM}){_mult('ma')}\s*(?P<c2>{CUR})?\s*"
    rf"(?:-|–|—|до|to|and)\s*(?P<c3>{CUR})?\s*(?P<b>{NUM}){_mult('mb')}\s*(?P<c4>{CUR})?",
    re.I,
)
FROM = re.compile(
    rf"(?:от|from|starting\s+(?:at|from)|minimum|min\.?)\s+(?P<c1>{CUR})?\s*(?P<a>{NUM}){_mult('ma')}\s*(?P<c2>{CUR})?",
    re.I,
)
FROM_KK = re.compile(rf"(?P<a>{NUM}){_mult('ma')}\s*(?P<c2>{CUR})\w*\s+бастап", re.I)
UPTO = re.compile(rf"(?:до|up\s+to|maximum|max\.?)\s+(?P<c1>{CUR})?\s*(?P<b>{NUM}){_mult('mb')}\s*(?P<c2>{CUR})?", re.I)
SINGLE = re.compile(rf"(?P<c1>{CUR})?\s*(?P<a>{NUM}){_mult('ma')}\s*(?P<c2>{CUR})?", re.I)

SALARY_KEYWORD = re.compile(
    r"зарплат\w*|заработн\w*\s+плат\w*|з/п|з\.\s?п\.|(?<![\w])зп(?![\w])|оклад\w*|стипенди\w*|оплат\w*\s+(?:труда|стажировки|стаж[её]р\w*)|"
    r"вознагражд\w*|доход\w*|salary|stipend|compensation|(?<![\w])pay(?![\w])|paid|жалақы\w*|төлем\w*|шәкіртақы\w*",
    re.I,
)
UNPAID = re.compile(
    r"неоплачиваем\w*|без\s+оплаты|без\s+заработн\w*\s+плат\w*|оплата\s+не\s+предусмотрен\w*|"
    r"(?<![\w])unpaid(?![\w])|non-paid|not\s+paid|ақысыз|ақы\s+төленбейді",
    re.I,
)
NET = re.compile(r"на\s+руки|чистыми|(?<![\w])net(?![\w])|after\s+tax|қолға", re.I)
GROSS = re.compile(r"до\s+вычета|(?<![\w])gross(?![\w])|before\s+tax|гросс|грязными", re.I)
PERIOD = [
    (re.compile(r"в\s+месяц|/\s?мес|в\s+мес|per\s+month|a\s+month|monthly|/\s?month|айына", re.I), "month"),
    (re.compile(r"в\s+час|/\s?час|per\s+hour|an\s+hour|hourly|/\s?h(?:ou)?r|сағатына", re.I), "hour"),
    (re.compile(r"в\s+день|per\s+day|a\s+day|daily|күніне", re.I), "day"),
]
NOT_MONEY_UNIT = re.compile(
    r"^\s*(?:\+\s*)?(?:лет|года|год|years?|yrs?|жыл|%|человек|сотрудник\w*|employees|users|клиент\w*|"
    r"час\w*|hours?|дн\w*|days?|месяц\w*|months?|м²|кв\.?\s*м|км|шт|students|студент\w*)(?![\w])",
    re.I,
)
PHONE = re.compile(r"(?:\+7|(?<!\d)8)[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}")
URL_OR_EMAIL = re.compile(r"https?://\S+|www\.\S+|[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

CURRENCY_CODES = [
    (re.compile(r"₸|тг|тенге|теңге|kzt", re.I), "KZT"),
    (re.compile(r"\$|usd|долл|dollar", re.I), "USD"),
    (re.compile(r"₽|руб|rub|rur", re.I), "RUB"),
    (re.compile(r"€|eur|евро", re.I), "EUR"),
]
SANE_RANGE = {"KZT": (10_000, 10_000_000), "RUB": (1_000, 10_000_000), "USD": (50, 100_000), "EUR": (50, 100_000)}
MULTIPLIERS = [
    (re.compile(r"млн|миллион|million|mln", re.I), 1_000_000),
    (re.compile(r"к|k|тыс|thousand|мың", re.I), 1_000),
]


def _currency(token: str | None) -> str | None:
    if not token:
        return None
    for pattern, code in CURRENCY_CODES:
        if pattern.search(token):
            return code
    return None


def _number(raw: str, mult: str | None) -> float | int:
    s = re.sub(r"[    '’]", "", raw)
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", s):
        value: float = float(s.replace(".", "").replace(",", ""))
    else:
        value = float(s.replace(",", "."))
    if mult:
        for pattern, factor in MULTIPLIERS:
            if pattern.match(mult):
                value *= factor
                break
    return int(value) if float(value).is_integer() else value


def _overlaps(span: tuple[int, int], blocked: list[tuple[int, int]]) -> bool:
    return any(span[0] < b_end and b_start < span[1] for b_start, b_end in blocked)


def _line_before(text: str, start: int, width: int = 60) -> str:
    chunk = text[max(0, start - width) : start]
    return chunk.rsplit("\n", 1)[-1]


def salary_candidates(text: str, source_fields: dict[str, Any] | None = None) -> list[Candidate]:
    candidates: list[Candidate] = []

    src = (source_fields or {}).get("salary")
    if isinstance(src, dict) and (src.get("from") or src.get("to")):
        currency = (src.get("currency") or "").upper().replace("RUR", "RUB") or None
        gross = src.get("gross")
        lo, hi = src.get("from"), src.get("to")
        candidates.append(
            Candidate(
                value={
                    "min": lo,
                    "max": hi,
                    "currency": currency,
                    "gross_net": None if gross is None else ("gross" if gross else "net"),
                    "period": None,
                    "unpaid": False,
                    "text": " – ".join(str(v) for v in (lo, hi) if v) + (f" {currency}" if currency else ""),
                },
                confidence=0.97,
                method="source:salary",
                priority=SOURCE,
            )
        )

    blocked = [m.span() for m in PHONE.finditer(text)] + [m.span() for m in URL_OR_EMAIL.finditer(text)]
    blocked += [(d.start, d.end) for d in find_dates(text)]
    consumed: list[tuple[int, int]] = []

    for kind, pattern in (("range", RANGE), ("from", FROM), ("from", FROM_KK), ("upto", UPTO), ("single", SINGLE)):
        for m in pattern.finditer(text):
            span = (m.start(), m.end())
            if _overlaps(span, blocked) or _overlaps(span, consumed):
                continue
            g = m.groupdict()
            currency = _currency(g.get("c1") or g.get("c2") or g.get("c3") or g.get("c4"))
            has_keyword = bool(SALARY_KEYWORD.search(_line_before(text, m.start())))
            if currency is None and not has_keyword:
                continue
            if currency is None and NOT_MONEY_UNIT.match(text[m.end() : m.end() + 20]):
                continue

            lo = _number(g["a"], g.get("ma")) if g.get("a") else None
            hi = _number(g["b"], g.get("mb")) if g.get("b") else None
            if kind == "range" and lo is not None and hi is not None and g.get("mb") and not g.get("ma") and lo < 1000:
                lo = _number(g["a"], g["mb"])
            if kind == "single":
                hi = lo
            if lo is not None and hi is not None and lo > hi:
                continue

            amounts = [v for v in (lo, hi) if v is not None]
            low_ok, high_ok = SANE_RANGE.get(currency or "KZT", (10_000, 10_000_000))
            if not amounts or any(not (low_ok <= v <= high_ok) for v in amounts):
                continue
            if currency is None and any(1950 <= v <= 2100 for v in amounts):
                continue  # a year, not money

            after = text[m.end() : m.end() + 40]
            around = text[max(0, m.start() - 40) : m.start()] + " " + after
            gross_net = "net" if NET.search(around) else "gross" if GROSS.search(around) else None
            period = next((name for pat, name in PERIOD if pat.search(after)), None)

            confidence = 0.95 if (currency and has_keyword) else 0.85 if currency else 0.65
            consumed.append(span)
            candidates.append(
                Candidate(
                    value={
                        "min": lo if kind != "upto" else None,
                        "max": hi,
                        "currency": currency,
                        "gross_net": gross_net,
                        "period": period,
                        "unpaid": False,
                        "text": text[m.start() : m.end()].strip(),
                    },
                    confidence=confidence,
                    method=f"rule:salary_{kind}",
                    span=span,
                    priority=TEXT_STRONG if has_keyword else TEXT,
                )
            )

    for m in UNPAID.finditer(text):
        candidates.append(
            Candidate(
                value={
                    "min": None,
                    "max": None,
                    "currency": None,
                    "gross_net": None,
                    "period": None,
                    "unpaid": True,
                    "text": m.group(0),
                },
                confidence=0.85,
                method="rule:salary_unpaid",
                span=m.span(),
                priority=TEXT_STRONG,
            )
        )
    return candidates


def salary_key(value: dict[str, Any] | None) -> tuple | None:
    """Comparison key used for conflict detection and evaluation: ignores formatting details."""
    if not value:
        return None
    if value.get("unpaid"):
        return ("unpaid",)
    return (value.get("min"), value.get("max"), value.get("currency"))
