import asyncio
import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
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
from papermind.utils import _rows_from_query_result, validate_pdf_path


ingest_router = APIRouter(prefix="/papermind", tags=["papermind-ingest"])
MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100 MB
note_generator = AcademicNoteGenerator()
embedder = AtomEmbedder()


class IngestRequest(BaseModel):
    pdf_path: str
    notebook_id: str
    triggered_by: Literal["upload", "upload_form", "watcher", "manual_scan"] = "upload"


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


def _compute_file_hash(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def _parse_pdf(pdf_path: str) -> ParsedPaper:
    parser = AcademicPDFParser(file_path=pdf_path)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, parser.parse)


async def _save_academic_paper(parsed: ParsedPaper, source_id: str) -> AcademicPaper:
    fallback_title = os.path.basename(str(source_id))
    source_rows = _rows_from_query_result(
        await repo_query(
            "SELECT title FROM source WHERE id = $id LIMIT 1",
            {"id": ensure_record_id(source_id)},
        )
    )
    if source_rows:
        source_title = str(source_rows[0].get("title") or "").strip()
        if source_title:
            fallback_title = source_title

    parsed_title = str(parsed.title or "").strip()
    if parsed_title.lower() in {"", "unknown title", "unknown paper"}:
        parsed_title = fallback_title

    source_record_id = ensure_record_id(source_id)
    existing_result = await repo_query(
        "SELECT * FROM academic_paper WHERE source_id = $source_id LIMIT 1",
        {"source_id": source_record_id},
    )
    existing_rows = _rows_from_query_result(existing_result)

    if existing_rows:
        paper = AcademicPaper(**existing_rows[0])
        paper.source_id = source_record_id
        paper.title = parsed_title
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
            title=parsed_title,
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


def _normalize_ingest_title(raw_title: str, pdf_path: str) -> str:
    title = str(raw_title or "").strip()
    if title and title.lower() not in {"unknown title", "unknown paper"}:
        return title
    return Path(pdf_path).stem


async def _run_ingest_pipeline(
    pdf_path: str,
    notebook_id: str,
    triggered_by: Literal["upload", "upload_form", "watcher", "manual_scan"],
) -> IngestResponse:
    logger.info(
        f"Starting ingest pipeline for {pdf_path} "
        f"(notebook_id={notebook_id}, triggered_by={triggered_by})"
    )

    # 1. DEDUP
    try:
        file_hash = _compute_file_hash(pdf_path)
    except Exception as exc:
        logger.exception(f"Ingest failed during dedup hash for {pdf_path}")
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
        logger.info(f"Duplicate ingest skipped for {pdf_path}")
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
            pdf_path=pdf_path,
            notebook_id=notebook_id,
            file_hash=file_hash,
        )
    except Exception as exc:
        logger.exception(f"Ingest failed creating source record for {pdf_path}")
        raise HTTPException(
            status_code=500,
            detail=_error_detail(None, "source", str(exc), "source_error"),
        )

    # 3. PARSE
    try:
        parsed = await _parse_pdf(pdf_path)
    except Exception as exc:
        logger.exception(f"Ingest parse failed for source {source_id}")
        await update_source_status(source_id, "parse_error")
        raise HTTPException(
            status_code=422,
            detail=_error_detail(source_id, "parse", str(exc), "parse_error"),
        )

    # 4. SAVE ACADEMIC PAPER
    try:
        paper = await _save_academic_paper(parsed, source_id)
        paper_id = str(paper.id)
        logger.info(f"Saved academic_paper {paper_id} for source {source_id}")
    except Exception as exc:
        logger.exception(f"Ingest paper save failed for source {source_id}")
        await update_source_status(source_id, "paper_error")
        raise HTTPException(
            status_code=500,
            detail=_error_detail(source_id, "paper", str(exc), "paper_error"),
        )

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
        logger.exception(f"Ingest embed failed for source {source_id}")
        await update_source_status(source_id, "embed_error")
        raise HTTPException(
            status_code=500,
            detail=_error_detail(source_id, "embed", str(exc), "embed_error"),
        )

    # 6. SIMILARITY EDGES
    try:
        edge_count = await build_similarity_edges(paper_id)
        logger.info(f"Built {edge_count} similarity edges for paper {paper_id}")
    except Exception as exc:
        logger.exception(f"Ingest similarity edge build failed for source {source_id}")
        await update_source_status(source_id, "graph_error")
        raise HTTPException(
            status_code=500,
            detail=_error_detail(source_id, "graph", str(exc), "graph_error"),
        )

    # 7. NOTE GENERATION
    try:
        note = await note_generator.generate_note(paper)
        logger.info(f"Generated note {note.note_id} for paper {paper_id}")
    except Exception as exc:
        logger.exception(f"Ingest note generation failed for source {source_id}")
        await update_source_status(source_id, "note_error")
        raise HTTPException(
            status_code=500,
            detail=_error_detail(source_id, "note", str(exc), "note_error"),
        )

    # 8. AUTO-TAG
    try:
        tags = await auto_tagger.tag_paper(paper_id, parsed, note.concepts)
    except Exception as exc:
        logger.exception(f"Ingest auto-tag failed for source {source_id}")
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
    final_title = _normalize_ingest_title(parsed.title, pdf_path)
    await update_source_status(
        source_id,
        "complete",
        title=final_title,
        full_text=parsed.raw_text,
    )
    return IngestResponse(
        source_id=source_id,
        paper_id=paper_id,
        title=final_title,
        atom_count=len(atom_ids),
        similarity_edge_count=edge_count,
        tag_count=len(tags),
        note_id=note.note_id or "",
        status="complete",
    )


