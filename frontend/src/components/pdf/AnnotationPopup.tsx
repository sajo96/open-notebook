'use client'

import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { useTranslation } from '@/lib/hooks/use-translation'

type AnnotationTool = 'highlight' | 'underline' | 'note'

interface AnnotationPopupProps {
    open: boolean
    selectedText: string
    tool: AnnotationTool
    position?: { x: number; y: number }
    isSaving?: boolean
    onConfirm: (comment?: string) => Promise<void> | void
    onCancel: () => void
}

export function AnnotationPopup({
    open,
    selectedText,
    tool,
    position,
    isSaving = false,
    onConfirm,
    onCancel,
}: AnnotationPopupProps) {
    const { t } = useTranslation()
    const [comment, setComment] = useState('')

    useEffect(() => {
        if (!open) {
            setComment('')
        }
    }, [open])

    if (!open || !position) {
        return null
    }

    const toolLabel =
        tool === 'highlight'
            ? t.pdfReader.tools.highlight
            : tool === 'underline'
                ? t.pdfReader.tools.underline
                : t.pdfReader.tools.note

    const confirmLabel =
        tool === 'note' ? t.pdfReader.actions.addNote : t.pdfReader.actions.saveAnnotation

    return (
        <div
            className="fixed z-[80] w-80 rounded-lg border bg-background p-3 shadow-xl"
            style={{ left: position.x, top: position.y, transform: 'translateX(-50%)' }}
        >
            <div className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {toolLabel}
            </div>

            <div className="mb-3 max-h-20 overflow-y-auto rounded-md bg-muted px-2 py-1 text-sm">
                {selectedText}
            </div>

            <Textarea
                rows={3}
                value={comment}
                onChange={event => setComment(event.target.value)}
                placeholder={t.pdfReader.commentPlaceholder}
                className="mb-3"
            />

            <div className="flex justify-end gap-2">
                <Button type="button" variant="outline" size="sm" onClick={onCancel} disabled={isSaving}>
                    {t.common.cancel}
                </Button>
                <Button
                    type="button"
                    size="sm"
                    onClick={() => onConfirm(comment.trim() || undefined)}
                    disabled={isSaving}
                >
                    {confirmLabel}
                </Button>
            </div>
        </div>
    )
}
