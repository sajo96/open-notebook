'use client'

import React, { useState, useEffect } from 'react'
import { SourceListResponse } from '@/lib/types/api'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator
} from '@/components/ui/dropdown-menu'
import {
  FileText,
  ExternalLink,
  Upload,
  MoreVertical,
  Trash2,
  RefreshCw,
  Clock,
  CheckCircle,
  AlertTriangle,
  Loader2,
  Unlink,
  Pencil,
  Check,
  X
} from 'lucide-react'
import { usePaperStatusBySource, useSourceStatus, useUpdatePaperTitle } from '@/lib/hooks/use-sources'
import { useTranslation } from '@/lib/hooks/use-translation'
import { TranslationKeys } from '@/lib/locales'
import { cn } from '@/lib/utils'
import { ContextToggle } from '@/components/common/ContextToggle'
import { ContextMode } from '@/app/(dashboard)/notebooks/[id]/page'
import { Input } from '@/components/ui/input'

interface SourceCardProps {
  source: SourceListResponse
  onDelete?: (sourceId: string) => void
  onRetry?: (sourceId: string) => void
  onRemoveFromNotebook?: (sourceId: string) => void
  onClick?: (sourceId: string) => void
  onRefresh?: () => void
  className?: string
  showRemoveFromNotebook?: boolean
  contextMode?: ContextMode
  onContextModeChange?: (mode: ContextMode) => void
}

const SOURCE_TYPE_ICONS = {
  link: ExternalLink,
  upload: Upload,
  text: FileText,
} as const

const PIPELINE_STAGE_LABELS: Record<string, string> = {
  ingesting: 'Ingesting',
  parsing: 'Parsing',
  embedding: 'Embedding',
  notes: 'Generating Notes',
  graph: 'Building Graph',
  done: 'Ready',
  failed: 'Failed',
}

const TITLE_SOURCE_LABELS: Record<string, string> = {
  heuristic: 'Unverified title',
  llm: 'Unverified title',
  raw_text: 'Unverified title',
  unknown: 'No title',
}

const getStatusConfig = (t: TranslationKeys) => ({
  new: {
    icon: Clock,
    color: 'text-blue-600',
    bgColor: 'bg-blue-50',
    borderColor: 'border-blue-200',
    label: t.sources.statusProcessing,
    description: t.sources.statusPreparingDesc
  },
  queued: {
    icon: Clock,
    color: 'text-blue-600',
    bgColor: 'bg-blue-50',
    borderColor: 'border-blue-200',
    label: t.sources.statusQueued,
    description: t.sources.statusQueuedDesc
  },
  running: {
    icon: Loader2,
    color: 'text-blue-600',
    bgColor: 'bg-blue-50',
    borderColor: 'border-blue-200',
    label: t.sources.statusProcessing,
    description: t.sources.statusProcessingDesc
  },
  processing: {
    icon: Loader2,
    color: 'text-blue-600',
    bgColor: 'bg-blue-50',
    borderColor: 'border-blue-200',
    label: t.sources.statusProcessing,
    description: t.sources.statusProcessingDesc
  },
  completed: {
    icon: CheckCircle,
    color: 'text-green-600',
    bgColor: 'bg-green-50',
    borderColor: 'border-green-200',
    label: t.sources.statusCompleted,
    description: t.sources.statusCompletedDesc
  },
  failed: {
    icon: AlertTriangle,
    color: 'text-red-600',
    bgColor: 'bg-red-50',
    borderColor: 'border-red-200',
    label: t.sources.statusFailed,
    description: t.sources.statusFailedDesc
  }
} as const)

type SourceStatus = 'new' | 'queued' | 'running' | 'processing' | 'completed' | 'failed'

function isSourceStatus(status: unknown): status is SourceStatus {
  return typeof status === 'string' && ['new', 'queued', 'running', 'processing', 'completed', 'failed'].includes(status)
}

function getSourceType(source: SourceListResponse): 'link' | 'upload' | 'text' {
  // Determine type based on asset information
  if (source.asset?.url) return 'link'
  if (source.asset?.file_path) return 'upload'
  return 'text'
}

