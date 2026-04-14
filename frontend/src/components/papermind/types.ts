export interface GraphNode {
    id: string;
    type: string;
    label: string;
    year?: number;
    authors?: string[];
    doi?: string;
    atom_count?: number;
    concepts?: string[];
    x?: number;
    y?: number;
    z?: number;
}

export interface GraphEdge {
    source: string;
    target: string;
    type: string;
    weight: number;
    label?: string;
}

export interface GraphData {
    nodes: GraphNode[];
    links: GraphEdge[];
    meta: {
        paper_count: number;
        concept_count: number;
        concept_options?: string[];
        edge_count: number;
        generated_at: string;
    };
}
