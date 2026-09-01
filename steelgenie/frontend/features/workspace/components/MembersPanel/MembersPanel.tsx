import React, { useState } from 'react'
import { FileSpreadsheet, AlertTriangle } from 'lucide-react'
import { useWorkspaceStore } from '../../../../lib/stores/workspaceStore'

interface Member {
  id: string
  kind: string
  section: string | null
  grade: string | null
  rotation: number
  length_ft: number | null
  geometry: any
  confidence?: number | null
  status?: string
  source?: string
}

interface MembersPanelProps {
  members: Member[]
  selectedMemberId: string | null
  onSelectMember: (id: string | null) => void
}

const needsReview = (m: Member) =>
  m.status === 'need_review' || m.section === null || (m.confidence !== null && m.confidence !== undefined && m.confidence < 0.7)

export function MembersPanel({ members, selectedMemberId, onSelectMember }: MembersPanelProps) {
  const { selectedRatio, imageNaturalWidth, imageAspect } = useWorkspaceStore()
  const [reviewOnly, setReviewOnly] = useState(false)

  const reviewCount = members.filter(needsReview).length
  const visibleMembers = reviewOnly ? members.filter(needsReview) : members

  // Counts by kind
  const counts = members.reduce(
    (acc, cur) => {
      const k = cur.kind
      acc[k] = (acc[k] || 0) + 1
      return acc
    },
    { beam: 0, column: 0, vbrace: 0, hbrace: 0, joist: 0 } as Record<string, number>
  )

  const getMemberKindLabel = (kind: string) => {
    return {
      beam: 'Beam',
      column: 'Column',
      vbrace: 'Vert Brace',
      hbrace: 'Horiz Brace',
      joist: 'Joist',
    }[kind] || kind
  }

  return (
    <div
      style={{
        // Collapse to a slim bar when the page has no members yet —
        // the canvas gets the vertical space instead of an empty black panel.
        height: members.length === 0 ? '72px' : '180px',
        transition: 'height 0.25s ease',
        backgroundColor: '#132E4F',
        borderTop: '1px solid rgba(59, 130, 246, 0.1)',
        display: 'flex',
        flexDirection: 'column',
        boxSizing: 'border-box',
        flexShrink: 0,
      }}
    >
      {/* Panel header / quick counts summary */}
      <div
        style={{
          height: '38px',
          borderBottom: '1px solid rgba(59, 130, 246, 0.08)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 16px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <span style={{ fontSize: '12px', fontWeight: 700, color: '#F1F5F9' }}>Takeoff Summary</span>
          <span style={{ fontSize: '11px', color: '#EC4899', backgroundColor: 'rgba(236,72,153,0.1)', padding: '2px 8px', borderRadius: '4px' }}>
            Beams: {counts.beam}
          </span>
          <span style={{ fontSize: '11px', color: '#3B82F6', backgroundColor: 'rgba(59,130,246,0.1)', padding: '2px 8px', borderRadius: '4px' }}>
            Columns: {counts.column}
          </span>
          <span style={{ fontSize: '11px', color: '#F59E0B', backgroundColor: 'rgba(245,158,11,0.1)', padding: '2px 8px', borderRadius: '4px' }}>
            Braces: {counts.vbrace + counts.hbrace}
          </span>
          <span style={{ fontSize: '11px', color: '#10B981', backgroundColor: 'rgba(16,185,129,0.1)', padding: '2px 8px', borderRadius: '4px' }}>
            Joists: {counts.joist}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <button
            onClick={() => setReviewOnly(!reviewOnly)}
            title="Show only members that need review (low confidence, missing section, or flagged)"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '5px',
              padding: '3px 10px',
              backgroundColor: reviewOnly ? 'rgba(245,158,11,0.2)' : 'transparent',
              border: `1px solid ${reviewCount > 0 ? 'rgba(245,158,11,0.5)' : 'rgba(148,163,184,0.2)'}`,
              borderRadius: '6px',
              color: reviewCount > 0 ? '#F59E0B' : '#64748B',
              fontSize: '11px',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            <AlertTriangle size={11} />
            Need Review: {reviewCount}
          </button>
          <span style={{ fontSize: '11px', color: '#64748B' }}>
            {members.length} total members detected
          </span>
        </div>
      </div>

      {/* Scrollable list of individual member entries */}
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '8px 16px',
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))',
          gap: '8px',
          alignContent: 'flex-start',
        }}
      >
        {members.length === 0 ? (
          <div
            style={{
              gridColumn: '1 / -1',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#475569',
              fontSize: '12px',
              flexDirection: 'row',
              gap: '8px',
              padding: '4px',
            }}
          >
            <FileSpreadsheet size={16} />
            <span>No members yet — set Scale + T.O.S. on the page card, then press Extract.</span>
          </div>
        ) : (
          visibleMembers.map((m) => {
            const isSelected = selectedMemberId === m.id
            const review = needsReview(m)
            return (
              <div
                key={m.id}
                onClick={() => onSelectMember(isSelected ? null : m.id)}
                style={{
                  padding: '8px 12px',
                  backgroundColor: isSelected ? 'rgba(59, 130, 246, 0.12)' : '#1B3A60',
                  border: isSelected ? '1px solid #3B82F6' : '1px solid rgba(255,255,255,0.05)',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  transition: 'all 0.15s ease',
                }}
                onMouseEnter={(e) => {
                  if (!isSelected) e.currentTarget.style.borderColor = 'rgba(59, 130, 246, 0.25)'
                }}
                onMouseLeave={(e) => {
                  if (!isSelected) e.currentTarget.style.borderColor = 'rgba(255,255,255,0.05)'
                }}
              >
                <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                  <span style={{ fontSize: '12px', fontWeight: 700, color: '#F1F5F9', display: 'flex', alignItems: 'center', gap: '5px' }}>
                    {m.section || ((m.geometry as any)?.grid_ref ? `Col @ ${(m.geometry as any).grid_ref}` : (m.geometry as any)?.grid_tag || 'Unlabelled')}
                    {review && <AlertTriangle size={10} style={{ color: '#F59E0B' }} />}
                  </span>
                  <span style={{ fontSize: '10px', color: '#94A3B8' }}>
                    {getMemberKindLabel(m.kind)}
                    {(m.geometry as any)?.grid_ref && (
                      <span style={{ color: '#38BDF8', fontWeight: 600 }}> · Grid {(m.geometry as any).grid_ref}</span>
                    )}
                    {m.source === 'manual' && <span style={{ color: '#8B5CF6' }}> · manual</span>}
                    {m.confidence !== null && m.confidence !== undefined && (
                      <span style={{ color: m.confidence >= 0.7 ? '#10B981' : '#F59E0B' }}>
                        {' '}· {Math.round(m.confidence * 100)}%
                      </span>
                    )}
                  </span>
                </div>
                {(() => {
                  const len = m.length_ft && m.length_ft > 0 ? m.length_ft : (() => {
                    const geo = m.geometry || {}
                    const bx1 = geo.bx1 ?? (m as any).bx1
                    const by1 = geo.by1 ?? (m as any).by1
                    const bx2 = geo.bx2 ?? (m as any).bx2
                    const by2 = geo.by2 ?? (m as any).by2
                    if (bx1 !== undefined && bx1 !== null && bx2 !== undefined && bx2 !== null && (bx1 !== bx2 || by1 !== by2)) {
                      const ratio = selectedRatio || 96
                      const ppf = 864.0 / ratio
                      // Preview images are rendered at 150 DPI by the ingest worker.
                      // PDF points = pixels × (72 / 150). Fall back to ANSI-D-sized
                      // defaults (2448 × 1584 pts) only when the image hasn't loaded yet.
                      const PREVIEW_DPI = 150
                      const pageWPt = imageNaturalWidth ? imageNaturalWidth * (72 / PREVIEW_DPI) : 2448
                      const pageHPt = imageNaturalWidth ? imageNaturalWidth * imageAspect * (72 / PREVIEW_DPI) : 1584
                      const lenPt = Math.hypot((bx2 - bx1) * pageWPt, (by2 - by1) * pageHPt)
                      const cFt = lenPt / ppf
                      if (cFt >= 2.0 && cFt <= 150.0) return Math.round(cFt * 10) / 10
                    }
                    return null
                  })()
                  return len !== null ? (
                    <span style={{ fontSize: '11px', color: '#60A5FA', fontWeight: 600 }}>
                      {len.toFixed(1)}'
                    </span>
                  ) : null
                })()}
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
