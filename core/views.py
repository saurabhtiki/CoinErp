from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.views import View
from django.views.generic import TemplateView

from core.registry import dashboard_cards


class HomeView(LoginRequiredMixin, TemplateView):
    """Home dashboard: one card per app the user may open, from the app registry."""

    template_name = "core/home.html"

    def get_context_data(self, **kwargs):
        return super().get_context_data(cards=dashboard_cards(self.request.user), **kwargs)


class HealthCheckView(View):
    """Used by Docker/nginx to check the app is up. No login, no data."""

    def get(self, request):
        return HttpResponse("ok", content_type="text/plain")
