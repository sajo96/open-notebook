import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useToast } from '@/lib/hooks/use-toast'
import { useTranslation } from '@/lib/hooks/use-translation'
import { annotationsApi } from '@/lib/api/annotations'
import { QUERY_KEYS } from '@/lib/api/query-client'
import { getApiErrorMessage } from '@/lib/utils/error-handler'
import type { AnnotationCreate } from '@/lib/types/api'

export function useAnnotations(sourceId: string) {
  const query = useQuery({
    queryKey: QUERY_KEYS.annotations(sourceId),
    queryFn: () => annotationsApi.list(sourceId),
    enabled: !!sourceId,
    staleTime: 5 * 60 * 1000, // 5 minutes
    refetchOnWindowFocus: false,
  })

  return query
}

export function useCreateAnnotation(sourceId: string) {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: (data: AnnotationCreate) => annotationsApi.create(sourceId, data),
    onSuccess: () => {
      // Invalidate annotations cache to refresh the list
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.annotations(sourceId),
      })
    },
    onError: (error: unknown) => {
      toast({
        title: t.common.error,
        description: getApiErrorMessage(error),
        variant: 'destructive',
      })
    },
  })
}

export function useUpdateAnnotation(sourceId: string) {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: ({ annotationId, data }: { annotationId: string; data: Partial<AnnotationCreate> }) =>
      annotationsApi.update(annotationId, data),
    onSuccess: (_, variables) => {
      // Invalidate both the specific annotation and the list
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.annotation(variables.annotationId),
      })
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.annotations(sourceId),
      })
    },
    onError: (error: unknown) => {
      toast({
        title: t.common.error,
        description: getApiErrorMessage(error),
        variant: 'destructive',
      })
    },
  })
}

export function useDeleteAnnotation(sourceId: string) {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: (annotationId: string) => annotationsApi.delete(annotationId),
    onSuccess: (_, variables) => {
      // Invalidate both the specific annotation and the list
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.annotation(variables),
      })
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.annotations(sourceId),
      })
      toast({
        title: t.common.success,
        description: t.annotations.deleted,
      })
    },
    onError: (error: unknown) => {
      toast({
        title: t.common.error,
        description: getApiErrorMessage(error),
        variant: 'destructive',
      })
    },
  })
}

export function useClearAnnotations(sourceId: string) {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: () => annotationsApi.deleteAll(sourceId),
    onSuccess: () => {
      // Invalidate the annotations list
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.annotations(sourceId),
      })
      toast({
        title: t.common.success,
        description: t.annotations.allCleared,
      })
    },
    onError: (error: unknown) => {
      toast({
        title: t.common.error,
        description: getApiErrorMessage(error),
        variant: 'destructive',
      })
    },
  })
}