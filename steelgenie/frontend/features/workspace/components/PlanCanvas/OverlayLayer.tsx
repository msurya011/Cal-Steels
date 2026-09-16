import React, { useMemo } from 'react'
import { useWorkspaceStore, getMemberRenderProps } from '../../../../lib/stores/workspaceStore'
import { ColumnSymbol } from './ColumnSymbol'
import { BeamLine } from './BeamLine'
import { DimensionLine } from './DimensionLine'

interface Member {
  id: string
  kind: string
  section: string | null
  grade: string | null
  rotation: number
  geometry: {
    x: number
    y: number
    w?: number
    h?: number
    bx1?: number | null
    by1?: number | null
    bx2?: number | null
    by2?: number | null
    angle_deg?: number | null
    beam_dir?: string
    color?: string
  }
  confidence?: number | null
  status?: string
  source?: string
  length_ft?: number | null
  piecemark?: string | null
  reaction?: string | null
}

interface OverlayLayerProps {
  members: Member[]
  onMemberClick: (member: Member, e: React.MouseEvent) => void
  hoveredMemberId: string | null
  onMemberHover: (id: string | null) => void
  onMemberDragEnd?: (id: string, dx: number, dy: number) => void
  onEndpointDragEnd?: (id: string, endpoint: 'start' | 'end', x: number, y: number) => void
  snapPoint?: (x: number, y: number, ignorePt?: { x: number; y: number } | null) => { x: number; y: number; snapped: boolean }
}

