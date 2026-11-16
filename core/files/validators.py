"""Upload checks: allowed types, size, and that the content really is what the name says.

Example: "invoice.pdf" must start like a PDF, so a renamed program file is refused.
"""
import logging
import os

from django.core.exceptions import ValidationError
from django.template.defaultfilters import filesizeformat

logger = logging.getLogger(__name__)

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
ZIP_START = (b"PK\x03\x04",)  # Excel and Word files are zip files inside
FILE_STARTS = {
    ".pdf": (b"%PDF",),
    ".png": (b"\x89PNG",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".xlsx": ZIP_START,
    ".docx": ZIP_START,
    ".csv": None,  # plain text: checked separately
}
ALLOWED_TYPES_TEXT = "PDF, JPG, PNG, Excel (.xlsx), Word (.docx) or CSV"


def _read_start(file, length=1024):
    file.seek(0)
    start = file.read(length)
    file.seek(0)
    return start


def validate_file_content(file):
    """The first bytes must match the extension. Works for any of the types above."""
    extension = os.path.splitext(file.name)[1].lower()
    if extension not in FILE_STARTS:
        return
    start = _read_start(file)
    expected = FILE_STARTS[extension]
    looks_right = b"\x00" not in start if expected is None else start.startswith(expected)
    if not looks_right:
        logger.warning("Refused upload %r: content does not match its extension", file.name)
        raise ValidationError(f"This file is not a real {extension} file. Please upload the original file.")


def validate_attachment(file):
    """Type, size and content checks for attachments. Example message: "File is too big (12.3 MB)..."."""
    extension = os.path.splitext(file.name)[1].lower()
    if extension not in FILE_STARTS:
        logger.warning("Refused upload %r: type not allowed", file.name)
        raise ValidationError(f"This type of file is not allowed. Use {ALLOWED_TYPES_TEXT}.")
    if file.size > MAX_ATTACHMENT_BYTES:
        logger.warning("Refused upload %r: %s bytes", file.name, file.size)
        raise ValidationError(f"File is too big ({filesizeformat(file.size)}). The limit is 10 MB.")
    validate_file_content(file)
