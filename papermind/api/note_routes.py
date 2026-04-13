from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from papermind.models import AcademicPaper
from papermind.generators.academic_note_generator import AcademicNoteGenerator, GeneratedNote
from open_notebook.database.repository import repo_query

router = APIRouter(prefix="/papermind", tags=["papermind-notes"])
note_generator = AcademicNoteGenerator()

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
                "SELECT out.* FROM type::thing($id)->refer FETCH out", 
                {"id": request.paper_id}
            )
            if existing_note_query and len(existing_note_query) > 0 and len(existing_note_query[0]) > 0:
                for res in existing_note_query[0]:
                    if res and res.get("out") and res["out"].get("note_type") == "ai":
                        return {
                            "status": "existing",
                            "note": res["out"]
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
            "note": out_note
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")

@router.get("/note/{paper_id}")
async def get_note_for_paper(paper_id: str):
    paper_id_full = f"academic_paper:{paper_id}" if not paper_id.startswith("academic_paper:") else paper_id
    try:
        existing_note_query = await repo_query(
            "SELECT out.* FROM type::thing($id)->refer FETCH out", 
            {"id": paper_id_full}
        )
        if existing_note_query and len(existing_note_query) > 0 and len(existing_note_query[0]) > 0:
            for res in existing_note_query[0]:
                if res and res.get("out") and res["out"].get("note_type") == "ai":
                    return res["out"]
        raise HTTPException(status_code=404, detail="AI Note not found for this paper")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
