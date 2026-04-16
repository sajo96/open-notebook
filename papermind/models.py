from datetime import datetime
from typing import ClassVar, Dict, List, Optional, Union, Any, Literal

from loguru import logger
from open_notebook.domain.base import ObjectModel
from open_notebook.database.repository import ensure_record_id
from pydantic import Field, field_validator
from surrealdb import RecordID


class AcademicPaper(ObjectModel):
    table_name: ClassVar[str] = "academic_paper"

    source_id: Union[str, Any]
    title: str
    title_source: Optional[
        Literal["crossref", "metadata", "scholarly", "heuristic", "raw_text", "llm", "unknown", "manual"]
    ] = None
    title_confidence: Optional[float] = None
    authors: List[str] = []
    abstract: Optional[str] = None
    doi: Optional[str] = None
    year: Optional[int] = None
    keywords: List[str] = []
    sections: Dict[str, str] = {}
    raw_references: List[str] = []
    command: Optional[Union[str, RecordID]] = Field(
        default=None,
        description="Link to surreal-commands processing job for current pipeline stage",
    )
    pipeline_stage: Optional[str] = Field(
        default=None,
        description="Current stage: ingesting|parsing|embedding|notes|graph|done|failed",
    )
    stage_updated_at: Optional[datetime] = None
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None

    # ── RecordID validators ───────────────────────────────────────────────────
    # parse_record_ids() in repository.py converts every RecordID to a plain
    # string before returning query results.  These validators convert them back
    # so that paper.save() sends the correct record<…> type to SurrealDB.

    @field_validator("source_id", mode="before")
    @classmethod
    def parse_source_id(cls, value: Any) -> Any:
        if isinstance(value, str) and value:
            return ensure_record_id(value)
        return value

    @field_validator("command", mode="before")
    @classmethod
    def parse_command(cls, value: Any) -> Any:
        if isinstance(value, str) and value:
            return ensure_record_id(value)
        return value

    # ── Status helpers ────────────────────────────────────────────────────────

    async def get_status(self) -> Optional[str]:
        """Query surreal_commands for the current job status."""
        if not self.command:
            return None
        try:
            from surreal_commands import get_command_status

            status = await get_command_status(str(self.command))
            return status.status if status else "unknown"
        except Exception as e:
            logger.warning(f"Status fetch failed for {self.command}: {e}")
            return "unknown"

    async def get_processing_progress(self) -> Dict[str, Any]:
        """Return pipeline stage + command execution metadata for UI polling."""
        if not self.command:
            return {
                "pipeline_stage": self.pipeline_stage,
                "job_status": None,
                "stage_updated_at": self.stage_updated_at,
                "error_message": self.error_message,
                "processing_info": None,
            }

        try:
            from surreal_commands import get_command_status

            status_result = await get_command_status(str(self.command))
            if not status_result:
                return {
                    "pipeline_stage": self.pipeline_stage,
                    "job_status": "unknown",
                    "stage_updated_at": self.stage_updated_at,
                    "error_message": self.error_message,
                    "processing_info": None,
                }

            result = getattr(status_result, "result", None)
            execution_metadata = (
                result.get("execution_metadata", {}) if isinstance(result, dict) else {}
            )

            return {
                "pipeline_stage": self.pipeline_stage,
                "job_status": status_result.status,
                "stage_updated_at": self.stage_updated_at,
                "error_message": self.error_message or getattr(status_result, "error_message", None),
                "processing_info": {
                    "started_at": execution_metadata.get("started_at"),
                    "completed_at": execution_metadata.get("completed_at"),
                    "result": result,
                },
            }
        except Exception as e:
            logger.warning(f"Progress fetch failed for {self.command}: {e}")
            return {
                "pipeline_stage": self.pipeline_stage,
                "job_status": "unknown",
                "stage_updated_at": self.stage_updated_at,
                "error_message": self.error_message,
                "processing_info": None,
            }


class Atom(ObjectModel):
    table_name: ClassVar[str] = "atom"

    paper_id: Union[str, Any]
    section_label: str
    content: str
    embedding: Optional[List[float]] = None
    created_at: Optional[datetime] = None

    @field_validator("paper_id", mode="before")
    @classmethod
    def parse_paper_id(cls, value: Any) -> Any:
        if isinstance(value, str) and value:
            return ensure_record_id(value)
        return value


class Concept(ObjectModel):
    table_name: ClassVar[str] = "concept"

    label: str
    description: Optional[str] = None
    created_at: Optional[datetime] = None


class Cites(ObjectModel):
    table_name: ClassVar[str] = "cites"

    in_id: Union[str, Any]
    out_id: Union[str, Any]
    confidence: float = 1.0

    @field_validator("in_id", "out_id", mode="before")
    @classmethod
    def parse_relation_ids(cls, value: Any) -> Any:
        if isinstance(value, str) and value:
            return ensure_record_id(value)
        return value


class SimilarTo(ObjectModel):
    table_name: ClassVar[str] = "similar_to"

    in_id: Union[str, Any]
    out_id: Union[str, Any]
    similarity_score: float

    @field_validator("in_id", "out_id", mode="before")
    @classmethod
    def parse_relation_ids(cls, value: Any) -> Any:
        if isinstance(value, str) and value:
            return ensure_record_id(value)
        return value


class TaggedWith(ObjectModel):
    table_name: ClassVar[str] = "tagged_with"

    in_id: Union[str, Any]
    out_id: Union[str, Any]

    @field_validator("in_id", "out_id", mode="before")
    @classmethod
    def parse_relation_ids(cls, value: Any) -> Any:
        if isinstance(value, str) and value:
            return ensure_record_id(value)
        return value


class WatchedFolder(ObjectModel):
    table_name: ClassVar[str] = "watched_folder"

    path: str
    notebook_id: Union[str, Any]
    recursive: bool = False
    active: bool = True
    created_at: Optional[datetime] = None

    @field_validator("notebook_id", mode="before")
    @classmethod
    def parse_notebook_id(cls, value: Any) -> Any:
        if isinstance(value, str) and value:
            return ensure_record_id(value)
        return value
