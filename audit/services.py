"""
The work behind the management commands. Commands parse arguments and print;
these functions do the database writes, so tests can call them directly.
"""

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import transaction

from .models import PageMetric, Site


def normalize_site_url(url):
    """Validate a URL-prefix property and make sure it ends with '/' (Search Console's format)."""
    url = url.strip()
    try:
        URLValidator(schemes=["http", "https"])(url)
    except ValidationError as exc:
        raise ValueError(f"Not a valid http(s) URL: {url!r}") from exc
    if not url.endswith("/"):
        url += "/"
    return url


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0

    @property
    def total(self):
        return self.created + self.updated


def import_metrics(site, backend, start, end):
    """
    Fetch page metrics for start..end from `backend` and store them.

    update_or_create looks a row up by (site, page_url, date_start, date_end),
    the same fields as PageMetric's unique constraint. If it exists the numbers
    are updated, otherwise a row is created. Running this twice therefore
    leaves the same number of rows.
    """
    rows = backend.fetch_page_metrics(site.url, start, end)
    result = ImportResult()
    with transaction.atomic():
        for row in rows:
            _, created = PageMetric.objects.update_or_create(
                site=site,
                page_url=row.page_url,
                date_start=start,
                date_end=end,
                defaults={
                    "clicks": row.clicks,
                    "impressions": row.impressions,
                    "ctr": row.ctr,
                    "position": row.position,
                },
            )
            if created:
                result.created += 1
            else:
                result.updated += 1
    return result
