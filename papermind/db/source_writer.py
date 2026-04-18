import os
import shutil
from pathlib import Path
from typing import Optional

from loguru import logger

from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.config import UPLOADS_FOLDER
from open_notebook.domain.notebook import Asset, Source
from papermind.utils import _normalize_notebook_id


def _persist_source_pdf(pdf_path: str, file_hash: str) -> str:
    source_path = Path(pdf_path).expanduser().resolve()
    uploads_dir = Path(UPLOADS_FOLDER).expanduser().resolve()
    uploads_dir.mkdir(parents=True, exist_ok=True)

    suffix = source_path.suffix.lower() or ".pdf"
    persisted_path = uploads_dir / f"{file_hash}{suffix}"

    if source_path != persisted_path:
        shutil.copy2(source_path, persisted_path)

    return str(persisted_path)


async def create_source_record(
    pdf_path: str,
    notebook_id: str,
    file_hash: str,
    title: Optional[str] = None,
) -> str:
    """
    Create a minimal source stub compatible with Open Notebook source reads.

    The record is created up front so failures later in the pipeline can still be
    surfaced in UI flows that rely on `source` existence.
    """
    normalized_notebook_id = _normalize_notebook_id(notebook_id)
    persisted_pdf_path = _persist_source_pdf(pdf_path, file_hash)

    source = Source(
        title=title or os.path.basename(pdf_path),
        topics=[],
        asset=Asset(file_path=persisted_pdf_path),
    )
    await source.save()

    if not source.id:
        raise RuntimeError("Failed to create source record")

    source_id = str(source.id)

    # Keep notebook association behavior consistent with upstream APIs.
    await source.add_to_notebook(normalized_notebook_id)

    # Persist extra ingestion metadata directly on the source row.
    await repo_query(
        """
        UPDATE type::thing($source_id)
        MERGE {
            type: "pdf",
            file_hash: $file_hash,
            notebook_id: $notebook_id,
            status: "running",
            created_at: time::now()
        }
        """,
        {
            "source_id": source_id,
            "file_hash": file_hash,
            "notebook_id": ensure_record_id(normalized_notebook_id),
        },
    )

    logger.debug(f"Created source stub {source_id} for {pdf_path}")
    return source_id


async def update_source_status(
    source_id: str,
    status: str,
    title: Optional[str] = None,
    full_text: Optional[str] = None,
) -> None:
    """Update source pipeline status and optionally set title."""
    merge_payload = {
        "status": status,
    }
    if title is not None:
        merge_payload["title"] = title
    if full_text is not None:
        merge_payload["full_text"] = full_text

    await repo_query(
        """
        UPDATE type::thing($source_id)
        MERGE $merge_payload
        """,
        {
            "source_id": source_id,
            "merge_payload": merge_payload,
        },
    )
