import json
import tempfile
from datetime import date
from io import StringIO
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from audit.gsc import (
    GoogleBackend,
    GscRow,
    MockBackend,
    SearchConsoleError,
    date_window,
    get_backend,
    rows_from_response,
)
from audit.models import PageMetric, Site
from audit.services import import_metrics, normalize_site_url

SITE_URL = "https://shop.example.com/"


class DateWindowTests(SimpleTestCase):
    def test_window_ends_three_days_ago_and_covers_n_days(self):
        start, end = date_window(28, today=date(2026, 11, 4))
        self.assertEqual(end, date(2026, 11, 1))
        self.assertEqual(start, date(2026, 10, 5))
        self.assertEqual((end - start).days + 1, 28)

    def test_one_day_window_starts_and_ends_on_same_day(self):
        start, end = date_window(1, today=date(2026, 11, 4))
        self.assertEqual(start, end)

    def test_zero_days_is_rejected(self):
        with self.assertRaises(ValueError):
            date_window(0)


class RowsFromResponseTests(SimpleTestCase):
    def test_casts_api_floats_to_ints(self):
        response = {"rows": [{"keys": ["https://a.com/x/"], "clicks": 12.0, "impressions": 340.0, "ctr": 0.035, "position": 4.2}]}
        self.assertEqual(
            rows_from_response(response),
            [GscRow("https://a.com/x/", clicks=12, impressions=340, ctr=0.035, position=4.2)],
        )

    def test_joins_paths_onto_site_url(self):
        response = {"rows": [{"keys": ["/blog/post/"], "clicks": 1, "impressions": 2, "ctr": 0.5, "position": 1}]}
        rows = rows_from_response(response, site_url=SITE_URL)
        self.assertEqual(rows[0].page_url, "https://shop.example.com/blog/post/")

    def test_response_without_rows_gives_empty_list(self):
        # The API omits "rows" entirely when there is no data.
        self.assertEqual(rows_from_response({"responseAggregationType": "byPage"}), [])


class MockBackendTests(SimpleTestCase):
    def test_sample_file_has_about_40_valid_rows(self):
        rows = MockBackend(settings.GSC_SAMPLE_FILE).fetch_page_metrics(SITE_URL, date(2026, 10, 1), date(2026, 10, 28))
        self.assertGreaterEqual(len(rows), 35)
        self.assertEqual(len({row.page_url for row in rows}), len(rows), "page URLs should be unique")
        for row in rows:
            self.assertTrue(row.page_url.startswith(SITE_URL))
            self.assertLessEqual(row.clicks, row.impressions)
            self.assertAlmostEqual(row.ctr, row.clicks / row.impressions, places=4)
            self.assertGreaterEqual(row.position, 1)

    def test_rows_follow_the_site_url(self):
        rows = MockBackend(settings.GSC_SAMPLE_FILE).fetch_page_metrics("https://other.example.org/", None, None)
        self.assertTrue(all(row.page_url.startswith("https://other.example.org/") for row in rows))

    def test_missing_file_raises_search_console_error(self):
        with self.assertRaises(SearchConsoleError):
            MockBackend("/nonexistent/gsc.json").fetch_page_metrics(SITE_URL, None, None)


class GoogleBackendTests(SimpleTestCase):
    def make_service(self, *responses):
        service = mock.MagicMock()
        service.searchanalytics.return_value.query.return_value.execute.side_effect = list(responses)
        return service

    @staticmethod
    def api_rows(count):
        return [
            {"keys": [f"https://a.com/{i}/"], "clicks": 1.0, "impressions": 10.0, "ctr": 0.1, "position": 3.0}
            for i in range(count)
        ]

    def test_queries_page_dimension_for_the_date_range(self):
        service = self.make_service({"rows": self.api_rows(2)})
        backend = GoogleBackend(service=service)

        rows = backend.fetch_page_metrics("https://a.com/", date(2026, 10, 1), date(2026, 10, 28))

        self.assertEqual(len(rows), 2)
        query = service.searchanalytics.return_value.query
        query.assert_called_once_with(
            siteUrl="https://a.com/",
            body={
                "startDate": "2026-10-01",
                "endDate": "2026-10-28",
                "dimensions": ["page"],
                "rowLimit": 25000,
                "startRow": 0,
            },
        )

    def test_pages_through_results_until_a_short_page(self):
        service = self.make_service({"rows": self.api_rows(2)}, {"rows": self.api_rows(1)})
        backend = GoogleBackend(service=service, row_limit=2)

        rows = backend.fetch_page_metrics("https://a.com/", date(2026, 10, 1), date(2026, 10, 28))

        self.assertEqual(len(rows), 3)
        calls = service.searchanalytics.return_value.query.call_args_list
        self.assertEqual([c.kwargs["body"]["startRow"] for c in calls], [0, 2])

    def test_missing_credentials_raise_clear_error(self):
        with self.assertRaisesMessage(SearchConsoleError, "GOOGLE_APPLICATION_CREDENTIALS"):
            GoogleBackend(credentials_file="").fetch_page_metrics("https://a.com/", date(2026, 10, 1), date(2026, 10, 2))


