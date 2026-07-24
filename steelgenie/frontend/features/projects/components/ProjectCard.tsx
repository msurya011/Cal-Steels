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

interface ProjectCardProps {
  project: Project
  onOpen: (p: Project) => void
  onPin: (id: string) => Promise<void>
  onClone: (id: string) => Promise<void>
  onDelete: (id: string) => Promise<void>
}

export function ProjectCard({ project, onOpen, onPin, onClone, onDelete }: ProjectCardProps) {
  const getStatusColor = (status: string) => {
    if (status === 'completed') return '#10B981'
    if (status === 'in_progress') return '#F59E0B'
    if (status === 'on_hold') return '#EF4444'
    return '#64748B'
  }

  const formatDate = (iso: string) => {
    return new Date(iso).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    })
  }

  return (
    <div
      style={{
        backgroundColor: '#111827',
        border: '1px solid rgba(59, 130, 246, 0.12)',
        borderRadius: '12px',
        padding: '24px',
        display: 'flex',
        flexDirection: 'column',
        gap: '16px',
        transition: 'all 0.2s ease',
        boxShadow: '0 4px 20px rgba(0, 0, 0, 0.2)',
        position: 'relative',
        overflow: 'hidden',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = 'rgba(59, 130, 246, 0.35)'
        e.currentTarget.style.boxShadow = '0 8px 30px rgba(0,0,0,0.3)'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = 'rgba(59, 130, 246, 0.12)'
        e.currentTarget.style.boxShadow = '0 4px 20px rgba(0, 0, 0, 0.2)'
      }}
    >
      {/* Thumbnail preview -- first extracted page of the project's first
          drawing, so a card actually shows what the project looks like
          instead of a generic icon, matching SteelGenie's project cards. */}
      <div
        style={{
          margin: '-24px -24px 0',
          height: '120px',
          backgroundColor: '#0B1220',
          borderBottom: '1px solid rgba(59,130,246,0.1)',
          borderRadius: '12px 12px 0 0',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          overflow: 'hidden',
          position: 'relative',
        }}
      >
        {project.thumbnail_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={project.thumbnail_url}
            alt=""
            style={{ width: '100%', height: '100%', objectFit: 'cover', opacity: 0.9 }}
          />
        ) : (
          <FileImage size={22} color="#334155" />
        )}
        {project.is_example && (
          <span
            style={{
              position: 'absolute', top: '8px', left: '8px', padding: '2px 8px',
              backgroundColor: 'rgba(139, 92, 246, 0.85)', borderRadius: '5px',
              fontSize: '9px', fontWeight: 700, color: '#FFFFFF', letterSpacing: '0.4px',
              textTransform: 'uppercase',
            }}
          >
            Example
          </span>
        )}
      </div>

      {/* Top row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <span
          style={{
            padding: '3px 8px',
            borderRadius: '5px',
            fontSize: '10px',
            fontWeight: 600,
            textTransform: 'uppercase',
            letterSpacing: '0.5px',
            backgroundColor: `${getStatusColor(project.status)}15`,
            border: `1px solid ${getStatusColor(project.status)}30`,
            color: getStatusColor(project.status),
          }}
        >
          {project.status.replace('_', ' ')}
        </span>

        <div style={{ display: 'flex', gap: '8px' }}>
          <button
            onClick={() => onPin(project.id)}
            title={project.pinned ? 'Unpin project' : 'Pin project'}
            style={{
              background: 'none',
              border: 'none',
              color: project.pinned ? '#F59E0B' : '#64748B',
              cursor: 'pointer',
              padding: '4px',
              borderRadius: '4px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Star size={16} fill={project.pinned ? '#F59E0B' : 'none'} />
          </button>
          <button
            onClick={() => onClone(project.id)}
            title="Clone project"
            style={{
              background: 'none',
              border: 'none',
              color: '#64748B',
              cursor: 'pointer',
              padding: '4px',
              borderRadius: '4px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Copy size={16} />
          </button>
          <button
            onClick={() => {
              if (confirm(`Delete project "${project.name}"?`)) {
                onDelete(project.id)
              }
            }}
            title="Delete project"
            style={{
              background: 'none',
              border: 'none',
              color: '#EF4444',
              cursor: 'pointer',
              padding: '4px',
              borderRadius: '4px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Trash2 size={16} />
          </button>
        </div>
      </div>

      {/* Title */}
      <div>
        <h3
          style={{
            margin: 0,
            fontSize: '18px',
            fontWeight: 700,
            color: '#F1F5F9',
            lineHeight: 1.3,
            cursor: 'pointer',
          }}
          onClick={() => onOpen(project)}
        >
          {project.name}
        </h3>
        {project.number && (
          <span style={{ fontSize: '12px', color: '#3B82F6', fontWeight: 500, marginTop: '4px', display: 'inline-block' }}>
            #{project.number}
          </span>
        )}
      </div>

      {/* Description */}
      {project.description && (
        <p
          style={{
            margin: 0,
            fontSize: '13px',
            color: '#94A3B8',
            lineHeight: 1.4,
            height: '38px',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            display: '-webkit-box',
            WebkitLineClamp: 2,
            WebkitBoxOrient: 'vertical',
          }}
        >
          {project.description}
        </p>
      )}

      {/* Metadata tags */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginTop: 'auto' }}>
        <span style={{ padding: '3px 8px', backgroundColor: '#1F2937', borderRadius: '5px', fontSize: '11px', color: '#94A3B8' }}>
          {project.design_standard}
        </span>
        <span style={{ padding: '3px 8px', backgroundColor: '#1F2937', borderRadius: '5px', fontSize: '11px', color: '#94A3B8' }}>
          {project.unit_system}
        </span>
        {project.location && (
          <span style={{ padding: '3px 8px', backgroundColor: '#1F2937', borderRadius: '5px', fontSize: '11px', color: '#94A3B8' }}>
            {project.location}
          </span>
        )}
      </div>

      {/* Card footer */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          borderTop: '1px solid rgba(59, 130, 246, 0.08)',
          paddingTop: '12px',
          marginTop: '4px',
        }}
      >
        <span style={{ fontSize: '11px', color: '#475569' }} title={`Created ${formatDate(project.created_at)}`}>
          Modified {relativeTime(project.updated_at || project.created_at)}
        </span>
        <button
          onClick={() => onOpen(project)}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            padding: '6px 12px',
            backgroundColor: 'rgba(59, 130, 246, 0.1)',
            border: '1px solid rgba(59, 130, 246, 0.25)',
            borderRadius: '6px',
            color: '#60A5FA',
            fontSize: '12px',
            fontWeight: 600,
            cursor: 'pointer',
            transition: 'all 0.2s ease',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.backgroundColor = '#3B82F6'
            e.currentTarget.style.color = '#FFFFFF'
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.backgroundColor = 'rgba(59, 130, 246, 0.1)'
            e.currentTarget.style.color = '#60A5FA'
          }}
        >
          Open <ArrowRight size={12} />
        </button>
      </div>
    </div>
  )
}
