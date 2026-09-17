import React, { useState } from 'react'

export interface GridDimension {
  id: string
  axis: 'V' | 'H' | 'SKEWED'
  from_grid: string
  to_grid: string
  label?: string
  length_ft: number
  text: string
  x1: number
  y1: number
  x2: number
  y2: number
  angle_deg?: number
  source?: string
  ocr_text?: string | null
  matched_scale?: string | null
  scale_source?: 'explicit' | 'guessed'
  flagged?: boolean
  side?: string
}

interface DimensionLineProps {
  dimension: GridDimension
  opacity?: number
}

export function DimensionLine({ dimension, opacity = 0.95 }: DimensionLineProps) {
  const [isHovered, setIsHovered] = useState(false)

  const x1 = dimension.x1 * 100
  const y1 = dimension.y1 * 100
  const x2 = dimension.x2 * 100
  const y2 = dimension.y2 * 100

  const midX = (x1 + x2) / 2
  const midY = (y1 + y2) / 2

  const dx = x2 - x1
  const dy = y2 - y1
  const spanPct = Math.hypot(dx, dy)
  const isTightBay = spanPct < 1.8

  const isSkewed = dimension.axis === 'SKEWED' || (Math.abs(dx) > 0.5 && Math.abs(dy) > 0.5)
  const isHorizontal = !isSkewed && dimension.axis === 'V' // Top/bottom horizontal line
  const isTotal = Boolean(dimension.id.includes('total') || dimension.label?.toUpperCase().includes('TOTAL'))

  // Calculate text rotation angle to follow line orientation
  let textAngle = 0
  if (isSkewed) {
    const rawAngle = Math.atan2(dy, dx) * (180 / Math.PI)
    textAngle = rawAngle
    // Keep text readable left-to-right (within [-90, 90])
    if (textAngle > 90) textAngle -= 180
    if (textAngle < -90) textAngle += 180
  } else if (!isHorizontal) {
    textAngle = 90
  }

  // Calculate badge text position with perpendicular offset from line
  let textX = midX
  let textY = midY
  if (isSkewed) {
    const rad = Math.atan2(dy, dx)
    const nx = -Math.sin(rad)
    const ny = Math.cos(rad)
    const offset = isTightBay ? 1.4 : 0.8
    textX = midX + nx * offset
    textY = midY + ny * offset
  } else if (isHorizontal) {
    textY = midY - (isTightBay ? 1.4 : 0.7)
  }

  // ── Match / Mismatch Color Coding ─────────────────────────────────────────
  const isMismatch = Boolean(dimension.flagged)

  const MATCH_COLOR = '#22C55E'      // Green -- agrees with estimator value
  const MATCH_HOVER = '#4ADE80'
  const MISMATCH_COLOR = '#EF4444'   // Red -- disagrees with estimator value
  const MISMATCH_HOVER = '#F87171'

  const DIM_COLOR = isMismatch ? MISMATCH_COLOR : MATCH_COLOR
  const HOVER_COLOR = isMismatch ? MISMATCH_HOVER : MATCH_HOVER

  const strokeColor = isHovered ? HOVER_COLOR : DIM_COLOR
  const strokeWidth = isHovered ? 3.5 : (isTotal ? 3.0 : 2.5)

  const gridTypeLabel = isTotal ? 'Total Overall Line' : (isSkewed ? 'Skewed Grid Line' : 'Grid Line')
  const matchLabel = isMismatch ? 'MISMATCH vs. estimator value' : 'Matches estimator value'

  return (
    <g
      style={{
        pointerEvents: 'all',
        cursor: 'pointer',
        opacity: isHovered ? 1.0 : opacity,
        transition: 'all 0.12s ease'
      }}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      {/* Title tooltip on hover for QA verification inspection */}
      <title>
        {`[${gridTypeLabel}] Grid ${dimension.label || `${dimension.from_grid}–${dimension.to_grid}`}: ${dimension.text} (${dimension.length_ft} ft) -- ${matchLabel}` +
         (dimension.ocr_text ? ` [OCR on sheet: "${dimension.ocr_text}"]` : '') +
         (dimension.matched_scale ? ` (Scale: ${dimension.matched_scale})` : '') +
         (dimension.scale_source === 'guessed' ? ' (Scale: Unverified default)' : '')}
      </title>

      {/* Invisible wider hit area for easy hover/interaction */}
      <line
        x1={`${x1}%`}
        y1={`${y1}%`}
        x2={`${x2}%`}
        y2={`${y2}%`}
        stroke="transparent"
        strokeWidth={16}
      />

      {/* Solid Grid-to-Grid Segment Line */}
      <line
        x1={`${x1}%`}
        y1={`${y1}%`}
        x2={`${x2}%`}
        y2={`${y2}%`}
        fill="none"
        stroke={strokeColor}
        strokeWidth={strokeWidth}
        strokeDasharray={isTotal ? 'none' : 'none'}
        strokeLinecap="round"
        style={{
          transition: 'all 0.12s ease',
        }}
      />

      {/* Grid Intersection Terminal Dots (shown on hover or for discrete bay inspection) */}
      {isHovered && (
        <>
          <circle
            cx={`${x1}%`}
            cy={`${y1}%`}
            r={4}
            fill="#FFFFFF"
            stroke={strokeColor}
            strokeWidth={2}
          />
          <circle
            cx={`${x2}%`}
            cy={`${y2}%`}
            r={4}
            fill="#FFFFFF"
            stroke={strokeColor}
            strokeWidth={2}
          />
        </>
      )}

      {/* Dimension Length Text Badge (matches beam length badge style) */}
      <g
        style={{
          transformBox: 'fill-box',
          transformOrigin: `${midX}% ${midY}%`,
          transform: textAngle === 0 ? 'none' : `rotate(${textAngle}deg)`,
        }}
      >
        <text
          x={`${textX}%`}
          y={`${textY}%`}
          fill={strokeColor}
          fontSize={isHovered ? "10px" : (isTightBay ? "7.5px" : (isTotal ? "9.5px" : "8.5px"))}
          fontWeight="800"
          fontFamily="'Inter', 'Segoe UI', system-ui, sans-serif"
          textAnchor="middle"
          dominantBaseline="central"
          style={{
            userSelect: 'none',
            letterSpacing: '0.02em',
            pointerEvents: 'none',
            paintOrder: 'stroke fill',
            stroke: '#FFFFFF',
            strokeWidth: isTightBay ? 2.5 : 3.0,
            strokeLinejoin: 'round',
            strokeLinecap: 'round',
          }}
        >
          {dimension.text}
        </text>
      </g>
    </g>
  )
}
