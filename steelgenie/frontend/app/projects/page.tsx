'use client'

import React, { useState } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '../../features/auth/hooks/useAuth'
import { useProjects } from '../../features/projects/hooks/useProjects'
import { ProjectCard } from '../../features/projects/components/ProjectCard'
import { CreateProjectModal } from '../../features/projects/components/CreateProjectModal'
import { Spinner } from '../../components/ui/Spinner'
import { Plus, Search, LogOut } from 'lucide-react'
import { toast } from 'sonner'

export default function ProjectsPage() {
  const router = useRouter()
  const { user, signOut, loading: authLoading } = useAuth()
  const {
    projects,
    isLoading: projectsLoading,
    createProject,
    pinProject,
    cloneProject,
    deleteProject,
  } = useProjects()

  const [search, setSearch] = useState('')
  const [showModal, setShowModal] = useState(false)

  // Filter projects by search
  const filteredProjects = projects.filter((p: any) =>
    p.name.toLowerCase().includes(search.toLowerCase()) ||
    (p.number && p.number.toLowerCase().includes(search.toLowerCase()))
  )

  const handleOpenProject = (project: any) => {
    router.push(`/projects/${project.id}`)
  }

  const handleCreate = async (data: any) => {
    try {
      await createProject(data)
      toast.success('Project created successfully')
    } catch (err: any) {
      toast.error(err.message || 'Failed to create project')
      throw err
    }
  }

  const handlePin = async (id: string) => {
    try {
      await pinProject(id)
      toast.success('Project pin toggled')
    } catch (err: any) {
      toast.error('Failed to pin project')
    }
  }

  const handleClone = async (id: string) => {
    try {
      await cloneProject(id)
      toast.success('Project cloned successfully')
    } catch (err: any) {
      toast.error('Failed to clone project')
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await deleteProject(id)
      toast.success('Project deleted')
    } catch (err: any) {
      toast.error('Failed to delete project')
    }
  }

  if (authLoading || projectsLoading) {
    return (
      <div style={{ display: 'flex', minHeight: '100vh', alignItems: 'center', justifyContent: 'center', backgroundColor: '#090D1A' }}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px' }}>
          <Spinner size="lg" />
          <span style={{ fontSize: '14px', color: '#94A3B8' }}>Loading workspace...</span>
        </div>
      </div>
    )
  }

  return (
    <div style={{ minHeight: '100vh', backgroundColor: '#090D1A', position: 'relative' }}>
      {/* Grid Pattern Background */}
      <div
        style={{
          position: 'fixed',
          inset: 0,
          pointerEvents: 'none',
          zIndex: 0,
          backgroundImage:
            'linear-gradient(rgba(59, 130, 246, 0.02) 1px, transparent 1px), linear-gradient(90deg, rgba(59, 130, 246, 0.02) 1px, transparent 1px)',
          backgroundSize: '40px 40px',
        }}
      />

      {/* Header */}
      <header
        style={{
          position: 'sticky',
          top: 0,
          zIndex: 50,
          backgroundColor: 'rgba(9, 13, 26, 0.85)',
          backdropFilter: 'blur(12px)',
          borderBottom: '1px solid rgba(59, 130, 246, 0.1)',
          padding: '0 32px',
          height: '64px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div
            style={{
              width: '34px',
              height: '34px',
              backgroundColor: 'rgba(59, 130, 246, 0.1)',
              border: '1px solid rgba(59, 130, 246, 0.3)',
              borderRadius: '8px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
              <path d="M4 4h16v4H4zM4 10h10v4H4zM4 16h7v4H4z" fill="#3B82F6" />
            </svg>
          </div>
          <span style={{ fontSize: '18px', fontWeight: 800, color: '#F1F5F9', letterSpacing: '-0.3px' }}>
            CalSteel
          </span>
          <span
            style={{
              marginLeft: '8px',
              padding: '2px 8px',
              backgroundColor: 'rgba(59, 130, 246, 0.08)',
              border: '1px solid rgba(59, 130, 246, 0.2)',
              borderRadius: '4px',
              fontSize: '10px',
              fontWeight: 700,
              color: '#60A5FA',
              letterSpacing: '0.8px',
            }}
          >
            ESTIMATOR
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>
          <span style={{ fontSize: '13px', color: '#64748B', fontWeight: 500 }}>
            {user?.email}
          </span>
          <button
            onClick={signOut}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '6px 14px',
              backgroundColor: 'transparent',
              border: '1px solid rgba(239, 68, 68, 0.25)',
              borderRadius: '6px',
              color: '#EF4444',
              fontSize: '12px',
              fontWeight: 600,
              cursor: 'pointer',
              transition: 'all 0.2s ease',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'rgba(239, 68, 68, 0.08)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'transparent'
            }}
          >
            <LogOut size={14} /> Sign Out
          </button>
        </div>
      </header>

      {/* Main Container */}
      <main style={{ position: 'relative', zIndex: 10, maxWidth: '1200px', margin: '0 auto', padding: '40px 32px' }}>
        {/* Page Title & Add Button */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '32px' }}>
          <div>
            <h1 style={{ margin: '0 0 6px', fontSize: '28px', fontWeight: 800, color: '#F1F5F9', letterSpacing: '-0.5px' }}>
              Projects
            </h1>
            <p style={{ margin: 0, fontSize: '14px', color: '#64748B' }}>
              Create and manage structural drawing takeoff estimates
            </p>
          </div>

          <button
            onClick={() => setShowModal(true)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              padding: '10px 20px',
              backgroundColor: '#3B82F6',
              border: 'none',
              borderRadius: '8px',
              color: '#FFFFFF',
              fontSize: '14px',
              fontWeight: 600,
              cursor: 'pointer',
              boxShadow: '0 4px 14px rgba(59, 130, 246, 0.35)',
              transition: 'all 0.2s ease',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = '#2563EB'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = '#3B82F6'
            }}
          >
            <Plus size={16} /> New Project
          </button>
        </div>

        {/* Search & Stats Bar */}
        <div style={{ display: 'flex', gap: '20px', marginBottom: '32px', flexWrap: 'wrap-reverse', alignItems: 'center' }}>
          {/* Search Input */}
          <div style={{ position: 'relative', flex: '1 1 300px' }}>
            <Search size={18} style={{ position: 'absolute', left: '14px', top: '50%', transform: 'translateY(-50%)', color: '#64748B' }} />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search projects by name or number..."
              style={{
                width: '100%',
                boxSizing: 'border-box',
                padding: '12px 16px 12px 42px',
                backgroundColor: 'rgba(30, 41, 59, 0.4)',
                border: '1px solid rgba(59, 130, 246, 0.12)',
                borderRadius: '8px',
                color: '#F1F5F9',
                fontSize: '14px',
                outline: 'none',
                transition: 'all 0.2s ease',
              }}
              onFocus={(e) => (e.target.style.borderColor = 'rgba(59, 130, 246, 0.35)')}
              onBlur={(e) => (e.target.style.borderColor = 'rgba(59, 130, 246, 0.12)')}
            />
          </div>

          {/* Mini Stats */}
          <div style={{ display: 'flex', gap: '12px', flex: '1 1 auto', justifyContent: 'flex-end' }}>
            <div style={{ padding: '8px 16px', backgroundColor: 'rgba(30, 41, 59, 0.4)', border: '1px solid rgba(59, 130, 246, 0.08)', borderRadius: '8px', textAlign: 'center' }}>
              <span style={{ fontSize: '18px', fontWeight: 700, color: '#F1F5F9' }}>{projects.length}</span>
              <span style={{ fontSize: '11px', color: '#64748B', marginLeft: '6px' }}>Total</span>
            </div>
            <div style={{ padding: '8px 16px', backgroundColor: 'rgba(30, 41, 59, 0.4)', border: '1px solid rgba(59, 130, 246, 0.08)', borderRadius: '8px', textAlign: 'center' }}>
              <span style={{ fontSize: '18px', fontWeight: 700, color: '#F59E0B' }}>{projects.filter((p: any) => p.status === 'in_progress').length}</span>
              <span style={{ fontSize: '11px', color: '#64748B', marginLeft: '6px' }}>Active</span>
            </div>
            <div style={{ padding: '8px 16px', backgroundColor: 'rgba(30, 41, 59, 0.4)', border: '1px solid rgba(59, 130, 246, 0.08)', borderRadius: '8px', textAlign: 'center' }}>
              <span style={{ fontSize: '18px', fontWeight: 700, color: '#10B981' }}>{projects.filter((p: any) => p.status === 'completed').length}</span>
              <span style={{ fontSize: '11px', color: '#64748B', marginLeft: '6px' }}>Done</span>
            </div>
          </div>
        </div>

        {/* Project Grid */}
        {filteredProjects.length === 0 ? (
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              padding: '80px 20px',
              textAlign: 'center',
              border: '1px dashed rgba(59, 130, 246, 0.15)',
              borderRadius: '16px',
              backgroundColor: 'rgba(30, 41, 59, 0.15)',
            }}
          >
            <div
              style={{
                width: '60px',
                height: '60px',
                backgroundColor: 'rgba(59, 130, 246, 0.08)',
                border: '1px solid rgba(59, 130, 246, 0.2)',
                borderRadius: '14px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                marginBottom: '20px',
              }}
            >
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
                <path d="M4 4h16v4H4zM4 10h10v4H4zM4 16h7v4H4z" fill="#3B82F6" opacity="0.6" />
              </svg>
            </div>
            <h2 style={{ margin: '0 0 8px', fontSize: '18px', fontWeight: 600, color: '#94A3B8' }}>
              {search ? 'No projects match your search' : 'No projects yet'}
            </h2>
            <p style={{ margin: '0 0 24px', fontSize: '14px', color: '#475569', maxWidth: '380px' }}>
              {search
                ? 'Try editing your search query or clear the filter to view all projects.'
                : 'Create your first project to begin uploading and extracting structural plans.'}
            </p>
            {!search && (
              <button
                onClick={() => setShowModal(true)}
                style={{
                  padding: '10px 24px',
                  backgroundColor: '#3B82F6',
                  border: 'none',
                  borderRadius: '8px',
                  color: '#FFFFFF',
                  fontSize: '14px',
                  fontWeight: 600,
                  cursor: 'pointer',
                  boxShadow: '0 4px 14px rgba(59, 130, 246, 0.35)',
                }}
              >
                Create Project
              </button>
            )}
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '24px' }}>
            {filteredProjects.map((project: any) => (
              <ProjectCard
                key={project.id}
                project={project}
                onOpen={handleOpenProject}
                onPin={handlePin}
                onClone={handleClone}
                onDelete={handleDelete}
              />
            ))}
          </div>
        )}
      </main>

      {/* Create Project Modal */}
      {showModal && (
        <CreateProjectModal
          onClose={() => setShowModal(false)}
          onCreate={handleCreate}
        />
      )}
    </div>
  )
}
