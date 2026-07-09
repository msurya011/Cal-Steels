import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { membersApi } from '../../../lib/api'

export function useMembers(pageId: string | null) {
  const queryClient = useQueryClient()

  // Query: Get all members for page
  const { data: members = [], isLoading, error } = useQuery({
    queryKey: ['members', pageId],
    queryFn: () => (pageId ? membersApi.list(pageId) : Promise.resolve([])),
    enabled: !!pageId,
  })

  // Mutation: Create member
  const createMutation = useMutation({
    mutationFn: (data: any) => {
      if (!pageId) throw new Error('No active page')
      return membersApi.create(pageId, data)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['members', pageId] })
    },
  })

  // Mutation: Update member
  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: any }) => membersApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['members', pageId] })
    },
  })

  // Mutation: Delete member
  const deleteMutation = useMutation({
    mutationFn: membersApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['members', pageId] })
    },
  })

  // Mutation: Bulk update members
  const bulkUpdateMutation = useMutation({
    mutationFn: ({ ids, update }: { ids: string[]; update: any }) =>
      membersApi.bulkUpdate(ids, update),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['members', pageId] })
    },
  })

  // Mutation: Bulk delete members
  const bulkDeleteMutation = useMutation({
    mutationFn: (ids: string[]) => membersApi.bulkDelete(ids),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['members', pageId] })
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
