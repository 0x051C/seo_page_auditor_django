from datetime import date

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from audit import rules
from audit.models import Issue, PageCheck, PageMetric, Site


class SiteModelTests(TestCase):
    def test_str_is_url(self):
        site = Site.objects.create(url="https://www.example.com/")
        self.assertEqual(str(site), "https://www.example.com/")

    def test_url_is_unique(self):
        Site.objects.create(url="https://www.example.com/")
        with self.assertRaises(IntegrityError):
            Site.objects.create(url="https://www.example.com/")

    def test_deleting_site_deletes_its_data(self):
        site = Site.objects.create(url="https://www.example.com/")
        PageCheck.objects.create(site=site, page_url="https://www.example.com/a/", status_code=200)
        site.delete()
        self.assertEqual(PageCheck.objects.count(), 0)


class PageMetricModelTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(url="https://www.example.com/")
        self.fields = {
            "site": self.site,
            "page_url": "https://www.example.com/blog/post/",
            "date_start": date(2026, 10, 1),
            "date_end": date(2026, 10, 28),
        }

    def test_same_page_and_range_cannot_be_stored_twice(self):
        PageMetric.objects.create(**self.fields, clicks=10, impressions=100)
        with self.assertRaises(IntegrityError):
            PageMetric.objects.create(**self.fields, clicks=11, impressions=101)

    def test_same_page_with_a_different_range_is_allowed(self):
        PageMetric.objects.create(**self.fields)
        PageMetric.objects.create(**{**self.fields, "date_end": date(2026, 10, 29)})
        self.assertEqual(PageMetric.objects.count(), 2)


class IssueModelTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(url="https://www.example.com/")

    def test_one_issue_per_page_and_rule(self):
        fields = {"site": self.site, "page_url": "https://www.example.com/a/", "rule": rules.NO_H1}
        Issue.objects.create(**fields, severity=rules.LOW)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Issue.objects.create(**fields, severity=rules.HIGH)

    def test_default_ordering_puts_open_high_priority_first(self):
        url = "https://www.example.com/a/"
        Issue.objects.create(site=self.site, page_url=url, rule=rules.NO_H1, severity=rules.LOW, priority=2)
        Issue.objects.create(site=self.site, page_url=url, rule=rules.BROKEN_PAGE, severity=rules.HIGH, priority=9)
        Issue.objects.create(
            site=self.site, page_url=url, rule=rules.THIN_CONTENT, severity=rules.HIGH, priority=20, resolved=True
        )
        self.assertEqual(
            [issue.rule for issue in Issue.objects.all()],
            [rules.BROKEN_PAGE, rules.NO_H1, rules.THIN_CONTENT],
        )

    def test_str_uses_rule_label(self):
        issue = Issue(site=self.site, page_url="https://www.example.com/a/", rule=rules.MISSING_TITLE)
        self.assertEqual(str(issue), "Missing title on https://www.example.com/a/")


class AdminTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_superuser("admin", "admin@example.com", "password")
        self.client.force_login(user)

    def test_can_create_site_in_admin(self):
        response = self.client.post("/admin/audit/site/add/", {"url": "https://www.example.com/"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Site.objects.filter(url="https://www.example.com/").exists())

    def test_changelists_load(self):
        for model in ["site", "pagemetric", "pagecheck", "issue"]:
            with self.subTest(model=model):
                response = self.client.get(f"/admin/audit/{model}/")
                self.assertEqual(response.status_code, 200)
