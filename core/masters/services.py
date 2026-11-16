"""Masters business logic."""
from core.access.services import companies_for_app

from .models import Customer, Employee, Vendor


def dashboard_counts(user):
    """How many records of each main master the user can see. Example: Companies 2, Vendors 14."""
    counts = [
        ("companies", "Companies", companies_for_app(user, "masters")),
        ("employees", "Employees", Employee.objects.for_user(user)),
        ("vendors", "Vendors", Vendor.objects.for_user(user)),
        ("customers", "Customers", Customer.objects.for_user(user)),
    ]
    return {"counts": [{"slug": slug, "title": title, "count": rows.count()} for slug, title, rows in counts]}
