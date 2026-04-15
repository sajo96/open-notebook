'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import { Badge } from '@/components/ui/badge'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { EmptyState } from '@/components/common/EmptyState'
import { FolderOpen, Loader2, Trash2, RotateCcw } from 'lucide-react'
import { useTranslation } from '@/lib/hooks/use-translation'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'

interface WatchedFolder {
    id: string
    path: string
    notebook_id: string
    recursive: boolean
    active: boolean
    paper_count: number
    created_at: string
}

interface AddFolderPayload {
    path: string
    notebook_id: string
    recursive: boolean
}

interface WatchedFoldersProps {
    notebookId: string
}

const STATUS_DOT_COLORS = {
    active: 'bg-green-500',
    paused: 'bg-muted-foreground/50',
}

export function WatchedFolders({ notebookId }: WatchedFoldersProps) {
    const { t } = useTranslation()
    const queryClient = useQueryClient()

    const [path, setPath] = useState('')
    const [recursive, setRecursive] = useState(false)
    const [addError, setAddError] = useState(false)
    const [confirmRemoveId, setConfirmRemoveId] = useState<string | null>(null)
    const [scanningId, setScanningId] = useState<string | null>(null)

    // Fetch folders
    const { data: folders = [], isLoading, refetch } = useQuery({
        queryKey: ['watched-folders', notebookId],
        queryFn: () => {
            return axios.get<WatchedFolder[]>('/api/papermind/watch').then(r => r.data)
        },
    })

    // Add folder mutation
    const addFolder = useMutation({
        mutationFn: (payload: AddFolderPayload) =>
            axios.post('/api/papermind/watch', payload),
        onSuccess: () => {
            refetch()
            setPath('')
            setRecursive(false)
            setAddError(false)
            toast.success(t.sources.folderAdded || 'Folder added - watching for new PDFs.')
        },
        onError: (error) => {
            console.error('Error adding folder:', error)
            setAddError(true)
            toast.error(t.sources.folderNotFound || 'Folder not found. Check the path and try again.')
        },
    })

    // Remove folder mutation
    const removeFolder = useMutation({
        mutationFn: (id: string) =>
            axios.delete(`/api/papermind/watch/${id}`),
        onSuccess: () => {
            refetch()
            setConfirmRemoveId(null)
            toast.success(t.sources.folderRemoved || 'Folder removed.')
        },
        onError: (error) => {
            console.error('Error removing folder:', error)
            toast.error(t.sources.failedToRemoveFolder || 'Failed to remove folder.')
        },
    })

    // Scan folder mutation
    const scanFolder = useMutation({
        mutationFn: (id: string) =>
            axios.post(`/api/papermind/watch/${id}/scan`),
        onSuccess: () => {
            refetch()
            toast.success(t.sources.folderScanned || 'Folder scanned for new PDFs.')
        },
        onError: (error) => {
            console.error('Error scanning folder:', error)
            toast.error(t.sources.failedToScanFolder || 'Failed to scan folder.')
        },
    })

    const handleAddFolder = () => {
        if (path.trim() === '') {
            setAddError(true)
            return
        }

        addFolder.mutate({
            path: path.trim(),
            notebook_id: notebookId,
            recursive,
        })
    }

    const handleScanFolder = async (id: string) => {
        setScanningId(id)
        try {
            await scanFolder.mutateAsync(id)
        } finally {
            setScanningId(null)
        }
    }

    const handleRemoveConfirm = () => {
        if (confirmRemoveId) {
            removeFolder.mutate(confirmRemoveId)
        }
    }

    if (isLoading) {
        return (
            <div className="flex items-center justify-center py-8">
                <LoadingSpinner />
            </div>
        )
    }

    return (
        <section className="space-y-4">
            <div>
                <h3 className="text-base font-semibold">{t.sources.watchFolder || 'Watch a Folder'}</h3>
                <p className="text-xs text-muted-foreground mt-1">
                    {t.sources.watchFolderDesc || 'Auto-ingest PDFs the moment they appear in a local folder.'}
                </p>
            </div>

            {/* Add folder form */}
            <div className="space-y-2 p-3 bg-muted/50 rounded border border-border">
                <div>
                    <Label htmlFor="folder-path" className="text-xs">
                        {t.sources.folderPath || 'Folder Path'}
                    </Label>
                    <Input
                        id="folder-path"
                        type="text"
                        placeholder="/path/to/your/papers/"
                        value={path}
                        onChange={(e) => {
                            setPath(e.target.value)
                            setAddError(false)
                        }}
                        disabled={addFolder.isPending}
                        className="mt-1 text-sm"
                    />
                </div>

                <div className="flex items-center gap-2">
                    <Checkbox
                        id="recursive-checkbox"
                        checked={recursive}
                        onCheckedChange={(checked) => setRecursive(checked as boolean)}
                        disabled={addFolder.isPending}
                    />
                    <Label htmlFor="recursive-checkbox" className="text-xs cursor-pointer">
                        {t.sources.includeSubfolders || 'Include subfolders'}
                    </Label>
                </div>

                <Button
                    onClick={handleAddFolder}
                    disabled={path.trim() === '' || addFolder.isPending}
                    size="sm"
                    className="w-full"
                >
                    {addFolder.isPending ? (
                        <>
                            <Loader2 className="h-3 w-3 mr-2 animate-spin" />
                            {t.common.adding || 'Adding...'}
                        </>
                    ) : (
                        <>
                            <FolderOpen className="h-3 w-3 mr-2" />
                            {t.sources.addFolder || '+ Add Folder'}
                        </>
                    )}
                </Button>

                {/* Inline feedback */}
                {addError && (
                    <p className="text-xs text-destructive">
                        {t.sources.folderPathError || 'Folder not found. Check the path and try again.'}
                    </p>
                )}
            </div>

            {/* Folder list */}
            {folders.length === 0 ? (
                <div className="text-center py-6 text-muted-foreground">
                    <p className="text-xs">{t.sources.noFolders || 'No watched folders yet. Add one above to start auto-ingesting.'}</p>
                </div>
            ) : (
                <div className="space-y-2">
                    {folders
                        .sort((a, b) => {
                            // active first, then by created_at desc
                            if (a.active !== b.active) return a.active ? -1 : 1
                            return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
                        })
                        .map((folder) => (
                            <div
                                key={folder.id}
                                className="p-2 border border-border rounded text-xs"
                            >
                                {confirmRemoveId === folder.id ? (
                                    // Inline confirm
                                    <div className="space-y-2">
                                        <p className="text-muted-foreground">
                                            {t.sources.removeConfirmMessage || 'Remove this folder? Papers already ingested will not be deleted.'}
                                        </p>
                                        <div className="flex gap-2 justify-end">
                                            <Button
                                                variant="outline"
                                                size="sm"
                                                onClick={() => setConfirmRemoveId(null)}
                                                className="h-7 text-xs"
                                            >
                                                {t.common.cancel || 'Cancel'}
                                            </Button>
                                            <Button
                                                variant="destructive"
                                                size="sm"
                                                onClick={handleRemoveConfirm}
                                                disabled={removeFolder.isPending}
                                                className="h-7 text-xs"
                                            >
                                                {removeFolder.isPending ? (
                                                    <>
                                                        <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                                                        {t.common.removing || 'Removing...'}
                                                    </>
                                                ) : (
                                                    <>
                                                        <Trash2 className="h-3 w-3 mr-1" />
                                                        {t.common.remove || 'Remove'}
                                                    </>
                                                )}
                                            </Button>
                                        </div>
                                    </div>
                                ) : (
                  <>
                                        {/* Folder info */}
                                        <div className="flex items-start justify-between gap-2 mb-2">
                                            <div className="flex items-start gap-2 flex-1 min-w-0">
                                                <div
                                                    className={cn(
                                                        'h-1.5 w-1.5 rounded-full flex-shrink-0 mt-1.5',
                                                        STATUS_DOT_COLORS[folder.active ? 'active' : 'paused']
                                                    )}
                                                />
                                                <div className="min-w-0 flex-1">
                                                    <p className="font-medium truncate text-xs">{folder.path}</p>
                                                    <div className="flex items-center gap-1 mt-1 flex-wrap">
                                                        <Badge variant="secondary" className="text-xs">
                                                            {folder.paper_count === 1
                                                                ? '1 paper'
                                                                : `${folder.paper_count} papers`}
                                                        </Badge>
                                                        <Badge variant={folder.active ? 'default' : 'secondary'} className="text-xs">
                                                            {folder.active ? t.common.active || 'Watching' : t.common.paused || 'Paused'}
                                                        </Badge>
                                                    </div>
                                                </div>
                                            </div>
                                        </div>

                                        {/* Actions */}
                                        <div className="flex gap-1 justify-end">
                                            <Button
                                                variant="outline"
                                                size="sm"
                                                onClick={() => handleScanFolder(folder.id)}
                                                disabled={scanningId === folder.id || scanFolder.isPending}
                                                className="h-7 text-xs"
                                            >
                                                {scanningId === folder.id ? (
                                                    <>
                                                        <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                                                        {t.common.scanning || 'Scanning...'}
                                                    </>
                                                ) : (
                                                    <>
                                                        <RotateCcw className="h-3 w-3 mr-1" />
                                                        {t.sources.scanNow || 'Scan'}
                                                    </>
                                                )}
                                            </Button>
                                            <Button
                                                variant="outline"
                                                size="sm"
                                                onClick={() => setConfirmRemoveId(folder.id)}
                                                className="h-7 text-xs"
                                            >
                                                <Trash2 className="h-3 w-3 mr-1" />
