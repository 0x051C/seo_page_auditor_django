"""Helpers shared by the management commands. The leading underscore keeps Django from treating this as a command."""

from django.core.management.base import CommandError

from audit.models import Site
from audit.services import normalize_site_url


def site_url_or_error(url):
    try:
        return normalize_site_url(url)
    except ValueError as exc:
        raise CommandError(str(exc)) from exc


def get_site_or_error(url):
    url = site_url_or_error(url)
    try:
        return Site.objects.get(url=url)
    except Site.DoesNotExist:
        raise CommandError(f"No site {url}. Run: python manage.py import_gsc --site {url}") from None
