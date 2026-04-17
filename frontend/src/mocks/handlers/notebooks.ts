import { http, HttpResponse } from 'msw'
import { mockNotebooks } from '../data/notebooks'

let notebooks = [...mockNotebooks]

export const notebookHandlers = [
  // GET /api/notebooks
  http.get('/api/notebooks', ({ request }) => {
    const url = new URL(request.url)
    const archived = url.searchParams.get('archived')

    let filtered = notebooks
    if (archived === 'true') {
      filtered = notebooks.filter(n => n.archived)
    } else if (archived === 'false') {
      filtered = notebooks.filter(n => !n.archived)
    }

    return HttpResponse.json(filtered)
  }),

  // GET /api/notebooks/:id
  http.get('/api/notebooks/:id', ({ params }) => {
    const notebook = notebooks.find(n => n.id === params.id)
    if (!notebook) {
      return new HttpResponse(null, { status: 404 })
    }
    return HttpResponse.json(notebook)
  }),

  // POST /api/notebooks
  http.post('/api/notebooks', async ({ request }) => {
    const body = await request.json() as { name: string; description?: string }
    const newNotebook = {
      id: `nb-${Date.now()}`,
      name: body.name,
      description: body.description || '',
      archived: false,
      created: new Date().toISOString(),
      updated: new Date().toISOString(),
      source_count: 0,
      note_count: 0,
    }
    notebooks.unshift(newNotebook)
    return HttpResponse.json(newNotebook)
  }),

  // PUT /api/notebooks/:id
  http.put('/api/notebooks/:id', async ({ params, request }) => {
    const body = await request.json()
    const idx = notebooks.findIndex(n => n.id === params.id)
    if (idx === -1) return new HttpResponse(null, { status: 404 })
    notebooks[idx] = { ...notebooks[idx], ...body, updated: new Date().toISOString() }
    return HttpResponse.json(notebooks[idx])
  }),

  // GET /api/notebooks/:id/delete-preview
  http.get('/api/notebooks/:id/delete-preview', ({ params }) => {
    const notebook = notebooks.find(n => n.id === params.id)
    if (!notebook) {
      return new HttpResponse(null, { status: 404 })
    }
    return HttpResponse.json({
      notebook_id: params.id,
      notebook_name: notebook.name,
      note_count: notebook.note_count,
      exclusive_source_count: 0,
      shared_source_count: 0,
    })
  }),

  // DELETE /api/notebooks/:id
  http.delete('/api/notebooks/:id', ({ params }) => {
    const idx = notebooks.findIndex(n => n.id === params.id)
    if (idx !== -1) notebooks.splice(idx, 1)
    return HttpResponse.json({
      message: 'Notebook deleted',
      deleted_notes: 0,
      deleted_sources: 0,
      unlinked_sources: 0,
    })
  }),

  // POST /api/notebooks/:notebookId/sources/:sourceId
  http.post('/api/notebooks/:notebookId/sources/:sourceId', ({ params }) => {
    return HttpResponse.json({
      message: 'Source added to notebook',
    })
  }),

  // DELETE /api/notebooks/:notebookId/sources/:sourceId
  http.delete('/api/notebooks/:notebookId/sources/:sourceId', ({ params }) => {
    return HttpResponse.json({
      message: 'Source removed from notebook',
    })
  }),
]