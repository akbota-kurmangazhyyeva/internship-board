"""Part B unit tests: HTTP client, adapters, raw response store, seed tools, retry policy. No database needed.

Fixtures in tests/fixtures follow the real response formats (hh.ru /vacancies/{id}, WordPress /wp-json/wp/v2/...),
with fictional employers. Replace them with recorded responses from data/snapshots when the token arrives.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from app.ingest.adapters import FetchContext, build_registry
from app.ingest.adapters.hh import HeadHunterAdapter, map_vacancy, parse_hh_datetime
from app.ingest.adapters.seed_file import SeedFileAdapter
from app.ingest.adapters.wordpress import WordPressJobsAdapter
from app.ingest.errors import PermanentError, TransientError
from app.ingest.http import PoliteClient
from app.ingest.runner import RunReport
from app.ingest.seed_tools import csv_to_postings, merge_seed, write_jsonl
from app.ingest.settings import IngestSettings
from app.ingest.snapshots import RawResponseStore, iter_snapshots

FIX = Path(__file__).parent / "fixtures"


def client(handler, store=None, **kw) -> PoliteClient:
    sleeps: list[float] = []
    c = PoliteClient(
        user_agent="test-agent (t@example.org)",
        store=store,
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
        **kw,
    )
    c.sleeps = sleeps  # type: ignore[attr-defined]
    return c


# --------------------------------------------------------------------------- HTTP client


def test_retries_5xx_then_succeeds_and_honours_retry_after():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        if len(calls) == 1:
            return httpx.Response(503)
        if len(calls) == 2:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, json={"ok": True})

    c = client(handler, max_retries=3, min_interval=0)
    data, _ = c.get_json("https://api.example/x")
    assert data == {"ok": True}
    assert len(calls) == 3
    assert 7.0 in c.sleeps  # Retry-After used for 429
    assert calls[0].headers["User-Agent"].startswith("test-agent")


def test_gives_up_with_transient_error():
    c = client(lambda r: httpx.Response(502), max_retries=2, min_interval=0)
    with pytest.raises(TransientError):
        c.get("https://api.example/x")


def test_network_error_is_transient():
    def handler(req):
        raise httpx.ConnectError("boom", request=req)

    with pytest.raises(TransientError):
        client(handler, max_retries=1, min_interval=0).get("https://api.example/x")


@pytest.mark.parametrize("status", [401, 403])
def test_access_denied_is_permanent(status):
    with pytest.raises(PermanentError):
        client(lambda r: httpx.Response(status), min_interval=0).get("https://api.example/x")


def test_rate_limit_waits_between_requests_to_same_host():
    t = [0.0]
    c = PoliteClient(
        user_agent="ua",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text="x")),
        min_interval=1.5,
        sleep=lambda s: t.__setitem__(0, t[0] + s),
        clock=lambda: t[0],
    )
    c.get("https://a.example/1")
    c.get("https://a.example/2")
    assert t[0] == pytest.approx(1.5)


def test_robots_txt_is_respected():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")
        return httpx.Response(200, json=[])

    c = client(handler, min_interval=0)
    c.get("https://site.example/public/jobs", check_robots=True)
    with pytest.raises(PermanentError, match="robots"):
        c.get("https://site.example/private/jobs", check_robots=True)


# --------------------------------------------------------------------------- raw response store


def test_store_writes_gzip_snapshots_and_replays(tmp_path):
    store = RawResponseStore(tmp_path, "demo")
    c = client(
        lambda r: httpx.Response(200, json={"v": 1}, headers={"Set-Cookie": "secret", "ETag": "abc"}),
        store=store,
        min_interval=0,
    )
    c.get("https://api.example/v")
    files = list((tmp_path / "demo").rglob("*.json.gz"))
    assert len(files) == 1
    snap = next(iter_snapshots(tmp_path, "demo"))
    assert snap["status"] == 200 and json.loads(snap["body"]) == {"v": 1}
    assert "set-cookie" not in snap["headers"] and snap["headers"]["etag"] == "abc"  # cookies never stored
    assert len(snap["sha256"]) == 64


# --------------------------------------------------------------------------- HeadHunter


def test_hh_mapping_uses_structured_fields():
    p = map_vacancy(json.loads((FIX / "hh_vacancy.json").read_text()))
    assert p.external_id == "120000001"
    assert p.url == "https://hh.kz/vacancy/120000001"
    assert p.employer == "ТОО «Пример Финтех»"
    assert p.published_at == datetime(2026, 11, 20, 5, 15, tzinfo=UTC)
    sf = p.source_fields
    assert sf["city"] == ["Алматы"]
    assert sf["work_format"] == "hybrid"
    assert sf["employment"] == "internship"
    assert sf["experience"] == "noExperience"
    assert sf["salary"] == {"from": 150000, "to": 200000, "currency": "KZT", "gross": False}
    assert sf["skills"] == ["SQL", "Python", "Power BI"]
    assert "branded_description" not in p.payload


def test_hh_mapping_leaves_ambiguous_format_to_text_rules():
    v = json.loads((FIX / "hh_vacancy.json").read_text())
    v["work_format"] = [{"id": "REMOTE"}, {"id": "ON_SITE"}]
    v["salary_range"] = None
    assert "work_format" not in map_vacancy(v).source_fields
    assert "salary" not in map_vacancy(v).source_fields


def test_hh_datetime_without_colon():
    assert parse_hh_datetime("2026-11-20T10:15:00+0300").utcoffset() == timedelta(hours=3)
    assert parse_hh_datetime(None) is None


def test_hh_refuses_to_run_without_token():
    with pytest.raises(PermanentError, match="HH_APP_TOKEN"):
        HeadHunterAdapter(IngestSettings(hh_app_token=None, hh_stub_path=Path("/nonexistent.json"))).check_config()


def test_hh_stub_mode_without_token_serves_labelled_demo_data():
    stub = Path(__file__).resolve().parent.parent / "data" / "hh_stub" / "vacancies.json"
    adapter = HeadHunterAdapter(IngestSettings(hh_app_token=None, hh_stub_path=stub))
    assert adapter.stub_mode and "STUB" in adapter.name
    out = list(adapter.fetch(FetchContext(client=client(lambda r: httpx.Response(500)))))  # no network used
    assert len(out) == 6
    assert all(p.external_id.startswith("stub-") and p.payload["stub"] for p in out)
    assert not HeadHunterAdapter(IngestSettings(hh_app_token="tok", hh_stub_path=stub)).stub_mode


def test_hh_fetch_search_then_detail_skips_archived():
    detail = json.loads((FIX / "hh_vacancy.json").read_text())

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["Authorization"] == "Bearer tok"
        assert "HH-User-Agent" in req.headers
        if req.url.path == "/vacancies":
            assert req.url.params["area"] == "40"
            return httpx.Response(200, json={"items": [{"id": "1"}, {"id": "2"}], "pages": 1, "found": 2})
        if req.url.path == "/vacancies/1":
            return httpx.Response(200, json={**detail, "id": "1"})
        return httpx.Response(200, json={**detail, "id": "2", "archived": True})

    ctx = FetchContext(client=client(handler, min_interval=0))
    out = list(HeadHunterAdapter(IngestSettings(hh_app_token="tok")).fetch(ctx))
    assert [p.external_id for p in out] == ["1"]
    assert ctx.complete


# --------------------------------------------------------------------------- WordPress career sites


def _wp_handler(req: httpx.Request) -> httpx.Response:
    if req.url.path == "/robots.txt":
        return httpx.Response(200, text="User-agent: *\nDisallow:\n")
    return httpx.Response(200, text=(FIX / "wp_open_position.json").read_text(), headers={"X-WP-TotalPages": "1"})


def test_wordpress_adapter_keeps_kazakhstan_postings_only():
    adapter = WordPressJobsAdapter(
        key="w", name="W", base_url="https://careers.example", rest_base="open_position", employer="Example"
    )
    ctx = FetchContext(client=client(_wp_handler, min_interval=0))
    out = list(adapter.fetch(ctx))
    assert [p.external_id for p in out] == ["7569"]
    p = out[0]
    assert p.title == "Data Analyst Intern – Kazakhstan"  # HTML entities decoded
    assert p.employer == "Example" and p.apply_url == p.url
    assert p.published_at == datetime(2026, 11, 26, 9, 22, 8, tzinfo=UTC)
    assert ctx.complete


# --------------------------------------------------------------------------- seed file + seed tools


def test_seed_file_adapter_skips_bad_lines(tmp_path):
    f = tmp_path / "seed.jsonl"
    good = {"external_id": "a", "url": "https://x/a", "title": "Intern"}
    f.write_text(json.dumps(good) + "\n{not json}\n" + json.dumps({"title": "no id"}) + "\n", encoding="utf-8")
    adapter = SeedFileAdapter(f)
    ctx = FetchContext(client=client(lambda r: httpx.Response(200)))
    assert [p.external_id for p in adapter.fetch(ctx)] == ["a"]
    assert len(adapter.errors) == 2


def test_seed_file_missing_is_permanent(tmp_path):
    with pytest.raises(PermanentError):
        SeedFileAdapter(tmp_path / "nope.jsonl").check_config()


def test_csv_to_seed_and_merge(tmp_path):
    csv_path = tmp_path / "manual.csv"
    csv_path.write_text(
        "source,url,title,employer,published_at,description,apply_url\n"
        "telegram,https://t.me/jobs_kz/101,Стажер QA,Kolesa Group,2026-11-20,Ищем стажера QA в Алматы,\n"
        "linkedin,,Missing url,X,,text,\n",
        encoding="utf-8",
    )
    postings, errors = csv_to_postings(csv_path)
    assert len(postings) == 1 and len(errors) == 1 and "url" in errors[0]
    p = postings[0]
    assert p.external_id.startswith("telegram:")
    assert p.published_at == datetime(2026, 11, 20, tzinfo=UTC)
    a = tmp_path / "a.jsonl"
    write_jsonl(postings, a)
    counts = merge_seed([a, a], tmp_path / "all.jsonl")  # duplicates dropped
    assert counts == {"telegram": 1}


# --------------------------------------------------------------------------- registry and retry policy


def test_registry_has_seed_and_two_live_sources():
    reg = build_registry(IngestSettings())
    assert {"seed_file", "hh_kz", "indrive_careers"} <= set(reg)
    assert all(a.policy_notes for a in reg.values())


def test_retry_policy():
    from app.worker import retry_delay, should_retry

    transient = RunReport("x", "failed", 1, transient=True)
    permanent = RunReport("x", "failed", 1, transient=False)
    assert should_retry(transient, 0, max_retries=3)
    assert not should_retry(transient, 3, max_retries=3)
    assert not should_retry(permanent, 0, max_retries=3)
    assert not should_retry(RunReport("x", "success", 1), 0, max_retries=3)
    assert 60 <= retry_delay(0, base=60) <= 72 and 240 <= retry_delay(2, base=60) <= 288


def test_beat_schedule_covers_every_source():
    from app.worker import build_schedule

    sched = build_schedule()
    assert "expire-vacancies" in sched
    assert {"collect:seed_file", "collect:hh_kz", "collect:indrive_careers"} <= set(sched)
