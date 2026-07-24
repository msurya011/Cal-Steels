import React, { useState } from 'react'
import { drawingsApi } from '../../../lib/api'

interface CreateProjectModalProps {
  onClose: () => void
  onCreate: (data: {
    name: string
    number: string
    design_standard: string
    unit_system: string
    location: string
    description: string
  }) => Promise<any>
}

const STANDARDS = ['AISC', 'IS 800', 'Eurocode 3', 'BS 5950', 'AS 4100']
const UNITS = ['imperial', 'metric']

// Standard sheet sizes (inches, landscape) — mirrors the backend's PAPER_SIZES_IN.
const PAPER_SIZES: Record<string, [number, number]> = {
  'ANSI A': [11, 8.5],
  'ANSI B': [17, 11],
  'ANSI C': [22, 17],
  'ANSI D': [34, 22],
  'ANSI E': [44, 34],
  'ARCH D': [36, 24],
  'ARCH E': [48, 36],
}
const SCALES: { label: string; num: number }[] = [
  { label: '1/8" = 1\'-0"', num: 96 },
  { label: '3/16" = 1\'-0"', num: 64 },
  { label: '1/4" = 1\'-0"', num: 48 },
  { label: '3/8" = 1\'-0"', num: 32 },
  { label: '1/2" = 1\'-0"', num: 24 },
  { label: '1" = 1\'-0"', num: 12 },
]
const MARGIN_IN = 1

