"""
Vercel serverless function for Free AI Gateway.
Direct wrapper for FastAPI app with proper ASGI handling.
"""
import os
import sys
import traceback

os.chdir('/vercel/path0')
sys.path.insert(0, '/vercel/path0')

# Set environment to skip heavy initialization
os.environ.setdefault('VERCEL', '1')

# Catch import errors
try:
    from app.main import app as application
    print("App imported successfully", file=sys.stderr)
except Exception as e:
    print(f"Import error: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    raise

# Export handler for Vercel Python runtime
handler = application
app = application