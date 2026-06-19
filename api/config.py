"""API configuration via environment variables."""

import os
from pathlib import Path

# Project root (parent of this api/ directory)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Model settings
MODEL_NAME = os.getenv("HERBI_MODEL_NAME", "universal")
CHECKPOINTS_DIR = os.getenv("HERBI_CHECKPOINTS_DIR", str(PROJECT_ROOT / "model_saved"))

# GPU settings — comma-separated GPU ids, e.g. "0" or "0,1"; empty string or "-1" for CPU
_gpu_ids_str = os.getenv("HERBI_GPU_IDS", "")
from typing import List

if _gpu_ids_str in ("", "-1"):
    GPU_IDS: List[int] = []
else:
    GPU_IDS = [int(x.strip()) for x in _gpu_ids_str.split(",")]

# SAM settings
# SAM requires model weights to be present in CHECKPOINTS_DIR (auto-detected from available files).
# Set HERBI_ENABLE_SAM=false to force-disable SAM even if weights are present.
ENABLE_SAM = os.getenv("HERBI_ENABLE_SAM", "true").lower() in ("true", "1", "yes")
SAM_DEVICE = os.getenv("HERBI_SAM_DEVICE", "cuda")
SAM_BOX_THRESHOLD = float(os.getenv("HERBI_SAM_BOX_THRESHOLD", "0.3"))
SAM_TEXT_THRESHOLD = float(os.getenv("HERBI_SAM_TEXT_THRESHOLD", "0.25"))

# API settings
MAX_UPLOAD_SIZE_MB = int(os.getenv("HERBI_MAX_UPLOAD_SIZE_MB", "20"))
REQUEST_TIMEOUT_SECONDS = int(os.getenv("HERBI_REQUEST_TIMEOUT_SECONDS", "60"))
API_KEY = os.getenv("HERBI_API_KEY", "")  # Empty = no auth required
CORS_ORIGINS = os.getenv("HERBI_CORS_ORIGINS", "*").split(",")
RATE_LIMIT_PER_MINUTE = int(os.getenv("HERBI_RATE_LIMIT_PER_MINUTE", "30"))

# Default DPI for scanned images
DEFAULT_DPI = int(os.getenv("HERBI_DEFAULT_DPI", "300"))
