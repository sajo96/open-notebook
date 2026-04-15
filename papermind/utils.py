"""Shared utilities for the papermind package."""

from pathlib import Path
from typing import Any, Dict, List

from loguru import logger


def _normalize_notebook_id(notebook_id: str) -> str:
    raw = str(notebook_id or "").strip()
    if not raw:
        raise ValueError("notebook_id is required")
    return raw if ":" in raw else f"notebook:{raw}"


def _rows_from_query_result(query_result: Any) -> List[Dict[str, Any]]:
    if not query_result:
        return []

    first = query_result[0]
    if isinstance(first, dict) and isinstance(first.get("result"), list):
        return first["result"]
    if isinstance(first, list):
        return first
    if isinstance(query_result, list) and all(isinstance(x, dict) for x in query_result):
        return query_result
    return []


def validate_pdf_path(path: str) -> str:
    """Validate that a PDF path is safe and exists.

    Returns the resolved absolute path.
    Raises ValueError if the path doesn't end with .pdf, doesn't exist, or isn't a file.
    """
    resolved = Path(path).expanduser().resolve()

    if not str(resolved).lower().endswith(".pdf"):
        raise ValueError(f"Invalid file extension: {path}")

    if not resolved.exists():
        raise ValueError(f"File does not exist: {path}")

    if not resolved.is_file():
        raise ValueError(f"Path is not a file: {path}")

    return str(resolved)


def validate_directory_path(path: str) -> str:
    """Validate that a directory path is safe and exists.

    Returns the resolved absolute path.
    Raises ValueError if the path doesn't exist or isn't a directory.
    """
    resolved = Path(path).expanduser().resolve()

    if not resolved.exists():
        raise ValueError(f"Directory does not exist: {path}")

    if not resolved.is_dir():
        raise ValueError(f"Path is not a directory: {path}")

    return str(resolved)


def safe_error_detail(message: str) -> dict:
    """Return a sanitized error dict safe for HTTP responses.

    Logs the real error internally but returns a generic message
    to avoid leaking internal details to clients.
    """
    logger.error(f"Internal error (sanitized): {message}")
    return {"detail": "An internal error occurred. Check server logs for details."}
