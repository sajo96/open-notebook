import os
import re
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from loguru import logger
import httpx
from pathlib import Path
from typing import Any
from urllib.parse import quote

from papermind.models import AcademicPaper
from papermind.parsers.academic_pdf_parser import AcademicPDFParser
from open_notebook.database.repository import ensure_record_id, repo_query

router = APIRouter(prefix="/papermind/parse_academic", tags=["papermind-parser"])

# Use port 5055 by default since this might run in the background worker or fastapi app
API_BASE = os.environ.get("PAPERMIND_API_BASE", "http://localhost:5055")

class ParseRequest(BaseModel):
    source_id: str

class ParseResponse(BaseModel):
    academic_paper_id: str
    title: str
    authors: list[str]
    section_count: int
    doi: str | None


def _normalize_section_key(key: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")
    return normalized or "section"


def _normalize_sections(sections: object) -> dict[str, str]:
    if not isinstance(sections, dict):
        return {}

    normalized: dict[str, str] = {}
    for raw_key, raw_value in sections.items():
        key = _normalize_section_key(str(raw_key))
        value = str(raw_value or "").strip()
        if not value:
            continue

        # De-duplicate sanitized keys by suffixing an index.
        final_key = key
        idx = 2
        while final_key in normalized:
            final_key = f"{key}_{idx}"
            idx += 1
        normalized[final_key] = value

    return normalized


def _extract_pdf_text_fallback(file_path: str) -> str:
    try:
        import fitz  # type: ignore

        chunks: list[str] = []
        doc = fitz.open(file_path)
        for page in doc:
            text = page.get_text("text")
            if text:
                chunks.append(text)
        return "\n".join(chunks).strip()
    except Exception:
        return ""


def _rows_from_query_result(query_result: Any) -> list[dict[str, Any]]:
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

@router.post("", response_model=ParseResponse)
async def parse_academic_paper(req: ParseRequest, background_tasks: BackgroundTasks):
    try:
        # Load the source file path from DB by calling existing API
        async with httpx.AsyncClient(timeout=10.0) as client:
            source_res = await client.get(f"{API_BASE}/api/sources/{quote(req.source_id, safe='')}")
            if source_res.status_code >= 400:
                raise HTTPException(status_code=404, detail="Source not found")
            source_data = source_res.json()

        asset_data = source_data.get("asset") if isinstance(source_data, dict) else None
        file_path = source_data.get("file_path") if isinstance(source_data, dict) else None
        if not file_path and isinstance(asset_data, dict):
            file_path = asset_data.get("file_path")

        if not file_path or not Path(file_path).exists():
             raise HTTPException(status_code=400, detail="Source file path is invalid or missing.")

        # 2. Run AcademicPDFParser on it
        parser = AcademicPDFParser(file_path=file_path)
        # Parse synchronously right now
        import asyncio
        loop = asyncio.get_event_loop()
        parsed_paper = await loop.run_in_executor(None, parser.parse)
        normalized_sections = _normalize_sections(parsed_paper.sections)
        if not normalized_sections and parsed_paper.raw_text:
            normalized_sections = {"full_text": parsed_paper.raw_text.strip()}
        if not normalized_sections and file_path:
            fallback_text = _extract_pdf_text_fallback(file_path)
            if fallback_text:
                normalized_sections = {"full_text": fallback_text}
        if not normalized_sections:
            summary_text = "\n".join(
                [
                    str(parsed_paper.title or "").strip(),
                    str(parsed_paper.abstract or "").strip(),
                ]
            ).strip()
            if summary_text:
                normalized_sections = {"summary": summary_text}

        # 3. Upsert ParsedPaper data to academic_paper table by source_id.
        source_record_id = ensure_record_id(req.source_id)
        existing_result = await repo_query(
            "SELECT * FROM academic_paper WHERE source_id = $source_id LIMIT 1",
            {"source_id": source_record_id},
        )
        existing_rows = _rows_from_query_result(existing_result)

        if existing_rows:
            paper = AcademicPaper(**existing_rows[0])
            paper.source_id = source_record_id
            paper.title = parsed_paper.title
            paper.authors = parsed_paper.authors
            paper.abstract = parsed_paper.abstract
            paper.doi = parsed_paper.doi
            paper.year = parsed_paper.year
            paper.keywords = parsed_paper.keywords
            paper.sections = normalized_sections
            paper.raw_references = parsed_paper.raw_references
        else:
            paper = AcademicPaper(
                source_id=source_record_id,
                title=parsed_paper.title,
                authors=parsed_paper.authors,
                abstract=parsed_paper.abstract,
                doi=parsed_paper.doi,
                year=parsed_paper.year,
                keywords=parsed_paper.keywords,
                sections=normalized_sections,
                raw_references=parsed_paper.raw_references,
            )
        await paper.save()

        # 4. Trigger atom chunking
        async def trigger_atomize(paper_id: str):
             try:
                 async with httpx.AsyncClient(timeout=120.0) as c:
                      await c.post(f"{API_BASE}/api/papermind/atomize", json={"paper_id": paper_id})
             except Exception as e:
                 logger.error(f"Failed to trigger atomize for {paper_id}: {e}")

        # Currently we schedule it in background task
        background_tasks.add_task(trigger_atomize, paper.id)

        return ParseResponse(
            academic_paper_id=paper.id,
            title=paper.title,
            authors=paper.authors,
            section_count=len(normalized_sections),
            doi=paper.doi
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to parse academic pdf")
        raise HTTPException(status_code=500, detail=str(e))
