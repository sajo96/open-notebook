'use client'

import { useState, useMemo, useRef, useCallback, useEffect } from 'react'
import { SourceListResponse } from '@/lib/types/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Plus, FileText, Link2, ChevronDown, Loader2 } from 'lucide-react'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { EmptyState } from '@/components/common/EmptyState'
import { AddSourceDialog } from '@/components/sources/AddSourceDialog'
import { AddExistingSourceDialog } from '@/components/sources/AddExistingSourceDialog'
import { SourceCard } from '@/components/sources/SourceCard'
import { useDeleteSource, useRetrySource, useRemoveSourceFromNotebook } from '@/lib/hooks/use-sources'
import { sourcesApi } from '@/lib/api/sources'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { useModalManager } from '@/lib/hooks/use-modal-manager'
import { ContextMode } from '../[id]/page'
import { CollapsibleColumn, createCollapseButton } from '@/components/notebooks/CollapsibleColumn'
import { useNotebookColumnsStore } from '@/lib/stores/notebook-columns-store'
import { useTranslation } from '@/lib/hooks/use-translation'
import { STAGE_LABEL, useUploadStore } from '@/lib/stores/upload-store'

interface SourcesColumnProps {
  sources?: SourceListResponse[]
  isLoading: boolean
  notebookId: string
  notebookName?: string
  onRefresh?: () => void
  contextSelections?: Record<string, ContextMode>
  onContextModeChange?: (sourceId: string, mode: ContextMode) => void
  // Pagination props
  hasNextPage?: boolean
  isFetchingNextPage?: boolean
  fetchNextPage?: () => void
}

