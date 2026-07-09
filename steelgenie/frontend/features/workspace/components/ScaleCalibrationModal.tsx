'use client'

import React, { useMemo, useState } from 'react'
import { X, Ruler } from 'lucide-react'

// Preview images are rendered at 150 DPI by the ingest worker (backend _PREVIEW_DPI).
// PDF points are 72/inch, so: points = pixels * 72 / 150.
const PREVIEW_DPI = 150

const STANDARD_SCALES: { label: string; ratio: number }[] = [
  { label: '1/32" = 1\'-0"', ratio: 384 },
  { label: '1/16" = 1\'-0"', ratio: 192 },
  { label: '3/32" = 1\'-0"', ratio: 128 },
  { label: '1/8" = 1\'-0"', ratio: 96 },
  { label: '3/16" = 1\'-0"', ratio: 64 },
  { label: '1/4" = 1\'-0"', ratio: 48 },
  { label: '3/8" = 1\'-0"', ratio: 32 },
  { label: '1/2" = 1\'-0"', ratio: 24 },
  { label: '3/4" = 1\'-0"', ratio: 16 },
  { label: '1" = 1\'-0"', ratio: 12 },
]

interface Props {
  /** Drawn line, in fractions of the page image [0..1] */
  line: { x1: number; y1: number; x2: number; y2: number }
  /** Natural pixel width/height of the page preview image */
  imageNaturalWidth: number
  imageAspect: number // naturalHeight / naturalWidth
  onApply: (label: string, ratio: number) => void
  onClose: () => void
}

export function ScaleCalibrationModal({ line, imageNaturalWidth, imageAspect, onApply, onClose }: Props) {
  const [feet, setFeet] = useState('')
  const [inches, setInches] = useState('0')

  // Line length in PDF points
  const linePts = useMemo(() => {
    const wPx = imageNaturalWidth
    const hPx = imageNaturalWidth * imageAspect
    const dxPx = (line.x2 - line.x1) * wPx
    const dyPx = (line.y2 - line.y1) * hPx
    const lenPx = Math.sqrt(dxPx * dxPx + dyPx * dyPx)
    return (lenPx * 72) / PREVIEW_DPI
  }, [line, imageNaturalWidth, imageAspect])

  const distanceFt = (parseFloat(feet) || 0) + (parseFloat(inches) || 0) / 12

  // ratio: engine convention is pts_per_foot = 864 / ratio  →  ratio = 864 * ft / pts
  const computedRatio = distanceFt > 0 ? (864 * distanceFt) / linePts : null

  const nearest = useMemo(() => {
    if (!computedRatio) return null
    let best = STANDARD_SCALES[0]
    let bestErr = Infinity
    for (const s of STANDARD_SCALES) {
      const err = Math.abs(s.ratio - computedRatio) / s.ratio
      if (err < bestErr) {
        bestErr = err
        best = s
      }
    }
    return { ...best, errPct: bestErr * 100 }
  }, [computedRatio])

  const snapOk = nearest && nearest.errPct < 7

  const handleApply = () => {
    if (!computedRatio) return
    if (snapOk && nearest) {
      onApply(nearest.label, nearest.ratio)
    } else {
      onApply(`Custom (1:${computedRatio.toFixed(1)})`, Math.round(computedRatio * 10) / 10)
    }
  }

  const field: React.CSSProperties = {
    width: '70px',
    padding: '8px 10px',
    backgroundColor: '#090D1A',
    border: '1px solid rgba(59, 130, 246, 0.25)',
    borderRadius: '8px',
    color: '#F1F5F9',
    fontSize: '14px',
    outline: 'none',
    textAlign: 'center',
  }

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(0,0,0,0.6)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
      }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: '380px',
          backgroundColor: '#111827',
          border: '1px solid rgba(59, 130, 246, 0.25)',
          borderRadius: '12px',
          padding: '20px',
          display: 'flex',
          flexDirection: 'column',
          gap: '16px',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '15px', fontWeight: 700, color: '#F1F5F9' }}>
            <Ruler size={16} /> Scale Calibration
          </span>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#94A3B8', cursor: 'pointer' }}>
            <X size={16} />
          </button>
        </div>

        <p style={{ margin: 0, fontSize: '12px', color: '#94A3B8', lineHeight: 1.5 }}>
          You drew a line over the plan. Enter the real-world dimension that line represents
          (use a labeled grid spacing or dimension string), and the drawing scale will be computed.
        </p>

        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <input type="number" min="0" value={feet} autoFocus placeholder="ft" onChange={(e) => setFeet(e.target.value)} style={field} />
          <span style={{ color: '#94A3B8', fontSize: '13px' }}>ft</span>
          <input type="number" min="0" max="11.99" value={inches} onChange={(e) => setInches(e.target.value)} style={field} />
          <span style={{ color: '#94A3B8', fontSize: '13px' }}>in</span>
        </div>

        {computedRatio && (
          <div
            style={{
              padding: '10px 12px',
              backgroundColor: 'rgba(59, 130, 246, 0.08)',
              border: '1px solid rgba(59, 130, 246, 0.2)',
              borderRadius: '8px',
              fontSize: '12px',
              color: '#CBD5E1',
              lineHeight: 1.6,
            }}
          >
            Computed ratio: <b>1 : {computedRatio.toFixed(1)}</b>
            <br />
            {snapOk && nearest ? (
              <>
                Matches standard scale <b style={{ color: '#10B981' }}>{nearest.label}</b>{' '}
                <span style={{ color: '#64748B' }}>({nearest.errPct.toFixed(1)}% off)</span>
              </>
            ) : (
              <span style={{ color: '#F59E0B' }}>
                No standard scale within 7% — a custom scale will be applied.
              </span>
            )}
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
          <button
            onClick={onClose}
            style={{
              padding: '8px 16px',
              backgroundColor: 'transparent',
              border: '1px solid rgba(148,163,184,0.3)',
              borderRadius: '8px',
              color: '#94A3B8',
              fontSize: '13px',
              cursor: 'pointer',
            }}
          >
            Cancel
          </button>
          <button
            onClick={handleApply}
            disabled={!computedRatio}
            style={{
              padding: '8px 16px',
              backgroundColor: computedRatio ? '#3B82F6' : 'rgba(59,130,246,0.2)',
              border: 'none',
              borderRadius: '8px',
              color: computedRatio ? '#FFF' : '#64748B',
              fontSize: '13px',
              fontWeight: 600,
              cursor: computedRatio ? 'pointer' : 'not-allowed',
            }}
          >
            Apply Scale
          </button>
        </div>
      </div>
    </div>
  )
}
