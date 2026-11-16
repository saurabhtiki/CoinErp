from django.urls import include, path

from config.urls import urlpatterns as project_urls

from .views import NoteDetailView, NotesHomeView

urlpatterns = [
    path("notes/", NotesHomeView.as_view(), name="notes_home"),
    path("notes/<int:pk>/", NoteDetailView.as_view(), name="note_detail"),
    path("", include(project_urls)),
]
