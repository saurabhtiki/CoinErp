from django.apps import AppConfig


class MastersConfig(AppConfig):
    name = "core.masters"
    label = "masters"
    verbose_name = "Masters"

    def ready(self):
        from core.files.services import protect_file_field
        from core.registry import AppEntry, register

        from .models import Employee
        from .services import dashboard_counts

        protect_file_field(Employee, "profile_photo")  # photo opens only for users who may see the employee

        register(
            AppEntry(
                code="masters",
                name="Masters",
                icon="building",
                url_name="masters:list",
                url_args=("companies",),
                description="Companies, branches, departments, employees, vendors and customers",
                order=10,
                widget_template="masters/widget.html",
                widget_data=dashboard_counts,
            )
        )
