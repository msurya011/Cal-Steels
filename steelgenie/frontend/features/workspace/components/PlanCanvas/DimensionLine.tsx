import React, { useState } from 'react'

export interface GridDimension {
  id: string
  axis: 'V' | 'H'
  from_grid: string
  to_grid: string
  label?: string
  length_ft: number
  text: string
  x1: number
  y1: number
  x2: number
  y2: number
  source?: string
  ocr_text?: string | null
  scale_source?: 'explicit' | 'guessed'
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

  const isHorizontal = dimension.axis === 'V' // Top/bottom horizontal line
  const isTotal = Boolean(dimension.id.includes('total') || dimension.label?.toUpperCase().includes('TOTAL'))
  const isSubGrid = Boolean(
    !isTotal && (
      (dimension.from_grid && dimension.from_grid.includes('.')) ||
      (dimension.to_grid && dimension.to_grid.includes('.'))
    )
  )

  // ── 3 Distinct Color Schemes per User Requirement ──────────────────────────
  // 1. Total Overall Building Lines -> Vibrant Amber / Gold (#F59E0B)
  // 2. Sub-Grid Lines (A.5, B.3, 1.9, 8.4) -> Electric Cyan (#06B6D4)
  // 3. Primary Grid Lines (A, B, C, 1, 2, 3) -> Vibrant Hot Pink (#EC4899)
  let DIM_COLOR = '#EC4899' // Primary Grids (Pink)
  let HOVER_COLOR = '#F472B6'

  if (isTotal) {
    DIM_COLOR = '#F59E0B' // Total Building Lines (Amber/Gold)
    HOVER_COLOR = '#FBBF24'
  } else if (isSubGrid) {
    DIM_COLOR = '#06B6D4' // Sub-Grids (Electric Cyan)
    HOVER_COLOR = '#38BDF8'
  }

  const strokeColor = isHovered ? HOVER_COLOR : DIM_COLOR
  const strokeWidth = isHovered ? 3.5 : (isTotal ? 3.0 : 2.5)

  // Calculate physical screen span to handle tight bays (e.g. 1.9-2, B.2-B.3)
  const spanPct = isHorizontal ? Math.abs(x2 - x1) : Math.abs(y2 - y1)
  const isTightBay = spanPct < 1.8

  const gridTypeLabel = isTotal ? 'Total Overall Line' : (isSubGrid ? 'Sub-Grid Line' : 'Primary Grid Line')

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
        {`[${gridTypeLabel}] Grid ${dimension.label || `${dimension.from_grid}–${dimension.to_grid}`}: ${dimension.text} (${dimension.length_ft} ft)` +
         (dimension.ocr_text ? ` [OCR on sheet: "${dimension.ocr_text}"]` : '') +
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
          transform: isHorizontal ? 'none' : `rotate(90deg)`,
        }}
      >
        <text
          x={`${midX}%`}
          y={isHorizontal ? `${midY - (isTightBay ? 1.4 : 0.7)}%` : `${midY}%`}
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
