'use client'

import React, { useMemo, useState } from 'react'
import { ChevronDown, ChevronUp, Eye, EyeOff, Target, AlertTriangle } from 'lucide-react'
import { useWorkspaceStore } from '../../../lib/stores/workspaceStore'

interface Member {
  id: string
  kind: string
  section: string | null
  length_ft: number | null
  geometry?: any
  status?: string
}

interface SheetSummaryProps {
  members: Member[]
  bomItems?: any[]
  activeSheetName?: string
}

/**
 * Parse unit weight (lb/ft) from common US shape designations:
 * W12X26 → 26, HP12X53 → 53, C15X33.9 → 33.9, MC18X42.7 → 42.7, S12X31.8 → 31.8
 * HSS/L/pipe designations don't encode weight — returns null for those.
 */
function unitWeightLbFt(section: string | null): number | null {
  if (!section) return null
  const s = section.toUpperCase().trim()
  const m = s.match(/^(?:W|WT|S|ST|C|MC|M|MT|HP)\s*\d+(?:\.\d+)?X(\d+(?:\.\d+)?)/)
  if (m) return parseFloat(m[1])
  if (s.startsWith('HSS')) return 10.0
  if (s.startsWith('PIPE')) return 8.0
  if (s.startsWith('L')) return 3.5
  return null
}

