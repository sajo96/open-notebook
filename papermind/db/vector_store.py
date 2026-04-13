import os
import sqlite3
import sqlite_vec
import numpy as np
import struct
from typing import List, Dict

class VectorStore:
    def __init__(self):
        self.db_path = os.environ.get("PAPERMIND_VECTOR_DB_PATH", "./data/papermind_vectors.db")
        self.dim = int(os.environ.get("PAPERMIND_EMBED_DIM", "768"))
        self._init_db()

    def _init_db(self):
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            
        with sqlite3.connect(self.db_path) as db:
            db.enable_load_extension(True)
            sqlite_vec.load(db)
            db.enable_load_extension(False)
            # Use sqlite-vec standard initialization
            db.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_items USING vec0(id TEXT PRIMARY KEY, embedding float[{self.dim}])")
            db.commit()

    def upsert(self, atom_id: str, embedding: np.ndarray | List[float]) -> None:
        if embedding is None:
            return
            
        if isinstance(embedding, list):
            embedding = np.array(embedding, dtype=np.float32)
            
        blob = embedding.tobytes()
            
        with sqlite3.connect(self.db_path) as db:
            db.enable_load_extension(True)
            sqlite_vec.load(db)
            db.enable_load_extension(False)
            
            # Using bare blob
            db.execute(
                "INSERT OR REPLACE INTO vec_items(id, embedding) VALUES (?, ?)",
                (atom_id, blob)
            )
            db.commit()

    def find_similar(self, vector: np.ndarray | List[float], top_k: int = 10, threshold: float = 0.75, exclude_id: str = None) -> List[Dict]:
        if isinstance(vector, list):
            vector = np.array(vector, dtype=np.float32)
            
        blob = vector.tobytes()
            
        with sqlite3.connect(self.db_path) as db:
            db.enable_load_extension(True)
            sqlite_vec.load(db)
            db.enable_load_extension(False)
            
            cursor = db.cursor()
            
            if exclude_id:
                cursor.execute(
                    """
                    SELECT id, vec_distance_cosine(embedding, ?) AS distance
                    FROM vec_items
                    WHERE id != ?
                    ORDER BY distance ASC
                    LIMIT ?
                    """,
                    (blob, exclude_id, top_k)
                )
            else:
                cursor.execute(
                    """
                    SELECT id, vec_distance_cosine(embedding, ?) AS distance
                    FROM vec_items
                    ORDER BY distance ASC
                    LIMIT ?
                    """,
                    (blob, top_k)
                )
                
            results = []
            for row in cursor.fetchall():
                sim_score = 1.0 - float(row[1]) # cosine distance to similarity
                if sim_score >= threshold:
                    results.append({"id": row[0], "score": sim_score})
            return results

    def delete(self, atom_id: str) -> None:
        with sqlite3.connect(self.db_path) as db:
            db.enable_load_extension(True)
            sqlite_vec.load(db)
            db.enable_load_extension(False)
            db.execute("DELETE FROM vec_items WHERE id = ?", (atom_id,))
            db.commit()

vector_store = VectorStore()
