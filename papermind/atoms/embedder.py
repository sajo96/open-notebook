import os
import httpx
import numpy as np
from typing import List, Any

class AtomEmbedder:
    def __init__(self):
        self.provider = os.environ.get("PAPERMIND_EMBED_PROVIDER", "ollama")
        self.model = os.environ.get("PAPERMIND_EMBED_MODEL", "nomic-embed-text")
        self.dim = int(os.environ.get("PAPERMIND_EMBED_DIM", "768"))
        self.ollama_url = os.environ.get("PAPERMIND_OLLAMA_URL", "http://localhost:11434")

    def _normalize_embedding(self, raw_embedding: Any) -> np.ndarray:
        """Normalize provider output to a single float32 vector of expected dimension."""
        arr = np.asarray(raw_embedding, dtype=np.float32)

        if arr.ndim == 2:
            # Some providers return a batch shape for a single input.
            arr = arr[0]

        arr = arr.reshape(-1)

        if arr.shape[0] == self.dim:
            return arr

        # Defensive fallback for malformed batch flattening (e.g. 3*768).
        if arr.shape[0] > self.dim and arr.shape[0] % self.dim == 0:
            return arr[: self.dim]

        raise ValueError(
            f"Unexpected embedding dimension: got {arr.shape[0]}, expected {self.dim}"
        )

    async def embed_atom(self, atom_content: str) -> np.ndarray:
        try:
            from open_notebook.ai.models import model_manager
            embed_model = await model_manager.get_embedding_model()
            if embed_model:
                embedding = await embed_model.aembed(atom_content)
                return self._normalize_embedding(embedding)
        except Exception:
            # Fall back to standalone if not running inside Open Notebook context or SurrealDB fails
            pass

        if self.provider == "openai":
            import openai
            client = openai.AsyncClient()
            response = await client.embeddings.create(input=atom_content, model=self.model)
            embedding = response.data[0].embedding
            return self._normalize_embedding(embedding)
        else:
            async with httpx.AsyncClient() as client:
                res = await client.post(
                    f"{self.ollama_url}/api/embeddings",
                    json={"model": self.model, "prompt": atom_content},
                    timeout=60.0
                )
                res.raise_for_status()
                embedding = res.json()["embedding"]
            return self._normalize_embedding(embedding)

    async def embed_batch(self, texts: List[str]) -> List[np.ndarray]:
        # For ollama, it might require one by one unless using the batch endpoint if available
        # We will do concurrent tasks
        import asyncio
        tasks = [self.embed_atom(t) for t in texts]
        results = await asyncio.gather(*tasks)
        return list(results)
