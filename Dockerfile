# ==============================================================
# HerbiEstim API — Docker image for cloud deployment
# ==============================================================
# Build (CPU, 国内服务器推荐):
#   docker build -t herbiestim-api .
#
# Build (GPU + CUDA):
#   docker build --build-arg USE_GPU=true -t herbiestim-api:gpu .
#
# Build (自定义 pip 镜像源):
#   docker build --build-arg PIP_INDEX=https://repo.huaweicloud.com/repository/pypi/simple \
#                --build-arg PIP_TRUSTED_HOST=repo.huaweicloud.com \
#                -t herbiestim-api .
#
# Run (CPU):
#   docker run -p 8000:8000 herbiestim-api
#
# Run (GPU):
#   docker run --gpus all -p 8000:8000 -e HERBI_GPU_IDS=0 herbiestim-api:gpu
# ==============================================================

# --- Build arguments ---
# Set USE_GPU=true to install CUDA-enabled PyTorch (image will be larger)
ARG USE_GPU=false
# pip mirror for faster downloads inside China
ARG PIP_INDEX=https://repo.huaweicloud.com/repository/pypi/simple
ARG PIP_TRUSTED_HOST=repo.huaweicloud.com

FROM python:3.10-slim-bookworm

# Prevent interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies required by OpenCV
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Re-declare ARGs after FROM (they don't persist across stages)
ARG USE_GPU
ARG PIP_INDEX
ARG PIP_TRUSTED_HOST

# Make pip more robust on slow networks
ENV PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=5 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install numpy BEFORE PyTorch so torch can detect it at import time.
RUN pip install --no-cache-dir -i ${PIP_INDEX} --trusted-host ${PIP_TRUSTED_HOST} \
    "numpy>=1.21.0,<2.0.0"

# Install PyTorch (largest dependency, cached as separate layer)
# transformers >= 4.48 requires PyTorch >= 2.4 (needed by GroundingDINO's BertModel)
RUN if [ "$USE_GPU" = "true" ]; then \
        pip install --no-cache-dir \
            torch==2.4.1+cu118 torchvision==0.19.1+cu118 \
            --index-url https://download.pytorch.org/whl/cu118 ; \
    else \
        pip install --no-cache-dir \
            torch==2.4.1+cpu torchvision==0.19.1+cpu \
            --index-url https://download.pytorch.org/whl/cpu ; \
    fi

# Verify torch+numpy integration at build time (fail fast if broken)
RUN python -c "import numpy, torch; print(f'numpy {numpy.__version__}, torch {torch.__version__}'); \
    t = torch.from_numpy(numpy.array([1,2,3])); print('torch.from_numpy OK')"

# Copy dependency file and install remaining packages
COPY requirements-api.txt .
RUN pip install --no-cache-dir -i ${PIP_INDEX} --trusted-host ${PIP_TRUSTED_HOST} -r requirements-api.txt

# Copy project source code
COPY pix2pix/ ./pix2pix/
COPY utils/ ./utils/
COPY config/ ./config/
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY split.py modelpredict.py calculation.py synthetic.py modeltraining.py ./

# Install GroundingDINO (required for SAM segmentation)
COPY GroundingDINO/ ./GroundingDINO/
RUN pip install --no-cache-dir -e ./GroundingDINO

# Copy pre-trained model weights (pix2pix universal only, ~54MB)
# SAM weights (~3GB) are excluded by default — mount them via volume if needed
COPY model_saved/universal/ ./model_saved/universal/

# Environment defaults
ENV HERBI_MODEL_NAME=universal \
    HERBI_CHECKPOINTS_DIR=/app/model_saved \
    HERBI_GPU_IDS="" \
    HERBI_ENABLE_SAM=false \
    HERBI_API_KEY="" \
    HERBI_CORS_ORIGINS="*" \
    HERBI_RATE_LIMIT_PER_MINUTE=30 \
    HERBI_MAX_UPLOAD_SIZE_MB=20 \
    HERBI_IMAGE_MAX_DIM=1024 \
    HF_ENDPOINT=https://hf-mirror.com

# Expose API port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')" || exit 1

# Start the API server
CMD ["python", "-m", "uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
