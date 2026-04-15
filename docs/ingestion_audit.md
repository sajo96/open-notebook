# Ingestion Audit (Task A)

Date: 2026-04-15
Scope: `papermind` backend ingestion paths only.

## 1) Python call sites that hit Open Notebook source ingestion APIs

The codebase currently uses `/api/sources` (plural), including `/api/sources/json` for create and `/api/sources/{id}/status` for polling.

Runtime call sites:
- `papermind/watcher/folder_watcher.py`
  - `POST {API_BASE}/api/sources/json` (creates source)
  - `GET {API_BASE}/api/sources/{source_id}/status` (polls processing)
- `papermind/api/parser_routes.py`
  - `GET {API_BASE}/api/sources/{source_id}` (reads source metadata/path)

Library/client wrappers (indirect callers used by services/tests):
- `api/client.py`
  - `GET /api/sources`
  - `POST /api/sources/json`
  - `GET /api/sources/{source_id}`
  - `GET /api/sources/{source_id}/status`
  - `PUT /api/sources/{source_id}`
  - `DELETE /api/sources/{source_id}`
  - `GET /api/sources/{source_id}/insights`
  - `POST /api/sources/{source_id}/insights`

Tests that call source API:
- `tests/test_sources_api.py`

Notes:
- The Task A grep command without exclusions also matched `.venv` dependencies. Those are third-party files and not app runtime code.

## 2) Exact source schema fields written by Open Notebook ingestion

Source creation is implemented in `api/routers/sources.py` via `POST /api/sources` and `POST /api/sources/json`.

Fields written on initial source record creation:
- `title`
- `topics` (initialized to `[]`)
- `asset` object:
  - `asset.file_path` for upload sources
  - `asset.url` for link sources

Fields written during source processing (`open_notebook/graphs/source.py` and `commands/source_commands.py`):
- `asset` (updated with parsed `url`/`file_path`)
- `full_text` (extracted content)
- `title` (updated from extracted content only if current title is empty or `"Processing..."`)
- `command` (reference to surreal-commands job record)

Additional field written by current upload flow in this repo:
- `file_hash` (persisted after upload dedup path)
  - Defined in migration: `papermind/db/migrations/001_academic_tables.surql`

Notebook relation side effect:
- A `reference` edge is created from each source to notebook(s) immediately in source create flow.

## 3) Automatic downstream hooks triggered by Open Notebook ingestion

When Open Notebook ingestion runs (`process_source` command), it triggers these downstream behaviors:

- Content extraction via `source_graph` (`content_core` pipeline).
- Source save/update (`asset`, `full_text`, optional title update).
- Optional vectorization of source text when `embed=true` (calls `source.vectorize()`).
- Optional transformation execution creating `source_insight` records.
- PaperMind-specific auto-hook in `commands/source_commands.py`:
  - `_trigger_papermind_pipeline()` for PDF sources:
    - `POST /api/papermind/parse_academic`
    - `POST /api/papermind/atomize`
    - `POST /api/papermind/generate_note`

Implication for migration:
- PaperMind `/api/papermind/ingest` must bypass Open Notebook source ingestion command flow to avoid duplicate/mixed processing and hidden side effects.

## 4) Responsibility split: PaperMind vs Open Notebook

PaperMind already handles:
- Academic parsing (`AcademicPDFParser`)
- Atom chunking and embeddings (AtomChunker + Embedder + vector store)
- Graph construction/similarity edges
- Academic note generation
- Watcher integration and graph routes

Open Notebook ingestion currently handles:
- Generic source extraction (`content_core`)
- Generic source persistence (`asset`, `full_text`, `command`)
- Optional generic embeddings + transformations
- Current automatic trigger into PaperMind parse/atomize/note for PDFs

Migration target outcome:
- Keep only a minimal source stub compatible with Notebook View.
- Run all PaperMind pipeline stages from a single `/api/papermind/ingest` endpoint.
- Do not invoke Open Notebook source extraction/transform pipelines for PaperMind-ingested PDFs.
