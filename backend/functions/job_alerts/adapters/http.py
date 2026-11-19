"""Shared HTTP and HTML helpers for adapters."""
import time
from collections.abc import Callable
from html.parser import HTMLParser
from typing import Any

import httpx
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .base import AdapterError, RateLimitedError

TIMEOUT_SECONDS = 20
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1.0
TOO_MANY_REQUESTS = 429
# 429 is deliberately not retried: retrying a rate limit only adds load and keeps us blocked.
RETRY_STATUSES = (500, 502, 503, 504)
USER_AGENT = "job-alerts/0.1"
BLOCK_TAGS = frozenset({"p", "br", "li", "div", "ul", "ol", "h1", "h2", "h3", "h4", "tr"})


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def html_to_text(html: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(html)
    lines = (" ".join(line.split()) for line in "".join(extractor.parts).splitlines())
    return "\n".join(line for line in lines if line)


def build_session() -> requests.Session:
    # POST is included because job board POSTs are read-only searches.
    retry = Retry(
        total=MAX_RETRIES,
        backoff_factor=RETRY_BACKOFF_SECONDS,
        status_forcelist=RETRY_STATUSES,
        allowed_methods=frozenset({"GET", "POST"}),
        raise_on_status=False,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"Accept": "application/json", "User-Agent": USER_AGENT})
    return session


def fetch(session: requests.Session, method: str, url: str, **kwargs: Any) -> requests.Response:
    try:
        response = session.request(method, url, timeout=TIMEOUT_SECONDS, **kwargs)
        response.raise_for_status()
    except requests.RequestException as error:
        status = error.response.status_code if error.response is not None else None
        if status == TOO_MANY_REQUESTS:
            raise RateLimitedError(f"{method} {url} was rate limited (429)") from error
        raise AdapterError(f"{method} {url} failed: {error}") from error
    return response


def _json_value(response: requests.Response | httpx.Response, method: str, url: str) -> Any:
    try:
        return response.json()
    except ValueError as error:
        content_type = response.headers.get("Content-Type", "unknown type")
        raise AdapterError(f"{method} {url} did not return JSON (HTTP {response.status_code}, {content_type})") from error


def _json_object(payload: Any, method: str, url: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AdapterError(f"{method} {url} returned non-object JSON")
    return payload


def fetch_json_value(session: requests.Session, method: str, url: str, **kwargs: Any) -> Any:
    """Any JSON value (object or list); callers check the shape."""
    return _json_value(fetch(session, method, url, **kwargs), method, url)


def fetch_json(session: requests.Session, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    return _json_object(fetch_json_value(session, method, url, **kwargs), method, url)


def build_http2_client() -> httpx.Client:
    """For Workday. From GitHub's servers it answers Python over HTTP/1.1 with 429 on the first request,
    but HTTP/2 with 200 (same headers, same server; tested 2026-11-19). The User-Agent stays our own."""
    return httpx.Client(
        http2=True,
        timeout=TIMEOUT_SECONDS,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )


def _send_http2(
    client: httpx.Client, method: str, url: str, sleep: Callable[[float], None], **kwargs: Any
) -> httpx.Response:
    """Retries 5xx like build_session does; 429 is never retried."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = client.request(method, url, **kwargs)
        except httpx.HTTPError as error:
            raise AdapterError(f"{method} {url} failed: {error}") from error
        is_retryable = response.status_code in RETRY_STATUSES and attempt < MAX_RETRIES
        if not is_retryable:
            return response
        sleep(RETRY_BACKOFF_SECONDS * 2**attempt)
    return response


def fetch_json_http2(
    client: httpx.Client, method: str, url: str, sleep: Callable[[float], None] = time.sleep, **kwargs: Any
) -> dict[str, Any]:
    response = _send_http2(client, method, url, sleep, **kwargs)
    if response.status_code == TOO_MANY_REQUESTS:
        raise RateLimitedError(f"{method} {url} was rate limited (429)")
    if response.is_error:
        raise AdapterError(f"{method} {url} failed: HTTP {response.status_code}")
    return _json_object(_json_value(response, method, url), method, url)
