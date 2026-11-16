from django.urls import path

from .views import MasterListView

app_name = "masters"

urlpatterns = [
    path("<slug:master>/", MasterListView.as_view(), name="list"),
]
