"""
On-page checks.

parse_html() is a pure function: HTML in, fields out, no network. That is
what the tests exercise. Fetching is separate:

- HttpFetcher makes real requests (timeout, User-Agent, at most 1 per second).
- MockFetcher builds pages from sample_data/pages_sample.json for offline demos.
"""

import html as html_lib
import json
import re
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup
from django.conf import settings

# Tags whose text a visitor never reads as page content.
NON_CONTENT_TAGS = ["head", "script", "style", "noscript", "template", "svg"]


@dataclass(frozen=True)
class ParsedPage:
    title: str = ""
    meta_description: str = ""
    h1_count: int = 0
    word_count: int = 0
    has_canonical: bool = False


def parse_html(html):
    """Extract the on-page SEO basics from an HTML string."""
    soup = BeautifulSoup(html or "", "html.parser")

    # <svg> icons can contain their own <title>; only a document title counts.
    title_tag = next((tag for tag in soup.find_all("title") if tag.find_parent("svg") is None), None)
    title = " ".join(title_tag.get_text().split()) if title_tag else ""

    meta = soup.find("meta", attrs={"name": re.compile(r"^description$", re.IGNORECASE)})
    meta_description = " ".join((meta.get("content") or "").split()) if meta else ""

    h1_count = len(soup.find_all("h1"))
    has_canonical = soup.find("link", rel="canonical", href=True) is not None

    # Count words last, because it removes tags from the soup.
    for tag in soup(NON_CONTENT_TAGS):
        tag.decompose()
    tokens = soup.get_text(" ").split()
    # A "word" is any whitespace-separated token with a letter or digit in it,
    # so stray punctuation like "|" or "-" is not counted.
    word_count = sum(1 for token in tokens if any(char.isalnum() for char in token))

    return ParsedPage(
        title=title,
        meta_description=meta_description,
        h1_count=h1_count,
        word_count=word_count,
        has_canonical=has_canonical,
    )


@dataclass(frozen=True)
class FetchResult:
    # None means no response at all (timeout, DNS failure, refused connection).
    status_code: int | None
    html: str = ""


class HttpFetcher:
    """Fetches pages over HTTP, politely: fixed User-Agent, timeout, and a delay between requests."""

    def __init__(self, user_agent, timeout=10, delay=1.0, session=None, sleep=time.sleep, clock=time.monotonic):
        self.user_agent = user_agent
        self.timeout = timeout
        self.delay = delay
        self.session = session or requests.Session()
        # sleep and clock are injectable so tests can check rate limiting without waiting.
        self.sleep = sleep
        self.clock = clock
        self._last_request_at = None

    def _wait_for_turn(self):
        if self._last_request_at is not None:
            elapsed = self.clock() - self._last_request_at
            if elapsed < self.delay:
                self.sleep(self.delay - elapsed)
        self._last_request_at = self.clock()

    def fetch(self, url):
        self._wait_for_turn()
        try:
            response = self.session.get(url, headers={"User-Agent": self.user_agent}, timeout=self.timeout)
        except requests.RequestException:
            return FetchResult(status_code=None)
        # Only parse HTML; a PDF or image body would produce nonsense fields.
        is_html = "html" in response.headers.get("Content-Type", "").lower()
        return FetchResult(status_code=response.status_code, html=response.text if is_html else "")


class MockFetcher:
    """Serves fake pages described in a JSON file, keyed by URL path. Unknown paths return 404."""

    def __init__(self, path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.pages = data["pages"]
        self.filler_words = data["filler_text"].split()

    def fetch(self, url):
        spec = self.pages.get(urlsplit(url).path or "/")
        if spec is None:
            return FetchResult(status_code=404, html="<html><head><title>Not found</title></head><body>Not found</body></html>")
        return FetchResult(status_code=spec.get("status", 200), html=self.render(url, spec))

    def render(self, url, spec):
        esc = html_lib.escape
        head = ['<meta charset="utf-8">']
        if spec.get("title"):
            head.append(f"<title>{esc(spec['title'])}</title>")
        if spec.get("meta_description"):
            head.append(f'<meta name="description" content="{esc(spec["meta_description"])}">')
        if spec.get("canonical", True):
            head.append(f'<link rel="canonical" href="{esc(url)}">')

        words = [self.filler_words[i % len(self.filler_words)] for i in range(spec.get("words", 0))]
        paragraphs = [" ".join(words[i : i + 60]) for i in range(0, len(words), 60)]
        body = [f"<h1>{esc(h1)}</h1>" for h1 in spec.get("h1", [])]
        body += [f"<p>{esc(p)}</p>" for p in paragraphs]

        return (
            "<!doctype html>\n<html lang=\"en\">\n<head>\n"
            + "\n".join(head)
            + "\n</head>\n<body>\n<main>\n"
            + "\n".join(body)
            + "\n</main>\n<script>window.dataLayer = [];</script>\n</body>\n</html>\n"
        )


def get_fetcher(name=None):
    """Build the fetcher named by `name`, or by settings.PAGE_FETCHER if not given."""
    name = (name or settings.PAGE_FETCHER).strip().lower()
    if name == "mock":
        return MockFetcher(settings.PAGE_SAMPLE_FILE)
    if name == "http":
        return HttpFetcher(
            user_agent=settings.PAGE_FETCH_USER_AGENT,
            timeout=settings.PAGE_FETCH_TIMEOUT,
            delay=settings.PAGE_FETCH_DELAY,
        )
    raise ValueError(f"Unknown PAGE_FETCHER {name!r}; use 'mock' or 'http'.")
