"""Indian ID fields. Each one saves upper-case and checks the format.

Examples: PAN ABCDE1234F, TAN ABCD12345E, GSTN 27ABCDE1234F1Z5,
CIN U12345MH2020PTC123456, IFSC HDFC0001234, mobile 9876543210.
"""
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, RegexValidator
from django.db import models

PAN_VALIDATOR = RegexValidator(r"^[A-Z]{5}[0-9]{4}[A-Z]$", "PAN must look like ABCDE1234F.")
TAN_VALIDATOR = RegexValidator(r"^[A-Z]{4}[0-9]{5}[A-Z]$", "TAN must look like ABCD12345E.")
GSTN_VALIDATOR = RegexValidator(
    r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$", "GSTN must look like 27ABCDE1234F1Z5."
)
CIN_VALIDATOR = RegexValidator(
    r"^[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$", "CIN must look like U12345MH2020PTC123456."
)
IFSC_VALIDATOR = RegexValidator(r"^[A-Z]{4}0[A-Z0-9]{6}$", "IFSC must look like HDFC0001234.")
MOBILE_VALIDATOR = RegexValidator(r"^[6-9][0-9]{9}$", "Mobile must be 10 digits, e.g. 9876543210.")
PHOTO_EXTENSIONS = FileExtensionValidator(["jpg", "jpeg", "png"], "Photo must be a JPG or PNG file.")
MAX_PHOTO_BYTES = 2 * 1024 * 1024


def validate_photo_size(file):
    if file.size > MAX_PHOTO_BYTES:
        raise ValidationError("Photo must be 2 MB or smaller.")


LOGO_EXTENSIONS = FileExtensionValidator(["jpg", "jpeg", "png"], "Logo must be a JPG or PNG file.")
MAX_LOGO_BYTES = 1024 * 1024


def validate_logo_size(file):
    if file.size > MAX_LOGO_BYTES:
        raise ValidationError("Logo must be 1 MB or smaller.")


class UpperCaseCharField(models.CharField):
    """Text saved in capitals without outer spaces, so 'abcde1234f ' becomes 'ABCDE1234F'."""

    def to_python(self, value):
        value = super().to_python(value)
        return value.strip().upper() if isinstance(value, str) else value

    def pre_save(self, model_instance, add):
        value = self.to_python(getattr(model_instance, self.attname))
        setattr(model_instance, self.attname, value)
        return value


def pan_field(**extra):
    return UpperCaseCharField("PAN", max_length=10, blank=True, validators=[PAN_VALIDATOR], **extra)


def gstn_field(**extra):
    return UpperCaseCharField("GSTN", max_length=15, blank=True, validators=[GSTN_VALIDATOR], **extra)


def check_gstn_matches_pan(pan, gstn):
    """A GSTN carries the PAN inside it (characters 3 to 12). Example: 27ABCDE1234F1Z5 -> ABCDE1234F."""
    if pan and gstn and gstn[2:12] != pan:
        raise ValidationError({"gstn": f"This GSTN does not belong to PAN {pan}."})
