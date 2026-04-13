from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel
from urllib.parse import unquote
from loguru import logger

from open_notebook.database.repository import repo_query, ensure_record_id

router = APIRouter(prefix="/papermind", tags=["papermind-graph"])

class GraphNode(BaseModel):
    id: str
    type: str # "paper" | "concept" | "author" | "atom"
    label: str
    year: Optional[int] = None
    authors: Optional[List[str]] = None
    doi: Optional[str] = None
    atom_count: Optional[int] = None
    concepts: Optional[List[str]] = None

class GraphEdge(BaseModel):
    source: str
    target: str
    type: str # "cites" | "similar_to" | "tagged_with" | "authored_by" | "contains"
    weight: float

class GraphMeta(BaseModel):
    paper_count: int
    concept_count: int
    edge_count: int
    generated_at: datetime

class GraphResponse(BaseModel):
    nodes: List[GraphNode]
    edges: List[GraphEdge]
    meta: GraphMeta


def _rows_from_query_result(query_result: Any) -> List[Dict[str, Any]]:
    if not query_result:
        return []

    # Pattern A: [{"status": "OK", "result": [...]}]
    first = query_result[0]
    if isinstance(first, dict) and isinstance(first.get("result"), list):
        return first["result"]

    # Pattern B: [[...rows...]]
    if isinstance(first, list):
        return first

    # Pattern C: [...rows...]
    if isinstance(query_result, list) and all(isinstance(x, dict) for x in query_result):
        return query_result

    return []


def _record_id_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("id", "out", "in"):
            nested = value.get(key)
            if isinstance(nested, str):
                return nested
    return str(value)


