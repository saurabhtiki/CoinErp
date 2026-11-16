import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import DatabaseError, connection
from django.http import HttpResponse
from django.views import View
from django.views.generic import TemplateView

from core.registry import dashboard_cards

logger = logging.getLogger(__name__)


class HomeView(LoginRequiredMixin, TemplateView):
    """Home dashboard: one card per app the user may open, from the app registry."""

    template_name = "core/home.html"

    def get_context_data(self, **kwargs):
        return super().get_context_data(cards=dashboard_cards(self.request.user), **kwargs)


class HealthCheckView(View):
    """Used by Docker and uptime monitors. No login, no data. Says 503 when the database cannot be reached."""

    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        except DatabaseError:
            logger.exception("Health check failed: the database cannot be reached")
            return HttpResponse("Database is not reachable. Check the db container and DATABASE_URL.",
                                content_type="text/plain", status=503)
        return HttpResponse("ok", content_type="text/plain")
