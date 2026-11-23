# نسخة الخادم من «مرصد التحقق»: الواجهة مبنية داخل الصورة، والخادم والعامل من الصورة نفسها.
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    MARSAD_HOME=/app MARSAD_MODE=server \
    MARSAD_DATA_DIR=/data MARSAD_BACKUP_DIR=/backups MARSAD_CONFIG_DIR=/config
WORKDIR /app
COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/marsad backend/marsad
RUN pip install --no-cache-dir ./backend && rm -rf backend/build backend/*.egg-info
COPY --from=web /web/dist frontend/dist
ARG MARSAD_VERSION=dev
ENV MARSAD_VERSION=${MARSAD_VERSION}
RUN useradd --system --uid 10001 marsad && mkdir -p /data /backups /config \
    && chown marsad /data /backups /config
USER marsad
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["uvicorn", "marsad.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
