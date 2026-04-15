from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List
from loguru import logger
from pathlib import Path
import asyncio

from papermind.models import AcademicPaper, Atom
from papermind.atoms.chunker import chunk_paper_into_atoms
from papermind.services.embedder_service import EmbedderService
from papermind.parsers.academic_pdf_parser import AcademicPDFParser
from open_notebook.domain.notebook import Source
from open_notebook.database.repository import ensure_record_id, repo_query
from papermind.utils import safe_error_detail, _rows_from_query_result

router = APIRouter(prefix="/papermind", tags=["papermind-atoms"])

embedder_service = EmbedderService()

class AtomizeRequest(BaseModel):
    paper_id: str

class AtomizeResponse(BaseModel):
    atom_count: int
    embedded_count: int = 0
    similarity_edge_count: int = 0

class AtomResponse(BaseModel):
    id: str
    section_label: str
    content: str


@router.post("/atomize", response_model=AtomizeResponse)
async def create_atoms(req: AtomizeRequest):
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
                    loop = asyncio.get_running_loop()
                    chunk_input = await loop.run_in_executor(None, parser.parse)
            except Exception as e:
                logger.warning(f"Fallback parse for atomization failed for {paper.id}: {e}")

        atoms = chunk_paper_into_atoms(chunk_input, paper.id)
        saved_atoms = []
        
        for a in atoms:
            a.paper_id = ensure_record_id(str(a.paper_id))
            await a.save()
            saved_atoms.append(a)

        embedded_count = await embedder_service.embed_atoms(saved_atoms)
        similarity_edge_count = await embedder_service.build_similarity_edges(req.paper_id)
        
        return AtomizeResponse(
            atom_count=len(saved_atoms),
            embedded_count=embedded_count,
            similarity_edge_count=similarity_edge_count,
        )
    except Exception as e:
        logger.exception("Failed to atomize paper")
        raise HTTPException(status_code=500, detail=safe_error_detail(str(e)))

@router.get("/atoms/{paper_id}", response_model=List[AtomResponse])
async def get_atoms(paper_id: str):
    try:
        atoms_result = await repo_query(
            "SELECT id, section_label, content FROM atom WHERE paper_id = $paper_id",
            {"paper_id": ensure_record_id(paper_id)},
        )
        atom_rows = _rows_from_query_result(atoms_result)

        results = []
        for row in atom_rows:
            if not isinstance(row, dict):
                continue
            results.append(AtomResponse(
                id=str(row.get("id", "")),
                section_label=str(row.get("section_label", "")),
                content=str(row.get("content", "")),
            ))
        return results
    except Exception as e:
        logger.exception("Failed to get atoms")
        raise HTTPException(status_code=500, detail=safe_error_detail(str(e)))