export function SheetSummary({ members, bomItems, activeSheetName }: SheetSummaryProps) {
  const store = useWorkspaceStore()
  const {
    layers,
    toggleLayerVisibility,
    isolation,
    setIsolation,
    setSearchQuery,
  } = store

  const [open, setOpen] = useState(true)
  const [hoveredRow, setHoveredRow] = useState<string | null>(null)

  const stats = useMemo(() => {
    const counts = { column: 0, beam: 0, vbrace: 0, hbrace: 0, joist: 0 }
    let weightLbs = 0
    for (const m of members) {
      const sectionStr = (m.section || '').trim().toUpperCase()
      const isExplicitBeam = m.kind === 'beam' && /^(W\d|HSS|C\d|MC\d|L\d|PIPE|ISA)/.test(sectionStr)
      const isExplicitJoist = m.kind === 'joist' ||
        /\d{1,2}(?:K|LH|DLH|KSP|G|CJ|CS)/.test(sectionStr) ||
        sectionStr.includes('JOIST')

      let k = m.kind
      if (isExplicitJoist || (!isExplicitBeam && m.kind !== 'column' && m.kind !== 'footing')) {
        k = 'joist'
      } else if (isExplicitBeam) {
        k = 'beam'
      }

      if (k in counts) (counts as any)[k] += 1
      const uw = unitWeightLbFt(m.section)
      if (uw && m.length_ft && k !== 'joist') weightLbs += uw * m.length_ft
    }

    let weldStuds = 0
    let bolts = 0

    if (bomItems && bomItems.length > 0 && activeSheetName) {
      const sheetBom = bomItems.filter(item => item.sheet === activeSheetName)
      sheetBom.forEach(item => {
        if (item.category === 'Weld Studs') {
          weldStuds += item.weld_studs || item.qty || 0
        }
        if (item.category === 'Bolts') {
          bolts += item.qty || 0
        }
      })
    }

    return { counts, tons: weightLbs / 2000, weldStuds, bolts }
  }, [members, bomItems, activeSheetName])

  const reviewStats = useMemo(() => {
    const total = members.length
    if (total === 0) return { pct: 100, remain: 0 }
    const verified = members.filter(m => m.status === 'verified').length
    const remain = members.filter(m => m.status !== 'verified' && m.status !== 'excluded').length
    const pct = Math.round((verified / total) * 100)
    return { pct, remain }
  }, [members])

  const totalsRow = (label: string, value: React.ReactNode) => (
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
      <span style={{ fontSize: '11px', color: '#94A3B8', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.4px' }}>{label}:</span>
      <span style={{ fontSize: '12px', fontWeight: 700, color: '#F1F5F9' }}>{value}</span>
    </div>
  )

  const handleRowClick = (kind: string) => {
    // Filter Member Explorer list by kind
    setSearchQuery(kind)
  }

  const handleIsolateClick = (e: React.MouseEvent, kind: string) => {
    e.stopPropagation()
    const activeIsolateKind = isolation?.kind
    if (activeIsolateKind === kind) {
      setIsolation(null)
    } else {
      setIsolation({ kind })
    }
  }

  const renderSummaryRow = (label: string, kindKey: string, count: number, isTotals = false) => {
    const visible = layers.classVisibility[kindKey] !== false
    const isIsolated = isolation?.kind === kindKey
    const isHovered = hoveredRow === kindKey

    return (
      <div
        key={label}
        onClick={() => handleRowClick(kindKey)}
        onMouseEnter={() => setHoveredRow(kindKey)}
        onMouseLeave={() => setHoveredRow(null)}
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '7px 14px',
          borderBottom: '1px solid rgba(255,255,255,0.05)',
          cursor: 'pointer',
          backgroundColor: isHovered ? 'rgba(59, 130, 246, 0.08)' : 'transparent',
          transition: 'background-color 0.15s ease',
        }}
      >
        <span style={{ fontSize: '12px', color: '#B9C7D8', fontWeight: 600 }}>{label}</span>
        
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          {/* Action buttons revealed on hover */}
          {(isHovered || isIsolated || !visible) && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  toggleLayerVisibility(kindKey)
                }}
                style={{
                  background: 'none',
                  border: 'none',
                  color: visible ? '#3B82F6' : '#64748B',
                  cursor: 'pointer',
                  padding: 0,
                  display: 'flex',
                }}
                title={visible ? 'Hide layer' : 'Show layer'}
              >
                {visible ? <Eye size={13} /> : <EyeOff size={13} />}
              </button>
              
              <button
                onClick={(e) => handleIsolateClick(e, kindKey)}
                style={{
                  background: 'none',
                  border: 'none',
                  color: isIsolated ? '#10B981' : '#64748B',
                  cursor: 'pointer',
                  padding: 0,
                  display: 'flex',
                }}
                title={isIsolated ? 'Clear Isolation' : 'Isolate category'}
              >
                <Target size={13} />
              </button>
            </div>
          )}

          <span
            style={{
              fontSize: '12px',
              fontWeight: 700,
              color: isTotals ? '#F1F5F9' : '#FFFFFF',
              backgroundColor: isTotals ? 'rgba(59,130,246,0.35)' : 'transparent',
              padding: isTotals ? '1px 6px' : undefined,
              borderRadius: isTotals ? '4px' : undefined,
            }}
          >
            {isTotals ? count.toFixed(2) : count}
          </span>
        </div>
      </div>
    )
  }

  return (
    <div
      style={{
        width: '260px',
        backgroundColor: '#111827',
        borderLeft: '1px solid rgba(59, 130, 246, 0.1)',
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        flexShrink: 0,
        overflowY: 'auto',
      }}
    >
      {/* 1. PROJECT TOTALS */}
      <div style={{ padding: '10px 0 0' }}>
        {totalsRow('Total Weight (tons)', stats.tons.toFixed(2))}
        {totalsRow('Hrs/Ton', <span style={{ color: '#64748B', fontSize: '10px', fontWeight: 700 }}>WIP</span>)}
      </div>

      {/* 2. SHEET SUMMARY (COLLAPSIBLE CARD) */}
      <div
        style={{
          margin: '12px 10px',
          borderRadius: '8px',
          overflow: 'hidden',
          border: '1px solid rgba(59,130,246,0.12)',
          backgroundColor: '#0F172A',
        }}
      >
        <button
          onClick={() => setOpen(!open)}
          style={{
            width: '100%',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            padding: '9px 14px',
            backgroundColor: '#0F172A',
            border: 'none',
            color: '#F1F5F9',
            fontSize: '12px',
            fontWeight: 700,
            cursor: 'pointer',
            borderBottom: open ? '1px solid rgba(255,255,255,0.05)' : 'none',
          }}
        >
          <span>SHEET SUMMARY</span>
          {open ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
        </button>

        {open && (
          <div style={{ backgroundColor: '#111827' }}>
            {renderSummaryRow('Column', 'column', stats.counts.column)}
            {renderSummaryRow('Beam', 'beam', stats.counts.beam)}
            {renderSummaryRow('Vertical Brace', 'vbrace', stats.counts.vbrace)}
            {renderSummaryRow('Horizontal Brace', 'hbrace', stats.counts.hbrace)}
            {renderSummaryRow('Joist', 'joist', stats.counts.joist)}
            {renderSummaryRow('Total Weight (tons)', 'weight', stats.tons, true)}
          </div>
        )}
      </div>

      {/* 3. REVIEW PROGRESS TRACKING CARD */}
      <div
        style={{
          margin: '0 10px 12px',
          padding: '12px 14px',
          borderRadius: '8px',
          border: '1px solid rgba(59,130,246,0.12)',
          backgroundColor: '#0F172A',
          display: 'flex',
          flexDirection: 'column',
          gap: '10px',
        }}
      >
        <div style={{ fontSize: '10px', fontWeight: 700, color: '#94A3B8', textTransform: 'uppercase' }}>
          Review
        </div>
        
        {/* Progress bar */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', fontWeight: 600 }}>
            <span>{reviewStats.pct}% verified</span>
            <span>{members.length - reviewStats.remain}/{members.length}</span>
          </div>
          <div style={{ width: '100%', height: '6px', backgroundColor: '#1E293B', borderRadius: '3px', overflow: 'hidden' }}>
            <div
              style={{
                width: `${reviewStats.pct}%`,
                height: '100%',
                backgroundColor: '#10B981',
                borderRadius: '3px',
                transition: 'width 0.3s ease',
              }}
            />
          </div>
        </div>

        {/* Need Review badge/trigger button */}
        {reviewStats.remain > 0 && (
          <button
            onClick={() => setSearchQuery('need_review')}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '6px',
              padding: '6px 10px',
              backgroundColor: 'rgba(245, 158, 11, 0.1)',
              border: '1px solid rgba(245, 158, 11, 0.25)',
              borderRadius: '6px',
              color: '#F59E0B',
              fontSize: '11px',
              fontWeight: 700,
              cursor: 'pointer',
              transition: 'background-color 0.2s',
            }}
            onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'rgba(245, 158, 11, 0.18)'}
            onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'rgba(245, 158, 11, 0.1)'}
          >
            <AlertTriangle size={13} />
            <span>{reviewStats.remain} remain to verify</span>
          </button>
        )}
      </div>

      <div style={{ padding: '0 14px 14px', fontSize: '10px', color: '#475569', lineHeight: 1.5 }}>
        Weight computed from W/S/C/M/HP designations × member length. Connection
        quantities (bolts, plates, camber, studs) populate after the Build step (M4).
      </div>
    </div>
  )
}
