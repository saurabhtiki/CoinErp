from django.apps import AppConfig


class TasksConfig(AppConfig):
    name = "apps.tasks"
    label = "tasks"
    verbose_name = "Tasks"

    def ready(self):
        from core.registry import AppEntry, register

        register(
            AppEntry(
                code="tasks",
                name="Tasks",
                icon="check",
                url_name="tasks:list",
                url_args=("mine",),
                description="Tasks with owners, due dates, files and comments",
                order=20,
            )
        )
