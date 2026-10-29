FROM python:3.15-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=from=ghcr.io/astral-sh/uv:0.12.1,source=/uv,target=/usr/local/bin/uv \
    uv sync --frozen --no-dev --no-cache
COPY app.py services.py views.py LIBRARY.md ./
COPY static ./static
COPY artifacts ./artifacts
RUN useradd --uid 10001 --create-home nominal
USER nominal
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["/app/.venv/bin/uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
