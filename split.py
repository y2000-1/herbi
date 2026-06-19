import csv
import os
import cv2
import imutils
import numpy as np
import math
import argparse
import tempfile
from pathlib import Path

def angle(img):
    # convert to grayscale
    img_gs = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    #inverted binary threshold
    _, thresh = cv2.threshold(img_gs, 250, 1, cv2.THRESH_BINARY_INV)
    #From a matrix of pixels to a matrix of coordinates of non-black points.
    #(note: mind the col/row order, pixels are accessed as [row, col]
    #but when we draw, it's (x, y), so have to swap here or there)
    mat = np.argwhere(thresh != 0)
    #swap here
    mat[:, [0, 1]] = mat[:, [1, 0]]
    # convert type for PCA
    mat = np.array(mat).astype(np.float32)
    #mean (e. g. the geometrical center) and eigenvectors (e. g. directions of principal components)
    m, e = cv2.PCACompute(mat, mean = np.array([]))

    #scale our primary axis by 100,
    center = tuple(m[0])
    endpoint1 = tuple(m[0] + e[0]*100)

    ## calculate the angle in degree to horizontal
    y = center[1] - endpoint1[1]
    x = endpoint1[0] - center[0]

    if x < 0 and y < 0:
        radianA = math.atan2(abs(y), abs(x))
    elif x > 0 and y < 0:
        radianA = math.atan2((-y), (-x))
    else:
        radianA = math.atan2(y,x)

    angleHor = np.rad2deg(radianA)
    return(angleHor)

