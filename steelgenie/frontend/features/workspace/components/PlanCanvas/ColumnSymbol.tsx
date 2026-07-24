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
  onDragEnd?: (id: string, dx: number, dy: number) => void
  snapPoint?: (x: number, y: number, ignorePt?: { x: number; y: number } | null) => { x: number; y: number; snapped: boolean }
}

// Matches the real SteelGenie overlay style (verified live against
// app.steelgenie.com): a thin stroked cross-section symbol plus the profile
// text sitting directly next to it. No background pill, no category label
// ("Column"), no translucent highlight box, no confidence halo -- status is
// conveyed only through stroke color/weight, exactly like the reference.
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
  onDragEnd,
  snapPoint
}: ColumnSymbolProps) {
  const { setDraggingMember, draggingMemberId } = useWorkspaceStore()
  const isDraggingThis = draggingMemberId === m.id
  const { color, opacity } = renderProps
  const geo = m.geometry
  const flags: string[] = geo.error_flags || []
  const isSuggested = Boolean(geo.suggested)
  const hasError = flags.some((f: string) => f !== 'suggested')
  const isVerified = m.status === 'verified'
  const filterStyle = isSelected || isZoomTarget ? 'url(#glow-select)' : undefined

  // Position in percent (0-100).
  //
  // Stage 6 Part 2 (2026-07-17, live-verified against real SteelGenie): the
  // backend snaps a detected symbol's structural position onto the nearest
  // grid line (geo.x/geo.y) so beam connectivity/3D math has a clean
  // intersection to work with -- but that snap can be a few real inches
  // away from where the symbol is ACTUALLY drawn on the sheet. Rendering at
  // the snapped point is what made markers look "close but not quite on"
  // the real symbol. geo.raw_x/raw_y (now that the backend persists them --
  // they were previously silently dropped) is the true detected center, so
  // the visual marker uses that when available and only falls back to the
  // snapped point for older data that predates this fix.
  const hasRaw = geo.raw_x !== undefined && geo.raw_x !== null && geo.raw_y !== undefined && geo.raw_y !== null
  const cx = (hasRaw ? geo.raw_x : geo.x) * 100
  const cy = (hasRaw ? geo.raw_y : geo.y) * 100

  // Drag logic
  const groupRef = useRef<SVGGElement>(null)
  const snapIndicatorRef = useRef<SVGCircleElement>(null)

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
      // Convert screen coordinates into the 0-100 percent space every
      // element is positioned in, using the SVG's own on-screen bounding
      // box. The overlay has no viewBox, so its user-unit space is raw CSS
      // pixels -- createSVGPoint/getScreenCTM would hand back pixel values
      // where percent values are expected, causing wild jumps.
      const rect = svg.getBoundingClientRect()
      if (rect.width && rect.height) {
        let svgPt = {
          x: ((ev.clientX - rect.left) / rect.width) * 100,
          y: ((ev.clientY - rect.top) / rect.height) * 100,
        }

        let isSnapped = false
        if (snapPoint) {
           const snapped = snapPoint(svgPt.x / 100, svgPt.y / 100)
           if (snapped.snapped) {
               svgPt.x = snapped.x * 100
               svgPt.y = snapped.y * 100
               isSnapped = true
           }
        }

        if (groupRef.current) {
          let dx = svgPt.x - cx
          let dy = svgPt.y - cy

          // Shift key constraint: horizontal or vertical translation only
          if (ev.shiftKey) {
            if (Math.abs(dx) > Math.abs(dy)) {
              dy = 0
              svgPt.y = cy
            } else {
              dx = 0
              svgPt.x = cx
            }
          }

          groupRef.current.setAttribute('transform', `translate(${dx}, ${dy})`)
          currentX = svgPt.x
          currentY = svgPt.y
          
          if (snapIndicatorRef.current) {
            if (isSnapped) {
              snapIndicatorRef.current.setAttribute('cx', `${svgPt.x - dx}%`)
              snapIndicatorRef.current.setAttribute('cy', `${svgPt.y - dy}%`)
              snapIndicatorRef.current.style.display = 'block'
            } else {
              snapIndicatorRef.current.style.display = 'none'
            }
          }
        }
      }
    }

    const handlePointerUp = (ev: PointerEvent) => {
      ;(ev.target as Element)?.releasePointerCapture(ev.pointerId)
      window.removeEventListener('pointermove', handlePointerMove)
      window.removeEventListener('pointerup', handlePointerUp)
      setDraggingMember(null, null, null)
      if (groupRef.current) {
        groupRef.current.removeAttribute('transform')
      }
      if (snapIndicatorRef.current) snapIndicatorRef.current.style.display = 'none'
      if (Math.abs(currentX - cx) > 0.1 || Math.abs(currentY - cy) > 0.1) {
        onDragEnd(m.id, (currentX - cx) / 100, (currentY - cy) / 100)
      } else {
        onClick(e as any)
      }
    }

    window.addEventListener('pointermove', handlePointerMove)
    window.addEventListener('pointerup', handlePointerUp)
    setDraggingMember(m.id, null, null)
  }

  // ── Symbol sizing ──────────────────────────────────────────────────────────
  // Small, fixed visual size by default -- geo.w/geo.h are the AI-detected
  // TEXT label bounding box, not the physical symbol size, so they're
  // ignored here, same as before.
  //
  // Stage 6 Part 2: for a real BOX/footing outline, SteelGenie draws the
  // marker AT THE ACTUAL SIZE of the detected shape, not a generic square --
  // geo.sym_w/sym_h (the real bounding box, as a fraction of the page, now
  // propagated from the backend's detection bbox) gives us that. I/H column
  // icons stay the small fixed schematic size verified earlier against the
  // real app -- only BOX uses the real detected size.
  const symbol = geo.symbol || 'I'
  const hasRealSize = symbol === 'BOX' && typeof geo.sym_w === 'number' && typeof geo.sym_h === 'number' && geo.sym_w > 0 && geo.sym_h > 0
  const sW = hasRealSize ? geo.sym_w * 100 : 0.5
  const sH = hasRealSize ? geo.sym_h * 100 : 0.5
  const ft = sW * 0.22   // flange thickness ≈ 22% of depth — matches real wide-flange proportions

  let stroke = color
  let dash: string | undefined
  if (layers.colorMode === 'kind') {
    if (isSuggested) { stroke = '#94A3B8'; dash = '3,3' }
    else if (hasError) { stroke = '#EF4444'; dash = '4,3' }
    else if (isVerified) { stroke = '#10B981' }
    else if (isLowConf || m.status === 'need_review') { stroke = '#F59E0B'; dash = '4,3' }
  }
  const sw = (isHovered ? 2.2 : 1.4) + (isSelected ? 1.0 : 0)

  // Stroke-only flanges/web -- matches the thin line weight seen on the real
  // reference, rather than solid-filled shapes that read as heavier blobs.
  const f1 = { x: cx - sW / 2, y: cy - sH / 2, w: ft, h: sH }
  const f2 = { x: cx + sW / 2 - ft, y: cy - sH / 2, w: ft, h: sH }
  const web = { x: cx - sW / 2 + ft, y: cy - ft / 2, w: sW - 2 * ft, h: ft }

  const rectEl = (r: { x: number; y: number; w: number; h: number }, key: string) => (
    <rect
      key={key}
      x={`${r.x}%`} y={`${r.y}%`} width={`${r.w}%`} height={`${r.h}%`}
      fill="none"
      stroke={stroke}
      strokeWidth={sw}
      strokeDasharray={dash}
      strokeLinejoin="round"
      className={isZoomTarget ? 'pulsing-member' : ''}
      style={{ transition: isDraggingThis ? 'none' : 'all 0.1s ease', filter: filterStyle }}
    />
  )

  const labelText = isSuggested ? 'Column?' : getLabelText(m)

  return (
    <g
      ref={groupRef}
      onPointerDown={handlePointerDown}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      style={{ pointerEvents: 'all', cursor: isSuggested ? 'pointer' : 'grab', opacity: isSuggested ? opacity * 0.65 : opacity, touchAction: 'none' }}
    >
      {/* Suggested ghost ring — the only "extra" affordance kept, since a
          suggested/unconfirmed column genuinely has no real symbol yet. */}
      {isSuggested && (
        <circle
          cx={`${cx}%`} cy={`${cy}%`} r={isHovered ? 10 : 8}
          fill="none" stroke="#94A3B8" strokeWidth={1.2} strokeDasharray="3,3"
          className="pulsing-halo"
        />
      )}

      {/* Selection outline — editing aid, not part of the base drawing style */}
      {isSelected && (
        <rect
          x={`${cx - sW / 2 - 0.4}%`}
          y={`${cy - sH / 2 - 0.4}%`}
          width={`${sW + 0.8}%`}
          height={`${sH + 0.8}%`}
          fill="none"
          stroke="#22C55E"
          strokeWidth={1.2}
          strokeDasharray="2,2"
        />
      )}

      {/* Validation overlay: snap vector from the visual marker (the real
          detected position) to the grid-snapped structural point used for
          beam-connectivity/3D math. Points AWAY from the marker now, since
          the marker itself moved to the real position (Stage 6 Part 2) --
          previously this pointed the other direction, which collapsed to a
          zero-length line once cx/cy became the raw point. */}
      {layers.aids.columnProjections !== false && hasRaw && (Math.abs(geo.raw_x - geo.x) > 0.0001 || Math.abs(geo.raw_y - geo.y) > 0.0001) && (
        <g style={{ pointerEvents: 'none' }}>
          <line
            x1={`${cx}%`}
            y1={`${cy}%`}
            x2={`${geo.x * 100}%`}
            y2={`${geo.y * 100}%`}
            stroke="#EF4444"
            strokeWidth={1}
            strokeDasharray="3,3"
            opacity={0.7}
          />
        </g>
      )}

      {/* Cross-section symbol — thin stroke only, precise rotation */}
      <g style={{ transformOrigin: 'center', transformBox: 'fill-box', transform: `rotate(${m.rotation || 0}deg)` }}>
        {symbol === 'BOX' ? (
          rectEl({ x: cx - sW / 2, y: cy - sH / 2, w: sW, h: sH }, 'box')
        ) : symbol === 'PIPE' ? (
          <circle
            cx={`${cx}%`} cy={`${cy}%`} r={Math.max(sW, sH) / 2}
            fill="none" stroke={stroke} strokeWidth={sw} strokeDasharray={dash}
            className={isZoomTarget ? 'pulsing-member' : ''}
            style={{ transition: isDraggingThis ? 'none' : 'all 0.1s ease', filter: filterStyle }}
          />
        ) : (
          <>
            {rectEl(f1, 'f1')}
            {rectEl(f2, 'f2')}
            {rectEl(web, 'web')}
          </>
        )}
      </g>

      {/* Node marker — tiny fixed dot at the exact grid intersection, matching
          the small connection-point icon in the reference (not a scaled
          confidence indicator). */}
      {!isSuggested && (
        <rect
          x={`${cx - 0.3}%`}
          y={`${cy - 0.3}%`}
          width="0.6%"
          height="0.6%"
          fill={stroke}
          style={{ pointerEvents: 'none' }}
        />
      )}

      {/* Profile label — plain text next to the symbol, color-coded by status.
          No pill background, no category text, no warning glyph -- a flagged
          column is communicated by the stroke color alone (red), matching
          the reference's restraint. */}
      {labelText && (
        <text
          x={`${cx}%`}
          y={`${cy - sH / 2 - 1.2}%`}
          fill={stroke}
          fontSize="6px"
          fontWeight="600"
          textAnchor="middle"
          style={{
            userSelect: 'none',
            paintOrder: 'stroke',
            stroke: '#0B1220',
            strokeWidth: 2,
            pointerEvents: 'none',
          }}
        >
          {labelText}
        </text>
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
    </g>
  )
}
