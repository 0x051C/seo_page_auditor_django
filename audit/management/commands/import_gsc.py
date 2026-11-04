from django.core.management.base import BaseCommand, CommandError

from audit.gsc import SearchConsoleError, date_window, get_backend
from audit.models import Site
from audit.services import import_metrics

from ._common import site_url_or_error


class Command(BaseCommand):
    help = "Import Search Console page metrics (clicks, impressions, CTR, position) for a site."

    def add_arguments(self, parser):
        parser.add_argument("--site", required=True, help="Search Console property URL, e.g. https://www.example.com/")
        parser.add_argument("--days", type=int, default=28, help="How many days of data to import (default 28).")

    def handle(self, *args, **options):
        url = site_url_or_error(options["site"])
        try:
            start, end = date_window(options["days"])
            backend = get_backend()
            site, _ = Site.objects.get_or_create(url=url)
            result = import_metrics(site, backend, start, end)
        except (ValueError, SearchConsoleError) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {result.total} pages for {site.url} ({start} to {end}): "
                f"{result.created} created, {result.updated} updated."
            )
        )
