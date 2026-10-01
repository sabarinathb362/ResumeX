"""
ResumeIQ — FastAPI Application Entry Point.
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging

from backend.config import settings
from backend.database import init_db
from backend.api import resume, jd, analysis, jobs, knowledge, rewrite, recommendations, export, company, editor
from backend.jobs.queue import job_queue

logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    # Startup
    init_db()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)

    # Start background job worker
    worker_task = asyncio.create_task(job_queue.run_worker())

    yield

    # Shutdown
    job_queue.stop()
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="ResumeIQ API",
    description=(
        "Privacy-preserving, local-first resume analysis engine. "
        "Scores ATS compatibility, matches against job descriptions, "
        "and provides evidence-grounded feedback — all on-device."
    ),
    version=settings.app_version,
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(resume.router)
app.include_router(jd.router)
app.include_router(analysis.router)
app.include_router(jobs.router)
app.include_router(knowledge.router)
app.include_router(rewrite.router)
app.include_router(recommendations.router)
app.include_router(export.router)
app.include_router(company.router)
app.include_router(editor.router)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Graceful error handler ensuring informative JSON responses and terminal tracebacks."""
    logger.exception("Unhandled error processing %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={
            "detail": f"Server Error: {str(exc)}",
            "error_type": type(exc).__name__,
            "path": request.url.path,
        },
    )


@app.get("/health/db", tags=["health"])
async def db_health():
    from backend.database import engine
    from sqlalchemy import inspect
    insp = inspect(engine)
    return {
        "status": "healthy",
        "database": engine.url.database,
        "tables": insp.get_table_names(),
    }


@app.get("/", tags=["health"])
async def root():
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "status": "running",
    }


@app.get("/health", tags=["health"])
async def health():
    from backend.nlp import embeddings

    return {
        "status": "healthy",
        "embeddings": {
            "available": embeddings.is_available(),
            "model": settings.embedding_model,
            "device": settings.embedding_device,
        },
    }


@app.get("/health/embeddings", tags=["health"])
async def embeddings_health():
    """Check embedding model availability and warm it up on first call."""
    from backend.nlp import embeddings

    available = embeddings.is_available()
    return {
        "available": available,
        "model": settings.embedding_model if available else None,
        "device": settings.embedding_device if available else None,
        "status": "loaded" if available else "unavailable — falling back to word overlap",
    }
