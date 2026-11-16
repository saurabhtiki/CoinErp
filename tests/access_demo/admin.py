from django.contrib import admin

from core.access.admin import AccessModelAdmin

from .models import Expense


@admin.register(Expense)
class ExpenseAdmin(AccessModelAdmin):
    """Test-only admin, to prove locked records cannot be changed or deleted from the admin."""

    list_display = ["title", "amount", "company"]