class GetBackendTests(SimpleTestCase):
    def test_mock(self):
        self.assertIsInstance(get_backend("mock"), MockBackend)

    @override_settings(GSC_BACKEND="google")
    def test_reads_setting_when_no_name_given(self):
        self.assertIsInstance(get_backend(), GoogleBackend)

    def test_unknown_name(self):
        with self.assertRaises(SearchConsoleError):
            get_backend("bing")


class NormalizeSiteUrlTests(SimpleTestCase):
    def test_adds_trailing_slash(self):
        self.assertEqual(normalize_site_url(" https://shop.example.com "), SITE_URL)

    def test_rejects_non_urls(self):
        with self.assertRaises(ValueError):
            normalize_site_url("shop.example.com")


class ImportMetricsTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(url=SITE_URL)
        self.start, self.end = date(2026, 10, 1), date(2026, 10, 28)

    def write_sample(self, rows):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump({"rows": rows}, tmp)
        tmp.close()
        self.addCleanup(Path(tmp.name).unlink)
        return MockBackend(tmp.name)

    def test_importing_twice_keeps_the_same_row_count(self):
        backend = MockBackend(settings.GSC_SAMPLE_FILE)

        first = import_metrics(self.site, backend, self.start, self.end)
        count_after_first = PageMetric.objects.count()
        second = import_metrics(self.site, backend, self.start, self.end)

        self.assertEqual(PageMetric.objects.count(), count_after_first)
        self.assertEqual(first.created, count_after_first)
        self.assertEqual((second.created, second.updated), (0, count_after_first))

    def test_reimport_updates_changed_numbers(self):
        row = {"keys": ["/a/"], "clicks": 1, "impressions": 100, "ctr": 0.01, "position": 9.0}
        import_metrics(self.site, self.write_sample([row]), self.start, self.end)
        import_metrics(self.site, self.write_sample([{**row, "clicks": 5, "ctr": 0.05}]), self.start, self.end)

        metric = PageMetric.objects.get()
        self.assertEqual((metric.clicks, metric.ctr), (5, 0.05))

    def test_a_new_date_range_adds_rows(self):
        backend = MockBackend(settings.GSC_SAMPLE_FILE)
        import_metrics(self.site, backend, self.start, self.end)
        count = PageMetric.objects.count()
        import_metrics(self.site, backend, date(2026, 10, 2), date(2026, 10, 29))
        self.assertEqual(PageMetric.objects.count(), count * 2)


@override_settings(GSC_BACKEND="mock")
class ImportGscCommandTests(TestCase):
    def run_command(self, *args):
        out = StringIO()
        call_command("import_gsc", *args, stdout=out)
        return out.getvalue()

    def test_running_twice_yields_same_row_count(self):
        self.run_command("--site", "https://shop.example.com", "--days", "28")
        count = PageMetric.objects.count()
        output = self.run_command("--site", "https://shop.example.com", "--days", "28")

        self.assertGreater(count, 0)
        self.assertEqual(PageMetric.objects.count(), count)
        self.assertEqual(Site.objects.get().url, SITE_URL)
        self.assertIn(f"0 created, {count} updated", output)

    def test_bad_site_url_is_a_command_error(self):
        with self.assertRaises(CommandError):
            self.run_command("--site", "not a url")

    @override_settings(GSC_BACKEND="google", GSC_CREDENTIALS_FILE="")
    def test_google_backend_without_credentials_is_a_command_error(self):
        with self.assertRaisesMessage(CommandError, "GOOGLE_APPLICATION_CREDENTIALS"):
            self.run_command("--site", SITE_URL)
