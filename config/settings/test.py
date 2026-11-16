"""Automated tests: fast in-memory SQLite, no real emails, fixed secret."""
import os

os.environ.setdefault("SECRET_KEY", "test-only-not-secret")

from .base import *  # noqa: E402,F401,F403

DEBUG = False
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Test-only app with a sample model for the access layer tests.
INSTALLED_APPS = [*INSTALLED_APPS, "tests.access_demo"]  # noqa: F405
