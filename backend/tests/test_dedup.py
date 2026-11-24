from datetime import UTC, date, datetime, timedelta

from app.config import get_settings
from app.dedup import DedupRecord, Features, assign, cluster, employer_key, is_candidate, pair_score

T0 = datetime(2026, 11, 10, tzinfo=UTC)
DESC_RU = (
    "ТОО «Дала Софт» приглашает студентов 3-4 курсов на оплачиваемую стажировку Python-разработчика. "
    "Требования: Python, SQL, Git, базовое понимание REST API. Формат гибридный, офис в Алматы. "
    "Стипендия 150 000 тенге. Прием заявок до 15 декабря."
)
DESC_RU_REPOST = (
    "Дала Софт ищет стажеров! Студенты 3-4 курсов, оплачиваемая стажировка Python-разработчика. "
    "Требования: Python, SQL, Git, понимание REST API. Гибридный формат, Алматы. "
    "Стипендия 150 000 тенге. Заявки принимаем до 15 декабря."
)


def rec(id, title="Стажер Python-разработчик", employer="ТОО «Дала Софт»", desc=DESC_RU, days=0, **kw):
    kw.setdefault("cities", ["Almaty"])
    kw.setdefault("level", "intern")
    kw.setdefault("skills", ["Python", "SQL", "Git", "REST API"])
    return DedupRecord(
        id=id, title=title, description=desc, employer=employer, published_at=T0 + timedelta(days=days), **kw
    )


_S = get_settings()
KW = dict(merge_threshold=_S.dedup_merge_threshold, review_threshold=_S.dedup_review_threshold, window_days=60)


def test_employer_key_normalisation():
    assert employer_key("ТОО «Kaspi.kz»") == employer_key("Kaspi.kz LLP") == "kaspi"
    assert employer_key('АО "Дала Софт"') == employer_key("Дала Софт") == "dala soft"
    assert employer_key(None) is None


def test_repost_with_different_wording_merges():
    s = pair_score(Features.of(rec(1)), Features.of(rec(2, title="Python стажер", desc=DESC_RU_REPOST, days=3)))
    assert not s.vetoes and s.score >= KW["merge_threshold"], s


def test_cross_language_title_synonyms_help():
    a = Features.of(rec(1, title="Стажер Python-разработчик"))
    b = Features.of(
        rec(
            2,
            title="Python Developer Intern",
            desc="Dala Soft: paid Python internship for 3rd-4th year students. "
            "Python, SQL, Git, REST API. Hybrid, Almaty. Apply by December 15.",
        )
    )
    s = pair_score(a, b)
    assert s.components["title"] >= 0.6 and s.components["skills"] == 1.0


def test_vetoes_protect_distinct_opportunities():
    base = Features.of(rec(1))
    assert "different_city" in pair_score(base, Features.of(rec(2, cities=["Astana"]))).vetoes
    assert "different_level" in pair_score(base, Features.of(rec(2, level="junior"))).vetoes
    assert (
        "different_deadline"
        in pair_score(
            Features.of(rec(1, deadline=date(2026, 12, 15))), Features.of(rec(2, deadline=date(2027, 3, 1)))
        ).vetoes
    )
    assert "different_employer" in pair_score(base, Features.of(rec(2, employer="Steppe Analytics"))).vetoes


def test_unknown_fields_do_not_veto():
    assert not pair_score(Features.of(rec(1)), Features.of(rec(2, cities=[], level=None))).vetoes


def test_blocking():
    a = Features.of(rec(1))
    assert is_candidate(a, Features.of(rec(2, days=10)), 60)
    assert not is_candidate(a, Features.of(rec(2, days=90)), 60)  # outside publication window
    assert not is_candidate(a, Features.of(rec(2, employer="Другая компания")), 60)
    assert is_candidate(a, Features.of(rec(2, employer=None, title="Стажер Python разработчик")), 60)


def test_same_employer_different_role_not_merged():
    other = rec(
        2,
        title="Стажер-маркетолог",
        skills=["SMM", "Figma"],
        desc="Дала Софт ищет стажера в отдел маркетинга: SMM, Figma, копирайтинг. Офис в Алматы, стипендия 120 000 тенге.",
    )
    groups = cluster([rec(1), other], **KW)
    assert groups[1] != groups[2]


def test_cluster_groups_reposts_and_keeps_others_apart():
    records = [
        rec("a"),
        rec("b", title="Python стажер", desc=DESC_RU_REPOST, days=2),
        rec("c", cities=["Astana"], days=1),  # same text, other city: a different opportunity
        rec(
            "d",
            title="Data Analyst Intern",
            employer="Steppe Analytics",
            skills=["SQL", "Excel"],
            desc="Steppe Analytics hires data analyst interns. SQL, Excel, Power BI. Remote.",
            cities=[],
        ),
    ]
    groups = cluster(records, **KW)
    assert groups["a"] == groups["b"]
    assert len({groups["a"], groups["c"], groups["d"]}) == 3


def test_assign_reports_suspected_duplicates_between_thresholds():
    existing = {10: [Features.of(rec(1))]}
    near = Features.of(rec(2, title="Стажер Python", desc="Стажировка в Дала Софт. Python.", skills=["Python"]))
    d = assign(near, existing, **KW)
    assert d.group_id is None
    assert d.suspected and d.suspected[0][0] == 10


def test_same_employer_other_role_with_shared_boilerplate_goes_to_review_not_merge():
    java_desc = DESC_RU.replace("Python-разработчика", "Java-разработчика").replace(
        "Python, SQL, Git, базовое понимание REST API", "Java, Spring, SQL, Git"
    )
    java = Features.of(rec(2, title="Стажер Java-разработчик", desc=java_desc, skills=["Java", "Spring", "SQL", "Git"]))
    d = assign(java, {10: [Features.of(rec(1))]}, **KW)
    assert d.group_id is None and [g for g, _ in d.suspected] == [10]
