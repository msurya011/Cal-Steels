import React from 'react'
import { useWorkspaceStore, getMemberRenderProps } from '../../../../lib/stores/workspaceStore'

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
}

interface OverlayLayerProps {
  members: Member[]
  onMemberClick: (member: Member, e: React.MouseEvent) => void
  hoveredMemberId: string | null
  onMemberHover: (id: string | null) => void
}

export function OverlayLayer({
  members,
  onMemberClick,
  hoveredMemberId,
  onMemberHover,
}: OverlayLayerProps) {
  const store = useWorkspaceStore()
  const { layers, selection, hiddenIds, isolation, zoomTarget } = store

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
        @keyframes pulse-halo {
          0% { opacity: 0.2; }
          50% { opacity: 0.55; }
          100% { opacity: 0.2; }
        }
        .pulse-halo-animation {
          animation: pulse-halo 1.5s infinite ease-in-out;
        }
      `}</style>

      {members.map((m) => {
        const geo = m.geometry

        // Check markers aid visibility
        if (m.source === 'manual' && !layers.aids.markers) {
          return null
        }

        // Get visibility, color and opacity from centralized selector
        const { visible, color, opacity } = getMemberRenderProps({ layers, hiddenIds, isolation }, m)
        if (!visible) return null

        const isHovered = hoveredMemberId === m.id
        const isSelected = selection.has(m.id)
        const isZoomTarget = zoomTarget && zoomTarget.id === m.id
        const isLowConf = m.confidence !== undefined && m.confidence !== null && m.confidence < 0.70
        const showHalo = layers.aids.confidenceHalo && isLowConf

        let filterStyle = undefined
        const isDimmed = opacity < 0.5 && !isSelected
        if (isDimmed) {
          filterStyle = 'grayscale(100%)'
        } else if (isSelected || isZoomTarget) {
          filterStyle = `drop-shadow(0 0 4px ${isZoomTarget ? '#F59E0B' : '#3B82F6'})`
        }

        const strokeWidthModifier = isSelected ? 1.5 : 0

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
              {/* Confidence Halo */}
              {showHalo && (
                <rect
                  x={`${cx - (w + 0.8) / 2}%`}
                  y={`${cy - (h + 0.8) / 2}%`}
                  width={`${w + 0.8}%`}
                  height={`${h + 0.8}%`}
                  fill="none"
                  stroke="#F59E0B"
                  strokeWidth={4}
                  className="pulse-halo-animation"
                  style={{ filter: 'blur(1px)' }}
                />
              )}
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
                stroke={isLowConf && layers.colorMode === 'kind' ? '#F59E0B' : color}
                strokeWidth={isHovered ? 2.5 + strokeWidthModifier : 1.5 + strokeWidthModifier}
                className={isZoomTarget ? 'pulsing-member' : ''}
                style={{
                  transition: 'all 0.1s ease',
                  filter: filterStyle,
                }}
              />
              {/* Text label */}
              {layers.aids.labels && m.section && (
                <text
                  x={`${cx}%`}
                  y={`${cy - h / 2 - 1}%`}
                  fill={isLowConf && layers.colorMode === 'kind' ? '#F59E0B' : '#F1F5F9'}
                  fontSize="9px"
                  fontWeight="bold"
                  textAnchor="middle"
                  style={{ userSelect: 'none', paintOrder: 'stroke', stroke: '#090D1A', strokeWidth: 2 }}
                >
                  {isLowConf && layers.colorMode === 'kind' ? `⚠️ ${m.section}` : m.section}
                </text>
              )}
            </g>
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
              style={{ pointerEvents: 'auto', cursor: 'pointer', opacity }}
              onClick={(e) => onMemberClick(m, e)}
              onMouseEnter={() => onMemberHover(m.id)}
              onMouseLeave={() => onMemberHover(null)}
            >
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
                  className="pulse-halo-animation"
                  style={{ filter: 'blur(1px)' }}
                />
              )}
              {/* Thick interactive buffer path */}
              <line
                x1={`${x1}%`}
                y1={`${y1}%`}
                x2={`${x2}%`}
                y2={`${y2}%`}
                fill="none"
                stroke="transparent"
                strokeWidth={14}
              />
              {/* Selection background line */}
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
                stroke={isLowConf && layers.colorMode === 'kind' ? '#F59E0B' : color}
                strokeWidth={isHovered ? 3.5 + strokeWidthModifier : 2.0 + strokeWidthModifier}
                className={isZoomTarget ? 'pulsing-member' : ''}
                style={{
                  transition: 'all 0.1s ease',
                  filter: filterStyle,
                }}
              />
              {/* Label */}
              {layers.aids.labels && m.section && (
                <text
                  x={`${(x1 + x2) / 2}%`}
                  y={`${(y1 + y2) / 2 - 1.5}%`}
                  fill={isLowConf && layers.colorMode === 'kind' ? '#F59E0B' : (layers.colorMode === 'kind' ? '#EC4899' : color)}
                  fontSize="9px"
                  fontWeight="bold"
                  textAnchor="middle"
                  style={{ userSelect: 'none', paintOrder: 'stroke', stroke: '#090D1A', strokeWidth: 2 }}
                >
                  {isLowConf && layers.colorMode === 'kind' ? `⚠️ ${m.section}` : m.section}
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
            {/* Confidence Halo */}
            {showHalo && (
              <circle
                cx={`${bx}%`}
                cy={`${by}%`}
                r={10}
                fill="none"
                stroke="#F59E0B"
                strokeWidth={4}
                className="pulse-halo-animation"
                style={{ filter: 'blur(1px)' }}
              />
            )}
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
              fill={isLowConf && layers.colorMode === 'kind' ? '#F59E0B' : color}
              stroke="#FFFFFF"
              strokeWidth={isHovered ? 1.5 : 1}
              className={isZoomTarget ? 'pulsing-member' : ''}
              style={{
                transition: 'all 0.1s ease',
                filter: filterStyle,
              }}
            />
            {layers.aids.labels && m.section && (
              <text
                x={`${bx}%`}
                y={`${by - 6}%`}
                fill={isLowConf && layers.colorMode === 'kind' ? '#F59E0B' : (layers.colorMode === 'kind' ? '#F59E0B' : color)}
                fontSize="9px"
                fontWeight="bold"
                textAnchor="middle"
                style={{ userSelect: 'none', paintOrder: 'stroke', stroke: '#090D1A', strokeWidth: 2 }}
              >
                {isLowConf && layers.colorMode === 'kind' ? `⚠️ ${m.section}` : m.section}
              </text>
            )}
          </g>
        )
      })}
    </svg>
  )
}
