import { http, HttpResponse } from 'msw'
import { mockNotes } from '../data/notes'
import { NoteResponse } from '@/lib/types/api'

type MockNote = NoteResponse & {
  source_id?: string | null
  notebook_id?: string | null
}

type NoteUpsertBody = {
  title?: string
  content?: string
  note_type?: string
  source_id?: string | null
  notebook_id?: string | null
}

let notes: MockNote[] = [...(mockNotes as MockNote[])]

export const noteHandlers = [
  // GET /api/notes
  http.get('/api/notes', ({ request }) => {
    const url = new URL(request.url)
    const notebookId = url.searchParams.get('notebook_id')
    const sourceId = url.searchParams.get('source_id')

    let filtered = notes
    if (notebookId) {
      filtered = notes.filter(n => n.notebook_id === notebookId)
    }
    if (sourceId) {
      filtered = notes.filter(n => n.source_id === sourceId)
    }

    return HttpResponse.json(filtered)
  }),

  // GET /api/notes/:id
  http.get('/api/notes/:id', ({ params }) => {
    const note = notes.find(n => n.id === params.id)
    if (!note) {
      return new HttpResponse(null, { status: 404 })
    }
    return HttpResponse.json(note)
  }),

  // POST /api/notes
  http.post('/api/notes', async ({ request }) => {
    const body = await request.json() as NoteUpsertBody
    const newNote = {
      id: `note-${Date.now()}`,
      title: body.title || 'New Note',
      content: body.content || '',
      note_type: body.note_type || 'notes',
      source_id: body.source_id || null,
      notebook_id: body.notebook_id,
      created: new Date().toISOString(),
      updated: new Date().toISOString(),
    }
    notes.unshift(newNote)
    return HttpResponse.json(newNote)
  }),

  // PUT /api/notes/:id
  http.put('/api/notes/:id', async ({ params, request }) => {
    const body = await request.json() as NoteUpsertBody
    const idx = notes.findIndex(n => n.id === params.id)
    if (idx === -1) return new HttpResponse(null, { status: 404 })

    notes[idx] = {
      ...notes[idx],
      ...body,
      updated: new Date().toISOString(),
    }
    return HttpResponse.json(notes[idx])
  }),

  // DELETE /api/notes/:id
  http.delete('/api/notes/:id', ({ params }) => {
    const idx = notes.findIndex(n => n.id === params.id)
    if (idx !== -1) notes.splice(idx, 1)
    return HttpResponse.json({ message: 'Note deleted' })
  }),
]