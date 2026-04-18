from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from papermind.db.source_writer import Source, create_source_record


@pytest.mark.asyncio
async def test_create_source_record_persists_pdf_into_uploads(tmp_path):
    external_pdf = tmp_path / "external.pdf"
    external_pdf.write_bytes(b"%PDF-1.4\nFake PDF")

    uploads_dir = tmp_path / "uploads"

    async def fake_save(source):
        source.id = "source:test"

    with patch("papermind.db.source_writer.UPLOADS_FOLDER", str(uploads_dir)):
        with patch.object(Source, "save", autospec=True, side_effect=fake_save):
            with patch.object(Source, "add_to_notebook", new=AsyncMock()):
                with patch("papermind.db.source_writer.repo_query", new=AsyncMock(return_value=[])):
                    source_id = await create_source_record(
                        pdf_path=str(external_pdf),
                        notebook_id="notebook:1",
                        file_hash="abc123",
                        title="Paper",
                    )

    assert source_id == "source:test"
    expected_path = uploads_dir / "abc123.pdf"
    assert expected_path.exists()
    assert expected_path.read_bytes() == external_pdf.read_bytes()
