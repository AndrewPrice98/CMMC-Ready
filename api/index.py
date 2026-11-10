"""Vercel entry point: serves the CMMC Ready FastAPI app as a Python serverless function.

vercel.json rewrites every /api/* request here; FastAPI routes on the original path.
Each function instance builds its own SQLite database in /tmp from
backend/data/demo_fixture.json (the fictional demo organization) on cold start, so the
hosted site is a self-contained, read-only demo.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

# The admin variables (CMMCREADY_ADMIN_PASSWORD_HASH, CMMCREADY_SECRET_KEY) are optional here:
# without them visitors browse as a read-only guest and nobody can sign in.
# Serverless defaults; any of these can be overridden in Vercel's environment settings.
os.environ.setdefault("CMMCREADY_DB", "/tmp/cmmcready.db")  # /tmp is the only writable path
os.environ.setdefault("CMMCREADY_DEMO", "true")
os.environ.setdefault("CMMCREADY_TRUST_PROXY", "true")  # Vercel sets X-Forwarded-For itself
os.environ.setdefault("CMMCREADY_MAX_UPLOAD_MB", "4")  # Vercel caps request bodies at 4.5 MB

from cmmcready.api import app  # noqa: E402
from cmmcready.demo import ensure_seeded  # noqa: E402

ensure_seeded()

__all__ = ["app"]
