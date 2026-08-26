import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { drawingsApi } from '../../../lib/api'

// A project can have more than one uploaded drawing (a second PDF, a re-scan,
// a supplemental page). Every drawing's pages contribute to the SAME building
// once extracted -- see model.py's scope=building merge, which stacks/merges
// by floor T.O.S. regardless of which drawing a page came from. The workspace
// must therefore list and make extractable EVERY page from EVERY drawing in
// the project, not just the first drawing uploaded. Previously this hook
// picked `drawings[0]` only, which silently hid every page belonging to any
// drawing uploaded after the first -- those pages never appeared in the Plans
// rail and could never be extracted into the shared 3D model, producing what
// looked like "separate" buildings instead of one accumulating one.
export function useWorkspace(projectId: string) {
  const queryClient = useQueryClient()

  // Query: Get all drawings in project
  const { data: drawings = [], isLoading: drawingsLoading } = useQuery({
    queryKey: ['drawings', projectId],
    queryFn: () => drawingsApi.list(projectId),
    enabled: !!projectId,
    staleTime: 1000 * 60 * 10,
    gcTime: 1000 * 60 * 30,
  })

  const drawingIds = drawings.map((d: any) => d.id).sort().join(',')

  // Query: Get pages across ALL drawings in the project, flattened into one
  // list (each page already carries its own drawing_id from the API).
  const { data: pages = [], isLoading: pagesLoading } = useQuery({
    queryKey: ['pages', projectId, drawingIds],
    queryFn: async () => {
      if (!drawings.length) return []
      const perDrawing = await Promise.all(
        drawings.map((d: any) => drawingsApi.listPages(d.id))
      )
      return perDrawing.flat()
    },
    enabled: drawings.length > 0,
    staleTime: 1000 * 60 * 10,
    gcTime: 1000 * 60 * 30,
  })

  // Kept for any callers that still want "the first drawing" (e.g. as a
  // default upload target) -- no longer used to scope which pages are shown.
  const activeDrawingId = drawings[0]?.id || null

  // Mutation: Update page (optimistic cache update for instant UI response)
  const updatePageMutation = useMutation({
    mutationFn: ({ pageId, data }: { pageId: string; data: any }) =>
      drawingsApi.updatePage(pageId, data),
    onMutate: async ({ pageId, data }) => {
      // Optimistically update the cached pages list immediately
      queryClient.setQueryData(['pages', projectId, drawingIds], (old: any[] | undefined) => {
        if (!old) return old
        return old.map((p) => (p.id === pageId ? { ...p, ...data } : p))
      })
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
