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
    const notebookId = resolvedParams.id;

    return (
        <main className="flex h-screen w-full flex-col">
            <div className="flex-1 w-full bg-muted/20 relative">
                <KnowledgeGraph notebookId={notebookId} />
            </div>
        </main>
    );
}