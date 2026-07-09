'use client'

import React, { useMemo, useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'

interface Member {
  id: string
  kind: string
  section: string | null
  length_ft: number | null
  geometry?: any
}

interface SheetSummaryProps {
  members: Member[]
}

/**
 * Parse unit weight (lb/ft) from common US shape designations:
 * W12X26 → 26, HP12X53 → 53, C15X33.9 → 33.9, MC18X42.7 → 42.7, S12X31.8 → 31.8
 * HSS/L/pipe designations don't encode weight — returns null for those.
 */
function unitWeightLbFt(section: string | null): number | null {
  if (!section) return null
  const s = section.toUpperCase().trim()
  if (s.startsWith('HSS') || s.startsWith('L') || s.startsWith('PIPE')) return null
  const m = s.match(/^(?:W|WT|S|ST|C|MC|M|MT|HP)\s*\d+(?:\.\d+)?X(\d+(?:\.\d+)?)/)
  return m ? parseFloat(m[1]) : null
}

export function SheetSummary({ members }: SheetSummaryProps) {
  const [open, setOpen] = useState(true)

  const stats = useMemo(() => {
    const counts = { column: 0, beam: 0, vbrace: 0, hbrace: 0, joist: 0 }
    let weightLbs = 0
    for (const m of members) {
      if (m.kind in counts) (counts as any)[m.kind] += 1
      const uw = unitWeightLbFt(m.section)
      if (uw && m.length_ft) weightLbs += uw * m.length_ft
    }
    return { counts, tons: weightLbs / 2000 }
  }, [members])

  const row = (label: string, value: React.ReactNode, highlight = false) => (
    <div
      key={label}
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: '7px 14px',
        borderBottom: '1px solid rgba(255,255,255,0.05)',
      }}
    >
      <span style={{ fontSize: '12px', color: '#B9C7D8', fontWeight: 600 }}>{label}:</span>
      <span
        style={{
          fontSize: '12px',
          fontWeight: 700,
          color: '#F1F5F9',
          backgroundColor: highlight ? 'rgba(59,130,246,0.35)' : 'transparent',
          padding: highlight ? '1px 6px' : undefined,
          borderRadius: highlight ? '4px' : undefined,
        }}
      >
        {value}
      </span>
    </div>
  )

  return (
    <div
      style={{
        width: '260px',
        backgroundColor: '#132E4F',
        borderLeft: '1px solid rgba(59, 130, 246, 0.12)',
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        flexShrink: 0,
        overflowY: 'auto',
      }}
    >
      {/* Top quick metrics (mirrors reference layout) */}
      <div style={{ padding: '10px 0 0' }}>
        {row('Weld Studs', 0)}
        {row('Total Weight (tons)', stats.tons.toFixed(2))}
        {row('Hrs/Ton', <span style={{ color: '#94A3B8' }}>WIP</span>)}
      </div>

      {/* Collapsible Sheet Summary card */}
      <div style={{ margin: '12px 10px', borderRadius: '8px', overflow: 'hidden', border: '1px solid rgba(59,130,246,0.18)' }}>
        <button
          onClick={() => setOpen(!open)}
          style={{
            width: '100%',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            padding: '9px 14px',
            backgroundColor: '#1B3A60',
            border: 'none',
            color: '#F1F5F9',
            fontSize: '13px',
            fontWeight: 700,
            cursor: 'pointer',
          }}
        >
          Sheet Summary
          {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>

        {open && (
          <div style={{ backgroundColor: '#122B4A' }}>
            {row('Column', stats.counts.column)}
            {row('Beam', stats.counts.beam)}
            {row('Vertical Brace', stats.counts.vbrace)}
            {row('Horizontal Brace', stats.counts.hbrace)}
            {row('Joists', stats.counts.joist)}
            {row('Moment Connection', 0)}
            {row('Bolt', 0)}
            {row('Embed Plate', 0)}
            {row('Camber', 0)}
            {row('Weld Studs', 0)}
            {row('Total Weight (tons)', stats.tons.toFixed(2), true)}
          </div>
        )}
      </div>

      <div style={{ padding: '0 14px 14px', fontSize: '10px', color: '#64748B', lineHeight: 1.5 }}>
        Weight computed from W/S/C/M/HP designations × member length. Connection
        quantities (bolts, plates, camber, studs) populate after the Build step (M4).
      </div>
    </div>
  )
}
