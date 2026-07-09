import React, { useState } from 'react'
import { Play, MoreVertical } from 'lucide-react'
import { Spinner } from '../../../../components/ui/Spinner'

interface Page {
  id: string
  drawing_id: string
  idx: number
  sheet_no: string | null
  title: string | null
  scale_num: number | null
  scale_label: string | null
  tos_ft: number | null
  status: string
  thumb_url: string | null
}

interface PageCardProps {
  page: Page
  isActive: boolean
  isExtracting: boolean
  extractProgress: { pct: number; msg: string } | null
  onClick: () => void
  onUpdatePage: (pageId: string, data: any) => Promise<any>
  onExtract: (page: Page) => void
}

// Standard architectural scales → ratio (drawing units per foot basis used by the engine)
export const SCALE_OPTIONS: { label: string; ratio: number }[] = [
  { label: '1/16" = 1\'-0"', ratio: 192 },
  { label: '3/32" = 1\'-0"', ratio: 128 },
  { label: '1/8" = 1\'-0"', ratio: 96 },
  { label: '3/16" = 1\'-0"', ratio: 64 },
  { label: '1/4" = 1\'-0"', ratio: 48 },
  { label: '3/8" = 1\'-0"', ratio: 32 },
  { label: '1/2" = 1\'-0"', ratio: 24 },
  { label: '3/4" = 1\'-0"', ratio: 16 },
  { label: '1" = 1\'-0"', ratio: 12 },
]

const STATUS_OPTIONS = [
  { value: 'not_started', label: 'Not Started' },
  { value: 'estimating', label: 'Estimating' },
  { value: 'need_review', label: 'Need Review' },
  { value: 'built', label: 'Built' },
]

const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: '5px 8px',
  backgroundColor: '#0E2240',
  border: '1px solid rgba(59, 130, 246, 0.2)',
  borderRadius: '6px',
  color: '#F1F5F9',
  fontSize: '12px',
  outline: 'none',
  boxSizing: 'border-box',
}

const rowLabel: React.CSSProperties = {
  fontSize: '10px',
  fontWeight: 700,
  color: '#64748B',
  textTransform: 'uppercase',
  letterSpacing: '0.04em',
  width: '52px',
  flexShrink: 0,
}

