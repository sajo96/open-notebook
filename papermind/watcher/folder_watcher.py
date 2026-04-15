import asyncio
import os
from pathlib import Path

import httpx
from loguru import logger
from watchdog.events import FileCreatedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from papermind.models import WatchedFolder


async def check_file_stability(file_path: str, wait_time: int = 2) -> bool:
    """Wait for file size to stabilize to ensure it's fully written."""
    p = Path(file_path)
    if not p.exists():
        return False

    last_size = -1
    for _ in range(10):  # Max 10 checks
        try:
            current_size = p.stat().st_size
            if current_size == last_size and current_size > 0:
                # Stable! Wait one more sleep to be absolutely sure locks are released
                await asyncio.sleep(wait_time)
                return True
            last_size = current_size
        except OSError:
            pass
        await asyncio.sleep(wait_time)

    return False


async def ingest_pdf(pdf_path: str, notebook_id: str):
    """
    BYPASSED: PaperMind uses /api/papermind/ingest instead of Open Notebook
    source ingestion endpoints.
    """
    logger.info(f"Checking new PDF at {pdf_path}")
    wait_time = int(os.environ.get("PAPERMIND_FILE_STABILITY_SECONDS", "2"))
    is_stable = await check_file_stability(pdf_path, wait_time=wait_time)
    if not is_stable:
        logger.warning(f"File {pdf_path} did not stabilize in time, skipping.")
        return

    API_BASE = os.environ.get("PAPERMIND_API_BASE", "http://localhost:5055")
    logger.info(f"Using notebook_id: {notebook_id}")
    logger.info(f"Calling /api/papermind/upload for {pdf_path}")

    async with httpx.AsyncClient(timeout=120.0) as client:
        with open(pdf_path, "rb") as f:
            res = await client.post(
                f"{API_BASE}/api/papermind/upload",
                data={
                    "notebook_id": notebook_id,
                    "triggered_by": "watcher",
                },
                files={"file": (Path(pdf_path).name, f, "application/pdf")},
            )
        logger.info(f"Response status: {res.status_code}")
        data = res.json() if res.text else {}

        if data.get("status") == "duplicate":
            logger.info(f"Skipped duplicate: {pdf_path}")
            return

        if res.status_code == 200:
            logger.info(
                f"Ingested: {data.get('title', 'Unknown Title')} "
                f"({data.get('atom_count', 0)} atoms, "
                f"{data.get('similarity_edge_count', 0)} edges)"
            )
            return

        logger.info(f"Response body: {res.text}")
        logger.error(
            f"Ingest failed [{data.get('error_stage', 'unknown')}] "
            f"for {pdf_path}: {data.get('detail', res.text)}"
        )


class PDFHandler(FileSystemEventHandler):
    """
    Fires when a new file is created in the watched directory.
    Only processes .pdf files.
    """

    def __init__(self, notebook_id: str, loop: asyncio.AbstractEventLoop):
        self.notebook_id = notebook_id
        self.loop = loop
        super().__init__()

    def on_created(self, event):
        if event.is_directory:
            return
        if event.src_path.lower().endswith(".pdf"):
            logger.info(f"New PDF detected: {event.src_path}")
            asyncio.run_coroutine_threadsafe(
                ingest_pdf(event.src_path, self.notebook_id), self.loop
            )


class FolderWatcher:
    """
    Manages watchdog Observers per watched folder.
    Reads WatchedFolder records from SurrealDB on startup via sync logic or triggers in FastAPI startup.
    """

    def __init__(self):
        self._observers = {}
        self._loop = None

    async def start(self):
        """Starts monitoring based on configured WatchedFolders."""
        if not os.environ.get("PAPERMIND_WATCH_ENABLED", "true").lower() in ("1", "true"):
            logger.info("FolderWatcher disabled via PAPERMIND_WATCH_ENABLED")
            return

        self._loop = asyncio.get_event_loop()
        
        # In a real SurrealDB flow we could read the WatchedFolder table on boot
        try:
            folders = await WatchedFolder.get_all()
            for folder in folders:
                if folder.active:
                    self.add_folder_watch(
                        folder.path, folder.notebook_id, folder.recursive
                    )
            logger.info(f"FolderWatcher started with {len(self._observers)} active feeds.")
        except Exception as e:
            logger.error(f"Failed to initialize folder watchers: {e}")

    def add_folder_watch(self, path: str, notebook_id: str, recursive: bool):
        if path in self._observers:
            logger.warning(f"Already watching {path}")
            return
            
        p = Path(path)
        if not p.exists():
            logger.warning(f"Watched path {path} does not exist, creating it.")
            p.mkdir(parents=True, exist_ok=True)
            
        observer = Observer()
        handler = PDFHandler(notebook_id, self._loop)
        observer.schedule(handler, path, recursive=recursive)
        observer.start()
        self._observers[path] = observer
        logger.info(f"Started watching folder: {path} for notebook: {notebook_id}")

    async def add_folder(self, path: str, notebook_id: str, recursive: bool):
        """Insert or reactivate watched folder in DB and start its observer."""
        existing = await WatchedFolder.get_all()
        for folder in existing:
            if folder.path == path:
                folder.notebook_id = notebook_id
                folder.recursive = recursive
                folder.active = True
                await folder.save()
                self.add_folder_watch(path, notebook_id, recursive)
                return folder

        folder = WatchedFolder(
            path=path,
            notebook_id=notebook_id,
            recursive=recursive,
            active=True,
        )
        await folder.save()
        self.add_folder_watch(path, notebook_id, recursive)
        return folder

    def remove_folder_watch(self, path: str):
        if path in self._observers:
            observer = self._observers.pop(path)
            observer.stop()
            observer.join()
            logger.info(f"Stopped watching folder: {path}")

    async def remove_folder(self, folder_id: str):
        """Mark watched folder inactive in DB and stop its observer."""
        folder = await WatchedFolder.get(folder_id)
        if not folder:
            return None

        self.remove_folder_watch(folder.path)
        folder.active = False
        await folder.save()
        return folder

    async def stop(self):
        """Cleanly stops all observers."""
        for path, observer in list(self._observers.items()):
            observer.stop()
            observer.join()
            logger.info(f"Stopped watching {path}")
        self._observers.clear()

watcher_instance = FolderWatcher()
