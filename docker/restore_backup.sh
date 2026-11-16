#!/bin/sh
# Restore a backup zip into a server. Run on the SERVER, from the project folder. There is no button for this in the app.
#
#   PROJECT=coinerp-prod    ENV_FILE=.env.prod    sh docker/restore_backup.sh /path/to/backup-20261116-020000-7.zip
#   PROJECT=coinerp-sandbox ENV_FILE=.env.sandbox sh docker/restore_backup.sh /path/to/backup.zip
#
# WARNING: this OVERWRITES the database and all uploaded files of that server with the backup.
# Tip: restore a production backup into the SANDBOX first to check it, before ever touching production.
set -eu

ZIP_FILE="${1:-}"
PROJECT="${PROJECT:-coinerp-prod}"
ENV_FILE="${ENV_FILE:-.env.prod}"
COMPOSE="docker compose -p $PROJECT --env-file $ENV_FILE -f docker/compose.yml"
unset ENV_FILE  # compose reads its own ENV_FILE (../.env.prod) from the env file; ours would override it

if [ -z "$ZIP_FILE" ] || [ ! -f "$ZIP_FILE" ]; then
    echo "Usage: PROJECT=... ENV_FILE=... sh docker/restore_backup.sh <backup.zip>" >&2
    echo "Backup file not found: '$ZIP_FILE'" >&2
    exit 1
fi

echo "This will OVERWRITE the database and uploaded files of '$PROJECT' with:"
echo "  $ZIP_FILE"
printf "Type the project name (%s) to continue: " "$PROJECT"
read -r ANSWER
if [ "$ANSWER" != "$PROJECT" ]; then
    echo "Cancelled. Nothing was changed."
    exit 1
fi

ZIP_DIR="$(cd "$(dirname "$ZIP_FILE")" && pwd)"
ZIP_NAME="$(basename "$ZIP_FILE")"

echo "Stopping the app (the database stays up)..."
$COMPOSE up -d db
$COMPOSE stop worker web

echo "Restoring..."
$COMPOSE run --rm --no-deps --entrypoint sh -v "$ZIP_DIR:/restore:ro" web -c '
    set -eu
    rm -rf /tmp/restore && mkdir /tmp/restore
    python -m zipfile -e "/restore/'"$ZIP_NAME"'" /tmp/restore
    [ -f /tmp/restore/database.sql ] || { echo "No database.sql in this backup" >&2; exit 1; }
    PGPASSWORD="$POSTGRES_PASSWORD" psql -h db -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -q -f /tmp/restore/database.sql
    find /app/private_media -mindepth 1 -delete
    if [ -d /tmp/restore/private_media ]; then cp -a /tmp/restore/private_media/. /app/private_media/; fi
    echo "Database and files restored."
'

echo "Starting the app..."
$COMPOSE up -d
echo "Done. Open the site and check it."
