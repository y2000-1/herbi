try:
    import groundingdino
    print("GroundingDINO OK")
except Exception as e:
    print(f"GroundingDINO FAIL: {e}")

try:
    import segment_anything
    print("segment_anything OK")
except Exception as e:
    print(f"segment_anything FAIL: {e}")

import os
sam_path = r"D:\MyProject\Python\HerbiEstim-main\model_saved\sam_vit_h_4b8939.pth"
gdino_path = r"D:\MyProject\Python\HerbiEstim-main\model_saved\groundingdino_swint_ogc.pth"
print(f"SAM weights exist: {os.path.exists(sam_path)} ({os.path.getsize(sam_path)//1024//1024} MB)" if os.path.exists(sam_path) else "SAM weights: MISSING")
print(f"GDINO weights exist: {os.path.exists(gdino_path)} ({os.path.getsize(gdino_path)//1024//1024} MB)" if os.path.exists(gdino_path) else "GDINO weights: MISSING")

import torch
print(f"CUDA available: {torch.cuda.is_available()}")
print(f"PyTorch version: {torch.__version__}")
