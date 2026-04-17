import { http, HttpResponse } from 'msw'
import { mockModels } from '../data/models'

export const modelHandlers = [
  // GET /api/models
  http.get('/api/models', () => {
    return HttpResponse.json(mockModels)
  }),

  // POST /api/models
  http.post('/api/models', async ({ request }) => {
    const body = await request.json() as any
    const newModel = {
      id: `model-${Date.now()}`,
      name: body.name,
      provider: body.provider,
      type: body.type,
      credential: body.credential || null,
      created: new Date().toISOString(),
      updated: new Date().toISOString(),
    }
    return HttpResponse.json(newModel)
  }),

  // GET /api/models/defaults
  http.get('/api/models/defaults', () => {
    return HttpResponse.json({
      language: 'gpt-4o',
      embedding: 'text-embedding-3-small',
      text_to_speech: null,
      speech_to_text: null,
    })
  }),

  // PUT /api/models/defaults
  http.put('/api/models/defaults', async ({ request }) => {
    const body = await request.json() as Record<string, unknown>
    return HttpResponse.json({ ...body })
  }),

  // GET /api/models/providers
  http.get('/api/models/providers', () => {
    return HttpResponse.json({
      openai: true,
      anthropic: true,
      groq: false,
      google: false,
      ollama: false,
    })
  }),

  // GET /api/models/discover/:provider
  http.get('/api/models/discover/:provider', ({ params }) => {
    return HttpResponse.json([
      { model_id: params.provider + '-model-1', name: 'Model 1' },
      { model_id: params.provider + '-model-2', name: 'Model 2' },
    ])
  }),

  // POST /api/models/sync/:provider
  http.post('/api/models/sync/:provider', ({ params }) => {
    return HttpResponse.json({
      provider: params.provider,
      models_discovered: 2,
      models_registered: 2,
      message: 'Models synchronized successfully',
    })
  }),

  // POST /api/models/sync
  http.post('/api/models/sync', () => {
    return HttpResponse.json({
      results: [
        { provider: 'openai', success: true, models_discovered: 5, models_registered: 5 },
        { provider: 'anthropic', success: true, models_discovered: 3, models_registered: 3 },
      ],
      total_discovered: 8,
      total_registered: 8,
    })
  }),

  // GET /api/models/count/:provider
  http.get('/api/models/count/:provider', ({ params }) => {
    return HttpResponse.json({
      provider: params.provider,
      count: 2,
    })
  }),

  // GET /api/models/by-provider/:provider
  http.get('/api/models/by-provider/:provider', ({ params }) => {
    const providerModels = mockModels.filter(m => m.provider === params.provider)
    return HttpResponse.json(providerModels)
  }),

  // POST /api/models/auto-assign
  http.post('/api/models/auto-assign', () => {
    return HttpResponse.json({
      assigned_language: 'gpt-4o',
      assigned_embedding: 'text-embedding-3-small',
      message: 'Models auto-assigned successfully',
    })
  }),

  // GET /api/models/:id
  http.get('/api/models/:id', ({ params }) => {
    const model = mockModels.find(m => m.id === params.id)
    if (!model) {
      return new HttpResponse(null, { status: 404 })
    }
    return HttpResponse.json(model)
  }),

  // DELETE /api/models/:id
  http.delete('/api/models/:id', () => {
    return HttpResponse.json({ message: 'Model deleted' })
  }),

  // POST /api/models/:id/test
  http.post('/api/models/:id/test', ({ params }) => {
    return HttpResponse.json({
      model_id: params.id,
      success: true,
      message: 'Model connection successful',
      response_time: 1500,
    })
  }),
]