import React from 'react'
import { useWorkspaceStore, getMemberRenderProps } from '../../../../lib/stores/workspaceStore'
import { ColumnSymbol } from './ColumnSymbol'
import { BeamLine } from './BeamLine'

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
    if (layers.aids.labels === false) return null

    const parts: string[] = []

    // 1. Piecemarks
    if (layers.aids.piecemarks !== false) {
      parts.push(m.piecemark || m.section || '')
    }

    // 2. Lengths
    if (layers.aids.lengths === true && m.length_ft) {
      parts.push(`${m.length_ft.toFixed(1)}'`)
    }

    // 3. Reactions
    if (layers.aids.reactions === true && m.reaction) {
      parts.push(m.reaction)
    }

    if (parts.length === 0 && layers.aids.labels) {
      return m.section || ''
    }

    return parts.filter(Boolean).join(' - ')
  }

  // Freshly extracted members were silently invisible with zero on-screen
  // indication of why (only a console.warn nobody ever sees): a
  // classVisibility/isolation filter left over from a PREVIOUS session gets
  // restored from localStorage on load and applies to every page, including
  // ones just extracted. The extraction itself was working fine -- the plan
  // just looked "broken" because 100% of the new members matched an old
  // hidden-layer filter. Compute that state for real (not just log it) so a
  // visible fix can be offered instead of a silent, undiscoverable failure.
  const visibleMembers = members.filter(m => getMemberRenderProps({ layers, hiddenIds, isolation }, m).visible)
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
        {[...members].sort((a, b) => (a.kind === 'column' ? 1 : 0) - (b.kind === 'column' ? 1 : 0)).map((m) => {
        const renderProps = getMemberRenderProps({ layers, hiddenIds, isolation }, m)
        if (!renderProps.visible) return null

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

        // 2. Beam rendering
        if (m.kind === 'beam') {
          // Red = "needs a profile assigned" on every extraction, unconditionally --
          // not gated by the "Unlabelled" detect-more-candidates checkbox. That
          // checkbox only controls whether the backend goes looking for EXTRA
          // beam-shaped lines with no section callout at all (geo.unlabeled).
          // A beam can also lack a section simply because OCR/registration
          // didn't confidently match a callout to it -- those must be red too,
          // by default, with no toggle required.
          const isUnlabeled = !!(geo as any).unlabeled || !m.section
          // Verified live against app.steelgenie.com (Page 31, zoomed to plan
          // density): normal/labeled beams render violet/purple there, with
          // red reserved specifically for flagged/unlabeled members -- the
          // opposite of what this file had. Matches the 3D viewer's already
          // -confirmed lavender/red scheme too.
          const LABELED_BEAM_COLOR = '#8B5CF6' // Violet/purple for labeled beams, like SteelGenie
          const UNLABELED_BEAM_COLOR = '#EF4444' // Red for unlabeled/flagged

          const hasSpan = geo.bx1 !== undefined && geo.bx1 !== null && geo.bx2 !== undefined && geo.bx2 !== null
          const markerColor = isUnlabeled ? UNLABELED_BEAM_COLOR : (isLowConf && layers.colorMode === 'kind' ? '#F59E0B' : LABELED_BEAM_COLOR)
          
          // Hover highlight -- verified live against app.steelgenie.com: hovering
          // a beam there highlights it bright green, not cyan.
          const strokeColor = isHovered ? '#22C55E' : markerColor
          const strokeWidthBase = isHovered ? 4 : 2
          const strokeWidth = strokeWidthBase + strokeWidthModifier
          
          // Progressive disclosure: only show full text if zoomed in significantly, or hovered/selected
          const showText = (zoomLevel >= 2.5) || isHovered || isSelected || isZoomTarget

          if (!hasSpan) {
            const px = geo.x * 100
            const py = geo.y * 100
            const labelText = getLabelText(m)
            return (
              <g
                key={m.id}
                onClick={(e) => { e.stopPropagation(); onMemberClick(m, e) }}
                onMouseEnter={() => onMemberHover(m.id)}
                onMouseLeave={() => onMemberHover(null)}
                style={{ pointerEvents: 'all', cursor: 'pointer', opacity }}
              >
                <circle
                  cx={`${px}%`}
                  cy={`${py}%`}
                  r={isHovered ? 5 : 3.5}
                  fill={isHovered ? '#22C55E' : 'none'}
                  stroke={strokeColor}
                  strokeWidth={1.4}
                  strokeDasharray={isUnlabeled ? "2,2" : "none"}
                  style={{ transition: 'all 0.15s ease', filter: filterStyle }}
                />
                {showText && labelText && !isUnlabeled && (
                  <text
                    x={`${px}%`}
                    y={`${py - 1.6}%`}
                    fill={strokeColor}
                    fontSize="6.5px"
                    fontWeight="600"
                    textAnchor="middle"
                    style={{
                      userSelect: 'none', paintOrder: 'stroke', stroke: '#0B1220', strokeWidth: 2, pointerEvents: 'none'
                    }}
                  >
                    {labelText}
                  </text>
                )}
              </g>
            )
          }

          const x1 = geo.bx1! * 100
          const y1 = geo.by1! * 100
          const x2 = geo.bx2! * 100
          const y2 = geo.by2! * 100

          return (
            <BeamLine
              key={m.id}
              member={m}
              x1={x1} y1={y1} x2={x2} y2={y2}
              strokeColor={strokeColor}
              markerColor={markerColor}
              strokeWidth={strokeWidth}
              isSelected={isSelected}
              isHovered={isHovered}
              isZoomTarget={isZoomTarget}
              isUnlabeled={isUnlabeled}
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

        // 3. Brace rendering
        const bx = geo.x * 100
        const by = geo.y * 100
        const bgx1 = geo.bx1 !== undefined && geo.bx1 !== null ? geo.bx1 * 100 : null
        const bgy1 = geo.by1 !== undefined && geo.by1 !== null ? geo.by1 * 100 : null
        const bgx2 = geo.bx2 !== undefined && geo.bx2 !== null ? geo.bx2 * 100 : null
        const bgy2 = geo.by2 !== undefined && geo.by2 !== null ? geo.by2 * 100 : null
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
      </svg>
    </>
  )
}
