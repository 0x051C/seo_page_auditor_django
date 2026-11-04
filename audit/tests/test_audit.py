from datetime import date
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings

from audit import rules
from audit.models import Issue, PageCheck, PageMetric, Site
from audit.services import latest_metrics_by_page, run_audit

PAGE = "https://a.com/page/"


class RunAuditTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(url="https://a.com/")
        self.metric = PageMetric.objects.create(
            site=self.site,
            page_url=PAGE,
            date_start=date(2026, 10, 1),
            date_end=date(2026, 10, 28),
            clicks=5,
            impressions=1000,
            ctr=0.005,
            position=2.0,
        )
        self.check = PageCheck.objects.create(
            site=self.site, page_url=PAGE, status_code=200, title="Fine", meta_description="Fine", h1_count=0, word_count=900
        )

    def open_rules(self):
        return set(self.site.issues.filter(resolved=False).values_list("rule", flat=True))

    def test_creates_issues_with_priority_and_severity(self):
        result = run_audit(self.site)

        self.assertEqual(result.created, 2)
        self.assertEqual(self.open_rules(), {rules.LOW_CTR, rules.NO_H1})
        no_h1 = Issue.objects.get(rule=rules.NO_H1)
        self.assertEqual(no_h1.priority, rules.priority_score(rules.NO_H1, 1000))
        self.assertEqual(no_h1.severity, rules.MEDIUM)

    def test_running_twice_does_not_duplicate(self):
        run_audit(self.site)
        result = run_audit(self.site)
        self.assertEqual((result.created, result.updated, result.resolved), (0, 2, 0))
        self.assertEqual(Issue.objects.count(), 2)

    def test_fixed_problems_are_marked_resolved(self):
        run_audit(self.site)
        self.check.h1_count = 1
        self.check.save()

        result = run_audit(self.site)

        self.assertEqual(result.resolved, 1)
        self.assertTrue(Issue.objects.get(rule=rules.NO_H1).resolved)
        self.assertEqual(self.open_rules(), {rules.LOW_CTR})

    def test_problems_that_come_back_are_reopened(self):
        run_audit(self.site)
        self.check.h1_count = 1
        self.check.save()
        run_audit(self.site)
        self.check.h1_count = 0
        self.check.save()

        run_audit(self.site)

        issue = Issue.objects.get(rule=rules.NO_H1)
        self.assertFalse(issue.resolved)
        self.assertEqual(Issue.objects.filter(rule=rules.NO_H1).count(), 1)

    def test_priority_follows_the_latest_metrics(self):
        run_audit(self.site)
        PageMetric.objects.create(
            site=self.site,
            page_url=PAGE,
            date_start=date(2026, 10, 2),
            date_end=date(2026, 10, 29),
            clicks=50,
            impressions=100000,
            ctr=0.0005,
            position=2.0,
        )
        run_audit(self.site)
        issue = Issue.objects.get(rule=rules.NO_H1)
        self.assertEqual(issue.priority, rules.priority_score(rules.NO_H1, 100000))
        self.assertEqual(issue.severity, rules.HIGH)

    def test_latest_metrics_by_page_picks_newest_range(self):
        newer = PageMetric.objects.create(
            site=self.site, page_url=PAGE, date_start=date(2026, 10, 2), date_end=date(2026, 10, 29)
        )
        self.assertEqual(latest_metrics_by_page(self.site), {PAGE: newer})

    def test_other_sites_are_untouched(self):
        other = Site.objects.create(url="https://b.com/")
        Issue.objects.create(site=other, page_url="https://b.com/x/", rule=rules.NO_H1, severity=rules.LOW)
        run_audit(self.site)
        self.assertFalse(Issue.objects.get(site=other).resolved)


@override_settings(GSC_BACKEND="mock", PAGE_FETCHER="mock")
class MockPipelineTests(TestCase):
    """End to end on the sample data: import, check, audit."""

    def setUp(self):
        site_url = "https://shop.example.com/"
        call_command("import_gsc", "--site", site_url, stdout=StringIO())
        call_command("check_pages", "--site", site_url, stdout=StringIO())
        self.out = StringIO()
        call_command("run_audit", "--site", site_url, stdout=self.out)

    def test_sample_data_produces_every_rule(self):
        found = set(Issue.objects.values_list("rule", flat=True))
        self.assertEqual(found, set(rules.RULE_LABELS))

    def test_sample_data_produces_every_severity(self):
        found = set(Issue.objects.values_list("severity", flat=True))
        self.assertEqual(found, {rules.LOW, rules.MEDIUM, rules.HIGH})

    def test_command_prints_summary(self):
        self.assertIn("open issues", self.out.getvalue())
        self.assertIn("By severity:", self.out.getvalue())
