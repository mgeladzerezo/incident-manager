# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install -r requirements.txt

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH="/opt/venv/bin:$PATH"
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home app
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY alembic.ini .
COPY migrations migrations
COPY app app
USER 10001
EXPOSE 8000
# The same image runs the API (default), the worker (`python -m app.worker`) and
# migrations (`alembic upgrade head`).
CMD ["uvicorn", "app.asgi:app", "--host", "0.0.0.0", "--port", "8000"]
