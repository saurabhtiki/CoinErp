"""Developer PC: SQLite, debug on, emails printed to the console."""
from .base import *  # noqa: F401,F403
from .base import env

DEBUG = env.bool("DEBUG", default=True)
ENVIRONMENT = env("ENVIRONMENT", default="development")  # so load_demo_data works on a developer PC
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
Q_CLUSTER = {**Q_CLUSTER, "sync": env.bool("Q_SYNC", default=True)}  # noqa: F405  jobs run at once, no worker
