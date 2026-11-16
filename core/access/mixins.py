from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin

from . import services


class AppAccessRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Put on every app view. Not logged in -> login page; role lacks the app -> 403.

    Example:
        class TaskListView(AppAccessRequiredMixin, ListView):
            app_code = "tasks"
    """

    app_code = None

    def test_func(self):
        if not self.app_code:
            raise ValueError(f"{type(self).__name__} must set app_code.")
        return services.user_can_open_app(self.request.user, self.app_code)


class VisibleRowsMixin:
    """For list/detail/edit views: limits the queryset to rows the user may see.
    Someone else's row gives 404, so the page doesn't even reveal it exists."""

    def get_queryset(self):
        return super().get_queryset().for_user(self.request.user)
