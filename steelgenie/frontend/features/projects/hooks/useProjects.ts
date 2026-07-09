import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { projectsApi } from '../../../lib/api'

export function useProjects() {
  const queryClient = useQueryClient()

  // Query: Get all projects
  const { data: projects = [], isLoading, error } = useQuery({
    queryKey: ['projects'],
    queryFn: projectsApi.list,
  })

  // Mutation: Create project
  const createMutation = useMutation({
    mutationFn: projectsApi.create,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
    },
  })

  // Mutation: Update project
  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: any }) => projectsApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
    },
  })

  // Mutation: Delete project
  const deleteMutation = useMutation({
    mutationFn: projectsApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
    },
  })

  // Mutation: Pin/Unpin project
  const pinMutation = useMutation({
    mutationFn: projectsApi.pin,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
    },
  })

  // Mutation: Clone project
  const cloneMutation = useMutation({
    mutationFn: projectsApi.clone,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
    },
  })

  return {
    projects,
    isLoading,
    error,
    createProject: createMutation.mutateAsync,
    isCreating: createMutation.isPending,
    updateProject: updateMutation.mutateAsync,
    deleteProject: deleteMutation.mutateAsync,
    pinProject: pinMutation.mutateAsync,
    cloneProject: cloneMutation.mutateAsync,
  }
}