export function PageCard({
  page,
  isActive,
  isExtracting,
  extractProgress,
  onClick,
  onUpdatePage,
  onExtract,
}: PageCardProps) {
  const [tosDraft, setTosDraft] = useState<string>(page.tos_ft !== null ? String(page.tos_ft) : '')

  const getStatusColor = (status: string) => {
    if (status === 'built') return '#10B981'
    if (status === 'estimating') return '#3B82F6'
    if (status === 'need_review') return '#F59E0B'
    return '#475569'
  }

  const scaleSet = page.scale_num !== null && page.scale_num !== undefined
  const tosSet = page.tos_ft !== null && page.tos_ft !== undefined
  const canExtract = scaleSet && !isExtracting

  const commitTos = async () => {
    const v = parseFloat(tosDraft)
    if (Number.isNaN(v)) return
    if (v === page.tos_ft) return
    await onUpdatePage(page.id, { tos_ft: v })
  }

  const handleScale = async (e: React.ChangeEvent<HTMLSelectElement>) => {
    const opt = SCALE_OPTIONS.find((o) => o.label === e.target.value)
    if (!opt) return
    await onUpdatePage(page.id, { scale_label: opt.label, scale_num: opt.ratio })
  }

  const handleStatus = async (e: React.ChangeEvent<HTMLSelectElement>) => {
    await onUpdatePage(page.id, { status: e.target.value })
  }

  const stop = (e: React.SyntheticEvent) => e.stopPropagation()

  return (
    <div
      onClick={onClick}
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '8px',
        padding: '12px',
        backgroundColor: isActive ? '#1B3A60' : '#132E4F',
        border: isActive ? '1px solid #3B82F6' : '1px solid rgba(59, 130, 246, 0.08)',
        borderRadius: '8px',
        cursor: 'pointer',
        transition: 'all 0.2s ease',
      }}
      onMouseEnter={(e) => {
        if (!isActive) e.currentTarget.style.borderColor = 'rgba(59, 130, 246, 0.25)'
      }}
      onMouseLeave={(e) => {
        if (!isActive) e.currentTarget.style.borderColor = 'rgba(59, 130, 246, 0.08)'
      }}
    >
      {/* Header: page label + extract (play) button */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: '12px', fontWeight: 700, color: '#F1F5F9' }}>
          Page {page.idx + 1}
          {page.title ? ` | ${page.title}` : ''}
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <button
            onClick={(e) => {
              stop(e)
              if (canExtract) onExtract(page)
            }}
            disabled={!canExtract}
            title={
              !scaleSet
                ? 'Set a scale first to enable extraction'
                : isExtracting
                ? 'Extraction running…'
                : 'Run member extraction on this sheet'
            }
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: '26px',
              height: '26px',
              borderRadius: '50%',
              border: `1px solid ${canExtract ? '#10B981' : 'rgba(148,163,184,0.25)'}`,
              backgroundColor: canExtract ? 'rgba(16,185,129,0.12)' : 'transparent',
              color: canExtract ? '#10B981' : '#475569',
              cursor: canExtract ? 'pointer' : 'not-allowed',
            }}
          >
            {isExtracting ? <Spinner size="sm" /> : <Play size={12} />}
          </button>
          <span
            style={{
              width: '8px',
              height: '8px',
              borderRadius: '50%',
              backgroundColor: getStatusColor(page.status),
            }}
            title={`Status: ${page.status}`}
          />
        </div>
      </div>

      {/* Extraction progress bar */}
      {isExtracting && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
          <div
            style={{
              width: '100%',
              height: '5px',
              backgroundColor: 'rgba(59, 130, 246, 0.15)',
              borderRadius: '3px',
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                width: `${extractProgress?.pct ?? 5}%`,
                height: '100%',
                backgroundColor: '#3B82F6',
                borderRadius: '3px',
                transition: 'width 0.6s ease',
              }}
            />
          </div>
          <span style={{ fontSize: '10px', color: '#60A5FA' }}>
            {extractProgress ? `${extractProgress.pct}% — ${extractProgress.msg}` : 'Starting extraction…'}
          </span>
        </div>
      )}

      {/* Sheet number */}
      {page.sheet_no && (
        <span style={{ fontSize: '11px', color: '#94A3B8', marginTop: '-4px' }}>Sheet {page.sheet_no}</span>
      )}

      {/* Thumbnail */}
      <div
        style={{
          width: '100%',
          height: '110px',
          backgroundColor: '#FFFFFF',
          borderRadius: '4px',
          overflow: 'hidden',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          border: '1px solid rgba(255, 255, 255, 0.05)',
        }}
      >
        {page.thumb_url ? (
          <img
            src={page.thumb_url}
            alt={page.title || `Page ${page.idx + 1}`}
            style={{ width: '100%', height: '100%', objectFit: 'contain' }}
          />
        ) : (
          <span style={{ fontSize: '11px', color: '#475569' }}>No Image</span>
        )}
      </div>

      {/* Top of Steel */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span style={rowLabel}>Top of Steel</span>
        <input
          type="number"
          step="0.5"
          value={tosDraft}
          placeholder="set a valid T.O.S."
          onClick={stop}
          onChange={(e) => setTosDraft(e.target.value)}
          onBlur={commitTos}
          onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()}
          style={{
            ...inputStyle,
            border: tosSet ? inputStyle.border : '1px solid rgba(239, 68, 68, 0.5)',
            color: tosSet ? '#F1F5F9' : '#FCA5A5',
          }}
        />
      </div>

      {/* Scale */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span style={rowLabel}>Scale</span>
        <select
          value={page.scale_label || ''}
          onClick={stop}
          onChange={handleScale}
          style={{ ...inputStyle, cursor: 'pointer' }}
        >
          <option value="" disabled>
            Select an option
          </option>
          {SCALE_OPTIONS.map((o) => (
            <option key={o.label} value={o.label}>
              {o.label}
            </option>
          ))}
        </select>
      </div>

      {/* Status */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span style={rowLabel}>Status</span>
        <select
          value={page.status || 'not_started'}
          onClick={stop}
          onChange={handleStatus}
          style={{ ...inputStyle, cursor: 'pointer' }}
        >
          {STATUS_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
    </div>
  )
}
