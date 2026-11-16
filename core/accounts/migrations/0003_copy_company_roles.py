"""Copy the old links (user companies × user roles) into the new company-role table."""
from django.db import migrations


def copy_links(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    CompanyRole = apps.get_model("accounts", "CompanyRole")
    for user in User.objects.prefetch_related("companies", "roles"):
        for company in user.companies.all():
            for role in user.roles.all():
                CompanyRole.objects.get_or_create(user=user, company=company, role=role)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_company_role")]

    operations = [migrations.RunPython(copy_links, migrations.RunPython.noop)]
