"""Field extraction rules. Postings here are synthetic, written for the tests, and never part of an evaluation set."""

from datetime import UTC, datetime

import pytest

from app.extraction import PostingText, extract
from app.extraction.salary import salary_candidates
from app.extraction.vocab import normalize_city, normalize_skill

PUB = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)


def run(title: str, description: str = "", **kw):
    kw.setdefault("published_at", PUB)
    return extract(PostingText(title=title, description=description, **kw))


# --------------------------------------------------------------------------- deadline


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Прием заявок до 15 декабря.", "2026-12-15"),
        ("Срок подачи заявок: 15.12.2026", "2026-12-15"),
        ("Дедлайн — 1 декабря 2026 года", "2026-12-01"),
        ("Applications close December 1, 2026.", "2026-12-01"),
        ("Apply by 10 Jan.", "2027-01-10"),  # year inferred: January after a November posting
        ("Өтінімдер 2026 жылғы 10 желтоқсанға дейін қабылданады.", "2026-12-10"),
        ("Құжаттарды 15.12.2026 дейін жіберіңіз, өтінім қабылдау аяқталады.", "2026-12-15"),
        ("Отправьте резюме до 5 декабря.", "2026-12-05"),  # weak cue "до" + application context
        ("Deadline: 2026-12-20", "2026-12-20"),
    ],
)
def test_deadline_found(text, expected):
    f = run("Стажер", text).fields["deadline"]
    assert f.status == "ok", f
    assert f.public == expected
    assert f.evidence and f.method


@pytest.mark.parametrize(
    "text",
    [
        "Стажировка проходит с 10 января до 31 марта.",  # a period, not a deadline
        "Internship runs from June 1 until August 31.",
        "Начало стажировки: 1 июня 2027 года.",  # start date, no cue
        "Опубликовано 20.11.2026",
        "Зарплата до 200 000 тенге.",  # "до" before money, not a date
        "Требуется Python 3.11 и опыт с Django.",
    ],
)
def test_no_deadline_invented(text):
    assert run("Стажер", text).public("deadline") is None


def test_relative_deadline_is_low_confidence_not_a_date():
    f = run("Стажер", "Заявки принимаются до конца месяца.").fields["deadline"]
    assert f.public is None
    assert f.status == "low_confidence"


def test_bare_until_without_application_context_is_unknown():
    f = run("Стажер", "Акция действует до 5 декабря.").fields["deadline"]
    assert f.public is None and f.status == "low_confidence"


def test_two_different_deadlines_conflict():
    f = run("Intern", "Deadline: 1 December 2026. Applications close 15 December 2026.").fields["deadline"]
    assert f.status == "conflict" and f.public is None
    assert len(f.details["candidates"]) == 2


def test_deadline_in_the_past_is_not_shown():
    f = run("Стажер", "Прием заявок до 1 ноября 2026 года.").fields["deadline"]
    assert f.public is None and f.details.get("before_posting_date")


def test_source_deadline_outranks_text():
    f = run("Intern", "Deadline: 1 December 2026", source_fields={"deadline": "2026-12-05"}).fields["deadline"]
    assert f.public == "2026-12-05" and f.method == "source:deadline"


# --------------------------------------------------------------------------- salary


@pytest.mark.parametrize(
    "text, lo, hi, cur",
    [
        ("Зарплата: от 150 000 до 250 000 тенге на руки", 150000, 250000, "KZT"),
        ("Стипендия 100 000 ₸ в месяц", 100000, 100000, "KZT"),
        ("Оплата стажировки: 150-200 тыс. тенге", 150000, 200000, "KZT"),
        ("Salary: $500–800 per month", 500, 800, "USD"),
        ("Жалақы: 120 000 теңге", 120000, 120000, "KZT"),
        ("Зарплата до 300 000 тг", None, 300000, "KZT"),
        ("Доход от 200к ₸", 200000, None, "KZT"),
        ("Stipend 1,5 млн тенге", 1500000, 1500000, "KZT"),
    ],
)
def test_salary_as_stated(text, lo, hi, cur):
    f = run("Intern", text).fields["salary"]
    assert f.status == "ok", f
    assert (f.public["min"], f.public["max"], f.public["currency"]) == (lo, hi, cur)


def test_salary_net_and_period():
    v = run("Intern", "Зарплата от 150 000 до 250 000 тенге на руки в месяц").public("salary")
    assert v["gross_net"] == "net" and v["period"] == "month"


@pytest.mark.parametrize(
    "text",
    [
        "Звоните: +7 701 123 45 67",
        "В компании 5 000 сотрудников",
        "Опыт работы от 1 до 3 лет",
        "Основана в 2005 году, офис 305",
        "Зарплата по результатам собеседования",
        "Competitive salary and benefits",
    ],
)
def test_no_salary_invented(text):
    assert run("Intern", text).public("salary") is None


