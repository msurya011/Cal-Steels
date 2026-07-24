import React from 'react'
import { Pin, Star, Trash2, Copy, ArrowRight, FileImage } from 'lucide-react'
import { relativeTime } from '../utils/relativeTime'

interface Project {
  id: string
  name: string
  number: string | null
  status: string
  design_standard: string
  unit_system: string
  location: string | null
  description: string | null
  pinned: boolean
  created_at: string
  updated_at?: string
  thumbnail_url?: string | null
  is_example?: boolean
}

interface ProjectRowProps {
  project: Project
  onOpen: (p: Project) => void
  onPin: (id: string) => Promise<void>
  onClone: (id: string) => Promise<void>
  onDelete: (id: string) => Promise<void>
}

// Table-view counterpart to ProjectCard -- same data, dense single-line
// layout. SteelGenie's dashboard supports both a grid and a table view;
// this is the row rendered when the user picks the table toggle.
export function ProjectRow({ project, onOpen, onPin, onClone, onDelete }: ProjectRowProps) {
  const getStatusColor = (status: string) => {
    if (status === 'completed') return '#10B981'
    if (status === 'in_progress') return '#F59E0B'
    if (status === 'on_hold') return '#EF4444'
    return '#64748B'
  }

  const formatDate = (iso: string) =>
    new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '48px 1fr 120px 130px 140px 110px 90px',
        gap: '12px',
        alignItems: 'center',
        padding: '10px 16px',
        borderTop: '1px solid rgba(59,130,246,0.06)',
        cursor: 'pointer',
        transition: 'background-color 0.15s ease',
      }}
      onClick={() => onOpen(project)}
      onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'rgba(59,130,246,0.04)')}
      onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
    >
      <div
        style={{
          width: '36px', height: '36px', borderRadius: '6px', overflow: 'hidden',
          backgroundColor: '#0B1220', display: 'flex', alignItems: 'center', justifyContent: 'center',
          flexShrink: 0,
        }}
      >
        {project.thumbnail_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={project.thumbnail_url} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
        ) : (
          <FileImage size={14} color="#334155" />
        )}
      </div>

      <div style={{ minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span style={{ fontSize: '13px', fontWeight: 600, color: '#F1F5F9', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {project.name}
          </span>
          {project.pinned && <Star size={11} fill="#F59E0B" color="#F59E0B" />}
          {project.is_example && (
            <span style={{ fontSize: '9px', fontWeight: 700, color: '#8B5CF6', padding: '1px 6px', backgroundColor: 'rgba(139,92,246,0.12)', borderRadius: '4px', textTransform: 'uppercase' }}>
              Example
            </span>
          )}
        </div>
        {project.number && <span style={{ fontSize: '11px', color: '#3B82F6' }}>#{project.number}</span>}
      </div>

      <span
        style={{
          padding: '2px 8px', borderRadius: '5px', fontSize: '10px', fontWeight: 600,
          textTransform: 'uppercase', letterSpacing: '0.4px', width: 'fit-content',
          backgroundColor: `${getStatusColor(project.status)}15`,
          border: `1px solid ${getStatusColor(project.status)}30`,
          color: getStatusColor(project.status),
        }}
      >
        {project.status.replace('_', ' ')}
      </span>

      <span style={{ fontSize: '12px', color: '#94A3B8' }}>{project.design_standard}</span>
      <span style={{ fontSize: '12px', color: '#94A3B8' }} title={formatDate(project.created_at)}>
        {relativeTime(project.updated_at || project.created_at)}
      </span>
      <span style={{ fontSize: '12px', color: '#64748B' }}>{formatDate(project.created_at)}</span>

      <div style={{ display: 'flex', gap: '4px', justifyContent: 'flex-end' }} onClick={(e) => e.stopPropagation()}>
        <button
          onClick={() => onPin(project.id)}
          title={project.pinned ? 'Unpin' : 'Pin'}
          style={{ background: 'none', border: 'none', color: project.pinned ? '#F59E0B' : '#64748B', cursor: 'pointer', padding: '4px' }}
        >
          <Pin size={13} />
        </button>
        <button
          onClick={() => onClone(project.id)}
          title="Clone"
          style={{ background: 'none', border: 'none', color: '#64748B', cursor: 'pointer', padding: '4px' }}
        >
          <Copy size={13} />
        </button>
        <button
          onClick={() => {
            if (confirm(`Delete project "${project.name}"?`)) onDelete(project.id)
          }}
          title="Delete"
          style={{ background: 'none', border: 'none', color: '#EF4444', cursor: 'pointer', padding: '4px' }}
        >
          <Trash2 size={13} />
        </button>
        <button
          onClick={() => onOpen(project)}
          title="Open"
          style={{ background: 'none', border: 'none', color: '#60A5FA', cursor: 'pointer', padding: '4px' }}
        >
          <ArrowRight size={13} />
        </button>
      </div>
    </div>
  )
}
