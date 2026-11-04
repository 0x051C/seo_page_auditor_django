from urllib.parse import urlsplit

from django.db import models
from django.utils import timezone

from . import rules


class Site(models.Model):
    """A Search Console property, e.g. https://www.example.com/."""

    url = models.URLField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["url"]

    def __str__(self):
        return self.url


class PageMetric(models.Model):
    """Search Console performance for one page over one date range."""

    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="metrics")
    page_url = models.URLField(max_length=2048)
    date_start = models.DateField()
    date_end = models.DateField()
    clicks = models.PositiveIntegerField(default=0)
    impressions = models.PositiveIntegerField(default=0)
    # Stored as a fraction, the way the API returns it: 0.025 means 2.5%.
    ctr = models.FloatField(default=0)
    position = models.FloatField(default=0)

    class Meta:
        ordering = ["-impressions"]
        constraints = [
            # One row per page per date range. The importer relies on this
            # with update_or_create, which is what makes re-imports idempotent.
            models.UniqueConstraint(
                fields=["site", "page_url", "date_start", "date_end"],
                name="unique_page_metric_per_range",
            ),
        ]

    def __str__(self):
        return f"{self.page_url} ({self.date_start} to {self.date_end})"


class PageCheck(models.Model):
    """The latest on-page snapshot for a page. One row per page, overwritten on re-check."""

    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="page_checks")
    page_url = models.URLField(max_length=2048)
    fetched_at = models.DateTimeField(default=timezone.now)
    # Null when the request failed before any response arrived (timeout, DNS error).
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    title = models.TextField(blank=True)
    meta_description = models.TextField(blank=True)
    h1_count = models.PositiveIntegerField(default=0)
    word_count = models.PositiveIntegerField(default=0)
    has_canonical = models.BooleanField(default=False)

    class Meta:
        ordering = ["page_url"]
        constraints = [
            models.UniqueConstraint(fields=["site", "page_url"], name="unique_page_check_per_page"),
        ]

    def __str__(self):
        return f"{self.page_url} [{self.status_code}]"


class Issue(models.Model):
    """A problem found by a rule on one page. Kept after it is fixed, with resolved=True."""

    RULE_CHOICES = list(rules.RULE_LABELS.items())
    SEVERITY_CHOICES = list(rules.SEVERITY_LABELS.items())

    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="issues")
    page_url = models.URLField(max_length=2048)
    rule = models.CharField(max_length=32, choices=RULE_CHOICES)
    severity = models.CharField(max_length=8, choices=SEVERITY_CHOICES)
    # Higher means fix it sooner. See rules.priority_score().
    priority = models.FloatField(default=0)
    detail = models.TextField(blank=True)
    detected_at = models.DateTimeField(auto_now_add=True)
    resolved = models.BooleanField(default=False)

    class Meta:
        ordering = ["resolved", "-priority"]
        constraints = [
            # A page has at most one issue per rule; run_audit updates it in place.
            models.UniqueConstraint(fields=["site", "page_url", "rule"], name="unique_issue_per_page_rule"),
        ]

    def __str__(self):
        return f"{self.get_rule_display()} on {self.page_url}"

    @property
    def path(self):
        """The URL without scheme and host, for compact display: '/blog/post/'."""
        return urlsplit(self.page_url).path or "/"
