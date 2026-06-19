"""
HerbiEstim Cloud API — FastAPI application.

Provides RESTful endpoints for leaf herbivore damage estimation.
Designed to be called from cross-platform applications (web, mobile, desktop).
"""

import logging
import sys
import os
import io

import cv2
import numpy as np

# Ensure project root is in path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
if os.path.join(_project_root, 'pix2pix') not in sys.path:
    sys.path.insert(0, os.path.join(_project_root, 'pix2pix'))

import torch
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from api.config import (
    MODEL_NAME, CHECKPOINTS_DIR, GPU_IDS,
    ENABLE_SAM, SAM_DEVICE, SAM_BOX_THRESHOLD, SAM_TEXT_THRESHOLD,
    MAX_UPLOAD_SIZE_MB, CORS_ORIGINS, DEFAULT_DPI,
)
from api.schemas import AnalyzeResponse, HealthResponse, ErrorResponse
from api.middleware import APIKeyMiddleware, RateLimitMiddleware
from api.pipeline import HerbiEstimPipeline

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("herbiestim.api")

# ===== Application =====
app = FastAPI(
    title="HerbiEstim API",
    description="Leaf herbivore damage estimation service using pix2pix GAN. "
                "Upload a leaf image and receive damage analysis results.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ===== Middleware =====
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(APIKeyMiddleware)
app.add_middleware(RateLimitMiddleware)

# ===== Pipeline (singleton) =====
from typing import Optional as _Optional

pipeline: _Optional[HerbiEstimPipeline] = None

ALLOWED_CONTENT_TYPES = {
    "image/jpeg", "image/png", "image/tiff",
    "image/jpg", "image/bmp", "image/webp",
    # Mobile/WeChat may send these variants
    "application/octet-stream", "multipart/form-data",
    "image/*",
}

# File extensions that we can decode (fallback when content-type is missing/unreliable)
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.tiff', '.tif', '.bmp', '.webp'}


@app.on_event("startup")
async def startup_event():
    """Load models at application startup."""
    global pipeline
    logger.info("=" * 60)
    logger.info("HerbiEstim API starting up...")
    logger.info(f"  Model: {MODEL_NAME}")
    logger.info(f"  Checkpoints: {CHECKPOINTS_DIR}")
    logger.info(f"  GPU IDs: {GPU_IDS}")
    logger.info(f"  SAM enabled: {ENABLE_SAM}")
    logger.info(f"  Platform: {sys.platform}")
    logger.info(f"  Python: {sys.version}")
    logger.info(f"  PyTorch version: {torch.__version__}")
    cuda_available = torch.cuda.is_available()
    logger.info(f"  CUDA available: {cuda_available}")

    # ── GPU diagnostic ──
    if cuda_available:
        gpu_count = torch.cuda.device_count()
        logger.info(f"  GPU count: {gpu_count}")
        for i in range(gpu_count):
            gpu_name = torch.cuda.get_device_name(i)
            gpu_mem_total = torch.cuda.get_device_properties(i).total_mem / (1024**3)
            logger.info(f"    GPU[{i}]: {gpu_name} ({gpu_mem_total:.1f} GB VRAM)")
    else:
        logger.warning("  CUDA NOT available — inference will run on CPU (very slow).")
        logger.warning("  Verify: NVIDIA driver, CUDA toolkit, and PyTorch CUDA build are installed.")
    logger.info("=" * 60)

    pipeline = HerbiEstimPipeline(
        model_name=MODEL_NAME,
        checkpoints_dir=CHECKPOINTS_DIR,
        gpu_ids=GPU_IDS,
        enable_sam=ENABLE_SAM,
        sam_device=SAM_DEVICE,
        sam_box_threshold=SAM_BOX_THRESHOLD,
        sam_text_threshold=SAM_TEXT_THRESHOLD,
    )
    try:
        pipeline.load_models()
        logger.info("Pipeline ready. Accepting requests.")
    except Exception as e:
        logger.error(f"Failed to load models: {e}")
        logger.warning("Server will start in degraded mode. Check model files and configuration.")
        # Don't crash — allow health checks to report status


@app.get("/api/v1/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """Check service health and model loading status."""
    return HealthResponse(
        status="healthy" if (pipeline and pipeline.pix2pix_loaded) else "degraded",
        pix2pix_loaded=pipeline.pix2pix_loaded if pipeline else False,
        sam_loaded=pipeline.sam_loaded if pipeline else False,
        gpu_available=torch.cuda.is_available(),
    )


@app.post("/api/v1/analyze",
          response_model=AnalyzeResponse,
          responses={
              400: {"model": ErrorResponse, "description": "Invalid input"},
              413: {"model": ErrorResponse, "description": "File too large"},
              500: {"model": ErrorResponse, "description": "Internal error"},
          },
          tags=["Analysis"])
async def analyze_leaf(
    image: UploadFile = File(..., description="Leaf image file (jpg/png/tiff)"),
    dpi: int = Form(default=DEFAULT_DPI, ge=72, le=2400,
                    description="Image DPI for area calculation"),
    use_sam: bool = Form(default=False,
                         description="Use Grounded SAM for segmentation (requires GPU)"),
    return_images: bool = Form(default=True,
                               description="Include base64-encoded images in response"),
    is_scanned: bool = Form(default=True,
                            description="Whether the image is from a scanner (affects area units)"),
    debug: bool = Form(default=False,
                       description="Enable debug mode to return intermediate pipeline images"),
):
    """
    Analyze a leaf image for herbivore damage.

    Upload a leaf image and receive per-leaf damage metrics including
    leaf area, intact area, and damage percentage.

    **For mobile/web integration**: POST multipart/form-data with the image file.
    """
    global pipeline

    if pipeline is None or not pipeline.pix2pix_loaded:
        raise HTTPException(
            status_code=503,
            detail="Model not loaded. Service is starting up, please retry.",
        )

    # Read image bytes
    image_bytes = await image.read()

    # Validate (lenient for mobile browsers)
    import numpy as np
    if len(image_bytes) == 0:
        raise HTTPException(status_code=400, detail="Empty file uploaded.")

    if len(image_bytes) > MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size: {MAX_UPLOAD_SIZE_MB} MB.",
        )

    # Try to decode — this catches most invalid uploads regardless of MIME type
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        _, ext = os.path.splitext((image.filename or '').lower())
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported image format. Supported formats: {', '.join(ALLOWED_EXTENSIONS)}",
            )
        raise HTTPException(
            status_code=400,
            detail="Could not decode image. Please upload a valid JPEG, PNG, TIFF, BMP, or WebP image.",
        )

    # Auto-correct EXIF orientation (common issue with iPhone/iOS photos)
    logger.info(f"Processing image: {image.filename}, size: {len(image_bytes)} bytes")
    try:
        import io as _io
        from PIL import Image
        img_pil = Image.open(_io.BytesIO(image_bytes))
        exif = img_pil.getexif() if hasattr(img_pil, 'getexif') else None
        if exif:
            orientation = exif.get(0x0112, 1)
            if orientation != 1:
                rotate_map = {3: 180, 6: 270, 8: 90}
                if orientation in rotate_map:
                    img_pil = img_pil.rotate(rotate_map[orientation], expand=True)
                if orientation in (2, 5, 7):
                    img_pil = img_pil.transpose(Image.FLIP_LEFT_RIGHT)
                buf = _io.BytesIO()
                img_pil = img_pil.convert('RGB')
                img_pil.save(buf, format='JPEG', quality=92)
                image_bytes = buf.getvalue()
                logger.info(f"EXIF orientation corrected: {orientation} -> 1")
    except Exception:
        pass  # Non-critical, continue with original bytes

    # Validate SAM request
    if use_sam and not pipeline.sam_loaded:
        if not ENABLE_SAM:
            raise HTTPException(
                status_code=400,
                detail="SAM mode not enabled on this server. "
                       "Set HERBI_ENABLE_SAM=true to enable.",
            )
        raise HTTPException(
            status_code=503,
            detail="SAM model failed to load. Use use_sam=false for OpenCV mode.",
        )

    # Run analysis
    try:
        result = pipeline.analyze(
            image_bytes=image_bytes,
            dpi=dpi,
            use_sam=use_sam,
            return_images=return_images,
            is_scanned=is_scanned,
            debug=debug,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Analysis failed")
        raise HTTPException(
            status_code=500,
            detail=f"Analysis failed: {str(e)}",
        )

    return result


# ===== Run with uvicorn =====
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.app:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        workers=1,  # Single worker to share GPU model in memory
    )
