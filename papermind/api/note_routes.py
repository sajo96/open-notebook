from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import ast
import json
import re

from papermind.models import AcademicPaper
from papermind.generators.academic_note_generator import AcademicNoteGenerator, GeneratedNote
from open_notebook.database.repository import repo_query, ensure_record_id
from loguru import logger
from papermind.utils import _rows_from_query_result, safe_error_detail

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


def _is_placeholder_text(value: str) -> bool:
    raw = str(value or "").strip().lower()
    if not raw:
        return True
    placeholders = {
        "methodology details unavailable.",
        "limitations not explicitly stated in source text.",
        "n/a",
        "none",
    }
    return raw in placeholders


def _parse_loose_mapping(raw: str) -> Optional[dict]:
    text = (raw or "").strip()
    if not text:
        return None

    candidates = [text]
    if text.startswith('"') and text.endswith('"'):
        candidates.append(text[1:-1])

    for candidate in candidates:
        normalized = candidate.strip()
        if not normalized.startswith("{"):
            continue

        try:
            parsed = json.loads(normalized)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        try:
            parsed = ast.literal_eval(normalized)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    return None


def _coerce_text_field(raw: str, preferred_keys: list[str]) -> str:
    text = (raw or "").strip()
    if not text:
        return ""

    mapping = _parse_loose_mapping(text)
    if not mapping:
        return text

    lowered = {str(k).strip().lower(): v for k, v in mapping.items()}
    for key in preferred_keys:
        value = lowered.get(key.lower())
        if value is None:
            continue
        cleaned = str(value).strip()
        if cleaned:
            return cleaned

    # Fallback: return first non-empty value from the mapping.
    for value in mapping.values():
        cleaned = str(value).strip()
        if cleaned:
            return cleaned

    return text


def _parse_ai_note_content(note_obj: dict) -> dict:
    """Convert markdown note content into the structured fields expected by the PaperPanel."""
    if not isinstance(note_obj, dict):
        return {}

    content = str(note_obj.get("content") or "")
    if not content:
        return _json_safe(note_obj)

    summary_match = re.search(r"\*\*Summary\*\*:\s*(.*)", content)
    one_line_summary_raw = summary_match.group(1).strip() if summary_match else ""
    one_line_summary = _coerce_text_field(
        one_line_summary_raw,
        ["one_line_summary", "summary", "abstract", "result"],
    )

    key_findings_block = _extract_section_block(
        content,
        "## Key Findings",
        ["## Methodology", "## Limitations", "**Concepts**:"],
    )
    key_findings = []
    for line in key_findings_block.splitlines():
        stripped = line.strip()
        if not stripped.startswith("-"):
            continue
        key_findings.append(
            _coerce_text_field(
                stripped[2:].strip(),
                ["finding", "key_finding", "result", "summary"],
            )
        )

    methodology_raw = _extract_section_block(
        content,
        "## Methodology",
        ["## Limitations", "**Concepts**:"],
    )
    methodology = _coerce_text_field(
        methodology_raw,
        ["methodology", "methods", "approach", "dataset", "experimental_setup"],
    )
    if _is_placeholder_text(methodology):
        methodology = ""

    limitations_block = _extract_section_block(
        content,
        "## Limitations",
        ["**Concepts**:"],
    )
    limitations = []
    for line in limitations_block.splitlines():
        stripped = line.strip()
        if not stripped.startswith("-"):
            continue
        limitations.append(
            _coerce_text_field(
                stripped[2:].strip(),
                ["limitation", "limitations", "risk", "caveat"],
            )
        )
    limitations = [item for item in limitations if not _is_placeholder_text(item)]

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


