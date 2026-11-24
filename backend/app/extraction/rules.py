"""Rule-based extractors for the remaining FR-06 fields.

Every function takes the combined text (title + blank line + description) and returns `Candidate`s; spans
refer to that combined text. `title_end` is the length of the title, used where the title is a stronger cue.
"""

from __future__ import annotations

import re
from typing import Any

from app.extraction.types import SOURCE, TEXT_STRONG, Candidate
from app.extraction.vocab import CITY_TERMS, SKILL_TERMS, normalize_city, normalize_skill

# --------------------------------------------------------------------------- posting language

_KK_CYR = set("әғқңөұүһіӘҒҚҢӨҰҮҺІ")
_KK_LAT = set("áǵıńóúýşçÁǴIŃÓÚÝŞÇ")


def detect_language(text: str) -> tuple[str | None, float]:
    """Returns ("kk" | "ru" | "en" | "mixed" | None, confidence) from script and Kazakh-specific letters."""
    cyr = lat = kk_cyr = kk_lat = 0
    for ch in text:
        if ch in _KK_CYR:
            cyr += 1
            kk_cyr += 1
        elif "Ѐ" <= ch <= "ӿ":
            cyr += 1
        elif ch in _KK_LAT:
            lat += 1
            kk_lat += 1
        elif ch.isascii() and ch.isalpha():
            lat += 1
    total = cyr + lat
    if total < 20:
        return None, 0.0
    cyr_share = cyr / total
    if 0.35 <= cyr_share <= 0.65:
        return "mixed", 0.7
    if cyr > lat:
        kk_share = kk_cyr / cyr
        if kk_share >= 0.04:
            return "kk", 0.9
        if kk_share >= 0.012:
            return "mixed", 0.65  # mostly Russian with Kazakh passages
        return "ru", 0.9
    if kk_lat / lat >= 0.02:
        return "kk", 0.7  # Kazakh in Latin script (DR-03)
    return "en", 0.9


# --------------------------------------------------------------------------- internship & level (DR-04)

INTERN = re.compile(
    r"(?<![\w])(?:стаж[её]р\w*|стажировк\w*|стаж[её]рск\w*|практикант\w*|"
    r"(?:производственн|преддипломн|учебн|летн|оплачиваем)\w*\s+практик\w*|практик[ауи]\s+для\s+студентов|"
    r"прохождени\w*\s+практик\w*|тағылымдам\w*|internships?|interns?|trainees?|traineeships?)(?![\w])",
    re.I,
)
SENIOR_T = re.compile(
    r"(?<![\w])(?:senior|sr\.|сеньор|синьор|ведущ\w*|lead|тимлид|team\s?lead|head\s+of|руководител\w*|"
    r"старш\w*|главн\w*|chief|principal|директор\w*|director)(?![\w])",
    re.I,
)
MID_T = re.compile(r"(?<![\w])(?:middle|mid-level|мидл)(?![\w])", re.I)
JUNIOR_T = re.compile(r"(?<![\w])(?:junior|jr\.?|джуниор|младш\w*|начинающ\w*|entry[- ]level)(?![\w])", re.I)
EXP_NONE = re.compile(
    r"без\s+опыта|опыт\w*(?:\s+работы)?\s*(?:[:\-–—]\s*)?не\s+(?:требуется|обязателен|нужен)|"
    r"no\s+(?:prior\s+|previous\s+|work\s+)?experience\s+(?:is\s+)?(?:required|needed|necessary)|"
    r"experience\s+(?:is\s+)?not\s+required|тәжірибе\w*\s+(?:талап\s+етілмейді|қажет\s+емес|міндетті\s+емес)|"
    r"тәжірибесіз",
    re.I,
)
_YRS = r"(?P<n>\d{1,2}(?:[.,]5)?)\s*\+?\s*(?:(?:-|–|—|до|to)\s*\d{1,2}\s*)?"
EXP_YEARS = [
    re.compile(
        r"опыт\w*(?:\s+\w+){0,4}?[\s:–—-]+(?:(?:от|не\s+менее|более|свыше|минимум)\s+)?"
        + _YRS
        + r"(?:года|год|лет)(?![\w])",
        re.I,
    ),
    re.compile(_YRS + r"(?:года|год|лет)\s+(?:\w+\s+)?опыт", re.I),
    re.compile(_YRS + r"(?:years?|yrs?)(?:\s+of)?(?:\s+[\w-]+){0,3}?\s+experience", re.I),
    re.compile(
        r"experience\s*(?:of|:|—|-)?\s*(?:at\s+least|minimum|min\.?|over|more\s+than)?\s*(?P<n>\d{1,2})\s*\+?\s*(?:years?|yrs?)",
        re.I,
    ),
    re.compile(r"(?P<n>\d{1,2})\s*(?:(?:-|–)\s*\d{1,2}\s*)?жыл\w*(?:\s+\w+){0,2}?\s+(?:жұмыс\s+)?тәжірибе", re.I),
    re.compile(r"тәжірибе\w*\s*(?:[:\-–—]\s*)?(?:кемінде\s+)?(?P<n>\d{1,2})\s*жыл", re.I),
]
_SOURCE_EXPERIENCE = {
    "noexperience": 0,
    "none": 0,
    "0": 0,
    "between1and3": 1,
    "1-3": 1,
    "between3and6": 3,
    "3-6": 3,
    "morethan6": 6,
    "6+": 6,
}
_INTERN_EMPLOYMENT = {"internship", "probation", "стажировка", "intern"}


