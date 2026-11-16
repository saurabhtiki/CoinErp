from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.views.generic import TemplateView

from core.access.services import visible_records

from . import services


class RecordHistoryView(LoginRequiredMixin, TemplateView):
    """History of one record. Example: /history/masters/vendor/12/.

    Only for records the user may see; anything else gives "not found", so it doesn't reveal the record exists.
    """

    template_name = "audit/history.html"

    def get_context_data(self, app_label, model_name, pk, **kwargs):
        model = services.tracked_model(app_label, model_name)
        if model is None:
            raise Http404("This kind of record has no history.")
        record = get_object_or_404(visible_records(model, self.request.user), pk=pk)
        return super().get_context_data(
            record=record,
            kind=model._meta.verbose_name,
            entries=services.record_history(record, self.request.user),
            **kwargs,
        )
