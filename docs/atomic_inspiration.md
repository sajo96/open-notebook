# Atomic Inspiration

This document summarizes the architectural patterns from [kenforthewin/atomic](https://github.com/kenforthewin/atomic), which serve as inspiration for PaperMind's knowledge graph.

## Definition of "Atoms"
- Atoms are small, discrete semantic units of markdown text.
- They represent a single idea, concept, or section (like an "abstract" or "methodology" in an academic paper).
- By breaking large documents down into atoms, the system can perform granular similarity matching rather than attempting to match entire papers that cover multiple topics.

## Chunking Strategy
- Larger notes or papers are split into atoms based on structural boundaries (e.g., headings, paragraphs) or token limits.
- If a section exceeds the model's token limits or an arbitrary chunk size (e.g., 800 tokens), it is fragmented using a sliding window approach with overlaps (e.g., 600 tokens with 100 overlap) to preserve context.

## Embedding Storage (sqlite-vec)
- Embeddings are generated using an embedding model (like `nomic-embed-text` with 768 dimensions).
- They are stored locally in a SQLite database utilizing the `sqlite-vec` extension, preventing the need for a heavy standalone vector database.
- Schema approximation:
  ```sql
  CREATE VIRTUAL TABLE atom_vectors USING vec0(
      atom_id TEXT PRIMARY KEY,
      embedding FLOAT[768]
  );
  ```

## Semantic Links (Similarity)
- Semantic links between atoms are computed using cosine distance/similarity within `sqlite-vec`.
- A similarity threshold (e.g., `0.75`) is applied. Any pair of atoms with a cosine similarity above this threshold is considered "related".
- These similarities form the undirected edges of the knowledge graph (`similar_to` relations).

## Force-Directed Graph Data
- The knowledge graph visualizer (typically built with something like `react-force-graph`) expects two arrays: `nodes` and `edges`.
- **Nodes:** Consist of the papers themselves, extracted concepts, authors, and potentially the granular atoms.
- **Edges:** Explicit links (Paper A cites Paper B, Paper tagged with Concept X) and implicit semantic links (Atom A is similar to Atom B, implying Paper A is semantically related to Paper B).
- The visualizer maps these arrays into a 2D/3D physics simulation where edges pull related nodes together.