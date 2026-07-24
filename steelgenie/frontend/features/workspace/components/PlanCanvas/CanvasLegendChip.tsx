import React from 'react'
import { useWorkspaceStore } from '../../../../lib/stores/workspaceStore'

interface Member {
  id: string
  kind: string
  section: string | null
  confidence?: number | null
  status?: string
  sequence?: number | string | null
  weight_lbs?: number | null
  labor_code?: string | null
  paint?: string | null
}

interface CanvasLegendChipProps {
  members: Member[]
}

export function CanvasLegendChip({ members }: CanvasLegendChipProps) {
  const store = useWorkspaceStore()
  const { layers, toggleLegendKey } = store

  if (layers.colorMode === 'kind') return null

  // Helper to check if filtered
  const isHidden = (key: string) => {
    return layers.hiddenLegendKeys && layers.hiddenLegendKeys.has(key)
  }

  // Generate top sections
  const getTopSections = () => {
    const counts: Record<string, number> = {}
    members.forEach((m) => {
      if (m.section) {
        counts[m.section] = (counts[m.section] || 0) + 1
      }
    })
    return Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 8)
      .map(([section]) => section)
  }

  // Get legend configuration for the active color mode
  const legendItems = (() => {
    if (layers.colorMode === 'status') {
      return [
        { label: 'Verified', key: 'verified', color: '#10B981' },
        { label: 'Rejected', key: 'rejected', color: '#EF4444' },
        { label: 'Needs Review', key: 'need_review', color: '#F59E0B' },
      ]
    }
    if (layers.colorMode === 'weight') {
      return [
        { label: '< 100 lb', key: '< 100 lb', color: '#10B981' },
        { label: '100–300 lb', key: '100–300 lb', color: '#3B82F6' },
        { label: '300–600 lb', key: '300–600 lb', color: '#F59E0B' },
        { label: '> 600 lb', key: '> 600 lb', color: '#EF4444' },
      ]
    }
    if (layers.colorMode === 'sequence' || layers.colorMode === 'labor_code' || layers.colorMode === 'paint') {
      const field = layers.colorMode === 'sequence' ? 'sequence' : layers.colorMode === 'labor_code' ? 'labor_code' : 'paint'
      const fallback = field === 'sequence' ? 'Unsequenced' : field === 'labor_code' ? 'Unassigned' : 'Unpainted'
      const counts: Record<string, number> = {}
      members.forEach((m: any) => {
        const v = m[field] !== null && m[field] !== undefined && m[field] !== '' ? String(m[field]) : fallback
        counts[v] = (counts[v] || 0) + 1
      })
      const top = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([k]) => k)
      return top.map((v) => {
        if (v === fallback) return { label: fallback, key: v, color: '#64748B' }
        let hash = 0
        for (let i = 0; i < v.length; i++) hash = v.charCodeAt(i) + ((hash << 5) - hash)
        const colors = ['#3B82F6', '#EF4444', '#10B981', '#F59E0B', '#8B5CF6', '#EC4899', '#06B6D4', '#14B8A6']
        return { label: v, key: v, color: colors[Math.abs(hash) % colors.length] }
      })
    }
    return []
  })()

  // Remove duplicate entries if any
  const uniqueItems = legendItems.filter(
    (item, index, self) => self.findIndex((t) => t.key === item.key) === index
  )

  if (uniqueItems.length === 0) return null

  return (
    <div
      style={{
        position: 'absolute',
        bottom: '16px',
        left: '16px',
        zIndex: 20,
        backgroundColor: '#1E293B',
        border: '1px solid rgba(59, 130, 246, 0.2)',
        borderRadius: '8px',
        padding: '8px 10px',
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
        boxShadow: '0 4px 16px rgba(0,0,0,0.3)',
        color: '#F1F5F9',
        fontSize: '11px',
        fontFamily: 'Inter, system-ui, sans-serif',
        userSelect: 'none',
      }}
    >
      <span style={{ color: '#94A3B8', fontWeight: 700, textTransform: 'uppercase', fontSize: '9px', letterSpacing: '0.4px' }}>
        Filter:
      </span>
      <div style={{ display: 'flex', gap: '8px' }}>
        {uniqueItems.map((item) => {
          const hidden = isHidden(item.key)
          return (
            <button
              key={item.key}
              onClick={() => toggleLegendKey(item.key)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '5px',
                background: 'none',
                border: 'none',
                color: hidden ? '#64748B' : '#FFFFFF',
                cursor: 'pointer',
                padding: '2px 6px',
                borderRadius: '4px',
                backgroundColor: hidden ? 'transparent' : 'rgba(255,255,255,0.04)',
                borderWidth: '1px',
                borderStyle: 'solid',
                borderColor: hidden ? 'transparent' : 'rgba(255,255,255,0.08)',
                transition: 'all 0.15s ease',
                textDecoration: hidden ? 'line-through' : 'none',
              }}
            >
              <span
                style={{
                  width: '8px',
                  height: '8px',
                  borderRadius: '50%',
                  backgroundColor: item.color,
                  opacity: hidden ? 0.3 : 1,
                  display: 'inline-block',
                }}
              />
              <span>{item.label}</span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
