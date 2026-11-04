from datetime import date
from io import StringIO
from pathlib import Path
from unittest import mock

import requests
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from audit.models import PageCheck, PageMetric, Site
from audit.pagecheck import FetchResult, HttpFetcher, MockFetcher, ParsedPage, parse_html
from audit.services import check_pages, pages_by_impressions

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class ParseHtmlFixtureTests(SimpleTestCase):
    def test_good_page(self):
        page = parse_html(fixture("good_page.html"))
        self.assertEqual(page.title, "How to Choose Hiking Boots | Trailpeak Outdoors")
        self.assertTrue(page.meta_description.startswith("Cut, waterproofing, fit and break-in"))
        self.assertEqual(page.h1_count, 1)
        self.assertGreater(page.word_count, 300)
        self.assertTrue(page.has_canonical)

    def test_missing_title(self):
        page = parse_html(fixture("missing_title.html"))
        self.assertEqual(page.title, "")
        self.assertEqual(page.h1_count, 1)
        self.assertFalse(page.has_canonical)

    def test_two_h1s(self):
        page = parse_html(fixture("two_h1.html"))
        self.assertEqual(page.h1_count, 2)
        # name="DESCRIPTION" still matches, and surrounding whitespace is trimmed.
        self.assertEqual(page.meta_description, "Waterproof hiking boots and lightweight trail shoes.")


class ParseHtmlDetailTests(SimpleTestCase):
    def test_empty_html_gives_empty_fields(self):
        self.assertEqual(parse_html(""), ParsedPage())

    def test_svg_title_is_not_the_page_title(self):
        page = parse_html("<html><body><svg><title>Logo</title></svg><p>Hi</p></body></html>")
        self.assertEqual(page.title, "")

    def test_title_whitespace_is_collapsed(self):
        page = parse_html("<title>\n  Tents   and\n Tarps </title>")
        self.assertEqual(page.title, "Tents and Tarps")

    def test_word_count_skips_scripts_styles_and_punctuation(self):
        html = (
            "<html><head><title>Not counted</title><style>p { color: red }</style></head>"
            "<body><p>One two, three! | -</p><script>var notCounted = 1;</script>"
            "<noscript>Enable JavaScript</noscript></body></html>"
        )
        self.assertEqual(parse_html(html).word_count, 3)

    def test_canonical_needs_an_href(self):
        self.assertFalse(parse_html('<link rel="canonical">').has_canonical)
        self.assertTrue(parse_html('<link rel="canonical" href="https://a.com/">').has_canonical)

    def test_meta_without_content(self):
        self.assertEqual(parse_html('<meta name="description">').meta_description, "")


class FakeResponse:
    def __init__(self, status_code=200, text="<title>Hi</title>", content_type="text/html; charset=utf-8"):
        self.status_code = status_code
        self.text = text
        self.headers = {"Content-Type": content_type}


class HttpFetcherTests(SimpleTestCase):
    def make_fetcher(self, response=None, side_effect=None, clock_times=(0.0, 0.0)):
        session = mock.Mock()
        session.get.return_value = response or FakeResponse()
        session.get.side_effect = side_effect
        self.sleep = mock.Mock()
        clock = mock.Mock(side_effect=list(clock_times))
        fetcher = HttpFetcher(user_agent="TestBot/1.0", timeout=5, delay=1.0, session=session, sleep=self.sleep, clock=clock)
        return fetcher, session

    def test_sends_user_agent_and_timeout(self):
        fetcher, session = self.make_fetcher()
        result = fetcher.fetch("https://a.com/")
        session.get.assert_called_once_with("https://a.com/", headers={"User-Agent": "TestBot/1.0"}, timeout=5)
        self.assertEqual(result, FetchResult(status_code=200, html="<title>Hi</title>"))

    def test_waits_so_requests_are_at_least_one_second_apart(self):
        # Clock reads: first request at t=0, second checks at t=0.25 and records t=1.0.
        fetcher, _ = self.make_fetcher(clock_times=(0.0, 0.25, 1.0))
        fetcher.fetch("https://a.com/1/")
        self.sleep.assert_not_called()
        fetcher.fetch("https://a.com/2/")
        self.sleep.assert_called_once_with(0.75)

    def test_no_wait_when_enough_time_has_passed(self):
        fetcher, _ = self.make_fetcher(clock_times=(0.0, 3.0, 3.0))
        fetcher.fetch("https://a.com/1/")
        fetcher.fetch("https://a.com/2/")
        self.sleep.assert_not_called()

    def test_network_error_gives_no_status(self):
        fetcher, _ = self.make_fetcher(side_effect=requests.ConnectionError("boom"))
        self.assertEqual(fetcher.fetch("https://a.com/"), FetchResult(status_code=None))

    def test_non_html_body_is_not_kept(self):
        fetcher, _ = self.make_fetcher(response=FakeResponse(text="%PDF-1.7", content_type="application/pdf"))
        self.assertEqual(fetcher.fetch("https://a.com/x.pdf").html, "")

    def test_error_status_is_returned(self):
        fetcher, _ = self.make_fetcher(response=FakeResponse(status_code=404, text="<title>Not found</title>"))
        self.assertEqual(fetcher.fetch("https://a.com/gone/").status_code, 404)


