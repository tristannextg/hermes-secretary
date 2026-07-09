FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
RUN useradd --create-home --uid 1000 appuser

COPY services/obsidian_ops/pyproject.toml /app/services/obsidian_ops/pyproject.toml
COPY services/obsidian_ops/src /app/services/obsidian_ops/src
RUN pip install --no-cache-dir /app/services/obsidian_ops

COPY templates /app/templates
COPY config /app/config

USER appuser
CMD ["obsidian-ops", "serve"]
