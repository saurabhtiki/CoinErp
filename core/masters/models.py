from django.db import models


class Company(models.Model):
    """A group company. Step 4 adds address and tax IDs (PAN, TAN, GSTN, CIN)."""

    name = models.CharField(max_length=200)
    code = models.CharField(max_length=20, unique=True, help_text="Short code, e.g. ACME")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "companies"

    def __str__(self):
        return self.name
