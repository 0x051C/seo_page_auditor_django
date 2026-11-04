from datetime import date

from django.test import TestCase
from django.urls import reverse

from audit import rules
from audit.models import Issue, PageCheck, PageMetric, Site


class ViewTestData(TestCase):
    """Two sites; the first has three open issues and one resolved one."""

    def setUp(self):
        self.site = Site.objects.create(url="https://a.com/")
        self.other_site = Site.objects.create(url="https://b.com/")
        PageMetric.objects.create(
            site=self.site, page_url="https://a.com/top/", date_start=date(2026, 10, 1), date_end=date(2026, 10, 28), impressions=12345
        )
        PageCheck.objects.create(site=self.site, page_url="https://a.com/top/", status_code=200)

        def issue(site, path, rule, severity, priority, resolved=False):
            return Issue.objects.create(
                site=site,
                page_url=f"{site.url}{path}",
                rule=rule,
                severity=severity,
                priority=priority,
                detail=f"{rule} detail",
                resolved=resolved,
            )

        self.high = issue(self.site, "top/", rules.BROKEN_PAGE, rules.HIGH, 9.5)
        self.medium = issue(self.site, "mid/", rules.NO_H1, rules.MEDIUM, 5.5)
        self.low = issue(self.site, "low/", rules.TITLE_TOO_LONG, rules.LOW, 2.0)
        self.resolved = issue(self.site, "fixed/", rules.THIN_CONTENT, rules.HIGH, 9.9, resolved=True)
        self.foreign = issue(self.other_site, "x/", rules.NO_H1, rules.HIGH, 9.0)


class ReportViewTests(ViewTestData):
    def get_report(self, site):
        return self.client.get(reverse("audit:site-report", args=[site.pk]))

    def test_lists_open_issues_by_priority(self):
        response = self.get_report(self.site)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "audit/report.html")
        self.assertEqual(response.context["issues"], [self.high, self.medium, self.low])

    def test_hides_resolved_issues_and_other_sites(self):
        content = self.get_report(self.site).content.decode()
        self.assertNotIn("/fixed/", content)
        self.assertNotIn("b.com", content)

    def test_shows_impressions_from_metrics(self):
        response = self.get_report(self.site)
        self.assertEqual(response.context["issues"][0].impressions, 12345)
        self.assertContains(response, "12,345")

    def test_shows_severity_counts_and_resolved_count(self):
        response = self.get_report(self.site)
        self.assertEqual(response.context["severity_counts"], [("High", "high", 1), ("Medium", "medium", 1), ("Low", "low", 1)])
        self.assertEqual(response.context["resolved_count"], 1)
        self.assertEqual(response.context["pages_checked"], 1)

    def test_site_without_issues_shows_hint(self):
        empty = Site.objects.create(url="https://empty.com/")
        self.assertContains(self.get_report(empty), "No open issues")

    def test_unknown_site_is_404(self):
        self.assertEqual(self.client.get(reverse("audit:site-report", args=[999])).status_code, 404)


class SiteListViewTests(ViewTestData):
    def test_links_to_each_report(self):
        response = self.client.get(reverse("audit:site-list"))
        self.assertContains(response, reverse("audit:site-report", args=[self.site.pk]))
        self.assertContains(response, reverse("audit:site-report", args=[self.other_site.pk]))


class IssueApiTests(ViewTestData):
    def get_issues(self, site_id=None, **params):
        return self.client.get(reverse("audit:api-site-issues", args=[site_id or self.site.pk]), params)

    def test_returns_open_issues_by_priority_as_json(self):
        response = self.get_issues()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        data = response.json()
        self.assertEqual([item["id"] for item in data], [self.high.pk, self.medium.pk, self.low.pk])
        self.assertEqual(
            data[0],
            {
                "id": self.high.pk,
                "page_url": "https://a.com/top/",
                "rule": "BROKEN_PAGE",
                "rule_label": "Broken page",
                "severity": "high",
                "priority": 9.5,
                "detail": "BROKEN_PAGE detail",
                "detected_at": data[0]["detected_at"],
                "resolved": False,
            },
        )

    def test_filter_by_severity(self):
        data = self.get_issues(severity="medium").json()
        self.assertEqual([item["id"] for item in data], [self.medium.pk])

    def test_filter_by_rule(self):
        data = self.get_issues(rule="TITLE_TOO_LONG").json()
        self.assertEqual([item["id"] for item in data], [self.low.pk])

    def test_filters_are_case_insensitive_and_combine(self):
        self.assertEqual(len(self.get_issues(severity="HIGH", rule="broken_page").json()), 1)
        self.assertEqual(self.get_issues(severity="low", rule="BROKEN_PAGE").json(), [])

    def test_invalid_filter_values_are_400(self):
        response = self.get_issues(severity="urgent")
        self.assertEqual(response.status_code, 400)
        self.assertIn("severity", response.json())
        self.assertEqual(self.get_issues(rule="NOT_A_RULE").status_code, 400)

    def test_only_this_sites_issues(self):
        data = self.get_issues(site_id=self.other_site.pk).json()
        self.assertEqual([item["id"] for item in data], [self.foreign.pk])

    def test_unknown_site_is_404(self):
        self.assertEqual(self.get_issues(site_id=999).status_code, 404)

    def test_is_read_only(self):
        url = reverse("audit:api-site-issues", args=[self.site.pk])
        self.assertEqual(self.client.post(url, {}).status_code, 405)
