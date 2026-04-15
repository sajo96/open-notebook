from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from papermind.models import Atom
from papermind.parsers.academic_pdf_parser import ParsedPaper


@pytest.fixture
def client():
    from api.main import app

    return TestClient(app)


def _write_pdf_stub(tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nFake PDF bytes for test")
    return str(pdf_path)


def _parsed_paper() -> ParsedPaper:
    return ParsedPaper(
        title="Test Paper",
        authors=["A. Author"],
        abstract="Abstract",
        doi="10.1000/test",
        year=2024,
        keywords=["llm", "tagging"],
        sections={"abstract": "Abstract body"},
        raw_references=["Doe et al. Test Reference 2022"],
        raw_text="Abstract body",
        is_ocr=False,
    )


@pytest.mark.asyncio
async def test_ingest_happy_path(client, tmp_path):
    pdf_path = _write_pdf_stub(tmp_path)

    with (
        patch("papermind.api.ingest_routes.repo_query", new_callable=AsyncMock) as mock_repo_query,
        patch("papermind.api.ingest_routes.create_source_record", new_callable=AsyncMock) as mock_create_source,
        patch("papermind.api.ingest_routes.update_source_status", new_callable=AsyncMock) as mock_update_status,
        patch("papermind.api.ingest_routes._parse_pdf", new_callable=AsyncMock) as mock_parse,
        patch("papermind.api.ingest_routes._save_academic_paper", new_callable=AsyncMock) as mock_save_paper,
        patch("papermind.api.ingest_routes._save_atoms_to_db", new_callable=AsyncMock) as mock_save_atoms,
        patch("papermind.api.ingest_routes.embedder.embed_batch", new_callable=AsyncMock) as mock_embed_batch,
        patch("papermind.api.ingest_routes.build_similarity_edges", new_callable=AsyncMock) as mock_build_edges,
        patch("papermind.api.ingest_routes.note_generator.generate_note", new_callable=AsyncMock) as mock_generate_note,
        patch("papermind.api.ingest_routes.auto_tagger.tag_paper", new_callable=AsyncMock) as mock_tag,
        patch("papermind.api.ingest_routes.citation_linker.link_references", new_callable=AsyncMock) as mock_cite,
    ):
        mock_repo_query.return_value = []  # dedup lookup only
        mock_create_source.return_value = "source:1"
        mock_parse.return_value = _parsed_paper()
        mock_save_paper.return_value = SimpleNamespace(id="academic_paper:1")
        mock_save_atoms.return_value = ["atom:1", "atom:2"]
        mock_embed_batch.return_value = []
        mock_build_edges.return_value = 4
        mock_generate_note.return_value = SimpleNamespace(note_id="note:1", concepts=["llm", "tagging"])
        mock_tag.return_value = ["llm", "tagging"]
        mock_cite.return_value = 1

        with patch("papermind.api.ingest_routes.chunk_paper_into_atoms") as mock_chunk:
            mock_chunk.return_value = [
                Atom(paper_id="academic_paper:1", section_label="abstract", content="c1"),
                Atom(paper_id="academic_paper:1", section_label="abstract", content="c2"),
            ]
            response = client.post(
                "/api/papermind/ingest",
                json={
                    "pdf_path": pdf_path,
                    "notebook_id": "notebook:1",
                    "triggered_by": "upload",
                },
            )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "complete"
    assert body["source_id"] == "source:1"
    assert body["paper_id"] == "academic_paper:1"
    assert body["title"] == "Test Paper"
    assert body["atom_count"] == 2
    assert body["similarity_edge_count"] == 4
    assert body["tag_count"] == 2
    assert body["note_id"] == "note:1"

    mock_update_status.assert_awaited_once_with("source:1", "complete", title="Test Paper")


@pytest.mark.asyncio
async def test_ingest_duplicate_returns_duplicate_status(client, tmp_path):
    pdf_path = _write_pdf_stub(tmp_path)

    with (
        patch("papermind.api.ingest_routes.repo_query", new_callable=AsyncMock) as mock_repo_query,
        patch("papermind.api.ingest_routes.create_source_record", new_callable=AsyncMock) as mock_create_source,
    ):
        mock_repo_query.return_value = [{"id": "source:existing"}]

        response = client.post(
            "/api/papermind/ingest",
            json={
                "pdf_path": pdf_path,
                "notebook_id": "notebook:1",
                "triggered_by": "upload",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "duplicate"
    assert body["source_id"] == "source:existing"
    assert body["atom_count"] == 0
    mock_create_source.assert_not_called()


@pytest.mark.asyncio
async def test_ingest_parse_error_sets_parse_error_status(client, tmp_path):
    pdf_path = _write_pdf_stub(tmp_path)

    with (
        patch("papermind.api.ingest_routes.repo_query", new_callable=AsyncMock) as mock_repo_query,
        patch("papermind.api.ingest_routes.create_source_record", new_callable=AsyncMock) as mock_create_source,
        patch("papermind.api.ingest_routes._parse_pdf", new_callable=AsyncMock) as mock_parse,
        patch("papermind.api.ingest_routes.update_source_status", new_callable=AsyncMock) as mock_update_status,
    ):
        mock_repo_query.return_value = []
        mock_create_source.return_value = "source:1"
        mock_parse.side_effect = RuntimeError("corrupt pdf")

        response = client.post(
            "/api/papermind/ingest",
            json={
                "pdf_path": pdf_path,
                "notebook_id": "notebook:1",
                "triggered_by": "upload",
            },
        )

    assert response.status_code == 422
    body = response.json()
    detail = body["detail"]
    assert detail["error_stage"] == "parse"
    assert detail["status"] == "parse_error"
    mock_update_status.assert_awaited_once_with("source:1", "parse_error")


@pytest.mark.asyncio
async def test_ingest_embed_error_sets_embed_error_status(client, tmp_path):
    pdf_path = _write_pdf_stub(tmp_path)

    with (
        patch("papermind.api.ingest_routes.repo_query", new_callable=AsyncMock) as mock_repo_query,
        patch("papermind.api.ingest_routes.create_source_record", new_callable=AsyncMock) as mock_create_source,
        patch("papermind.api.ingest_routes._parse_pdf", new_callable=AsyncMock) as mock_parse,
        patch("papermind.api.ingest_routes._save_academic_paper", new_callable=AsyncMock) as mock_save_paper,
        patch("papermind.api.ingest_routes._save_atoms_to_db", new_callable=AsyncMock) as mock_save_atoms,
        patch("papermind.api.ingest_routes.embedder.embed_batch", new_callable=AsyncMock) as mock_embed_batch,
        patch("papermind.api.ingest_routes.update_source_status", new_callable=AsyncMock) as mock_update_status,
    ):
        mock_repo_query.return_value = []
        mock_create_source.return_value = "source:1"
        mock_parse.return_value = _parsed_paper()
        mock_save_paper.return_value = SimpleNamespace(id="academic_paper:1")
        mock_save_atoms.return_value = ["atom:1"]
        mock_embed_batch.side_effect = RuntimeError("embedder failure")

        with patch("papermind.api.ingest_routes.chunk_paper_into_atoms") as mock_chunk:
            mock_chunk.return_value = [
                Atom(paper_id="academic_paper:1", section_label="abstract", content="c1"),
            ]
            response = client.post(
                "/api/papermind/ingest",
                json={
                    "pdf_path": pdf_path,
                    "notebook_id": "notebook:1",
                    "triggered_by": "upload",
                },
            )

    assert response.status_code == 500
    body = response.json()
    detail = body["detail"]
    assert detail["error_stage"] == "embed"
    assert detail["status"] == "embed_error"
    mock_update_status.assert_awaited_once_with("source:1", "embed_error")
