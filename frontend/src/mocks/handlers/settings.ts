import { http, HttpResponse } from 'msw'
import { mockSettings } from '../data/settings'

export const settingsHandlers = [
  // GET /api/settings
  http.get('/api/settings', () => {
    return HttpResponse.json(mockSettings)
  }),

  // PUT /api/settings
  http.put('/api/settings', async ({ request }) => {
    const body = await request.json() as Record<string, unknown>
    return HttpResponse.json({ ...mockSettings, ...body })
  }),
]