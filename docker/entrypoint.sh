#!/bin/sh
set -e
python manage.py migrate --noinput
python manage.py collectstatic --noinput  # into the shared volume that Caddy serves
# Daily jobs (safe to repeat): tasks from repeating rules at 6:00, backup at 2:00
python manage.py setup_task_jobs
python manage.py setup_backup_jobs
exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --access-logfile -
