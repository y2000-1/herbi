"""
Cross-platform configuration via environment variables.
No system-specific dependencies — runs on Windows, Linux, macOS.
"""

import os
from pathlib import Path
from typing import List

# Project root — parent of this backend/ directory, where split.py, modelpredict.py, etc. live
BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent

# ===== Model settings =====
MODEL_NAME = os.getenv("HERBI_MODEL_NAME", "universal")
CHECKPOINTS_DIR = os.getenv("HERBI_CHECKPOINTS_DIR", str(PROJECT_ROOT / "model_saved"))

# GPU settings — comma-separated GPU ids, e.g. "0" or "0,1"; empty string or "-1" for CPU
_gpu_ids_str = os.getenv("HERBI_GPU_IDS", "")
if _gpu_ids_str in ("", "-1"):
    GPU_IDS: List[int] = []
else:
    GPU_IDS = [int(x.strip()) for x in _gpu_ids_str.split(",")]

# ===== SAM settings =====
# SAM requires model weights to be present in CHECKPOINTS_DIR (auto-detected from available files).
# Set HERBI_ENABLE_SAM=false to force-disable SAM even if weights are present.
ENABLE_SAM = os.getenv("HERBI_ENABLE_SAM", "true").lower() in ("true", "1", "yes")
SAM_DEVICE = os.getenv("HERBI_SAM_DEVICE", "cuda")
SAM_BOX_THRESHOLD = float(os.getenv("HERBI_SAM_BOX_THRESHOLD", "0.3"))
SAM_TEXT_THRESHOLD = float(os.getenv("HERBI_SAM_TEXT_THRESHOLD", "0.25"))

# ===== Image preprocessing =====
# Maximum image dimension before downscaling for OpenCV processing.
# High-res phone photos (12-48MP) can cause timeouts on CPU.
# Set to 0 to disable auto-downscale.
IMAGE_MAX_DIM = int(os.getenv("HERBI_IMAGE_MAX_DIM", "1024"))

# ===== API settings =====
MAX_UPLOAD_SIZE_MB = int(os.getenv("HERBI_MAX_UPLOAD_SIZE_MB", "20"))
REQUEST_TIMEOUT_SECONDS = int(os.getenv("HERBI_REQUEST_TIMEOUT_SECONDS", "120"))
API_KEY = os.getenv("HERBI_API_KEY", "")  # Empty = no auth required
CORS_ORIGINS = os.getenv("HERBI_CORS_ORIGINS", "*").split(",")
RATE_LIMIT_PER_MINUTE = int(os.getenv("HERBI_RATE_LIMIT_PER_MINUTE", "30"))

# Default DPI for scanned images
DEFAULT_DPI = int(os.getenv("HERBI_DEFAULT_DPI", "300"))

# ===== Mobile optimization =====
# Maximum dimension for base64-encoded images in response (reduces mobile data usage)
MOBILE_IMAGE_MAX_DIM = int(os.getenv("HERBI_MOBILE_IMAGE_MAX_DIM", "800"))
# JPEG quality for encoded images (0-100, lower = smaller but lower quality)
MOBILE_JPEG_QUALITY = int(os.getenv("HERBI_MOBILE_JPEG_QUALITY", "75"))