export function OverlayLayer({
  members,
  onMemberClick,
  hoveredMemberId,
  onMemberHover,
  onMemberDragEnd,
  onEndpointDragEnd,
  snapPoint,
}: OverlayLayerProps) {
  const store = useWorkspaceStore()
  const { layers, selection, hiddenIds, isolation, zoomTarget, zoomLevel } = store
  // Labels are always shown, SteelGenie-style — now that they're plain rotated
  // text (no chip/bubble background) they're light enough not to clutter dense
  // sheets even at full-plan zoom-out, matching the reference framing plans.
  const showChips = true

  // Helper to compose label text dynamically
  const getLabelText = (m: Member) => {
    // 1. Column Reference Display (Resolved vs Unresolved)
    if (m.kind === 'column') {
      const geo: any = m.geometry || {}
      const sec = m.section || geo.resolved_profile || ''
      const bp = geo.base_plate_mark ? ` • ${geo.base_plate_mark}` : ''
      const gridRef = geo.grid_tag || (geo.grid_ref ? `Col @ ${geo.grid_ref}` : null) || geo.grid_location

      if (sec || m.piecemark) {
        const gridSuffix = gridRef ? ` [${gridRef.replace(/^Col\s*@\s*/i, '')}]` : ''
        return `${sec || m.piecemark}${bp}${gridSuffix}`
      }
      return gridRef || 'Column'
    }

    const parts: string[] = []

    // 2. Piecemarks / Section (e.g. W16X26)
    if (m.section || m.piecemark) {
      parts.push(m.section || m.piecemark || '')
    }

    // 3. Lengths (always included by default when length_ft is present or computed from span geometry)
    if (m.kind !== 'column') {
      let len = m.length_ft && m.length_ft > 0 ? m.length_ft : null
      if (!len) {
        const geo: any = m.geometry || {}
        const bx1 = geo.bx1 ?? (m as any).bx1
        const by1 = geo.by1 ?? (m as any).by1
        const bx2 = geo.bx2 ?? (m as any).bx2
        const by2 = geo.by2 ?? (m as any).by2
        if (bx1 !== undefined && bx1 !== null && bx2 !== undefined && bx2 !== null && (bx1 !== bx2 || by1 !== by2)) {
          const ratio = store.selectedRatio || 96
          const ppf = 864.0 / ratio
          const wPt = store.imageNaturalWidth || 2592
          const hPt = store.imageAspect ? wPt / store.imageAspect : 1728
          const lenPt = Math.hypot((bx2 - bx1) * wPt, (by2 - by1) * hPt)
          const calcFt = lenPt / ppf
          if (calcFt >= 1.0 && calcFt <= 250.0) len = Math.round(calcFt * 10) / 10
        }
      }
      if (len && len > 0) {
        parts.push(`${len.toFixed(1)}'`)
      }
    }

    // 4. Reactions
    if (layers.aids?.reactions === true && m.reaction) {
      parts.push(m.reaction)
    }

    return parts.filter(Boolean).join(' • ') || (m.section ?? '')
  }

  // Memoize visible members and sort them so columns render on top.
  // This prevents expensive O(N log N) sorting and redundant getMemberRenderProps
  // calls on every render cycle when hovering/selecting.
  const { visibleMembers, sortedVisibleMembers } = useMemo(() => {
    const visible: Member[] = []
    const visibleWithProps: { m: Member, renderProps: ReturnType<typeof getMemberRenderProps> }[] = []

    for (const m of members) {
      const renderProps = getMemberRenderProps({ layers, hiddenIds, isolation }, m)
      if (renderProps.visible) {
        visible.push(m)
        visibleWithProps.push({ m, renderProps })
      }
    }

    // Sort so columns paint last (on top)
    const sorted = visibleWithProps.sort((a, b) => (a.m.kind === 'column' ? 1 : 0) - (b.m.kind === 'column' ? 1 : 0))

    return { visibleMembers: visible, sortedVisibleMembers: sorted }
  }, [members, layers, hiddenIds, isolation])

  const allHiddenByFilter = members.length > 0 && visibleMembers.length === 0

  return (
    <>
      {allHiddenByFilter && (
        <div
          style={{
            position: 'absolute', top: 12, left: '50%', transform: 'translateX(-50%)',
            zIndex: 20, display: 'flex', alignItems: 'center', gap: '10px',
            backgroundColor: '#1E293B', border: '1px solid rgba(251,191,36,0.4)',
            borderRadius: '8px', padding: '8px 14px', fontSize: '12px', color: '#F1F5F9',
            boxShadow: '0 4px 12px rgba(0,0,0,0.3)', pointerEvents: 'auto',
          }}
        >
          <span>
            {members.length} member{members.length === 1 ? '' : 's'} extracted, but all hidden by a layer/isolation filter.
          </span>
          <button
            onClick={() => useWorkspaceStore.getState().applyPreset('preset-all')}
            style={{
              background: '#3B82F6', border: 'none', borderRadius: '6px', color: '#fff',
              fontSize: '12px', fontWeight: 600, padding: '4px 10px', cursor: 'pointer',
            }}
          >
            Show all layers
          </button>
        </div>
      )}
      <svg
        style={{
          position: 'absolute',
          inset: 0,
          width: '100%',
          height: '100%',
          overflow: 'hidden',
          pointerEvents: 'none',
          zIndex: 10,
        }}
      >
        {/* Glow Filter for Hover & ZoomTarget */}
        <defs>
          <filter id="glow-select" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
          </filter>
        </defs>

        {/* Columns sit exactly where beam lines converge — if a column happened
          to be earlier in the members array than the beams crossing it, SVG's
          paint-order-by-document-order would bury the column marker under
          the beam lines drawn on top of it, making it invisible even though
          it's rendering correctly. Force columns to always paint last (on
          top) so every column marker is guaranteed visible. */}
        {sortedVisibleMembers.map(({ m, renderProps }) => {


          const { color, opacity } = renderProps
          const geo = m.geometry
          const isSelected = selection.has(m.id)
          const isHovered = hoveredMemberId === m.id
          const isZoomTarget = zoomTarget?.id === m.id
          const isLowConf = m.confidence !== undefined && m.confidence !== null && m.confidence < 0.7

          // Filter visual styles
          let filterStyle = undefined
          if (isSelected || isZoomTarget) {
            filterStyle = 'url(#glow-select)'
          }

          // Handle manually added highlights
          if (m.source === 'manual' && !layers.aids.markers) {
            return null
          }

          const strokeWidthModifier = isSelected ? 2 : 0

          // Confidence Halo
          const showHalo = layers.aids.confidenceHalo && isLowConf

          // 0. Footings are extracted and kept as real data (BOM, linked_group_id
          // pairing with their column, etc.) but are explicitly NOT drawn with a
          // symbol marker in this overlay -- verified live 2026-07-17 against
          // user feedback: kind="footing" members were falling through to the
          // generic brace/circle-marker branch below (the only kinds this file
          // special-cases are "column" and "beam"), so every footing was getting
          // a stray circle+line "brace" marker drawn right on top of its own
          // linked column's I/H tick at the exact same position -- reading as
          // "everything is marked as a column" clutter. Only a real column
          // (kind="column") should ever get a marker here.
          if (m.kind === 'footing') {
            return null
          }

          // 1. Column rendering — oriented steel symbol (I / box / pipe) with states
          if (m.kind === 'column') {
            return (
              <ColumnSymbol
                key={m.id}
                member={m}
                renderProps={renderProps}
                layers={layers}
                isSelected={isSelected}
                isHovered={isHovered}
                isZoomTarget={isZoomTarget}
                isLowConf={isLowConf}
                getLabelText={getLabelText}
                onClick={(e) => {
                  e.stopPropagation()
                  onMemberClick(m, e)
                }}
                onMouseEnter={() => onMemberHover(m.id)}
                onMouseLeave={() => onMemberHover(null)}
                onDragEnd={onMemberDragEnd}
                snapPoint={snapPoint}
              />
            )
          }

          // 2. Determine member category: Column, Beam, or Joist
          const sectionStr = (m.section || '').trim().toUpperCase()
          const piecemarkStr = (m.piecemark || '').trim().toUpperCase()

          // Joist check: explicit kind, SJI callout (20K4, 28K6, 24K7), or infill framing line without a W-section
          const isExplicitJoist = m.kind === 'joist' ||
            /\d{1,2}(?:K|LH|DLH|KSP|G|CJ|CS)/.test(sectionStr) ||
            /\d{1,2}(?:K|LH|DLH|KSP|G|CJ|CS)/.test(piecemarkStr) ||
            sectionStr.includes('JOIST') || piecemarkStr.includes('JOIST')

          // Beam check: has a real hot-rolled profile (W, HSS, C, MC, L, PIPE)
          const isExplicitBeam = m.kind === 'beam' &&
            /^(W\d|HSS|C\d|MC\d|L\d|PIPE|ISA)/.test(sectionStr)

          const isJoist = isExplicitJoist || (!isExplicitBeam && m.kind !== 'column' && m.kind !== 'footing')

          // 2. Joist rendering — clean GREEN SVG line overlay across joist geometry, NO text label
          if (isJoist) {
            const JOIST_COLOR = '#10B981' // Vibrant Green
            const hasSpan = geo.bx1 !== undefined && geo.bx1 !== null && geo.bx2 !== undefined && geo.bx2 !== null
            if (!hasSpan) return null

            const strokeColor = isHovered ? '#22C55E' : (isSelected ? '#22C55E' : JOIST_COLOR)
            const strokeWidth = (isHovered ? 3.5 : 2.2) + strokeWidthModifier

            const clamp01 = (v: number) => Math.max(0, Math.min(1, v))
            const x1 = clamp01(geo.bx1!) * 100
            const y1 = clamp01(geo.by1!) * 100
            const x2 = clamp01(geo.bx2!) * 100
            const y2 = clamp01(geo.by2!) * 100

            return (
              <g
                key={m.id}
                onClick={(e) => { e.stopPropagation(); onMemberClick(m, e) }}
                onMouseEnter={() => onMemberHover(m.id)}
                onMouseLeave={() => onMemberHover(null)}
                style={{ pointerEvents: 'all', cursor: 'pointer', opacity }}
              >
                {/* Selection highlight line */}
                {isSelected && (
                  <line
                    x1={`${x1}%`} y1={`${y1}%`} x2={`${x2}%`} y2={`${y2}%`}
                    fill="none" stroke="#22C55E" strokeWidth={strokeWidth + 4}
                    style={{ opacity: 0.5, pointerEvents: 'none' }}
                  />
                )}
                {/* Clean joist line overlay on top of drawing in SOLID GREEN — NO text overlay */}
                <line
                  x1={`${x1}%`} y1={`${y1}%`} x2={`${x2}%`} y2={`${y2}%`}
                  fill="none"
                  stroke={strokeColor}
                  strokeWidth={strokeWidth}
                  strokeLinecap="round"
                  className={isZoomTarget ? 'pulsing-member' : ''}
                  style={{
                    transition: 'all 0.12s ease',
                    filter: filterStyle,
                    mixBlendMode: 'multiply',
                  }}
                />
              </g>
            )
          }

          // 3. Beam rendering — real hot-rolled structural beams in VIOLET with label & length
          if (isExplicitBeam || m.kind === 'beam') {
            const BEAM_COLOR = '#8B5CF6' // Violet / Purple straight solid line
            const hasSpan = geo.bx1 !== undefined && geo.bx1 !== null && geo.bx2 !== undefined && geo.bx2 !== null
            if (!hasSpan) return null

            const strokeColor = isHovered ? '#22C55E' : (isSelected ? '#22C55E' : BEAM_COLOR)
            const strokeWidthBase = isHovered ? 4 : 2
            const strokeWidth = strokeWidthBase + strokeWidthModifier
            const showText = layers.aids.labels !== false

            const clamp01 = (v: number) => Math.max(0, Math.min(1, v))
            const x1 = clamp01(geo.bx1!) * 100
            const y1 = clamp01(geo.by1!) * 100
            const x2 = clamp01(geo.bx2!) * 100
            const y2 = clamp01(geo.by2!) * 100

            return (
              <BeamLine
                key={m.id}
                member={m}
                x1={x1} y1={y1} x2={x2} y2={y2}
                strokeColor={strokeColor}
                markerColor={BEAM_COLOR}
                strokeWidth={strokeWidth}
                isSelected={isSelected}
                isHovered={isHovered}
                isZoomTarget={isZoomTarget}
                isUnlabeled={false}
                showHalo={showHalo}
                showText={showText}
                labelText={getLabelText(m)}
                filterStyle={filterStyle}
                opacity={opacity}
                onClick={(e) => { e.stopPropagation(); onMemberClick(m, e) }}
                onMouseEnter={() => onMemberHover(m.id)}
                onMouseLeave={() => onMemberHover(null)}
                onDragEnd={onMemberDragEnd}
                onEndpointDragEnd={onEndpointDragEnd}
                snapPoint={snapPoint}
              />
            )
          }

          // 4. Brace rendering
          const _c01 = (v: number | undefined | null) => Math.max(0, Math.min(1, v ?? 0))
          const bx = _c01(geo.x ?? m.x) * 100
          const by = _c01(geo.y ?? m.y) * 100
          const bgx1 = geo.bx1 !== undefined && geo.bx1 !== null ? _c01(geo.bx1) * 100 : null
          const bgy1 = geo.by1 !== undefined && geo.by1 !== null ? _c01(geo.by1) * 100 : null
          const bgx2 = geo.bx2 !== undefined && geo.bx2 !== null ? _c01(geo.bx2) * 100 : null
          const bgy2 = geo.by2 !== undefined && geo.by2 !== null ? _c01(geo.by2) * 100 : null
          const hasBraceLine = bgx1 !== null && bgy1 !== null && bgx2 !== null && bgy2 !== null

          const markerColor = isLowConf && layers.colorMode === 'kind' ? '#F59E0B' : color
          const strokeColor = isHovered ? '#22C55E' : markerColor
          const showText = (zoomLevel >= 2.5) || isHovered || isSelected || isZoomTarget

          return (
            <g
              key={m.id}
              onClick={(e) => { e.stopPropagation(); onMemberClick(m, e) }}
              onMouseEnter={() => onMemberHover(m.id)}
              onMouseLeave={() => onMemberHover(null)}
              style={{ pointerEvents: 'all', cursor: 'pointer', opacity }}
            >
              {/* Confidence Halo */}
              {showHalo && (
                <circle cx={`${bx}%`} cy={`${by}%`} r={8} fill="none" stroke="#F59E0B" strokeWidth={1.5} strokeDasharray="3,3" className="pulsing-halo" />
              )}

              {/* Selection highlight circle */}
              {isSelected && (
                <circle cx={`${bx}%`} cy={`${by}%`} r={isHovered ? 9 : 7} fill="none" stroke="#22C55E" strokeWidth={1.5} />
              )}

              {/* Diagonal brace line */}
              {hasBraceLine && (
                <line
                  x1={`${bgx1}%`} y1={`${bgy1}%`} x2={`${bgx2}%`} y2={`${bgy2}%`}
                  fill="none" stroke={strokeColor} strokeWidth={isHovered ? 3.0 : 1.8}
                  className={isZoomTarget ? 'pulsing-member' : ''}
                  style={{ transition: 'all 0.1s ease', filter: filterStyle }}
                />
              )}

              {/* Base Brace node marker */}
              <circle
                cx={`${bx}%`} cy={`${by}%`}
                r={isHovered ? 6 + strokeWidthModifier : 4 + strokeWidthModifier}
                fill={isHovered ? '#22C55E' : markerColor}
                stroke="#FFFFFF" strokeWidth={isHovered ? 1.5 : 1}
                className={isZoomTarget ? 'pulsing-member' : ''}
                style={{ transition: 'all 0.1s ease', filter: filterStyle }}
              />

              {/* Progressive Label */}
              {showText && getLabelText(m) && (() => {
                const labelText = isLowConf && layers.colorMode === 'kind' ? `⚠ ${getLabelText(m)}` : getLabelText(m)!
                const midX = hasBraceLine ? (bgx1! + bgx2!) / 2 : bx
                const midY = hasBraceLine ? (bgy1! + bgy2!) / 2 : by
                let angle = geo.angle_deg ?? (hasBraceLine ? (Math.atan2(bgy2! - bgy1!, bgx2! - bgx1!) * 180) / Math.PI : 0)
                if (angle > 90) angle -= 180
                if (angle < -90) angle += 180
                return (
                  <g>
                    {isHovered && (
                      <rect
                        x={`${midX}%`} y={`${midY - 2.5}%`}
                        width="8%" height="3%"
                        fill="#0F172A" rx="1" ry="1"
                        style={{
                          transformBox: 'fill-box', transformOrigin: 'center', transform: `translate(-4%, 0) rotate(${angle}deg)`, opacity: 0.85, pointerEvents: 'none'
                        }}
                      />
                    )}
                    <text
                      x={`${midX}%`}
                      y={`${midY - 1.4}%`}
                      fill={isHovered ? '#FFFFFF' : markerColor}
                      fontSize={isHovered ? "8px" : "7px"}
                      fontWeight="700"
                      textAnchor="middle"
                      style={{
                        userSelect: 'none', paintOrder: 'stroke', stroke: '#0B1220', strokeWidth: 2.2, pointerEvents: 'none',
                        transformBox: 'fill-box', transformOrigin: 'center', transform: `rotate(${angle}deg)`,
                      }}
                    >
                      {labelText}
                    </text>
                  </g>
                )
              })()}
            </g>
          )
        })}

        {/* 5. Grid-to-Grid Dimension Lines */}
        {layers.aids.gridDimensions !== false && store.gridDimensions && store.gridDimensions.map((dim: any) => (
          <DimensionLine key={dim.id} dimension={dim} />
        ))}
      </svg>
    </>
  )
}
