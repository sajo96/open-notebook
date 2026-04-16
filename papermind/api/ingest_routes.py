import asyncio
import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any, Literal, Optional
from datetime import datetime

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
from papermind.commands.pipeline_commands import advance_stage, mark_done, mark_failed
from papermind.models import AcademicPaper, Atom
from papermind.parsers.academic_pdf_parser import AcademicPDFParser, ParsedPaper
from papermind.tagging.concept_saver import save_concepts
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


class PaperStatusResponse(BaseModel):
    paper_id: str
    title: Optional[str] = None
    pipeline_stage: Optional[str]
    job_status: Optional[str]
    stage_updated_at: Optional[datetime]
    error_message: Optional[str]
    processing_info: Optional[dict[str, Any]] = None
    title_source: Optional[str] = None
    title_confidence: Optional[float] = None


class PaperDetailResponse(BaseModel):
    id: str
    source_id: str
    title: str
    authors: list[str]
    abstract: Optional[str]
    doi: Optional[str]
    year: Optional[int]
    keywords: list[str]
    pipeline_stage: Optional[str]
    stage_updated_at: Optional[datetime]
    error_message: Optional[str]


class UpdatePaperTitleRequest(BaseModel):
    title: str


class UpdatePaperTitleResponse(BaseModel):
    paper_id: str
    source_id: str
    title: str
    title_source: str
    title_confidence: float


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
        paper.title_source = parsed.title_source
        paper.title_confidence = parsed.title_confidence
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
            title_source=parsed.title_source,
            title_confidence=parsed.title_confidence,
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


async def _upsert_ingesting_stub_paper(source_id: str, pdf_path: str) -> AcademicPaper:
    source_record_id = ensure_record_id(source_id)
    existing_result = await repo_query(
        "SELECT * FROM academic_paper WHERE source_id = $source_id LIMIT 1",
        {"source_id": source_record_id},
    )
    existing_rows = _rows_from_query_result(existing_result)

    if existing_rows:
        paper = AcademicPaper(**existing_rows[0])
    else:
        paper = AcademicPaper(
            source_id=source_record_id,
            title=Path(pdf_path).stem,
            title_source="unknown",
            title_confidence=0.0,
            authors=[],
            abstract=None,
            doi=None,
            year=None,
            keywords=[],
            sections={},
            raw_references=[],
        )

    await paper.save()
    if not paper.id:
        raise RuntimeError("Failed to upsert ingesting academic paper stub")
    return paper


async def _save_atoms_to_db(atoms: list[Atom]) -> list[str]:
    atom_ids: list[str] = []
    for atom in atoms:
        await atom.save()
        if atom.id:
            atom_ids.append(str(atom.id))
    return atom_ids


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

        paper_stub = await _upsert_ingesting_stub_paper(source_id=source_id, pdf_path=pdf_path)
        await advance_stage(
            paper_id=str(paper_stub.id),
            stage="ingesting",
            source_id=source_id,
            job_payload={
                "stage": "ingesting",
                "source_id": source_id,
                "paper_id": str(paper_stub.id),
                "triggered_by": triggered_by,
                "filename": Path(pdf_path).name,
            },
        )
    except Exception as exc:
        logger.exception(f"Ingest failed creating source record for {pdf_path}")
        raise HTTPException(
            status_code=500,
            detail=_error_detail(None, "source", str(exc), "source_error"),
        )

    try:
        paper, atom_ids, edge_count, tags, note, final_title = await _run_ingest_from_source(
            source_id,
            pdf_path,
            paper_id=str(paper_stub.id),
            triggered_by=triggered_by,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"Ingest failed for source {source_id}")
        await update_source_status(source_id, "failed")
        raise HTTPException(
            status_code=500,
            detail=_error_detail(source_id, "pipeline", str(exc), "pipeline_error"),
        )

    return IngestResponse(
        source_id=source_id,
        paper_id=str(paper.id),
        title=final_title,
        atom_count=len(atom_ids),
        similarity_edge_count=edge_count,
        tag_count=len(tags),
        note_id=note.note_id or "",
        status="complete",
    )