def experience_years(text: str, source_fields: dict[str, Any]) -> tuple[float | None, Candidate | None]:
    src = source_fields.get("experience")
    if isinstance(src, str) and src.replace("_", "").lower() in _SOURCE_EXPERIENCE:
        years = _SOURCE_EXPERIENCE[src.replace("_", "").lower()]
        return years, Candidate(years, 0.9, "source:experience", priority=SOURCE)
    if m := EXP_NONE.search(text):
        return 0, Candidate(0, 0.85, "rule:no_experience", m.span())
    for pattern in EXP_YEARS:
        if m := pattern.search(text):
            years = float(m.group("n").replace(",", "."))
            if years <= 15:
                years = int(years) if years.is_integer() else years
                return years, Candidate(years, 0.8, "rule:experience_years", m.span())
    return None, None


def internship_and_level(
    text: str, title_end: int, source_fields: dict[str, Any]
) -> tuple[list[Candidate], list[Candidate], dict[str, Any]]:
    """Returns (is_internship candidates, level candidates, details)."""
    title = text[:title_end]
    title_intern = INTERN.search(title)
    desc_intern = INTERN.search(text, title_end)
    employment = str(source_fields.get("employment") or "").lower()

    title_level: tuple[str, re.Match[str]] | None = None
    for level, pattern in (("senior", SENIOR_T), ("mid", MID_T), ("junior", JUNIOR_T)):
        if m := pattern.search(title):
            title_level = (level, m)
            break

    years, years_cand = experience_years(text, source_fields)
    details: dict[str, Any] = {"experience_years": years} if years is not None else {}

    intern: list[Candidate] = []
    if title_intern:
        intern.append(Candidate(True, 0.95, "rule:intern_title", title_intern.span(), TEXT_STRONG))
    elif employment in _INTERN_EMPLOYMENT:
        intern.append(Candidate(True, 0.9, "source:employment", priority=SOURCE))
    elif desc_intern and title_level is None:
        intern.append(Candidate(True, 0.8, "rule:intern_description", desc_intern.span(), TEXT_STRONG))
    elif title_level is not None:
        intern.append(Candidate(False, 0.85, "rule:level_title", title_level[1].span(), TEXT_STRONG))
    else:
        intern.append(Candidate(False, 0.7, "rule:no_internship_cue"))

    level: list[Candidate] = []
    is_intern = intern[0].value is True
    if is_intern:
        level.append(Candidate("intern", intern[0].confidence, intern[0].method, intern[0].span, TEXT_STRONG))
    elif title_level is not None:
        level.append(Candidate(title_level[0], 0.9, "rule:level_title", title_level[1].span(), TEXT_STRONG))

    # Years of experience either confirm the level or contradict it (=> conflict => Unknown + review).
    if years is not None and years_cand is not None:
        from_years = "junior" if years < 3 else "mid" if years < 6 else "senior"
        compatible = {
            "intern": {"junior"} if years < 3 else set(),
            "junior": {"junior"} if years < 3 else set(),
            "mid": {"mid", "junior"} if years >= 1 else set(),
            "senior": {"mid", "senior"} if years >= 3 else set(),
        }
        if level:
            if from_years not in compatible[level[0].value]:
                level.append(
                    Candidate(
                        from_years, 0.75, years_cand.method, years_cand.span, TEXT_STRONG, {"experience_years": years}
                    )
                )
        else:
            conf = 0.7 if from_years == "junior" else 0.75
            level.append(
                Candidate(
                    from_years, conf, years_cand.method, years_cand.span, TEXT_STRONG, {"experience_years": years}
                )
            )
    return intern, level, details


# --------------------------------------------------------------------------- work format

