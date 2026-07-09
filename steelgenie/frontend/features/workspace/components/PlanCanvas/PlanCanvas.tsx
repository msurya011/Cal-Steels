import React, { useRef, useEffect, useState } from 'react'
import { useWorkspaceStore, Point, CropRect } from '../../../../lib/stores/workspaceStore'
import { OverlayLayer } from './OverlayLayer'
import { CanvasLegendChip } from './CanvasLegendChip'

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
}

interface PlanCanvasProps {
  imageUrl: string | null
  members: Member[]
  onMemberSelect: (member: Member | null) => void
  onAddAnnotationMarker: (pt: Point) => void
  onRulerCalibrate: (line: { x1: number; y1: number; x2: number; y2: number }) => void
  onDrawMember: (
    kind: 'column' | 'beam' | 'brace',
    geom: { x1: number; y1: number; x2: number; y2: number }
  ) => void
}

export function PlanCanvas({
  imageUrl,
  members,
  onMemberSelect,
  onAddAnnotationMarker,
  onRulerCalibrate,
  onDrawMember,
}: PlanCanvasProps) {
  const {
    activeTool,
    zoomLevel,
    setZoom,
    isPanning,
    setIsPanning,
    rulerStart,
    setRulerStart,
    rulerEnd,
    setRulerEnd,
    rulerDragging,
    setRulerDragging,
    addRulerLine,
    pushUndo,
    markerDots,
    addMarkerDot,
    rulerLines,
    setWrapperSize,
    selectedMemberId,
    selectMember,
    setImageNaturalWidth,
    imageNaturalWidth,
    selectedRatio,
    imageAspect,
    setImageAspect,
    zoomTarget,
    layers,
  } = useWorkspaceStore()

  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const imageWrapperRef = useRef<HTMLDivElement>(null)
  const [panStart, setPanStart] = useState({ x: 0, y: 0, scrollLeft: 0, scrollTop: 0 })
  const [hoveredMemberId, setHoveredMemberId] = useState<string | null>(null)

  // Centering scroll view to target member on double click
  useEffect(() => {
    if (!zoomTarget || !scrollContainerRef.current || !imageWrapperRef.current) return
    const member = members.find((m) => m.id === zoomTarget.id)
    if (!member) return

    const container = scrollContainerRef.current
    const wrapper = imageWrapperRef.current

    if (zoomLevel < 1.5) {
      setZoom(1.5)
    }

    setTimeout(() => {
      const rect = wrapper.getBoundingClientRect()
      const targetX = member.geometry.x * rect.width
      const targetY = member.geometry.y * rect.height

      const scrollLeft = targetX - container.clientWidth / 2
      const scrollTop = targetY - container.clientHeight / 2

      container.scrollTo({
        left: scrollLeft,
        top: scrollTop,
        behavior: 'smooth',
      })
    }, 150)
  }, [zoomTarget, members])

  // Zoom listener
  useEffect(() => {
    const el = imageWrapperRef.current
    if (el) {
      setWrapperSize(el.clientWidth, el.clientHeight)
    }
  }, [zoomLevel, setWrapperSize])

  // Mouse coordinate fractions
  const getImgPct = (e: React.MouseEvent): Point => {
    const el = imageWrapperRef.current
    if (!el) return { x: 0, y: 0 }
    const r = el.getBoundingClientRect()
    return {
      x: Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)),
      y: Math.max(0, Math.min(1, (e.clientY - r.top) / r.height)),
    }
  }

  const handleMouseDown = (e: React.MouseEvent) => {
    if (activeTool === 'hand') {
      e.preventDefault()
      setIsPanning(true)
      const sc = scrollContainerRef.current
      setPanStart({
        x: e.clientX,
        y: e.clientY,
        scrollLeft: sc?.scrollLeft ?? 0,
        scrollTop: sc?.scrollTop ?? 0,
      })
      return
    }

    if (activeTool === 'ruler' || activeTool === 'beam' || activeTool === 'brace') {
      e.preventDefault()
      const pt = getImgPct(e)
      setRulerStart(pt)
      setRulerEnd(pt)
      setRulerDragging(true)
      return
    }

    if (activeTool === 'column') {
      e.preventDefault()
      const pt = getImgPct(e)
      onDrawMember('column', { x1: pt.x, y1: pt.y, x2: pt.x, y2: pt.y })
      return
    }

    if (activeTool === 'marker') {
      e.preventDefault()
      const pt = getImgPct(e)
      addMarkerDot(pt)
      pushUndo('marker')
      onAddAnnotationMarker(pt)
      return
    }
  }

  const handleMouseMove = (e: React.MouseEvent) => {
    if (activeTool === 'hand' && isPanning) {
      const sc = scrollContainerRef.current
      if (!sc) return
      sc.scrollLeft = panStart.scrollLeft - (e.clientX - panStart.x)
      sc.scrollTop = panStart.scrollTop - (e.clientY - panStart.y)
      return
    }

    if ((activeTool === 'ruler' || activeTool === 'beam' || activeTool === 'brace') && rulerDragging) {
      setRulerEnd(getImgPct(e))
      return
    }
  }

  const handleMouseUp = (e: React.MouseEvent) => {
    if (activeTool === 'hand') {
      setIsPanning(false)
      return
    }

    if (activeTool === 'ruler' && rulerDragging && rulerStart) {
      const pt = getImgPct(e)
      const line = { x1: rulerStart.x, y1: rulerStart.y, x2: pt.x, y2: pt.y }
      addRulerLine(line)
      pushUndo('ruler')
      onRulerCalibrate(line)

      setRulerStart(null)
      setRulerEnd(null)
      setRulerDragging(false)
      return
    }

    if ((activeTool === 'beam' || activeTool === 'brace') && rulerDragging && rulerStart) {
      const pt = getImgPct(e)
      const dx = pt.x - rulerStart.x
      const dy = pt.y - rulerStart.y
      // Ignore accidental clicks (line too short)
      if (Math.sqrt(dx * dx + dy * dy) > 0.005) {
        onDrawMember(activeTool, { x1: rulerStart.x, y1: rulerStart.y, x2: pt.x, y2: pt.y })
      }
      setRulerStart(null)
      setRulerEnd(null)
      setRulerDragging(false)
      return
    }
  }

  // Live ft-in readout for the ruler/beam/brace drag line
  const liveDistance = (() => {
    if (!rulerStart || !rulerEnd || !imageNaturalWidth || !selectedRatio) return null
    const wPx = imageNaturalWidth
    const hPx = imageNaturalWidth * imageAspect
    const dxPx = (rulerEnd.x - rulerStart.x) * wPx
    const dyPx = (rulerEnd.y - rulerStart.y) * hPx
    const lenPts = (Math.sqrt(dxPx * dxPx + dyPx * dyPx) * 72) / 150 // preview rendered at 150 DPI
    const ft = (lenPts * selectedRatio) / 864
    const whole = Math.floor(ft)
    const inches = Math.round((ft - whole) * 12)
    return `${whole}'-${inches}"`
  })()

  return (
    <div
      ref={scrollContainerRef}
      style={{
        flex: 1,
        overflow: 'auto',
        backgroundColor: '#3E4E63',
        position: 'relative',
        cursor: activeTool === 'hand' ? (isPanning ? 'grabbing' : 'grab') : 'crosshair',
        outline: 'none',
        height: '100%',
        width: '100%',
      }}
    >
      {/* Floating Canvas Legend */}
      <CanvasLegendChip members={members} />

      {imageUrl ? (
        <div
          ref={imageWrapperRef}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          style={{
            position: 'relative',
            width: `${zoomLevel * 100}%`,
            height: 'fit-content',
            transformOrigin: 'top left',
            margin: '0 auto',
          }}
        >
          {/* Base drawing image */}
          <img
            src={imageUrl}
            alt="Drawing Plan"
            onLoad={(e) => {
              const img = e.currentTarget
              setImageNaturalWidth(img.naturalWidth)
              setImageAspect(img.naturalHeight / img.naturalWidth)
            }}
            style={{ width: '100%', height: 'auto', display: 'block', userSelect: 'none', opacity: layers.planVisible === false ? 0 : 1, transition: 'opacity 0.2s ease' }}
          />

          {/* SVG Overlay layer */}
          <OverlayLayer
            members={members}
            onMemberClick={(m, e) => {
              if (e.shiftKey || e.ctrlKey || e.metaKey) {
                useWorkspaceStore.getState().toggleSelection(m.id)
              } else {
                useWorkspaceStore.getState().setSelection(new Set([m.id]))
              }
              onMemberSelect(m)
            }}
            hoveredMemberId={hoveredMemberId}
            onMemberHover={setHoveredMemberId}
          />

          {/* Ruler calibration preview overlay lines */}
          {rulerStart && rulerEnd && (
            <svg
              style={{
                position: 'absolute',
                inset: 0,
                width: '100%',
                height: '100%',
                pointerEvents: 'none',
                zIndex: 20,
              }}
            >
              <line
                x1={`${rulerStart.x * 100}%`}
                y1={`${rulerStart.y * 100}%`}
                x2={`${rulerEnd.x * 100}%`}
                y2={`${rulerEnd.y * 100}%`}
                stroke={activeTool === 'ruler' ? '#F59E0B' : activeTool === 'brace' ? '#3B82F6' : '#EF4444'}
                strokeWidth={2}
                strokeDasharray="4 4"
              />
              {liveDistance && (
                <text
                  x={`${((rulerStart.x + rulerEnd.x) / 2) * 100}%`}
                  y={`${((rulerStart.y + rulerEnd.y) / 2) * 100 - 1}%`}
                  fill="#F59E0B"
                  fontSize="13"
                  fontWeight="700"
                  textAnchor="middle"
                  style={{ paintOrder: 'stroke', stroke: '#090D1A', strokeWidth: 3 }}
                >
                  {liveDistance}
                </text>
              )}
            </svg>
          )}

          {/* Placed ruler calibration overlays */}
          <svg
            style={{
              position: 'absolute',
              inset: 0,
              width: '100%',
              height: '100%',
              pointerEvents: 'none',
              zIndex: 5,
            }}
          >
            {rulerLines.map((line, idx) => (
              <line
                key={idx}
                x1={`${line.x1 * 100}%`}
                y1={`${line.y1 * 100}%`}
                x2={`${line.x2 * 100}%`}
                y2={`${line.y2 * 100}%`}
                stroke="#10B981"
                strokeWidth={2}
              />
            ))}
          </svg>
        </div>
      ) : (
        <div
          style={{
            display: 'flex',
            height: '100%',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#475569',
            fontSize: '14px',
            flexDirection: 'column',
            gap: '8px',
          }}
        >
          <span>No plan drawing loaded.</span>
          <span style={{ fontSize: '12px' }}>Select a page from the rail on the left.</span>
        </div>
      )}
    </div>
  )
}
