'use client'

import { useState } from 'react'
import {
    Highlighter,
    Underline,
    StickyNote,
    ZoomIn,
    ZoomOut,
    Trash2,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { useTranslation } from '@/lib/hooks/use-translation'

type AnnotationTool = 'highlight' | 'underline' | 'note'

interface PdfToolbarProps {
    currentPage: number
    numPages: number | null
    zoom: number
    activeTool: AnnotationTool
    isClearing?: boolean
    onToolChange: (tool: AnnotationTool) => void
    onZoomIn: () => void
    onZoomOut: () => void
    onClearAll: () => Promise<void> | void
}

export function PdfToolbar({
    currentPage,
    numPages,
    zoom,
    activeTool,
    isClearing = false,
    onToolChange,
    onZoomIn,
    onZoomOut,
    onClearAll,
}: PdfToolbarProps) {
    const { t } = useTranslation()
    const [confirmOpen, setConfirmOpen] = useState(false)
    const pageLabel = t.pdfReader.pageOf
        .replace('{page}', String(currentPage))
        .replace('{total}', String(numPages || 0))

    const handleConfirmClear = async () => {
        await onClearAll()
        setConfirmOpen(false)
    }

    const toolButtons: Array<{ key: AnnotationTool; icon: typeof Highlighter; label: string }> = [
        { key: 'highlight', icon: Highlighter, label: t.pdfReader.tools.highlight },
        { key: 'underline', icon: Underline, label: t.pdfReader.tools.underline },
        { key: 'note', icon: StickyNote, label: t.pdfReader.tools.note },
    ]

    return (
        <>
            <div className="border-b bg-background px-3 py-2">
                <div className="flex flex-wrap items-center gap-2">
                    <div className="flex items-center gap-1">
                        {toolButtons.map(tool => {
                            const Icon = tool.icon
                            const isActive = activeTool === tool.key

                            return (
                                <Tooltip key={tool.key}>
                                    <TooltipTrigger asChild>
                                        <Button
                                            type="button"
                                            size="sm"
                                            variant={isActive ? 'default' : 'outline'}
                                            onClick={() => onToolChange(tool.key)}
                                            aria-label={tool.label}
                                        >
                                            <Icon className="h-4 w-4" />
                                        </Button>
                                    </TooltipTrigger>
                                    <TooltipContent>{tool.label}</TooltipContent>
                                </Tooltip>
                            )
                        })}
                    </div>

                    <Separator orientation="vertical" className="h-6" />

                    <div className="flex items-center gap-1">
                        <Tooltip>
                            <TooltipTrigger asChild>
                                <Button
                                    type="button"
                                    size="sm"
                                    variant="outline"
                                    onClick={onZoomOut}
                                    aria-label={t.pdfReader.zoomOut}
                                >
                                    <ZoomOut className="h-4 w-4" />
                                </Button>
                            </TooltipTrigger>
                            <TooltipContent>{t.pdfReader.zoomOut}</TooltipContent>
                        </Tooltip>

                        <span className="min-w-14 text-center text-sm text-muted-foreground">
                            {Math.round(zoom * 100)}%
                        </span>

                        <Tooltip>
                            <TooltipTrigger asChild>
                                <Button
                                    type="button"
                                    size="sm"
                                    variant="outline"
                                    onClick={onZoomIn}
                                    aria-label={t.pdfReader.zoomIn}
                                >
                                    <ZoomIn className="h-4 w-4" />
                                </Button>
                            </TooltipTrigger>
                            <TooltipContent>{t.pdfReader.zoomIn}</TooltipContent>
                        </Tooltip>
                    </div>

                    <Separator orientation="vertical" className="h-6" />

                    <div className="text-sm text-muted-foreground">
                        {pageLabel}
                    </div>

                    <div className="ml-auto">
                        <Tooltip>
                            <TooltipTrigger asChild>
                                <Button
                                    type="button"
                                    size="sm"
                                    variant="destructive"
                                    onClick={() => setConfirmOpen(true)}
                                >
                                    <Trash2 className="mr-2 h-4 w-4" />
                                    {t.pdfReader.clearAll}
                                </Button>
                            </TooltipTrigger>
                            <TooltipContent>{t.pdfReader.clearAllHint}</TooltipContent>
                        </Tooltip>
                    </div>
                </div>
            </div>

            <ConfirmDialog
                open={confirmOpen}
                onOpenChange={setConfirmOpen}
                title={t.pdfReader.clearAllTitle}
                description={t.pdfReader.clearAllDescription}
                confirmText={t.pdfReader.clearAllConfirm}
                confirmVariant="destructive"
                onConfirm={handleConfirmClear}
                isLoading={isClearing}
            />
        </>
    )
}
