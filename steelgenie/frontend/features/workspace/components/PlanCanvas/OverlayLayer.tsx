import React from 'react'
import { useWorkspaceStore, getMemberRenderProps } from '../../../../lib/stores/workspaceStore'
import { ColumnSymbol } from './ColumnSymbol'

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
  onMemberDragEnd?: (id: string, x: number, y: number) => void
}

export function OverlayLayer({
  members,
  onMemberClick,
  hoveredMemberId,
  onMemberHover,
  onMemberDragEnd,
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

  return (
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
            />
          )
        }

        // 2. Beam rendering
        if (m.kind === 'beam') {
          const x1 = geo.bx1 !== undefined && geo.bx1 !== null ? geo.bx1 * 100 : geo.x * 100 - 3
          const y1 = geo.by1 !== undefined && geo.by1 !== null ? geo.by1 * 100 : geo.y * 100
          const x2 = geo.bx2 !== undefined && geo.bx2 !== null ? geo.bx2 * 100 : geo.x * 100 + 3
          const y2 = geo.by2 !== undefined && geo.by2 !== null ? geo.by2 * 100 : geo.y * 100

          return (
            <g
              key={m.id}
              onClick={(e) => {
                e.stopPropagation()
                onMemberClick(m, e)
              }}
              onMouseEnter={() => onMemberHover(m.id)}
              onMouseLeave={() => onMemberHover(null)}
              style={{ pointerEvents: 'all', cursor: 'pointer', opacity }}
            >
              {/* Invisible thick click-target helper */}
              <line
                x1={`${x1}%`}
                y1={`${y1}%`}
                x2={`${x2}%`}
                y2={`${y2}%`}
                fill="none"
                stroke="transparent"
                strokeWidth={16}
                style={{ cursor: 'pointer' }}
              />

              {/* Confidence Halo */}
              {showHalo && (
                <line
                  x1={`${x1}%`}
                  y1={`${y1}%`}
                  x2={`${x2}%`}
                  y2={`${y2}%`}
                  fill="none"
                  stroke="#F59E0B"
                  strokeWidth={6}
                  strokeDasharray="4,4"
                  className="pulsing-halo"
                  style={{ opacity: 0.8 }}
                />
              )}

              {/* Selection line indicator */}
              {isSelected && (
                <line
                  x1={`${x1}%`}
                  y1={`${y1}%`}
                  x2={`${x2}%`}
                  y2={`${y2}%`}
                  fill="none"
                  stroke="#22C55E"
                  strokeWidth={6}
                  style={{ opacity: 0.6 }}
                />
              )}

              {/* Base Beam line */}
              <line
                x1={`${x1}%`}
                y1={`${y1}%`}
                x2={`${x2}%`}
                y2={`${y2}%`}
                fill="none"
                stroke={isLowConf && layers.colorMode === 'kind' ? '#F59E0B' : color}
                strokeWidth={isHovered ? 3.5 + strokeWidthModifier : 2.0 + strokeWidthModifier}
                className={isZoomTarget ? 'pulsing-member' : ''}
                style={{
                  transition: 'all 0.1s ease',
                  filter: filterStyle,
                }}
              />
              {/* Label — plain text rotated along the beam, SteelGenie-style (no chip background) */}
              {(showChips || isHovered || isSelected || isZoomTarget) && getLabelText(m) && (() => {
                const labelText = isLowConf && layers.colorMode === 'kind' ? `⚠ ${getLabelText(m)}` : getLabelText(m)!
                const midX = (x1 + x2) / 2
                const midY = (y1 + y2) / 2
                // Prefer the backend-computed true angle; fall back to the on-screen
                // line angle (approximate — % space isn't square, but close enough
                // for near-horizontal/vertical members which dominate framing plans).
                let angle = geo.angle_deg ?? (Math.atan2(y2 - y1, x2 - x1) * 180) / Math.PI
                // Keep text upright/readable — never render upside-down.
                if (angle > 90) angle -= 180
                if (angle < -90) angle += 180
                const labelColor = isLowConf && layers.colorMode === 'kind' ? '#F59E0B' : color
                return (
                  <text
                    x={`${midX}%`}
                    y={`${midY - 1.1}%`}
                    fill={labelColor}
                    fontSize="7px"
                    fontWeight="700"
                    textAnchor="middle"
                    style={{
                      userSelect: 'none',
                      paintOrder: 'stroke',
                      stroke: '#0B1220',
                      strokeWidth: 2.2,
                      pointerEvents: 'none',
                      transformBox: 'fill-box',
                      transformOrigin: 'center',
                      transform: `rotate(${angle}deg)`,
                    }}
                  >
                    {labelText}
                  </text>
                )
              })()}
            </g>
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

        return (
          <g
            key={m.id}
            onClick={(e) => {
              e.stopPropagation()
              onMemberClick(m, e)
            }}
            onMouseEnter={() => onMemberHover(m.id)}
            onMouseLeave={() => onMemberHover(null)}
            style={{ pointerEvents: 'all', cursor: 'pointer', opacity }}
          >
            {/* Invisible thick click-target helper */}
            <circle
              cx={`${bx}%`}
              cy={`${by}%`}
              r={16}
              fill="transparent"
              style={{ cursor: 'pointer' }}
            />

            {/* Confidence Halo */}
            {showHalo && (
              <circle
                cx={`${bx}%`}
                cy={`${by}%`}
                r={isHovered ? 10 : 8}
                fill="none"
                stroke="#F59E0B"
                strokeWidth={1.5}
                strokeDasharray="3,3"
                className="pulsing-halo"
              />
            )}

            {/* Selection highlight circle */}
            {isSelected && (
              <circle
                cx={`${bx}%`}
                cy={`${by}%`}
                r={isHovered ? 9 : 7}
                fill="none"
                stroke="#22C55E"
                strokeWidth={1.5}
              />
            )}

            {/* Diagonal brace line, when true endpoint geometry is available */}
            {hasBraceLine && (
              <line
                x1={`${bgx1}%`}
                y1={`${bgy1}%`}
                x2={`${bgx2}%`}
                y2={`${bgy2}%`}
                fill="none"
                stroke={isLowConf && layers.colorMode === 'kind' ? '#F59E0B' : color}
                strokeWidth={isHovered ? 3.0 : 1.8}
                className={isZoomTarget ? 'pulsing-member' : ''}
                style={{ transition: 'all 0.1s ease', filter: filterStyle }}
              />
            )}

            {/* Base Brace node marker */}
            <circle
              cx={`${bx}%`}
              cy={`${by}%`}
              r={isHovered ? 6 + strokeWidthModifier : 4 + strokeWidthModifier}
              fill={isLowConf && layers.colorMode === 'kind' ? '#F59E0B' : color}
              stroke="#FFFFFF"
              strokeWidth={isHovered ? 1.5 : 1}
              className={isZoomTarget ? 'pulsing-member' : ''}
              style={{
                transition: 'all 0.1s ease',
                filter: filterStyle,
              }}
            />
            {/* Label — plain text, no chip background, SteelGenie-style */}
            {(showChips || isHovered || isSelected || isZoomTarget) && getLabelText(m) && (() => {
              const labelText = isLowConf && layers.colorMode === 'kind' ? `⚠ ${getLabelText(m)}` : getLabelText(m)!
              const labelColor = isLowConf && layers.colorMode === 'kind' ? '#F59E0B' : color
              const midX = hasBraceLine ? (bgx1! + bgx2!) / 2 : bx
              const midY = hasBraceLine ? (bgy1! + bgy2!) / 2 : by
              let angle = geo.angle_deg ?? (hasBraceLine ? (Math.atan2(bgy2! - bgy1!, bgx2! - bgx1!) * 180) / Math.PI : 0)
              if (angle > 90) angle -= 180
              if (angle < -90) angle += 180
              return (
                <text
                  x={`${midX}%`}
                  y={`${midY - 1.4}%`}
                  fill={labelColor}
                  fontSize="7px"
                  fontWeight="700"
                  textAnchor="middle"
                  style={{
                    userSelect: 'none',
                    paintOrder: 'stroke',
                    stroke: '#0B1220',
                    strokeWidth: 2.2,
                    pointerEvents: 'none',
                    transformBox: 'fill-box',
                    transformOrigin: 'center',
                    transform: `rotate(${angle}deg)`,
                  }}
                >
                  {labelText}
                </text>
              )
            })()}
          </g>
        )
      })}
    </svg>
  )
}
