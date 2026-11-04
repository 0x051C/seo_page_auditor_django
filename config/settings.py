"""
Django settings for the SEO Page Auditor project.

Configuration comes from environment variables. For local work, put them in
an untracked `.env` file (see `.env.example`); python-dotenv loads it below.
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Where files you create live: the database and .env. From source that is the
# project folder. The Nuitka binary unpacks its code into a temporary folder
# on every run, so there it is the folder you run the binary from instead.
# Nuitka defines __compiled__ in every module it compiles.
DATA_DIR = Path.cwd() if "__compiled__" in globals() else BASE_DIR

# Read KEY=value pairs from .env into os.environ. Real environment variables
# win over the file, so the same code works locally and in CI.
load_dotenv(DATA_DIR / ".env")


def env_bool(name, default=False):
    """Read an environment variable as a boolean ("1", "true", "yes" = True)."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


DEBUG = env_bool("DJANGO_DEBUG", default=True)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("Set DJANGO_SECRET_KEY when DJANGO_DEBUG is off.")
    # Placeholder for local development only. It is not a real secret.
    SECRET_KEY = "dev-only-insecure-key-change-me"

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "rest_framework",
    "audit",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Database: a single SQLite file, ignored by git.

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "db.sqlite3",
    }
}


# Password validation (used by the admin's createsuperuser)

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# Internationalization

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True


# Static files

STATIC_URL = "static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Django REST Framework: one read-only endpoint, no auth needed locally.
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
}


# Search Console
# "mock" reads sample_data/gsc_sample.json, "google" calls the real API.
GSC_BACKEND = os.environ.get("GSC_BACKEND", "mock")
GSC_SAMPLE_FILE = BASE_DIR / "sample_data" / "gsc_sample.json"
# Path to a service-account JSON key with read access to the property.
GSC_CREDENTIALS_FILE = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")


# Page checker
# "mock" builds pages from sample_data/pages_sample.json, "http" fetches them.
# Defaults to mock when the Search Console backend is mock, so one switch
# (GSC_BACKEND=mock) runs the whole pipeline offline.
PAGE_FETCHER = os.environ.get("PAGE_FETCHER") or ("mock" if GSC_BACKEND == "mock" else "http")
PAGE_SAMPLE_FILE = BASE_DIR / "sample_data" / "pages_sample.json"
PAGE_FETCH_TIMEOUT = float(os.environ.get("PAGE_FETCH_TIMEOUT", "10"))  # seconds
PAGE_FETCH_DELAY = float(os.environ.get("PAGE_FETCH_DELAY", "1"))  # seconds between requests
PAGE_FETCH_USER_AGENT = os.environ.get(
    "PAGE_FETCH_USER_AGENT",
    "SEOPageAuditor/0.1 (+https://github.com/0x051C/seo_page_auditor_django)",
)
