import os
from typing import Optional

from loguru import logger

from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.notebook import Asset, Source
from papermind.utils import _normalize_notebook_id


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

    source = Source(
        title=title or os.path.basename(pdf_path),
        topics=[],
        asset=Asset(file_path=pdf_path),
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
            status: "processing",
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
