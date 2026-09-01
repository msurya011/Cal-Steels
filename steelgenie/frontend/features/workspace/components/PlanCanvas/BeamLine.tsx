import React, { useRef } from 'react'
import { useWorkspaceStore } from '../../../../lib/stores/workspaceStore'

export interface BeamLineProps {
  member: any
  x1: number // percent (0-100)
  y1: number
  x2: number
  y2: number
  strokeColor: string
  markerColor: string
  strokeWidth: number
  isSelected: boolean
  isHovered: boolean
  isZoomTarget: boolean
  isUnlabeled: boolean
  showHalo: boolean
  showText: boolean
  labelText: string | null
  filterStyle?: string
  opacity: number
  onClick: (e: React.MouseEvent) => void
  onMouseEnter: () => void
  onMouseLeave: () => void
  onDragEnd?: (id: string, dx: number, dy: number) => void
  onEndpointDragEnd?: (id: string, endpoint: 'start' | 'end', x: number, y: number) => void
  snapPoint?: (x: number, y: number, ignorePt?: { x: number; y: number } | null) => { x: number; y: number; snapped: boolean }
}

// Beam line with drag-and-drop editing: drag anywhere on the line body to
// translate the whole beam, or grab either endpoint handle (visible on
// hover/select) to reposition just that end -- e.g. reconnecting a beam to a
// different grid intersection without having to redraw it from scratch.
export const BeamLine = React.memo(function BeamLine({
  member: m,
  x1, y1, x2, y2,
  strokeColor,
  markerColor,
  strokeWidth,
  isSelected,
  isHovered,
  isZoomTarget,
  isUnlabeled,
  showHalo,
  showText,
  labelText,
  filterStyle,
  opacity,
  onClick,
  onMouseEnter,
  onMouseLeave,
  onDragEnd,
  onEndpointDragEnd,
  snapPoint,
}: BeamLineProps) {
  const { setDraggingMember, imageNaturalWidth, imageAspect, selectedRatio, draggingMemberId } = useWorkspaceStore()
  const isDraggingThis = draggingMemberId === m.id

  const groupRef = useRef<SVGGElement>(null)
  const snapIndicatorRef = useRef<SVGCircleElement>(null)
  const guideTextRef = useRef<SVGTextElement>(null)
  const guideBgRef = useRef<SVGRectElement>(null)

  const lineRef = useRef<SVGLineElement>(null)
  const haloLineRef = useRef<SVGLineElement>(null)
  const selectionLineRef = useRef<SVGLineElement>(null)
  const clickTargetRef = useRef<SVGLineElement>(null)
  const startHandleRef = useRef<SVGCircleElement>(null)
  const endHandleRef = useRef<SVGCircleElement>(null)

  // Convert a pointer event's screen coordinates into the 0-100 percent
  // space every element in this overlay is positioned in. Deliberately uses
  // the SVG's own on-screen bounding box (not createSVGPoint/getScreenCTM) --
  // the overlay has no viewBox, so its internal user-unit space is raw CSS
  // pixels, and CTM-based conversion would give pixel values where percent
  // values are expected (that mismatch is what caused drags to jump wildly
  // and endpoints to save far off the page).
  const toSvgPct = (ev: PointerEvent, svg: SVGSVGElement) => {
    const rect = svg.getBoundingClientRect()
    if (!rect.width || !rect.height) return null
    return {
      x: ((ev.clientX - rect.left) / rect.width) * 100,
      y: ((ev.clientY - rect.top) / rect.height) * 100,
    }
  }

  // Drag the whole line (translate both endpoints together)
  const handleLinePointerDown = (e: React.PointerEvent) => {
    if (!onDragEnd) return
    e.stopPropagation()
    const svg = groupRef.current?.ownerSVGElement
    if (!svg) return
    ;(e.target as Element).setPointerCapture(e.pointerId)

    let dxLive = 0
    let dyLive = 0

    const handleMove = (ev: PointerEvent) => {
      let svgPt = toSvgPct(ev, svg)
      if (!svgPt || !groupRef.current) return
      
      let isSnapped = false
      if (snapPoint) {
         const snapped = snapPoint(svgPt.x / 100, svgPt.y / 100)
         if (snapped.snapped) {
             svgPt.x = snapped.x * 100
             svgPt.y = snapped.y * 100
             isSnapped = true
         }
      }
      
      dxLive = svgPt.x - startClientPt.x
      dyLive = svgPt.y - startClientPt.y

      // Shift key constraint: horizontal or vertical translation only
      if (ev.shiftKey) {
        if (Math.abs(dxLive) > Math.abs(dyLive)) {
          dyLive = 0
        } else {
          dxLive = 0
        }
      }

      groupRef.current.setAttribute('transform', `translate(${dxLive}, ${dyLive})`)

      if (snapIndicatorRef.current) {
        if (isSnapped) {
          // Counter the transform to keep the snap indicator fixed at the absolute snap point
          snapIndicatorRef.current.setAttribute('cx', `${svgPt.x - dxLive}%`)
          snapIndicatorRef.current.setAttribute('cy', `${svgPt.y - dyLive}%`)
          snapIndicatorRef.current.style.display = 'block'
        } else {
          snapIndicatorRef.current.style.display = 'none'
        }
      }
    }

    const startClientPt = (() => {
      const rect = svg.getBoundingClientRect()
      if (!rect.width || !rect.height) return { x: 0, y: 0 }
      return {
        x: ((e.clientX - rect.left) / rect.width) * 100,
        y: ((e.clientY - rect.top) / rect.height) * 100,
      }
    })()

    const handleUp = (ev: PointerEvent) => {
      ;(ev.target as Element)?.releasePointerCapture(ev.pointerId)
      window.removeEventListener('pointermove', handleMove)
      window.removeEventListener('pointerup', handleUp)
      setDraggingMember(null, null, null)
      if (groupRef.current) groupRef.current.removeAttribute('transform')
      if (snapIndicatorRef.current) snapIndicatorRef.current.style.display = 'none'
      // 0.1% of the sheet width is sub-pixel at any real screen size -- an
      // ordinary hand-tremor between mousedown and mouseup on a plain click
      // clears that easily, which was firing a phantom "position updated"
      // save (and PATCH request) on every single select-click instead of
      // just selecting. This is what made clicking beams feel unreliable/
      // "hard" -- raised to a threshold no accidental click can cross.
      if (Math.abs(dxLive) > 0.6 || Math.abs(dyLive) > 0.6) {
        onDragEnd(m.id, dxLive / 100, dyLive / 100)
      } else {
        onClick(e as any)
      }
    }

    window.addEventListener('pointermove', handleMove)
    window.addEventListener('pointerup', handleUp)
    setDraggingMember(m.id, null, null)
  }

  // Drag a single endpoint handle (reposition just that end of the beam)
  const makeEndpointHandler = (endpoint: 'start' | 'end', ex: number, ey: number) => (e: React.PointerEvent) => {
    if (!onEndpointDragEnd) return
    e.stopPropagation()
    const svg = groupRef.current?.ownerSVGElement
    if (!svg) return
    ;(e.target as Element).setPointerCapture(e.pointerId)

    // Move the *visible* dot, not e.currentTarget -- the pointerdown lands on
    // the larger invisible hit-circle sitting on top of it, which never
    // needs to move itself (pointer capture keeps tracking it either way).
    const handleEl = (endpoint === 'start' ? startHandleRef.current : endHandleRef.current) as SVGCircleElement
    let liveX = ex
    let liveY = ey
    const startX = ex
    const startY = ey

    const handleMove = (ev: PointerEvent) => {
      let svgPt = toSvgPct(ev, svg)
      if (!svgPt) return
      
      const otherX = endpoint === 'start' ? x2 : x1
      const otherY = endpoint === 'start' ? y2 : y1

      let isSnapped = false
      if (snapPoint) {
         const snapped = snapPoint(svgPt.x / 100, svgPt.y / 100, { x: otherX / 100, y: otherY / 100 })
         if (snapped.snapped) {
             svgPt.x = snapped.x * 100
             svgPt.y = snapped.y * 100
             isSnapped = true
         }
      }

      // Shift key constraint: restrict dragging to orthogonal axis relative to other endpoint
      if (ev.shiftKey) {
        const dx = svgPt.x - otherX
        const dy = svgPt.y - otherY
        if (Math.abs(dx) > Math.abs(dy)) {
          svgPt.y = otherY
        } else {
          svgPt.x = otherX
        }
      }

      liveX = svgPt.x
      liveY = svgPt.y
      handleEl.setAttribute('cx', `${liveX}%`)
      handleEl.setAttribute('cy', `${liveY}%`)

      if (lineRef.current) {
        if (endpoint === 'start') {
          lineRef.current.setAttribute('x1', `${liveX}%`)
          lineRef.current.setAttribute('y1', `${liveY}%`)
        } else {
          lineRef.current.setAttribute('x2', `${liveX}%`)
          lineRef.current.setAttribute('y2', `${liveY}%`)
        }
      }
      if (selectionLineRef.current) {
        if (endpoint === 'start') {
          selectionLineRef.current.setAttribute('x1', `${liveX}%`)
          selectionLineRef.current.setAttribute('y1', `${liveY}%`)
        } else {
          selectionLineRef.current.setAttribute('x2', `${liveX}%`)
          selectionLineRef.current.setAttribute('y2', `${liveY}%`)
        }
      }
      if (haloLineRef.current) {
        if (endpoint === 'start') {
          haloLineRef.current.setAttribute('x1', `${liveX}%`)
          haloLineRef.current.setAttribute('y1', `${liveY}%`)
        } else {
          haloLineRef.current.setAttribute('x2', `${liveX}%`)
          haloLineRef.current.setAttribute('y2', `${liveY}%`)
        }
      }
      if (clickTargetRef.current) {
        if (endpoint === 'start') {
          clickTargetRef.current.setAttribute('x1', `${liveX}%`)
          clickTargetRef.current.setAttribute('y1', `${liveY}%`)
        } else {
          clickTargetRef.current.setAttribute('x2', `${liveX}%`)
          clickTargetRef.current.setAttribute('y2', `${liveY}%`)
        }
      }

      if (snapIndicatorRef.current) {
        if (isSnapped) {
          snapIndicatorRef.current.setAttribute('cx', `${liveX}%`)
          snapIndicatorRef.current.setAttribute('cy', `${liveY}%`)
          snapIndicatorRef.current.style.display = 'block'
        } else {
          snapIndicatorRef.current.style.display = 'none'
        }
      }

      if (guideTextRef.current && guideBgRef.current && imageNaturalWidth && selectedRatio) {
         const liveX1 = endpoint === 'start' ? liveX : x1
         const liveY1 = endpoint === 'start' ? liveY : y1
         const liveX2 = endpoint === 'end' ? liveX : x2
         const liveY2 = endpoint === 'end' ? liveY : y2
         
         const dxPx = ((liveX2 - liveX1) / 100) * imageNaturalWidth
         const dyPx = ((liveY2 - liveY1) / 100) * imageNaturalWidth * imageAspect
         const lenPts = (Math.sqrt(dxPx * dxPx + dyPx * dyPx) * 72) / 150
         const ft = (lenPts * selectedRatio) / 864
         const whole = Math.floor(ft)
         const inches = Math.round((ft - whole) * 12)
         
         let angle = (Math.atan2(liveY2 - liveY1, liveX2 - liveX1) * 180) / Math.PI
         if (angle > 90) angle -= 180
         if (angle < -90) angle += 180
         
         guideTextRef.current.textContent = `${whole}'-${inches}" | ${Math.round(angle)}°`
         
         const midX = (liveX1 + liveX2) / 2
         const midY = (liveY1 + liveY2) / 2
         
         // Using inline style translation since SVG transform attribute origin can be tricky
         guideTextRef.current.style.transform = `translate(${midX}%, ${midY - 1.1}%) rotate(${angle}deg)`
         guideBgRef.current.style.transform = `translate(${midX - 4}%, ${midY - 2.5}%) rotate(${angle}deg)`
         
         guideTextRef.current.style.display = 'block'
         guideBgRef.current.style.display = 'block'
      }
    }

    const handleUp = (ev: PointerEvent) => {
      ;(ev.target as Element)?.releasePointerCapture(ev.pointerId)
      window.removeEventListener('pointermove', handleMove)
      window.removeEventListener('pointerup', handleUp)
      setDraggingMember(null, null, null)
      if (snapIndicatorRef.current) snapIndicatorRef.current.style.display = 'none'
      if (guideTextRef.current) guideTextRef.current.style.display = 'none'
      if (guideBgRef.current) guideBgRef.current.style.display = 'none'
      // Same phantom-save guard as the whole-line drag: a plain click on the
      // handle (to just select it) shouldn't fire a resize save.
      if (Math.abs(liveX - startX) > 0.6 || Math.abs(liveY - startY) > 0.6) {
        onEndpointDragEnd(m.id, endpoint, liveX / 100, liveY / 100)
      } else {
        onClick(e as any)
      }
    }

    window.addEventListener('pointermove', handleMove)
    window.addEventListener('pointerup', handleUp)
    setDraggingMember(m.id, endpoint, null)
  }

  const midX = (x1 + x2) / 2
  const midY = (y1 + y2) / 2
  
  // Calculate CAD line orientation
  const dx = x2 - x1
  const dy = y2 - y1
  const isVertical = Math.abs(dy) > Math.abs(dx) * 1.5

  let angle = m.geometry?.angle_deg ?? (Math.atan2(dy, dx) * 180) / Math.PI
  if (angle > 90) angle -= 180
  if (angle < -90) angle += 180
  if (isVertical) angle = -90

  const showHandles = (isSelected || isHovered) && (onDragEnd || onEndpointDragEnd)

  return (
    <g
      ref={groupRef}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      style={{ pointerEvents: 'all', opacity, touchAction: 'none' }}
    >
      {/* Invisible thick click/drag-target helper -- also the whole-line drag handle */}
      <line
        ref={clickTargetRef}
        x1={`${x1}%`} y1={`${y1}%`} x2={`${x2}%`} y2={`${y2}%`}
        fill="none" stroke="transparent" strokeWidth={16}
        onClick={(e) => { e.stopPropagation(); onClick(e) }}
        onPointerDown={handleLinePointerDown}
        style={{ cursor: onDragEnd ? 'grab' : 'pointer' }}
      />

      {/* Confidence Halo */}
      {showHalo && (
        <line
          ref={haloLineRef}
          x1={`${x1}%`} y1={`${y1}%`} x2={`${x2}%`} y2={`${y2}%`}
          fill="none" stroke="#F59E0B" strokeWidth={6} strokeDasharray="4,4"
          className="pulsing-halo" style={{ opacity: 0.8, pointerEvents: 'none', transition: isDraggingThis ? 'none' : 'all 0.15s ease' }}
        />
      )}

      {/* Selection line indicator */}
      {isSelected && (
        <line
          ref={selectionLineRef}
          x1={`${x1}%`} y1={`${y1}%`} x2={`${x2}%`} y2={`${y2}%`}
          fill="none" stroke="#22C55E" strokeWidth={6} style={{ opacity: 0.6, pointerEvents: 'none', transition: isDraggingThis ? 'none' : 'all 0.15s ease' }}
        />
      )}

      {/* Base Beam line.
          mixBlendMode: 'multiply' (not a plain opaque stroke) -- the beam
          overlay sits in an SVG layer drawn on top of the base PDF page
          image, so wherever a beam's real-world line crosses a detail-
          reference bubble (or any other dark linework baked into the
          drawing) a plain opaque stroke fully painted over it, making the
          bubble unreadable underneath. Multiply lets the underlying ink
          show through: over the white sheet the beam still reads at its
          full color (white is the identity color for multiply), but over
          a bubble's black outline/divider/arrow the result darkens toward
          that linework instead of hiding it, so the bubble stays legible
          right through the beam. Purely a paint-compositing change --
          doesn't touch which beams are drawn or their real geometry. */}
      <line
        ref={lineRef}
        x1={`${x1}%`} y1={`${y1}%`} x2={`${x2}%`} y2={`${y2}%`}
        fill="none"
        stroke={strokeColor}
        strokeWidth={strokeWidth}
        strokeDasharray="none"
        className={isZoomTarget ? 'pulsing-member' : ''}
        style={{ transition: isDraggingThis ? 'none' : 'all 0.15s ease', filter: filterStyle, opacity: 0.9, mixBlendMode: 'multiply', pointerEvents: 'none' }}
      />

      {/* Endpoint drag handles -- shown on hover/select so the beam can be
          re-pinned to a different point on either end */}
      {showHandles && (
        <>
          {/* Each handle is drawn as a small dot but grabbed via a much
              bigger invisible circle around it -- a 4px visual radius is
              nearly impossible to land a real mouse/trackpad drag on, which
              was a big part of why endpoint editing felt "hard" to grab. */}
          <circle
            cx={`${x1}%`} cy={`${y1}%`} r={14}
            fill="transparent"
            onPointerDown={makeEndpointHandler('start', x1, y1)}
            style={{ cursor: onEndpointDragEnd ? 'move' : 'default', pointerEvents: onEndpointDragEnd ? 'all' : 'none' }}
          />
          <circle
            ref={startHandleRef}
            cx={`${x1}%`} cy={`${y1}%`} r={4.5}
            fill="#0B1220" stroke={strokeColor} strokeWidth={1.5}
            style={{ pointerEvents: 'none' }}
          />
          <circle
            cx={`${x2}%`} cy={`${y2}%`} r={14}
            fill="transparent"
            onPointerDown={makeEndpointHandler('end', x2, y2)}
            style={{ cursor: onEndpointDragEnd ? 'move' : 'default', pointerEvents: onEndpointDragEnd ? 'all' : 'none' }}
          />
          <circle
            ref={endHandleRef}
            cx={`${x2}%`} cy={`${y2}%`} r={4.5}
            fill="#0B1220" stroke={strokeColor} strokeWidth={1.5}
            style={{ pointerEvents: 'none' }}
          />
        </>
      )}

      {/* Beam Profile & Length Label aligned along beam orientation */}
      {showText && labelText && (
        <g style={{ pointerEvents: 'none' }}>
          <text
            x={`${midX}%`}
            y={`${midY}%`}
            fill={isHovered ? '#60A5FA' : '#FFFFFF'}
            fontSize="10px"
            fontWeight="700"
            textAnchor="middle"
            dominantBaseline="central"
            style={{
              userSelect: 'none',
              paintOrder: 'stroke fill',
              stroke: '#0B1220',
              strokeWidth: 3.5,
              strokeLinejoin: 'round',
              fontFamily: "'Inter', 'Segoe UI', system-ui, sans-serif",
              letterSpacing: '0.02em',
              pointerEvents: 'none',
              transformBox: 'fill-box',
              transformOrigin: 'center',
              transform: `rotate(${angle}deg) translate(0, -6px)`,
            }}
          >
            {labelText}
          </text>
        </g>
      )}
      
      {/* Dynamic Snap Indicator */}
      <circle
        ref={snapIndicatorRef}
        r={6}
        fill="none"
        stroke="#3B82F6"
        strokeWidth={2.5}
        strokeDasharray="2,2"
        style={{ display: 'none', pointerEvents: 'none', zIndex: 50 }}
      />
      
      {/* Dynamic Drag Guides */}
      <g style={{ pointerEvents: 'none', zIndex: 60 }}>
        <rect
          ref={guideBgRef}
          width="8%" height="3%"
          fill="#1E293B" rx="1" ry="1"
          style={{ display: 'none', opacity: 0.9, transformBox: 'fill-box', transformOrigin: 'center' }}
        />
        <text
          ref={guideTextRef}
          fill="#60A5FA"
          fontSize="7px"
          fontWeight="700"
          textAnchor="middle"
          style={{ display: 'none', userSelect: 'none', transformBox: 'fill-box', transformOrigin: 'center' }}
        />
      </g>
    </g>
  )
}, (prev, next) => {
  return prev.member === next.member &&
         prev.x1 === next.x1 &&
         prev.y1 === next.y1 &&
         prev.x2 === next.x2 &&
         prev.y2 === next.y2 &&
         prev.strokeColor === next.strokeColor &&
         prev.isSelected === next.isSelected &&
         prev.isHovered === next.isHovered &&
         prev.isZoomTarget === next.isZoomTarget &&
         prev.showText === next.showText &&
         prev.labelText === next.labelText &&
         prev.opacity === next.opacity &&
         prev.filterStyle === next.filterStyle
})
