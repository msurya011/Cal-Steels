'use client'

import React, { useEffect, useMemo, useState, useCallback } from 'react'
import { membersApi } from '../../../../lib/api'
import { KeyPlanFloor, KeyPlanPage, colorForPageIdx } from './KeyPlanTypes'

interface Member {
  id: string
  kind: string
  geometry: {
    x: number
    y: number
    bx1?: number | null
    by1?: number | null
    bx2?: number | null
    by2?: number | null
    global?: {
      gx_ft?: number
      gy_ft?: number
      gx1_ft?: number
      gy1_ft?: number
      gx2_ft?: number
      gy2_ft?: number
    }
  }
}

interface KeyPlanViewProps {
  floor: KeyPlanFloor | null
  manualPageIds: Set<string>
  hiddenPageIds: Set<string>
  // Live-committed feet offset nudges keyed by page_id, applied on top of
  // each page's stored registration -- lets a drag preview instantly
  // without waiting on a round trip, then gets folded into the PATCH.
  onDragCommit: (pageId: string, dxFt: number, dyFt: number) => void
}

/**
 * Renders every page of a floor overlaid into one shared feet-based
 * coordinate space (using each member's registered geometry.global), color
 * -coded per page -- SteelGenie's Key Plan canvas.
 */
export function KeyPlanView({ floor, manualPageIds, hiddenPageIds, onDragCommit }: KeyPlanViewProps) {
  const [membersByPage, setMembersByPage] = useState<Record<string, Member[]>>({})
  const [loading, setLoading] = useState(false)
  const [drag, setDrag] = useState<{ pageId: string; startX: number; startY: number; dxPx: number; dyPx: number } | null>(null)
  const svgWidthRef = React.useRef(1000)

  useEffect(() => {
    if (!floor) return
    let cancelled = false
    setLoading(true)
    Promise.all(
      floor.pages.map((p) => membersApi.list(p.page_id).then((ms: Member[]) => [p.page_id, ms] as const).catch(() => [p.page_id, []] as const))
    ).then((pairs) => {
      if (cancelled) return
      const map: Record<string, Member[]> = {}
      for (const [pid, ms] of pairs) map[pid] = ms as Member[]
      setMembersByPage(map)
      setLoading(false)
    })
    return () => {
      cancelled = true
    }
  }, [floor])

  // Bounding box across every registered member of every visible page, in feet.
  const bounds = useMemo(() => {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
    let any = false
    for (const p of floor?.pages || []) {
      if (hiddenPageIds.has(p.page_id)) continue
      for (const m of membersByPage[p.page_id] || []) {
        const g = m.geometry?.global
        if (!g) continue
        const xs = [g.gx_ft, g.gx1_ft, g.gx2_ft].filter((v) => typeof v === 'number') as number[]
        const ys = [g.gy_ft, g.gy1_ft, g.gy2_ft].filter((v) => typeof v === 'number') as number[]
        for (const x of xs) { minX = Math.min(minX, x); maxX = Math.max(maxX, x); any = true }
        for (const y of ys) { minY = Math.min(minY, y); maxY = Math.max(maxY, y) }
      }
    }
    if (!any) return null
    const padX = Math.max(10, (maxX - minX) * 0.08)
    const padY = Math.max(10, (maxY - minY) * 0.08)
    return { minX: minX - padX, minY: minY - padY, maxX: maxX + padX, maxY: maxY + padY }
  }, [floor, membersByPage, hiddenPageIds])

  const registeredCount = (floor?.pages || []).filter((p) => membersByPage[p.page_id]?.some((m) => m.geometry?.global)).length

  const handlePageMouseDown = useCallback(
    (pageId: string, e: React.MouseEvent) => {
      if (!manualPageIds.has(pageId)) return
      e.stopPropagation()
      e.preventDefault()
      setDrag({ pageId, startX: e.clientX, startY: e.clientY, dxPx: 0, dyPx: 0 })
    },
    [manualPageIds]
  )

  useEffect(() => {
    if (!drag) return
    const onMove = (e: MouseEvent) => {
      setDrag((d) => (d ? { ...d, dxPx: e.clientX - d.startX, dyPx: e.clientY - d.startY } : d))
    }
    const onUp = () => {
      setDrag((d) => {
        if (d && bounds && (Math.abs(d.dxPx) > 2 || Math.abs(d.dyPx) > 2)) {
          const scaleFtPerPx = (bounds.maxX - bounds.minX) / svgWidthRef.current
          onDragCommit(d.pageId, d.dxPx * scaleFtPerPx, d.dyPx * scaleFtPerPx)
        }
        return null
      })
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drag, bounds])

  if (!floor) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#64748B', fontSize: '13px' }}>
        No floor selected yet.
      </div>
    )
  }

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#64748B', fontSize: '13px' }}>
        Loading pages…
      </div>
    )
  }

  if (!bounds) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#64748B', fontSize: '13px', padding: '24px', textAlign: 'center' }}>
        <span>None of this floor's pages are registered into a shared coordinate space yet.</span>
        <span style={{ fontSize: '12px', opacity: 0.8 }}>Click Apply in the panel on the right to register this floor.</span>
      </div>
    )
  }

  const w = bounds.maxX - bounds.minX
  const h = bounds.maxY - bounds.minY
  const toX = (ftX: number) => ((ftX - bounds.minX) / w) * 100
  const toY = (ftY: number) => ((ftY - bounds.minY) / h) * 100

  // Feet-labeled axis ticks, ~8 divisions, matching the reference ruler.
  const tickStep = Math.max(5, Math.round(w / 8 / 5) * 5)
  const xTicks: number[] = []
  for (let t = Math.ceil(bounds.minX / tickStep) * tickStep; t <= bounds.maxX; t += tickStep) xTicks.push(t)

  return (
    <div
      style={{ position: 'relative', width: '100%', height: '100%', backgroundColor: '#0B1220', overflow: 'hidden' }}
      ref={(el) => { if (el) svgWidthRef.current = el.clientWidth }}
    >
      {/* Axis ruler */}
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: '22px', borderBottom: '1px solid rgba(255,255,255,0.08)', display: 'flex' }}>
        {xTicks.map((t) => (
          <span
            key={t}
            style={{ position: 'absolute', left: `${toX(t)}%`, top: '2px', fontSize: '10px', color: '#475569', transform: 'translateX(-50%)' }}
          >
            {t}'-0"
          </span>
        ))}
      </div>

      <svg style={{ position: 'absolute', inset: '22px 0 0 0', width: '100%', height: 'calc(100% - 22px)' }}>
        {/* Grid */}
        {xTicks.map((t) => (
          <line key={t} x1={`${toX(t)}%`} y1="0%" x2={`${toX(t)}%`} y2="100%" stroke="rgba(255,255,255,0.04)" strokeWidth={1} />
        ))}

        {floor.pages.map((p, i) => {
          if (hiddenPageIds.has(p.page_id)) return null
          const color = colorForPageIdx(i)
          const ms = membersByPage[p.page_id] || []
          const isManual = manualPageIds.has(p.page_id)
          const isDragging = drag?.pageId === p.page_id
          const dxFrac = isDragging ? (drag!.dxPx / svgWidthRef.current) * 100 : 0
          const dyFrac = isDragging ? (drag!.dyPx / (svgWidthRef.current * (h / w))) * 100 : 0

          let cxSum = 0, cySum = 0, cCount = 0

          const shapes = ms.map((m) => {
            const g = m.geometry?.global
            if (!g) return null
            if (typeof g.gx1_ft === 'number' && typeof g.gx2_ft === 'number') {
              const x1 = toX(g.gx1_ft!), y1 = toY(g.gy1_ft!), x2 = toX(g.gx2_ft!), y2 = toY(g.gy2_ft!)
              cxSum += (x1 + x2) / 2; cySum += (y1 + y2) / 2; cCount++
              return <line key={m.id} x1={`${x1}%`} y1={`${y1}%`} x2={`${x2}%`} y2={`${y2}%`} stroke={color} strokeWidth={1.6} opacity={0.9} />
            }
            if (typeof g.gx_ft === 'number') {
              const x = toX(g.gx_ft!), y = toY(g.gy_ft!)
              cxSum += x; cySum += y; cCount++
              return <circle key={m.id} cx={`${x}%`} cy={`${y}%`} r={3} fill={color} />
            }
            return null
          })

          const labelX = cCount > 0 ? cxSum / cCount : 50
          const labelY = cCount > 0 ? cySum / cCount : 50

          return (
            <g
              key={p.page_id}
              transform={isDragging ? `translate(${dxFrac} ${dyFrac})` : undefined}
              style={{ cursor: isManual ? 'grab' : 'default' }}
              onMouseDown={(e) => handlePageMouseDown(p.page_id, e)}
            >
              {shapes}
              <text
                x={`${labelX}%`}
                y={`${labelY}%`}
                fill={color}
                fontSize="11px"
                fontWeight={700}
                textAnchor="middle"
                style={{ paintOrder: 'stroke', stroke: '#0B1220', strokeWidth: 3, pointerEvents: 'none', userSelect: 'none' }}
              >
                {p.sheet_no ? `Page ${p.sheet_no}` : p.title || `Page ${p.idx ?? ''}`}
              </text>
            </g>
          )
        })}
      </svg>

      {registeredCount < floor.pages.length && (
        <div style={{ position: 'absolute', bottom: '12px', left: '12px', fontSize: '11px', color: '#F59E0B', backgroundColor: 'rgba(245,158,11,0.1)', border: '1px solid rgba(245,158,11,0.3)', borderRadius: '6px', padding: '6px 10px' }}>
          {floor.pages.length - registeredCount} of {floor.pages.length} page(s) not registered yet — click Apply.
        </div>
      )}
    </div>
  )
}