export function SourceCard({
  source,
  onClick,
  onDelete,
  onRetry,
  onRemoveFromNotebook,
  onRefresh,
  className,
  showRemoveFromNotebook = false,
  contextMode,
  onContextModeChange
}: SourceCardProps) {
  const { t } = useTranslation()
  const statusConfigMap = getStatusConfig(t)

  // Only fetch status for sources that might have async processing
  const sourceWithStatus = source as SourceListResponse & { command_id?: string; status?: string }

  // Track processing state to continue polling until we detect completion
  const [wasProcessing, setWasProcessing] = useState(false)
  const [showDoneStageBadge, setShowDoneStageBadge] = useState(false)
  const [isEditingTitle, setIsEditingTitle] = useState(false)
  const [draftTitle, setDraftTitle] = useState('')

  const shouldFetchStatus = !!sourceWithStatus.command_id ||
    sourceWithStatus.status === 'new' ||
    sourceWithStatus.status === 'queued' ||
    sourceWithStatus.status === 'running' ||
    sourceWithStatus.status === 'processing' ||
    wasProcessing // Keep polling if we were processing to catch the completion

  const { data: statusData, isLoading: statusLoading } = useSourceStatus(
    source.id,
    shouldFetchStatus
  )
  const { data: paperStatusData } = usePaperStatusBySource(source.id, !!source.id)
  const updatePaperTitleMutation = useUpdatePaperTitle()

  // Determine current status
  // If source has a command_id but no status, treat as "new" (just created)
  const rawStatus = statusData?.status || sourceWithStatus.status
  const currentStatus: SourceStatus = isSourceStatus(rawStatus)
    ? rawStatus
    : (sourceWithStatus.command_id ? 'new' : 'completed')


  // Track processing state and detect completion
  useEffect(() => {
    const currentStatusFromData = statusData?.status || sourceWithStatus.status

    // If we're currently processing, mark that we were processing
    if (currentStatusFromData === 'new' || currentStatusFromData === 'running' || currentStatusFromData === 'queued' || currentStatusFromData === 'processing') {
      setWasProcessing(true)
    }

    // If we were processing and now completed/failed, trigger refresh and stop polling
    if (wasProcessing &&
      (currentStatusFromData === 'completed' || currentStatusFromData === 'failed')) {
      setWasProcessing(false) // Stop polling

      if (onRefresh) {
        setTimeout(() => onRefresh(), 500) // Small delay to ensure API is updated
      }
    }
  }, [statusData, sourceWithStatus.status, wasProcessing, onRefresh, source.id])

  const statusConfig = statusConfigMap[currentStatus] || statusConfigMap.completed
  const StatusIcon = statusConfig.icon
  const sourceType = getSourceType(source)
  const SourceTypeIcon = SOURCE_TYPE_ICONS[sourceType]

  const title = (paperStatusData?.title || source.title || '').trim() || t.sources.untitledSource
  const paperId = paperStatusData?.paper_id

  const handleRetry = () => {
    if (onRetry) {
      onRetry(source.id)
    }
  }

  const handleDelete = () => {
    if (onDelete) {
      onDelete(source.id)
    }
  }

  const handleRemoveFromNotebook = () => {
    if (onRemoveFromNotebook) {
      onRemoveFromNotebook(source.id)
    }
  }

  const handleCardClick = () => {
    if (onClick) {
      onClick(source.id)
    }
  }

  useEffect(() => {
    if (!isEditingTitle) {
      setDraftTitle(title)
    }
  }, [isEditingTitle, title])

  const handleStartTitleEdit = (e: React.MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation()
    if (!paperId) {
      return
    }
    setDraftTitle(title)
    setIsEditingTitle(true)
  }

  const handleCancelTitleEdit = (e: React.MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation()
    setIsEditingTitle(false)
    setDraftTitle(title)
  }

  const saveTitle = () => {
    if (!paperId) {
      return
    }

    const normalizedTitle = draftTitle.trim()
    if (!normalizedTitle || normalizedTitle === title) {
      setIsEditingTitle(false)
      return
    }

    updatePaperTitleMutation.mutate(
      { sourceId: source.id, paperId, title: normalizedTitle },
      {
        onSuccess: () => {
          setIsEditingTitle(false)
        },
      }
    )
  }

  const handleSaveTitle = (e: React.MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation()
    saveTitle()
  }

  const isProcessing: boolean = currentStatus === 'new' || currentStatus === 'running' || currentStatus === 'queued' || currentStatus === 'processing'
  const isFailed: boolean = currentStatus === 'failed'
  const isCompleted: boolean = currentStatus === 'completed'
  const pipelineStage = paperStatusData?.pipeline_stage ?? undefined
  const pipelineLabel = pipelineStage ? PIPELINE_STAGE_LABELS[pipelineStage] || pipelineStage : null
  const pipelineError = paperStatusData?.error_message || null
  const titleSource = paperStatusData?.title_source ?? undefined
  const titleConfidence = paperStatusData?.title_confidence ?? undefined
  const showTitleQualityBadge = !!titleSource && ['heuristic', 'llm', 'raw_text', 'unknown'].includes(titleSource)
  const titleBadgeLabel = titleSource ? TITLE_SOURCE_LABELS[titleSource] || 'Unverified title' : 'Unverified title'
  const titleBadgeVariant = titleSource === 'unknown' ? 'destructive' : 'secondary'
  const titleBadgeTitle = typeof titleConfidence === 'number'
    ? `Title source: ${titleSource}, confidence: ${(titleConfidence * 100).toFixed(0)}%`
    : `Title source: ${titleSource}`
  const pipelineInProgress = !!pipelineStage && !['done', 'failed'].includes(pipelineStage)
  const shouldShowPipelineBadge = !!pipelineLabel && (pipelineStage !== 'done' || showDoneStageBadge)

  useEffect(() => {
    if (pipelineStage === 'done') {
      setShowDoneStageBadge(true)
      const timer = setTimeout(() => setShowDoneStageBadge(false), 2000)
      return () => clearTimeout(timer)
    }

    setShowDoneStageBadge(true)
  }, [pipelineStage])

  return (
    <Card
      className={cn(
        'transition-all duration-200 hover:shadow-md group relative cursor-pointer border border-border/60 dark:border-border/40',
        className
      )}
      onClick={handleCardClick}
    >
      <CardContent className="px-3 py-1">
        {/* Header with status indicator */}
        <div className="flex items-start justify-between gap-3 mb-1">
          <div className="flex-1 min-w-0">
            <div className="flex items-start gap-2 mb-1.5">
              {isEditingTitle ? (
                <div className="min-w-0 flex-1 flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                  <Input
                    value={draftTitle}
                    onChange={(e) => setDraftTitle(e.target.value)}
                    className="h-8 text-sm"
                    autoFocus
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        e.stopPropagation()
                        saveTitle()
                      }
                      if (e.key === 'Escape') {
                        e.preventDefault()
                        setIsEditingTitle(false)
                        setDraftTitle(title)
                      }
                    }}
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7"
                    onClick={handleSaveTitle}
                    disabled={updatePaperTitleMutation.isPending}
                    title={t.common.save}
                  >
                    {updatePaperTitleMutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7"
                    onClick={handleCancelTitleEdit}
                    disabled={updatePaperTitleMutation.isPending}
                    title={t.common.cancel}
                  >
                    <X className="h-3.5 w-3.5" />
                  </Button>
                </div>
              ) : (
                <>
                  <h4
                    className="min-w-0 flex-1 text-sm font-medium leading-tight line-clamp-2 break-all"
                    title={title}
                  >
                    {title}
                  </h4>
                  {paperId && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity"
                      onClick={handleStartTitleEdit}
                      title={t.common.edit}
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                  )}
                </>
              )}
              {!isCompleted && (
                <div className={cn(
                  'flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-medium shrink-0',
                  statusConfig.bgColor,
                  statusConfig.color
                )}>
                  <StatusIcon className={cn(
                    'h-3 w-3',
                    isProcessing && 'animate-spin'
                  )} />
                  {statusLoading && shouldFetchStatus ? t.sources.checking : statusConfig.label}
                </div>
              )}
            </div>

            {/* Source type indicator */}
            <div className="flex items-center gap-1 text-gray-500 mb-1">
              <SourceTypeIcon className="h-3 w-3" />
              <span className="text-xs capitalize">{t.common.source}</span>
            </div>

            {/* Processing message for active statuses */}
            {statusData?.message && (isProcessing || isFailed) && (
              <p className="text-xs text-gray-600 mb-2 italic">
                {statusData.message}
              </p>
            )}

            {shouldShowPipelineBadge && (
              <div className="mb-2">
                <Badge
                  variant={pipelineStage === 'failed' ? 'destructive' : 'outline'}
                  className="text-xs flex items-center gap-1.5"
                  title={pipelineError || undefined}
                >
                  {pipelineInProgress && <Loader2 className="h-3 w-3 animate-spin" />}
                  Stage: {pipelineLabel}
                </Badge>
              </div>
            )}

            {showTitleQualityBadge && (
              <div className="mb-2">
                <Badge
                  variant={titleBadgeVariant}
                  className="text-xs"
                  title={titleBadgeTitle}
                >
                  {titleSource === 'unknown' ? '? No title' : '⚠ Unverified title'}
                </Badge>
              </div>
            )}

            {/* Metadata badges */}
            <div className="flex items-center gap-2 flex-wrap">
              {/* Source type badge */}
              <Badge variant="secondary" className="text-xs flex items-center gap-1">
                <SourceTypeIcon className="h-3 w-3" />
                {sourceType === 'link' ? t.sources.addUrl : sourceType === 'upload' ? t.sources.uploadFile : t.sources.enterText}
              </Badge>

              {isCompleted && source.insights_count > 0 && (
                <Badge variant="outline" className="text-xs">
                  {t.sources.insightsCount.replace('{count}', source.insights_count.toString())}
                </Badge>
              )}
              {source.topics && source.topics.length > 0 && isCompleted && (
                <>
                  {source.topics.slice(0, 2).map((topic, index) => (
                    <Badge key={index} variant="outline" className="text-xs">
                      {topic}
                    </Badge>
                  ))}
                  {source.topics.length > 2 && (
                    <Badge variant="outline" className="text-xs">
                      +{source.topics.length - 2}
                    </Badge>
                  )}
                </>
              )}
            </div>
          </div>

          {/* Context toggle and actions */}
          <div className="flex items-center gap-1">
            {/* Context toggle - only show if handler provided */}
            {onContextModeChange && contextMode && (
              <ContextToggle
                mode={contextMode}
                hasInsights={source.insights_count > 0}
                onChange={onContextModeChange}
              />
            )}

            {/* Actions dropdown */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 w-8 p-0 opacity-0 group-hover:opacity-100 transition-opacity"
                  onClick={(e) => e.stopPropagation()}
                >
                  <MoreVertical className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-48">
                {showRemoveFromNotebook && (
                  <>
                    <DropdownMenuItem
                      onClick={(e) => {
                        e.stopPropagation()
                        handleRemoveFromNotebook()
                      }}
                      disabled={!onRemoveFromNotebook}
                    >
                      <Unlink className="h-4 w-4 mr-2" />
                      {t.sources.removeFromNotebook}
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                  </>
                )}

                {isFailed && (
                  <>
                    <DropdownMenuItem
                      onClick={(e) => {
                        e.stopPropagation()
                        handleRetry()
                      }}
                      disabled={!onRetry}
                    >
                      <RefreshCw className="h-4 w-4 mr-2" />
                      {t.sources.retryProcessing}
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                  </>
                )}

                <DropdownMenuItem
                  onClick={(e) => {
                    e.stopPropagation()
                    handleDelete()
                  }}
                  disabled={!onDelete}
                  className="text-red-600 focus:text-red-600"
                >
                  <Trash2 className="h-4 w-4 mr-2" />
                  {t.sources.deleteSource}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
        {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
        {(isFailed as any) && (
          <div className="flex gap-2 pt-2 border-t">
            <Button
              variant="outline"
              size="sm"
              onClick={handleRetry}
              disabled={!onRetry}
              className="h-7 text-xs"
            >
              <RefreshCw className="h-3 w-3 mr-1" />
              {t.sources.retry}
            </Button>
          </div>
        )}

        {/* Processing progress indicator */}
        {isProcessing && statusData?.processing_info?.progress && (
          <div className="mt-3 pt-2 border-t">
            <div className="flex justify-between items-center mb-1">
              <span className="text-xs text-gray-600">{t.common.progress}</span>
              <span className="text-xs text-gray-600">
                {Math.round(statusData.processing_info.progress as number)}%
              </span>
            </div>
            <div className="w-full bg-gray-200 rounded-full h-1.5">
              <div
                className="bg-blue-600 h-1.5 rounded-full transition-all duration-300"
                style={{ width: `${statusData.processing_info.progress as number}%` }}
              />
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
