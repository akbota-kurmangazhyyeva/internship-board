"""HeadHunter (hh.kz) adapter, through the official API.

Policy: official API, so robots.txt does not apply, but the API terms do: a registered application, a token, an
honest HH-User-Agent with a contact, and modest request rates. Since 2026 anonymous /vacancies requests get HTTP 403,
so this adapter refuses to run without HH_APP_TOKEN instead of hammering the API.

One run = search pages (newest first) + one detail request per vacancy, because only the detail has the full
description and key_skills. hh.ru returns at most 2000 results per query; if we hit that cap the run is not
complete, so nothing is marked missing.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from datetime import datetime
from typing import Any

from app.ingest.adapters.base import Adapter, FetchContext
from app.ingest.contract import RawPostingIn
from app.ingest.errors import PermanentError
from app.ingest.settings import IngestSettings

API = "https://api.hh.ru"
_HH_FORMATS = {"REMOTE": "remote", "HYBRID": "hybrid", "ON_SITE": "onsite"}
_TZ_NO_COLON = re.compile(r"([+-]\d{2})(\d{2})$")


def parse_hh_datetime(value: str | None) -> datetime | None:
    """hh returns '2026-11-20T10:15:00+0300'; Python wants '+03:00'."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(_TZ_NO_COLON.sub(r"\1:\2", value))
    except ValueError:
        return None


def _work_format(v: dict[str, Any]) -> str | None:
    formats = {_HH_FORMATS[f["id"]] for f in v.get("work_format") or [] if f.get("id") in _HH_FORMATS}
    if len(formats) == 1:
        return formats.pop()
    if not formats and (v.get("schedule") or {}).get("id") == "remote":
        return "remote"
    return None  # several formats offered, or not stated: let the text rules decide


def _employment(v: dict[str, Any]) -> str | None:
    if v.get("internship") is True:
        return "internship"
    if emp := (v.get("employment") or {}).get("id"):
        return emp  # "probation" is hh's id for стажировка
    if form := (v.get("employment_form") or {}).get("id"):
        return str(form).lower()
    return None


def _salary(v: dict[str, Any]) -> dict[str, Any] | None:
    s = v.get("salary_range") or v.get("salary")
    if not s or not (s.get("from") or s.get("to")):
        return None
    return {"from": s.get("from"), "to": s.get("to"), "currency": s.get("currency"), "gross": s.get("gross")}


def map_vacancy(v: dict[str, Any]) -> RawPostingIn:
    """Detail JSON from GET /vacancies/{id} → RawPostingIn. Pure function, tested with recorded fixtures."""
    source_fields: dict[str, Any] = {}
    cities = [c for c in [(v.get("area") or {}).get("name"), ((v.get("address") or {}) or {}).get("city")] if c]
    if cities:
        source_fields["city"] = list(dict.fromkeys(cities))
    if wf := _work_format(v):
        source_fields["work_format"] = wf
    if exp := (v.get("experience") or {}).get("id"):
        source_fields["experience"] = exp
    if emp := _employment(v):
        source_fields["employment"] = emp
    if sal := _salary(v):
        source_fields["salary"] = sal
    if skills := [s["name"] for s in v.get("key_skills") or [] if s.get("name")]:
        source_fields["skills"] = skills

    payload = {k: val for k, val in v.items() if k not in {"branded_description", "relations", "negotiations_url"}}
    return RawPostingIn(
        external_id=str(v["id"]),
        url=v.get("alternate_url") or f"https://hh.kz/vacancy/{v['id']}",
        title=v["name"],
        description=v.get("description") or _snippet_text(v),
        employer=(v.get("employer") or {}).get("name"),
        published_at=parse_hh_datetime(v.get("published_at")),
        apply_url=v.get("apply_alternate_url"),
        source_fields=source_fields,
        payload=payload,
    )


def _snippet_text(v: dict[str, Any]) -> str:
    snip = v.get("snippet") or {}
    return "\n".join(x for x in (snip.get("requirement"), snip.get("responsibility")) if x)


class HeadHunterAdapter(Adapter):
    key = "hh_kz"
    name = "HeadHunter Kazakhstan (hh.kz API)"
    kind = "api"
    base_url = API
    interval_minutes = 6 * 60
    full_scan = True
    policy_notes = (
        "Official API (api.hh.ru), area=40 Kazakhstan. Needs an application token from dev.hh.ru (manual moderation). "
        "Store attribution and link back to hh.kz; no personal data of applicants is collected."
    )

    def __init__(self, settings: IngestSettings) -> None:
        self.settings = settings
        if self.stub_mode:
            self.name = "HeadHunter (DEMO STUB, token pending)"
            self.kind = "file"
            self.full_scan = False

    @property
    def stub_mode(self) -> bool:
        """No token yet → serve the demo file instead of the API (placeholder; remove when the token arrives)."""
        return not self.settings.hh_app_token and self.settings.hh_stub_path.exists()

    def _fetch_stub(self, ctx: FetchContext) -> Iterator[RawPostingIn]:
        data = json.loads(self.settings.hh_stub_path.read_text(encoding="utf-8"))
        for n, item in enumerate(data.get("items") or [], 1):
            posting = map_vacancy(item)
            posting.external_id = f"stub-{posting.external_id}"  # never collides with real hh ids later
            posting.payload = {**(posting.payload or {}), "stub": True}
            yield posting
            if ctx.limit and n >= ctx.limit:
                return

    def check_config(self) -> None:
        if self.stub_mode:
            return
        if not self.settings.hh_app_token:
            raise PermanentError(
                "HH_APP_TOKEN is not set. hh.ru answers 403 to anonymous vacancy search; register an application at "
                "https://dev.hh.ru and put its token in .env"
            )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.hh_app_token}",
            "HH-User-Agent": self.settings.http_user_agent,
        }

    def fetch(self, ctx: FetchContext) -> Iterator[RawPostingIn]:
        if self.stub_mode:
            yield from self._fetch_stub(ctx)
            return
        self.check_config()
        s = self.settings
        yielded = 0
        pages_total = 1
        page = 0
        while page < min(pages_total, s.hh_max_pages):
            params: dict[str, Any] = {
                "text": s.hh_search_text,
                "area": s.hh_area,
                "per_page": 100,
                "page": page,
                "order_by": "publication_time",
                "host": "hh.kz",
            }
            data, _ = ctx.client.get_json(f"{API}/vacancies", params=params, headers=self._headers())
            pages_total = int(data.get("pages") or 0)
            for item in data.get("items") or []:
                detail, resp = ctx.client.get_json(
                    f"{API}/vacancies/{item['id']}", params={"host": "hh.kz"}, headers=self._headers()
                )
                if resp.status_code == 404 or detail.get("archived"):
                    continue
                yield map_vacancy(detail)
                yielded += 1
                if ctx.limit and yielded >= ctx.limit:
                    return
            page += 1
        found = int(data.get("found") or 0)
        ctx.complete = page >= pages_total and found < 2000  # saw every result page, and hh didn't truncate
