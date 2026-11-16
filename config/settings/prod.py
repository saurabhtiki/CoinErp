"""Staging and production servers (behind Caddy, which does HTTPS). Everything comes from .env."""
from .base import *  # noqa: F401,F403
from .base import SILENCED_SYSTEM_CHECKS, env

DEBUG = False

# Caddy tells us the visitor used https. The app port is open on 127.0.0.1 only, so only Caddy can say so.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SECURE_REDIRECT_EXEMPT = [r"^healthz/$"]  # Docker and uptime monitors check this over plain http
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# HSTS makes browsers refuse plain http for this long. Start small; raise to 31536000 (1 year) once HTTPS works.
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=3600)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False)
SECURE_HSTS_PRELOAD = False
# Agreed not to use these two: "preload" is almost impossible to undo, and "include subdomains" would also
# bind other sites on the same domain (e.g. the sandbox) to HTTPS rules they may not follow.
SILENCED_SYSTEM_CHECKS = [*SILENCED_SYSTEM_CHECKS, "security.W005", "security.W021"]

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
