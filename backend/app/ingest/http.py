"""A small, polite HTTP client shared by all adapters.

* identifies itself with a User-Agent that includes a contact address;
* waits `min_interval` between requests to the same host (rate limit);
* checks robots.txt before fetching pages (RFC 9309) unless the adapter uses an official API;
* retries 429 / 5xx / network errors with exponential backoff, honouring Retry-After;
* saves every response to the raw response store;
* turns failures into TransientError (retry the run later) or PermanentError (don't).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from app.ingest.errors import PermanentError, TransientError
from app.ingest.snapshots import NullStore, RawResponseStore

_RETRY_STATUS = {429, 500, 502, 503, 504}


class PoliteClient:
    def __init__(
        self,
        *,
        user_agent: str,
        store: RawResponseStore | None = None,
        timeout: float = 20.0,
        max_retries: int = 3,
        min_interval: float = 1.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.user_agent = user_agent
        self.store = store or NullStore()
        self.max_retries = max_retries
        self.min_interval = min_interval
        self._sleep = sleep
        self._clock = clock
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}
        self.requests_made = 0
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": user_agent, "Accept": "application/json, text/html;q=0.9, */*;q=0.5"},
            follow_redirects=True,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PoliteClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ robots.txt

    def allowed_by_robots(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser: RobotFileParser | None = RobotFileParser()
            try:
                resp = self._request("GET", f"{origin}/robots.txt", save=False)
                if resp.status_code >= 400:
                    parser = None  # no robots.txt => everything allowed
                else:
                    parser.parse(resp.text.splitlines())
            except TransientError:
                raise
            self._robots[origin] = parser
        parser = self._robots[origin]
        return True if parser is None else parser.can_fetch(self.user_agent, url)

    # ------------------------------------------------------------------ requests

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        check_robots: bool = False,
    ) -> tuple[Any, httpx.Response]:
        resp = self.get(url, params=params, headers=headers, check_robots=check_robots)
        try:
            return resp.json(), resp
        except json.JSONDecodeError as exc:
            raise PermanentError(f"{url}: response is not JSON") from exc

    def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        check_robots: bool = False,
    ) -> httpx.Response:
        if check_robots and not self.allowed_by_robots(url):
            raise PermanentError(f"robots.txt disallows {url}")
        return self._request("GET", url, params=params, headers=headers)

    def _wait_for_host(self, host: str) -> None:
        last = self._last_request.get(host)
        if last is not None:
            delay = self.min_interval - (self._clock() - last)
            if delay > 0:
                self._sleep(delay)
        self._last_request[host] = self._clock()

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        save: bool = True,
    ) -> httpx.Response:
        host = urlsplit(url).netloc
        attempt = 0
        while True:
            attempt += 1
            self._wait_for_host(host)
            try:
                resp = self._client.request(method, url, params=params, headers=headers)
                self.requests_made += 1
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                if attempt > self.max_retries:
                    raise TransientError(f"{url}: {exc.__class__.__name__}: {exc}") from exc
                self._sleep(self._backoff(attempt))
                continue

            if save:
                self.store.save(
                    url=str(resp.request.url), status=resp.status_code, body=resp.text, headers=dict(resp.headers)
                )
            if resp.status_code in _RETRY_STATUS:
                if attempt > self.max_retries:
                    raise TransientError(f"{url}: HTTP {resp.status_code} after {attempt} attempts")
                self._sleep(self._retry_after(resp) or self._backoff(attempt))
                continue
            if resp.status_code in (401, 403):
                raise PermanentError(f"{url}: HTTP {resp.status_code} (access denied: check token / source policy)")
            if resp.status_code >= 400 and resp.status_code != 404:
                raise PermanentError(f"{url}: HTTP {resp.status_code}")
            return resp

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(2.0**attempt, 60.0)

    @staticmethod
    def _retry_after(resp: httpx.Response) -> float | None:
        value = resp.headers.get("retry-after")
        if value and value.isdigit():
            return min(float(value), 120.0)
        return None