REMOTE = re.compile(
    r"(?<![\w])(?:удал[её]нн\w*\s+(?:работ|формат|режим|занятост|основ)\w*|работ\w*\s+удал[её]нно|удал[её]нно|"
    r"удал[её]нк\w*|дистанционн\w*|remote(?:ly)?(?!\s+(?:sensing|control|access|server|monitoring))|"
    r"work\s+from\s+home|wfh|қашықтан|қашықтықтан)(?![\w])",
    re.I,
)
NOT_REMOTE = re.compile(
    r"(?<![\w])(?:(?:не|без)\s+(?:\w+\s+)?(?:удал[её]нн\w*|удал[её]нк\w*|удал[её]нно|дистанционн\w*)|"
    r"(?:удал[её]нн\w*(?:\s+(?:работ|формат|режим)\w*)?|удал[её]нк\w*)\s+(?:не\s+(?:предусмотрен|возможн|рассматрива)\w*|невозможн\w*|исключен\w*)|"
    r"no\s+remote|not\s+remote|remote\s+(?:work\s+)?(?:is\s+)?not\s+(?:possible|available|an\s+option)|"
    r"қашықтан\s+емес)",
    re.I,
)
HYBRID = re.compile(
    r"(?<![\w])(?:гибрид\w*|hybrid|аралас\s+(?:формат|режим|жұмыс)\w*|смешанн\w*\s+(?:формат|режим)\w*|"
    r"частично\s+удал[её]нн?\w*|partially\s+remote|partly\s+remote)(?![\w])",
    re.I,
)
ONSITE = re.compile(
    r"(?<![\w])(?:(?:работа|работать|работы)\s+(?:в|из)\s+офис\w*|в\s+(?:нашем\s+)?офисе|офисн\w*\s+(?:формат|режим|работ)\w*|"
    r"формат\w*(?:\s+работы)?\s*[:\-–—]\s*офис\w*|on-?site|in[- ](?:the\s+)?office|office[- ]based|"
    r"at\s+(?:our|the)\s+office|in[- ]person|только\s+(?:в\s+)?офис\w*|office\s+only|кеңседе|офисте)(?![\w])",
    re.I,
)
_FORMATS = {"remote", "hybrid", "onsite"}


def work_format(text: str, title_end: int, source_fields: dict[str, Any]) -> list[Candidate]:
    out: list[Candidate] = []
    src = str(source_fields.get("work_format") or "").lower().replace("-", "").replace("_", "")
    if src in _FORMATS:
        out.append(Candidate(src, 0.95, "source:work_format", priority=SOURCE))

    hybrid = list(HYBRID.finditer(text))
    if hybrid:
        out.append(Candidate("hybrid", 0.85, "rule:hybrid", hybrid[0].span()))
        return out

    negated = [m.span() for m in NOT_REMOTE.finditer(text)]
    remote = [m for m in REMOTE.finditer(text) if not any(m.start() < e and s < m.end() for s, e in negated)]
    if remote:
        m = remote[0]
        out.append(Candidate("remote", 0.9 if m.start() < title_end else 0.8, "rule:remote", m.span()))
    onsite = list(ONSITE.finditer(text))
    if negated:
        out.append(Candidate("onsite", 0.8, "rule:not_remote", negated[0]))
    elif onsite:
        out.append(Candidate("onsite", 0.75, "rule:onsite", onsite[0].span()))
    return out


# --------------------------------------------------------------------------- cities

LOCATION_LABEL = re.compile(
    r"(?:город|локация|местоположение|место\s+работы|адрес|location|city|address|қала|мекенжай)\s*[:\-–—]\s*[^\n]{0,40}$",
    re.I,
)


def cities(text: str, title_end: int, source_fields: dict[str, Any]) -> list[Candidate]:
    out: list[Candidate] = []
    src = source_fields.get("city") or source_fields.get("cities")
    for raw in [src] if isinstance(src, str) else (src or []):
        if name := normalize_city(str(raw)):
            out.append(Candidate(name, 0.95, "source:city", priority=SOURCE))
    for term in CITY_TERMS:
        for m in term.pattern.finditer(text):
            if m.start() < title_end:
                conf, method = 0.9, "rule:city_title"
            elif LOCATION_LABEL.search(text[max(0, m.start() - 60) : m.start()]):
                conf, method = 0.9, "rule:city_labeled"
            else:
                conf, method = 0.75, "rule:city_mention"
            out.append(Candidate(term.name, conf, method, m.span()))
    return out


# --------------------------------------------------------------------------- skills

