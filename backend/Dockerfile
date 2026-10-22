# PerkFlex API (FastAPI). Build with the backend/ folder as the context:
#   docker build -t perkflex-api backend
#
# The app resolves its paths from the file layout (<root>/backend/app and
# <root>/backend/db), so that layout is kept under /srv.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/backend

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app ./app
# SQL migrations and the RDS CA bundle. demo-credentials.local.md is excluded by .dockerignore.
COPY db/sql ./db/sql
COPY db/certs ./db/certs

RUN useradd --system --no-create-home --uid 10001 perkflex
USER perkflex

# Configuration comes from environment variables (no .env is baked into the image).
ENV ENVIRONMENT=production \
    DEMO_MODE=false

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=4).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
