from collections import Counter

from django.db.models import Max, OuterRef, Subquery
from django.shortcuts import get_object_or_404, render
from rest_framework import generics
from rest_framework.exceptions import ValidationError

from . import rules
from .models import PageMetric, Site
from .serializers import IssueSerializer


def latest_impressions():
    """
    A subquery that, for each Issue row, looks up impressions from the newest
    PageMetric of the same site and page. OuterRef points at the Issue.
    """
    newest = PageMetric.objects.filter(site=OuterRef("site"), page_url=OuterRef("page_url")).order_by("-date_end")
    return Subquery(newest.values("impressions")[:1])


def site_list(request):
    return render(request, "audit/site_list.html", {"sites": Site.objects.all()})


def site_report(request, site_id):
    site = get_object_or_404(Site, pk=site_id)
    issues = list(
        site.issues.filter(resolved=False)
        .annotate(impressions=latest_impressions())
        .order_by("-priority", "page_url", "rule")
    )
    counts = Counter(issue.severity for issue in issues)
    context = {
        "site": site,
        "issues": issues,
        "severity_counts": [(rules.SEVERITY_LABELS[level], level, counts[level]) for level in (rules.HIGH, rules.MEDIUM, rules.LOW)],
        "pages_checked": site.page_checks.count(),
        "last_checked": site.page_checks.aggregate(latest=Max("fetched_at"))["latest"],
        "resolved_count": site.issues.filter(resolved=True).count(),
    }
    return render(request, "audit/report.html", context)


class SiteIssueList(generics.ListAPIView):
    """
    GET /api/sites/<id>/issues/ — open issues for a site, highest priority first.

    Optional filters: ?severity=high|medium|low and ?rule=<RULE_CODE>.
    """

    serializer_class = IssueSerializer

    def get_queryset(self):
        site = get_object_or_404(Site, pk=self.kwargs["site_id"])
        issues = site.issues.filter(resolved=False).order_by("-priority", "page_url", "rule")

        severity = self.request.query_params.get("severity")
        if severity:
            severity = severity.lower()
            if severity not in rules.SEVERITY_LABELS:
                raise ValidationError({"severity": [f"Must be one of: {', '.join(rules.SEVERITY_LABELS)}."]})
            issues = issues.filter(severity=severity)

        rule = self.request.query_params.get("rule")
        if rule:
            rule = rule.upper()
            if rule not in rules.RULE_LABELS:
                raise ValidationError({"rule": [f"Must be one of: {', '.join(rules.RULE_LABELS)}."]})
            issues = issues.filter(rule=rule)

        return issues
