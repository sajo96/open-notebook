from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from papermind.api.progress_state import event_to_dict, job_to_dict, progress_registry


router = APIRouter(prefix="/papermind/progress", tags=["papermind-progress"])


class ProgressJobResponse(BaseModel):
    id: str
    notebook_id: str
    paper_name: str
    trigger: str
    stage: str
    progress: int
    source_id: str | None = None
    error_message: str | None = None
    created_at: str
    updated_at: str


class ProgressEventsResponse(BaseModel):
    events: list[dict[str, Any]]
    cursor: int


@router.get("/{job_id}", response_model=ProgressJobResponse)
async def get_progress(job_id: str):
    job = progress_registry.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Progress job not found")
    return job_to_dict(job)


@router.get("/events/list", response_model=ProgressEventsResponse)
async def list_progress_events(
    notebook_id: str,
    after: int = Query(0, ge=0),
):
    events = progress_registry.list_events(notebook_id=notebook_id, after=after)
    payload = [event_to_dict(event) for event in events]
    cursor = payload[-1]["cursor"] if payload else after
    return {"events": payload, "cursor": cursor}
