"""Synthetic postings for integration tests (fictional employers; not evaluation data)."""

from datetime import UTC, date, datetime, timedelta

from app.ingest.contract import RawPostingIn

NOW = datetime.now(UTC)
SOON = date.today() + timedelta(days=20)
SOON_RU = f"{SOON.day:02d}.{SOON.month:02d}.{SOON.year}"


def python_intern(external_id: str = "hh-1", **kw) -> RawPostingIn:
    data = dict(
        external_id=external_id,
        url=f"https://hh.example/vacancy/{external_id}",
        title="Стажер Python-разработчик",
        employer="ТОО «Дала Софт»",
        published_at=NOW - timedelta(days=2),
        description=(
            "<p>ТОО «Дала Софт» приглашает студентов 3-4 курсов на оплачиваемую стажировку Python-разработчика.</p>"
            "<ul><li>Python, SQL, Git</li><li>Английский язык не ниже B1</li></ul>"
            f"<p>Формат гибридный, офис в Алматы. Стипендия 150 000 тенге. Прием заявок до {SOON_RU}.</p>"
        ),
    )
    data.update(kw)
    return RawPostingIn(**data)


def python_intern_repost(external_id: str = "tg-77", **kw) -> RawPostingIn:
    data = dict(
        external_id=external_id,
        url=f"https://t.me/example_jobs/{external_id}",
        title="Python стажер в Дала Софт",
        employer="Дала Софт",
        published_at=NOW - timedelta(days=1),
        description=(
            "Дала Софт ищет стажеров! Студенты 3-4 курсов, оплачиваемая стажировка Python-разработчика. "
            "Требования: Python, SQL, Git, английский B1. Гибридный формат, Алматы. "
            f"Стипендия 150 000 тенге. Заявки принимаем до {SOON_RU}."
        ),
    )
    data.update(kw)
    return RawPostingIn(**data)


def data_intern(external_id: str = "hh-2", **kw) -> RawPostingIn:
    data = dict(
        external_id=external_id,
        url=f"https://hh.example/vacancy/{external_id}",
        title="Data Analyst Intern (Remote)",
        employer="Steppe Analytics LLP",
        published_at=NOW - timedelta(days=5),
        description=(
            "Steppe Analytics is looking for 3rd and 4th year students. Requirements: Excel, Power BI, SQL. "
            "Fluent English, Kazakh is a plus. Unpaid internship. Apply via https://forms.gle/steppe-apply."
        ),
    )
    data.update(kw)
    return RawPostingIn(**data)


def senior_java(external_id: str = "hh-3", **kw) -> RawPostingIn:
    data = dict(
        external_id=external_id,
        url=f"https://hh.example/vacancy/{external_id}",
        title="Senior Java Developer",
        employer="Qazaq Byte",
        published_at=NOW - timedelta(days=1),
        description="Опыт работы от 5 лет. Java, Spring Boot, Kafka. г. Шымкент, работа в офисе. Зарплата до 1 500 000 тг.",
    )
    data.update(kw)
    return RawPostingIn(**data)


def kazakh_marketing(external_id: str = "tg-5", **kw) -> RawPostingIn:
    data = dict(
        external_id=external_id,
        url=f"https://t.me/example_jobs/{external_id}",
        title="Маркетинг бойынша тағылымдамашы",
        employer="Nomad Media",
        published_at=NOW - timedelta(days=3),
        description=(
            "Біз Астанадағы кеңседе жұмыс істеуге 2-3 курс студенттерін шақырамыз. "
            "Талаптар: SMM, Figma, қазақ тілін еркін меңгеру. Жалақы: 120 000 ₸."
        ),
    )
    data.update(kw)
    return RawPostingIn(**data)
