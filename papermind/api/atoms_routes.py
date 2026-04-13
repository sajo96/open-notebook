from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional
from loguru import logger
from pathlib import Path
import asyncio

from papermind.models import AcademicPaper, Atom
from papermind.atoms.chunker import chunk_paper_into_atoms
from papermind.atoms.embedder import AtomEmbedder
from papermind.db.vector_store import vector_store
from papermind.graph.graph_builder import build_similarity_edges
from papermind.parsers.academic_pdf_parser import AcademicPDFParser
from open_notebook.domain.notebook import Source
from open_notebook.database.repository import repo_query, ensure_record_id

router = APIRouter(prefix="/papermind", tags=["papermind-atoms"])

class AtomizeRequest(BaseModel):
    paper_id: str

class AtomizeResponse(BaseModel):
    atom_count: int
    edge_count: int = 0

class AtomResponse(BaseModel):
    id: str
    section_label: str
    content: str
    similarity_edge_count: int = 0

embedder = AtomEmbedder()

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
        
        # Save initially to get IDs
        for a in atoms:
            a.paper_id = ensure_record_id(str(a.paper_id))
            await a.save()
            saved_atoms.append(a)
            
        # Embed in batches
        texts = [a.content for a in saved_atoms]
        embeddings = await embedder.embed_batch(texts)
        
        # Update atoms and sqlite-vec
        for a, emb in zip(saved_atoms, embeddings):
            a.paper_id = ensure_record_id(str(a.paper_id))
            a.embedding = emb.tolist()
            await a.save()
            vector_store.upsert(a.id, emb)
            
        # Trigger similarity edge builder
        background_tasks.add_task(build_similarity_edges, req.paper_id)
        
        return AtomizeResponse(
            atom_count=len(atoms),
            edge_count=0 # Edge count evaluated async
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
            res = await repo_query(f"SELECT count() FROM similar_to WHERE in = {a.id}")
            count = 0
            if "result" in res and res["result"] and len(res["result"]) > 0:
                 count = res["result"][0].get("count", 0)
                 
            results.append(AtomResponse(
                id=a.id,
                section_label=a.section_label,
                content=a.content,
                similarity_edge_count=count
            ))
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
