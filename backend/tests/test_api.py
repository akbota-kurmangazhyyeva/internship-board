"""API v0: auth, list/search/filter, detail, feed, profile, saved, consent, deletion."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.models import Interaction, User
from app.pipeline import ensure_source, ingest_posting
from tests.factories import NOW, SOON, data_intern, kazakh_marketing, python_intern, python_intern_repost, senior_java

API = "/api/v1"


@pytest.fixture
def seeded(db):
    ensure_source(db, "hh", name="HeadHunter (test)", kind="api")
    ensure_source(db, "tg", name="Telegram (test)", kind="telegram")
    ids = {}
    for key, source, posting in [
        ("python", "hh", python_intern()),
        ("python_repost", "tg", python_intern_repost()),
        ("data", "hh", data_intern()),
        ("java", "hh", senior_java()),
        ("kk", "tg", kazakh_marketing()),
    ]:
        ids[key] = ingest_posting(db, source, posting, now=NOW).canonical_vacancy_id
    db.commit()
    return ids


def auth(client, email="student@example.kz", password="correct-horse-1"):
    r = client.post(f"{API}/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


PROFILE = {
    "education_level": "bachelor",
    "year_of_study": 3,
    "field_of_study": "Computer Science",
    "skills": ["python", "SQL", "git", "Docker"],
    "preferred_cities": ["Алматы"],
    "work_formats": ["remote", "hybrid"],
    "languages": ["ru", "en"],
    "interests": ["data"],
}


# --------------------------------------------------------------------------- auth


def test_register_login_and_me(client):
    headers = auth(client)
    assert client.get(f"{API}/me", headers=headers).json()["email"] == "student@example.kz"
    assert (
        client.post(
            f"{API}/auth/register", json={"email": "Student@example.kz", "password": "whatever-123"}
        ).status_code
        == 409
    )
    ok = client.post(f"{API}/auth/login", json={"email": "STUDENT@example.kz", "password": "correct-horse-1"})
    assert ok.status_code == 200 and ok.json()["access_token"]
    assert (
        client.post(f"{API}/auth/login", json={"email": "student@example.kz", "password": "wrong-pass"}).status_code
        == 401
    )
    assert (
        client.post(f"{API}/auth/login", json={"email": "nobody@example.kz", "password": "wrong-pass"}).status_code
        == 401
    )


def test_password_is_hashed_and_short_passwords_rejected(client, db):
    auth(client)
    stored = db.scalar(select(User.password_hash))
    assert stored.startswith("$argon2") and "correct-horse-1" not in stored
    assert client.post(f"{API}/auth/register", json={"email": "a@b.kz", "password": "short"}).status_code == 422


def test_invalid_token_is_rejected_even_on_public_routes(client):
    bad = {"Authorization": "Bearer nonsense"}
    assert client.get(f"{API}/vacancies", headers=bad).status_code == 401
    assert client.get(f"{API}/me").status_code == 401


# --------------------------------------------------------------------------- list / search / filter / detail


def test_list_is_deduplicated_and_newest_first_for_guests(client, seeded):
    body = client.get(f"{API}/vacancies").json()
    assert body["total"] == 4  # five postings, one repost merged
    assert seeded["python"] == seeded["python_repost"]
    published = [v["published_at"] for v in body["items"]]
    assert published == sorted(published, reverse=True)
    assert all(v["fit"] is None and v["is_saved"] is None for v in body["items"])
    python_card = next(v for v in body["items"] if v["id"] == seeded["python"])
    assert python_card["sources"] == ["HeadHunter (test)", "Telegram (test)"]


@pytest.mark.parametrize(
    "q, expected_key",
    [
        ("стажировка", "python"),  # Russian stemming: стажировку / стажировка
        ("Python", "python"),
        ("analyst", "data"),
        ("тағылымдама", "kk"),  # Kazakh prefix match: тағылымдамашы
        ("Kafka", "java"),
    ],
)
def test_multilingual_search(client, seeded, q, expected_key):
    ids = [v["id"] for v in client.get(f"{API}/vacancies", params={"q": q}).json()["items"]]
    assert seeded[expected_key] in ids


@pytest.mark.parametrize(
    "params, expected",
    [
        ({"city": "Алматы"}, {"python"}),
        ({"city": ["Astana", "Shymkent"]}, {"kk", "java"}),
        ({"skill": "postgres"}, set()),
        ({"skill": ["SQL"]}, {"python", "data"}),
        ({"work_format": "remote"}, {"data"}),
        ({"level": "senior"}, {"java"}),
        ({"internship_only": True}, {"python", "data", "kk"}),
        ({"language": "kk"}, {"data", "kk"}),
        ({"deadline_to": (SOON + timedelta(days=1)).isoformat()}, {"python"}),
    ],
)
def test_filters(client, seeded, params, expected):
    ids = {v["id"] for v in client.get(f"{API}/vacancies", params=params).json()["items"]}
    assert ids == {seeded[k] for k in expected}


def test_sort_by_deadline_puts_unknown_last(client, seeded):
    items = client.get(f"{API}/vacancies", params={"sort": "deadline"}).json()["items"]
    assert items[0]["id"] == seeded["python"] and items[0]["deadline"] == SOON.isoformat()


def test_detail_has_provenance_sources_and_original_text(client, seeded):
    d = client.get(f"{API}/vacancies/{seeded['python']}").json()
    assert d["deadline"] == SOON.isoformat() and d["apply_url"]
    assert d["fields"]["deadline"]["status"] == "ok" and d["fields"]["deadline"]["evidence"]
    assert len(d["source_links"]) == 2 and all(link["live"] for link in d["source_links"])
    assert "Python" in d["description"]
    assert client.get(f"{API}/vacancies/999999").status_code == 404


def test_unknown_fields_are_null_not_guessed(client, seeded):
    d = client.get(f"{API}/vacancies/{seeded['kk']}").json()
    assert d["deadline"] is None and d["fields"]["deadline"]["status"] == "missing"


def test_pagination(client, seeded):
    page = client.get(f"{API}/vacancies", params={"limit": 2, "offset": 2}).json()
    assert page["total"] == 4 and len(page["items"]) == 2


# --------------------------------------------------------------------------- profile & feed


def test_profile_roundtrip_canonicalises_input(client):
    headers = auth(client)
    assert client.get(f"{API}/me/profile", headers=headers).status_code == 404
    r = client.put(f"{API}/me/profile", headers=headers, json=PROFILE)
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["skills"] == ["Python", "SQL", "Git", "Docker"] and p["preferred_cities"] == ["Almaty"]
    assert client.get(f"{API}/me/profile", headers=headers).json()["year_of_study"] == 3
    bad = client.put(f"{API}/me/profile", headers=headers, json={**PROFILE, "preferred_cities": ["Atlantis"]})
    assert bad.status_code == 422


def test_feed_ranks_with_reasons_and_applies_hard_constraints(client, seeded):
    headers = auth(client)
    client.put(f"{API}/me/profile", headers=headers, json=PROFILE)
    feed = client.get(f"{API}/feed", headers=headers).json()
    ids = [v["id"] for v in feed["items"]]
    assert ids[0] == seeded["python"]
    assert seeded["java"] not in ids  # senior + Shymkent office: hard constraints
    assert seeded["kk"] not in ids  # Astana office, student wants Almaty/remote
    top = feed["items"][0]["fit"]
    assert top["eligible"] and "skills match" in top["summary"] and "Almaty" in top["summary"]
    assert not feed["relaxed"] and feed["profile_complete"]


def test_feed_relaxes_when_nothing_matches(client, seeded):
    headers = auth(client)
    client.put(
        f"{API}/me/profile",
        headers=headers,
        json={**PROFILE, "preferred_cities": ["Taraz"], "work_formats": ["onsite"]},
    )
    feed = client.get(f"{API}/feed", headers=headers).json()
    assert feed["relaxed"] and feed["items"] and feed["hint"]


def test_list_defaults_to_fit_for_students_with_profile(client, seeded):
    headers = auth(client)
    assert client.get(f"{API}/vacancies", params={"sort": "fit"}, headers=headers).status_code == 400
    client.put(f"{API}/me/profile", headers=headers, json=PROFILE)
    items = client.get(f"{API}/vacancies", headers=headers).json()["items"]
    assert items[0]["id"] == seeded["python"] and items[0]["fit"]["score"] > 0
    assert not items[-1]["fit"]["eligible"]  # ineligible ones sink to the bottom but are not hidden


def test_dismiss_removes_from_feed_without_tracking_consent(client, seeded):
    headers = auth(client)
    client.put(f"{API}/me/profile", headers=headers, json=PROFILE)
    r = client.post(f"{API}/me/interactions", headers=headers, json={"vacancy_id": seeded["python"], "kind": "dismiss"})
    assert r.json() == {"recorded": True, "reason": None}
    ids = [v["id"] for v in client.get(f"{API}/feed", headers=headers).json()["items"]]
    assert seeded["python"] not in ids


def test_behavioural_signals_need_consent_and_are_erased_on_withdrawal(client, seeded, db):
    headers = auth(client)
    view = {"vacancy_id": seeded["data"], "kind": "view"}
    assert client.post(f"{API}/me/interactions", headers=headers, json=view).json() == {
        "recorded": False,
        "reason": "no_consent",
    }
    assert client.put(f"{API}/me/consent", headers=headers, json={"tracking": True}).json()["tracking_consent"] is True
    assert client.post(f"{API}/me/interactions", headers=headers, json=view).json()["recorded"] is True
    client.put(f"{API}/me/consent", headers=headers, json={"tracking": False})
    assert db.scalar(select(func.count()).select_from(Interaction).where(Interaction.kind == "view")) == 0


# --------------------------------------------------------------------------- saved & account


def test_saved_list_ordered_by_deadline(client, seeded):
    headers = auth(client)
    for key in ("data", "python"):
        assert client.put(f"{API}/me/saved/{seeded[key]}", headers=headers).status_code == 200
    saved = client.get(f"{API}/me/saved", headers=headers).json()
    assert [s["vacancy"]["id"] for s in saved] == [seeded["python"], seeded["data"]]  # known deadline first
    assert all(s["vacancy"]["is_saved"] for s in saved)
    assert (
        client.put(f"{API}/me/saved/{seeded['data']}", headers=headers, json={"remind": False}).json()["remind"]
        is False
    )
    assert client.delete(f"{API}/me/saved/{seeded['data']}", headers=headers).status_code == 204
    assert len(client.get(f"{API}/me/saved", headers=headers).json()) == 1
    assert client.put(f"{API}/me/saved/999999", headers=headers).status_code == 404


def test_account_deletion_removes_personal_data(client, seeded, db):
    headers = auth(client)
    client.put(f"{API}/me/profile", headers=headers, json=PROFILE)
    client.put(f"{API}/me/saved/{seeded['python']}", headers=headers)
    assert client.delete(f"{API}/me", headers=headers).status_code == 204
    assert db.scalar(select(func.count()).select_from(User)) == 0
    assert client.get(f"{API}/me", headers=headers).status_code == 401


def test_meta_and_health(client):
    meta = client.get(f"{API}/meta/filters").json()
    assert "Almaty" in meta["cities"] and "Python" in meta["skills"]
    assert client.get("/health").json() == {"status": "ok"}
