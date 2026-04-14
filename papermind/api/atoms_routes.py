from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional
from loguru import logger
from pathlib import Path
import asyncio

from papermind.models import AcademicPaper, Atom
from papermind.atoms.chunker import chunk_paper_into_atoms
from papermind.parsers.academic_pdf_parser import AcademicPDFParser
from open_notebook.domain.notebook import Source
from open_notebook.database.repository import repo_query, ensure_record_id

router = APIRouter(prefix="/papermind", tags=["papermind-atoms"])

class AtomizeRequest(BaseModel):
    paper_id: str

class AtomizeResponse(BaseModel):
    atom_count: int

class AtomResponse(BaseModel):
    id: str
    section_label: str
    content: str


@router.post("/atomize", response_model=AtomizeResponse)
async def create_atoms(req: AtomizeRequest, background_tasks: BackgroundTasks):
    try:
        paper = await AcademicPaper.get(req.paper_id)
        if not paper:
            raise HTTPException(status_code=404, detail="Paper not found")

        chunk_input = paper
        sections = getattr(paper, "sections", None)
        if not isinstance(sections, dict) or len(sections) == 0:
            try:
                source = await Source.get(str(paper.source_id))
                file_path = source.asset.file_path if source and source.asset else None
                if file_path and Path(file_path).exists():
                    parser = AcademicPDFParser(file_path=file_path)
                    loop = asyncio.get_event_loop()
                    chunk_input = await loop.run_in_executor(None, parser.parse)
            except Exception as e:
                logger.warning(f"Fallback parse for atomization failed for {paper.id}: {e}")

        atoms = chunk_paper_into_atoms(chunk_input, paper.id)
        saved_atoms = []
        
        for a in atoms:
            a.paper_id = ensure_record_id(str(a.paper_id))
            await a.save()
            saved_atoms.append(a)
        
        return AtomizeResponse(
                atom_count=len(saved_atoms),
        )
    except Exception as e:
        logger.exception("Failed to atomize paper")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/atoms/{paper_id}", response_model=List[AtomResponse])
async def get_atoms(paper_id: str):
    try:
        results = []
        atoms = await Atom.get_all()
        paper_atoms = [a for a in atoms if str(a.paper_id) == paper_id]
        
        for a in paper_atoms:
            results.append(AtomResponse(
                id=a.id,
                section_label=a.section_label,
                content=a.content
            ))
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
