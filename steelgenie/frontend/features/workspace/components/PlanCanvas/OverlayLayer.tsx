import React from 'react'

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
}

interface OverlayLayerProps {
  members: Member[]
  onMemberClick: (member: Member, e: React.MouseEvent) => void
  hoveredMemberId: string | null
  onMemberHover: (id: string | null) => void
  selection?: Set<string>
  hiddenKinds?: Set<string>
  hiddenIds?: Set<string>
  isolation?: { kind?: string; ids?: Set<string> } | null
  colorMode?: 'kind' | 'status' | 'confidence'
  zoomTarget?: { id: string; nonce: number } | null
}

const isMatchKind = (mKind: string, targetKind: string) => {
  if (mKind === targetKind) return true
  if (targetKind === 'vbrace' && (mKind === 'vbrace' || mKind === 'hbrace' || mKind === 'brace')) return true
  return false
}

export function OverlayLayer({
  members,
  onMemberClick,
  hoveredMemberId,
  onMemberHover,
  selection = new Set(),
  hiddenKinds = new Set(),
  hiddenIds = new Set(),
  isolation = null,
  colorMode = 'kind',
  zoomTarget = null,
}: OverlayLayerProps) {

  const isIsolated = !!isolation
  const isolatedKind = isolation?.kind
  const isolatedIds = isolation?.ids

  const getMemberColor = (m: Member) => {
    // If category isolation is enabled and this member is the isolated category, force green!
    if (isolatedKind && isMatchKind(m.kind, isolatedKind)) {
      return '#10B981' // Green
    }
    if (colorMode === 'status') {
      if (m.status === 'verified') return '#10B981' // green
      if (m.status === 'rejected') return '#EF4444' // red
      if (m.status === 'need_review') return '#F59E0B' // orange
      return '#64748B' // gray
    }
    if (colorMode === 'confidence') {
      const conf = m.confidence ?? 0
      if (conf >= 0.9) return '#10B981'
      if (conf >= 0.7) return '#3B82F6'
      if (conf >= 0.5) return '#F59E0B'
      return '#EF4444'
    }
    
    // Default: color by kind
    if (m.kind === 'column') return '#3B82F6' // Blue
    if (m.kind === 'beam') return '#EC4899'   // Pink
    if (m.kind === 'vbrace' || m.kind === 'hbrace' || m.kind === 'brace') return '#F59E0B' // Orange
    return '#10B981' // Green
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
      <style>{`
        @keyframes pulse-highlight {
          0% { filter: drop-shadow(0 0 2px #3B82F6); stroke-width: 3.5px; }
          50% { filter: drop-shadow(0 0 10px #3B82F6); stroke-width: 6.5px; }
          100% { filter: drop-shadow(0 0 2px #3B82F6); stroke-width: 3.5px; }
        }
        .pulsing-member {
          animation: pulse-highlight 0.8s ease-in-out 3;
        }
      `}</style>

      {members.map((m) => {
        const geo = m.geometry
        const isHidden = hiddenKinds.has(m.kind) || hiddenIds.has(m.id)
        if (isHidden) return null

        // If category isolation is enabled, hide all other categories completely
        const isTargetKind = isolatedKind ? isMatchKind(m.kind, isolatedKind) : false
        if (isolatedKind && !isTargetKind) {
          return null
        }

        // Determine if isolated / dimmed
        const isTarget =
          !isIsolated ||
          (isolatedKind && isTargetKind) ||
          (isolatedIds && isolatedIds.has(m.id))
        const isDimmed = isIsolated && !isTarget

        const color = getMemberColor(m)
        const isHovered = hoveredMemberId === m.id
        const isSelected = selection.has(m.id)
        const isZoomTarget = zoomTarget && zoomTarget.id === m.id

        // Render styles
        const opacity = isDimmed ? 0.15 : 1.0
        const strokeWidthModifier = isSelected ? 1.5 : 0
        const isLowConf = m.confidence !== undefined && m.confidence !== null && m.confidence < 0.70
        
        let filterStyle = undefined
        if (isDimmed) {
          filterStyle = 'grayscale(100%)'
        } else if (isSelected || isZoomTarget) {
          filterStyle = `drop-shadow(0 0 4px ${isZoomTarget ? '#F59E0B' : '#3B82F6'})`
        }

        // 1. Column rendering
        if (m.kind === 'column') {
          const cx = geo.x * 100
          const cy = geo.y * 100
          const w = (geo.w || 0.01) * 100
          const h = (geo.h || 0.01) * 100

          return (
            <g
              key={m.id}
              style={{ pointerEvents: 'auto', cursor: 'pointer', opacity }}
              onClick={(e) => onMemberClick(m, e)}
              onMouseEnter={() => onMemberHover(m.id)}
              onMouseLeave={() => onMemberHover(null)}
            >
              {isSelected && (
                <rect
                  x={`${cx - (w + 0.4) / 2}%`}
                  y={`${cy - (h + 0.4) / 2}%`}
                  width={`${w + 0.4}%`}
                  height={`${h + 0.4}%`}
                  fill="none"
                  stroke="#FFFFFF"
                  strokeWidth={1}
                />
              )}
              <rect
                x={`${cx - w / 2}%`}
                y={`${cy - h / 2}%`}
                width={`${w}%`}
                height={`${h}%`}
                fill={isHovered ? 'rgba(59, 130, 246, 0.4)' : 'rgba(59, 130, 246, 0.2)'}
                stroke={isLowConf && colorMode === 'kind' ? '#F59E0B' : color}
                strokeWidth={isHovered ? 2.5 + strokeWidthModifier : 1.5 + strokeWidthModifier}
                className={isZoomTarget ? 'pulsing-member' : ''}
                style={{
                  transition: 'all 0.1s ease',
                  filter: filterStyle,
                }}
              />
              {/* Text label */}
              {m.section && (
                <text
                  x={`${cx}%`}
                  y={`${cy - h / 2 - 1}%`}
                  fill={isLowConf && colorMode === 'kind' ? '#F59E0B' : '#F1F5F9'}
                  fontSize="9px"
                  fontWeight="bold"
                  textAnchor="middle"
                  style={{ userSelect: 'none', paintOrder: 'stroke', stroke: '#090D1A', strokeWidth: 2 }}
                >
                  {isLowConf && colorMode === 'kind' ? `⚠️ ${m.section}` : m.section}
                </text>
              )}
            </g>
          )
        }

        // 2. Beam rendering (using span line endpoint percentages)
        if (m.kind === 'beam') {
          const x1 = geo.bx1 !== undefined && geo.bx1 !== null ? geo.bx1 * 100 : geo.x * 100 - 3
          const y1 = geo.by1 !== undefined && geo.by1 !== null ? geo.by1 * 100 : geo.y * 100
          const x2 = geo.bx2 !== undefined && geo.bx2 !== null ? geo.bx2 * 100 : geo.x * 100 + 3
          const y2 = geo.by2 !== undefined && geo.by2 !== null ? geo.by2 * 100 : geo.y * 100

          return (
            <g
              key={m.id}
              style={{ pointerEvents: 'auto', cursor: 'pointer', opacity }}
              onClick={(e) => onMemberClick(m, e)}
              onMouseEnter={() => onMemberHover(m.id)}
              onMouseLeave={() => onMemberHover(null)}
            >
              {/* Thick transparent interactive buffer path */}
              <line
                x1={`${x1}%`}
                y1={`${y1}%`}
                x2={`${x2}%`}
                y2={`${y2}%`}
                fill="none"
                stroke="transparent"
                strokeWidth={14}
              />
              {/* White background border line for selected state */}
              {isSelected && (
                <line
                  x1={`${x1}%`}
                  y1={`${y1}%`}
                  x2={`${x2}%`}
                  y2={`${y2}%`}
                  fill="none"
                  stroke="#FFFFFF"
                  strokeWidth={4.5}
                />
              )}
              {/* Solid visible overlay line */}
              <line
                x1={`${x1}%`}
                y1={`${y1}%`}
                x2={`${x2}%`}
                y2={`${y2}%`}
                fill="none"
                stroke={isLowConf && colorMode === 'kind' ? '#F59E0B' : color}
                strokeWidth={isHovered ? 3.5 + strokeWidthModifier : 2.0 + strokeWidthModifier}
                className={isZoomTarget ? 'pulsing-member' : ''}
                style={{
                  transition: 'all 0.1s ease',
                  filter: filterStyle,
                }}
              />
              {/* Label */}
              {m.section && (
                <text
                  x={`${(x1 + x2) / 2}%`}
                  y={`${(y1 + y2) / 2 - 1.5}%`}
                  fill={isLowConf && colorMode === 'kind' ? '#F59E0B' : (colorMode === 'kind' ? '#EC4899' : color)}
                  fontSize="9px"
                  fontWeight="bold"
                  textAnchor="middle"
                  style={{ userSelect: 'none', paintOrder: 'stroke', stroke: '#090D1A', strokeWidth: 2 }}
                >
                  {isLowConf && colorMode === 'kind' ? `⚠️ ${m.section}` : m.section}
                </text>
              )}
            </g>
          )
        }

        // 3. Brace / Joist / Default rendering
        const bx = geo.x * 100
        const by = geo.y * 100
        return (
          <g
            key={m.id}
            style={{ pointerEvents: 'auto', cursor: 'pointer', opacity }}
            onClick={(e) => onMemberClick(m, e)}
            onMouseEnter={() => onMemberHover(m.id)}
            onMouseLeave={() => onMemberHover(null)}
          >
            {isSelected && (
              <circle
                cx={`${bx}%`}
                cy={`${by}%`}
                r={isHovered ? 8 : 6}
                fill="none"
                stroke="#FFFFFF"
                strokeWidth={1}
              />
            )}
            <circle
              cx={`${bx}%`}
              cy={`${by}%`}
              r={isHovered ? 6 + strokeWidthModifier : 4 + strokeWidthModifier}
              fill={isLowConf && colorMode === 'kind' ? '#F59E0B' : color}
              stroke="#FFFFFF"
              strokeWidth={isHovered ? 1.5 : 1}
              className={isZoomTarget ? 'pulsing-member' : ''}
              style={{
                transition: 'all 0.1s ease',
                filter: filterStyle,
              }}
            />
            {m.section && (
              <text
                x={`${bx}%`}
                y={`${by - 6}%`}
                fill={isLowConf && colorMode === 'kind' ? '#F59E0B' : (colorMode === 'kind' ? '#F59E0B' : color)}
                fontSize="9px"
                fontWeight="bold"
                textAnchor="middle"
                style={{ userSelect: 'none', paintOrder: 'stroke', stroke: '#090D1A', strokeWidth: 2 }}
              >
                {isLowConf && colorMode === 'kind' ? `⚠️ ${m.section}` : m.section}
              </text>
            )}
          </g>
        )
      })}
    </svg>
  )
}
