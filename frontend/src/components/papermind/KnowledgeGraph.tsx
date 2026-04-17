"use client";

import { useState, useMemo, useEffect, useRef } from "react";
import { Loader2 } from "lucide-react";
import PaperPanel from "./PaperPanel";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { GraphNode, GraphData } from "./types";
import KnowledgeGraphSigmaCanvas from "./KnowledgeGraphSigmaCanvas";
import { useSources } from "@/lib/hooks/use-sources";
import { QUERY_KEYS } from "@/lib/api/query-client";
export default function KnowledgeGraph({ notebookId }: { notebookId: string }) {
    const [minSim, setMinSim] = useState<number>(0.75);
    const [minSharedConcepts, setMinSharedConcepts] = useState<number>(2);
    const [conceptFilter, setConceptFilter] = useState<string>("");
    const [showConceptNodes, setShowConceptNodes] = useState<boolean>(false);
    const [edgeMode, setEdgeMode] = useState<"concept_similarity" | "cites" | "similar_to">("concept_similarity");
    const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
    const [hasLoadedGraphOnce, setHasLoadedGraphOnce] = useState<boolean>(false);
    const hasSeenActiveSourceRef = useRef<boolean>(false);
    const queryClient = useQueryClient();

    const normalizedNotebookId = useMemo(() => {
        // Route params may already be URL-encoded (e.g. notebook%3Aabc).
        // Decode once so we only encode once when calling the API.
        try {
            return decodeURIComponent(notebookId);
        } catch {
            return notebookId;
        }
    }, [notebookId]);

    const { data: sources } = useSources(normalizedNotebookId);
    const hasActiveSource = useMemo(() => {
        if (!sources) {
            return false;
        }

        return sources.some((source) => {
            if (source.command_id) {
                return true;
            }

            return source.status === "new" || source.status === "queued" || source.status === "running" || source.status === "processing";
        });
    }, [sources]);

    useEffect(() => {
        if (hasActiveSource) {
            hasSeenActiveSourceRef.current = true;
            return;
        }

        if (!hasSeenActiveSourceRef.current) {
            return;
        }

        hasSeenActiveSourceRef.current = false;

        // A source reached a terminal/ready state, so refresh graph data once.
        queryClient.invalidateQueries({
            queryKey: QUERY_KEYS.notebookGraph(normalizedNotebookId),
            refetchType: "active",
        });
    }, [hasActiveSource, normalizedNotebookId, queryClient]);

    const fetchGraphData = async (): Promise<GraphData> => {
        let url = `/api/papermind/graph/${encodeURIComponent(normalizedNotebookId)}?min_similarity=${minSim}&max_similarity_edges=800&max_atoms=2500&min_shared_concepts=${minSharedConcepts}`;
        if (conceptFilter) url += `&concept_filter=${encodeURIComponent(conceptFilter)}`;

        // We expect the FASTAPI backend mapping at /api (via proxy in UI or directly)
        const res = await fetch(url);
        if (!res.ok) {
            throw new Error(`Failed to load graph: ${res.statusText}`);
        }
        const json = await res.json();
        return { nodes: json.nodes, links: json.edges, meta: json.meta };
    };

    const { data, isLoading, error } = useQuery<GraphData>({
        queryKey: [...QUERY_KEYS.notebookGraph(normalizedNotebookId), minSim, minSharedConcepts, conceptFilter],
        queryFn: fetchGraphData,
        enabled: !hasLoadedGraphOnce || !hasActiveSource,
        staleTime: 30 * 1000,
        refetchOnWindowFocus: !hasActiveSource,
    });

    useEffect(() => {
        if (!data || hasLoadedGraphOnce) {
            return;
        }

        setHasLoadedGraphOnce(true);
    }, [data, hasLoadedGraphOnce]);

    const uniqueConcepts = useMemo(() => {
        const metaConcepts = (data?.meta?.concept_options as string[] | undefined) || [];
        if (metaConcepts.length > 0) return metaConcepts;
        if (!data?.nodes) return [];
        const conceptIds = new Set<string>();
        data.nodes
            .filter((n) => n.type === "paper")
            .forEach((paper) => {
                (paper.concepts || []).forEach((c) => conceptIds.add(c));
            });
        return Array.from(conceptIds).sort();
    }, [data]);

    const renderedGraphData = useMemo(() => {
        if (!data) return data;
        const nodes = showConceptNodes ? data.nodes : data.nodes.filter((n) => n.type !== "concept");
        const links = data.links.filter((l) => {
            if (!showConceptNodes && l.type === "tagged_with") return false;
            if (l.type === "tagged_with") return true;
            if (l.type === "authored_by") return false;
            return l.type === edgeMode;
        });
        return { ...data, nodes, links };
    }, [data, showConceptNodes, edgeMode]);

    return (
        <div className="relative w-full h-full flex overflow-hidden bg-zinc-50 dark:bg-[#1C1C1E]">
            {/* Settings / Controls Overlay */}
            <div className="absolute top-4 left-4 z-20 bg-background/80 backdrop-blur-md border rounded-xl p-4 shadow-sm w-72 flex flex-col gap-4">
                <h3 className="font-semibold text-sm text-foreground/90 uppercase tracking-widest flex items-center gap-2">
                    Knowledge Map Controls
                </h3>

                <div className="flex flex-col gap-2">
                    <label className="text-xs font-medium">Concept Filter</label>
                    <select
                        className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                        value={conceptFilter}
                        onChange={(e) => setConceptFilter(e.target.value)}
                    >
                        <option value="">-- Show All --</option>
                        {uniqueConcepts.map((c) => (
                            <option key={c} value={c}>
                                {c.replace("concept:", "").replace("_", " ")}
                            </option>
                        ))}
                    </select>
                </div>

                <div className="flex flex-col gap-2">
                    <label className="text-xs font-medium">Edge Mode</label>
                    <select
                        className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                        value={edgeMode}
                        onChange={(e) => setEdgeMode(e.target.value as "concept_similarity" | "cites" | "similar_to")}
                    >
                        <option value="concept_similarity">Concept similarity</option>
                        <option value="cites">Citation</option>
                        <option value="similar_to">Vector similarity</option>
                    </select>
                </div>

                <div className="flex flex-col gap-2">
                    <label className="text-xs font-medium">Similarity Threshold: {minSim}</label>
                    <input
                        type="range"
                        min={0.5}
                        max={0.99}
                        step={0.01}
                        value={minSim}
                        onChange={(e) => setMinSim(parseFloat(e.target.value))}
                        className="w-full"
                    />
                </div>

                <div className="flex flex-col gap-2">
                    <label className="text-xs font-medium">Semantic Overlap Min: {minSharedConcepts}</label>
                    <input
                        type="range"
                        min={1}
                        max={5}
                        step={1}
                        value={minSharedConcepts}
                        onChange={(e) => setMinSharedConcepts(parseInt(e.target.value, 10))}
                        className="w-full"
                    />
                </div>


            </div>

            {isLoading ? (
                <div className="w-full h-full flex flex-col items-center justify-center text-muted-foreground gap-4">
                    <Loader2 className="h-8 w-8 animate-spin" />
                    Loading Knowledge Graph...
                </div>
            ) : error ? (
                <div className="w-full h-full flex flex-col items-center justify-center text-destructive">
                    <p>Failed to load graph.</p>
                    <p className="text-xs mt-2">{String(error)}</p>
                </div>
            ) : (
                <div className="flex-1 w-full h-full">
                    <KnowledgeGraphSigmaCanvas graphData={renderedGraphData} onPaperClick={setSelectedNode} />
                </div>
            )}

            {/* Detail Slide panel */}
            {selectedNode && (
                <div className="absolute top-0 right-0 w-[420px] h-full min-h-0 shadow-2xl border-l bg-background z-30 transition-transform flex flex-col">
                    <PaperPanel
                        notebookId={notebookId}
                        paperNode={selectedNode}
                        onClose={() => setSelectedNode(null)}
                        onConceptClick={(cId) => setConceptFilter(cId)}
                    />
                </div>
            )}
        </div>
    );
}
