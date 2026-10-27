FROM python:3.12.7-slim AS builder
RUN pip install --no-cache-dir --no-deps uv==0.12.13
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-cache

FROM python:3.12.7-slim
RUN useradd --create-home --uid 10001 esc
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./alembic.ini
RUN chmod -R a+rX /app/app /app/alembic /app/alembic.ini
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER esc
EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
