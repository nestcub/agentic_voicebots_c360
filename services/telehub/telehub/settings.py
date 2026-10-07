"""
Django settings for telehub project.

Postgres (Supabase) backend, no Redis, no auth.
"""

import os
import sys
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

# BASE_DIR is the outer services/telehub/ directory (contains manage.py),
# i.e. two levels up from this settings.py file.
BASE_DIR = Path(__file__).resolve().parent.parent

# Make sure the "apps" package (apps/telehub/...) is importable given
# this nested layout.
sys.path.insert(0, str(BASE_DIR))

# Repo root's .env (three levels up: telehub/ -> services/ -> repo root) —
# shared with the rest of the monorepo (CHAT360_OUTBOUND_BEARER_TOKEN,
# CHAT360_AUTH_COOKIE, etc., see services/dispatcher.py). Without this,
# os.environ.get(...) in dispatcher.py silently returns "" for everything in
# .env even when the file has real values — Django never reads dotenv files
# on its own.
load_dotenv(BASE_DIR.parent.parent / ".env")

# Deployed (Render) sets DJANGO_SECRET_KEY / DJANGO_DEBUG=false; local dev needs neither.
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY", "django-insecure-telehub-dev-only-secret-key-change-me"
)

DEBUG = os.environ.get("DJANGO_DEBUG", "true").lower() == "true"

ALLOWED_HOSTS = ["*"]

# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "corsheaders",
    "rest_framework",
    "apps.telehub",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "telehub.urls"

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

WSGI_APPLICATION = "telehub.wsgi.application"
ASGI_APPLICATION = "telehub.asgi.application"

# Database — Supabase Postgres.
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases
#
# Deliberately NOT the repo's existing DATABASE_URL — that name is already
# claimed by the Intelligence plane's Neon/pgvector connection (see
# .env.example, intelligence/). Reusing it here would silently point telehub
# at the wrong database. TELEHUB_DATABASE_URL is a separate Supabase project.
#
# Use Supabase's pooled connection string (port 6543, ?pgbouncer=true) for
# normal app traffic. Set TELEHUB_DATABASE_MIGRATE_URL (direct port 5432) if
# the pooled connection rejects DDL when running `manage.py migrate`.
_database_url = os.environ.get("TELEHUB_DATABASE_MIGRATE_URL") if "migrate" in sys.argv else None
_database_url = _database_url or os.environ.get("TELEHUB_DATABASE_URL")
if not _database_url:
    raise RuntimeError(
        "TELEHUB_DATABASE_URL is not set — telehub requires a Supabase/Postgres "
        "connection string in the repo-root .env (see CLAUDE.md). Do not reuse "
        "DATABASE_URL — that's the Intelligence plane's Neon connection."
    )

DATABASES = {
    "default": dj_database_url.parse(_database_url, conn_max_age=600),
}
# Supabase's docs append ?pgbouncer=true to the pooled URL as a hint for
# clients like asyncpg — dj_database_url forwards unknown query params
# straight into OPTIONS, and psycopg (unlike psycopg2) rejects unknown libpq
# connection options outright, so this must be stripped rather than passed through.
DATABASES["default"].get("OPTIONS", {}).pop("pgbouncer", None)

# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators
# V1 has no auth per the plan docs; these are kept only because
# django.contrib.auth is installed for admin site login.

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = "static/"
# collectstatic target; WhiteNoise serves it (Django admin CSS) without a separate web server.
STATIC_ROOT = BASE_DIR / "staticfiles"

# Default primary key field type
# https://docs.djangoproject.com/en/6.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# CORS — explicit origins only (not CORS_ALLOW_ALL_ORIGINS). Defaults to the
# Next.js dev origin; deployed, set a comma-separated list (the Vercel URL).
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
    if origin.strip()
]
# Needed for Django admin login over HTTPS on the deployed host.
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
# Render terminates TLS at its proxy; trust its header so request.is_secure() is right.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# Admin session/CSRF cookies over HTTPS only when deployed.
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

# Without this, apps.telehub's loggers (e.g. services/dispatcher.py) are silent
# on console — Django's unconfigured-logger default only surfaces WARNING+.
# This surfaces dispatch attempts/results (URL, status, redirect Location) in
# whatever terminal is running runserver/run_scheduler.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "loggers": {
        "apps.telehub": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
