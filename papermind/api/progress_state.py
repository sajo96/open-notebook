from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Literal
import uuid


UploadStage = Literal[
    "uploading",
    "parsing",
    "atomizing",
    "embedding",
    "note_generating",
    "complete",
    "error",
]


STAGE_PROGRESS: dict[UploadStage, int] = {
    "uploading": 10,
    "parsing": 25,
    "atomizing": 50,
    "embedding": 70,
    "note_generating": 85,
    "complete": 100,
    "error": 100,
}


@dataclass
class UploadJobState:
    id: str
    notebook_id: str
    paper_name: str
    trigger: Literal["manual", "watcher"]
    stage: UploadStage = "uploading"
    progress: int = 10
    source_id: str | None = None
    error_message: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ProgressEvent:
    cursor: int
    event: str
    job_id: str
    notebook_id: str
    payload: dict[str, Any]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ProgressRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._jobs: dict[str, UploadJobState] = {}
        self._events: list[ProgressEvent] = []
        self._cursor: int = 0

    def create_job(self, *, notebook_id: str, paper_name: str, trigger: Literal["manual", "watcher"]) -> UploadJobState:
        job_id = str(uuid.uuid4())
        job = UploadJobState(
            id=job_id,
            notebook_id=notebook_id,
            paper_name=paper_name,
            trigger=trigger,
            stage="uploading",
            progress=STAGE_PROGRESS["uploading"],
        )
        with self._lock:
            self._jobs[job_id] = job
            self._append_event_locked(
                event="job_created",
                job=job,
                payload={"stage": job.stage, "progress": job.progress},
            )
        return job

    def update_job(
        self,
        job_id: str,
        *,
        stage: UploadStage | None = None,
        progress: int | None = None,
        source_id: str | None = None,
        error_message: str | None = None,
    ) -> UploadJobState | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None

            if stage is not None:
                job.stage = stage
            if progress is not None:
                job.progress = max(0, min(100, int(progress)))
            elif stage is not None:
                job.progress = STAGE_PROGRESS.get(stage, job.progress)
            if source_id is not None:
                job.source_id = source_id
            if error_message is not None:
                job.error_message = error_message

            job.updated_at = datetime.now(timezone.utc)
            self._append_event_locked(
                event="job_updated",
                job=job,
                payload={
                    "stage": job.stage,
                    "progress": job.progress,
                    "source_id": job.source_id,
                    "error_message": job.error_message,
                },
            )
            return job

    def get_job(self, job_id: str) -> UploadJobState | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_events(self, notebook_id: str, after: int = 0) -> list[ProgressEvent]:
        with self._lock:
            return [
                event
                for event in self._events
                if event.notebook_id == notebook_id and event.cursor > after
            ]

    def _append_event_locked(self, *, event: str, job: UploadJobState, payload: dict[str, Any]) -> None:
        self._cursor += 1
        self._events.append(
            ProgressEvent(
                cursor=self._cursor,
                event=event,
                job_id=job.id,
                notebook_id=job.notebook_id,
                payload=payload,
            )
        )


def job_to_dict(job: UploadJobState) -> dict[str, Any]:
    data = asdict(job)
    data["created_at"] = job.created_at.isoformat()
    data["updated_at"] = job.updated_at.isoformat()
    return data


def event_to_dict(event: ProgressEvent) -> dict[str, Any]:
    data = asdict(event)
    data["created_at"] = event.created_at.isoformat()
    return data


progress_registry = ProgressRegistry()