def _record_id_list(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    out: List[str] = []
    for v in values:
        s = _record_id_str(v)
        if s:
            out.append(s)
    return out


def _count_as_int(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict):
            nested = first.get("count")
            if isinstance(nested, (int, float)):
                return int(nested)
    if isinstance(value, dict):
        nested = value.get("count")
        if isinstance(nested, (int, float)):
            return int(nested)
    return 0

@router.get("/graph/{notebook_id}", response_model=GraphResponse)
async def get_notebook_graph(
    notebook_id: str,
    min_similarity: float = Query(0.75, description="minimum edge weight to include"),
    max_similarity_edges: int = Query(2000, ge=100, le=20000, description="cap similarity edges processed"),
    max_atoms: int = Query(4000, ge=100, le=50000, description="cap atom ids used for similarity scan"),
    include_concepts: bool = Query(True, description="include concept nodes"),
    include_authors: bool = Query(False, description="include author nodes"),
    year_from: Optional[int] = Query(None, description="Starting year"),
    year_to: Optional[int] = Query(None, description="Ending year"),
    concept_filter: Optional[str] = Query(None, description="filter to papers tagged with this concept")
):
    try:
        notebook_id = unquote(notebook_id)
        # Resolve notebook ID prefix if missing
        nb_id = f"notebook:{notebook_id}" if not notebook_id.startswith("notebook:") else notebook_id
        nb_record_id = ensure_record_id(nb_id)

        # We construct a SurrealDB query to fetch all required graph relations from the notebook
        query = """
        SELECT
          id, title, authors, year, doi,
          (SELECT id, section_label FROM atom WHERE paper_id = $parent.id) AS atoms,
          ->cites->academic_paper AS cited_papers,
          ->tagged_with->concept AS concepts
        FROM academic_paper
        WHERE source_id.notebook_id = $notebook_id
        """
        
        # Build query conditionals for academic papers
        conditions = ["source_id IN (SELECT VALUE in FROM reference WHERE out = $notebook_id)"]
        if year_from is not None:
            conditions.append(f"year >= {year_from}")
        if year_to is not None:
            conditions.append(f"year <= {year_to}")
            
        where_clause = " AND ".join(conditions)
        
        query = f"""
        SELECT
          id, source_id, title, authors, year, doi,
          (SELECT id, section_label FROM atom WHERE paper_id = $parent.id) AS atoms,
          ->cites->academic_paper AS cited_papers,
          ->tagged_with.out AS concepts
        FROM academic_paper
        WHERE {where_clause}
        """

        papers_result = await repo_query(query, {"notebook_id": nb_record_id})
        papers = _rows_from_query_result(papers_result)

        # Find plain sources (in case they weren't parsed into academic_paper)
        sources_query = """
        SELECT id, title, (SELECT count() FROM source_embedding WHERE source = $parent.id) as chunk_count
        FROM source 
        WHERE id IN (SELECT VALUE in FROM reference WHERE out = $notebook_id)
        """
        plain_sources_result = await repo_query(sources_query, {"notebook_id": nb_record_id})
        plain_sources = _rows_from_query_result(plain_sources_result)

        if concept_filter:
            # If concept filter is applied, only keep papers that have the specified concept
            filtered_papers = []
            filter_slug = concept_filter.strip().lower().replace(" ", "_")
            concept_target = f"concept:{filter_slug}" if not concept_filter.startswith("concept:") else concept_filter
            for p in papers:
                if "concepts" in p and concept_target in p["concepts"]:
                    filtered_papers.append(p)
            papers = filtered_papers

        nodes_dict: Dict[str, GraphNode] = {}
        edges: List[GraphEdge] = []

        paper_count = 0
        concept_count = 0

        # Construct nodes and basic structural edges
        # Add academic papers
        for p in papers:
            paper_id = _record_id_str(p.get("id"))
            if not paper_id:
                continue

            concepts_list = _record_id_list(p.get("concepts", []))
            atom_list = p.get("atoms", [])
            
            # Paper Node
            nodes_dict[paper_id] = GraphNode(
                id=paper_id,
                type="paper",
                label=p.get("title", "Unknown Paper"),
                year=p.get("year"),
                authors=p.get("authors", []),
                doi=p.get("doi"),
                atom_count=len(atom_list),
                concepts=[c for c in concepts_list if c]
            )
            paper_count += 1

            # Author Nodes
            if include_authors and p.get("authors"):
                for author in p["authors"]:
                    author_id = f"author:{author.strip().lower().replace(' ', '_')}"
                    if author_id not in nodes_dict:
                        nodes_dict[author_id] = GraphNode(
                            id=author_id,
                            type="author",
                            label=author.strip()
                        )
                    edges.append(GraphEdge(source=paper_id, target=author_id, type="authored_by", weight=1.0))

            # Concept Nodes
            if include_concepts and concepts_list:
                for c_id in concepts_list:
                    if not c_id: continue
                    label = c_id.replace("concept:", "").replace("_", " ").title()
                    if c_id not in nodes_dict:
                        nodes_dict[c_id] = GraphNode(
                            id=c_id,
                            type="concept",
                            label=label
                        )
                        concept_count += 1
                    edges.append(GraphEdge(source=paper_id, target=c_id, type="tagged_with", weight=1.0))

            # Citations Edges
            cites_list = p.get("cited_papers", [])
            if cites_list:
                for cited in cites_list:
                    cited_id = _record_id_str(cited)
                    if not cited_id:
                        continue
                    edges.append(GraphEdge(source=paper_id, target=cited_id, type="cites", weight=1.0))

        # Add plain sources as papers if they aren't already represented by an academic_paper
        parsed_source_ids = {
            sid
            for sid in (_record_id_str(p.get("source_id")) for p in papers)
            if sid
        }
        for s in plain_sources:
            s_id = _record_id_str(s.get("id"))
            if not s_id or s_id in parsed_source_ids:
                continue
            
            nodes_dict[s_id] = GraphNode(
                id=s_id,
                type="paper", # Treat plain source as paper
                label=s.get("title", "Unknown Source"),
                year=None,
                authors=[],
                doi=None,
                atom_count=_count_as_int(s.get("chunk_count")),
                concepts=[]
            )
            paper_count += 1
            
            # Atom Nodes & contains edges
            # Usually we don't return all atoms as graph nodes globally unless necessary, 
            # but if we do, we can add them here. For performance we keep atoms inside `similarity_to` queries below.

        # Fetch semantic edges from SurrealDB (similar_to edges between atoms)
        # and aggregate them to paper-level similarity edges for stable rendering.
        paper_id_strings = [pid for pid in (_record_id_str(p.get("id")) for p in papers) if pid]
        paper_ids = [ensure_record_id(pid) for pid in paper_id_strings]
        if paper_ids:
            atoms_result = await repo_query(
                "SELECT id, paper_id FROM atom WHERE paper_id IN $paper_ids LIMIT $atom_limit",
                {"paper_ids": paper_ids, "atom_limit": max_atoms},
            )
            atom_rows = _rows_from_query_result(atoms_result)
            atom_to_paper: Dict[str, str] = {}
            atom_ids: List[str] = []
            for row in atom_rows:
                atom_id = _record_id_str(row.get("id"))
                paper_id = _record_id_str(row.get("paper_id"))
                if atom_id and paper_id:
                    atom_to_paper[atom_id] = paper_id
                    atom_ids.append(atom_id)

            if atom_ids:
                similarity_query = """
                SELECT in AS source, out AS target, similarity_score AS weight
                FROM similar_to
                WHERE in IN $atom_ids
                  AND out IN $atom_ids
                  AND similarity_score >= $min_weight
                ORDER BY similarity_score DESC
                LIMIT $edge_limit
                """
                try:
                    sim_edges_result = await repo_query(
                        similarity_query,
                        {
                            "atom_ids": [ensure_record_id(aid) for aid in atom_ids],
                            "min_weight": min_similarity,
                            "edge_limit": max_similarity_edges,
                        },
                    )
                    sim_edges = _rows_from_query_result(sim_edges_result)

                    paper_similarity: Dict[tuple[str, str], float] = {}
                    for se in sim_edges:
                        source_id = _record_id_str(se.get("source"))
                        target_id = _record_id_str(se.get("target"))
                        if not source_id or not target_id:
                            continue
                        source_paper = atom_to_paper.get(source_id)
                        target_paper = atom_to_paper.get(target_id)
                        if not source_paper or not target_paper or source_paper == target_paper:
                            continue

                        key = tuple(sorted((source_paper, target_paper)))
                        weight = float(se.get("weight", 0.0))
                        prev = paper_similarity.get(key)
                        if prev is None or weight > prev:
                            paper_similarity[key] = weight

                    for (source_paper, target_paper), weight in paper_similarity.items():
                        edges.append(
                            GraphEdge(
                                source=source_paper,
                                target=target_paper,
                                type="similar_to",
                                weight=weight,
                            )
                        )
                except Exception as e:
                    # Return structural graph even if similarity scan is interrupted.
                    logger.warning(f"Similarity query failed for notebook {nb_id}: {e}")
                
        # Generate basic connectivity between plain sources if they reside in the same notebook 
        # (Since standard `source` nodes don't get `similar_to` atom edges by default without parsing)
        plain_source_ids = []
        for s in plain_sources:
            sid = _record_id_str(s.get("id"))
            if sid and sid not in parsed_source_ids:
                plain_source_ids.append(sid)
        import itertools
        if len(plain_source_ids) > 1:
            for s1, s2 in itertools.combinations(plain_source_ids, 2):
                # Create a baseline conceptual edge so standalone documents cluster together slightly
                edges.append(GraphEdge(
                    source=s1,
                    target=s2,
                    type="similar_to",
                    weight=0.5
                ))
        
        return GraphResponse(
            nodes=list(nodes_dict.values()),
            edges=edges,
            meta=GraphMeta(
                paper_count=paper_count,
                concept_count=concept_count,
                edge_count=len(edges),
                generated_at=datetime.utcnow()
            )
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