def getmask(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.medianBlur(gray, 3)
    (T, threshInv) = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    return(threshInv)


def rotate_and_resize(leaf_img):
    """
    Rotate a single-leaf image to vertical orientation via PCA and resize to 256x256.
    Shared by both OpenCV and SAM branches.

    Args:
        leaf_img: BGR image of a single leaf on white background.

    Returns:
        (resized_img, resize_ratio) or (None, None) if the leaf is too small.
    """
    h, w = leaf_img.shape[:2]
    max_dim = max(h, w)

    # Make the image square with the leaf centered
    half = round(max_dim * 0.75)
    cy, cx = h // 2, w // 2

    y1 = cy - half
    x1 = cx - half
    y2 = cy + half
    x2 = cx + half

    # Pad if necessary
    top = max(0, -y1)
    bottom = max(0, y2 - h)
    left = max(0, -x1)
    right = max(0, x2 - w)
    padded = cv2.copyMakeBorder(leaf_img, top, bottom, left, right,
                                cv2.BORDER_CONSTANT, value=[255, 255, 255])

    y1 = max(0, y1)
    x1 = max(0, x1)
    y2 = y1 + 2 * half
    x2 = x1 + 2 * half

    # Ensure we don't exceed padded image bounds
    y2 = min(y2, padded.shape[0])
    x2 = min(x2, padded.shape[1])

    ROI = padded[y1:y2, x1:x2]

    roi_h, roi_w = ROI.shape[:2]
    if roi_h < 128 or roi_w < 128:
        return None, None

    # Rotate to vertical using PCA
    ang = 90 - angle(ROI)
    M = cv2.getRotationMatrix2D((roi_w / 2, roi_h / 2), ang, 1.0)

    mask = getmask(ROI)
    change = cv2.warpAffine(ROI, M, (roi_w, roi_h))
    changmask = cv2.warpAffine(mask, M, (roi_w, roi_h))
    image_synthetic = cv2.bitwise_and(change, change, mask=changmask)

    b = np.ones_like(ROI, np.uint8) * 255
    cv2.bitwise_not(b, b, mask=changmask)
    ROI = image_synthetic + b

    # Resize to 256x256
    length, height, _ = ROI.shape
    ROIsized = cv2.resize(ROI, (256, 256), interpolation=cv2.INTER_AREA)
    resize_ratio = height / 256

    return ROIsized, resize_ratio


def process_with_sam(args, img_list, dirname):
    """
    Process images using Grounded SAM for leaf segmentation.
    Output format is identical to the OpenCV branch.
    """
    from utils.sam_segmentor import GroundedSAMSegmentor, extract_leaf_from_mask

    debug = getattr(args, 'debug', False)
    debug_dir = str(getattr(args, 'debug_dir', './imgs_debug'))

    if debug:
        from utils.debug_visualizer import (
            visualize_detections,
            visualize_masks,
            visualize_filtered_masks,
        )
        os.makedirs(debug_dir, exist_ok=True)
        print(f"[DEBUG] Debug visualizations will be saved to: {debug_dir}")

    print("[INFO] Initializing Grounded SAM segmentor...")
    try:
        segmentor = GroundedSAMSegmentor(
            device=args.sam_device,
            box_threshold=args.box_threshold,
            text_threshold=args.text_threshold,
        )
    except Exception as e:
        print(f"[ERROR] Failed to initialize Grounded SAM: {e}")
        print("[INFO] Falling back to OpenCV contour detection mode...")
        return False  # Signal to fall back

    with open(os.path.join(args.output, 'resize_ratio.csv'), "w", newline='') as resizcsv:
        wresizcsv = csv.writer(resizcsv)
        wresizcsv.writerow(['img_tag', 'img_num', 'resize_ratio'])

        for imagepath in img_list:
            pathfrom = os.path.join(args.input, imagepath)
            image = cv2.imread(pathfrom)
            if image is None:
                print(f"[WARN] Cannot read image: {pathfrom}, skipping.")
                continue

            print(f"[INFO] Processing (SAM): {imagepath}")

            # Detect and segment leaves
            if debug:
                results, debug_info = segmentor.segment_leaves(
                    image, return_debug_info=True
                )
            else:
                results = segmentor.segment_leaves(image)

            if len(results) == 0:
                print(f"[WARN] No leaves detected in {imagepath}, skipping.")
                continue

            print(f"[INFO]   Found {len(results)} leaf/leaves.")

            # --- Save debug visualizations ---
            if debug:
                img_stem = Path(imagepath).stem
                img_debug_dir = os.path.join(debug_dir, img_stem)
                os.makedirs(img_debug_dir, exist_ok=True)

                boxes = debug_info['boxes_xyxy']
                confs = debug_info['box_confidences']
                raw_masks = debug_info['raw_masks']
                rejected_masks = debug_info['rejected_masks']
                kept_masks = [r['mask'] for r in results]

                # 1) GroundingDINO detections
                visualize_detections(
                    image, boxes, confs,
                    os.path.join(img_debug_dir, "01_detections.png"),
                )
                # 2) SAM raw masks (before filtering)
                if raw_masks:
                    visualize_masks(
                        image, raw_masks, confs,
                        os.path.join(img_debug_dir, "02_sam_masks.png"),
                    )
                # 3) Filtered result: kept vs rejected
                visualize_filtered_masks(
                    image, kept_masks, rejected_masks,
                    os.path.join(img_debug_dir, "03_filtered_masks.png"),
                )
                print(f"[DEBUG]   Saved debug images to: {img_debug_dir}")

            image_number = 0
            for leaf_result in results:
                mask = leaf_result['mask']

                # Extract leaf with white background
                leaf_img = extract_leaf_from_mask(image, mask)

                # Rotate and resize (shared logic)
                ROIsized, resize_ratio = rotate_and_resize(leaf_img)
                if ROIsized is None:
                    continue

                wresizcsv.writerow([imagepath, image_number, resize_ratio])

                nam = "{}_{}.png".format(imagepath, image_number)
                pathdir = os.path.join(dirname, nam)
                cv2.imwrite(pathdir, ROIsized)
                image_number += 1
                print(f"  {nam}")

    return True  # Success


def _opencv_segment_single_image(image):
    """
    Segment leaves from a single BGR image using OpenCV contour detection.

    Includes PCA rotation and resize to 256x256 (matching CLI _run_cli behavior).

    Args:
        image: BGR numpy array of the input image.

    Returns:
        List of (resized_image, resize_ratio) tuples for each detected leaf.
    """
    image = cv2.copyMakeBorder(image, top=30, bottom=30, left=30, right=30,
                               borderType=cv2.BORDER_CONSTANT, value=[255, 255, 255])
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.medianBlur(gray, 15)
    (T, threshInv) = cv2.threshold(blurred, 0, 255,
                                   cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    f = cv2.bitwise_and(image, image, mask=threshInv)
    b = np.ones_like(image, np.uint8) * 255
    cv2.bitwise_not(b, b, mask=threshInv)
    image_th = f + b

    auto = imutils.auto_canny(threshInv)
    kernel = np.ones((5, 5), np.uint8)
    dilate = cv2.dilate(auto, kernel, iterations=1)
    cntss = cv2.findContours(dilate.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cnts = cntss[0] if len(cntss) == 2 else cntss[1]

    leaf_images = []
    for c in cnts:
        canvas = np.zeros(image_th.shape[0:2], dtype=np.uint8)
        cv2.drawContours(canvas, [c], -1, (255, 255, 255), -1, cv2.LINE_AA)
        res = cv2.bitwise_and(image_th, image_th, mask=canvas)
        wbg = np.ones_like(image_th, np.uint8) * 255
        cv2.bitwise_not(wbg, wbg, mask=canvas)
        dst = wbg + res

        x, y, w, heig = cv2.boundingRect(c)
        cx = x + round(w / 2)
        cy = y + round(heig / 2)
        if w >= heig:
            heig = round(round(w / 2) * 1.5)
        else:
            heig = round(round(heig / 2) * 1.5)

        y1 = cy - heig
        x1 = cx - heig
        y2 = cy + heig
        x2 = cx + heig

        if y1 < 0:
            dst = cv2.copyMakeBorder(dst, top=(-y1), bottom=0, left=0, right=0,
                                     borderType=cv2.BORDER_CONSTANT, value=[255, 255, 255])
            y1 = 0
            y2 = heig + heig
        if x1 < 0:
            dst = cv2.copyMakeBorder(dst, top=0, bottom=0, left=(-x1), right=0,
                                     borderType=cv2.BORDER_CONSTANT, value=[255, 255, 255])
            x1 = 0
            x2 = heig + heig
        if y2 > (image.shape[0]):
            dst = cv2.copyMakeBorder(dst, top=0, bottom=(y2 - image.shape[0]), left=0, right=0,
                                     borderType=cv2.BORDER_CONSTANT, value=[255, 255, 255])
        if x2 > (image.shape[1]):
            dst = cv2.copyMakeBorder(dst, top=0, bottom=0, left=0, right=(x2 - image.shape[1]),
                                     borderType=cv2.BORDER_CONSTANT, value=[255, 255, 255])

        ROI = dst[y1:y2, x1:x2]

        if heig > 128:
            ang = 90 - angle(ROI)
            M = cv2.getRotationMatrix2D((ROI.shape[0] / 2, ROI.shape[1] / 2), ang, 1.0)

            mask = getmask(ROI)
            change = cv2.warpAffine(ROI, M, (ROI.shape[0], ROI.shape[1]))
            changmask = cv2.warpAffine(mask, M, (ROI.shape[0], ROI.shape[1]))
            image_synthetic = cv2.bitwise_and(change, change, mask=changmask)

            b = np.ones_like(ROI, np.uint8) * 255
            cv2.bitwise_not(b, b, mask=changmask)
            ROI = image_synthetic + b

            length, height_val, _ = ROI.shape
            ROIsized = cv2.resize(ROI, (256, 256), interpolation=cv2.INTER_AREA)
            resize_ratio = height_val / 256

            leaf_images.append((ROIsized, resize_ratio))

    return leaf_images


def _sam_segment_single_image(image, segmentor, return_debug_info=False):
    """
    Segment leaves from a single BGR image using Grounded SAM.

    Args:
        image: BGR numpy array.
        segmentor: An initialized GroundedSAMSegmentor instance.
        return_debug_info: If True, return (leaf_images, debug_info) tuple.

    Returns:
        If return_debug_info is False:
            List of BGR numpy arrays, each containing one leaf on white background.
        If return_debug_info is True:
            Tuple of (leaf_images, debug_info) where debug_info is a dict with
            boxes_xyxy, box_confidences, raw_masks, rejected_masks, kept_masks.
    """
    from utils.sam_segmentor import extract_leaf_from_mask

    if return_debug_info:
        results, debug_info = segmentor.segment_leaves(image, return_debug_info=True)
        kept_masks = [r['mask'] for r in results]
        debug_info['kept_masks'] = kept_masks
    else:
        results = segmentor.segment_leaves(image)
        debug_info = None

    leaf_images = []
    for leaf_result in results:
        leaf_img = extract_leaf_from_mask(image, leaf_result['mask'])
        leaf_images.append(leaf_img)

    if return_debug_info:
        return leaf_images, debug_info
    return leaf_images


def standardize_image(image_bytes_or_ndarray, use_sam=False, sam_segmentor=None,
                      sam_device='cuda', box_threshold=0.3, text_threshold=0.25,
                      return_debug_info=False):
    """
    Standardize a single input image: segment leaves, rotate via PCA, resize to 256x256.

    This is the primary API function for cloud deployment.

    Args:
        image_bytes_or_ndarray: Either raw image bytes or a BGR numpy array.
        use_sam: Whether to use Grounded SAM for segmentation.
        sam_segmentor: Pre-initialized GroundedSAMSegmentor instance (reuse across requests).
                       If None and use_sam=True, a new instance will be created.
        sam_device: Device for SAM inference ('cuda' or 'cpu').
        box_threshold: GroundingDINO detection confidence threshold.
        text_threshold: GroundingDINO text matching threshold.
        return_debug_info: If True, return (results, debug_dict) tuple with intermediate data.

    Returns:
        If return_debug_info is False:
            List of dicts:
                [{'image': ndarray (256x256 BGR), 'resize_ratio': float, 'leaf_id': int}, ...]
        If return_debug_info is True:
            Tuple of (results_list, debug_dict) where debug_dict contains:
                - original_image: decoded BGR image
                - sam_debug: SAM debug info dict (None if use_sam=False)
    """
    # Decode bytes to ndarray if necessary
    if isinstance(image_bytes_or_ndarray, (bytes, bytearray)):
        nparr = np.frombuffer(image_bytes_or_ndarray, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("Failed to decode image bytes")
    else:
        image = image_bytes_or_ndarray

    debug_dict = {'original_image': image, 'sam_debug': None} if return_debug_info else None

    # Segment leaves
    if use_sam:
        if sam_segmentor is None:
            from utils.sam_segmentor import GroundedSAMSegmentor
            sam_segmentor = GroundedSAMSegmentor(
                device=sam_device,
                box_threshold=box_threshold,
                text_threshold=text_threshold,
            )
        if return_debug_info:
            leaf_rois, sam_debug = _sam_segment_single_image(
                image, sam_segmentor, return_debug_info=True)
            debug_dict['sam_debug'] = sam_debug
        else:
            leaf_rois = _sam_segment_single_image(image, sam_segmentor)
        # SAM branch: rotate and resize each leaf
        results = []
        for idx, leaf_img in enumerate(leaf_rois):
            resized, ratio = rotate_and_resize(leaf_img)
            if resized is not None:
                results.append({
                    'image': resized,
                    'resize_ratio': ratio,
                    'leaf_id': idx,
                })
    else:
        # OpenCV branch: _opencv_segment_single_image already returns
        # (256x256 image, resize_ratio) tuples matching CLI behavior
        leaf_rois = _opencv_segment_single_image(image)
        results = []
        for idx, (resized, ratio) in enumerate(leaf_rois):
            results.append({
                'image': resized,
                'resize_ratio': ratio,
                'leaf_id': idx,
            })

    if return_debug_info:
        return results, debug_dict
    return results


def _run_cli(args):
    """Run the CLI workflow with parsed args."""
    if not os.path.exists(args.output):
        os.makedirs(args.output)
    dirname = os.path.join(args.output, 'test')
    if not os.path.exists(dirname):
        os.makedirs(dirname)

    # remove .DS_Store file in the folder
    img = os.listdir(args.input)
    if '.DS_Store' in img:
        img.remove('.DS_Store')

    # ==================== SAM Branch ====================
    if args.use_sam:
        success = process_with_sam(args, img, dirname)
        if not success:
            print("[INFO] SAM initialization failed. Running OpenCV mode instead...")
            args.use_sam = False  # Fall through to OpenCV branch below

    # ==================== OpenCV Branch (default) ====================
    if not args.use_sam:
        with open(os.path.join(args.output, 'resize_ratio.csv'), "w", newline='') as resizcsv:
            wresizcsv = csv.writer(resizcsv)
            wresizcsv.writerow(['img_tag', 'img_num', 'resize_ratio'])

            for imagepath in img:
                pathfrom = os.path.join(args.input, imagepath)
                image = cv2.imread(pathfrom)

                image = cv2.copyMakeBorder(image, top=30, bottom=30, left=30, right=30,
                                           borderType=cv2.BORDER_CONSTANT, value=[255, 255, 255])
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                blurred = cv2.medianBlur(gray, 15)
                (T, threshInv) = cv2.threshold(blurred, 0, 255,
                                               cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
                f = cv2.bitwise_and(image, image, mask=threshInv)
                b = np.ones_like(image, np.uint8) * 255
                cv2.bitwise_not(b, b, mask=threshInv)
                image_th = f + b

                auto = imutils.auto_canny(threshInv)
                kernel = np.ones((5, 5), np.uint8)
                dilate = cv2.dilate(auto, kernel, iterations=1)
                cntss = cv2.findContours(dilate.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                cnts = imutils.grab_contours(cntss)
                cnts = cntss[0] if len(cntss) == 2 else cntss[1]

                image_number = 0
                for c in cnts:
                    canvas = np.zeros(image_th.shape[0:2], dtype=np.uint8)
                    cv2.drawContours(canvas, [c], -1, (255, 255, 255), -1, cv2.LINE_AA)
                    res = cv2.bitwise_and(image_th, image_th, mask=canvas)
                    wbg = np.ones_like(image_th, np.uint8) * 255
                    cv2.bitwise_not(wbg, wbg, mask=canvas)
                    dst = wbg + res

                    x, y, w, heig = cv2.boundingRect(c)
                    cx = x + round(w / 2)
                    cy = y + round(heig / 2)
                    if w >= heig:
                        heig = round(round(w / 2) * 1.5)
                    else:
                        heig = round(round(heig / 2) * 1.5)

                    y1 = cy - heig
                    x1 = cx - heig
                    y2 = cy + heig
                    x2 = cx + heig

                    if y1 < 0:
                        dst = cv2.copyMakeBorder(dst, top=(-y1), bottom=0, left=0, right=0,
                                                 borderType=cv2.BORDER_CONSTANT, value=[255, 255, 255])
                        y1 = 0
                        y2 = heig + heig
                    if x1 < 0:
                        dst = cv2.copyMakeBorder(dst, top=0, bottom=0, left=(-x1), right=0,
                                                 borderType=cv2.BORDER_CONSTANT, value=[255, 255, 255])
                        x1 = 0
                        x2 = heig + heig
                    if y2 > (image.shape[0]):
                        dst = cv2.copyMakeBorder(dst, top=0, bottom=(y2 - image.shape[0]), left=0, right=0,
                                                 borderType=cv2.BORDER_CONSTANT, value=[255, 255, 255])
                    if x2 > (image.shape[1]):
                        dst = cv2.copyMakeBorder(dst, top=0, bottom=0, left=0, right=(x2 - image.shape[1]),
                                                 borderType=cv2.BORDER_CONSTANT, value=[255, 255, 255])

                    ROI = dst[y1:y2, x1:x2]

                    if heig > 128:
                        ang = 90 - angle(ROI)
                        M = cv2.getRotationMatrix2D((ROI.shape[0] / 2, ROI.shape[1] / 2), ang, 1.0)

                        mask = getmask(ROI)
                        change = cv2.warpAffine(ROI, M, (ROI.shape[0], ROI.shape[1]))
                        changmask = cv2.warpAffine(mask, M, (ROI.shape[0], ROI.shape[1]))
                        image_synthetic = cv2.bitwise_and(change, change, mask=changmask)

                        b = np.ones_like(ROI, np.uint8) * 255
                        cv2.bitwise_not(b, b, mask=changmask)
                        ROI = image_synthetic + b

                        length, height, _ = ROI.shape
                        ROIsized = cv2.resize(ROI, (256, 256), interpolation=cv2.INTER_AREA)
                        dd1 = height / 256

                        wresizcsv.writerow([imagepath, image_number, dd1])

                        nam = "{}_{}.png".format(imagepath, image_number)
                        pathdir = os.path.join(dirname, nam)
                        cv2.imwrite(pathdir, ROIsized)
                        image_number += 1
                        print(nam)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Split multiple-leaf images to single-leaf images and standardize to 256*256",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("-i", "--input", type=Path, required=True, help="Path to the input directory")
    parser.add_argument("-o", "--output", type=Path, default='./imgs_standardized', help="Path to the output directory")
    parser.add_argument("--use-sam", action='store_true',
                        help="Use Grounded SAM for leaf segmentation instead of OpenCV contour detection")
    parser.add_argument("--sam-device", type=str, default='cuda',
                        help="Device for SAM/GroundingDINO inference ('cuda' or 'cpu')")
    parser.add_argument("--box-threshold", type=float, default=0.3,
                        help="GroundingDINO detection confidence threshold")
    parser.add_argument("--text-threshold", type=float, default=0.25,
                        help="GroundingDINO text matching threshold")
    parser.add_argument("--debug", action='store_true',
                        help="[Dev only] Save intermediate Grounded SAM visualizations to --debug-dir")
    parser.add_argument("--debug-dir", type=Path, default='./imgs_debug',
                        help="Directory to save debug visualizations (used with --debug)")

    args = parser.parse_args()
    _run_cli(args)


