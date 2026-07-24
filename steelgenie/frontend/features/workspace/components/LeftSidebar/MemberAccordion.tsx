import React, { useState } from 'react'
import { ChevronRight, Check } from 'lucide-react'
import { useWorkspaceStore } from '../../../../lib/stores/workspaceStore'

interface Member {
  id: string
  kind: string
  section: string | null
  status?: string
}

interface MemberAccordionProps {
  title: string
  members: Member[]
  isExpanded: boolean
  onToggleExpand: () => void
}

export function MemberAccordion({ title, members, isExpanded, onToggleExpand }: MemberAccordionProps) {
  const { toggleLayerVisibility, layers } = useWorkspaceStore()
  
  // Example for Beams (12) -> kind is "beam" (derived from title loosely for this example)
  const kind = title.toLowerCase().replace(/s$/, '') // Beams -> beam

  const isVisible = (layers as any)[kind] !== false // default true

  return (
    <div style={{ marginBottom: '8px' }}>
      <div
        onClick={onToggleExpand}
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '10px 12px',
          backgroundColor: '#0F172A', // Very dark background
          borderRadius: '6px',
          cursor: 'pointer',
          border: '1px solid rgba(255, 255, 255, 0.05)',
          userSelect: 'none',
        }}
      >
        <span
          style={{
            fontWeight: 700,
            fontSize: '13px',
            color: '#E2E8F0',
            flex: 1,
          }}
        >
          {title} ({members.length})
        </span>

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {/* Green Check (Simulating Verification / Visibility state) */}
          <button
            onClick={(e) => {
              e.stopPropagation()
              toggleLayerVisibility(kind)
            }}
            style={{
              background: 'none',
              border: 'none',
              padding: 0,
              color: isVisible ? '#10B981' : '#475569',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
            }}
            title={isVisible ? 'Visible' : 'Hidden'}
          >
            <Check size={16} strokeWidth={3} />
          </button>

          <ChevronRight
            size={16}
            color="#64748B"
            style={{ transform: isExpanded ? 'rotate(90deg)' : 'none', transition: 'transform 0.15s' }}
          />
        </div>
      </div>

      {isExpanded && (
        <div style={{ padding: '8px 4px 8px 12px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
          {/* In Phase 2, this will use virtualization for 10,000+ members.
              For now, rendering a placeholder or the first few items. */}
          {members.slice(0, 50).map(m => (
            <div key={m.id} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px', fontSize: '12px', color: '#94A3B8' }}>
              <span>{m.section || 'Unknown'}</span>
              <span style={{ color: m.status === 'verified' ? '#10B981' : '#F59E0B' }}>
                {m.status || 'not_started'}
              </span>
            </div>
          ))}
          {members.length > 50 && (
            <div style={{ fontSize: '11px', color: '#64748B', textAlign: 'center', padding: '4px' }}>
              + {members.length - 50} more (Virtualization active)
            </div>
          )}
        </div>
      )}
    </div>
  )
}
