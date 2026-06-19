import os
import argparse
from pathlib import Path
from collections import defaultdict
import cv2
import numpy as np
import csv


def getmask(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.medianBlur(gray, 3)
    (T, threshInv) = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    return (threshInv)


def calculate_damage(real_img, fake_img, resize_ratio, dpi=300, is_scanned=True):
    """
    Calculate leaf damage from a pair of real (damaged) and fake (reconstructed) images.

    This is the primary API function for cloud deployment.

    Args:
        real_img: BGR numpy array of the real (damaged) leaf image.
        fake_img: BGR numpy array of the fake (reconstructed intact) leaf image.
        resize_ratio: The ratio used to convert pixel counts back to real-world areas.
        dpi: DPI of the original scan (used only when is_scanned=True).
        is_scanned: Whether the image was scanned (True) or photographed (False).

    Returns:
        dict with keys:
            - leaf_area: Actual leaf area (cm² if scanned, pixel count if not).
            - intact_area: Reconstructed intact leaf area.
            - damage_pct: Damage percentage (0.0 - 1.0).
    """
    mask_real = getmask(real_img)
    d1 = np.count_nonzero(mask_real)

    mask_fake = getmask(fake_img)
    d2 = np.count_nonzero(mask_fake)

    if is_scanned:
        dpivalue = (dpi / 2.54) ** 2
        act_area = round(d1 * float(resize_ratio) * float(resize_ratio) / dpivalue, 3)
        intact_area = round(d2 * float(resize_ratio) * float(resize_ratio) / dpivalue, 3)
    else:
        act_area = int(round(d1 * float(resize_ratio) * float(resize_ratio), 0))
        intact_area = int(round(d2 * float(resize_ratio) * float(resize_ratio), 0))

    if intact_area > 0:
        damage_pct = round((intact_area - act_area) / intact_area, 3)
    else:
        damage_pct = 0.0

    return {
        'leaf_area': act_area,
        'intact_area': intact_area,
        'damage_pct': damage_pct,
    }


def _run_cli(args):
    """Run the CLI workflow with parsed args."""
    dpivalue = (args.dpi / 2.54) ** 2

    # Collect per-image aggregation data
    image_summary = defaultdict(lambda: {'act_area': [], 'intact_area': []})

    with open("result.csv", "w", newline='') as predcsv:
        wpredcsv = csv.writer(predcsv)
        if args.notscanned:
            wpredcsv.writerow(['img.tag', 'ind.leaf', 'LA(cm2)', 'intact.LA(cm2)', 'damage(%)'])
        else:
            wpredcsv.writerow(['img.tag', 'ind.leaf', 'num_pixel', 'intact.num_pixel', 'damage(%)'])

        target_file = os.path.join(args.standardized, "resize_ratio.csv")
        if not os.path.exists(target_file):
            print(f"[ERROR] Resize ratio file not found: {target_file}")
            print("Please run split.py first to generate this file.")
            return

        with open(target_file, mode='r', encoding='UTF-8-sig', newline='') as f_input:
            csv_input = csv.reader(f_input)
            try:
                header = next(csv_input)
            except StopIteration:
                print(f"[ERROR] {target_file} is empty. Please re-run split.py.")
                return
            
            # Check for data
            rows = list(csv_input)
            if not rows:
                 print(f"[WARNING] {target_file} contains only a header. No images to process.")
                 return

            # Reset iterator for processing
            f_input.seek(0)
            csv_input = csv.reader(f_input)
            next(csv_input) # Skip header again

            for row in csv_input:
                if not row or len(row) < 3:
                    continue
                fake = os.path.join(args.imgspredict, args.name, 'test_latest', 'images',
                                    str(row[0]) + '_' + str(row[1]) + '_fake.png')
                real = os.path.join(args.imgspredict, args.name, 'test_latest', 'images',
                                    str(row[0]) + '_' + str(row[1]) + '_real.png')
                imagereal = cv2.imread(real)
                mask = getmask(imagereal)
                d1 = np.count_nonzero(mask)

                imagefake = cv2.imread(fake)
                mask2 = getmask(imagefake)
                d2 = np.count_nonzero(mask2)

                if args.notscanned:
                    act_area = round(d1 * float(row[2]) * float(row[2]) / dpivalue, 3)
                    intact_area = round(d2 * float(row[2]) * float(row[2]) / dpivalue, 3)
                else:
                    act_area = int(round(d1 * float(row[2]) * float(row[2]), 0))
                    intact_area = int(round(d2 * float(row[2]) * float(row[2]), 0))

                proportation = round((intact_area - act_area) / intact_area, 3)
                wpredcsv.writerow([row[0], row[1], act_area, intact_area, proportation])

                image_summary[row[0]]['act_area'].append(act_area)
                image_summary[row[0]]['intact_area'].append(intact_area)

    with open("result_summary.csv", "w", newline='') as summcsv:
        wsummcsv = csv.writer(summcsv)
        if args.notscanned:
            wsummcsv.writerow(['img.tag', 'num_leaves', 'total_LA(cm2)', 'total_intact_LA(cm2)', 'total_damage(%)'])
        else:
            wsummcsv.writerow(['img.tag', 'num_leaves', 'total_num_pixel', 'total_intact_num_pixel', 'total_damage(%)'])

        for img_tag, data in image_summary.items():
            num_leaves = len(data['act_area'])
            total_act = round(sum(data['act_area']), 3)
            total_intact = round(sum(data['intact_area']), 3)
            if total_intact > 0:
                total_damage = round((total_intact - total_act) / total_intact, 3)
            else:
                total_damage = 0.0
            wsummcsv.writerow([img_tag, num_leaves, total_act, total_intact, total_damage])

    print(f"[INFO] Leaf-level results written to: result.csv")
    print(f"[INFO] Image-level summary written to: result_summary.csv")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Calculate leaf damage based on reconstructed leaves",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    parser.add_argument("-s", "--standardized", type=Path, default='./imgs_standardized',
                        help="Path to the standardized images")
    parser.add_argument("-p", "--imgspredict", type=Path, default='./imgs_predicted',
                        help="Path of predicted images")
    parser.add_argument("-n", '--name', type=str, default='experiment_name', help='model name')
    parser.add_argument("-d", '--dpi', type=int, default=300,
                        help="The resolution of images in dpi, default is 300 dpi")
    parser.add_argument('--notscanned', action='store_false',
                        help="Include the argument if images are not scanned")

    args = parser.parse_args()
    _run_cli(args)