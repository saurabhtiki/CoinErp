"""Developer PC: SQLite, debug on, emails printed to the console."""
from .base import *  # noqa: F401,F403
from .base import env

DEBUG = env.bool("DEBUG", default=True)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
