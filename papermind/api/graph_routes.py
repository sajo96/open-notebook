from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel

from open_notebook.database.repository import repo_query

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

@router.get("/graph/{notebook_id}", response_model=GraphResponse)
async def get_notebook_graph(
    notebook_id: str,
    min_similarity: float = Query(0.75, description="minimum edge weight to include"),
    include_concepts: bool = Query(True, description="include concept nodes"),
    include_authors: bool = Query(False, description="include author nodes"),
    year_from: Optional[int] = Query(None, description="Starting year"),
    year_to: Optional[int] = Query(None, description="Ending year"),
    concept_filter: Optional[str] = Query(None, description="filter to papers tagged with this concept")
):
    try:
        # Resolve notebook ID prefix if missing
        nb_id = f"notebook:{notebook_id}" if not notebook_id.startswith("notebook:") else notebook_id

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
        
        # Build query conditionals
        conditions = ["source_id.notebook_id = $notebook_id"]
        if year_from is not None:
            conditions.append(f"year >= {year_from}")
        if year_to is not None:
            conditions.append(f"year <= {year_to}")
            
        where_clause = " AND ".join(conditions)
        
        query = f"""
        SELECT
          id, title, authors, year, doi,
          (SELECT id, section_label FROM atom WHERE paper_id = $parent.id) AS atoms,
          ->cites->academic_paper AS cited_papers,
          ->tagged_with.out AS concepts
        FROM academic_paper
        WHERE {where_clause}
        """

        papers_result = await repo_query(query, {"notebook_id": nb_id})
        papers = papers_result[0] if papers_result and len(papers_result) > 0 else []

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
        for p in papers:
            paper_id = p.get("id")
            if not paper_id:
                continue

            concepts_list = p.get("concepts", [])
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
                    edges.append(GraphEdge(source=paper_id, target=cited, type="cites", weight=1.0))
            
            # Atom Nodes & contains edges
            # Usually we don't return all atoms as graph nodes globally unless necessary, 
            # but if we do, we can add them here. For performance we keep atoms inside `similarity_to` queries below.

        # Fetch semantic edges from SurrealDB (similar_to edges between atoms)
        # We need all atoms that belong to the papers in the current notebook.
        paper_ids = [p["id"] for p in papers]
        if paper_ids:
            similarity_query = """
            SELECT in AS source, out AS target, weight 
            FROM similar_to 
            WHERE in.paper_id IN $paper_ids AND weight >= $min_weight
            """
            sim_edges_result = await repo_query(
                similarity_query, 
                {"paper_ids": paper_ids, "min_weight": min_similarity}
            )
            sim_edges = sim_edges_result[0] if sim_edges_result and len(sim_edges_result) > 0 else []
            
            for se in sim_edges:
                edges.append(GraphEdge(
                    source=se["source"],
                    target=se["target"],
                    type="similar_to",
                    weight=se["weight"]
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
