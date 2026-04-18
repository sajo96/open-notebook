import apiClient from './client'
import type { AnnotationCreate, AnnotationResponse } from '@/lib/types/api'

export type { AnnotationCreate, AnnotationResponse }

export const annotationsApi = {
  /**
   * Get all annotations for a source
   */
  list: async (sourceId: string) => {
    const response = await apiClient.get<AnnotationResponse[]>(
      `/sources/${encodeURIComponent(sourceId)}/annotations`
    )
    return response.data
  },

  /**
   * Create a new annotation
   */
  create: async (sourceId: string, data: AnnotationCreate) => {
    const response = await apiClient.post<AnnotationResponse>(
      `/sources/${encodeURIComponent(sourceId)}/annotations`,
      data
    )
    return response.data
  },

  /**
   * Update an existing annotation
   */
  update: async (annotationId: string, data: Partial<AnnotationCreate>) => {
    const response = await apiClient.patch<AnnotationResponse>(
      `/annotations/${encodeURIComponent(annotationId)}`,
      data
    )
    return response.data
  },

  /**
   * Delete a single annotation
   */
  delete: async (annotationId: string) => {
    await apiClient.delete(`/annotations/${encodeURIComponent(annotationId)}`)
    return { deleted: annotationId }
  },

  /**
   * Delete all annotations for a source
   */
  deleteAll: async (sourceId: string) => {
    await apiClient.delete(`/sources/${encodeURIComponent(sourceId)}/annotations`)
    return { cleared: sourceId }
  },
}