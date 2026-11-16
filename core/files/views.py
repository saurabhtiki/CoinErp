import logging
import mimetypes

from django.apps import apps
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from core.access.services import can_see_record, visible_records

from . import services
from .models import FileAttachment

logger = logging.getLogger(__name__)
SHOWN_IN_BROWSER = {"application/pdf", "image/png", "image/jpeg"}


class PrivateFileView(LoginRequiredMixin, View):
    """Serves a private file only to users who may see its record. Others get "not found"."""

    def get(self, request, name):
        found = services.file_for_download(request.user, name)
        if found is None:
            raise Http404("File not found.")
        stored_file, download_name = found
        try:
            handle = stored_file.open("rb")
        except FileNotFoundError:
            logger.error("File %r is in the database but missing on disk", name)
            raise Http404("This file is missing on the server. Please tell your admin.") from None
        content_type = mimetypes.guess_type(download_name)[0] or "application/octet-stream"
        response = FileResponse(
            handle,
            as_attachment=content_type not in SHOWN_IN_BROWSER,
            filename=download_name,
            content_type=content_type,
        )
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "sandbox"  # a file can never run scripts on our site
        return response


def _visible_record(user, app_label, model_name, pk):
    try:
        model = apps.get_model(app_label, model_name)
    except LookupError:
        raise Http404("No such kind of record.") from None
    return get_object_or_404(visible_records(model, user), pk=pk)


class RecordFilesView(LoginRequiredMixin, View):
    """Files of one record: list, upload, delete. Example: /files/masters/vendor/12/.

    Full page on a normal visit; only the panel for htmx requests, so uploads don't reload the page.
    """

    def get(self, request, app_label, model_name, pk):
        record = _visible_record(request.user, app_label, model_name, pk)
        return self.render(request, record)

    def post(self, request, app_label, model_name, pk):
        record = _visible_record(request.user, app_label, model_name, pk)
        error = None
        try:
            services.attach(record, request.FILES.get("file"), request.user)
        except ValidationError as refused:
            error = " ".join(refused.messages)
        if not request.htmx and error is None:
            return redirect(request.path)
        return self.render(request, record, error=error)

    @staticmethod
    def render(request, record, error=None):
        meta = record._meta
        context = {
            "record": record,
            "kind": meta.verbose_name,
            "upload_url": reverse("files:record", args=[meta.app_label, meta.model_name, record.pk]),
            "items": [(item, services.can_remove(item, request.user)) for item in services.attachments_for(record)],
            "error": error,
        }
        template = "files/partials/panel.html" if request.htmx else "files/record_files.html"
        return render(request, template, context)


class DeleteFileView(LoginRequiredMixin, View):
    """Soft delete one file, then redraw the panel."""

    def post(self, request, pk):
        attachment = get_object_or_404(FileAttachment, pk=pk, is_deleted=False)
        if not can_see_record(request.user, attachment.record):
            raise Http404("File not found.")
        services.remove(attachment, request.user)  # PermissionDenied -> 403 with a clear message
        return RecordFilesView.render(request, attachment.record)
