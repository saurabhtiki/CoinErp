from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db.models import F
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django_datatable import CHOICE, DATE, Column, DataTable, table_response

from . import services
from .models import BackupRecord

COLUMNS = [
    Column("created_at", "Started", type=DATE),
    Column("kind", "Type", type=CHOICE, choices=dict(BackupRecord.Kind.choices)),
    Column("status", "Status", type=CHOICE, choices=dict(BackupRecord.Status.choices)),
]


class BackupsView(LoginRequiredMixin, View):
    """Superusers only. Everyone else gets 404, so the page looks like it does not exist."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not services.can_manage_backups(request.user):
            raise Http404("No such page.")
        return super().dispatch(request, *args, **kwargs)


class BackupListView(BackupsView):
    def get(self, request, error=""):
        rows = BackupRecord.objects.annotate(downloaded_by_name=F("last_downloaded_by__first_name"))
        table = DataTable(
            request.GET, rows, COLUMNS, table_id="backups-table", default_sort=("-created_at",),
            base_url=request.path, noun="backups",
        )
        context = {"table": table, "title": "Backups", "error": error}
        return table_response(request, table, "backups/list.html", "backups/partials/table.html", context)


class BackupNowView(BackupsView):
    def post(self, request):
        try:
            services.start_backup(request.user)
        except ValidationError as error:
            return BackupListView().get(request, error=error.message)
        return redirect("backups:list")


class BackupDownloadView(BackupsView):
    def get(self, request, pk):
        record = get_object_or_404(BackupRecord, pk=pk)
        path = services.downloadable_file(record)
        if path is None:
            raise Http404("This backup file is no longer on the server.")
        services.record_download(request.user, record)
        return FileResponse(open(path, "rb"), as_attachment=True, filename=record.file_name)
