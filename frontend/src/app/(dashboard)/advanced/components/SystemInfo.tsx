'use client'

import { useEffect, useState } from 'react'
import { Card } from '@/components/ui/card'
import { getConfig } from '@/lib/config'
import { Badge } from '@/components/ui/badge'
import { useTranslation } from '@/lib/hooks/use-translation'

export function SystemInfo() {
  const { t } = useTranslation()
  const [config, setConfig] = useState<{
    version: string
  } | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    const loadConfig = async () => {
      try {
        const cfg = await getConfig()
        setConfig(cfg)
      } catch (error) {
        console.error('Failed to load config:', error)
      } finally {
        setIsLoading(false)
      }
    }

    loadConfig()
  }, [])

  if (isLoading) {
    return (
      <Card className="p-6">
        <div className="space-y-4">
          <h2 className="text-xl font-semibold">{t.advanced.systemInfo}</h2>
          <div className="text-sm text-muted-foreground">{t.common.loading}</div>
        </div>
      </Card>
    )
  }

  return (
    <Card className="p-6">
      <div className="space-y-4">
        <h2 className="text-xl font-semibold">{t.advanced.systemInfo}</h2>

        <div className="space-y-3">
          {/* Current Version */}
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">{t.advanced.currentVersion}</span>
            <Badge variant="outline">{config?.version || t.advanced.unknown}</Badge>
          </div>
        </div>
      </div>
    </Card>
  )
}