def test_unpaid():
    v = run("Intern", "This is an unpaid internship.").public("salary")
    assert v["unpaid"] is True and v["min"] is None


def test_source_salary_preferred():
    src = {"salary": {"from": 150000, "to": None, "currency": "KZT", "gross": False}}
    v = run("Intern", "Зарплата 999 999 тг", source_fields=src).public("salary")
    assert v["min"] == 150000 and v["gross_net"] == "net"


def test_salary_same_amount_twice_is_not_a_conflict():
    f = run("Intern", "Стипендия 100 000 тг.\nУсловия: стипендия 100 000 ₸ в месяц").fields["salary"]
    assert f.status == "ok"


def test_salary_candidates_keep_exact_text():
    (cand,) = salary_candidates("Стипендия 100 000 ₸")
    assert cand.value["text"] == "100 000 ₸"


# --------------------------------------------------------------------------- level & internship (DR-04)


@pytest.mark.parametrize(
    "title, description, is_intern, level",
    [
        ("Стажер Python-разработчик", "", True, "intern"),
        ("Data Analyst Intern", "", True, "intern"),
        ("Маркетинг бойынша тағылымдамашы", "", True, "intern"),
        ("Аналитик данных", "Приглашаем на оплачиваемую стажировку.", True, "intern"),
        ("Junior QA engineer", "Опыт работы не требуется.", False, "junior"),
        ("Senior Java Developer", "Опыт работы от 5 лет.", False, "senior"),
        ("Python developer", "At least 3 years of experience.", False, "mid"),
        ("Бухгалтер", "Опыт работы от 1 года.", False, "junior"),
    ],
)
def test_internship_and_level(title, description, is_intern, level):
    r = run(title, description)
    assert r.public("is_internship") is is_intern
    assert r.public("level") == level


def test_level_title_contradicted_by_experience_is_conflict():
    f = run("Junior developer", "Требуется опыт работы от 5 лет.").fields["level"]
    assert f.status == "conflict" and f.public is None


def test_source_employment_marks_internship():
    r = run("Помощник бухгалтера", "", source_fields={"employment": "probation"})
    assert r.public("is_internship") is True and r.public("level") == "intern"


# --------------------------------------------------------------------------- work format


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Формат: гибридный", "hybrid"),
        ("Работа удаленно", "remote"),
        ("Fully remote role", "remote"),
        ("Работа в офисе в центре города", "onsite"),
        ("Удаленная работа не предусмотрена, только офис.", "onsite"),
        ("Қашықтан жұмыс", "remote"),
        ("Hybrid: 3 days in the office", "hybrid"),
    ],
)
def test_work_format(text, expected):
    assert run("Intern", text).public("work_format") == expected


def test_remote_and_office_is_conflict():
    f = run("Intern", "Удаленно или в офисе — на ваш выбор.").fields["work_format"]
    assert f.status == "conflict"


def test_remote_access_is_not_remote_work():
    assert run("Intern", "Experience with remote access tools").public("work_format") is None


# --------------------------------------------------------------------------- cities (DR-05)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Офис в Алматы", ["Almaty"]),
        ("Работа в Нур-Султане", ["Astana"]),
        ("Астанадағы кеңседе", ["Astana"]),
        ("Location: Shymkent", ["Shymkent"]),
        ("Офисы в Алматы и Астане", ["Almaty", "Astana"]),
        ("г. Усть-Каменогорск", ["Oskemen"]),
        ("Семейный бизнес, дружный коллектив", []),  # "семейный" is not Semey
        ("Oral communication skills", []),  # English "oral" is not the city Oral
    ],
)
def test_cities(text, expected):
    assert run("Intern", text).public("cities") == expected


def test_source_city_overrides_text_mentions():
    r = run("Intern", "Head office in Astana", source_fields={"city": "Алматы"})
    assert r.public("cities") == ["Almaty"]


# --------------------------------------------------------------------------- skills


def test_skills_basic_and_aliases():
    r = run("Стажер", "Знание Python, PostgreSQL (postgres), Git, 1С и анализа данных. React.js будет плюсом.")
    assert set(r.public("skills")) == {"Python", "PostgreSQL", "Git", "1C", "Data Analysis", "React"}


def test_ambiguous_short_skills_need_context():
    assert "C" in run("Intern", "Languages: C, C++, Python").public("skills")
    assert "C" not in run("Intern", "Driving licence category C").public("skills")
    assert "Go" in run("Intern", "Stack: Go, PostgreSQL, Docker").public("skills")
    assert "Go" not in run("Intern", "Go to our website to learn more").public("skills")


