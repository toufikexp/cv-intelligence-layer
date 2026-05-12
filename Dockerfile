# Use NVIDIA CUDA 12.8 runtime base image. The image sets CUDA_VERSION=12.8.0
# (valid semver) internally, which is what nvidia-container-toolkit's prestart
# hook expects at runtime. CUDA 12.8 + matching PyTorch wheels are required to
# support Blackwell (sm_120) GPUs such as the RTX 50-series.
FROM nvidia/cuda:12.8.0-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

WORKDIR /app
ENV PYTHONPATH=/app

# Install Python 3.11 (Ubuntu 22.04 ships with 3.10) + the system libs
# EasyOCR/OpenCV need at runtime (libgl1, libglib2.0-0).
RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        python3.11 \
        python3.11-dev \
        python3.11-venv \
        build-essential \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Use a venv so we get a modern pip without fighting Ubuntu's system Python.
RUN python3.11 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install PyTorch with CUDA 12.8 wheels (matches the base image runtime, ships
# Blackwell/sm_120 kernels) BEFORE the rest of the project so easyocr's
# transitive torch dep is satisfied without being overridden.
COPY pyproject.toml /app/pyproject.toml
COPY app/__init__.py /app/app/__init__.py
RUN pip install --no-cache-dir -U pip \
    && pip install --no-cache-dir torch torchvision \
        --index-url https://download.pytorch.org/whl/cu128 \
    && pip install --no-cache-dir .

# Pre-download EasyOCR (fr+en) model weights at build time. The default
# cache is /root/.EasyOCR/model/. Removes cold-start cost on first OCR call
# and removes any runtime network dependency on the EasyOCR CDN. gpu=False
# is fine — we are only downloading the weight files, not running inference.
RUN python -c "import easyocr; easyocr.Reader(['fr', 'en'], gpu=False, verbose=False)"

# Application code
COPY app /app/app
COPY prompts /app/prompts
COPY schemas /app/schemas
COPY alembic /app/alembic
COPY alembic.ini /app/alembic.ini

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
