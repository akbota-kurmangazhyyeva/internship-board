"""Company career sites built on WordPress, read through the public WordPress REST API.

Many career sites (e.g. careers.indrive.com, post type `open_position`) publish their vacancies as a custom post
type, which WordPress exposes as JSON at /wp-json/wp/v2/<rest_base>. It is the same public content as the HTML
pages, in a machine-readable form, so it is far more stable than scraping HTML. We still check robots.txt, keep the
rate low and link every card back to the original page.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from app.ingest.adapters.base import Adapter, FetchContext
from app.ingest.contract import RawPostingIn

KZ_LOCATION = re.compile(
    r"kazakhstan|qazaqstan|almaty|astana|shymkent|karaganda|aktobe|atyrau|aktau|pavlodar|ust-kamenogorsk|"
    r"казахстан|қазақстан|алматы|астана|шымкент|караганд|ақтөбе|актобе|атырау|актау|павлодар",
    re.I,
)


def _text(rendered: Any) -> str:
    if isinstance(rendered, dict):
        rendered = rendered.get("rendered")
    return html.unescape(str(rendered or "")).strip()


def map_post(post: dict[str, Any], *, employer: str) -> RawPostingIn:
    published = post.get("date_gmt") or post.get("date")
    published_at = datetime.fromisoformat(published).replace(tzinfo=UTC) if published else None
    link = post.get("link") or ""
    return RawPostingIn(
        external_id=str(post["id"]),
        url=link,
        title=_text(post.get("title")),
        description=_text(post.get("content")),
        employer=employer,
        published_at=published_at,
        apply_url=link or None,  # the apply form is on the posting page itself
        payload={k: post.get(k) for k in ("id", "slug", "link", "date_gmt", "modified_gmt", "type")},
    )


class WordPressJobsAdapter(Adapter):
    kind = "api"
    interval_minutes = 12 * 60
    full_scan = True

    def __init__(
        self,
        *,
        key: str,
        name: str,
        base_url: str,
        rest_base: str,
        employer: str,
        location_filter: re.Pattern[str] | None = KZ_LOCATION,
        policy_notes: str = "",
    ) -> None:
        self.key = key
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.rest_base = rest_base
        self.employer = employer
        self.location_filter = location_filter
        self.policy_notes = policy_notes or (
            "Public WordPress REST API of the employer's own career site; robots.txt checked on every run."
        )

    def keep(self, posting: RawPostingIn) -> bool:
        if self.location_filter is None:
            return True
        return bool(self.location_filter.search(posting.title) or self.location_filter.search(posting.description))

    def fetch(self, ctx: FetchContext) -> Iterator[RawPostingIn]:
        url = f"{self.base_url}/wp-json/wp/v2/{self.rest_base}"
        page, total_pages, yielded = 1, 1, 0
        while page <= total_pages:
            params = {
                "per_page": 100,
                "page": page,
                "orderby": "date",
                "order": "desc",
                "_fields": ("id,date,date_gmt,modified_gmt,slug,link,type,title,content"),
            }
            posts, resp = ctx.client.get_json(url, params=params, check_robots=True)
            total_pages = int(resp.headers.get("x-wp-totalpages") or 1)
            if not posts:
                break
            for post in posts:
                posting = map_post(post, employer=self.employer)
                if not self.keep(posting):
                    continue
                yield posting
                yielded += 1
                if ctx.limit and yielded >= ctx.limit:
                    return
            page += 1
        ctx.complete = True
