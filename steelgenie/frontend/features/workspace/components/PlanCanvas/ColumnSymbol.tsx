import React, { useRef } from 'react'
import { useWorkspaceStore } from '../../../../lib/stores/workspaceStore'

export interface ColumnSymbolProps {
  member: any
  renderProps: { visible: boolean; color: string; opacity: number }
  layers: any
  isSelected: boolean
  isHovered: boolean
  isZoomTarget: boolean
  isLowConf: boolean
  getLabelText: (m: any) => string | null
  onClick: (e: React.MouseEvent) => void
  onMouseEnter: () => void
  onMouseLeave: () => void
  onDragEnd?: (id: string, x: number, y: number) => void
}

export function ColumnSymbol({
  member: m,
  renderProps,
  layers,
  isSelected,
  isHovered,
  isZoomTarget,
  isLowConf,
  getLabelText,
  onClick,
  onMouseEnter,
  onMouseLeave,
  onDragEnd
}: ColumnSymbolProps) {
  const { color, opacity } = renderProps
  const geo = m.geometry
  const flags: string[] = geo.error_flags || []
  const isSuggested = Boolean(geo.suggested)
  const hasError = flags.some((f: string) => f !== 'suggested')
  const isVerified = m.status === 'verified'
  const filterStyle = isSelected || isZoomTarget ? 'url(#glow-select)' : undefined

  // Position in percent (0-100)
  const cx = geo.x * 100
  const cy = geo.y * 100

  // Drag logic
  const groupRef = useRef<SVGGElement>(null)
  
  const handlePointerDown = (e: React.PointerEvent) => {
    if (!onDragEnd || isSuggested) return
    e.stopPropagation()
    const svg = groupRef.current?.ownerSVGElement
    if (!svg) return
    
    // We want pointer capture to track mouse reliably
    ;(e.target as Element).setPointerCapture(e.pointerId)

    let currentX = cx
    let currentY = cy

    const handlePointerMove = (ev: PointerEvent) => {
      const pt = svg.createSVGPoint()
      pt.x = ev.clientX
      pt.y = ev.clientY
      const ctm = svg.getScreenCTM()
      if (ctm) {
        const svgPt = pt.matrixTransform(ctm.inverse())
        if (groupRef.current) {
          const dx = svgPt.x - cx
          const dy = svgPt.y - cy
          groupRef.current.setAttribute('transform', `translate(${dx}, ${dy})`)
          currentX = svgPt.x
          currentY = svgPt.y
        }
      }
    }

    const handlePointerUp = (ev: PointerEvent) => {
      ;(ev.target as Element)?.releasePointerCapture(ev.pointerId)
      window.removeEventListener('pointermove', handlePointerMove)
      window.removeEventListener('pointerup', handlePointerUp)
      if (groupRef.current) {
        groupRef.current.removeAttribute('transform')
      }
      if (Math.abs(currentX - cx) > 0.1 || Math.abs(currentY - cy) > 0.1) {
        onDragEnd(m.id, currentX / 100, currentY / 100)
      } else {
        // If we didn't drag far enough, treat as a click
        onClick(e as any)
      }
    }

    window.addEventListener('pointermove', handlePointerMove)
    window.addEventListener('pointerup', handlePointerUp)
  }

  const { selectedRatio, imageNaturalWidth } = useWorkspaceStore()

  // Symbol sizing based on true physical depth and scale ratio
  const depthIn = geo.depth_in ?? 10
  let sPct = 1.0
  if (selectedRatio && imageNaturalWidth) {
    // 150 DPI rendering: physical pixels for the given column depth
    const sizePx = (depthIn * 150) / selectedRatio
    // Clamp the pixel size for readability (min 12px, max 45px)
    const clampedPx = Math.max(12, Math.min(45, sizePx))
    sPct = (clampedPx / imageNaturalWidth) * 100
  } else {
    // Fallback if no scale is set on the page yet
    sPct = Math.min(2.0, Math.max(0.5, (geo.w ? geo.w * 100 : 0) || 1.0))
  }
  const s = sPct
  const ft = s * 0.22 
  const symbol = geo.symbol || 'I'

  let stroke = color
  let dash: string | undefined
  if (layers.colorMode === 'kind') {
    if (isSuggested) { stroke = '#94A3B8'; dash = '3,3' }
    else if (hasError) { stroke = '#EF4444'; dash = '4,3' }
    else if (isVerified) { stroke = '#10B981' }
    else if (isLowConf || m.status === 'need_review') { stroke = '#F59E0B'; dash = '4,3' }
  }
  const sw = (isHovered ? 3.0 : 2.0) + (isSelected ? 1.5 : 0)
  // Use transparent instead of none so pointer events are still captured
  const fillCol = 'transparent'

  // Base case (rotation 0 = horizontal web, vertical flanges)
  const f1 = { x: cx - s / 2, y: cy - s / 2, w: ft, h: s }
  const f2 = { x: cx + s / 2 - ft, y: cy - s / 2, w: ft, h: s }
  const web = { x: cx - s / 2 + ft, y: cy - ft / 2, w: s - 2 * ft, h: ft }

  const rectEl = (r: { x: number; y: number; w: number; h: number }, key: string, isSolid: boolean = false) => (
    <rect
      key={key}
      x={`${r.x}%`} y={`${r.y}%`} width={`${r.w}%`} height={`${r.h}%`}
      fill={isSolid ? stroke : fillCol}
      stroke={isSolid ? 'none' : stroke}
      strokeWidth={isSolid ? 0 : sw}
      strokeDasharray={isSolid ? undefined : dash}
      strokeLinejoin="round"
      className={isZoomTarget ? 'pulsing-member' : ''}
      style={{ transition: 'all 0.1s ease', filter: filterStyle }}
    />
  )

  const labelText = isSuggested ? 'Column?' : getLabelText(m)
  
  // Diagonal pointer line
  const labelDist = s + 1.5
  const labelX = cx + labelDist
  const labelY = cy - labelDist
  
  return (
    <g
      ref={groupRef}
      onPointerDown={handlePointerDown}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      style={{ pointerEvents: 'all', cursor: isSuggested ? 'pointer' : 'grab', opacity: isSuggested ? opacity * 0.65 : opacity, touchAction: 'none' }}
    >
      {/* Confidence Halo */}
      {layers.aids.confidenceHalo && isLowConf && !isSuggested && (
        <rect
          x={`${cx - s / 2 - 0.6}%`} y={`${cy - s / 2 - 0.6}%`}
          width={`${s + 1.2}%`} height={`${s + 1.2}%`}
          fill="none" stroke="#F59E0B" strokeWidth={2} strokeDasharray="4,4"
          className="pulsing-halo"
        />
      )}

      {/* Suggested ghost ring */}
      {isSuggested && (
        <circle
          cx={`${cx}%`} cy={`${cy}%`} r={isHovered ? 14 : 12}
          fill="none" stroke="#94A3B8" strokeWidth={1.5} strokeDasharray="4,4"
          className="pulsing-halo"
        />
      )}

      {/* Selection border */}
      {isSelected && (
        <rect
          x={`${cx - s / 2 - 0.5}%`} y={`${cy - s / 2 - 0.5}%`}
          width={`${s + 1}%`} height={`${s + 1}%`}
          fill="none" stroke="#3B82F6" strokeWidth={2}
        />
      )}

      {/* Steel symbol with precise rotation */}
      <g style={{ transformOrigin: 'center', transformBox: 'fill-box', transform: `rotate(${m.rotation || 0}deg)` }}>
        {symbol === 'BOX' ? (
          rectEl({ x: cx - s / 2, y: cy - s / 2, w: s, h: s }, 'box')
        ) : symbol === 'PIPE' ? (
          <circle
            cx={`${cx}%`} cy={`${cy}%`} r={s / 2}
            fill={fillCol} stroke={stroke} strokeWidth={sw} strokeDasharray={dash}
            className={isZoomTarget ? 'pulsing-member' : ''}
            style={{ transition: 'all 0.1s ease', filter: filterStyle }}
          />
        ) : (
          <>
            {rectEl(f1, 'f1', true)}
            {rectEl(f2, 'f2', true)}
            {rectEl(web, 'web', true)}
          </>
        )}
      </g>

      {/* Matched Profile Section Link Icon */}
      {isSelected && m.section && (
        <text
          x={`${cx - s / 2 - 1}%`}
          y={`${cy + s / 2 + 1.5}%`}
          fontSize="5px"
          style={{ userSelect: 'none', fill: '#10B981' }}
        >
          🔗
        </text>
      )}

      {/* Text label with leader line */}
      {labelText && (
        <g style={{ pointerEvents: 'none' }}>
          {/* Diagonal Leader Line */}
          <line
            x1={`${cx}%`} y1={`${cy}%`}
            x2={`${labelX}%`} y2={`${labelY}%`}
            stroke="#090D1A"
            strokeWidth={0.5}
            opacity={0.6}
          />
          <text
            x={`${labelX + 0.2}%`}
            y={`${labelY - 0.2}%`}
            fill={isSuggested ? '#94A3B8' : isLowConf && layers.colorMode === 'kind' ? '#F59E0B' : '#F1F5F9'}
            fontSize="5px"
            fontWeight="bold"
            textAnchor="start"
            transform={`rotate(-45, ${labelX}, ${labelY})`}
            style={{ userSelect: 'none', paintOrder: 'stroke', stroke: '#090D1A', strokeWidth: 1.5 }}
          >
            {hasError && !isSuggested && '⚠️ '}
            {labelText}
          </text>
        </g>
      )}
    </g>
  )
}
