"""Shared HTTP and HTML helpers for adapters."""
import json as jsonlib
import subprocess
import time
from collections.abc import Callable
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


def _json_value(response: requests.Response, method: str, url: str) -> Any:
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


def _run_curl(
    method: str, url: str, body: dict[str, Any] | None, run: Callable[..., subprocess.CompletedProcess]
) -> tuple[int, str]:
    """Returns (HTTP status, response body). curl prints the status on the last line (-w)."""
    args = ["curl", "-sS", "--max-time", str(TIMEOUT_SECONDS), "-X", method,
            "-H", "Accept: application/json", "-A", USER_AGENT, "-w", "\n%{http_code}"]
    if body is not None:
        args = [*args, "-H", "Content-Type: application/json", "--data-binary", "@-"]
    payload = None if body is None else jsonlib.dumps(body)
    try:
        result = run([*args, url], input=payload, capture_output=True, text=True, timeout=TIMEOUT_SECONDS + 10)
    except (OSError, subprocess.SubprocessError) as error:
        raise AdapterError(f"{method} {url} failed: could not run curl: {error}") from error
    if result.returncode != 0:
        raise AdapterError(f"{method} {url} failed: {result.stderr.strip() or f'curl exit {result.returncode}'}")
    text, _, status = result.stdout.rpartition("\n")
    return int(status), text


def fetch_json_curl(
    method: str, url: str, json: dict[str, Any] | None = None,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """For Workday. From GitHub's servers it answers Python HTTP clients (requests, httpx over HTTP/1.1
    or HTTP/2) with 429 on 77 of 90 requests, but curl with 200 on 60 of 60, with the same headers and
    User-Agent (tested 2026-11-19). Retries 5xx like build_session does; 429 is never retried."""
    for attempt in range(MAX_RETRIES + 1):
        status, text = _run_curl(method, url, json, run)
        if status not in RETRY_STATUSES or attempt == MAX_RETRIES:
            break
        sleep(RETRY_BACKOFF_SECONDS * 2**attempt)
    if status == TOO_MANY_REQUESTS:
        raise RateLimitedError(f"{method} {url} was rate limited (429)")
    if status >= 400:
        raise AdapterError(f"{method} {url} failed: HTTP {status}")
    try:
        payload = jsonlib.loads(text)
    except ValueError as error:
        raise AdapterError(f"{method} {url} did not return JSON (HTTP {status})") from error
    return _json_object(payload, method, url)
