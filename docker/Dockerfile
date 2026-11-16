FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings.prod

COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv

WORKDIR /app

# git: needed to install django-datatable from GitHub
# postgresql-client-17 (from the official Postgres repo): pg_dump/psql for backups, same version as the db container
RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates gnupg \
 && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/keyrings/pgdg.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/pgdg.gpg] http://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update && apt-get install -y --no-install-recommends postgresql-client-17 \
 && rm -rf /var/lib/apt/lists/*

# Install packages first (cached layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .

# Build Tailwind/DaisyUI CSS and collect static files (dummy key only for the build step)
RUN SECRET_KEY=build-only python manage.py tailwind build \
 && SECRET_KEY=build-only python manage.py collectstatic --noinput

RUN useradd --create-home erp && mkdir -p /app/private_media /app/backups && chown -R erp /app/private_media /app/backups /app/staticfiles
USER erp

EXPOSE 8000
CMD ["sh", "docker/entrypoint.sh"]
