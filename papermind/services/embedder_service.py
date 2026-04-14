"""Service for embedding atoms and building similarity edges."""

from __future__ import annotations

from loguru import logger

from papermind.atoms.embedder import AtomEmbedder
from papermind.db.vector_store import vector_store
from papermind.graph.graph_builder import build_similarity_edges
from papermind.models import Atom
from open_notebook.database.repository import repo_update


class EmbedderService:
    """Orchestrates embedding and semantic edge creation for atoms."""

    def __init__(self) -> None:
        self._embedder = AtomEmbedder()

    async def embed_atoms(self, atoms: list[Atom]) -> int:
        """Embed atoms, persist vectors to Atom records, and upsert into sqlite-vec."""
        if not atoms:
            return 0

        embeddings = await self._embedder.embed_batch([atom.content for atom in atoms])
        embedded_count = 0

        for atom, embedding in zip(atoms, embeddings):
            try:
                embedding_list = embedding.tolist()
                atom.embedding = embedding_list
                if not atom.id:
                    logger.error("Skipping atom without ID during embedding persistence")
                    continue

                await repo_update(
                    "atom",
                    str(atom.id),
                    {"embedding": embedding_list},
                )
                vector_store.upsert(str(atom.id), embedding)
                embedded_count += 1
            except Exception as exc:
                logger.error(f"Failed to persist embedding for atom {atom.id}: {exc}")

        return embedded_count

    async def build_similarity_edges(self, paper_id: str) -> int:
        """Build SurrealDB similarity edges from vectors stored for a paper's atoms."""
        try:
            return await build_similarity_edges(paper_id)
        except Exception as exc:
            logger.error(f"Failed to build similarity edges for paper {paper_id}: {exc}")
            return 0
