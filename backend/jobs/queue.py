"""
Phase 0 — Background Job Queue.
Single-worker, SQLite-backed job table with SSE progress streaming.
"""
import asyncio
import uuid
import json
import traceback
from datetime import datetime, timezone
from typing import Callable, Any, Optional
from collections import defaultdict

from backend.database import SessionLocal
from backend.models.db_models import BackgroundJob


# ── In-memory progress bus (for SSE) ─────────────────────────────

_progress_subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)


async def subscribe_progress(job_id: str) -> asyncio.Queue:
    """Subscribe to progress updates for a job."""
    queue: asyncio.Queue = asyncio.Queue()
    _progress_subscribers[job_id].append(queue)
    return queue


def unsubscribe_progress(job_id: str, queue: asyncio.Queue):
    """Unsubscribe from progress updates."""
    if job_id in _progress_subscribers:
        _progress_subscribers[job_id] = [
            q for q in _progress_subscribers[job_id] if q is not queue
        ]


async def _publish_progress(job_id: str, progress: float, message: str = ""):
    """Publish a progress update to all subscribers."""
    event = {"progress": progress, "message": message, "job_id": job_id}
    for queue in _progress_subscribers.get(job_id, []):
        await queue.put(event)


async def _publish_complete(job_id: str, result: Any = None, error: str | None = None):
    """Publish a completion event."""
    event = {
        "progress": 1.0,
        "message": "complete" if not error else f"error: {error}",
        "job_id": job_id,
        "done": True,
        "result": result,
        "error": error,
    }
    for queue in _progress_subscribers.get(job_id, []):
        await queue.put(event)


# ── Job queue ────────────────────────────────────────────────────

class JobQueue:
    """Simple single-worker async job queue backed by SQLite."""

    def __init__(self):
        self._running = False
        self._handlers: dict[str, Callable] = {}

    def register_handler(self, job_type: str, handler: Callable):
        """Register a handler function for a job type."""
        self._handlers[job_type] = handler

    def enqueue(self, job_type: str, payload: dict) -> str:
        """Add a job to the queue. Returns the job ID."""
        db = SessionLocal()
        try:
            job = BackgroundJob(
                id=str(uuid.uuid4()),
                job_type=job_type,
                payload=payload,
                status="queued",
            )
            db.add(job)
            db.commit()
            return job.id
        finally:
            db.close()

    def get_job(self, job_id: str) -> Optional[dict]:
        """Get job status."""
        db = SessionLocal()
        try:
            job = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
            if not job:
                return None
            return {
                "id": job.id,
                "job_type": job.job_type,
                "status": job.status,
                "progress": job.progress,
                "result": job.result,
                "error": job.error,
                "created_at": str(job.created_at),
            }
        finally:
            db.close()

    async def process_next(self):
        """Process the next queued job (single-worker)."""
        db = SessionLocal()
        try:
            job = (
                db.query(BackgroundJob)
                .filter(BackgroundJob.status == "queued")
                .order_by(BackgroundJob.created_at)
                .first()
            )
            if not job:
                return False

            handler = self._handlers.get(job.job_type)
            if not handler:
                job.status = "failed"
                job.error = f"No handler for job type: {job.job_type}"
                db.commit()
                return True

            job.status = "running"
            db.commit()

            try:
                # Run handler with progress callback
                async def progress_cb(p: float, msg: str = ""):
                    job.progress = p
                    job.updated_at = datetime.now(timezone.utc)
                    db.commit()
                    await _publish_progress(job.id, p, msg)

                if asyncio.iscoroutinefunction(handler):
                    result = await handler(job.payload, progress_cb)
                else:
                    result = handler(job.payload, None)

                job.status = "done"
                job.progress = 1.0
                job.result = result if isinstance(result, dict) else {"result": str(result)}
                db.commit()
                await _publish_complete(job.id, result=job.result)

            except Exception as e:
                job.status = "failed"
                job.error = f"{type(e).__name__}: {str(e)}"
                db.commit()
                await _publish_complete(job.id, error=job.error)

            return True
        finally:
            db.close()

    async def run_worker(self):
        """Run the single-worker loop."""
        self._running = True
        while self._running:
            processed = await self.process_next()
            if not processed:
                await asyncio.sleep(1)  # Poll interval

    def stop(self):
        self._running = False


# Singleton
job_queue = JobQueue()
