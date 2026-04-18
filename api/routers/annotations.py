from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.notebook import Source
from open_notebook.exceptions import NotFoundError
from api.models import AnnotationCreate, AnnotationResponse

router = APIRouter()


class AnnotationUpdate(BaseModel):
    """Request to update an annotation."""
    color: Optional[str] = None
    comment: Optional[str] = None


def _annotation_record_id(annotation_id: str) -> str:
    if annotation_id.startswith("annotation:"):
        return annotation_id
    return f"annotation:{annotation_id}"


def _to_annotation_response(record: Dict[str, Any]) -> AnnotationResponse:
    return AnnotationResponse(
        id=str(record.get("id", "")),
        source_id=str(record.get("source_id", "")),
        page_number=record.get("page_number", 0),
        annotation_type=record.get("annotation_type", "highlight"),
        selected_text=record.get("selected_text", ""),
        bounding_boxes=record.get("bounding_boxes", []),
        color=record.get("color"),
        comment=record.get("comment"),
        created_at=str(record.get("created_at", "")),
        updated_at=str(record.get("updated_at", "")),
    )


@router.get("/sources/{source_id}/annotations", response_model=List[AnnotationResponse])
async def get_annotations(source_id: str) -> List[AnnotationResponse]:
    """Return all annotations for a given source."""
    try:
        # Validate source exists
        await Source.get(source_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Source not found")

    annotations = await repo_query(
        "SELECT id, source_id, page_number, annotation_type, selected_text, bounding_boxes, color, comment, created_at, updated_at FROM annotation WHERE source_id = $source_id",
        {"source_id": ensure_record_id(source_id)}
    )

    return [_to_annotation_response(ann) for ann in annotations if isinstance(ann, dict)]


@router.post("/sources/{source_id}/annotations", response_model=AnnotationResponse)
async def add_annotation(source_id: str, annotation: AnnotationCreate) -> AnnotationResponse:
    """Create a new annotation."""
    # Validate source exists
    try:
        await Source.get(source_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Source not found")

    annotation_id = str(uuid.uuid4())

    annotation_data = {
        "source_id": ensure_record_id(source_id),
        "page_number": annotation.page_number,
        "annotation_type": annotation.annotation_type,
        "selected_text": annotation.selected_text,
        "bounding_boxes": annotation.bounding_boxes,
        "color": annotation.color,
        "comment": annotation.comment,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }

    created = await repo_query(
        "CREATE type::thing('annotation', $annotation_id) CONTENT $data",
        {"annotation_id": annotation_id, "data": annotation_data},
    )
    if not created:
        raise HTTPException(status_code=500, detail="Failed to create annotation")

    return _to_annotation_response(created[0])


@router.patch("/annotations/{annotation_id}", response_model=AnnotationResponse)
async def update_annotation(annotation_id: str, update: AnnotationUpdate) -> AnnotationResponse:
    """Update an existing annotation."""
    record_id = _annotation_record_id(annotation_id)
    existing = await repo_query(
        "SELECT * FROM $annotation_id",
        {"annotation_id": ensure_record_id(record_id)},
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Annotation not found")

    # Update annotation
    update_data = {k: v for k, v in update.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="No updates provided")

    update_data["updated_at"] = datetime.now(timezone.utc)
    updated = await repo_query(
        "UPDATE $annotation_id MERGE $update RETURN AFTER",
        {
            "annotation_id": ensure_record_id(record_id),
            "update": update_data,
        },
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Annotation not found")

    return _to_annotation_response(updated[0])


@router.delete("/annotations/{annotation_id}")
async def delete_annotation(annotation_id: str):
    """Delete a single annotation."""
    record_id = _annotation_record_id(annotation_id)
    deleted = await repo_query(
        "DELETE $annotation_id RETURN BEFORE",
        {"annotation_id": ensure_record_id(record_id)},
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Annotation not found")

    return {"deleted": annotation_id}


@router.delete("/sources/{source_id}/annotations")
async def clear_all_annotations(source_id: str):
    """Delete all annotations for a source."""
    # Validate source exists
    try:
        await Source.get(source_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Source not found")

    await repo_query(
        "DELETE annotation WHERE source_id = $source_id",
        {"source_id": ensure_record_id(source_id)}
    )

    return {"cleared": source_id}