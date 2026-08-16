"""
InvoiceFlow AI — FastAPI Application Entry Point
"""

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db.database import init_db, close_db
from app.api.routes import router
from app.webhooks.resend import router as webhooks_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-30s │ %(levelname)-7s │ %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info("  InvoiceFlow AI — AP Prototype")
    logger.info("=" * 60)

    init_db()

    if settings.auto_seed_on_startup and not settings.database_url:
        from app.db.seed_data import seed_database
        seed_database()
    else:
        logger.info("Skipping auto-seed (production mode — run scripts/reset_db.py)")

    settings.upload_path.mkdir(parents=True, exist_ok=True)
    logger.info(f"Provider priority: {settings.provider_list}")
    logger.info(f"Storage: {'Vercel Blob' if settings.blob_read_write_token else 'local'}")
    logger.info(f"Database: {'Postgres' if settings.database_url else settings.db_path}")

    yield
    close_db()
    logger.info("InvoiceFlow AI shut down")


app = FastAPI(
    title="InvoiceFlow AI",
    description="Intelligent Invoice Processing & Decision Engine",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(webhooks_router, prefix="/api")

if not settings.blob_read_write_token:
    uploads_dir = settings.upload_path
    uploads_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")

# Inngest serve endpoint when configured
try:
    from app.jobs.inngest_handler import get_inngest

    inngest_client = get_inngest()
    if inngest_client is not None:
        import inngest.fast_api

        inngest.fast_api.serve(app, inngest_client)
except Exception as exc:
    logger.debug("Inngest not mounted: %s", exc)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )
