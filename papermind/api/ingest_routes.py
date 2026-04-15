import asyncio
import hashlib
import os
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel

from open_notebook.database.repository import ensure_record_id, repo_query, repo_update
from papermind.atoms.chunker import chunk_paper_into_atoms
from papermind.atoms.embedder import AtomEmbedder
from papermind.db.source_writer import create_source_record, update_source_status
from papermind.db.vector_store import vector_store
from papermind.generators.academic_note_generator import AcademicNoteGenerator
from papermind.graph.citation_linker import CitationLinker
from papermind.graph.graph_builder import build_similarity_edges
from papermind.models import AcademicPaper, Atom
from papermind.parsers.academic_pdf_parser import AcademicPDFParser, ParsedPaper
from papermind.tagging.auto_tagger import AutoTagger


ingest_router = APIRouter(prefix="/papermind", tags=["papermind-ingest"])
note_generator = AcademicNoteGenerator()
embedder = AtomEmbedder()


class IngestRequest(BaseModel):
    pdf_path: str
    notebook_id: str
    triggered_by: Literal["upload", "watcher", "manual_scan"] = "upload"


class IngestResponse(BaseModel):
    source_id: str
    paper_id: str
    title: str
    atom_count: int
    similarity_edge_count: int
    tag_count: int
    note_id: str
    status: Literal["complete", "duplicate"]


class IngestErrorResponse(BaseModel):
    source_id: Optional[str]
    error_stage: str
    detail: str
    status: str


def _error_detail(
    source_id: Optional[str],
    error_stage: str,
    detail: str,
    status: str,
) -> dict[str, Any]:
    return IngestErrorResponse(
        source_id=source_id,
        error_stage=error_stage,
        detail=detail,
        status=status,
    ).model_dump()


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


def _compute_file_md5(path: str) -> str:
    digest = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def _parse_pdf(pdf_path: str) -> ParsedPaper:
    parser = AcademicPDFParser(file_path=pdf_path)
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, parser.parse)


async def _save_academic_paper(parsed: ParsedPaper, source_id: str) -> AcademicPaper:
    source_record_id = ensure_record_id(source_id)
    existing_result = await repo_query(
        "SELECT * FROM academic_paper WHERE source_id = $source_id LIMIT 1",
        {"source_id": source_record_id},
    )
    existing_rows = _rows_from_query_result(existing_result)

    if existing_rows:
        paper = AcademicPaper(**existing_rows[0])
        paper.source_id = source_record_id
        paper.title = parsed.title or os.path.basename(str(source_id))
        paper.authors = parsed.authors
        paper.abstract = parsed.abstract
        paper.doi = parsed.doi
        paper.year = parsed.year
        paper.keywords = parsed.keywords
        paper.sections = parsed.sections
        paper.raw_references = parsed.raw_references
    else:
        paper = AcademicPaper(
            source_id=source_record_id,
            title=parsed.title or os.path.basename(str(source_id)),
            authors=parsed.authors,
            abstract=parsed.abstract,
            doi=parsed.doi,
            year=parsed.year,
            keywords=parsed.keywords,
            sections=parsed.sections,
            raw_references=parsed.raw_references,
        )

    await paper.save()
    if not paper.id:
        raise RuntimeError("Failed to save academic paper record")
    return paper


async def _save_atoms_to_db(atoms: list[Atom]) -> list[str]:
    atom_ids: list[str] = []
    for atom in atoms:
        await atom.save()
        if atom.id:
            atom_ids.append(str(atom.id))
    return atom_ids


auto_tagger = AutoTagger()
citation_linker = CitationLinker()


@ingest_router.post(
    "/ingest",
    response_model=IngestResponse,
    responses={422: {"model": IngestErrorResponse}, 500: {"model": IngestErrorResponse}},
)
async def ingest(req: IngestRequest):
    # 1. DEDUP
    try:
        file_hash = _compute_file_md5(req.pdf_path)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=_error_detail(None, "dedup", str(exc), "dedup_error"),
        )

    existing_rows = _rows_from_query_result(
        await repo_query(
            "SELECT id FROM source WHERE file_hash = $file_hash LIMIT 1",
            {"file_hash": file_hash},
        )
    )
    if existing_rows:
        return IngestResponse(
            source_id=str(existing_rows[0].get("id")),
            paper_id="",
            title="",
            atom_count=0,
            similarity_edge_count=0,
            tag_count=0,
            note_id="",
            status="duplicate",
        )

    # 2. SOURCE STUB
    try:
        source_id = await create_source_record(
            pdf_path=req.pdf_path,
            notebook_id=req.notebook_id,
            file_hash=file_hash,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=_error_detail(None, "source", str(exc), "source_error"),
        )

    # 3. PARSE
    try:
        parsed = await _parse_pdf(req.pdf_path)
    except Exception as exc:
        await update_source_status(source_id, "parse_error")
        raise HTTPException(
            status_code=422,
            detail=_error_detail(source_id, "parse", str(exc), "parse_error"),
        )

    # 4. SAVE ACADEMIC PAPER
    paper = await _save_academic_paper(parsed, source_id)
    paper_id = str(paper.id)

    # 5. ATOMIZE + EMBED
    try:
        atoms = chunk_paper_into_atoms(parsed, paper_id)
        atom_ids = await _save_atoms_to_db(atoms)
        embeddings = await embedder.embed_batch([atom.content for atom in atoms]) if atoms else []

        for atom, embedding in zip(atoms, embeddings):
            if not atom.id:
                continue
            embedding_list = embedding.tolist()
            await repo_update("atom", str(atom.id), {"embedding": embedding_list})
            vector_store.upsert(str(atom.id), embedding)
    except Exception as exc:
        await update_source_status(source_id, "embed_error")
        raise HTTPException(
            status_code=500,
            detail=_error_detail(source_id, "embed", str(exc), "embed_error"),
        )

    # 6. SIMILARITY EDGES
    edge_count = await build_similarity_edges(paper_id)

    # 7. NOTE GENERATION
    try:
        note = await note_generator.generate_note(paper)
    except Exception as exc:
        await update_source_status(source_id, "note_error")
        raise HTTPException(
            status_code=500,
            detail=_error_detail(source_id, "note", str(exc), "note_error"),
        )

    # 8. AUTO-TAG
    try:
        tags = await auto_tagger.tag_paper(paper_id, parsed, note.concepts)
    except Exception as exc:
        await update_source_status(source_id, "tag_error")
        raise HTTPException(
            status_code=500,
            detail=_error_detail(source_id, "tag", str(exc), "tag_error"),
        )

    # 9. CITATION LINKING
    try:
        await citation_linker.link_references(paper_id, parsed.raw_references)
    except Exception as exc:
        logger.warning(f"Citation linking failed for {paper_id}: {exc}")

    # 10. FINALIZE
    await update_source_status(source_id, "complete", title=parsed.title)
    return IngestResponse(
        source_id=source_id,
        paper_id=paper_id,
        title=parsed.title,
        atom_count=len(atom_ids),
        similarity_edge_count=edge_count,
        tag_count=len(tags),
        note_id=note.note_id or "",
        status="complete",
    )
