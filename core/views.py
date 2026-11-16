from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.views import View
from django.views.generic import TemplateView


class HomeView(LoginRequiredMixin, TemplateView):
    """Home dashboard. Widgets from the app registry are added in Phase 1 step 5."""

    template_name = "core/home.html"


class HealthCheckView(View):
    """Used by Docker/nginx to check the app is up. No login, no data."""

    def get(self, request):
        return HttpResponse("ok", content_type="text/plain")