def test_javascript_is_not_java_and_excel_verb_ignored():
    skills = run("Intern", "JavaScript and TypeScript. You will excel in a fast team.").public("skills")
    assert "JavaScript" in skills and "Java" not in skills and "Excel" not in skills


def test_source_skills_are_merged():
    r = run("Intern", "Знание SQL", source_fields={"skills": ["Python", "Something unknown"]})
    assert r.public("skills") == ["Python", "SQL"]


# --------------------------------------------------------------------------- languages


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Английский язык не ниже B2", ["en"]),
        ("Fluent English, Kazakh is a plus", ["en", "kk"]),
        ("Знание казахского и русского языков", ["kk", "ru"]),
        ("Қазақ тілін еркін меңгеру", ["kk"]),
        ("Мемлекеттік тілді білу", ["kk"]),
        ("Студенты Казахского национального университета", []),
    ],
)
def test_languages(text, expected):
    assert run("Intern", text).public("languages") == expected


def test_language_level_recorded():
    f = run("Intern", "English B2 or higher").fields["languages"]
    assert f.details["levels"]["en"] == "B2"


# --------------------------------------------------------------------------- eligibility (DR-08)


@pytest.mark.parametrize(
    "text, years",
    [
        ("Приглашаем студентов 3-4 курсов", (3, 4)),
        ("студенты 2, 3 и 4 курсов", (2, 4)),
        ("Студенты с 3 курса", (3, None)),
        ("3 курс және одан жоғары студенттер", (3, None)),
        ("Open to 3rd and 4th year students", (3, 4)),
        ("2nd year students and above", (2, None)),
    ],
)
def test_study_years(text, years):
    v = run("Intern", text).public("eligibility")
    assert (v["min_year"], v["max_year"]) == years


def test_course_without_student_context_is_ignored():
    assert run("Intern", "Пройдено 2 курса по Python").public("eligibility") is None


def test_four_year_degree_is_not_study_year():
    v = run("Intern", "Bachelor's students in a 4-year degree program").public("eligibility")
    assert v is None or v["min_year"] is None


def test_graduates_and_degrees():
    v = run("Intern", "Приглашаем выпускников и магистрантов").public("eligibility")
    assert v["graduates"] is True and v["degrees"] == ["master"]


# --------------------------------------------------------------------------- application link & language


def test_apply_link_prefers_cue_url_over_fallback():
    r = run(
        "Intern",
        "Подробнее: https://company.kz/about\nПодать заявку: https://forms.gle/abc123.",
        url="https://hh.kz/vacancy/1",
    )
    assert r.public("apply_url") == "https://forms.gle/abc123"


def test_apply_email_and_fallback():
    assert run("Intern", "Send your CV to hr@company.kz").public("apply_url") == "mailto:hr@company.kz"
    assert (
        run("Intern", "No links here", url="https://hh.kz/vacancy/9").public("apply_url") == "https://hh.kz/vacancy/9"
    )


@pytest.mark.parametrize(
    "text, lang",
    [
        ("Мы ищем стажера в команду аналитики данных. Требования: знание SQL и Excel, внимательность.", "ru"),
        ("Біз деректерді талдау командасына тағылымдамашы іздейміз. Талаптар: SQL және Excel білу.", "kk"),
        ("We are looking for an intern to join our data analytics team. You will work with SQL and Excel.", "en"),
    ],
)
def test_posting_language(text, lang):
    assert run("Intern", text).public("posting_language") == lang


# --------------------------------------------------------------------------- general


def test_html_is_normalised_and_provenance_kept():
    r = run("Стажер", "<p>Прием заявок&nbsp;до <b>15 декабря</b>.</p><ul><li>Python</li></ul>")
    f = r.fields["deadline"]
    assert f.public == "2026-12-15"
    assert "15 декабря" in f.evidence and f.span is not None


def test_every_field_present_even_for_empty_posting():
    r = run("Vacancy", "")
    assert set(r.fields) >= {
        "level",
        "skills",
        "cities",
        "work_format",
        "deadline",
        "salary",
        "languages",
        "eligibility",
        "apply_url",
    }
    assert r.public("skills") == [] and r.public("deadline") is None


def test_vocab_normalisation():
    assert normalize_skill("postgres") == "PostgreSQL"
    assert normalize_skill("Питон") == "Python"
    assert normalize_skill("excel") == "Excel"
    assert normalize_city("Нур-Султан") == "Astana"
    assert normalize_city("Алматы") == "Almaty"
    assert normalize_city("Qaragandy") == "Karaganda"
    assert normalize_city("Atlantis") is None
