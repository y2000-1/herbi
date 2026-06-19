"""
HerbiEstim Cross-Platform API — FastAPI application.

Provides RESTful endpoints for leaf herbivore damage estimation.
Compatible with Windows, Linux, macOS servers.
Clients: desktop browsers, mobile browsers (Android, iOS),
         WeChat in-app browser.

100% API-compatible with the original api/app.py routes and response schemas.
"""

import logging
import sys
import os
import io

import cv2
import numpy as np

# ── Path setup: ensure project root and pix2pix are importable ──────────
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
_pix2pix_path = os.path.join(_project_root, 'pix2pix')
if _pix2pix_path not in sys.path:
    sys.path.insert(0, _pix2pix_path)

try:
    import torch
    _torch_available = True
except ImportError:
    torch = None  # type: ignore
    _torch_available = False

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from backend.config import (
    MODEL_NAME, CHECKPOINTS_DIR, GPU_IDS,
    ENABLE_SAM, SAM_DEVICE, SAM_BOX_THRESHOLD, SAM_TEXT_THRESHOLD,
    MAX_UPLOAD_SIZE_MB, CORS_ORIGINS, DEFAULT_DPI,
    MOBILE_IMAGE_MAX_DIM, MOBILE_JPEG_QUALITY, IMAGE_MAX_DIM,
)
from backend.schemas import AnalyzeResponse, HealthResponse, ErrorResponse
from backend.middleware import APIKeyMiddleware, RateLimitMiddleware
from backend.pipeline import HerbiEstimPipeline

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("herbiestim.api")

# ===== Application =====
app = FastAPI(
    title="HerbiEstim API",
    description="Cross-platform leaf herbivore damage estimation service using pix2pix GAN. "
                "Upload a leaf image and receive damage analysis results. "
                "Compatible with desktop and mobile browsers including WeChat in-app browser.",
    version="2.0.0",
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

# Relaxed content types for mobile browser compatibility
# Some mobile browsers and WeChat send non-standard or missing content-type headers
ALLOWED_CONTENT_TYPES = {
    "image/jpeg", "image/png", "image/tiff",
    "image/jpg", "image/bmp", "image/webp",
    # Mobile/WeChat may send these variants
    "application/octet-stream", "multipart/form-data",
    "image/*",
}

# File extensions that we can decode (fallback when content-type is missing/unreliable)
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.tiff', '.tif', '.bmp', '.webp'}


def _validate_image_bytes(image_bytes: bytes, filename: str = "") -> None:
    """
    Validate image bytes. More lenient than content-type checking —
    attempts to decode the image to confirm it's a valid image format.
    Mobile browsers sometimes send non-standard content types.
    """
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
        # Check extension as last resort
        _, ext = os.path.splitext(filename.lower())
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported image format. Supported formats: {', '.join(ALLOWED_EXTENSIONS)}",
            )
        raise HTTPException(
            status_code=400,
            detail="Could not decode image. Please upload a valid JPEG, PNG, TIFF, BMP, or WebP image.",
        )


def _correct_exif_orientation(image_bytes: bytes) -> bytes:
    """
    Auto-correct EXIF orientation in JPEG images (common iPhone/iOS issue).
    Non-JPEG images are returned unchanged.
    Returns the (possibly rotated) image bytes.
    """
    import io as _io
    try:
        from PIL import Image, ExifTags
    except ImportError:
        logger.warning("Pillow not installed — skipping EXIF orientation correction.")
        return image_bytes

    try:
        img_pil = Image.open(_io.BytesIO(image_bytes))

        # Get EXIF orientation tag
        exif = img_pil.getexif() if hasattr(img_pil, 'getexif') else None
        if exif is None:
            return image_bytes

        orientation = exif.get(0x0112, 1)  # 0x0112 = Orientation

        if orientation == 1:
            return image_bytes  # Normal — no correction needed

        # Apply rotation/flip based on EXIF orientation
        rotate_map = {3: 180, 6: 270, 8: 90}
        flip_map = {2: Image.FLIP_LEFT_RIGHT, 4: Image.FLIP_TOP_BOTTOM,
                    5: Image.FLIP_LEFT_RIGHT, 7: Image.FLIP_LEFT_RIGHT}

        if orientation in rotate_map:
            img_pil = img_pil.rotate(rotate_map[orientation], expand=True)
        if orientation in flip_map:
            img_pil = img_pil.transpose(flip_map[orientation])

        # Re-encode to JPEG bytes
        buf = _io.BytesIO()
        img_pil = img_pil.convert('RGB')  # Remove alpha channel if present
        img_pil.save(buf, format='JPEG', quality=92)
        logger.info(f"EXIF orientation corrected: {orientation} -> 1")
        return buf.getvalue()
    except Exception as e:
        logger.debug(f"EXIF correction skipped (non-critical): {e}")
        return image_bytes


