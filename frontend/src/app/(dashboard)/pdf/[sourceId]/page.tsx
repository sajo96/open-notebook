'use client'

import { useParams, useRouter } from 'next/navigation'
import { useCallback } from 'react'
import { Button } from '@/components/ui/button'
import { ArrowLeft } from 'lucide-react'
import { useNavigation } from '@/lib/hooks/use-navigation'
import { PdfViewer } from '@/components/pdf/PdfViewer'

export default function PdfReaderPage() {
  const router = useRouter()
  const params = useParams()
  const navigation = useNavigation()

  const sourceId = params?.sourceId
    ? decodeURIComponent(params.sourceId as string)
    : ''

  const handleBack = useCallback(() => {
    const returnPath = navigation.getReturnPath()
    router.push(returnPath)
    navigation.clearReturnTo()
  }, [navigation, router])

  return (
    <div className="flex flex-col h-screen bg-background">
      {/* Top toolbar */}
      <div className="flex items-center gap-3 px-4 py-2 border-b bg-background z-50 shrink-0">
        <Button
          variant="ghost"
          size="sm"
          onClick={handleBack}
          className="flex items-center gap-2"
        >
          <ArrowLeft className="h-4 w-4" />
          {navigation.getReturnLabel()}
        </Button>
      </div>

      {/* PDF viewer fills remaining space */}
      <div className="flex-1 overflow-hidden">
        <PdfViewer sourceId={sourceId} />
      </div>
    </div>
  )
}