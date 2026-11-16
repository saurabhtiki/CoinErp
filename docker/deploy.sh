#!/bin/sh
# Update one server to the latest code. Run on the server, from anywhere:
#   sh docker/deploy.sh prod        (or: sandbox)
# Steps: pull code, build, restart (the web container migrates the database on start), check health.
set -e

SERVER="$1"
case "$SERVER" in
  prod|sandbox) ;;
  *) echo "Say which server: sh docker/deploy.sh prod   or   sh docker/deploy.sh sandbox"; exit 1 ;;
esac

cd "$(dirname "$0")/.."
[ -f ".env.$SERVER" ] || { echo "Missing .env.$SERVER. Copy .env.$SERVER.example and fill it in."; exit 1; }
PORT=$(grep '^WEB_PORT=' ".env.$SERVER" | cut -d= -f2)
PORT=${PORT:-8000}
COMPOSE="docker compose -p coinerp-$SERVER --env-file .env.$SERVER -f docker/compose.yml"

echo "1/4 Pulling the latest code..."
git pull --ff-only

echo "2/4 Taking a backup first (so you can go back)..."
if $COMPOSE ps --status running web | grep -q web; then
  $COMPOSE exec -T web python manage.py shell -c "from core.backups.services import start_backup, run_backup; run_backup(start_backup().pk)" \
    || { echo "Backup FAILED, so nothing was updated. Fix this first (or wait if a backup is running)."; exit 1; }
else
  echo "Server is not running yet, nothing to back up."
fi

echo "3/4 Building and restarting..."
$COMPOSE up -d --build

echo "4/4 Waiting for the health check on port $PORT..."
for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
  if curl -fsS "http://127.0.0.1:$PORT/healthz/" >/dev/null 2>&1; then
    echo "OK: coinerp-$SERVER is up."
    exit 0
  fi
  sleep 5
done
echo "NOT healthy after 60 seconds. See the logs:  $COMPOSE logs --tail 100 web"
exit 1
