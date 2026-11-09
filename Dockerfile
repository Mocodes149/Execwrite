FROM python:3.13-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev

COPY execwrite ./execwrite

RUN useradd --create-home app
USER app

EXPOSE 8000

# Les hébergeurs comme Render et Railway imposent leur port via $PORT.
CMD ["sh", "-c", "exec .venv/bin/uvicorn execwrite.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
