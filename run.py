"""
run.py — Single entry point for IITIIMJobAssistant.

Usage:
    python run.py              # Start the Flask server
    python run.py --port 8000  # Custom port
"""
import os
import sys

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
except ImportError:
    pass

# Signal that we're using the app factory
os.environ["_APP_FACTORY_USED"] = "1"

import job_seeker_agent.runner
from core.app import create_app

app = create_app()

if __name__ == "__main__":
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 5000
    print("=" * 60)
    print("  IITIIMJobAssistant")
    print(f"  http://127.0.0.1:{port}")
    print(f"  http://127.0.0.1:{port}/login")
    print(f"  http://127.0.0.1:{port}/signup")
    print(f"  http://127.0.0.1:{port}/dashboard")
    print(f"  http://127.0.0.1:{port}/admin")
    print("=" * 60)
    app.run(host="0.0.0.0", port=port, debug=False)
