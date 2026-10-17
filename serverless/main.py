"""
main.py — Local development and test runner for CT-Forwards Serverless.

Usage:
    python main.py

Or directly using uvicorn:
    uvicorn api.index:app --reload --port 8000
"""
import os
import uvicorn

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    print(f"🚀 Starting CT-Forwards Serverless API on http://localhost:{port}")
    uvicorn.run("api.index:app", host="0.0.0.0", port=port, reload=True)