TECH_CONTEXT = re.compile(
    r"язык\w*\s+программирован|programming|stack|стек|технолог|technolog|framework|фреймворк|знани\w*|"
    r"knowledge|experience\s+with|опыт\s+(?:работы\s+)?с|навык|skills?|бағдарлама",
    re.I,
)


def skills(text: str, title_end: int, source_fields: dict[str, Any]) -> list[Candidate]:
    out: list[Candidate] = []
    for raw in source_fields.get("skills") or []:
        if name := normalize_skill(str(raw)):
            out.append(Candidate(name, 0.95, "source:skills", priority=SOURCE))

    plain: list[tuple[str, tuple[int, int]]] = []
    ambiguous: list[tuple[str, tuple[int, int]]] = []
    for term in SKILL_TERMS:
        for m in term.pattern.finditer(text):
            (ambiguous if term.needs_context else plain).append((term.name, m.span()))

    for name, span in plain:
        out.append(Candidate(name, 0.95 if span[0] < title_end else 0.85, "rule:skill", span))
    for name, span in ambiguous:
        near_other = any(abs(s - span[0]) <= 60 and n != name for n, (s, _) in plain)
        line_start = text.rfind("\n", 0, span[0]) + 1
        line_end = text.find("\n", span[1])
        line = text[line_start : line_end if line_end != -1 else len(text)]
        if near_other or TECH_CONTEXT.search(line):
            out.append(Candidate(name, 0.7, "rule:skill_ambiguous", span))
    return out


# --------------------------------------------------------------------------- language requirements

_LANGS = [
    ("en", re.compile(r"английск\w*|english|ағылшын\w*", re.I), False),
    ("kk", re.compile(r"казахск\w*|kazakh|қазақ(?=\s+тіл)", re.I), False),
    ("kk", re.compile(r"мемлекеттік\s+тіл\w*|государственн\w*\s+язык\w*", re.I), True),
    ("ru", re.compile(r"русск\w*|russian|орыс(?=\s+тіл)", re.I), False),
]
LANG_CONTEXT = re.compile(
    r"язык|language|тіл|fluen|proficien|speak|spoken|written|knowledge|command|знани|владени|уровень|level|"
    r"intermediate|advanced|upper|native|свободн|разговорн|письменн|базов|good|strong|excellent|working|business|"
    r"(?<![\w])[ABC][12](?![\w])|ielts|toefl|меңгер|білу",
    re.I,
)
CEFR = re.compile(r"(?<![\w])([ABC][12])(?![\w])")
LEVEL_WORDS = re.compile(
    r"upper[- ]intermediate|pre[- ]intermediate|intermediate|advanced|fluent|proficient|native|elementary|"
    r"beginner|свободн\w*|разговорн\w*|базов\w*|технич\w*",
    re.I,
)


def languages(text: str) -> list[Candidate]:
    out: list[Candidate] = []
    for code, pattern, self_context in _LANGS:
        for m in pattern.finditer(text):
            window = text[max(0, m.start() - 40) : m.start()] + " " + text[m.end() : m.end() + 40]
            if not self_context and not LANG_CONTEXT.search(window):
                continue
            details: dict[str, Any] = {}
            if lvl := CEFR.search(text[m.end() : m.end() + 40]) or CEFR.search(
                text[max(0, m.start() - 25) : m.start()]
            ):
                details = {"levels": {code: lvl.group(1)}}
            elif lvl := LEVEL_WORDS.search(window):
                details = {"levels": {code: lvl.group(0).lower()}}
            out.append(Candidate(code, 0.85, "rule:language", m.span(), details=details))
    return out


# --------------------------------------------------------------------------- eligibility (DR-08)