export function SourcesColumn({
  sources,
  isLoading,
  notebookId,
  onRefresh,
  contextSelections,
  onContextModeChange,
  hasNextPage,
  isFetchingNextPage,
  fetchNextPage,
}: SourcesColumnProps) {
  const { t } = useTranslation()
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const [addDialogOpen, setAddDialogOpen] = useState(false)
  const [addExistingDialogOpen, setAddExistingDialogOpen] = useState(false)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [sourceToDelete, setSourceToDelete] = useState<string | null>(null)
  const [removeDialogOpen, setRemoveDialogOpen] = useState(false)
  const [sourceToRemove, setSourceToRemove] = useState<string | null>(null)

  const { openModal } = useModalManager()
  const { jobs, addJob, updateJob, removeJob } = useUploadStore()
  const deleteSource = useDeleteSource()
  const retrySource = useRetrySource()
  const removeFromNotebook = useRemoveSourceFromNotebook()
  const watcherCursorRef = useRef(0)
  const completionTimeoutsRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())

  const notebookJobs = useMemo(
    () => jobs.filter((job) => job.notebookId === notebookId),
    [jobs, notebookId]
  )

  // Collapsible column state
  const { sourcesCollapsed, toggleSources } = useNotebookColumnsStore()
  const collapseButton = useMemo(
    () => createCollapseButton(toggleSources, t.navigation.sources),
    [toggleSources, t.navigation.sources]
  )

  // Scroll container ref for infinite scroll
  const scrollContainerRef = useRef<HTMLDivElement>(null)

  // Handle scroll for infinite loading
  const handleScroll = useCallback(() => {
    const container = scrollContainerRef.current
    if (!container || !hasNextPage || isFetchingNextPage || !fetchNextPage) return

    const { scrollTop, scrollHeight, clientHeight } = container
    // Load more when user scrolls within 200px of the bottom
    if (scrollHeight - scrollTop - clientHeight < 200) {
      fetchNextPage()
    }
  }, [hasNextPage, isFetchingNextPage, fetchNextPage])

  // Attach scroll listener
  useEffect(() => {
    const container = scrollContainerRef.current
    if (!container) return

    container.addEventListener('scroll', handleScroll)
    return () => container.removeEventListener('scroll', handleScroll)
  }, [handleScroll])

  const handleDeleteClick = (sourceId: string) => {
    setSourceToDelete(sourceId)
    setDeleteDialogOpen(true)
  }

  const handleDeleteConfirm = async () => {
    if (!sourceToDelete) return

    try {
      await deleteSource.mutateAsync(sourceToDelete)
      setDeleteDialogOpen(false)
      setSourceToDelete(null)
      onRefresh?.()
    } catch (error) {
      console.error('Failed to delete source:', error)
    }
  }

  const handleRemoveFromNotebook = (sourceId: string) => {
    setSourceToRemove(sourceId)
    setRemoveDialogOpen(true)
  }

  const handleRemoveConfirm = async () => {
    if (!sourceToRemove) return

    try {
      await removeFromNotebook.mutateAsync({
        notebookId,
        sourceId: sourceToRemove
      })
      setRemoveDialogOpen(false)
      setSourceToRemove(null)
    } catch (error) {
      console.error('Failed to remove source from notebook:', error)
      // Error toast is handled by the hook
    }
  }

  const handleRetry = async (sourceId: string) => {
    try {
      await retrySource.mutateAsync(sourceId)
    } catch (error) {
      console.error('Failed to retry source:', error)
    }
  }

  const handleSourceClick = (sourceId: string) => {
    openModal('source', sourceId)
  }

  useEffect(() => {
    const pending = notebookJobs.filter((job) => job.stage !== 'complete' && job.stage !== 'error')
    if (pending.length === 0) return

    let active = true
    const poll = async () => {
      await Promise.all(
        pending.map(async (job) => {
          try {
            const latest = await sourcesApi.getUploadProgress(job.id)
            if (!active) return

            const wasPending = job.stage !== 'complete' && job.stage !== 'error'
            const nowComplete = latest.stage === 'complete'
            updateJob(job.id, {
              stage: latest.stage,
              progress: latest.progress,
              sourceId: latest.source_id ?? null,
              errorMessage: latest.error_message ?? undefined,
            })

            if (wasPending && nowComplete) {
              onRefresh?.()
              if (!completionTimeoutsRef.current.has(job.id)) {
                const timeoutId = setTimeout(() => {
                  removeJob(job.id)
                  completionTimeoutsRef.current.delete(job.id)
                }, 5000)
                completionTimeoutsRef.current.set(job.id, timeoutId)
              }
            }
          } catch {
            // Ignore transient progress polling errors.
          }
        })
      )
    }

    poll()
    const intervalId = setInterval(poll, 2000)
    return () => {
      active = false
      clearInterval(intervalId)
    }
  }, [notebookJobs, onRefresh, removeJob, updateJob])

  useEffect(() => {
    let active = true
    watcherCursorRef.current = 0
    const completionTimeouts = completionTimeoutsRef.current
    const pollEvents = async () => {
      try {
        const result = await sourcesApi.listUploadEvents(notebookId, watcherCursorRef.current)
        if (!active) return

        watcherCursorRef.current = result.cursor
        await Promise.all(
          result.events.map(async (event) => {
            try {
              const latest = await sourcesApi.getUploadProgress(event.job_id)
              if (!active) return

              addJob({
                id: latest.id,
                paperName: latest.paper_name,
                notebookId: latest.notebook_id,
                sourceId: latest.source_id ?? null,
                trigger: latest.trigger,
                stage: latest.stage,
                progress: latest.progress,
                errorMessage: latest.error_message ?? undefined,
              })
            } catch {
              // Ignore stale event jobs that no longer exist.
            }
          })
        )
      } catch {
        // Ignore transient watcher polling errors.
      }
    }

    pollEvents()
    const intervalId = setInterval(pollEvents, 2000)
    return () => {
      active = false
      clearInterval(intervalId)
      completionTimeouts.forEach((timeoutId) => clearTimeout(timeoutId))
      completionTimeouts.clear()
    }
  }, [addJob, notebookId])

  return (
    <>
      <CollapsibleColumn
        isCollapsed={sourcesCollapsed}
        onToggle={toggleSources}
        collapsedIcon={FileText}
        collapsedLabel={t.navigation.sources}
      >
        <Card className="h-full flex flex-col flex-1 overflow-hidden">
          <CardHeader className="pb-3 flex-shrink-0">
            <div className="flex items-center justify-between gap-2">
              <CardTitle className="text-lg">{t.navigation.sources}</CardTitle>
              <div className="flex items-center gap-2">
                <DropdownMenu open={dropdownOpen} onOpenChange={setDropdownOpen}>
                  <DropdownMenuTrigger asChild>
                    <Button size="sm">
                      <Plus className="h-4 w-4 mr-2" />
                      {t.sources.addSource}
                      <ChevronDown className="h-4 w-4 ml-2" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onClick={() => { setDropdownOpen(false); setAddDialogOpen(true); }}>
                      <Plus className="h-4 w-4 mr-2" />
                      {t.sources.addSource}
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => { setDropdownOpen(false); setAddExistingDialogOpen(true); }}>
                      <Link2 className="h-4 w-4 mr-2" />
                      {t.sources.addExistingTitle}
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
                {collapseButton}
              </div>
            </div>
          </CardHeader>

          <CardContent ref={scrollContainerRef} className="flex-1 overflow-y-auto min-h-0">
            {isLoading ? (
              <div className="flex items-center justify-center py-8">
                <LoadingSpinner />
              </div>
            ) : (
              <div className="space-y-6">
                {notebookJobs.length > 0 && (
                  <div className="space-y-3">
                    {notebookJobs.map((job) => (
                      <div
                        key={job.id}
                        className="rounded-lg border border-teal-200 bg-teal-50 p-3"
                      >
                        <div className="flex items-center justify-between gap-3">
                          <p className="text-sm font-medium truncate">{job.paperName}</p>
                          <span className="text-xs text-muted-foreground">
                            {job.stage === 'complete' ? '✓ Ready' : STAGE_LABEL[job.stage]}
                          </span>
                        </div>
                        <div className="mt-2 h-1.5 w-full rounded-full bg-teal-100">
                          <div
                            className="h-1.5 rounded-full bg-teal-600 transition-all duration-500"
                            style={{ width: `${job.progress}%` }}
                          />
                        </div>
                        {job.stage === 'error' && (
                          <div className="mt-2 flex items-center justify-between gap-2">
                            <p className="text-xs text-red-600 truncate">
                              {job.errorMessage || 'Processing failed'}
                            </p>
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-7 px-2 text-xs"
                              disabled={!job.sourceId}
                              onClick={() => {
                                if (job.sourceId) {
                                  handleRetry(job.sourceId)
                                }
                              }}
                            >
                              Retry
                            </Button>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                {/* Sources Section */}
                {!sources || sources.length === 0 ? (
                  <EmptyState
                    icon={FileText}
                    title={t.sources.noSourcesYet}
                    description={t.sources.createFirstSource}
                  />
                ) : (
                  <div className="space-y-3">
                    {sources.map((source) => (
                      <SourceCard
                        key={source.id}
                        source={source}
                        onClick={handleSourceClick}
                        onDelete={handleDeleteClick}
                        onRetry={handleRetry}
                        onRemoveFromNotebook={handleRemoveFromNotebook}
                        onRefresh={onRefresh}
                        showRemoveFromNotebook={true}
                        contextMode={contextSelections?.[source.id]}
                        onContextModeChange={onContextModeChange
                          ? (mode) => onContextModeChange(source.id, mode)
                          : undefined
                        }
                      />
                    ))}
                    {/* Loading indicator for infinite scroll */}
                    {isFetchingNextPage && (
                      <div className="flex items-center justify-center py-4">
                        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </CollapsibleColumn>

      <AddSourceDialog
        open={addDialogOpen}
        onOpenChange={setAddDialogOpen}
        defaultNotebookId={notebookId}
      />

      <AddExistingSourceDialog
        open={addExistingDialogOpen}
        onOpenChange={setAddExistingDialogOpen}
        notebookId={notebookId}
        onSuccess={onRefresh}
      />

      <ConfirmDialog
        open={deleteDialogOpen}
        onOpenChange={setDeleteDialogOpen}
        title={t.sources.delete}
        description={t.sources.deleteConfirm}
        confirmText={t.common.delete}
        onConfirm={handleDeleteConfirm}
        isLoading={deleteSource.isPending}
        confirmVariant="destructive"
      />

      <ConfirmDialog
        open={removeDialogOpen}
        onOpenChange={setRemoveDialogOpen}
        title={t.sources.removeFromNotebook}
        description={t.sources.removeConfirm}
        confirmText={t.common.remove}
        onConfirm={handleRemoveConfirm}
        isLoading={removeFromNotebook.isPending}
        confirmVariant="default"
      />
    </>
  )
}
