from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import re

from papermind.models import AcademicPaper
from papermind.generators.academic_note_generator import AcademicNoteGenerator, GeneratedNote
from open_notebook.database.repository import repo_query, ensure_record_id

router = APIRouter(prefix="/papermind", tags=["papermind-notes"])
note_generator = AcademicNoteGenerator()


def _json_safe(value):
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    # Surreal RecordID and other custom objects should be rendered as string.
    return str(value)


def _rows_from_query_result(query_result):
    if not query_result:
        return []

    first = query_result[0]
    if isinstance(first, dict) and isinstance(first.get("result"), list):
        return first["result"]
    if isinstance(first, list):
        return first
    if isinstance(query_result, list):
        return query_result
    return []


def _extract_ai_note_from_rows(rows):
    for row in rows:
        if not isinstance(row, dict):
            continue
        out = row.get("out") if isinstance(row.get("out"), dict) else row
        if isinstance(out, dict) and out.get("note_type") == "ai":
            return out
    return None


def _extract_section_block(content: str, start_header: str, end_headers: list[str]) -> str:
    if not content:
        return ""
    start = content.find(start_header)
    if start == -1:
        return ""
    start += len(start_header)

    end = len(content)
    for header in end_headers:
        pos = content.find(header, start)
        if pos != -1:
            end = min(end, pos)
    return content[start:end].strip()


def _parse_ai_note_content(note_obj: dict) -> dict:
    """Convert markdown note content into the structured fields expected by the PaperPanel."""
    if not isinstance(note_obj, dict):
        return {}

    content = str(note_obj.get("content") or "")
    if not content:
        return _json_safe(note_obj)

    summary_match = re.search(r"\*\*Summary\*\*:\s*(.*)", content)
    one_line_summary = summary_match.group(1).strip() if summary_match else ""

    key_findings_block = _extract_section_block(
        content,
        "## Key Findings",
        ["## Methodology", "## Limitations", "**Concepts**:"],
    )
    key_findings = [
        line[2:].strip()
        for line in key_findings_block.splitlines()
        if line.strip().startswith("-")
    ]

    methodology = _extract_section_block(
        content,
        "## Methodology",
        ["## Limitations", "**Concepts**:"],
    )

    limitations_block = _extract_section_block(
        content,
        "## Limitations",
        ["**Concepts**:"],
    )
    limitations = [
        line[2:].strip()
        for line in limitations_block.splitlines()
        if line.strip().startswith("-")
    ]

    concepts_match = re.search(r"\*\*Concepts\*\*:\s*(.*)", content)
    concepts_raw = concepts_match.group(1).strip() if concepts_match else ""
    concepts = [c.strip() for c in concepts_raw.split(",") if c.strip()]

    structured = {
        "id": str(note_obj.get("id") or ""),
        "one_line_summary": one_line_summary,
        "key_findings": key_findings,
        "methodology": methodology,
        "limitations": limitations,
        "concepts": concepts,
    }
    return _json_safe(structured)

class GenerateNoteRequest(BaseModel):
    paper_id: str
    regenerate: Optional[bool] = False

@router.post("/generate_note")
async def generate_note(request: GenerateNoteRequest) -> dict:
    # 1. Fetch paper target
    try:
        paper = await AcademicPaper.get(request.paper_id)
        if not paper:
            raise HTTPException(status_code=404, detail="Paper not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    # 2. Check regeneration condition if a note already exists
    if not request.regenerate:
        try:
            # Note is linked from paper to note using refer edge
            existing_note_query = await repo_query(
                "SELECT out FROM $id->refer FETCH out",
                {"id": ensure_record_id(request.paper_id)}
            )
            rows = _rows_from_query_result(existing_note_query)
            existing_note = _extract_ai_note_from_rows(rows)
            if existing_note:
                return {
                    "status": "existing",
                    "note": _parse_ai_note_content(existing_note),
                }
        except Exception:
            pass

    # 3. Generate note
    try:
        generated = await note_generator.generate_note(paper)
        if hasattr(generated, "dict"):
            out_note = generated.dict()
        else:
            out_note = {
                "id": generated.note_id,
                "one_line_summary": generated.one_line_summary,
                "key_findings": generated.key_findings,
                "methodology": generated.methodology,
                "limitations": generated.limitations,
                "concepts": generated.concepts
            }
        return {
            "status": "success",
            "note": _json_safe(out_note)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")

@router.get("/note/{paper_id}")
async def get_note_for_paper(paper_id: str):
    paper_id_full = paper_id if ":" in paper_id else f"academic_paper:{paper_id}"
    try:
        existing_note_query = await repo_query(
            "SELECT out FROM $id->refer FETCH out",
            {"id": ensure_record_id(paper_id_full)}
        )
        rows = _rows_from_query_result(existing_note_query)
        existing_note = _extract_ai_note_from_rows(rows)
        if existing_note:
            return _parse_ai_note_content(existing_note)
        raise HTTPException(status_code=404, detail="AI Note not found for this paper")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
