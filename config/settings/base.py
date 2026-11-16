"""Settings shared by every environment. Secrets and per-server values come from .env."""
from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    # third party
    "django_htmx",
    "django_tailwind_cli",
    "django_datatable",
    "axes",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "simple_history",
    "django_q",
    # core
    "core",
    "core.masters",
    "core.accounts",
    "core.audit",
    "core.files",
    "core.notifications",
    "core.approvals",
    "core.reports",
    # apps
    "apps.tasks",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",  # records who made each change
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "core.accounts.middleware.TwoFactorRequiredMiddleware",
    # Must be last: blocks locked-out accounts.
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

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
                "core.context_processors.app_menu",
                "core.context_processors.environment",
                "core.notifications.context_processors.unread_notifications",
                "core.approvals.context_processors.waiting_approvals",
            ],
        },
    },
]

# Database: sqlite:///db.sqlite3 for dev, postgres://user:pass@host:5432/name for prod.
DATABASES = {"default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",  # must be first: counts wrong passwords
    "django.contrib.auth.backends.ModelBackend",
]

# Lockout: 5 wrong passwords lock that account for 30 minutes. Admin can unlock in "Axes".
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(minutes=30)
AXES_LOCKOUT_PARAMETERS = ["username"]
AXES_USERNAME_CALLABLE = "core.accounts.services.lockout_username"
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_TEMPLATE = "registration/locked.html"
# We lock the account, not the IP: everyone in one office shares an IP, so an IP lock
# would lock out the whole office. Agreed in docs/plan.md (decision 8).
SILENCED_SYSTEM_CHECKS = ["axes.W006"]

# 2FA: name shown in the authenticator app
OTP_TOTP_ISSUER = "Group ERP"

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = LOGIN_URL

# Region: India
LANGUAGE_CODE = "en-in"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True
DATE_INPUT_FORMATS = ["%d-%m-%Y", "%Y-%m-%d"]
DEFAULT_CURRENCY = "INR"

# History: view only. Restoring an old version is done by editing the record.
SIMPLE_HISTORY_REVERT_DISABLED = True

# Static and uploaded files. MEDIA is private: never served directly by nginx.
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "assets"]
MEDIA_ROOT = env.path("MEDIA_ROOT", default=BASE_DIR / "private_media")
# File links point to the permission-checked view (core/files), never to the folder itself.
MEDIA_URL = "/files/private/"

# Tailwind + DaisyUI, built without Node by django-tailwind-cli
TAILWIND_CLI_USE_DAISY_UI = True
TAILWIND_CLI_SRC_CSS = "frontend/source.css"
TAILWIND_CLI_DIST_CSS = "css/tailwind.css"

# Which server this is: "production" or "sandbox" (test copy with fake data only).
ENVIRONMENT = env("ENVIRONMENT", default="production")
IS_SANDBOX = ENVIRONMENT == "sandbox"
# Password of the fake demo users (sandbox only). Change it in the sandbox .env.
DEMO_PASSWORD = env("DEMO_PASSWORD", default="")

EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")
if IS_SANDBOX:
    # The sandbox never sends real mail: it is written to the log (and shown on the "Sent mail" page).
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
# Give up on a mail server that does not answer (seconds), so a stuck send is retried and logged.
EMAIL_TIMEOUT = env.int("EMAIL_TIMEOUT", default=20)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="erp@localhost")
# Full address of this site, used for links inside emails. Example: https://erp.example.com
SITE_URL = env("SITE_URL", default="http://localhost:8000")

# Background jobs (django-q2). The queue is kept in the database, so no Redis is needed.
# Docker runs them in the "worker" container. With sync=True (dev, tests) they run at once, no worker needed.
Q_CLUSTER = {
    "name": "erp",
    "orm": "default",
    "workers": env.int("Q_WORKERS", default=2),
    "timeout": 180,  # seconds one job may take: 3 email tries x 20s timeout + 40s waits fits easily
    "retry": 240,  # must be longer than timeout
    "catch_up": False,
    "sync": env.bool("Q_SYNC", default=False),
}
# A failed email is tried 3 times in all, waiting this many seconds between tries.
NOTIFY_RETRY_WAITS = (10, 30)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}
