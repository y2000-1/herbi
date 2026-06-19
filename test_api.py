"""Quick test script for the HerbiEstim API."""

import urllib.request
import json
import os
import sys


def build_multipart(fields, files):
    """Build multipart/form-data body."""
    boundary = b'----HerbiEstimTestBoundary9876543210'
    body = b''

    for name, value in fields.items():
        body += b'------HerbiEstimTestBoundary9876543210\r\n'
        body += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        body += f'{value}\r\n'.encode()

    for name, (filename, data, content_type) in files.items():
        body += b'------HerbiEstimTestBoundary9876543210\r\n'
        body += f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
        body += f'Content-Type: {content_type}\r\n\r\n'.encode()
        body += data
        body += b'\r\n'

    body += b'------HerbiEstimTestBoundary9876543210--\r\n'
    return body, 'multipart/form-data; boundary=----HerbiEstimTestBoundary9876543210'


def main():
    base_url = 'http://127.0.0.1:8000'

    # 1. Health check
    print("=" * 50)
    print("1. Testing health check...")
    try:
        r = urllib.request.urlopen(f'{base_url}/api/v1/health', timeout=10)
        health = json.loads(r.read())
        print(f"   Status: {health['status']}")
        print(f"   pix2pix loaded: {health['pix2pix_loaded']}")
        print(f"   SAM loaded: {health['sam_loaded']}")
        print(f"   GPU available: {health['gpu_available']}")
    except Exception as e:
        print(f"   FAILED: {e}")
        print("   Is the API server running? Start with:")
        print("   python -m uvicorn api.app:app --host 127.0.0.1 --port 8000")
        sys.exit(1)

    # 2. Analyze a test image
    print("\n" + "=" * 50)

    # Find a test image
    test_images = [
        os.path.join('imgs_raw', 's1.png'),
        os.path.join('imgs_raw', 's2.png'),
    ]

    img_path = None
    for p in test_images:
        if os.path.exists(p):
            img_path = p
            break

    if img_path is None:
        print("2. No test image found in imgs_raw/. Skipping analyze test.")
        return

    print(f"2. Testing analyze with: {img_path}")
    with open(img_path, 'rb') as f:
        img_data = f.read()

    print(f"   Image size: {len(img_data)} bytes")

    ext = os.path.splitext(img_path)[1].lower()
    ct_map = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.tiff': 'image/tiff'}
    content_type = ct_map.get(ext, 'image/png')

    fields = {
        'dpi': '300',
        'return_images': 'false',
        'use_sam': 'false',
        'is_scanned': 'true',
    }
    files = {
        'image': (os.path.basename(img_path), img_data, content_type),
    }

    body, ct = build_multipart(fields, files)

    req = urllib.request.Request(
        f'{base_url}/api/v1/analyze',
        data=body,
        headers={'Content-Type': ct},
        method='POST',
    )

    print("   Sending request (this may take a minute on CPU)...")
    try:
        r = urllib.request.urlopen(req, timeout=300)
        result = json.loads(r.read())
        print("\n   === RESULTS ===")
        print(f"   Leaves found: {result['summary']['num_leaves']}")
        if result['summary']['total_leaf_area_cm2'] is not None:
            print(f"   Total leaf area: {result['summary']['total_leaf_area_cm2']} cm²")
            print(f"   Total intact area: {result['summary']['total_intact_area_cm2']} cm²")
        print(f"   Avg damage: {result['summary']['avg_damage_pct'] * 100:.1f}%")
        print()
        for leaf in result['leaves']:
            area_str = f"{leaf['leaf_area_cm2']} cm²" if leaf['leaf_area_cm2'] else "N/A"
            intact_str = f"{leaf['intact_area_cm2']} cm²" if leaf['intact_area_cm2'] else "N/A"
            print(f"   Leaf {leaf['leaf_id']}: area={area_str}, intact={intact_str}, damage={leaf['damage_pct'] * 100:.1f}%")
        print("\n   SUCCESS!")
    except urllib.error.HTTPError as e:
        print(f"   HTTP ERROR {e.code}: {e.read().decode()}")
    except Exception as e:
        print(f"   FAILED: {e}")


if __name__ == '__main__':
    main()
