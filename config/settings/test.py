"""Automated tests: fast in-memory SQLite, no real emails, fixed secret."""
import os

os.environ.setdefault("SECRET_KEY", "test-only-not-secret")

from .base import *  # noqa: E402,F401,F403

DEBUG = False
ENVIRONMENT = "testing"
IS_SANDBOX = False
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
EMAIL_SETTINGS_KEY = "kSl1Hc4z0nN2pV5uYfQ3m8Wb7eTgXr6aJdLh9oUiCy0="  # test-only key, not secret
Q_CLUSTER = {**Q_CLUSTER, "sync": True}  # noqa: F405
NOTIFY_RETRY_WAITS = (0, 0)
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Test-only app with a sample model for the access layer tests.
INSTALLED_APPS = [*INSTALLED_APPS, "tests.access_demo"]  # noqa: F405