_ORD_RU = r"(?:-?(?:го|ого|ий|й|х|ых|ші|шы|сі|сы))?"
COURSE = re.compile(
    r"(?<![\w])(?P<nums>[1-6]" + _ORD_RU + r"(?:\s*(?:,|и|или|-|–|—|/|және|немесе)\s*[1-6]" + _ORD_RU + r")*)\s*курс\w*"
    r"(?P<plus>\s*(?:и\s+(?:выше|старше|более)|\+|және\s+(?:одан\s+)?жоғары))?",
    re.I,
)
EN_YEAR = re.compile(
    r"(?<![\w])(?P<nums>[1-6](?:st|nd|rd|th)?(?:\s*(?:,|and|or|-|–|/|to)\s*[1-6](?:st|nd|rd|th)?)*)[- ]year"
    r"(?![\w-])(?!\s+(?:of|experience|degree|program|programme|course|contract|internship|long|duration))"
    r"(?:\s+(?:bachelor'?s?\s+|undergraduate\s+|university\s+)?students?)?"
    r"(?P<plus>\s+(?:students?\s+)?(?:and|or)\s+(?:above|higher|later|beyond|older))?",
    re.I,
)
OPEN_ENDED_BEFORE = re.compile(r"(?:с|начиная\s+с|не\s+ниже|from|at\s+least|minimum)\s*$", re.I)
STUDENT_CONTEXT = re.compile(
    r"студент|обучающ|учащ|student|бакалавр|магистр|university|университет|вуз|жоо|оқитын|undergrad|bachelor",
    re.I,
)
GRADUATES = re.compile(r"выпускник\w*|(?<![\w])(?:recent\s+)?graduates?(?![\w])|түлек\w*|жас\s+маман\w*", re.I)
DEGREES = [
    ("bachelor", re.compile(r"бакалавр\w*|bachelor\w*|undergrad\w*", re.I)),
    ("master", re.compile(r"магистр\w*|магистрант\w*|master'?s|masters\s+(?:students?|degree|program)", re.I)),
    ("phd", re.compile(r"(?<![\w])ph\.?d|докторант\w*|аспирант\w*", re.I)),
]


def eligibility(text: str) -> list[Candidate]:
    min_year = max_year = None
    span = None
    for pattern in (COURSE, EN_YEAR):
        for m in pattern.finditer(text):
            window = text[max(0, m.start() - 50) : m.end() + 50]
            if not STUDENT_CONTEXT.search(window):
                continue
            nums = [int(n) for n in re.findall(r"[1-6]", m.group("nums"))]
            if not nums:
                continue
            open_ended = bool(m.group("plus")) or bool(
                OPEN_ENDED_BEFORE.search(text[max(0, m.start() - 15) : m.start()])
            )
            min_year, max_year = min(nums), (None if open_ended else max(nums))
            span = m.span()
            break
        if span:
            break

    graduates = GRADUATES.search(text)
    degrees = sorted({name for name, pattern in DEGREES if pattern.search(text)})
    if span is None and not graduates and not degrees:
        return []
    value = {
        "min_year": min_year,
        "max_year": max_year,
        "graduates": True if graduates else None,
        "degrees": degrees,
    }
    if span is not None:
        return [Candidate(value, 0.85, "rule:study_year", span)]
    first = graduates.span() if graduates else None
    return [Candidate(value, 0.75, "rule:eligibility_mentions", first)]


# --------------------------------------------------------------------------- application link

URL = re.compile(
    r"(?:https?://|www\.)[^\s<>\"'()\[\]{}«»]+|(?<![\w/.])(?:forms\.gle|bit\.ly|t\.me)/[^\s<>\"'()\[\]{}«»]+", re.I
)
EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
APPLY_CUE = re.compile(
    r"apply|application|подать|подач|заявк|отклик|анкет|регистрац|резюме|(?<![\w])cv(?![\w])|өтінім|тіркел|"
    r"форм[ауе]|(?<![\w])form(?![\w])|ссылк|link|сілтеме|send|отправ|жіберу",
    re.I,
)
FORM_HOSTS = re.compile(
    r"forms\.gle|docs\.google\.com/forms|forms\.office\.com|typeform\.com|jotform|tally\.so|"
    r"(?:^|[/.])(?:careers?|jobs)\.|/careers?(?:/|$)|/vacanc|/jobs?(?:/|$)",
    re.I,
)


def _clean_url(raw: str) -> str:
    url = raw.rstrip(".,;:!?)»”'\"")
    return url if re.match(r"https?://", url, re.I) else "https://" + url


def apply_url(text: str, posting_url: str | None, source_apply_url: str | None) -> list[Candidate]:
    out: list[Candidate] = []
    if source_apply_url:
        out.append(Candidate(source_apply_url, 0.95, "source:apply_url", priority=SOURCE))
    for m in URL.finditer(text):
        url = _clean_url(m.group(0))
        ctx = text[max(0, m.start() - 80) : m.start()]
        if APPLY_CUE.search(ctx):
            out.append(Candidate(url, 0.9, "rule:apply_url_cue", m.span(), TEXT_STRONG))
        elif FORM_HOSTS.search(url):
            out.append(Candidate(url, 0.8, "rule:apply_url_form", m.span(), TEXT_STRONG))
    for m in EMAIL.finditer(text):
        ctx = text[max(0, m.start() - 80) : m.start()]
        if APPLY_CUE.search(ctx):
            out.append(Candidate("mailto:" + m.group(0), 0.8, "rule:apply_email", m.span(), TEXT_STRONG))
    if posting_url:
        out.append(Candidate(posting_url, 0.7, "fallback:posting_url"))
    return out