class MockFetcherTests(SimpleTestCase):
    def setUp(self):
        self.fetcher = MockFetcher(settings.PAGE_SAMPLE_FILE)

    def test_known_page_renders_html_that_parses_back(self):
        result = self.fetcher.fetch("https://shop.example.com/hiking-boots/")
        page = parse_html(result.html)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(page.title, "Hiking Boots for Men and Women | Trailpeak Outdoors")
        self.assertEqual(page.h1_count, 2)
        self.assertTrue(page.has_canonical)

    def test_unknown_page_is_404(self):
        self.assertEqual(self.fetcher.fetch("https://shop.example.com/nope/").status_code, 404)


class FakeFetcher:
    """Returns canned results by URL and records what was fetched."""

    def __init__(self, results):
        self.results = results
        self.fetched = []

    def fetch(self, url):
        self.fetched.append(url)
        return self.results.get(url, FetchResult(status_code=404))


class CheckPagesServiceTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(url="https://a.com/")
        self.good = "https://a.com/good/"
        self.gone = "https://a.com/gone/"
        for url, impressions in [(self.good, 100), (self.gone, 900)]:
            PageMetric.objects.create(
                site=self.site, page_url=url, date_start=date(2026, 10, 1), date_end=date(2026, 10, 28), impressions=impressions
            )
        self.fetcher = FakeFetcher({self.good: FetchResult(200, fixture("good_page.html"))})

    def test_pages_are_distinct_and_ordered_by_impressions(self):
        # A second date range for the same page must not list it twice.
        PageMetric.objects.create(
            site=self.site, page_url=self.good, date_start=date(2026, 10, 2), date_end=date(2026, 10, 29), impressions=50
        )
        self.assertEqual(pages_by_impressions(self.site), [self.gone, self.good])

    def test_saves_one_check_per_page(self):
        result = check_pages(self.site, self.fetcher)

        self.assertEqual((result.checked, result.broken), (2, 1))
        good = PageCheck.objects.get(page_url=self.good)
        self.assertEqual((good.status_code, good.h1_count, good.has_canonical), (200, 1, True))
        self.assertEqual(PageCheck.objects.get(page_url=self.gone).status_code, 404)

    def test_rechecking_overwrites_instead_of_duplicating(self):
        check_pages(self.site, self.fetcher)
        self.fetcher.results[self.good] = FetchResult(200, fixture("two_h1.html"))
        check_pages(self.site, self.fetcher)

        self.assertEqual(PageCheck.objects.count(), 2)
        self.assertEqual(PageCheck.objects.get(page_url=self.good).h1_count, 2)

    def test_limit_checks_top_pages_first(self):
        check_pages(self.site, self.fetcher, limit=1)
        self.assertEqual(self.fetcher.fetched, [self.gone])


@override_settings(GSC_BACKEND="mock", PAGE_FETCHER="mock")
class CheckPagesCommandTests(TestCase):
    def test_checks_every_imported_page(self):
        call_command("import_gsc", "--site", "https://shop.example.com/", stdout=StringIO())
        out = StringIO()
        call_command("check_pages", "--site", "https://shop.example.com/", stdout=out)

        self.assertEqual(PageCheck.objects.count(), PageMetric.objects.count())
        self.assertIn("Checked 40 pages", out.getvalue())
        self.assertEqual(PageCheck.objects.get(page_url="https://shop.example.com/gift-cards/").status_code, 500)

    def test_unknown_site_is_a_command_error(self):
        with self.assertRaisesMessage(CommandError, "import_gsc"):
            call_command("check_pages", "--site", "https://unknown.example.com/")
