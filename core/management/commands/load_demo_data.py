from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from config.demo_data import DemoDataExists, load_demo_data


class Command(BaseCommand):
    help = "Create fake demo companies, users and tasks. Never runs on production."

    def handle(self, *args, **options):
        if settings.ENVIRONMENT == "production":
            raise CommandError("Refused: this is the production server. Demo data is for the sandbox only.")
        try:
            people = load_demo_data()
        except DemoDataExists as error:
            raise CommandError(str(error)) from error
        self.stdout.write(self.style.SUCCESS("Demo data loaded. Log in as one of these (same demo password):"))
        for person in people.values():
            self.stdout.write(f"  {person.email}")
