import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { drawingsApi } from '../../../lib/api'

export function useWorkspace(projectId: string) {
  const queryClient = useQueryClient()

  // Query: Get drawings in project
  const { data: drawings = [], isLoading: drawingsLoading } = useQuery({
    queryKey: ['drawings', projectId],
    queryFn: () => drawingsApi.list(projectId),
    enabled: !!projectId,
  })

  // Get active drawing ID
  const activeDrawingId = drawings[0]?.id || null

  // Query: Get pages in active drawing
  const { data: pages = [], isLoading: pagesLoading } = useQuery({
    queryKey: ['pages', activeDrawingId],
    queryFn: () => (activeDrawingId ? drawingsApi.listPages(activeDrawingId) : Promise.resolve([])),
    enabled: !!activeDrawingId,
  })

  // Mutation: Update page
  const updatePageMutation = useMutation({
    mutationFn: ({ pageId, data }: { pageId: string; data: any }) =>
      drawingsApi.updatePage(pageId, data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['pages', activeDrawingId] })
      queryClient.invalidateQueries({ queryKey: ['page', variables.pageId] })
    },
  })

  return {
    drawings,
    pages,
    isLoading: drawingsLoading || pagesLoading,
    activeDrawingId,
    updatePage: updatePageMutation.mutateAsync,
  }
}
