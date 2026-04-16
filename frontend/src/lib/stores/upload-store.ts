import { create } from 'zustand'

export type UploadStage =
    | 'uploading'
    | 'parsing'
    | 'atomizing'
    | 'embedding'
    | 'note_generating'
    | 'complete'
    | 'error'

export interface UploadJob {
    id: string
    paperName: string
    notebookId: string
    sourceId: string | null
    trigger: 'manual' | 'watcher'
    stage: UploadStage
    progress: number
    errorMessage?: string
    addedToGraph?: boolean
}

interface UploadStore {
    jobs: UploadJob[]
    addJob: (job: UploadJob) => void
    updateJob: (id: string, patch: Partial<UploadJob>) => void
    removeJob: (id: string) => void
    markAddedToGraph: (id: string) => void
}

export const STAGE_PROGRESS: Record<UploadStage, number> = {
    uploading: 10,
    parsing: 25,
    atomizing: 50,
    embedding: 70,
    note_generating: 85,
    complete: 100,
    error: 100,
}

export const STAGE_LABEL: Record<UploadStage, string> = {
    uploading: 'Uploading PDF...',
    parsing: 'Extracting metadata & sections...',
    atomizing: 'Chunking into atoms...',
    embedding: 'Embedding atoms...',
    note_generating: 'Generating structured notes...',
    complete: 'Ready',
    error: 'Processing failed',
}

export const useUploadStore = create<UploadStore>((set) => ({
    jobs: [],
    addJob: (job) =>
        set((state) => {
            const existingIdx = state.jobs.findIndex((j) => j.id === job.id)
            if (existingIdx >= 0) {
                const jobs = [...state.jobs]
                jobs[existingIdx] = { ...jobs[existingIdx], ...job }
                return { jobs }
            }
            return { jobs: [job, ...state.jobs] }
        }),
    updateJob: (id, patch) =>
        set((state) => ({
            jobs: state.jobs.map((job) => (job.id === id ? { ...job, ...patch } : job)),
        })),
    removeJob: (id) =>
        set((state) => ({
            jobs: state.jobs.filter((job) => job.id !== id),
        })),
    markAddedToGraph: (id) =>
        set((state) => ({
            jobs: state.jobs.map((job) => (job.id === id ? { ...job, addedToGraph: true } : job)),
        })),
}))
