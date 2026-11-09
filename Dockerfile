# MeetingOS: two-stage build. The web UI is compiled with Bun, then served by
# the FastAPI process from a slim Python image. No GPU stack: speech and
# language work goes to the configured hosted providers.

FROM oven/bun:1 AS web
WORKDIR /build
COPY package.json bun.lock ./
COPY web/package.json ./web/
RUN bun install --frozen-lockfile
COPY web/ ./web/
RUN cd web && bun run build

FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r meetingos && useradd -r -g meetingos -m meetingos
WORKDIR /app
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY --chown=meetingos:meetingos backend/ /app/backend/
COPY --from=web --chown=meetingos:meetingos /build/web/dist /app/frontend/
RUN mkdir -p /app/data && chown meetingos:meetingos /app/data
USER meetingos

EXPOSE 8470
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=20s \
    CMD curl -fs http://localhost:8470/health || exit 1

# 0.0.0.0 is the container's own interface; compose publishes it on the host's
# loopback only. The server refuses to start on a non-loopback bind without
# MEETINGOS_API_KEY, so a container is never an open endpoint.
CMD ["python", "-m", "backend.main", "--host", "0.0.0.0", "--port", "8470", "--data-dir", "/app/data"]
