#!/usr/bin/env python
"""Django command-line entry point."""
import os
import sys
from pathlib import Path

# Some shells set PYTHONSAFEPATH, which stops Python finding this project's folders.
PROJECT_DIR = str(Path(__file__).resolve().parent)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
