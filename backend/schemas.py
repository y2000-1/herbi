"""
Pydantic models for API request/response validation.
100% compatible with the original api/schemas.py response structure.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class LeafResult(BaseModel):
    """Analysis result for a single leaf."""
    leaf_id: int = Field(..., description="Leaf index (0-based)")
    leaf_area_cm2: Optional[float] = Field(None, description="Actual leaf area in cm²")
    intact_area_cm2: Optional[float] = Field(None, description="Reconstructed intact leaf area in cm²")
    damage_pct: float = Field(..., ge=0.0, le=1.0, description="Damage percentage (0.0-1.0)")
    standardized_image: Optional[str] = Field(None, description="Base64-encoded standardized leaf image (PNG)")
    reconstructed_image: Optional[str] = Field(None, description="Base64-encoded reconstructed intact leaf image (PNG)")


class AnalysisSummary(BaseModel):
    """Aggregated summary for all leaves in an image."""
    num_leaves: int = Field(..., description="Number of detected leaves")
    total_leaf_area_cm2: Optional[float] = Field(None, description="Total actual leaf area in cm²")
    total_intact_area_cm2: Optional[float] = Field(None, description="Total reconstructed intact area in cm²")
    avg_damage_pct: float = Field(..., description="Average damage percentage across all leaves")


class DebugLeafDetail(BaseModel):
    """Debug images for a single leaf's processing pipeline."""
    leaf_id: int = Field(..., description="Leaf index (0-based)")
    standardized: Optional[str] = Field(None, description="Base64 standardized 256x256 leaf image")
    real: Optional[str] = Field(None, description="Base64 pix2pix input (real)")
    fake: Optional[str] = Field(None, description="Base64 pix2pix output (reconstructed)")
    real_mask: Optional[str] = Field(None, description="Base64 binary mask of real leaf")
    fake_mask: Optional[str] = Field(None, description="Base64 binary mask of reconstructed leaf")


class DebugInfo(BaseModel):
    """All debug visualization data from a pipeline run."""
    original_image: Optional[str] = Field(None, description="Base64 uploaded original image")
    detection_boxes: Optional[str] = Field(None, description="Base64 GroundingDINO detections visualization")
    sam_masks: Optional[str] = Field(None, description="Base64 SAM raw masks visualization")
    filtered_masks: Optional[str] = Field(None, description="Base64 filtered masks visualization")
    leaves: List[DebugLeafDetail] = Field(default_factory=list, description="Per-leaf debug images")


class AnalyzeResponse(BaseModel):
    """Response from the /api/v1/analyze endpoint."""
    leaves: List[LeafResult] = Field(..., description="Per-leaf analysis results")
    summary: AnalysisSummary = Field(..., description="Aggregated summary")
    debug: Optional[DebugInfo] = Field(None, description="Debug visualizations (only when debug=True)")


class HealthResponse(BaseModel):
    """Response from the /api/v1/health endpoint."""
    status: str = Field(..., description="Service status: 'healthy' or 'degraded'")
    pix2pix_loaded: bool = Field(..., description="Whether pix2pix generator model is loaded")
    sam_loaded: bool = Field(..., description="Whether SAM model is loaded")
    gpu_available: bool = Field(..., description="Whether GPU/CUDA is available")


class ErrorResponse(BaseModel):
    """Standard error response."""
    error: str = Field(..., description="Error type")
    detail: str = Field(..., description="Human-readable error description")
