from typing import List, Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from loguru import logger

from papermind.models import WatchedFolder
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

@router.post("", response_model=WatchResponse)
async def add_watched_folder(req: WatchRequest, background_tasks: BackgroundTasks):
    """Add a new watched folder to the database and start the watcher."""
    try:
        # Check if already exists
        existing = await WatchedFolder.get_all()
        for f in existing:
            if f.path == req.path:
                # Instead of erroring out immediately, let's clean up inactive or old records if they overlap.
                # Since we changed DELETE to actually delete, there shouldn't be valid overlapping active ones.
                logger.info(f"Cleaning up existing watcher for {req.path}")
                watcher_instance.remove_folder_watch(f.path)
                await f.delete()
                
        folder = WatchedFolder(
            path=req.path,
            notebook_id=req.notebook_id,
            recursive=req.recursive,
            active=True
        )
        await folder.save()
        
        # Start immediately in the background
        watcher_instance.add_folder_watch(folder.path, folder.notebook_id, folder.recursive)
        
        return WatchResponse(
            id=folder.id,
            path=folder.path,
            notebook_id=folder.notebook_id,
            recursive=folder.recursive,
            active=folder.active,
            created_at=folder.created.isoformat() if hasattr(folder, 'created') and folder.created else ""
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to add watched folder")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{folder_id}")
async def remove_watched_folder(folder_id: str):
    """Remove a watched folder from DB and stop its watcher."""
    try:
        folder = await WatchedFolder.get(folder_id)
        if not folder:
            raise HTTPException(status_code=404, detail="Folder not found")
            
        watcher_instance.remove_folder_watch(folder.path)
        await folder.delete()
        
        return {"status": "success", "message": f"Stopped watching {folder.path}"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to remove watched folder")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=List[WatchResponse])
async def list_watched_folders():
    """List all watched folders and their status."""
    try:
        folders = await WatchedFolder.get_all()
        return [
            WatchResponse(
                id=f.id,
                path=f.path,
                notebook_id=f.notebook_id,
                recursive=f.recursive,
                active=f.active,
                created_at=f.created.isoformat() if hasattr(f, 'created') and f.created else ""
            ) for f in folders
        ]
    except Exception as e:
        logger.exception("Failed to list watched folders")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{folder_id}/scan")
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
            for pdf in pdfs:
                await ingest_pdf(str(pdf), folder.notebook_id)
                await asyncio.sleep(1) # stagger logic
                
        background_tasks.add_task(process_all_pdfs)
        return {"status": "success", "message": f"Scan queued for {len(pdfs)} files in {folder.path}"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to trigger scan")
        raise HTTPException(status_code=500, detail=str(e))
