"""
Unified inference pipeline for HerbiEstim.

Orchestrates: image standardization → pix2pix prediction → damage calculation.
Models are loaded once at startup and reused across requests.
"""

import os
import sys
import base64
import logging
from typing import List, Dict, Any, Optional

import cv2
import numpy as np

# Ensure pix2pix is importable
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.path.join(_project_root, 'pix2pix') not in sys.path:
    sys.path.insert(0, os.path.join(_project_root, 'pix2pix'))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

logger = logging.getLogger("herbiestim.pipeline")


class HerbiEstimPipeline:
    """
    End-to-end inference pipeline.

    Usage:
        pipeline = HerbiEstimPipeline(model_name='universal', gpu_ids=[])
        pipeline.load_models()
        results = pipeline.analyze(image_bytes, dpi=300, use_sam=False, return_images=True)
    """

    def __init__(self, model_name: str = 'universal',
                 checkpoints_dir: str = './model_saved',
                 gpu_ids: Optional[List[int]] = None,
                 enable_sam: bool = False,
                 sam_device: str = 'cuda',
                 sam_box_threshold: float = 0.3,
                 sam_text_threshold: float = 0.25,
                 mobile_max_dim: int = 800,
                 mobile_jpeg_quality: int = 75,
                 image_max_dim: int = 1024):
        self.model_name = model_name
        self.checkpoints_dir = checkpoints_dir
        self.gpu_ids = gpu_ids if gpu_ids is not None else []
        self.enable_sam = enable_sam
        self.sam_device = sam_device
        self.sam_box_threshold = sam_box_threshold
        self.sam_text_threshold = sam_text_threshold
        self.mobile_max_dim = mobile_max_dim
        self.mobile_jpeg_quality = mobile_jpeg_quality
        self.image_max_dim = image_max_dim

        self._pix2pix_model = None
        self._pix2pix_opt = None
        self._sam_segmentor = None
        self._models_loaded = False

    @property
    def pix2pix_loaded(self) -> bool:
        return self._pix2pix_model is not None

    @property
    def sam_loaded(self) -> bool:
        return self._sam_segmentor is not None

    def load_models(self):
        """
        Pre-load models into memory. Call once at application startup.
        """
        self._load_pix2pix()
        if self.enable_sam:
            self._load_sam()
        self._models_loaded = True
        logger.info("HerbiEstim pipeline models loaded successfully.")

    def _load_pix2pix(self):
        """Load pix2pix generator model."""
        from modelpredict import make_predict_opt
        from pix2pix.models import create_model

        logger.info(f"Loading pix2pix model '{self.model_name}' from '{self.checkpoints_dir}'...")

        # Build a dummy opt — we only need it to construct and load the model
        self._pix2pix_opt = make_predict_opt(
            dataroot='.',  # placeholder, overridden per-request
            name=self.model_name,
            checkpoints_dir=self.checkpoints_dir,
            results_dir='.',
            gpu_ids=self.gpu_ids,
        )

        self._pix2pix_model = create_model(self._pix2pix_opt)
        self._pix2pix_model.setup(self._pix2pix_opt)
        # Do NOT call model.eval() — pix2pix uses BatchNorm + Dropout with
        # batch_size=1.  The running statistics are unreliable, so training
        # mode (per-batch stats) is the intended inference behavior, matching
        # the CLI default (opt.eval=False).
        logger.info("pix2pix model loaded.")

    def _load_sam(self):
        """Load Grounded SAM segmentor."""
        try:
            from config.sam_config import SAM_MODEL_TYPE, SAM_CHECKPOINT_NAME
            logger.info(f"Loading Grounded SAM segmentor...")
            logger.info(f"  SAM model: {SAM_MODEL_TYPE} ({SAM_CHECKPOINT_NAME})")
            logger.info(f"  Device: {self.sam_device}")

            import torch
            if self.sam_device == 'cuda' and torch.cuda.is_available():
                gpu_name = torch.cuda.get_device_name(0)
                gpu_mem = torch.cuda.get_device_properties(0).total_mem / (1024**3)
                logger.info(f"  GPU: {gpu_name} ({gpu_mem:.1f} GB VRAM)")

            from utils.sam_segmentor import GroundedSAMSegmentor
            self._sam_segmentor = GroundedSAMSegmentor(
                device=self.sam_device,
                box_threshold=self.sam_box_threshold,
                text_threshold=self.sam_text_threshold,
            )
            logger.info(f"  SAM segmentor loaded successfully on {self.sam_device}.")
        except Exception as e:
            import traceback
            logger.warning(f"Failed to load SAM segmentor: {e}")
            logger.warning(f"  Traceback: {traceback.format_exc()}")
            logger.warning("  SAM mode will be unavailable.")
            self._sam_segmentor = None

    @staticmethod
    def _encode_image(img: np.ndarray, max_dim: int = 1024) -> str:
        """Encode a BGR image to base64 JPEG string, downscaling if too large."""
        h, w = img.shape[:2]
        if max(h, w) > max_dim:
            scale = max_dim / max(h, w)
            img = cv2.resize(img, (int(w * scale), int(h * scale)),
                             interpolation=cv2.INTER_AREA)
        _, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return base64.b64encode(buf).decode('utf-8')

    def _encode_image_mobile(self, img: np.ndarray) -> str:
        """
        Encode a BGR image to base64 JPEG with mobile-friendly compression.
        """
        h, w = img.shape[:2]
        max_dim = self.mobile_max_dim
        if max(h, w) > max_dim:
            scale = max_dim / max(h, w)
            new_w = max(1, int(w * scale))
            new_h = max(1, int(h * scale))
            img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
        _, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, self.mobile_jpeg_quality])
        return base64.b64encode(buf).decode('utf-8')

    @staticmethod
    def _encode_image_png(img: np.ndarray) -> str:
        """Encode a BGR image to base64 PNG (lossless, for standardized/result images)."""
        _, buf = cv2.imencode('.png', img)
        return base64.b64encode(buf).decode('utf-8')

    def _preprocess_image(self, image_bytes: bytes) -> bytes:
        """
        Preprocess uploaded image bytes for the pipeline.

        - Downscales large images to avoid timeouts on CPU
        - Preserves aspect ratio
        - Returns the (possibly downscaled) image bytes as JPEG
        """
        if self.image_max_dim <= 0:
            return image_bytes

        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return image_bytes

        h, w = img.shape[:2]
        max_dim = max(h, w)
        if max_dim <= self.image_max_dim:
            return image_bytes

        # Downscale preserving aspect ratio
        scale = self.image_max_dim / max_dim
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
        img_resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)

        _, buf = cv2.imencode('.jpg', img_resized, [cv2.IMWRITE_JPEG_QUALITY, 92])
        logger.info(f"Image downscaled: {w}x{h} -> {new_w}x{new_h}")
        return buf.tobytes()

    def analyze(self, image_bytes: bytes, dpi: int = 300,
                use_sam: bool = False, return_images: bool = True,
                is_scanned: bool = True, debug: bool = False) -> Dict[str, Any]:
        """
        Full inference pipeline: standardize → predict → calculate.

        Args:
            image_bytes: Raw image file bytes (jpg/png/tiff).
            dpi: DPI for area calculation (only used when is_scanned=True).
            use_sam: Whether to use SAM for leaf segmentation.
            return_images: Whether to include base64-encoded images in response.
            is_scanned: Whether the image is from a scanner.
            debug: Whether to collect and return intermediate pipeline images.

        Returns:
            Dict matching the AnalyzeResponse schema.
        """
        import tempfile
        from split import standardize_image
        from calculation import calculate_damage

        # Preprocess: downscale large images to avoid CPU timeouts
        processed_bytes = self._preprocess_image(image_bytes)

        debug_info = None
        if debug:
            debug_info = {
                'original_image': None,
                'detection_boxes': None,
                'sam_masks': None,
                'filtered_masks': None,
                'leaves': [],
            }

        # Step 1: Standardize — segment leaves, rotate, resize to 256x256
        logger.info("Step 1: Standardizing image...")
        sam_seg = self._sam_segmentor if use_sam else None

        if debug:
            standardized_leaves, std_debug = standardize_image(
                processed_bytes,
                use_sam=use_sam,
                sam_segmentor=sam_seg,
                sam_device=self.sam_device,
                box_threshold=self.sam_box_threshold,
                text_threshold=self.sam_text_threshold,
                return_debug_info=True,
            )
            # Encode original image
            original_img = std_debug['original_image']
            h, w = original_img.shape[:2]
            logger.info(f"  Input image size: {w}x{h}")
            debug_info['original_image'] = self._encode_image_mobile(original_img)

            # Generate SAM debug visualizations
            sam_debug = std_debug.get('sam_debug')
            if use_sam and sam_debug is not None:
                from utils.debug_visualizer import (
                    render_detections, render_masks, render_filtered_masks)

                boxes = sam_debug.get('boxes_xyxy')
                confs = sam_debug.get('box_confidences')
                if boxes is not None and confs is not None:
                    logger.info(f"  GroundingDINO detected {len(boxes)} boxes")
                    det_vis = render_detections(original_img, boxes, confs)
                    debug_info['detection_boxes'] = self._encode_image_mobile(det_vis)

                raw_masks = sam_debug.get('raw_masks')
                if raw_masks is not None and confs is not None:
                    logger.info(f"  SAM generated {len(raw_masks)} raw masks")
                    mask_vis = render_masks(original_img, raw_masks, confs)
                    debug_info['sam_masks'] = self._encode_image_mobile(mask_vis)

                kept_masks = sam_debug.get('kept_masks', [])
                rejected_masks = sam_debug.get('rejected_masks', [])
                logger.info(f"  Mask filtering: {len(kept_masks)} kept, {len(rejected_masks)} rejected")
                filt_vis = render_filtered_masks(
                    original_img, kept_masks, rejected_masks)
                debug_info['filtered_masks'] = self._encode_image_mobile(filt_vis)
        else:
            standardized_leaves = standardize_image(
                processed_bytes,
                use_sam=use_sam,
                sam_segmentor=sam_seg,
                sam_device=self.sam_device,
                box_threshold=self.sam_box_threshold,
                text_threshold=self.sam_text_threshold,
            )

        logger.info(f"  Standardization result: {len(standardized_leaves)} leaves found (use_sam={use_sam})")

        if not standardized_leaves:
            return {
                'leaves': [],
                'summary': {
                    'num_leaves': 0,
                    'total_leaf_area_cm2': 0.0,
                    'total_intact_area_cm2': 0.0,
                    'avg_damage_pct': 0.0,
                },
                'debug': debug_info,
            }

        # Collect per-leaf standardized images for debug
        if debug:
            for leaf_data in standardized_leaves:
                debug_info['leaves'].append({
                    'leaf_id': leaf_data['leaf_id'],
                    'standardized': self._encode_image_mobile(leaf_data['image']),
                    'real': None,
                    'fake': None,
                    'real_mask': None,
                    'fake_mask': None,
                })

        # Step 2: pix2pix prediction — reconstruct intact leaves
        logger.info(f"Step 2: Running pix2pix prediction on {len(standardized_leaves)} leaves...")
        predicted = self._predict_batch(standardized_leaves)

        # Step 3: Calculate damage
        logger.info("Step 3: Calculating damage metrics...")
        leaves_results = []
        total_leaf_area = 0.0
        total_intact_area = 0.0

        for i, (leaf_data, pred_data) in enumerate(zip(standardized_leaves, predicted)):
            real_img = pred_data.get('real')
            fake_img = pred_data.get('fake')

            if real_img is None or fake_img is None:
                continue

            damage = calculate_damage(
                real_img=real_img,
                fake_img=fake_img,
                resize_ratio=leaf_data['resize_ratio'],
                dpi=dpi,
                is_scanned=is_scanned,
            )

            leaf_result = {
                'leaf_id': leaf_data['leaf_id'],
                'leaf_area_cm2': damage['leaf_area'] if is_scanned else None,
                'intact_area_cm2': damage['intact_area'] if is_scanned else None,
                'damage_pct': max(0.0, min(1.0, damage['damage_pct'])),
            }

            if return_images:
                leaf_result['standardized_image'] = self._encode_image_png(leaf_data['image'])
                leaf_result['reconstructed_image'] = self._encode_image_png(fake_img)
            else:
                leaf_result['standardized_image'] = None
                leaf_result['reconstructed_image'] = None

            # Collect debug images for this leaf
            if debug and i < len(debug_info['leaves']):
                debug_info['leaves'][i]['real'] = self._encode_image_mobile(real_img)
                debug_info['leaves'][i]['fake'] = self._encode_image_mobile(fake_img)
                # Generate binary masks
                from calculation import getmask
                real_mask = getmask(real_img)
                fake_mask = getmask(fake_img)
                debug_info['leaves'][i]['real_mask'] = self._encode_image_mobile(
                    cv2.cvtColor(real_mask, cv2.COLOR_GRAY2BGR))
                debug_info['leaves'][i]['fake_mask'] = self._encode_image_mobile(
                    cv2.cvtColor(fake_mask, cv2.COLOR_GRAY2BGR))

            leaves_results.append(leaf_result)
            if is_scanned:
                total_leaf_area += damage['leaf_area']
                total_intact_area += damage['intact_area']

        num_leaves = len(leaves_results)
        # Calculate average damage from per-leaf damage_pct values (not area ratios)
        damage_pcts = [r['damage_pct'] for r in leaves_results]
        if num_leaves > 0 and len(damage_pcts) > 0:
            avg_damage = round(sum(damage_pcts) / len(damage_pcts), 3)
        else:
            avg_damage = 0.0

        return {
            'leaves': leaves_results,
            'summary': {
                'num_leaves': num_leaves,
                'total_leaf_area_cm2': round(total_leaf_area, 3) if is_scanned else None,
                'total_intact_area_cm2': round(total_intact_area, 3) if is_scanned else None,
                'avg_damage_pct': avg_damage,
            },
            'debug': debug_info,
        }

    def _predict_batch(self, standardized_leaves: List[Dict]) -> List[Dict]:
        """
        Run pix2pix prediction on a batch of standardized leaf images.

        Uses a temporary directory to interface with pix2pix's file-based dataset loading.

        Args:
            standardized_leaves: List of dicts from standardize_image().

        Returns:
            List of dicts: [{'name': str, 'real': ndarray, 'fake': ndarray}, ...]
        """
        import tempfile
        from pix2pix.data import create_dataset
        from pix2pix.util.visualizer import save_images
        from pix2pix.util import html
        from copy import deepcopy

        with tempfile.TemporaryDirectory(prefix='herbiestim_pred_') as tmpdir:
            # Write standardized images to temp directory
            test_dir = os.path.join(tmpdir, 'test')
            os.makedirs(test_dir, exist_ok=True)

            filenames = []
            for leaf in standardized_leaves:
                fname = f"leaf_{leaf['leaf_id']}.png"
                cv2.imwrite(os.path.join(test_dir, fname), leaf['image'])
                filenames.append(fname)

            # Configure opt for this batch
            opt = deepcopy(self._pix2pix_opt)
            opt.dataroot = tmpdir
            opt.results_dir = os.path.join(tmpdir, 'results')
            opt.num_test = len(filenames)

            # Create dataset and run inference
            dataset = create_dataset(opt)

            web_dir = os.path.join(opt.results_dir, opt.name,
                                   f'{opt.phase}_{opt.epoch}')
            webpage = html.HTML(web_dir,
                                f'Experiment = {opt.name}, Phase = {opt.phase}, Epoch = {opt.epoch}')

            for i, data in enumerate(dataset):
                if i >= opt.num_test:
                    break
                self._pix2pix_model.set_input(data)
                self._pix2pix_model.test()
                visuals = self._pix2pix_model.get_current_visuals()
                img_path = self._pix2pix_model.get_image_paths()
                save_images(webpage, visuals, img_path,
                            aspect_ratio=opt.aspect_ratio,
                            width=opt.display_winsize,
                            use_wandb=False)
            webpage.save()

            # Collect results
            img_dir = os.path.join(web_dir, 'images')
            results = []
            for fname in filenames:
                stem = os.path.splitext(fname)[0]
                real_path = os.path.join(img_dir, f'{stem}_real.png')
                fake_path = os.path.join(img_dir, f'{stem}_fake.png')
                real_img = cv2.imread(real_path) if os.path.exists(real_path) else None
                fake_img = cv2.imread(fake_path) if os.path.exists(fake_path) else None
                results.append({'name': fname, 'real': real_img, 'fake': fake_img})

            return results
