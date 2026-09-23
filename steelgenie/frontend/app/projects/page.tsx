'use client'

import React, { useEffect, useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '../../features/auth/hooks/useAuth'
import { useProjects } from '../../features/projects/hooks/useProjects'
import { ProjectCard } from '../../features/projects/components/ProjectCard'
import { ProjectRow } from '../../features/projects/components/ProjectRow'
import { CreateProjectModal } from '../../features/projects/components/CreateProjectModal'
import { Spinner } from '../../components/ui/Spinner'
import { Plus, Search, LogOut, LayoutGrid, List, FolderPlus, Folder, X } from 'lucide-react'
import { toast } from 'sonner'

type DashboardTab = 'mine' | 'company' | 'examples'
type ViewMode = 'grid' | 'table'

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
    folders,
    createFolder,
    deleteFolder,
  } = useProjects()

  const [search, setSearch] = useState('')
  const [showModal, setShowModal] = useState(false)
  const [tab, setTab] = useState<DashboardTab>('mine')
  const [viewMode, setViewMode] = useState<ViewMode>('grid')
  const [activeFolderId, setActiveFolderId] = useState<string | null>(null)

  // Persist view mode + last tab across visits, like a real product would.
  useEffect(() => {
    const savedView = typeof window !== 'undefined' ? localStorage.getItem('dashboard_view_mode') : null
    if (savedView === 'grid' || savedView === 'table') setViewMode(savedView)
  }, [])
  useEffect(() => {
    if (typeof window !== 'undefined') localStorage.setItem('dashboard_view_mode', viewMode)
  }, [viewMode])

  // Tab split: My Projects (owned, non-example) / Company Projects (shared
  // to the company, not mine) / Examples (is_example flag). Mirrors
  // SteelGenie's My Projects / Company Projects / Examples tabs.
  const tabbedProjects = useMemo(() => {
    return projects.filter((p: any) => {
      if (p.is_example) return tab === 'examples'
      if (tab === 'examples') return false
      const isMine = !user?.id || p.owner_id === user.id || p.owner_id === '64b9a35a-79f4-4a51-a47a-9c7bce45872c' || !p.owner_id || p.share_scope !== 'company'
      if (tab === 'mine') return isMine
      // company: shared scope and not the current user's own project
      return p.share_scope === 'company' && !isMine
    })
  }, [projects, tab, user])

  const folderFiltered = useMemo(() => {
    if (!activeFolderId) return tabbedProjects
    return tabbedProjects.filter((p: any) => p.folder_id === activeFolderId)
  }, [tabbedProjects, activeFolderId])

  // Filter projects by search — memoized so it only re-runs when search text
  // or the folder-filtered list actually changes, not on every render.
  const filteredProjects = useMemo(
    () =>
      folderFiltered.filter(
        (p: any) =>
          p.name.toLowerCase().includes(search.toLowerCase()) ||
          (p.number && p.number.toLowerCase().includes(search.toLowerCase()))
      ),
    [folderFiltered, search]
  )

  const handleNewFolder = async () => {
    const name = window.prompt('Folder name')
    if (!name || !name.trim()) return
    try {
      await createFolder(name.trim())
      toast.success('Folder created')
    } catch (err: any) {
      toast.error(err.message || 'Failed to create folder')
    }
  }

  const handleDeleteFolder = async (id: string) => {
    if (!confirm('Delete this folder? Projects inside it will move back to Unfiled.')) return
    try {
      await deleteFolder(id)
      if (activeFolderId === id) setActiveFolderId(null)
      toast.success('Folder deleted')
    } catch (err: any) {
      toast.error(err.message || 'Failed to delete folder')
    }
  }

  const handleOpenProject = (project: any) => {
    router.push(`/projects/${project.id}`)
  }

  const handleCreate = async (data: any) => {
    try {
      const project = await createProject(data)
      toast.success('Project created successfully')
      return project
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

        {/* My Projects / Company Projects / Examples */}
        <div style={{ display: 'flex', gap: '4px', marginBottom: '20px', backgroundColor: 'rgba(30,41,59,0.4)', padding: '4px', borderRadius: '10px', width: 'fit-content' }}>
          {([
            ['mine', 'My Projects', projects.filter((p: any) => !p.is_example && (!user?.id || p.owner_id === user.id)).length],
            ['company', 'Company Projects', projects.filter((p: any) => p.share_scope === 'company' && p.owner_id !== user?.id).length],
            ['examples', 'Examples', projects.filter((p: any) => p.is_example).length],
          ] as [DashboardTab, string, number][]).map(([id, label, count]) => (
            <button
              key={id}
              onClick={() => { setTab(id); setActiveFolderId(null) }}
              style={{
                display: 'flex', alignItems: 'center', gap: '6px', padding: '8px 16px',
                backgroundColor: tab === id ? '#3B82F6' : 'transparent',
                border: 'none', borderRadius: '7px', cursor: 'pointer',
                color: tab === id ? '#FFFFFF' : '#94A3B8', fontSize: '13px', fontWeight: 600,
                transition: 'all 0.15s ease',
              }}
            >
              {label}
              <span style={{
                fontSize: '10px', padding: '1px 6px', borderRadius: '999px',
                backgroundColor: tab === id ? 'rgba(255,255,255,0.2)' : 'rgba(255,255,255,0.06)',
                color: tab === id ? '#FFFFFF' : '#64748B',
              }}>
                {count}
              </span>
            </button>
          ))}
        </div>

        {/* Folder rail */}
        <div style={{ display: 'flex', gap: '8px', marginBottom: '24px', flexWrap: 'wrap', alignItems: 'center' }}>
          <button
            onClick={() => setActiveFolderId(null)}
            style={{
              display: 'flex', alignItems: 'center', gap: '6px', padding: '6px 12px',
              backgroundColor: activeFolderId === null ? 'rgba(59,130,246,0.15)' : 'transparent',
              border: `1px solid ${activeFolderId === null ? 'rgba(59,130,246,0.35)' : 'rgba(59,130,246,0.1)'}`,
              borderRadius: '999px', color: activeFolderId === null ? '#60A5FA' : '#64748B',
              fontSize: '12px', fontWeight: 600, cursor: 'pointer',
            }}
          >
            All
          </button>
          {folders.map((f: any) => (
            <div
              key={f.id}
              style={{
                display: 'flex', alignItems: 'center', gap: '4px', padding: '6px 10px 6px 12px',
                backgroundColor: activeFolderId === f.id ? 'rgba(59,130,246,0.15)' : 'transparent',
                border: `1px solid ${activeFolderId === f.id ? 'rgba(59,130,246,0.35)' : 'rgba(59,130,246,0.1)'}`,
                borderRadius: '999px', color: activeFolderId === f.id ? '#60A5FA' : '#64748B',
                fontSize: '12px', fontWeight: 600,
              }}
            >
              <button
                onClick={() => setActiveFolderId(f.id)}
                style={{ display: 'flex', alignItems: 'center', gap: '5px', background: 'none', border: 'none', color: 'inherit', fontSize: 'inherit', fontWeight: 'inherit', cursor: 'pointer', padding: 0 }}
              >
                <Folder size={12} /> {f.name}
              </button>
              <X
                size={11}
                style={{ cursor: 'pointer', opacity: 0.6 }}
                onClick={() => handleDeleteFolder(f.id)}
              />
            </div>
          ))}
          <button
            onClick={handleNewFolder}
            style={{
              display: 'flex', alignItems: 'center', gap: '6px', padding: '6px 12px',
              backgroundColor: 'transparent', border: '1px dashed rgba(59,130,246,0.25)',
              borderRadius: '999px', color: '#64748B', fontSize: '12px', fontWeight: 600, cursor: 'pointer',
            }}
          >
            <FolderPlus size={12} /> New Folder
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

          {/* Grid / Table view toggle */}
          <div style={{ display: 'flex', backgroundColor: 'rgba(30,41,59,0.4)', border: '1px solid rgba(59,130,246,0.08)', borderRadius: '8px', padding: '3px' }}>
            <button
              onClick={() => setViewMode('grid')}
              title="Grid view"
              style={{
                display: 'flex', alignItems: 'center', padding: '6px 10px', borderRadius: '6px', border: 'none',
                backgroundColor: viewMode === 'grid' ? '#3B82F6' : 'transparent',
                color: viewMode === 'grid' ? '#FFFFFF' : '#64748B', cursor: 'pointer',
              }}
            >
              <LayoutGrid size={15} />
            </button>
            <button
              onClick={() => setViewMode('table')}
              title="Table view"
              style={{
                display: 'flex', alignItems: 'center', padding: '6px 10px', borderRadius: '6px', border: 'none',
                backgroundColor: viewMode === 'table' ? '#3B82F6' : 'transparent',
                color: viewMode === 'table' ? '#FFFFFF' : '#64748B', cursor: 'pointer',
              }}
            >
              <List size={15} />
            </button>
          </div>

          {/* Mini Stats */}
          <div style={{ display: 'flex', gap: '12px', flex: '1 1 auto', justifyContent: 'flex-end' }}>
            <div style={{ padding: '8px 16px', backgroundColor: 'rgba(30, 41, 59, 0.4)', border: '1px solid rgba(59, 130, 246, 0.08)', borderRadius: '8px', textAlign: 'center' }}>
              <span style={{ fontSize: '18px', fontWeight: 700, color: '#F1F5F9' }}>{filteredProjects.length}</span>
              <span style={{ fontSize: '11px', color: '#64748B', marginLeft: '6px' }}>Total</span>
            </div>
            <div style={{ padding: '8px 16px', backgroundColor: 'rgba(30, 41, 59, 0.4)', border: '1px solid rgba(59, 130, 246, 0.08)', borderRadius: '8px', textAlign: 'center' }}>
              <span style={{ fontSize: '18px', fontWeight: 700, color: '#F59E0B' }}>{filteredProjects.filter((p: any) => p.status === 'in_progress').length}</span>
              <span style={{ fontSize: '11px', color: '#64748B', marginLeft: '6px' }}>Active</span>
            </div>
            <div style={{ padding: '8px 16px', backgroundColor: 'rgba(30, 41, 59, 0.4)', border: '1px solid rgba(59, 130, 246, 0.08)', borderRadius: '8px', textAlign: 'center' }}>
              <span style={{ fontSize: '18px', fontWeight: 700, color: '#10B981' }}>{filteredProjects.filter((p: any) => p.status === 'completed').length}</span>
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
              {search
                ? 'No projects match your search'
                : tab === 'company'
                ? 'Nothing shared to your company yet'
                : tab === 'examples'
                ? 'No example projects yet'
                : 'No projects yet'}
            </h2>
            <p style={{ margin: '0 0 24px', fontSize: '14px', color: '#475569', maxWidth: '380px' }}>
              {search
                ? 'Try editing your search query or clear the filter to view all projects.'
                : tab === 'company'
                ? 'Projects another teammate marks as shared to the company will show up here.'
                : tab === 'examples'
                ? 'Pre-built sample projects will appear here once added.'
                : 'Create your first project to begin uploading and extracting structural plans.'}
            </p>
            {!search && tab === 'mine' && (
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
        ) : viewMode === 'grid' ? (
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
        ) : (
          <div style={{ border: '1px solid rgba(59,130,246,0.1)', borderRadius: '12px', overflow: 'hidden' }}>
            <div style={{
              display: 'grid', gridTemplateColumns: '48px 1fr 120px 130px 140px 110px 90px',
              gap: '12px', padding: '10px 16px', backgroundColor: 'rgba(30,41,59,0.5)',
              fontSize: '11px', fontWeight: 700, color: '#64748B', textTransform: 'uppercase', letterSpacing: '0.4px',
            }}>
              <span />
              <span>Name</span>
              <span>Status</span>
              <span>Standard</span>
              <span>Modified</span>
              <span>Created</span>
              <span />
            </div>
            {filteredProjects.map((project: any) => (
              <ProjectRow
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