def _derive_methodology_and_limitations_from_paper(paper: dict, source_full_text: str = "") -> tuple[str, list[str]]:
    sections = paper.get("sections") if isinstance(paper, dict) else {}
    if not isinstance(sections, dict):
        sections = {}

    normalized_sections = {
        str(k or "").strip().lower(): str(v or "").strip()
        for k, v in sections.items()
        if str(v or "").strip()
    }

    methodology_candidates = [
        normalized_sections.get("methods", ""),
        normalized_sections.get("methodology", ""),
        normalized_sections.get("materials_and_methods", ""),
    ]
    methodology = next((m for m in methodology_candidates if m), "")
    if not methodology:
        source_pool = "\n".join(
            [
                normalized_sections.get("full_text", ""),
                source_full_text,
            ]
        ).strip()
        sentences = re.split(r"(?<=[.!?])\s+", source_pool)
        method_hits = [
            s.strip()
            for s in sentences
            if re.search(
                r"\b(method|methodology|dataset|experiment|evaluation|approach|protocol|model|simulation)\b",
                s,
                re.IGNORECASE,
            )
            and len(s.strip()) > 30
        ]
        if method_hits:
            methodology = " ".join(method_hits[:2]).strip()

    limitation_text = "\n".join(
        [
            normalized_sections.get("discussion", ""),
            normalized_sections.get("conclusion", ""),
            normalized_sections.get("full_text", "")[:2000],
            source_full_text[:4000],
        ]
    )
    limitation_hits: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", limitation_text):
        s = sentence.strip()
        if not s:
            continue
        if re.search(
            r"\b(limit|limitations|future work|constraint|caveat|weakness|shortcoming|however|although|may|might|could|tradeoff|error|uncertain)\b",
            s,
            re.IGNORECASE,
        ):
            limitation_hits.append(s)
        if len(limitation_hits) >= 4:
            break

    if not limitation_hits:
        tail_sentences = [
            s.strip()
            for s in re.split(r"(?<=[.!?])\s+", limitation_text)
            if len(s.strip()) > 80
        ]
        if tail_sentences:
            limitation_hits = tail_sentences[-2:]

    return methodology[:1200], limitation_hits

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
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to fetch paper")
        raise HTTPException(status_code=500, detail=safe_error_detail(str(e)))

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
        except Exception as e:
            logger.warning(f"Failed to check for existing note, proceeding to generate: {e}")

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
        logger.exception("Failed to generate note")
        raise HTTPException(status_code=500, detail=safe_error_detail(f"Generation failed: {str(e)}"))

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
            parsed_note = _parse_ai_note_content(existing_note)

            needs_enrichment = not parsed_note.get("methodology") or not parsed_note.get("limitations")
            if needs_enrichment:
                paper_rows_raw = await repo_query(
                    "SELECT sections FROM $id",
                    {"id": ensure_record_id(paper_id_full)},
                )
                paper_rows = _rows_from_query_result(paper_rows_raw)
                paper_row = paper_rows[0] if paper_rows and isinstance(paper_rows[0], dict) else {}
                source_full_text = ""
                source_rows_raw = await repo_query(
                    "SELECT source_id FROM $id",
                    {"id": ensure_record_id(paper_id_full)},
                )
                source_rows = _rows_from_query_result(source_rows_raw)
                source_row = source_rows[0] if source_rows and isinstance(source_rows[0], dict) else {}
                source_id = source_row.get("source_id")
                if source_id:
                    source_text_rows_raw = await repo_query(
                        "SELECT full_text FROM $id",
                        {"id": ensure_record_id(str(source_id))},
                    )
                    source_text_rows = _rows_from_query_result(source_text_rows_raw)
                    source_text_row = (
                        source_text_rows[0]
                        if source_text_rows and isinstance(source_text_rows[0], dict)
                        else {}
                    )
                    source_full_text = str(source_text_row.get("full_text") or "")

                derived_methodology, derived_limitations = _derive_methodology_and_limitations_from_paper(
                    paper_row,
                    source_full_text=source_full_text,
                )

                if not parsed_note.get("methodology") and derived_methodology:
                    parsed_note["methodology"] = derived_methodology
                if not parsed_note.get("limitations") and derived_limitations:
                    parsed_note["limitations"] = derived_limitations

            return parsed_note
        raise HTTPException(status_code=404, detail="AI Note not found for this paper")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get note for paper")
        raise HTTPException(status_code=500, detail=safe_error_detail(str(e)))
