"""
Search Console data sources.

Both backends implement the same interface, SearchConsoleBackend, so the
importer does not care where rows come from:

- MockBackend reads a JSON file shaped like a real API response.
- GoogleBackend calls the Search Analytics API with service-account credentials.

Pick one with the GSC_BACKEND setting ("mock" or "google").
"""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import urljoin

from django.conf import settings
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Search Console data for the last 2-3 days is incomplete, so the import
# window ends this many days before today.
DATA_LAG_DAYS = 3


class SearchConsoleError(Exception):
    """Raised when a backend cannot return data (bad config, API error)."""


@dataclass(frozen=True)
class GscRow:
    """One page's performance for the requested date range."""

    page_url: str
    clicks: int
    impressions: int
    ctr: float
    position: float


def date_window(days, today=None):
    """Return (start, end) dates covering `days` days, ending DATA_LAG_DAYS before today."""
    if days < 1:
        raise ValueError("days must be at least 1")
    today = today or date.today()
    end = today - timedelta(days=DATA_LAG_DAYS)
    start = end - timedelta(days=days - 1)
    return start, end


def rows_from_response(response, site_url=None):
    """
    Convert a searchanalytics.query response dict into GscRow objects.

    If site_url is given, keys are treated as paths and joined onto it
    (used by the mock data). The API returns clicks and impressions as
    floats like 12.0, so they are cast to int.
    """
    rows = []
    for raw in response.get("rows", []):
        page_url = raw["keys"][0]
        if site_url:
            page_url = urljoin(site_url, page_url)
        rows.append(
            GscRow(
                page_url=page_url,
                clicks=int(raw["clicks"]),
                impressions=int(raw["impressions"]),
                ctr=float(raw["ctr"]),
                position=float(raw["position"]),
            )
        )
    return rows


class SearchConsoleBackend(ABC):
    """The interface every backend implements."""

    @abstractmethod
    def fetch_page_metrics(self, site_url, start, end):
        """Return a list of GscRow, one per page, for the date range start..end (inclusive)."""


class MockBackend(SearchConsoleBackend):
    """Reads canned rows from a JSON file. The same rows are returned for any date range."""

    def __init__(self, path):
        self.path = path

    def fetch_page_metrics(self, site_url, start, end):
        try:
            with open(self.path, encoding="utf-8") as f:
                response = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            raise SearchConsoleError(f"Could not read mock data from {self.path}: {exc}") from exc
        return rows_from_response(response, site_url=site_url)


class GoogleBackend(SearchConsoleBackend):
    """Calls the Search Console API (searchanalytics.query, dimension = page)."""

    SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]

    def __init__(self, credentials_file="", service=None, row_limit=25000):
        self.credentials_file = credentials_file
        self.row_limit = row_limit  # 25,000 is the API maximum per request
        # Tests pass a fake service; real use builds one lazily from credentials.
        self._service = service

    def _get_service(self):
        if self._service is None:
            if not self.credentials_file:
                raise SearchConsoleError(
                    "GSC_BACKEND=google needs GOOGLE_APPLICATION_CREDENTIALS set to a service-account JSON file."
                )
            try:
                credentials = service_account.Credentials.from_service_account_file(
                    self.credentials_file, scopes=self.SCOPES
                )
            except (OSError, ValueError) as exc:
                raise SearchConsoleError(f"Could not load credentials: {exc}") from exc
            self._service = build("searchconsole", "v1", credentials=credentials, cache_discovery=False)
        return self._service

    def fetch_page_metrics(self, site_url, start, end):
        service = self._get_service()
        rows = []
        start_row = 0
        # The API pages results; keep asking until a page comes back short.
        while True:
            body = {
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
                "dimensions": ["page"],
                "rowLimit": self.row_limit,
                "startRow": start_row,
            }
            try:
                response = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
            except HttpError as exc:
                raise SearchConsoleError(f"Search Console API error: {exc}") from exc
            page = rows_from_response(response)
            rows.extend(page)
            if len(page) < self.row_limit:
                return rows
            start_row += self.row_limit


def get_backend(name=None):
    """Build the backend named by `name`, or by settings.GSC_BACKEND if not given."""
    name = (name or settings.GSC_BACKEND).strip().lower()
    if name == "mock":
        return MockBackend(settings.GSC_SAMPLE_FILE)
    if name == "google":
        return GoogleBackend(settings.GSC_CREDENTIALS_FILE)
    raise SearchConsoleError(f"Unknown GSC_BACKEND {name!r}; use 'mock' or 'google'.")
