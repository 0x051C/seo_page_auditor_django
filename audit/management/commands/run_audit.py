from django.core.management.base import BaseCommand
from django.urls import reverse

from audit import rules
from audit.services import run_audit

from ._common import get_site_or_error


class Command(BaseCommand):
    help = "Apply the SEO rules to a site's metrics and page checks, and update its issues."

    def add_arguments(self, parser):
        parser.add_argument("--site", required=True, help="Site URL, as imported with import_gsc.")

    def handle(self, *args, **options):
        site = get_site_or_error(options["site"])
        result = run_audit(site)

        self.stdout.write(
            self.style.SUCCESS(
                f"Audited {site.url}: {result.open} open issues "
                f"({result.created} new, {result.updated} still present), {result.resolved} resolved."
            )
        )
        open_issues = site.issues.filter(resolved=False)
        counts = [f"{open_issues.filter(severity=level).count()} {level}" for level in (rules.HIGH, rules.MEDIUM, rules.LOW)]
        self.stdout.write("  By severity: " + ", ".join(counts))
        self.stdout.write(f"  Report: {reverse('audit:site-report', args=[site.pk])} (start the server with: python manage.py runserver)")
