'use client'

import React, { useEffect, useState } from 'react'
import { useRouter, usePathname, useParams } from 'next/navigation'
import { useAuth } from '../../../features/auth/hooks/useAuth'
import { projectsApi } from '../../../lib/api'
import { Spinner } from '../../../components/ui/Spinner'
import { ArrowLeft, Play, BarChart3, Box, Settings, CheckSquare, Layers, GitBranch, FileText, Home, UploadCloud, Bell, HelpCircle } from 'lucide-react'
import { toast } from 'sonner'
import StructuralViewer3D from '../../../components/StructuralViewer3D'
import { useWorkspaceStore } from '../../../lib/stores/workspaceStore'

export default function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const params = useParams()
  const pathname = usePathname()
  const projectId = params?.id as string

  const { user, loading: authLoading } = useAuth()
  const [project, setProject] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  // Single source of truth (Zustand store, in-memory only — resets to false
  // on every load so a fresh/empty project never opens with the 3D pane
  // already showing) shared with the Plans page — this is the ONLY 3D
  // toggle in the app now. It used to be local state here plus a second,
  // disconnected toggle inside the Plans page, which caused both to render
  // at once. Not anymore.
  const { show3d, toggleShow3d, modelRefreshSignal } = useWorkspaceStore()

  // Redirect legacy /3d subpages to the split pane on the plans page
  useEffect(() => {
    if (pathname?.endsWith('/3d')) {
      useWorkspaceStore.getState().setShow3d(true)
      router.replace(`/projects/${projectId}`)
    }
  }, [pathname, projectId, router])

  useEffect(() => {
    if (!projectId) return
    projectsApi
      .get(projectId)
      .then((data) => {
        setProject(data)
        setLoading(false)
      })
      .catch((err) => {
        toast.error('Failed to load project details')
        router.push('/projects')
      })
  }, [projectId, router])

  const getActiveTab = () => {
    if (pathname?.endsWith('/bom')) return 'bom'
    if (pathname?.endsWith('/config')) return 'config'
    if (pathname?.endsWith('/columns')) return 'columns'
    if (pathname?.endsWith('/braces')) return 'braces'
    return 'takeoff'
  }

  const handleTabChange = (tab: string) => {
    if (tab === 'takeoff') {
      router.push(`/projects/${projectId}`)
    } else {
      router.push(`/projects/${projectId}/${tab}`)
    }
  }

  if (authLoading || loading) {
    return (
      <div style={{ display: 'flex', minHeight: '100vh', alignItems: 'center', justifySelf: 'center', backgroundColor: '#0A192E', width: '100vw', justifyContent: 'center' }}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px' }}>
          <Spinner size="lg" />
          <span style={{ fontSize: '14px', color: '#94A3B8' }}>Loading workspace...</span>
        </div>
      </div>
    )
  }

  const activeTab = getActiveTab()

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', backgroundColor: '#0A192E', overflow: 'hidden' }}>
      {/* Workspace TopBar */}
      <header
        style={{
          height: '56px',
          backgroundColor: '#0C1B30',
          borderBottom: '1px solid rgba(59, 130, 246, 0.1)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 24px',
          flexShrink: 0,
        }}
      >
        {/* Left: Project title & Back */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
               <Box size={24} style={{ color: '#F1F5F9' }} />
               <div style={{ display: 'flex', flexDirection: 'column' }}>
                 <span style={{ fontSize: '13px', fontWeight: 800, color: '#F1F5F9', lineHeight: 1 }}>Calsteel</span>
                 <span style={{ fontSize: '8px', fontWeight: 700, color: '#94A3B8', letterSpacing: '0.5px', marginTop: '2px' }}>BY CALDIM</span>
               </div>
            </div>
            <button
              onClick={() => router.push('/projects')}
              style={{
                background: 'none',
                border: '1px solid rgba(255,255,255,0.1)',
                color: '#94A3B8',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                padding: '6px',
                borderRadius: '6px',
                transition: 'all 0.2s',
              }}
              onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#1F2937')}
              onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
            >
              <Home size={14} />
            </button>
          </div>

          <div style={{ width: '1px', height: '24px', backgroundColor: 'rgba(255, 255, 255, 0.1)' }} />

          <div style={{ display: 'flex', flexDirection: 'column', minWidth: '120px' }}>
            <span style={{ fontSize: '9px', fontWeight: 600, color: '#64748B', letterSpacing: '0.5px' }}>
              PROJECT
            </span>
            <span style={{ fontSize: '12px', fontWeight: 600, color: '#F1F5F9', marginTop: '2px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {project?.name || 'Loading...'}
            </span>
          </div>
        </div>

        {/* Middle: Tab Selector — Calsteel-style white active pill */}
        <div style={{ display: 'flex', gap: '2px', backgroundColor: 'rgba(255,255,255,0.04)', padding: '4px', borderRadius: '24px', border: '1px solid rgba(255,255,255,0.05)' }}>
          {[
            { id: 'takeoff', label: 'Plans' },
            { id: 'columns', label: 'Columns' },
            { id: 'braces', label: 'Braces' },
            { id: 'bom', label: 'BOM' },
            { id: 'config', label: 'Config' },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => handleTabChange(tab.id)}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                padding: '6px 18px',
                border: 'none',
                borderRadius: '20px',
                fontSize: '12px',
                fontWeight: 600,
                cursor: 'pointer',
                fontFamily: 'inherit',
                transition: 'all 0.2s ease',
                backgroundColor: activeTab === tab.id ? '#FFFFFF' : 'transparent',
                color: activeTab === tab.id ? '#0F172A' : '#94A3B8',
              }}
              onMouseEnter={(e) => {
                if (activeTab !== tab.id) e.currentTarget.style.color = '#F1F5F9'
              }}
              onMouseLeave={(e) => {
                if (activeTab !== tab.id) e.currentTarget.style.color = '#94A3B8'
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Right: Actions and User Info */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div style={{ display: 'flex', gap: '8px' }}>
            {/* PDF Button */}
            <button
              onClick={() => toast.info('Exporting PDF markup...')}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                backgroundColor: 'transparent',
                border: '1px solid rgba(255, 255, 255, 0.1)',
                borderRadius: '6px',
                padding: '6px 12px',
                fontSize: '12px',
                fontWeight: 600,
                color: '#CBD5E1',
                cursor: 'pointer',
                transition: 'all 0.2s',
              }}
              onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)')}
              onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
            >
              <FileText size={14} />
              <span>PDF</span>
            </button>

            {/* 3D Toggle Button */}
            <button
              onClick={toggleShow3d}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                backgroundColor: show3d ? 'rgba(255,255,255,0.1)' : 'transparent',
                border: '1px solid rgba(255, 255, 255, 0.1)',
                borderRadius: '6px',
                padding: '6px 12px',
                fontSize: '12px',
                fontWeight: 600,
                color: show3d ? '#FFFFFF' : '#CBD5E1',
                cursor: 'pointer',
                transition: 'all 0.2s',
              }}
              onMouseEnter={(e) => {
                if (!show3d) e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)'
              }}
              onMouseLeave={(e) => {
                if (!show3d) e.currentTarget.style.backgroundColor = 'transparent'
              }}
            >
              <Box size={14} />
              <span>3D</span>
            </button>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '16px', color: '#94A3B8', marginLeft: '8px' }}>
            <UploadCloud size={16} style={{ cursor: 'pointer' }} />
            <Bell size={16} style={{ cursor: 'pointer' }} />
            <HelpCircle size={16} style={{ cursor: 'pointer' }} />
          </div>

          <div style={{
            width: '28px', height: '28px', borderRadius: '50%',
            backgroundColor: '#3B82F6', color: '#FFFFFF',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: '11px', fontWeight: 700, cursor: 'pointer',
            marginLeft: '4px'
          }}>
            UD
          </div>
        </div>
      </header>

      {/* Main Page Area */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', position: 'relative' }}>
        {/* Left Side: Active sub-route */}
        <div style={{ flex: 1, height: '100%', overflow: 'hidden', position: 'relative' }}>
          {children}
        </div>

        {/* Right Side: Persistent 3D viewer */}
        {show3d && (
          <div
            style={{
              width: '50%',
              height: '100%',
              borderLeft: '2px solid #E2E8F0',
              backgroundColor: '#F1F5F9',
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
            }}
          >
            <StructuralViewer3D projectId={projectId} refreshSignal={modelRefreshSignal} />
          </div>
        )}
      </div>
    </div>
  )
}
