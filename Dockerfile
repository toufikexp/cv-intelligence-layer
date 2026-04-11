FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
  && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /app/pyproject.toml
COPY app/__init__.py /app/app/__init__.py

# Install dependencies (cache layer — only re-runs when pyproject.toml changes)
RUN pip install --no-cache-dir -U pip && pip install --no-cache-dir .

# Copy full application code and re-install package (no-deps: deps already cached)
COPY app /app/app
COPY prompts /app/prompts
COPY schemas /app/schemas
COPY alembic /app/alembic
COPY alembic.ini /app/alembic.ini
RUN pip install --no-cache-dir --no-deps .

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
