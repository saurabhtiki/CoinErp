from django.contrib import admin

from core.access.admin import AccessModelAdmin

from .models import TaskCategory


@admin.register(TaskCategory)
class TaskCategoryAdmin(AccessModelAdmin):
    list_display = ("name", "company", "is_active")
    list_filter = ("company", "is_active")
    search_fields = ("name",)
