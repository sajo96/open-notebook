import { http, HttpResponse } from 'msw'
import { mockSources } from '../data/sources'
import { mockNotes } from '../data/notes'
import { SourceDetailResponse } from '@/lib/types/api'

type SourceCreateBody = {
  title?: string
  topics?: string[]
  asset?: SourceDetailResponse['asset']
  notebook_id?: string
}

export const mockSourcesState: { sources: SourceDetailResponse[] } = {
  sources: [...mockSources],
}

export const sourceHandlers = [
  // GET /api/sources
  http.get('/api/sources', ({ request }) => {
    const url = new URL(request.url)
    const notebookId = url.searchParams.get('notebook_id')
    const type = url.searchParams.get('type')

    let filtered = mockSourcesState.sources
    if (notebookId) {
      filtered = mockSourcesState.sources.filter(s => s.notebooks?.includes(notebookId))
    }
    if (type) {
      // Mock type filtering - in real app this would filter by asset type
    }

    return HttpResponse.json(filtered)
  }),

  // GET /api/sources/:id
  http.get('/api/sources/:id', ({ params }) => {
    const source = mockSourcesState.sources.find(s => s.id === params.id)
    if (!source) {
      return new HttpResponse(null, { status: 404 })
    }
    return HttpResponse.json(source)
  }),

  // POST /api/sources
  http.post('/api/sources', async ({ request }) => {
    const body = await request.json() as SourceCreateBody
    const newSource = {
      id: `src-${Date.now()}`,
      title: body.title || 'New Source',
      topics: body.topics || [],
      asset: body.asset || null,
      embedded: false,
      embedded_chunks: 0,
      insights_count: 0,
      created: new Date().toISOString(),
      updated: new Date().toISOString(),
      full_text: '',
      notebooks: body.notebook_id ? [body.notebook_id] : [],
      status: 'new' as const,
    }
    mockSourcesState.sources.unshift(newSource)
    return HttpResponse.json(newSource)
  }),

  // PUT /api/sources/:id
  http.put('/api/sources/:id', async ({ params, request }) => {
    const body = await request.json() as Partial<SourceDetailResponse>
    const idx = mockSourcesState.sources.findIndex(s => s.id === params.id)
    if (idx === -1) return new HttpResponse(null, { status: 404 })

    mockSourcesState.sources[idx] = {
      ...mockSourcesState.sources[idx],
      ...body,
      updated: new Date().toISOString(),
    }
    return HttpResponse.json(mockSourcesState.sources[idx])
  }),

  // DELETE /api/sources/:id
  http.delete('/api/sources/:id', ({ params }) => {
    const idx = mockSourcesState.sources.findIndex(s => s.id === params.id)
    if (idx !== -1) mockSourcesState.sources.splice(idx, 1)
    return HttpResponse.json({ message: 'Source deleted' })
  }),

  // POST /api/sources/:id/embed
  http.post('/api/sources/:id/embed', async ({ params, request }) => {
    const body = await request.json() as { chunk_count?: number }
    const idx = mockSourcesState.sources.findIndex(s => s.id === params.id)
    if (idx !== -1) {
      mockSourcesState.sources[idx].embedded = true
      mockSourcesState.sources[idx].embedded_chunks = body.chunk_count ?? 3
    }
    return HttpResponse.json({
      message: 'Source embedded successfully',
      chunks: mockSourcesState.sources[idx]?.embedded_chunks || 3,
    })
  }),

  // GET /api/sources/:id/status
  http.get('/api/sources/:id/status', ({ params }) => {
    const source = mockSourcesState.sources.find(s => s.id === params.id)
    if (!source) {
      return new HttpResponse(null, { status: 404 })
    }
    return HttpResponse.json({
      status: 'complete',
      message: 'Source processing completed',
      processing_info: {},
      command_id: null,
    })
  }),

  // GET /api/sources/:id/notes
  http.get('/api/sources/:id/notes', ({ params }) => {
    const notesWithSource = mockNotes as Array<(typeof mockNotes)[number] & { source_id?: string }>
    const sourceNotes = notesWithSource.filter((note) => note.source_id === params.id)
    return HttpResponse.json(sourceNotes)
  }),

  // GET /api/papermind/sources/:id/preview
  http.get('/api/papermind/sources/:id/preview', ({ params }) => {
    const source = mockSourcesState.sources.find(s => s.id === params.id)
    if (!source) {
      return new HttpResponse(null, { status: 404 })
    }
    return HttpResponse.json({
      title: source.title,
      preview_text: source.full_text.substring(0, 200) + '...',
      insights_count: source.insights_count,
    })
  }),
]