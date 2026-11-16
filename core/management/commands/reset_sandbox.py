import logging
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from config.demo_data import load_demo_data

logger = logging.getLogger(__name__)


def clear_folder(folder):
    """Delete everything inside a folder (not the folder itself)."""
    folder = Path(folder)
    if not folder.is_dir():
        return
    for item in folder.iterdir():
        shutil.rmtree(item) if item.is_dir() else item.unlink()


class Command(BaseCommand):
    help = "Sandbox only: wipe ALL data and uploaded files, then load fresh demo data."

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true", help="Confirm that everything may be deleted.")

    def handle(self, *args, **options):
        if not settings.IS_SANDBOX:
            logger.error("reset_sandbox refused: ENVIRONMENT is %s, not sandbox", settings.ENVIRONMENT)
            raise CommandError(
                f"Refused: ENVIRONMENT is '{settings.ENVIRONMENT}'. reset_sandbox runs only on the sandbox."
            )
        if not options["yes"]:
            raise CommandError("This deletes ALL sandbox data and uploaded files. Run again with --yes to confirm.")
        if not settings.DEMO_PASSWORD:
            raise CommandError("Set DEMO_PASSWORD in the sandbox .env first. The demo users must not use a password from the source code.")
        call_command("flush", interactive=False, verbosity=0)
        clear_folder(settings.MEDIA_ROOT)
        clear_folder(settings.BACKUP_ROOT)  # the backup records were just flushed
        call_command("setup_task_jobs", verbosity=0)  # flush also deleted the daily jobs
        call_command("setup_backup_jobs", verbosity=0)
        load_demo_data()
        self.stdout.write(self.style.SUCCESS("Sandbox reset: old data wiped, fresh demo data loaded."))
