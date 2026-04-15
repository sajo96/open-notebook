from typing import List, Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel
from loguru import logger

from papermind.models import WatchedFolder
from papermind.utils import _normalize_notebook_id, validate_directory_path, safe_error_detail
from papermind.watcher.folder_watcher import watcher_instance

router = APIRouter(prefix="/papermind/watch", tags=["papermind-watcher"])

class WatchRequest(BaseModel):
    path: str
    notebook_id: str
    recursive: bool = False

class WatchResponse(BaseModel):
    id: str
    path: str
    notebook_id: str
    recursive: bool
    active: bool
    created_at: str


class ActionResponse(BaseModel):
    status: str
    message: str

@router.post("", response_model=WatchResponse)
async def add_watched_folder(req: WatchRequest, background_tasks: BackgroundTasks):
    """Add a new watched folder to the database and start the watcher."""
    try:
        validate_directory_path(req.path)
        folder = await watcher_instance.add_folder(
            req.path,
            req.notebook_id,
            req.recursive,
        )
        
        return WatchResponse(
            id=folder.id,
            path=folder.path,
            notebook_id=folder.notebook_id,
            recursive=folder.recursive,
            active=folder.active,
            created_at=(
                folder.created_at.isoformat()
                if getattr(folder, "created_at", None)
                else (folder.created.isoformat() if hasattr(folder, "created") and folder.created else "")
            ),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to add watched folder")
        raise HTTPException(status_code=500, detail=safe_error_detail(str(e)))


@router.delete("/{folder_id}", response_model=ActionResponse)
async def remove_watched_folder(folder_id: str):
    """Remove a watched folder from DB and stop its observer."""
    try:
        folder = await watcher_instance.remove_folder(folder_id)
        if not folder:
            raise HTTPException(status_code=404, detail="Folder not found")

        return ActionResponse(
            status="success",
            message=f"Stopped watching {folder.path}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to remove watched folder")
        raise HTTPException(status_code=500, detail=safe_error_detail(str(e)))


@router.get("", response_model=List[WatchResponse])
async def list_watched_folders(notebook_id: Optional[str] = Query(None)):
    """List watched folders, optionally scoped to a specific notebook."""
    try:
        folders = [f for f in await WatchedFolder.get_all() if f.active]
        if notebook_id:
            expected_notebook_id = _normalize_notebook_id(notebook_id)
            folders = [f for f in folders if str(f.notebook_id) == expected_notebook_id]

        return [
            WatchResponse(
                id=f.id,
                path=f.path,
                notebook_id=f.notebook_id,
                recursive=f.recursive,
                active=f.active,
                created_at=(
                    f.created_at.isoformat()
                    if getattr(f, "created_at", None)
                    else (f.created.isoformat() if hasattr(f, "created") and f.created else "")
                ),
            ) for f in folders
        ]
    except Exception as e:
        logger.exception("Failed to list watched folders")
        raise HTTPException(status_code=500, detail=safe_error_detail(str(e)))


@router.post("/{folder_id}/scan", response_model=ActionResponse)
async def trigger_scan(folder_id: str, background_tasks: BackgroundTasks):
    """Manually trigger a full scan of the folder and process existing PDFs."""
    from pathlib import Path
    from papermind.watcher.folder_watcher import ingest_pdf
    import asyncio

    try:
        folder = await WatchedFolder.get(folder_id)
        if not folder:
            raise HTTPException(status_code=404, detail="Folder not found")

        p = Path(folder.path)
        if not p.exists() or not p.is_dir():
            raise HTTPException(status_code=404, detail="Physical directory not found")

        pdfs = list(p.rglob("*.pdf") if folder.recursive else p.glob("*.pdf"))

        async def process_all_pdfs():
            normalized_notebook_id = _normalize_notebook_id(str(folder.notebook_id))
            for pdf in pdfs:
                await ingest_pdf(str(pdf), normalized_notebook_id)
                await asyncio.sleep(1)

        background_tasks.add_task(process_all_pdfs)
        return ActionResponse(
            status="success",
            message=f"Scan queued for {len(pdfs)} files in {folder.path}",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to trigger scan")
        raise HTTPException(status_code=500, detail=safe_error_detail(str(e)))
