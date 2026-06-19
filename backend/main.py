"""
HerbiEstim Backend — Entry point.

Usage:
    python -m backend.main
    python backend/main.py

Or via uvicorn directly:
    python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000
"""

import sys
import os

# Ensure project root is in path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.app:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        workers=1,
    )
