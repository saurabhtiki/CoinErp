from django.db import models

from core.access.models import BaseModel
from core.approvals.mixins import ApprovableMixin


class Note(BaseModel):
    title = models.CharField(max_length=100)


class Expense(ApprovableMixin, BaseModel):
    """Test-only record that goes through approvals."""

    approval_amount_field = "amount"

    title = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    def __str__(self):
        return self.title
