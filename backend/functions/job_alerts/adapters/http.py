"""Shared HTTP and HTML helpers for adapters."""
from html.parser import HTMLParser
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .base import AdapterError, RateLimitedError

TIMEOUT_SECONDS = 20
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1.0
TOO_MANY_REQUESTS = 429
RETRY_STATUSES = (TOO_MANY_REQUESTS, 500, 502, 503, 504)
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


def fetch_json_value(session: requests.Session, method: str, url: str, **kwargs: Any) -> Any:
    """Any JSON value (object or list); callers check the shape."""
    response = fetch(session, method, url, **kwargs)
    try:
        return response.json()
    except ValueError as error:
        raise AdapterError(f"{method} {url} did not return JSON") from error


def fetch_json(session: requests.Session, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    payload = fetch_json_value(session, method, url, **kwargs)
    if not isinstance(payload, dict):
        raise AdapterError(f"{method} {url} returned non-object JSON")
    return payload
