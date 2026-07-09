import React from 'react'
import { AlertTriangle, CheckCircle, ShieldAlert } from 'lucide-react'
import { useWorkspaceStore } from '../../../lib/stores/workspaceStore'

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
}

interface SummaryBarProps {
  members: Member[]
}

export function SummaryBar({ members }: SummaryBarProps) {
  const { isolation, setIsolation } = useWorkspaceStore()

  // Compute counts
  const counts = members.reduce(
    (acc, cur) => {
      let k = cur.kind
      if (k === 'vertical_brace' || k === 'vbrace') k = 'vbrace'
      else if (k === 'horizontal_brace' || k === 'hbrace') k = 'hbrace'

      if (k === 'beam') acc.beam++
      else if (k === 'column') acc.column++
      else if (k === 'vbrace' || k === 'hbrace') acc.brace++
      else if (k === 'joist') acc.joist++

      // Count verified
      if (cur.status === 'verified') {
        acc.verified++
      }

      // Count need review
      const needsReview =
        cur.status === 'need_review' ||
        cur.section === null ||
        (cur.confidence !== null && cur.confidence !== undefined && cur.confidence < 0.7)
      if (needsReview && cur.status !== 'verified') {
        acc.needReview++
      }

      if (cur.status !== 'excluded') {
        acc.totalEligible++
      }

      return acc
    },
    { beam: 0, column: 0, brace: 0, joist: 0, verified: 0, needReview: 0, totalEligible: 0 }
  )

  const pct = counts.totalEligible > 0 ? Math.round((counts.verified / counts.totalEligible) * 100) : 0

  const handleChipClick = (kind: string | null, special: 'review' | null = null) => {
    if (special === 'review') {
      const reviewIds = members
        .filter(
          (m) =>
            (m.status === 'need_review' ||
              m.section === null ||
              (m.confidence !== null && m.confidence !== undefined && m.confidence < 0.7)) &&
            m.status !== 'verified'
        )
        .map((m) => m.id)
      
      const isCurrentlyReviewIsolated =
        isolation &&
        isolation.ids &&
        isolation.ids.size === reviewIds.length &&
        reviewIds.every((id) => isolation.ids?.has(id))

      if (isCurrentlyReviewIsolated) {
        setIsolation(null)
      } else {
        setIsolation({ ids: new Set(reviewIds) })
      }
      return
    }

    if (!kind) {
      setIsolation(null)
      return
    }

    // Toggle logic for isolation
    const apiKind = kind === 'brace' ? 'vbrace' : kind
    if (isolation && (isolation.kind === apiKind || (kind === 'brace' && (isolation.kind === 'vbrace' || isolation.kind === 'hbrace')))) {
      setIsolation(null)
    } else {
      setIsolation({ kind: apiKind })
    }
  }

  const isBeamIsolated = isolation?.kind === 'beam'
  const isColIsolated = isolation?.kind === 'column'
  const isBraceIsolated = isolation?.kind === 'vbrace' || isolation?.kind === 'hbrace'
  const isJoistIsolated = isolation?.kind === 'joist'

  return (
    <div
      style={{
        height: '42px',
        backgroundColor: '#111827',
        borderTop: '1px solid rgba(59, 130, 246, 0.1)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 16px',
        boxSizing: 'border-box',
        flexShrink: 0,
        zIndex: 10,
      }}
    >
      {/* Category Chips */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span style={{ fontSize: '11px', fontWeight: 700, color: '#64748B', textTransform: 'uppercase', marginRight: '4px' }}>
          Isolate View:
        </span>
        
        {/* Beams */}
        <button
          onClick={() => handleChipClick('beam')}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '5px',
            padding: '3px 8px',
            backgroundColor: isBeamIsolated ? 'rgba(236, 72, 153, 0.15)' : 'rgba(31, 41, 55, 0.5)',
            border: `1px solid ${isBeamIsolated ? '#EC4899' : 'rgba(148, 163, 184, 0.15)'}`,
            borderRadius: '4px',
            color: '#EC4899',
            fontSize: '11px',
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          Beams: {counts.beam}
        </button>

        {/* Columns */}
        <button
          onClick={() => handleChipClick('column')}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '5px',
            padding: '3px 8px',
            backgroundColor: isColIsolated ? 'rgba(59, 130, 246, 0.15)' : 'rgba(31, 41, 55, 0.5)',
            border: `1px solid ${isColIsolated ? '#3B82F6' : 'rgba(148, 163, 184, 0.15)'}`,
            borderRadius: '4px',
            color: '#60A5FA',
            fontSize: '11px',
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          Columns: {counts.column}
        </button>

        {/* Braces */}
        <button
          onClick={() => handleChipClick('brace')}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '5px',
            padding: '3px 8px',
            backgroundColor: isBraceIsolated ? 'rgba(245, 158, 11, 0.15)' : 'rgba(31, 41, 55, 0.5)',
            border: `1px solid ${isBraceIsolated ? '#F59E0B' : 'rgba(148, 163, 184, 0.15)'}`,
            borderRadius: '4px',
            color: '#F59E0B',
            fontSize: '11px',
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          Braces: {counts.brace}
        </button>

        {/* Joists */}
        <button
          onClick={() => handleChipClick('joist')}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '5px',
            padding: '3px 8px',
            backgroundColor: isJoistIsolated ? 'rgba(16, 185, 129, 0.15)' : 'rgba(31, 41, 55, 0.5)',
            border: `1px solid ${isJoistIsolated ? '#10B981' : 'rgba(148, 163, 184, 0.15)'}`,
            borderRadius: '4px',
            color: '#10B981',
            fontSize: '11px',
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          Joists: {counts.joist}
        </button>

        {/* Clear isolation */}
        {isolation && (
          <button
            onClick={() => handleChipClick(null)}
            style={{
              background: 'none',
              border: 'none',
              color: '#64748B',
              fontSize: '10px',
              cursor: 'pointer',
              textDecoration: 'underline',
              paddingLeft: '4px',
            }}
          >
            Clear Isolation
          </button>
        )}
      </div>

      {/* Verification Progress and Need Review */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        {/* Need Review badge */}
        <button
          onClick={() => handleChipClick(null, 'review')}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '4px',
            padding: '3px 8px',
            backgroundColor: counts.needReview > 0 ? 'rgba(239, 68, 68, 0.1)' : 'transparent',
            border: `1px solid ${counts.needReview > 0 ? 'rgba(239, 68, 68, 0.25)' : 'transparent'}`,
            borderRadius: '4px',
            color: counts.needReview > 0 ? '#EF4444' : '#64748B',
            fontSize: '11px',
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          <AlertTriangle size={12} />
          <span>Review: {counts.needReview}</span>
        </button>

        {/* Progress Bar indicator */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <CheckCircle size={13} style={{ color: pct === 100 ? '#10B981' : '#64748B' }} />
          <span style={{ fontSize: '11px', fontWeight: 600, color: '#E2E8F0', whiteSpace: 'nowrap' }}>
            {pct}% Verified
          </span>
          <div
            style={{
              width: '80px',
              height: '6px',
              backgroundColor: '#1E293B',
              borderRadius: '3px',
              overflow: 'hidden',
              display: 'flex',
            }}
          >
            <div
              style={{
                width: `${pct}%`,
                height: '100%',
                backgroundColor: pct === 100 ? '#10B981' : '#3B82F6',
                borderRadius: '3px',
                transition: 'width 0.3s ease',
              }}
            />
          </div>
        </div>

        <span style={{ fontSize: '11px', color: '#475569', borderLeft: '1px solid #1E293B', paddingLeft: '16px' }}>
          {members.length} total members
        </span>
      </div>
    </div>
  )
}
