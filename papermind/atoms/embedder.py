import os
import httpx
import numpy as np
from typing import List

class AtomEmbedder:
    def __init__(self):
        self.provider = os.environ.get("PAPERMIND_EMBED_PROVIDER", "ollama")
        self.model = os.environ.get("PAPERMIND_EMBED_MODEL", "nomic-embed-text")
        self.dim = int(os.environ.get("PAPERMIND_EMBED_DIM", "768"))
        self.ollama_url = os.environ.get("PAPERMIND_OLLAMA_URL", "http://localhost:11434")

    async def embed_atom(self, atom_content: str) -> np.ndarray:
        try:
            from open_notebook.ai.models import model_manager
            embed_model = await model_manager.get_embedding_model()
            if embed_model:
                embedding = await embed_model.aembed(atom_content)
                return np.array(embedding, dtype=np.float32)
        except Exception:
            # Fall back to standalone if not running inside Open Notebook context or SurrealDB fails
            pass

        if self.provider == "openai":
            import openai
            client = openai.AsyncClient()
            response = await client.embeddings.create(input=atom_content, model=self.model)
            embedding = response.data[0].embedding
        else:
            async with httpx.AsyncClient() as client:
                res = await client.post(
                    f"{self.ollama_url}/api/embeddings",
                    json={"model": self.model, "prompt": atom_content},
                    timeout=60.0
                )
                res.raise_for_status()
                embedding = res.json()["embedding"]
        return np.array(embedding, dtype=np.float32)

    async def embed_batch(self, texts: List[str]) -> List[np.ndarray]:
        # For ollama, it might require one by one unless using the batch endpoint if available
        # We will do concurrent tasks
        import asyncio
        tasks = [self.embed_atom(t) for t in texts]
        results = await asyncio.gather(*tasks)
        return list(results)
