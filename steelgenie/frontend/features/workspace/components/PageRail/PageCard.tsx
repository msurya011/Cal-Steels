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
  // Verified live against the real SteelGenie app (2026-07-17 behavioral
  // study, two separate projects): a foundation-plan sheet labels this
  // field "Bottom of Column", not "Top of Steel" -- the value represents
  // where a column STARTS, not where a floor's steel sits. Optional
  // because older/unre-extracted pages won't have this set yet.
  is_foundation_plan?: boolean | null
}

interface PageCardProps {
  page: Page
  isActive: boolean
  isExtracting: boolean
  extractProgress: { pct: number; msg: string } | null
  isDirty?: boolean
  // Position of this page within the project-wide, all-drawings-merged pages
  // list (1-based). A project can have more than one uploaded drawing, and
  // every drawing's pages share the same "Page N" numbering sequence in the
  // UI so two different drawings never both show "Page 1" -- each page's own
  // `idx` is per-drawing and would collide. Falls back to `idx + 1` if not
  // supplied so this component still works standalone.
  displayNumber?: number
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
  backgroundColor: '#1E293B',
  border: '1px solid rgba(255, 255, 255, 0.1)',
  borderRadius: '4px',
  color: '#F1F5F9',
  fontSize: '12px',
  outline: 'none',
  boxSizing: 'border-box',
  transition: 'border-color 0.2s',
}

const rowLabel: React.CSSProperties = {
  fontSize: '10px',
  fontWeight: 600,
  color: '#94A3B8',
  textTransform: 'uppercase',
  letterSpacing: '0.04em',
  width: '60px',
  flexShrink: 0,
}

export const formatFtIn = (ftDecimal: number) => {
  if (isNaN(ftDecimal)) return ''
  const whole = Math.floor(ftDecimal)
  const inches = Math.round((ftDecimal - whole) * 12)
  if (inches === 12) return `${whole + 1}'-0"`
  return `${whole}'-${inches}"`
}