async def _run_ingest_from_source(
    source_id: str,
    pdf_path: str,
    paper_id: Optional[str] = None,
    triggered_by: Literal["upload", "upload_form", "watcher", "manual_scan"] = "upload",
) -> tuple[AcademicPaper, list[str], int, list[str], Any, str]:
    """Run the ingest pipeline from parse through finalize, given an existing source."""

    # 3. PARSE
    try:
        await advance_stage(
            paper_id=paper_id,
            source_id=source_id,
            stage="parsing",
            job_payload={"stage": "parsing", "source_id": source_id, "paper_id": paper_id, "triggered_by": triggered_by},
        )
        parsed = await _parse_pdf(pdf_path)
    except Exception as exc:
        logger.exception(f"Ingest parse failed for source {source_id}")
        await update_source_status(source_id, "failed")
        await mark_failed(paper_id=paper_id, source_id=source_id, stage="parsing", error=str(exc))
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
        await update_source_status(source_id, "failed")
        await mark_failed(paper_id=paper_id, source_id=source_id, stage="parsing", error=str(exc))
        raise HTTPException(
            status_code=500,
            detail=_error_detail(source_id, "paper", str(exc), "paper_error"),
        )

    # 5. ATOMIZE + EMBED
    try:
        await advance_stage(
            paper_id=paper_id,
            source_id=source_id,
            stage="embedding",
            job_payload={"stage": "embedding", "source_id": source_id, "paper_id": paper_id, "triggered_by": triggered_by},
        )
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
        await update_source_status(source_id, "failed")
        await mark_failed(paper_id=paper_id, source_id=source_id, stage="embedding", error=str(exc))
        raise HTTPException(
            status_code=500,
            detail=_error_detail(source_id, "embed", str(exc), "embed_error"),
        )

    # 6b. STORE FULL TEXT (needed by note generator's _source_full_text fallback)
    if parsed.raw_text:
        await update_source_status(source_id, "running", full_text=parsed.raw_text)

    # 6. NOTE GENERATION
    try:
        await advance_stage(
            paper_id=paper_id,
            source_id=source_id,
            stage="notes",
            job_payload={"stage": "notes", "source_id": source_id, "paper_id": paper_id, "triggered_by": triggered_by},
        )
        note = await note_generator.generate_note(paper, raw_text=parsed.raw_text or "")
        logger.info(f"Generated note {note.note_id} for paper {paper_id}")
    except Exception as exc:
        logger.exception(f"Ingest note generation failed for source {source_id}")
        await update_source_status(source_id, "failed")
        await mark_failed(paper_id=paper_id, source_id=source_id, stage="notes", error=str(exc))
        raise HTTPException(
            status_code=500,
            detail=_error_detail(source_id, "note", str(exc), "note_error"),
        )

    # 7. SAVE CONCEPTS
    try:
        tags = await save_concepts(
            paper_id=paper_id,
            note_concepts=note.concepts,
            paper_keywords=parsed.keywords or [],
            authors=paper.authors or [],
        )
        logger.info(f"Saved {len(tags)} concepts for paper {paper_id}")
    except Exception as exc:
        logger.exception(f"Ingest concept save failed for source {source_id}")
        await update_source_status(source_id, "failed")
        await mark_failed(paper_id=paper_id, source_id=source_id, stage="notes", error=str(exc))
        raise HTTPException(
            status_code=500,
            detail=_error_detail(source_id, "tag", str(exc), "tag_error"),
        )

    # 8. SIMILARITY EDGES
    try:
        await advance_stage(
            paper_id=paper_id,
            source_id=source_id,
            stage="graph",
            job_payload={"stage": "graph", "source_id": source_id, "paper_id": paper_id, "triggered_by": triggered_by},
        )
        edge_count = await build_similarity_edges(paper_id)
        logger.info(f"Built {edge_count} similarity edges for paper {paper_id}")
    except Exception as exc:
        logger.exception(f"Ingest similarity edge build failed for source {source_id}")
        await update_source_status(source_id, "failed")
        await mark_failed(paper_id=paper_id, source_id=source_id, stage="graph", error=str(exc))
        raise HTTPException(
            status_code=500,
            detail=_error_detail(source_id, "graph", str(exc), "graph_error"),
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
        "completed",
        title=final_title,
        full_text=parsed.raw_text,
    )
    await mark_done(paper_id=paper_id, source_id=source_id)
    return paper, atom_ids, edge_count, tags, note, final_title


async def _continue_ingest_background(
    source_id: str,
    pdf_path: str,
    triggered_by: Literal["upload", "upload_form", "watcher", "manual_scan"],
):
    """Background task that continues the ingest pipeline after source creation."""
    try:
        await _run_ingest_from_source(source_id, pdf_path)
        logger.info(f"Background ingest completed for source {source_id}")
    except Exception as exc:
        logger.exception(f"Background ingest failed for source {source_id}: {exc}")
        await update_source_status(source_id, "failed")
    finally:
        if pdf_path and os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
            except OSError as cleanup_exc:
                logger.warning(f"Failed to cleanup temp file {pdf_path}: {cleanup_exc}")


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
                logger.warning(f"Failed to cleanup temp file {temp_file_path}: {exc}")


