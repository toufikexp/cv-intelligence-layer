FROM python:3.11-slim

WORKDIR /app
ENV PYTHONPATH=/app

# Set CUDA_VERSION=cu121 (or cu118) at build time to get CUDA-enabled PyTorch.
# Default "cpu" keeps the image small and works without a GPU.
ARG CUDA_VERSION=cpu

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
  && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /app/pyproject.toml
COPY app/__init__.py /app/app/__init__.py

# Install PyTorch first (CPU or CUDA wheel) so easyocr's transitive torch dep
# is satisfied without being overridden. Then install the rest of the project.
RUN pip install --no-cache-dir -U pip && \
    pip install --no-cache-dir torch torchvision \
        --index-url "https://download.pytorch.org/whl/${CUDA_VERSION}" && \
    pip install --no-cache-dir .

COPY app /app/app
COPY prompts /app/prompts
COPY schemas /app/schemas
COPY alembic /app/alembic
COPY alembic.ini /app/alembic.ini

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
