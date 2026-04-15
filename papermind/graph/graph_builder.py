from loguru import logger
from papermind.db.vector_store import vector_store
from papermind.models import Atom
from open_notebook.database.repository import repo_query, ensure_record_id
from papermind.utils import _rows_from_query_result

async def build_similarity_edges(paper_id: str, threshold: float = 0.75):
    """
    1. Query all atoms for this paper
    2. Query sqlite-vec for similar atoms across ALL papers
    3. Filter out atoms from same section in same paper
    4. Create RELATE atom_a -> similar_to -> atom_b in SurrealDB
    """
    edge_count = 0
    try:
        atoms_result = await repo_query(
            "SELECT * FROM atom WHERE paper_id = $paper_id",
            {"paper_id": ensure_record_id(paper_id)},
        )
        atom_rows = _rows_from_query_result(atoms_result)
        paper_atoms = [Atom(**row) for row in atom_rows if isinstance(row, dict)]
        
        for atom in paper_atoms:
            if not atom.embedding:
                continue

            try:
                similar_items = vector_store.find_similar(
                    vector=atom.embedding,
                    top_k=10,
                    threshold=threshold,
                    exclude_id=str(atom.id),
                )
            except Exception as e:
                logger.warning(f"Skipping similarity search for atom {atom.id}: {e}")
                continue
            
            for item in similar_items:
                target_id = item["id"]
                score = item["score"]
                
                # Exclude if same section from same paper (this requires loading target)
                target_res = await Atom.get(target_id)
                if not target_res:
                    continue
                    
                if str(target_res.paper_id) == str(paper_id) and target_res.section_label == atom.section_label:
                    continue
                    
                # RELATE undirected essentially means relate both ways
                logger.info(f"Creating edge {atom.id} -> {target_id} score {score}")
                await repo_query(
                    "RELATE $atom_id -> similar_to -> $target_id SET similarity_score = $score;",
                    {"atom_id": atom.id, "target_id": target_id, "score": score},
                )
                await repo_query(
                    "RELATE $target_id -> similar_to -> $atom_id SET similarity_score = $score;",
                    {"target_id": target_id, "atom_id": atom.id, "score": score},
                )
                edge_count += 2
    except Exception as e:
        logger.error(f"Failed to build similarity edges for {paper_id}: {e}")
    return edge_count
