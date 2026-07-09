'use client'

import React, { useEffect, useState } from 'react'
import { useRouter, usePathname, useParams } from 'next/navigation'
import { useAuth } from '../../../features/auth/hooks/useAuth'
import { projectsApi } from '../../../lib/api'
import { Spinner } from '../../../components/ui/Spinner'
import { ArrowLeft, Play, BarChart3, Box, Settings, CheckSquare } from 'lucide-react'
import { toast } from 'sonner'

export default function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const params = useParams()
  const pathname = usePathname()
  const projectId = params?.id as string

  const { user, loading: authLoading } = useAuth()
  const [project, setProject] = useState<any>(null)
  const [loading, setLoading] = useState(true)

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
    if (pathname?.endsWith('/3d')) return '3d'
    if (pathname?.endsWith('/config')) return 'config'
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
          <button
            onClick={() => router.push('/projects')}
            style={{
              background: 'none',
              border: 'none',
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
            <ArrowLeft size={16} />
          </button>
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            <span style={{ fontSize: '14px', fontWeight: 700, color: '#F1F5F9' }}>
              {project?.name}
            </span>
            {project?.number && (
              <span style={{ fontSize: '11px', color: '#3B82F6', fontWeight: 500 }}>
                #{project.number}
              </span>
            )}
          </div>
        </div>

        {/* Middle: Tab Selector — SteelGenie-style white active pill */}
        <div style={{ display: 'flex', gap: '4px', backgroundColor: 'rgba(255,255,255,0.06)', padding: '4px', borderRadius: '22px' }}>
          {[
            { id: 'takeoff', label: 'Takeoff', icon: <Play size={14} /> },
            { id: 'bom', label: 'BOM Grid', icon: <BarChart3 size={14} /> },
            { id: '3d', label: '3D Model', icon: <Box size={14} /> },
            { id: 'config', label: 'Config', icon: <Settings size={14} /> },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => handleTabChange(tab.id)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                padding: '6px 16px',
                border: 'none',
                borderRadius: '18px',
                fontSize: '13px',
                fontWeight: 700,
                cursor: 'pointer',
                fontFamily: 'inherit',
                transition: 'all 0.2s ease',
                backgroundColor: activeTab === tab.id ? '#FFFFFF' : 'transparent',
                color: activeTab === tab.id ? '#0A192E' : '#CBD5E1',
              }}
            >
              {tab.icon}
              {tab.label}
            </button>
          ))}
        </div>

        {/* Right: User Email info */}
        <div style={{ fontSize: '13px', color: '#64748B', fontWeight: 500 }}>
          {user?.email}
        </div>
      </header>

      {/* Main Page Area */}
      <div style={{ flex: 1, overflow: 'hidden', position: 'relative' }}>
        {children}
      </div>
    </div>
  )
}