export const parseFtIn = (val: string): number => {
  if (!val || val.trim() === '') return NaN
  const clean = val.replace(/"/g, '').trim()
  if (!isNaN(Number(clean))) return parseFloat(clean)
  const parts = clean.split(/[-']/).map(s => s.trim()).filter(Boolean)
  // A lone "-" (or anything that yields no usable numeric parts once split)
  // used to fall through the `|| 0` fallbacks below and silently resolve to
  // a "valid" T.O.S. of 0 -- that let Extract run with a bogus elevation
  // instead of blocking on the still-empty field, and registered members
  // under a phantom 0ft floor. Bail out to NaN instead so the field stays
  // flagged invalid until a real value is entered.
  if (parts.length === 0) return NaN
  if (parts.length === 1) {
    const n = parseFloat(parts[0])
    return isNaN(n) ? NaN : n
  }
  const ft = parseFloat(parts[0])
  const inVal = parseFloat(parts[1])
  if (isNaN(ft) || isNaN(inVal)) return NaN
  return ft + (inVal / 12)
}

export function PageCard({
  page,
  isActive,
  isExtracting,
  extractProgress,
  isDirty,
  displayNumber,
  onClick,
  onUpdatePage,
  onExtract,
}: PageCardProps) {
  const pageNumber = displayNumber ?? page.idx + 1
  const [tosDraft, setTosDraft] = useState<string>(page.tos_ft !== null ? formatFtIn(page.tos_ft) : '')

  // Bug found 2026-07-17: this field's draft state was only ever
  // initialized once, on mount, from page.tos_ft -- it never re-synced if
  // the underlying page prop changed later (a successful save refetching
  // with the new value, a failed save leaving the old value, another user
  // editing the same page). That meant the box could keep showing a typed
  // value with no reliable connection to what actually got saved -- typing
  // a number and never blurring the field looked identical to a save that
  // silently failed. Re-sync whenever the page's own tos_ft changes so the
  // displayed value always reflects confirmed backend state, not stale
  // local draft state.
  React.useEffect(() => {
    setTosDraft(page.tos_ft !== null && page.tos_ft !== undefined ? formatFtIn(page.tos_ft) : '')
  }, [page.tos_ft])

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
    try {
      const v = parseFtIn(tosDraft)
      if (Number.isNaN(v)) {
        setTosDraft(page.tos_ft !== null && page.tos_ft !== undefined ? formatFtIn(page.tos_ft) : '')
        return
      }
      
      // Always snap the input field itself to standard format on blur
      setTosDraft(formatFtIn(v))
      
      // Using a tolerance check since we parse back and forth
      if (page.tos_ft !== null && page.tos_ft !== undefined && Math.abs(v - page.tos_ft) < 0.001) return
      await onUpdatePage(page.id, { tos_ft: v })
    } catch (err) {
      console.error('[PageCard] commitTos error:', err)
    }
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
      onClick={(e) => {
        console.log('[PageCard] Card clicked, triggering selection for page:', page.id)
        onClick()
      }}
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '8px',
        padding: '12px',
        backgroundColor: isActive ? '#1E293B' : '#0F172A',
        border: isActive ? '1px solid #3B82F6' : '1px solid rgba(255, 255, 255, 0.05)',
        borderRadius: '8px',
        cursor: 'pointer',
        transition: 'all 0.2s ease',
      }}
      onMouseEnter={(e) => {
        if (!isActive) e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.15)'
      }}
      onMouseLeave={(e) => {
        if (!isActive) e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.05)'
      }}
    >
      {/* Header: page label + extract (play) button */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: '12px', fontWeight: 700, color: '#F1F5F9' }}>
          Page {pageNumber}
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

      {/* Requesting Build -- a member was edited on this sheet since it was
          last extracted/built, so its BOM/3D data no longer reflects what's
          on the plan. Cleared automatically once the sheet is re-extracted. */}
      {isDirty && page.status !== 'not_started' && (
        <div
          style={{
            display: 'flex', alignItems: 'center', gap: '5px', padding: '4px 8px',
            backgroundColor: 'rgba(245, 158, 11, 0.12)', border: '1px solid rgba(245, 158, 11, 0.35)',
            borderRadius: '5px', color: '#F59E0B', fontSize: '10px', fontWeight: 700, alignSelf: 'flex-start',
          }}
          title="A member was edited since this sheet was last built -- re-extract to refresh BOM/3D data"
        >
          ⚠ Requesting Build
        </div>
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
            alt={page.title || `Page ${pageNumber}`}
            style={{ width: '100%', height: '100%', objectFit: 'contain' }}
          />
        ) : (
          <span style={{ fontSize: '11px', color: '#475569' }}>No Image</span>
        )}
      </div>

      {/* Top of Steel / Bottom of Column -- label depends on sheet type,
          matching the real SteelGenie app's convention (verified live on
          Bayhealth + Congress Heights: foundation plans ask for "Bottom
          of Column", framing/roof plans ask for "Top of Steel"). Same
          input, same stored value (tos_ft) -- this is a labeling fix
          only, not a change to what the number means downstream. */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span style={rowLabel}>{page.is_foundation_plan ? 'Bottom of Column' : 'Top of Steel'}</span>
        {!tosSet && tosDraft === '' ? (
          <div
            onClick={(e) => {
              stop(e)
              setTosDraft(' ') // space triggers the input to mount
            }}
            style={{
              ...inputStyle,
              border: '1px solid #EF4444',
              color: '#EF4444',
              display: 'flex',
              alignItems: 'center',
              cursor: 'text',
            }}
          >
            {page.is_foundation_plan ? 'set a valid elevation' : 'set a valid T.O.S.'}
          </div>
        ) : (
          <div style={{ display: 'flex', width: '100%', borderRadius: '4px', overflow: 'hidden', border: '1px solid rgba(255, 255, 255, 0.1)', backgroundColor: '#1E293B' }}>
            <input
              type="text"
              autoFocus={tosDraft === ' '}
              value={tosDraft.trim()}
              placeholder="e.g. 15-5"
              onClick={stop}
              onChange={(e) => setTosDraft(e.target.value)}
              onBlur={commitTos}
              onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()}
              style={{
                ...inputStyle,
                border: 'none',
                borderRadius: 0,
                color: '#F1F5F9',
                flex: 1,
                minWidth: 0,
              }}
            />
            {tosDraft.trim() !== '' && !isNaN(parseFtIn(tosDraft)) && (
              <div style={{ 
                display: 'flex', 
                alignItems: 'center', 
                justifyContent: 'center', 
                padding: '0 8px', 
                backgroundColor: 'rgba(59, 130, 246, 0.2)', 
                color: '#60A5FA', 
                fontSize: '11px', 
                fontWeight: 600,
                borderLeft: '1px solid rgba(255, 255, 255, 0.05)',
                whiteSpace: 'nowrap'
              }}>
                {formatFtIn(parseFtIn(tosDraft))}
              </div>
            )}
          </div>
        )}
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
