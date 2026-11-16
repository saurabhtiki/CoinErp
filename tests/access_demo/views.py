from django.http import HttpResponse
from django.views.generic import DetailView, View

from core.access.mixins import AppAccessRequiredMixin, VisibleRowsMixin

from .models import Note


class NotesHomeView(AppAccessRequiredMixin, View):
    app_code = "access_demo"

    def get(self, request):
        return HttpResponse("notes")


class NoteDetailView(AppAccessRequiredMixin, VisibleRowsMixin, DetailView):
    app_code = "access_demo"
    model = Note

    def render_to_response(self, context, **kwargs):
        return HttpResponse(self.object.title)
