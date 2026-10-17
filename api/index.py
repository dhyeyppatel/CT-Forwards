"""
api/index.py — Gateway entry point for Vercel when deployed from the repository root.
Delegates cleanly to serverless.api.index.app.
"""
import sys
from pathlib import Path

# Add serverless folder to sys.path
_serverless_dir = Path(__file__).resolve().parent.parent / "serverless"
if str(_serverless_dir) not in sys.path:
    sys.path.insert(0, str(_serverless_dir))

from serverless.api.index import app