@ingest_router.post(
    "/upload-async",
)
async def upload_and_ingest_async(
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
                            None,
                            "source",
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

        # Create source record in the handler so it appears immediately with "running" status.
        file_hash = _compute_file_hash(temp_file_path)

        existing_rows = _rows_from_query_result(
            await repo_query(
                "SELECT id FROM source WHERE file_hash = $file_hash LIMIT 1",
                {"file_hash": file_hash},
            )
        )
        if existing_rows:
            return {"source_id": str(existing_rows[0].get("id")), "status": "duplicate"}

        source_id = await create_source_record(
            pdf_path=temp_file_path,
            notebook_id=notebook_id,
            file_hash=file_hash,
            title=file.filename,
        )

        paper_stub = await _upsert_ingesting_stub_paper(source_id=source_id, pdf_path=temp_file_path)
        await advance_stage(
            paper_id=str(paper_stub.id),
            stage="ingesting",
            source_id=source_id,
            job_payload={
                "stage": "ingesting",
                "source_id": source_id,
                "paper_id": str(paper_stub.id),
                "triggered_by": triggered_by,
                "filename": file.filename,
            },
        )

        asyncio.create_task(
            _continue_ingest_background(
                source_id=source_id,
                pdf_path=temp_file_path,
                triggered_by=triggered_by,
            )
        )

        return {"source_id": source_id, "status": "running"}
    except HTTPException:
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except OSError as exc:
                logger.warning(f"Failed to cleanup temp file {temp_file_path}: {exc}")
        raise
    finally:
        await file.close()


# ---------------------------------------------------------------------------
# Diagnostic endpoint – verify model provisioning end-to-end
# ---------------------------------------------------------------------------
@ingest_router.get("/diagnostics/llm")
async def diagnostics_llm():
    """
    Runs a minimal LLM provisioning check so you can see exactly where
    the chain breaks: defaults → model record → credential → API call.
    """
    from open_notebook.ai.models import DefaultModels, model_manager
    from open_notebook.ai.provision import provision_langchain_model
    from open_notebook.utils import token_count

    diag: dict[str, Any] = {"steps": {}}

    # Step 1 – fetch defaults
    try:
        defaults = await DefaultModels.get_instance()
        diag["steps"]["defaults"] = {
            "default_chat_model": defaults.default_chat_model,
            "default_transformation_model": defaults.default_transformation_model,
            "large_context_model": defaults.large_context_model,
            "default_embedding_model": defaults.default_embedding_model,
            "default_tools_model": defaults.default_tools_model,
        }
    except Exception as e:
        diag["steps"]["defaults"] = {"error": str(e)}
        diag["provision_ok"] = False
        return diag

    # Step 2 – resolve the model record
    chat_model_id = defaults.default_chat_model
    if not chat_model_id:
        diag["steps"]["model_record"] = {
            "error": "default_chat_model is NOT set in DefaultModels",
            "hint": "Go to Settings → Models and select a default chat model.",
        }
        diag["provision_ok"] = False
        return diag

    try:
        model_record = await model_manager.get_model(chat_model_id)
        diag["steps"]["model_record"] = {
            "id": str(getattr(model_record, "id", chat_model_id)),
            "name": getattr(model_record, "name", None),
            "provider": getattr(model_record, "provider", None),
            "type": getattr(model_record, "type", None),
            "has_credential": bool(getattr(model_record, "credential", None)),
        }
    except Exception as e:
        diag["steps"]["model_record"] = {"error": str(e)}
        diag["provision_ok"] = False
        return diag

    # Step 3 – provision a LangChain model (the same call note_generator makes)
    test_content = "Hello, this is a diagnostic test."
    try:
        llm = await provision_langchain_model(
            test_content,
            model_id=None,
            default_type="chat",
            temperature=0.1,
        )
        diag["steps"]["provision"] = {
            "status": "ok",
            "llm_type": type(llm).__name__,
            "tokens_estimated": token_count(test_content),
        }
    except Exception as e:
        diag["steps"]["provision"] = {"error": str(e)}
        diag["provision_ok"] = False
        return diag

    # Step 4 – actually call the LLM with a trivial prompt
    try:
        from langchain_core.messages import HumanMessage

        response = await llm.ainvoke([HumanMessage(content="Say 'ok' and nothing else.")])
        diag["steps"]["llm_call"] = {
            "status": "ok",
            "response_preview": str(getattr(response, "content", response))[:200],
        }
        diag["provision_ok"] = True
    except Exception as e:
        diag["steps"]["llm_call"] = {"error": str(e)}
        diag["provision_ok"] = False

    return diag


def _normalize_paper_id(paper_id: str) -> str:
    return paper_id if ":" in paper_id else f"academic_paper:{paper_id}"


async def _get_paper_by_id_or_404(paper_id: str) -> AcademicPaper:
    normalized_id = _normalize_paper_id(paper_id)
    paper = await AcademicPaper.get(normalized_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper


@ingest_router.get(
    "/papers/{paper_id}",
    response_model=PaperDetailResponse,
    summary="Get paper detail with pipeline stage",
)
async def get_paper_detail(paper_id: str):
    paper = await _get_paper_by_id_or_404(paper_id)
    return PaperDetailResponse(
        id=str(paper.id),
        source_id=str(paper.source_id),
        title=paper.title,
        authors=paper.authors,
        abstract=paper.abstract,
        doi=paper.doi,
        year=paper.year,
        keywords=paper.keywords,
        pipeline_stage=paper.pipeline_stage,
        stage_updated_at=paper.stage_updated_at,
        error_message=paper.error_message,
    )


@ingest_router.get(
    "/papers/{paper_id}/status",
    response_model=PaperStatusResponse,
    summary="Get real-time pipeline status for a paper",
)
async def get_paper_status(paper_id: str):
    paper = await _get_paper_by_id_or_404(paper_id)
    progress = await paper.get_processing_progress()
    return PaperStatusResponse(
        paper_id=str(paper.id),
        title=paper.title,
        pipeline_stage=progress["pipeline_stage"],
        job_status=progress["job_status"],
        stage_updated_at=progress["stage_updated_at"],
        error_message=progress["error_message"],
        processing_info=progress.get("processing_info"),
        title_source=paper.title_source,
        title_confidence=paper.title_confidence,
    )


@ingest_router.get(
    "/papers/source/{source_id}/status",
    response_model=PaperStatusResponse,
    summary="Get real-time pipeline status by source ID",
)
async def get_paper_status_by_source(source_id: str):
    rows_raw = await repo_query(
        "SELECT * FROM academic_paper WHERE source_id = $source_id LIMIT 1",
        {"source_id": ensure_record_id(source_id)},
    )
    rows = _rows_from_query_result(rows_raw)
    if not rows:
        raise HTTPException(status_code=404, detail="Paper not found for source")

    paper = AcademicPaper(**rows[0])
    progress = await paper.get_processing_progress()
    return PaperStatusResponse(
        paper_id=str(paper.id),
        title=paper.title,
        pipeline_stage=progress["pipeline_stage"],
        job_status=progress["job_status"],
        stage_updated_at=progress["stage_updated_at"],
        error_message=progress["error_message"],
        processing_info=progress.get("processing_info"),
        title_source=paper.title_source,
        title_confidence=paper.title_confidence,
    )


@ingest_router.patch(
    "/papers/{paper_id}/title",
    response_model=UpdatePaperTitleResponse,
    summary="Manually update paper title",
)
async def update_paper_title(paper_id: str, req: UpdatePaperTitleRequest):
    paper = await _get_paper_by_id_or_404(paper_id)

    normalized_title = str(req.title or "").strip()
    if len(normalized_title) < 3:
        raise HTTPException(status_code=422, detail="Title must be at least 3 characters")

    paper.title = normalized_title
    paper.title_source = "manual"
    paper.title_confidence = 1.0
    await paper.save()

    try:
        await repo_update("source", str(paper.source_id), {"title": normalized_title})
    except Exception as exc:
        logger.warning(f"Failed to sync source title for {paper.source_id}: {exc}")

    return UpdatePaperTitleResponse(
        paper_id=str(paper.id),
        source_id=str(paper.source_id),
        title=paper.title,
        title_source="manual",
        title_confidence=1.0,
    )


@ingest_router.post("/papers/{paper_id}/retry")
async def retry_paper_pipeline(paper_id: str):
    paper = await _get_paper_by_id_or_404(paper_id)
    source_rows = _rows_from_query_result(
        await repo_query(
            "SELECT asset FROM source WHERE id = $source_id LIMIT 1",
            {"source_id": ensure_record_id(str(paper.source_id))},
        )
    )
    asset = source_rows[0].get("asset") if source_rows else None
    file_path = asset.get("file_path") if isinstance(asset, dict) else None

    if not file_path or not Path(file_path).exists():
        raise HTTPException(
            status_code=400,
            detail="Retry requires an existing source file path",
        )

    await advance_stage(
        paper_id=str(paper.id),
        source_id=str(paper.source_id),
        stage="ingesting",
        job_payload={
            "stage": "ingesting",
            "source_id": str(paper.source_id),
            "paper_id": str(paper.id),
            "triggered_by": "retry",
            "filename": Path(file_path).name,
        },
    )

    asyncio.create_task(
        _run_ingest_from_source(
            source_id=str(paper.source_id),
            pdf_path=file_path,
            paper_id=str(paper.id),
            triggered_by="manual_scan",
        )
    )

    return {"status": "retrying", "paper_id": str(paper.id)}
