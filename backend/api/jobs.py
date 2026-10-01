"""
API routes — SSE progress streaming (Phase 0).
GET /api/jobs/{job_id}/events
"""
import asyncio
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.jobs.queue import job_queue, subscribe_progress, unsubscribe_progress

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/{job_id}", summary="Get job status")
async def get_job_status(job_id: str):
    job = job_queue.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.get("/{job_id}/events", summary="SSE progress stream for a job")
async def job_events(job_id: str):
    """
    Server-Sent Events endpoint for real-time job progress.
    Streams progress updates until the job completes or fails.
    """
    job = job_queue.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    async def event_generator():
        queue = await subscribe_progress(job_id)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30)
                    import json
                    yield f"data: {json.dumps(event)}\n\n"
                    if event.get("done"):
                        break
                except asyncio.TimeoutError:
                    # Send keepalive
                    yield f": keepalive\n\n"
        finally:
            unsubscribe_progress(job_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
