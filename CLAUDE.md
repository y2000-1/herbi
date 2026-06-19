# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

HerbiEstim estimates leaf herbivore damage using pix2pix (conditional GAN) to reconstruct intact leaves from damaged ones, then measures the difference. It runs as both a CLI pipeline and a FastAPI REST API.

## Commands

### CLI Pipeline (sequential steps)
```bash
python split.py -i imgs_raw                            # Step 1: Segment & standardize leaves to 256x256
python split.py -i imgs_raw --use-sam                   # Step 1 (alt): Use Grounded SAM for overlapping leaves
python synthetic.py -i imgs_intact -n 5000              # Step 2: Generate training pairs
python modeltraining.py --dataroot imgs_synthesis       # Step 3: Train pix2pix model
python modelpredict.py --dataroot imgs_standardized --name universal  # Step 4: Predict intact leaves
python calculation.py -n universal                      # Step 5: Calculate damage metrics
python calculation.py -n universal --dpi 300            # Step 5 (scanned): area in cm²
python calculation.py -n universal --notscanned         # Step 5 (photo): pixel counts only
```

### API Server
```bash
pip install -r requirements-api.txt
python -m uvicorn api.app:app --host 0.0.0.0 --port 8000
python test_api.py                                      # Integration test (requires running server)
```

### Docker
```bash
docker build -t herbiestim-api .
docker compose up -d                                    # CPU
docker compose --profile gpu up -d                      # GPU
```

### Environment Setup
```bash
conda create -n herbiestim python=3.8.13
conda activate herbiestim
pip install -r requirements.txt           # Full CLI + training
pip install -r requirements-api.txt       # API-only (minimal)
```

### Diagnostics
```bash
python _check_sam.py                      # Verify SAM/GroundingDINO dependencies
```

## Architecture

### 5-Step Pipeline
Each step reads from the previous step's output directory. Modifying any step's output format breaks downstream steps.

1. **split.py** → `imgs_standardized/` + `resize_ratio.csv` (critical: maps 256px back to original dimensions)
2. **synthetic.py** → `imgs_synthesis/train/` (aligned 256x512 images: left=intact target, right=damaged input)
3. **modeltraining.py** → `model_saved/{name}/` (thin wrapper delegating to pix2pix/train.py)
4. **modelpredict.py** → `imgs_predicted/{name}/test_latest/images/` (*_real.png and *_fake.png pairs)
5. **calculation.py** → `result.csv` + `result_summary.csv`

### API Layer (`api/`)
- **app.py**: FastAPI entry point. `POST /api/v1/analyze` (image upload), `GET /api/v1/health`
- **pipeline.py**: `HerbiEstimPipeline` singleton orchestrates standardize→predict→calculate in-memory, using temp directories to bridge with pix2pix's file-based dataset loader
- **config.py**: All settings via `HERBI_*` environment variables
- **middleware.py**: Optional API key auth (`X-API-Key`) and per-IP rate limiting

### Dual-Mode Design
Core modules expose both CLI (`argparse`) and importable functions: `standardize_image()` (split.py), `predict_from_images()` / `make_predict_opt()` (modelpredict.py), `calculate_damage()` (calculation.py).

### pix2pix Integration
The `pix2pix/` directory is a fork of pytorch-CycleGAN-and-pix2pix. **Do not modify pix2pix/ internals** unless fixing a core integration bug. Access is via `sys.path.append('pix2pix')`.

### SAM Fallback
`utils/sam_segmentor.py` uses GroundingDINO + SAM for segmentation but gracefully falls back to OpenCV contour detection on any failure. Model weights auto-download on first use (~3GB total).

## Critical Conventions

- **Image format**: OpenCV BGR convention throughout. White `(255, 255, 255)` background for segmentation/synthesis.
- **Fixed 256x256**: All neural network operations require exactly 256x256 inputs. The `resize_ratio` in CSV converts results back to real-world measurements.
- **Path handling**: Use `os.path.join` or `pathlib.Path` for cross-platform compatibility (project runs on both Windows and Linux).
- **Directory structure**: Follow established naming (`imgs_raw/`, `imgs_standardized/`, `imgs_synthesis/`, `imgs_predicted/`, `imgs_intact/`, `imgs_test/`).
- **calculation.py quirk**: `--notscanned` uses `action='store_false'`, so when the flag is present, `args.notscanned` is `False`.
- **resize_ratio.csv**: Must contain `img_tag` and `img_num` columns. Verify before running calculations.
- **No automated test suite**: Only `test_api.py` exists (manual integration test against a running server).
