import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { membersApi } from '../../../lib/api'
import { useWorkspaceStore } from '../../../lib/stores/workspaceStore'

export function useMembers(pageId: string | null) {
  const queryClient = useQueryClient()

  // Query: Get all members for page
  const { data: members = [], isLoading, error } = useQuery({
    queryKey: ['members', pageId],
    queryFn: () => (pageId ? membersApi.list(pageId) : Promise.resolve([])),
    enabled: !!pageId,
  })

  // Every mutation below also calls bumpModelRefresh(pageId) -- previously
  // only page EXTRACTION did this, so editing/creating/deleting a member on
  // an already-extracted page (drag an endpoint, change a profile, delete a
  // duplicate) silently never touched the 3D view: the 2D plan and the
  // members table updated, but the 3D scene had no idea anything changed
  // until a full page reload. Passing pageId (not just bumping the counter)
  // matters too -- see workspaceStore's lastEditedPageId doc comment: the 3D
  // viewer's incremental sync otherwise skips pages it already loaded.

  // Mutation: Create member
  const createMutation = useMutation({
    mutationFn: (data: any) => {
      if (!pageId) throw new Error('No active page')
      return membersApi.create(pageId, data)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['members', pageId] })
      if (pageId) useWorkspaceStore.getState().bumpModelRefresh(pageId)
    },
  })

  // Mutation: Update member
  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: any }) => membersApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['members', pageId] })
      if (pageId) useWorkspaceStore.getState().bumpModelRefresh(pageId)
    },
  })

  // Mutation: Delete member
  const deleteMutation = useMutation({
    mutationFn: membersApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['members', pageId] })
      if (pageId) useWorkspaceStore.getState().bumpModelRefresh(pageId)
    },
  })

  // Mutation: Bulk update members
  const bulkUpdateMutation = useMutation({
    mutationFn: ({ ids, update }: { ids: string[]; update: any }) =>
      membersApi.bulkUpdate(ids, update),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['members', pageId] })
      if (pageId) useWorkspaceStore.getState().bumpModelRefresh(pageId)
    },
  })

  // Mutation: Bulk delete members
  const bulkDeleteMutation = useMutation({
    mutationFn: (ids: string[]) => membersApi.bulkDelete(ids),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['members', pageId] })
      if (pageId) useWorkspaceStore.getState().bumpModelRefresh(pageId)
    },
  })

  // Mutation: Analyse page
  const analyseMutation = useMutation({
    mutationFn: (options: any) => {
      if (!pageId) throw new Error('No active page')
      return membersApi.analyse(pageId, options)
    },
  })

  // Mutation: Validate page columns
  const validateColumnsMutation = useMutation({
    mutationFn: () => {
      if (!pageId) throw new Error('No active page')
      return membersApi.validateColumns(pageId)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['members', pageId] })
    },
  })

  return {
    members,
    isLoading,
    error,
    createMember: createMutation.mutateAsync,
    updateMember: updateMutation.mutateAsync,
    deleteMember: deleteMutation.mutateAsync,
    bulkUpdateMembers: bulkUpdateMutation.mutateAsync,
    bulkDeleteMembers: bulkDeleteMutation.mutateAsync,
    analysePage: analyseMutation.mutateAsync,
    validateColumns: validateColumnsMutation.mutateAsync,
    isAnalysing: analyseMutation.isPending,
  }
}
