from django.core.management.base import BaseCommand, CommandError

from audit.pagecheck import get_fetcher
from audit.services import check_pages

from ._common import get_site_or_error


class Command(BaseCommand):
    help = "Fetch each imported page of a site and record its on-page basics (title, meta description, H1s, words)."

    def add_arguments(self, parser):
        parser.add_argument("--site", required=True, help="Site URL, as imported with import_gsc.")
        parser.add_argument("--limit", type=int, help="Only check the N pages with the most impressions.")

    def handle(self, *args, **options):
        site = get_site_or_error(options["site"])
        try:
            fetcher = get_fetcher()
        except (ValueError, OSError) as exc:
            raise CommandError(str(exc)) from exc

        def report(page_check):
            status = page_check.status_code or "no response"
            self.stdout.write(f"  {status}  {page_check.page_url}")

        result = check_pages(site, fetcher, limit=options["limit"], on_checked=report)
        if result.checked == 0:
            self.stdout.write(self.style.WARNING("No pages to check. Run import_gsc first."))
            return
        self.stdout.write(
            self.style.SUCCESS(f"Checked {result.checked} pages for {site.url}; {result.broken} returned an error.")
        )
