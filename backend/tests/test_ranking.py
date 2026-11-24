from datetime import UTC, date, datetime, timedelta

from app.ranking import Profile, VacancyView, rank, score

TODAY = date(2026, 11, 24)
NOW = datetime(2026, 11, 24, tzinfo=UTC)


def student(**kw):
    base = dict(
        skills=["Python", "SQL", "Git", "Docker"],
        interests=["data"],
        preferred_cities=["Almaty"],
        work_formats=["remote", "hybrid"],
        year_of_study=3,
        languages=["ru", "en"],
    )
    base.update(kw)
    return Profile(**base)


def vac(id, **kw):
    kw.setdefault("title", "Python Intern")
    kw.setdefault("level", "intern")
    return VacancyView(id=id, **kw)


def test_reason_summary_matches_fr20_format():
    fit = score(
        student(),
        vac(1, skills=["Python", "SQL", "Git", "Linux", "Docker", "AWS"], cities=["Almaty"], work_format="remote"),
        TODAY,
    )
    assert fit.eligible
    assert fit.summary.startswith("4 of 6 skills match")
    assert "Remote" in fit.summary


def test_hard_constraints():
    p = student()
    assert not score(p, vac(1, level="senior"), TODAY).eligible
    assert not score(p, vac(1, work_format="onsite"), TODAY).eligible
    assert not score(p, vac(1, cities=["Shymkent"], work_format="hybrid"), TODAY).eligible
    assert not score(p, vac(1, eligibility={"min_year": 4, "max_year": 4}), TODAY).eligible
    # remote jobs ignore location; relocation-friendly students are not excluded by city
    assert score(p, vac(1, cities=["Shymkent"], work_format="remote"), TODAY).eligible
    assert score(student(open_to_relocation=True), vac(1, cities=["Shymkent"], work_format="hybrid"), TODAY).eligible


def test_unknown_fields_never_exclude():
    assert score(student(), vac(1, level=None, work_format=None, cities=[], eligibility=None), TODAY).eligible


def test_better_match_ranks_higher():
    strong = vac(
        1,
        skills=["Python", "SQL", "Git", "Linux", "Docker", "AWS"],
        cities=["Almaty"],
        work_format="hybrid",
        eligibility={"min_year": 3, "max_year": 4},
        published_at=NOW - timedelta(days=2),
    )
    weak = vac(2, title="Data analyst intern", skills=["Excel", "SQL"], work_format="remote", languages=["kk"])
    result = rank(student(), [weak, strong], TODAY)
    assert [f.vacancy_id for f in result.items] == [1, 2]
    assert any(r.code == "language_missing" for r in result.items[1].reasons)


def test_relaxed_when_nothing_eligible():
    result = rank(
        student(preferred_cities=["Taraz"], work_formats=["onsite"]),
        [vac(1, cities=["Shymkent"], work_format="onsite"), vac(2, level="senior")],
        TODAY,
    )
    assert result.relaxed and len(result.items) == 2
    assert all(not f.eligible and f.violations for f in result.items)


def test_empty_profile_still_ranks():
    result = rank(Profile(), [vac(1, skills=["Python"]), vac(2)], TODAY)
    assert len(result.items) == 2 and not result.relaxed


def test_deadline_soon_is_informative():
    fit = score(student(), vac(1, deadline=TODAY + timedelta(days=3)), TODAY)
    assert any(r.code == "deadline_soon" and r.params["days"] == 3 for r in fit.reasons)
