"use client";

import dynamic from "next/dynamic";

const KnowledgeGraph = dynamic(() => import("@/components/papermind/KnowledgeGraph").then(m => m.default), {
    ssr: false,
});

import { use } from "react";

export default function NotebookGraphPage({
    params,
}: {
    params: Promise<{ id: string }>;
}) {
    const resolvedParams = use(params);
    let notebookId = resolvedParams.id;
    try {
        notebookId = decodeURIComponent(notebookId);
    } catch {
        // Keep original if not URI-encoded.
    }

    return (
        <main className="flex h-screen w-full flex-col">
            <div className="flex-1 w-full bg-muted/20 relative">
                <KnowledgeGraph notebookId={notebookId} />
            </div>
        </main>
    );
}