from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from simple_history.models import HistoricalRecords

from core.access.models import BaseModel
from core.access.services import allowed_companies
from core.files.validators import validate_file_content

from .fields import (
    CIN_VALIDATOR,
    IFSC_VALIDATOR,
    LOGO_EXTENSIONS,
    MOBILE_VALIDATOR,
    PHOTO_EXTENSIONS,
    TAN_VALIDATOR,
    UpperCaseCharField,
    check_gstn_matches_pan,
    gstn_field,
    pan_field,
    validate_logo_size,
    validate_photo_size,
)


class Company(models.Model):
    """A group company. Every business record belongs to one."""

    name = models.CharField(max_length=200)
    code = UpperCaseCharField(max_length=20, unique=True, help_text="Short code, e.g. ACME")
    address = models.TextField(blank=True)
    pan = pan_field()
    tan = UpperCaseCharField("TAN", max_length=10, blank=True, validators=[TAN_VALIDATOR])
    gstn = gstn_field()
    cin = UpperCaseCharField("CIN", max_length=21, blank=True, validators=[CIN_VALIDATOR])
    logo = models.FileField(
        upload_to="companies/logos/",
        blank=True,
        validators=[LOGO_EXTENSIONS, validate_logo_size, validate_file_content],
        help_text="JPG or PNG, up to 1 MB. Shown on reports.",
    )
    is_active = models.BooleanField(default=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "companies"

    def __str__(self):
        return self.name

    def clean(self):
        check_gstn_matches_pan(self.pan, self.gstn)


class CompanyCodedModel(BaseModel):
    """Name + short code; the code is unique inside one company. Example: branch "Pune", code "PUN"."""

    name = models.CharField(max_length=200)
    code = UpperCaseCharField(max_length=20)

    class Meta(BaseModel.Meta):
        abstract = True
        ordering = ["company", "name"]

    def __str__(self):
        return f"{self.name} ({self.code})"


def unique_code(name):
    return [models.UniqueConstraint(fields=["company", "code"], name=name)]


class Branch(CompanyCodedModel):
    address = models.TextField(blank=True)
    gstn = gstn_field(help_text="Only if this branch has its own GST registration.")

    class Meta(CompanyCodedModel.Meta):
        verbose_name_plural = "branches"
        constraints = unique_code("unique_branch_code_per_company")

    def clean(self):
        """A branch GSTN must carry the company's PAN. Example: Acme PAN ABCDE1234F -> 27ABCDE1234F1Z5."""
        if self.company_id:
            check_gstn_matches_pan(self.company.pan, self.gstn)


class Department(CompanyCodedModel):
    class Meta(CompanyCodedModel.Meta):
        constraints = unique_code("unique_department_code_per_company")


class CostCentre(CompanyCodedModel):
    class Meta(CompanyCodedModel.Meta):
        constraints = unique_code("unique_cost_centre_code_per_company")


def other_company_errors(record, **linked_records):
    """Errors for linked records from another company. Example: an Acme employee in a Globex branch."""
    return {
        field: f"Pick one from {record.company}."
        for field, linked in linked_records.items()
        if linked is not None and record.company_id and linked.company_id != record.company_id
    }


class Employee(BaseModel):
    employee_code = UpperCaseCharField(max_length=20, help_text="Unique inside the company, e.g. E0042")
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150, blank=True)
    email = models.EmailField(blank=True)
    mobile = models.CharField(max_length=10, blank=True, validators=[MOBILE_VALIDATOR])
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="employees",
        help_text="Login account, if this employee uses the ERP. One login can have one employee record per company.",
    )
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.PROTECT, related_name="employees")
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.PROTECT, related_name="employees"
    )
    designation = models.CharField(max_length=100, blank=True)
    reports_to = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="team")
    profile_photo = models.FileField(
        upload_to="employees/photos/",
        blank=True,
        validators=[PHOTO_EXTENSIONS, validate_photo_size, validate_file_content],
        help_text="JPG or PNG, up to 2 MB.",
    )

    class Meta(BaseModel.Meta):
        ordering = ["company", "first_name", "last_name"]
        constraints = [
            models.UniqueConstraint(fields=["company", "employee_code"], name="unique_employee_code_per_company"),
            models.UniqueConstraint(fields=["company", "user"], name="one_employee_record_per_user_per_company"),
        ]

    def __str__(self):
        return f"{self.first_name} {self.last_name}".strip() + f" ({self.employee_code})"

    def reports_to_in_loop(self):
        """True if the chosen manager is somewhere below this employee. Example: Asha -> Bina -> Asha."""
        if not self.pk:
            return False
        manager_id, seen = self.reports_to_id, set()
        while manager_id and manager_id not in seen:
            if manager_id == self.pk:
                return True
            seen.add(manager_id)
            manager_id = Employee.objects.filter(pk=manager_id).values_list("reports_to_id", flat=True).first()
        return False

    def clean(self):
        errors = other_company_errors(
            self, branch=self.branch, department=self.department, reports_to=self.reports_to
        )
        if self.pk and self.reports_to_id == self.pk:
            errors["reports_to"] = "An employee cannot report to themselves."
        elif self.reports_to_in_loop():
            errors["reports_to"] = f"{self.reports_to} already reports (directly or not) to this employee."
        if self.user_id and self.company_id and not allowed_companies(self.user).filter(pk=self.company_id).exists():
            errors["user"] = f"This login has no role in {self.company}. Give it a role there first."
        if errors:
            raise ValidationError(errors)


class Party(BaseModel):
    """Shared fields of Vendor and Customer. Bank fields are shown only to users allowed to see them."""

    BANK_FIELDS = ("bank_account_name", "bank_name", "bank_account_number", "bank_ifsc")

    name = models.CharField(max_length=200)
    pan = pan_field()
    gstn = gstn_field()
    contact_person = models.CharField(max_length=150, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    bank_account_name = models.CharField(max_length=200, blank=True)
    bank_name = models.CharField(max_length=200, blank=True)
    bank_account_number = models.CharField(max_length=30, blank=True)
    bank_ifsc = UpperCaseCharField("IFSC", max_length=11, blank=True, validators=[IFSC_VALIDATOR])

    class Meta(BaseModel.Meta):
        abstract = True
        ordering = ["company", "name"]

    def __str__(self):
        return self.name

    def clean(self):
        check_gstn_matches_pan(self.pan, self.gstn)


class Vendor(Party):
    class Meta(Party.Meta):
        permissions = [("view_bank_details", "Can see vendor and customer bank details")]


class Customer(Party):
    class Meta(Party.Meta):
        pass
