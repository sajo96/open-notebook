'use client'

import { useMemo, useRef, useState } from 'react'
import '@/lib/pdf-polyfills'
import { Document, Page } from 'react-pdf'
import { Loader2, FileX } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { PdfToolbar } from './PdfToolbar'
import { AnnotationOverlay } from './AnnotationOverlay'
import { AnnotationPopup } from './AnnotationPopup'
import {
  useAnnotations,
  useClearAnnotations,
  useCreateAnnotation,
} from '@/lib/hooks/use-annotations'
import { useTranslation } from '@/lib/hooks/use-translation'
import { createMockPdfBytes, getPdfUrl } from '@/lib/utils/pdf'
import type { AnnotationCreate } from '@/lib/types/api'
import '@/lib/pdf-worker'
import 'react-pdf/dist/esm/Page/AnnotationLayer.css'
import 'react-pdf/dist/esm/Page/TextLayer.css'

interface PdfViewerProps {
  sourceId: string
}

type AnnotationTool = 'highlight' | 'underline' | 'note'

interface SelectionState {
  text: string
  pageNumber: number
  boundingBoxes: Array<{ x1: number; y1: number; x2: number; y2: number }>
  popupPosition: { x: number; y: number }
}

export function PdfViewer({ sourceId }: PdfViewerProps) {
  const { t } = useTranslation()
  const [numPages, setNumPages] = useState<number | null>(null)
  const [currentPage, setCurrentPage] = useState(1)
  const [zoom, setZoom] = useState(1.0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeTool, setActiveTool] = useState<AnnotationTool>('highlight')
  const [selection, setSelection] = useState<SelectionState | null>(null)
  const pageRefs = useRef<Record<number, HTMLDivElement | null>>({})

  const { data: annotationsData } = useAnnotations(sourceId)
  const createAnnotation = useCreateAnnotation(sourceId)
  const clearAnnotations = useClearAnnotations(sourceId)
  const annotations = Array.isArray(annotationsData) ? annotationsData : []
  const pageLabel = t.pdfReader.pageOf
    .replace('{page}', String(currentPage))
    .replace('{total}', String(numPages || 0))

  const pdfFile = useMemo(() => {
    if (process.env.NEXT_PUBLIC_MOCK_API === 'true') {
      return {
        data: createMockPdfBytes(sourceId),
      }
    }

    const file: { url: string; httpHeaders?: Record<string, string> } = {
      url: getPdfUrl(sourceId),
    }

    if (typeof window !== 'undefined') {
      const authStorage = localStorage.getItem('auth-storage')
      if (authStorage) {
        try {
          const parsed = JSON.parse(authStorage)
          const token = parsed?.state?.token
          if (token) {
            file.httpHeaders = { Authorization: `Bearer ${token}` }
          }
        } catch {
          // No-op: reader still works for non-protected endpoints.
        }
      }
    }

    return file
  }, [sourceId])

  const onDocumentLoadSuccess = ({ numPages }: { numPages: number }) => {
    setNumPages(numPages)
    setCurrentPage(1)
    setLoading(false)
  }

  const onDocumentLoadError = (error: Error) => {
    console.error('PDF load error:', error)
    setError(t.pdfReader.loadError)
    setLoading(false)
  }

  const handlePageChange = (page: number) => {
    if (!numPages) return
    const targetPage = Math.max(1, Math.min(page, numPages))
    setCurrentPage(targetPage)

    const pageEl = pageRefs.current[targetPage]
    if (pageEl) {
      pageEl.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }

  const handleZoomIn = () => setZoom(prev => Math.min(prev + 0.25, 3))
  const handleZoomOut = () => setZoom(prev => Math.max(prev - 0.25, 0.5))

  const handleSelection = (pageNumber: number, container: HTMLDivElement) => {
    const selectionObj = window.getSelection()
    if (!selectionObj || selectionObj.rangeCount === 0) {
      return
    }

    const selectedText = selectionObj.toString().trim()
    if (!selectedText) {
      setSelection(null)
      return
    }

    const range = selectionObj.getRangeAt(0)
    if (!container.contains(range.commonAncestorContainer)) {
      return
    }

    const pageRect = container.getBoundingClientRect()
    const rects = Array.from(range.getClientRects()).filter(
      rect => rect.width > 0 && rect.height > 0
    )

    if (rects.length === 0 || pageRect.width === 0 || pageRect.height === 0) {
      return
    }

    const boundingBoxes = rects.map(rect => ({
      x1: (rect.left - pageRect.left) / pageRect.width,
      y1: (rect.top - pageRect.top) / pageRect.height,
      x2: (rect.right - pageRect.left) / pageRect.width,
      y2: (rect.bottom - pageRect.top) / pageRect.height,
    }))

    const anchorRect = rects[0]
    setSelection({
      text: selectedText,
      pageNumber,
      boundingBoxes,
      popupPosition: {
        x: Math.max(120, Math.min(window.innerWidth - 120, anchorRect.left + anchorRect.width / 2)),
        y: Math.max(80, Math.min(window.innerHeight - 40, anchorRect.bottom + 12)),
      },
    })

    selectionObj.removeAllRanges()
  }

  const handleCreateAnnotation = async (comment?: string) => {
    if (!selection || createAnnotation.isPending) return

    const annotation: AnnotationCreate = {
      page_number: selection.pageNumber,
      annotation_type: activeTool,
      selected_text: selection.text,
      bounding_boxes: selection.boundingBoxes,
      color: activeTool === 'highlight' ? '#fef08a' : undefined,
      comment,
    }

    await createAnnotation.mutateAsync(annotation)
    setSelection(null)
  }

  const handleClearAll = async () => {
    await clearAnnotations.mutateAsync()
    setSelection(null)
  }

  const clearSelection = () => {
    setSelection(null)
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-8">
        <FileX className="h-12 w-12 text-muted-foreground mb-4" />
        <p className="text-muted-foreground">{error}</p>
        <Button onClick={() => window.location.reload()} className="mt-4">
          {t.pdfReader.tryAgain}
        </Button>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      <PdfToolbar
        currentPage={currentPage}
        numPages={numPages}
        zoom={zoom}
        activeTool={activeTool}
        onZoomIn={handleZoomIn}
        onZoomOut={handleZoomOut}
        onToolChange={setActiveTool}
        onClearAll={handleClearAll}
        isClearing={clearAnnotations.isPending}
      />

      <div className="flex-1 overflow-auto relative bg-gray-100 p-4">
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-white/80 z-50">
            <Loader2 className="h-8 w-8 animate-spin text-gray-400" />
          </div>
        )}

        <Document
          file={pdfFile}
          loading={<div className="flex items-center justify-center h-full"><Loader2 className="h-8 w-8 animate-spin text-gray-400" /></div>}
          onLoadSuccess={onDocumentLoadSuccess}
          onLoadError={onDocumentLoadError}
          error={<div className="flex items-center justify-center h-full text-red-500">{t.pdfReader.loadError}</div>}
        >
          {Array.from({ length: numPages || 0 }, (_, index) => {
            const pageNumber = index + 1
            const pageAnnotations = annotations.filter(ann => ann.page_number === pageNumber)

            return (
              <div
                key={`page-${pageNumber}`}
                className="flex justify-center mb-4"
                ref={node => {
                  pageRefs.current[pageNumber] = node
                }}
                onMouseUp={event => handleSelection(pageNumber, event.currentTarget)}
              >
                <div className="relative inline-block">
                  <Page
                    pageNumber={pageNumber}
                    scale={zoom}
                    renderTextLayer={true}
                    renderAnnotationLayer={false}
                    className="shadow-lg"
                  />
                  <AnnotationOverlay annotations={pageAnnotations} />
                </div>
              </div>
            )
          })}
        </Document>

        <AnnotationPopup
          open={!!selection}
          tool={activeTool}
          selectedText={selection?.text || ''}
          position={selection?.popupPosition}
          isSaving={createAnnotation.isPending}
          onCancel={clearSelection}
          onConfirm={handleCreateAnnotation}
        />
      </div>

      {/* Page Navigation */}
      <div className="flex justify-between items-center px-4 py-2 border-t bg-background">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => handlePageChange(Math.max(currentPage - 1, 1))}
          disabled={currentPage <= 1}
        >
          {t.pdfReader.previous}
        </Button>
        <span className="text-sm text-muted-foreground">
          {pageLabel}
        </span>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => handlePageChange(currentPage + 1)}
          disabled={!numPages || currentPage >= numPages}
        >
          {t.pdfReader.next}
        </Button>
      </div>
    </div>
  )
}