export function CreateProjectModal({ onClose, onCreate }: CreateProjectModalProps) {
  const [mode, setMode] = useState<'upload' | 'blank'>('upload')
  const [name, setName] = useState('')
  const [number, setNumber] = useState('')
  const [standard, setStandard] = useState('AISC')
  const [units, setUnits] = useState('imperial')
  const [location, setLocation] = useState('')
  const [description, setDescription] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Blank Project mode state
  const [paperSize, setPaperSize] = useState('ANSI D')
  const [scaleLabel, setScaleLabel] = useState(SCALES[2].label)
  const [pageCount, setPageCount] = useState(1)

  const scaleNum = SCALES.find((s) => s.label === scaleLabel)?.num ?? 48
  const [pw, ph] = PAPER_SIZES[paperSize]
  const drawableWIn = Math.max(pw - MARGIN_IN * 2, 0)
  const drawableHIn = Math.max(ph - MARGIN_IN * 2, 0)
  const drawableWFt = (drawableWIn * scaleNum) / 12
  const drawableHFt = (drawableHIn * scaleNum) / 12
  const fmtFt = (v: number) => `${Math.round(v)}'`

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return

    setLoading(true)
    setError(null)
    try {
      const project = await onCreate({
        name,
        number: number || '',
        design_standard: standard,
        unit_system: units,
        location: location || '',
        description: description || '',
      })
      if (mode === 'blank' && project?.id) {
        await drawingsApi.createBlankPages(project.id, {
          page_count: pageCount,
          paper_size: paperSize,
          scale_label: scaleLabel,
          scale_num: scaleNum,
        })
      }
      onClose()
    } catch (err: any) {
      setError(err.message || 'Failed to create project')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1000,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: 'rgba(0, 0, 0, 0.65)',
        backdropFilter: 'blur(4px)',
        padding: '20px',
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: '480px',
          backgroundColor: '#111827',
          border: '1px solid rgba(59, 130, 246, 0.2)',
          borderRadius: '16px',
          padding: '32px',
          boxShadow: '0 25px 60px rgba(0, 0, 0, 0.65)',
        }}
      >
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: '24px',
          }}
        >
          <h2 style={{ margin: 0, fontSize: '20px', fontWeight: 700, color: '#F1F5F9' }}>
            New Project
          </h2>
          <button
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              color: '#64748B',
              cursor: 'pointer',
              fontSize: '24px',
              lineHeight: 1,
            }}
          >
            &times;
          </button>
        </div>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {/* Upload Drawing vs Blank Project mode toggle */}
          <div style={{ display: 'flex', backgroundColor: '#1E293B', borderRadius: '8px', padding: '3px' }}>
            <button
              type="button"
              onClick={() => setMode('upload')}
              style={{
                flex: 1, padding: '8px', borderRadius: '6px', border: 'none',
                backgroundColor: mode === 'upload' ? '#2563EB' : 'transparent',
                color: mode === 'upload' ? '#FFFFFF' : '#94A3B8',
                fontWeight: 600, fontSize: '12px', cursor: 'pointer', transition: 'all 0.2s',
              }}
            >
              Upload Drawing
            </button>
            <button
              type="button"
              onClick={() => setMode('blank')}
              style={{
                flex: 1, padding: '8px', borderRadius: '6px', border: 'none',
                backgroundColor: mode === 'blank' ? '#2563EB' : 'transparent',
                color: mode === 'blank' ? '#FFFFFF' : '#94A3B8',
                fontWeight: 600, fontSize: '12px', cursor: 'pointer', transition: 'all 0.2s',
              }}
            >
              Blank Project
            </button>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <label style={{ fontSize: '11px', fontWeight: 600, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.6px' }}>
              Project Name *
            </label>
            <input
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. West Tower Framing"
              style={{
                padding: '10px 14px',
                backgroundColor: 'rgba(30, 41, 59, 0.8)',
                border: '1px solid rgba(59, 130, 246, 0.15)',
                borderRadius: '8px',
                color: '#F1F5F9',
                fontSize: '14px',
                outline: 'none',
              }}
            />
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <label style={{ fontSize: '11px', fontWeight: 600, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.6px' }}>
              Project Number
            </label>
            <input
              value={number}
              onChange={(e) => setNumber(e.target.value)}
              placeholder="e.g. SG-2024-001"
              style={{
                padding: '10px 14px',
                backgroundColor: 'rgba(30, 41, 59, 0.8)',
                border: '1px solid rgba(59, 130, 246, 0.15)',
                borderRadius: '8px',
                color: '#F1F5F9',
                fontSize: '14px',
                outline: 'none',
              }}
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <label style={{ fontSize: '11px', fontWeight: 600, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.6px' }}>
                Standard
              </label>
              <select
                value={standard}
                onChange={(e) => setStandard(e.target.value)}
                style={{
                  padding: '10px 14px',
                  backgroundColor: 'rgba(30, 41, 59, 0.8)',
                  border: '1px solid rgba(59, 130, 246, 0.15)',
                  borderRadius: '8px',
                  color: '#F1F5F9',
                  fontSize: '14px',
                  outline: 'none',
                }}
              >
                {STANDARDS.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <label style={{ fontSize: '11px', fontWeight: 600, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.6px' }}>
                Units
              </label>
              <select
                value={units}
                onChange={(e) => setUnits(e.target.value)}
                style={{
                  padding: '10px 14px',
                  backgroundColor: 'rgba(30, 41, 59, 0.8)',
                  border: '1px solid rgba(59, 130, 246, 0.15)',
                  borderRadius: '8px',
                  color: '#F1F5F9',
                  fontSize: '14px',
                  outline: 'none',
                }}
              >
                {UNITS.map((u) => (
                  <option key={u} value={u}>{u}</option>
                ))}
              </select>
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <label style={{ fontSize: '11px', fontWeight: 600, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.6px' }}>
              Location
            </label>
            <input
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              placeholder="e.g. Chicago, IL"
              style={{
                padding: '10px 14px',
                backgroundColor: 'rgba(30, 41, 59, 0.8)',
                border: '1px solid rgba(59, 130, 246, 0.15)',
                borderRadius: '8px',
                color: '#F1F5F9',
                fontSize: '14px',
                outline: 'none',
              }}
            />
          </div>

          {mode === 'blank' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', padding: '14px', backgroundColor: 'rgba(59,130,246,0.05)', border: '1px solid rgba(59,130,246,0.15)', borderRadius: '10px' }}>
              <span style={{ fontSize: '11px', fontWeight: 700, color: '#60A5FA', textTransform: 'uppercase', letterSpacing: '0.6px' }}>
                Blank Sheet Setup
              </span>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <label style={{ fontSize: '11px', fontWeight: 600, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.6px' }}>
                    Paper Size
                  </label>
                  <select
                    value={paperSize}
                    onChange={(e) => setPaperSize(e.target.value)}
                    style={{ padding: '10px 14px', backgroundColor: 'rgba(30, 41, 59, 0.8)', border: '1px solid rgba(59, 130, 246, 0.15)', borderRadius: '8px', color: '#F1F5F9', fontSize: '14px', outline: 'none' }}
                  >
                    {Object.keys(PAPER_SIZES).map((k) => (
                      <option key={k} value={k}>{k} ({PAPER_SIZES[k][0]}"×{PAPER_SIZES[k][1]}")</option>
                    ))}
                  </select>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <label style={{ fontSize: '11px', fontWeight: 600, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.6px' }}>
                    Scale
                  </label>
                  <select
                    value={scaleLabel}
                    onChange={(e) => setScaleLabel(e.target.value)}
                    style={{ padding: '10px 14px', backgroundColor: 'rgba(30, 41, 59, 0.8)', border: '1px solid rgba(59, 130, 246, 0.15)', borderRadius: '8px', color: '#F1F5F9', fontSize: '14px', outline: 'none' }}
                  >
                    {SCALES.map((s) => (
                      <option key={s.label} value={s.label}>{s.label}</option>
                    ))}
                  </select>
                </div>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <label style={{ fontSize: '11px', fontWeight: 600, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.6px' }}>
                  Number of Sheets
                </label>
                <input
                  type="number"
                  min={1}
                  max={50}
                  value={pageCount}
                  onChange={(e) => setPageCount(Math.max(1, Math.min(50, parseInt(e.target.value) || 1)))}
                  style={{ padding: '10px 14px', backgroundColor: 'rgba(30, 41, 59, 0.8)', border: '1px solid rgba(59, 130, 246, 0.15)', borderRadius: '8px', color: '#F1F5F9', fontSize: '14px', outline: 'none' }}
                />
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', padding: '8px 10px', backgroundColor: 'rgba(59,130,246,0.08)', borderRadius: '6px' }}>
                <span style={{ color: '#94A3B8' }}>Drawable area at this scale:</span>
                <span style={{ color: '#F1F5F9', fontWeight: 700 }}>{fmtFt(drawableWFt)} × {fmtFt(drawableHFt)}</span>
              </div>
            </div>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <label style={{ fontSize: '11px', fontWeight: 600, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.6px' }}>
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Project description or notes..."
              rows={3}
              style={{
                padding: '10px 14px',
                backgroundColor: 'rgba(30, 41, 59, 0.8)',
                border: '1px solid rgba(59, 130, 246, 0.15)',
                borderRadius: '8px',
                color: '#F1F5F9',
                fontSize: '14px',
                outline: 'none',
                resize: 'none',
              }}
            />
          </div>

          {error && (
            <div
              style={{
                padding: '10px 14px',
                backgroundColor: 'rgba(239, 68, 68, 0.08)',
                border: '1px solid rgba(239, 68, 68, 0.2)',
                borderRadius: '8px',
                color: '#F87171',
                fontSize: '13px',
              }}
            >
              &#9888; {error}
            </div>
          )}

          <div style={{ display: 'flex', gap: '10px', marginTop: '12px' }}>
            <button
              type="button"
              onClick={onClose}
              style={{
                flex: 1,
                padding: '12px',
                backgroundColor: 'transparent',
                border: '1px solid rgba(100, 116, 139, 0.25)',
                borderRadius: '8px',
                color: '#94A3B8',
                fontSize: '14px',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              style={{
                flex: 2,
                padding: '12px',
                backgroundColor: loading ? '#1D4ED8' : '#3B82F6',
                border: 'none',
                borderRadius: '8px',
                color: '#FFFFFF',
                fontSize: '14px',
                fontWeight: 600,
                cursor: loading ? 'not-allowed' : 'pointer',
                boxShadow: '0 4px 14px rgba(59, 130, 246, 0.35)',
              }}
            >
              {loading ? 'Creating...' : 'Create Project'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
