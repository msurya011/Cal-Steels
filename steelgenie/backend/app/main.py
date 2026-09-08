"""
CalSteel Estimator — FastAPI Application Factory
================================================
This is the new structured backend entry point.
The legacy main.py is preserved for backward compatibility.
Start this with:  uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import sys as _sys
for _s in (_sys.stdout, _sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
import os
import sys
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.api.v1.router import api_router

# Ensure backend directory is in path so existing modules (main.py, brace_classifier, etc.)
# can still be imported by the workers.
_BACKEND_DIR = Path(__file__).parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup: clean up stale running/queued jobs left by previous server sessions
    try:
        from app.services.database import get_db, bulk_update_by_id
        db = get_db()
        stale_jobs = db.table("jobs").select("id, status").in_("status", ["running", "queued"]).execute().data or []
        if stale_jobs:
            logger.info("Cleaning up %d stale running/queued job(s) from prior session", len(stale_jobs))
            updates = {
                j["id"]: {
                    "status": "failed",
                    "error": "Server was restarted while this job was in progress",
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                }
                for j in stale_jobs
            }
            bulk_update_by_id("jobs", updates)
    except Exception as exc:
        logger.warning("Could not clean up stale jobs on startup: %s", exc)

    yield


def create_app() -> FastAPI:
    cfg = get_settings()

    app = FastAPI(
        title="CalSteel Estimator API",
        description="Structural steel estimating platform — PDF takeoff, member detection, BOM, 3D model.",
        version="1.0.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_no_cache_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    # ── API routers ───────────────────────────────────────────────────────────
    app.include_router(api_router)

    # ── File serving (local storage) ──────────────────────────────────────────
    upload_dir = Path(cfg.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    @app.get("/api/v1/files/{path:path}")
    async def serve_file(path: str):
        """Serve locally stored files (thumbnails, page images, exports)."""
        safe_path = path.lstrip("/\\").replace("..", "")
        full_path = upload_dir / safe_path
        if not full_path.exists():
            return JSONResponse({"detail": "File not found"}, status_code=404)
        return FileResponse(str(full_path))

    # ── Health check ──────────────────────────────────────────────────────────
    @app.get("/health")
    async def health():
        return {"status": "ok", "version": "1.0.0"}

    # ── Legacy compatibility — forward old endpoints to new API ────────────────
    # The old frontend still calls /upload, /analyse, /saved-projects, etc.
    # We import the legacy app and mount it at /legacy to keep backward compat.
    try:
        import importlib.util
        legacy_path = str(_BACKEND_DIR / "main.py")
        spec = importlib.util.spec_from_file_location("legacy_main", legacy_path)
        if spec and spec.loader:
            legacy_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(legacy_module)
            legacy_app = legacy_module.app
            app.mount("/legacy", legacy_app)
            logger.info("Legacy main.py mounted at /legacy")
    except Exception as exc:
        logger.warning("Could not mount legacy app: %s", exc)

    logger.info(
        "CalSteel API started — storage=%s env=%s brace_extraction=%s",
        cfg.storage_backend,
        cfg.environment,
        cfg.brace_extraction_enabled,
    )

    return app


app = create_app()