@app.on_event("startup")
async def startup_event():
    """Load models at application startup."""
    global pipeline
    logger.info("=" * 60)
    logger.info("HerbiEstim Cross-Platform API starting up...")
    logger.info(f"  Model: {MODEL_NAME}")
    logger.info(f"  Checkpoints: {CHECKPOINTS_DIR}")
    logger.info(f"  GPU IDs: {GPU_IDS}")
    logger.info(f"  SAM enabled: {ENABLE_SAM}")
    logger.info(f"  Platform: {sys.platform}")
    logger.info(f"  Python: {sys.version}")

    # ── GPU / CUDA diagnostic ──
    if _torch_available:
        logger.info(f"  PyTorch version: {torch.__version__}")
        cuda_available = torch.cuda.is_available()
        logger.info(f"  CUDA available: {cuda_available}")
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
    else:
        logger.warning("  PyTorch NOT installed — pix2pix model will not load!")

    logger.info(f"  Mobile max dim: {MOBILE_IMAGE_MAX_DIM}")
    logger.info(f"  Image max dim: {IMAGE_MAX_DIM}")
    logger.info("=" * 60)

    pipeline = HerbiEstimPipeline(
        model_name=MODEL_NAME,
        checkpoints_dir=CHECKPOINTS_DIR,
        gpu_ids=GPU_IDS,
        enable_sam=ENABLE_SAM,
        sam_device=SAM_DEVICE,
        sam_box_threshold=SAM_BOX_THRESHOLD,
        sam_text_threshold=SAM_TEXT_THRESHOLD,
        mobile_max_dim=MOBILE_IMAGE_MAX_DIM,
        mobile_jpeg_quality=MOBILE_JPEG_QUALITY,
        image_max_dim=IMAGE_MAX_DIM,
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
        gpu_available=_torch_available and torch.cuda.is_available(),
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
    image: UploadFile = File(..., description="Leaf image file (jpg/png/tiff/bmp/webp)"),
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

    **Cross-platform compatible** — works with desktop browsers, mobile browsers
    (Android, iOS), and WeChat in-app browser.
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
    filename = image.filename or ""
    _validate_image_bytes(image_bytes, filename)

    # Auto-correct EXIF orientation (common issue with iPhone/iOS photos)
    logger.info(f"Processing image: {filename}, size: {len(image_bytes)} bytes")
    image_bytes = _correct_exif_orientation(image_bytes)

    # Validate SAM request
    if use_sam and not pipeline.sam_loaded:
        if not ENABLE_SAM:
            raise HTTPException(
                status_code=400,
                detail="SAM mode not enabled on this server. Set HERBI_ENABLE_SAM=true to enable.",
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


# ===== Static file serving (frontend) =====
_frontend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'frontend')
_frontend_dir = os.path.abspath(_frontend_dir)

if os.path.isdir(_frontend_dir):
    @app.get("/", response_class=HTMLResponse, tags=["Frontend"])
    async def serve_frontend():
        """Serve the cross-platform web frontend."""
        index_path = os.path.join(_frontend_dir, 'index.html')
        if os.path.exists(index_path):
            with open(index_path, 'r', encoding='utf-8') as f:
                return HTMLResponse(content=f.read())
        return HTMLResponse(content="<h1>Frontend not found</h1>", status_code=404)

    # Mount static files (CSS, JS, images)
    app.mount("/static", StaticFiles(directory=_frontend_dir), name="static")


# ===== Run with uvicorn =====
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.app:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        workers=1,  # Single worker to share GPU model in memory
    )
