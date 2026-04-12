# Upstream Architecture - Open Notebook

## Directory Structure
- `api/` — FastAPI application and all REST API endpoints. Includes Pydantic schema models.
- `open_notebook/domain/` — Definition of core domain models extending base objects (BaseModel/Surreal records) like `notebook`, `credential`, `transformation`.
- `open_notebook/database/` — SurrealDB connection manager, query helpers, and async migration system running `.surrealql` files.
- `open_notebook/graphs/` — LangGraph definitions for various workflows (source ingestion, chatting, transformations, asking, etc.).
- `open_notebook/ai/` — LLM configuration, model discovery, and multi-provider API abstractions.
- `open_notebook/utils/` — Helper tools for embedding, encryption, testing connections, context building, and chunking.
- `open_notebook/podcasts/` — Modules to generate podcast scripts and synthesize voices.
- `commands/` — CLI/worker commands processing isolated tasks like embeddings or podcast creation.
- `frontend/` — Included Next.js React frontend (based on npm tasks in the root folder / Makefile).
- `docs/` — Public user documentation and configuration setup instructions.
- `tests/` — Pytest test suites.

## Database Tables (SurrealDB)
Defined across `migrations/*.surrealql` and implied from `domain/*.py` and endpoints:
- `notebook` — Organizes research and manages associated notes and sources.
- `source` — Represents imported documents/urls. Contains text, url, file_path, and title.
- `note` (or `artifact`) — Generated notes/texts from the LLM or user text.
- `transformation` — Records applied scripts to sources.
- `chat_session` — Stores a user's conversational interaction with a notebook.
- `credential` / `provider_config` — Stores API credentials for external LLM hosts.
- `model` — Specifies specific LLMs (like `gpt-5-mini` or `claude-3.5`).
- Relations (Edges): `reference` (links things to source/notebooks), `refers_to`, `artifact` etc.

## Key API Endpoints
(Defined in `api/routers` or `api/*_service.py` with FastAPI)
- `GET /api/notebooks` & `POST /api/notebooks` — Manage notebooks.
- `POST /api/sources` — Upload a document/URL to extract content. Uses LangGraph to process in background.
- `GET /api/search` — Perform local/vector search.
- `GET /api/notes` / `POST /api/notes` — Fetch or create LLM notes.
- `POST /api/chat` / `POST /api/ask` — Talk contextually with models regarding selected notebooks.
- `POST /api/podcasts` — Generate a podcast script and audio.

## Ingestion Pipeline
Sources (PDFs, URLs) start with `api/sources_service.py` pushing parameters into a background LangGraph definition at `open_notebook/graphs/source.py`.
1. The LangGraph flow `content_process` invokes the `content_core` library (an external package defined in `pyproject.toml`) to extract raw text (e.g. from `.pdf` or youtube).
2. It proceeds to `save_source` which updates the database.
3. It may trigger vectorization: embedding text via `open_notebook/utils/embedding.py` down to sqlite-vec or returning the matrix back to DB.
4. It finally applies configured `transformations` (running prompts against the text over LLMs).

## LangChain Integration
- Relies heavily on **LangGraph**.
- Flows like `graphs/chat.py` and `graphs/source_chat.py` define agents with states (like `SourceState`, `TransformationState`).
- Provider abstraction using `langchain_openai`, `langchain_anthropic`, `langchain_ollama` across `open_notebook/ai/` classes allows it to switch models easily while passing uniform calls.
