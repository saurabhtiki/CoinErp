from django.db import models


class ApprovableMixin(models.Model):
    """Add to an app model that goes through approvals. Example:

        class Expense(ApprovableMixin, BaseModel):
            approval_amount_field = "amount"   # optional: steps with a minimum amount use it
            amount = models.DecimalField(...)

    While waiting for approval or once approved, saving the record raises a ValidationError.
    """

    uses_approvals = True
    approval_amount_field = None

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk:
            from .services import ensure_editable

            ensure_editable(self)
        super().save(*args, **kwargs)
