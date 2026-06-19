"""
Configuration for Grounded SAM (GroundingDINO + SAM) leaf segmentation.
"""

import os

# ==================== Paths ====================
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(PROJECT_ROOT, "model_saved")

# ==================== SAM Model ====================
# Auto-detect SAM model from available weights in model_saved/
# Priority: vit_h > vit_l > vit_b
_available_sam_models = {
    "vit_h": "sam_vit_h_4b8939.pth",
    "vit_l": "sam_vit_l_0b3195.pth",
    "vit_b": "sam_vit_b_01ec64.pth",
}
SAM_MODEL_TYPE = None
SAM_CHECKPOINT_NAME = None
for _model_type, _fname in _available_sam_models.items():
    _candidate_path = os.path.join(MODEL_DIR, _fname)
    if os.path.isfile(_candidate_path):
        SAM_MODEL_TYPE = _model_type
        SAM_CHECKPOINT_NAME = _fname
        break

if SAM_MODEL_TYPE is None:
    # Fallback to default (will trigger auto-download if URL is accessible)
    SAM_MODEL_TYPE = "vit_b"
    SAM_CHECKPOINT_NAME = "sam_vit_b_01ec64.pth"

SAM_CHECKPOINT_PATH = os.path.join(MODEL_DIR, SAM_CHECKPOINT_NAME)
SAM_CHECKPOINT_URL = {
    "vit_h": "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth",
    "vit_l": "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_l_0b3195.pth",
    "vit_b": "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth",
}.get(SAM_MODEL_TYPE, "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth")

# ==================== GroundingDINO Model ====================
GDINO_CONFIG_PATH = os.path.join(
    PROJECT_ROOT, "GroundingDINO", "groundingdino", "config", "GroundingDINO_SwinT_OGC.py"
)
GDINO_CHECKPOINT_NAME = "groundingdino_swint_ogc.pth"
GDINO_CHECKPOINT_PATH = os.path.join(MODEL_DIR, GDINO_CHECKPOINT_NAME)
GDINO_CHECKPOINT_URL = (
    "https://github.com/IDEA-Research/GroundingDINO/releases/download/v0.1.0-alpha/groundingdino_swint_ogc.pth"
)

# ==================== Detection Parameters ====================
TEXT_PROMPT = "leaf"
BOX_THRESHOLD = 0.3
TEXT_THRESHOLD = 0.25

# ==================== Mask Filtering ====================
# Minimum mask area as a fraction of total image area (filter out tiny fragments)
MIN_MASK_AREA_RATIO = 0.005
# Maximum IoU between two masks before the lower-confidence one is removed
MASK_IOU_THRESHOLD = 0.5