@ingest_router.post(
    "/ingest",
    response_model=IngestResponse,
    responses={422: {"model": IngestErrorResponse}, 500: {"model": IngestErrorResponse}},
)
async def ingest(req: IngestRequest):
    try:
        validated_path = validate_pdf_path(req.pdf_path)
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail=_error_detail(None, "source", str(e), "validation_error"),
        )
    return await _run_ingest_pipeline(
        pdf_path=validated_path,
        notebook_id=req.notebook_id,
        triggered_by=req.triggered_by,
    )


@ingest_router.post(
    "/upload",
    response_model=IngestResponse,
    responses={422: {"model": IngestErrorResponse}, 500: {"model": IngestErrorResponse}},
)
async def upload_and_ingest(
    file: UploadFile = File(...),
    notebook_id: str = Form(...),
    triggered_by: Literal["upload", "upload_form", "watcher", "manual_scan"] = Form("upload"),
):
    if not file.filename:
        raise HTTPException(
            status_code=422,
            detail=_error_detail(None, "source", "Uploaded file is missing filename", "source_error"),
        )

    suffix = Path(file.filename).suffix.lower()
    if suffix != ".pdf":
        raise HTTPException(
            status_code=422,
            detail=_error_detail(None, "source", "Only PDF files are accepted", "validation_error"),
        )

    temp_file_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
            temp_file_path = temp_file.name
            total_bytes = 0
            first_chunk = True
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > MAX_UPLOAD_SIZE:
                    raise HTTPException(
                        status_code=422,
                        detail=_error_detail(
                            None, "source",
                            f"File exceeds maximum size of {MAX_UPLOAD_SIZE // (1024 * 1024)}MB",
                            "validation_error",
                        ),
                    )
                if first_chunk and not chunk[:5].startswith(b"%PDF-"):
                    raise HTTPException(
                        status_code=422,
                        detail=_error_detail(None, "source", "File is not a valid PDF", "validation_error"),
                    )
                first_chunk = False
                temp_file.write(chunk)

        return await _run_ingest_pipeline(
            pdf_path=temp_file_path,
            notebook_id=notebook_id,
            triggered_by=triggered_by,
        )
    finally:
        await file.close()
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except OSError as exc:
                logger.warning(f"Failed to cleanup temp upload file {temp_file_path}: {exc}")
