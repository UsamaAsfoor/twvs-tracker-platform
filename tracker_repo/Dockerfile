FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TWVS_REPO_ROOT=/app \
    TWVS_DATA_DIR=/data \
    TWVS_SCRIPTS_DIR=/app/scripts \
    TWVS_SESSION_DIR=/data/browser_session \
    TWVS_DOWNLOADS_DIR=/data/downloads_temp \
    PORT=8000

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY . .

RUN chmod +x /app/scripts/docker-entrypoint.sh

EXPOSE 8000

CMD ["/app/scripts/docker-entrypoint.sh"]
