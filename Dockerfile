FROM ghcr.io/astral-sh/uv:0.12.13 AS uv
FROM python:3.12-slim
LABEL org.opencontainers.image.version="0.2.0"

COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock ./
COPY src/ src/
RUN uv sync --locked --no-dev --no-editable \
    && useradd --create-home --uid 10001 wrapper
USER wrapper
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]
CMD ["/app/.venv/bin/uvicorn", "craft_wrapper.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
