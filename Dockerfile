# ---------------------------------------------------------------------------
# CaseForge AI - single container for Cloud Run
#   stage 1: build the React agent desktop
#   stage 2: FastAPI backend that also serves the built UI
# ---------------------------------------------------------------------------
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PORT=8080 STATIC_DIR=/app/static
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install -r requirements.txt
COPY backend/ ./
COPY --from=web /web/dist /app/static
RUN useradd -u 10001 -m caseforge && chown -R caseforge /app
USER caseforge
EXPOSE 8080
# --proxy-headers: Cloud Run terminates TLS; ws ping keeps Twilio/desktop sockets alive
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips="*" --ws-ping-interval 20
