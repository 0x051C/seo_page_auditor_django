"""
The work behind the management commands. Commands parse arguments and print;
these functions do the database writes, so tests can call them directly.
"""

from dataclasses import asdict, dataclass

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from . import rules
from .models import Issue, PageCheck, PageMetric
from .pagecheck import ParsedPage, parse_html


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


def pages_by_impressions(site):
    """
    Distinct page URLs that have metrics, highest impressions first.

    values("page_url").annotate(...) is a GROUP BY page_url in SQL, so each
    page appears once even if it has metrics for several date ranges.
    """
    return list(
        site.metrics.values("page_url")
        .annotate(top_impressions=Max("impressions"))
        .order_by("-top_impressions", "page_url")
        .values_list("page_url", flat=True)
    )


@dataclass
class CheckResult:
    checked: int = 0
    broken: int = 0


def check_pages(site, fetcher, limit=None, on_checked=None):
    """
    Fetch every imported page of `site`, parse it, and save a PageCheck.

    One PageCheck per page: update_or_create overwrites the previous snapshot.
    on_checked(page_check) is called after each page, for progress output.
    """
    urls = pages_by_impressions(site)
    if limit is not None:
        urls = urls[:limit]

    result = CheckResult()
    for url in urls:
        fetched = fetcher.fetch(url)
        parsed = parse_html(fetched.html) if fetched.html else ParsedPage()
        page_check, _ = PageCheck.objects.update_or_create(
            site=site,
            page_url=url,
            defaults={"fetched_at": timezone.now(), "status_code": fetched.status_code, **asdict(parsed)},
        )
        result.checked += 1
        if fetched.status_code is None or fetched.status_code >= 400:
            result.broken += 1
        if on_checked:
            on_checked(page_check)
    return result


def latest_metrics_by_page(site):
    """Map page_url -> its most recent PageMetric (by date_end)."""
    latest = {}
    for metric in site.metrics.order_by("date_end"):
        latest[metric.page_url] = metric  # later rows overwrite earlier ones
    return latest


@dataclass
class AuditResult:
    created: int = 0
    updated: int = 0
    resolved: int = 0

    @property
    def open(self):
        return self.created + self.updated


def run_audit(site):
    """
    Apply every rule to every page of `site` and sync the Issue table.

    - A finding with no matching Issue creates one.
    - A finding that matches an Issue (same page and rule) updates its
      severity, priority and detail, and reopens it if it was resolved.
    - An open Issue that no rule reported this time is marked resolved.
    """
    metrics = latest_metrics_by_page(site)
    checks = {check.page_url: check for check in site.page_checks.all()}

    result = AuditResult()
    still_open = []
    with transaction.atomic():
        for page_url in sorted(metrics.keys() | checks.keys()):
            metric = metrics.get(page_url)
            impressions = metric.impressions if metric else 0
            for finding in rules.evaluate(metric, checks.get(page_url)):
                score = rules.priority_score(finding.rule, impressions)
                issue, created = Issue.objects.update_or_create(
                    site=site,
                    page_url=page_url,
                    rule=finding.rule,
                    defaults={
                        "severity": rules.severity_for(score),
                        "priority": score,
                        "detail": finding.detail,
                        "resolved": False,
                    },
                )
                still_open.append(issue.pk)
                if created:
                    result.created += 1
                else:
                    result.updated += 1

        result.resolved = site.issues.filter(resolved=False).exclude(pk__in=still_open).update(resolved=True)
    return result
