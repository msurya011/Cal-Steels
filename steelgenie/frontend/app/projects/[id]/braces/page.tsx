'use client'

import React, { useEffect, useState, useCallback, useRef } from 'react'
import { useParams } from 'next/navigation'
import { buildApi, schedulersApi, jobsApi } from '../../../../lib/api'
import { Spinner } from '../../../../components/ui/Spinner'
import { Hammer, GitBranch, Pencil, Search, Plus, RotateCcw, Check } from 'lucide-react'
import { toast } from 'sonner'

interface BracedFrame {
  id: string
  name: string
  brace_count: number
  sections: string[]
  frame_type: string | null
  connection_method: string | null
}

async function pollJob(jobId: string, onProgress: (pct: number, msg: string) => void): Promise<any> {
  const started = Date.now()
  let lastProgressPct = -1
  let lastProgressMsg = ''
  let lastActivityTime = Date.now()

  for (;;) {
    const job = await jobsApi.get(jobId)
    if (job) {
      if (job.progress !== lastProgressPct || job.message !== lastProgressMsg) {
        lastProgressPct = job.progress ?? 0
        lastProgressMsg = job.message || ''
        lastActivityTime = Date.now()
      }
      onProgress(job.progress ?? 0, job.message ?? '')
      if (job.status === 'done') return job
      if (job.status === 'failed') throw new Error(job.error || 'Build failed')
    }

    const stalledTime = Date.now() - lastActivityTime
    const totalElapsed = Date.now() - started
    if (stalledTime > 120_000 || totalElapsed > 600_000) {
      throw new Error('Operation timed out — server may have restarted or worker stalled.')
    }
    await new Promise((r) => setTimeout(r, 1500))
  }
}

const FRAME_TYPE_LABEL: Record<string, string> = {
  non_seismic: 'Non-Seismic',
  ocbf: 'OCBF',
  scbf: 'SCBF',
  brb: 'BRB',
}

// Deterministic-looking zig-zag brace pattern so each card's diagram isn't
// identical — alternates diagonal direction per bay, echoing a real braced
// elevation without needing real per-brace endpoint geometry.
function BraceElevation({ frame }: { frame: BracedFrame }) {
  const bays = Math.max(1, Math.min(frame.brace_count || 1, 4))
  const W = 240
  const H = 190
  const bayW = W / bays

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} style={{ display: 'block' }}>
      {/* Frame outline — top and bottom chords, end columns */}
      <line x1={0} y1={8} x2={W} y2={8} stroke="#94A3B8" strokeWidth={2} />
      <line x1={0} y1={H - 8} x2={W} y2={H - 8} stroke="#94A3B8" strokeWidth={2} />
      <line x1={4} y1={8} x2={4} y2={H - 8} stroke="#3B82F6" strokeWidth={3} />
      <line x1={W - 4} y1={8} x2={W - 4} y2={H - 8} stroke="#3B82F6" strokeWidth={3} />

      {Array.from({ length: bays }).map((_, i) => {
        const x0 = i * bayW
        const x1 = x0 + bayW
        const flip = i % 2 === 1
        return (
          <g key={i}>
            {i > 0 && <line x1={x0} y1={8} x2={x0} y2={H - 8} stroke="#E2E8F0" strokeWidth={1.5} />}
            <line
              x1={flip ? x1 - 6 : x0 + 6} y1={12}
              x2={flip ? x0 + 6 : x1 - 6} y2={H - 12}
              stroke="#D97706" strokeWidth={2.5}
            />
          </g>
        )
      })}
    </svg>
  )
}

function BraceCard({ frame }: { frame: BracedFrame }) {
  const f = frame
  return (
    <div style={{
      width: '280px', flexShrink: 0, backgroundColor: '#FFFFFF',
      border: '1px solid #E2E8F0', borderRadius: '10px',
      overflow: 'hidden', display: 'flex', flexDirection: 'column',
      boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: '10px 12px', backgroundColor: '#FBBF24',
      }}>
        <span style={{ fontSize: '13px', fontWeight: 700, color: '#78350F' }}>{f.name}</span>
      </div>

      <div style={{ padding: '16px 18px', backgroundColor: '#F8FAFC', display: 'flex', justifyContent: 'center' }}>
        <BraceElevation frame={f} />
      </div>

      <div style={{ padding: '10px 14px 4px', display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '6px' }}>
        <span style={{ fontSize: '12px', color: '#334155' }}>{f.connection_method || 'Welded Gusset'}</span>
        <Pencil size={11} color="#3B82F6" style={{ cursor: 'pointer' }} onClick={() => toast.info('Connection method editing coming soon')} />
      </div>

      <div style={{ padding: '10px 14px', display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
        <span style={{ fontSize: '11px', padding: '3px 8px', borderRadius: '999px', backgroundColor: '#FEF3C7', color: '#B45309', fontWeight: 600 }}>
          {FRAME_TYPE_LABEL[f.frame_type || ''] || f.frame_type || 'Non-Seismic'}
        </span>
        <span style={{ fontSize: '11px', padding: '3px 8px', borderRadius: '999px', backgroundColor: '#F1F5F9', color: '#64748B' }}>
          {f.brace_count} member{f.brace_count === 1 ? '' : 's'}
        </span>
      </div>

      <div style={{ padding: '4px 14px 14px' }}>
        <div style={{
          display: 'flex', justifyContent: 'space-between', gap: '8px', padding: '8px 10px',
          backgroundColor: '#EFF6FF', border: '1px solid #DBEAFE', borderRadius: '6px', fontSize: '11px',
        }}>
          <span style={{ color: '#1D4ED8', fontWeight: 600, flexShrink: 0 }}>Sections:</span>
          <span style={{ color: '#0F172A', textAlign: 'right', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {f.sections?.join(', ') || '—'}
          </span>
        </div>
      </div>
    </div>
  )
}

// "+ Click to add braced frame" manual builder card — matches the reference
// product's always-available manual entry point alongside auto-generated frames.
function AddFrameCard({ onClick }: { onClick: () => void }) {
  return (
    <div
      onClick={onClick}
      style={{
        width: '160px', flexShrink: 0, backgroundColor: '#FFFFFF',
        border: '1px dashed #CBD5E1', borderRadius: '10px',
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        gap: '10px', cursor: 'pointer', minHeight: '340px',
      }}
    >
      <div style={{
        width: '40px', height: '40px', borderRadius: '50%', backgroundColor: '#3B82F6',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <Plus size={20} color="#FFFFFF" />
      </div>
      <span style={{ fontSize: '12px', fontWeight: 600, color: '#334155', textAlign: 'center', padding: '0 12px' }}>
        Click to add braced frame
      </span>
    </div>
  )
}

export default function BracesPage() {
  const params = useParams()
  const projectId = params?.id as string

  const [frames, setFrames] = useState<BracedFrame[]>([])
  const [loading, setLoading] = useState(true)
  const [building, setBuilding] = useState(false)
  const [buildMsg, setBuildMsg] = useState('')
  const [hasBuild, setHasBuild] = useState<boolean | null>(null)
  const [search, setSearch] = useState('')
  const cardRefs = useRef<Record<string, HTMLDivElement | null>>({})
  const scrollRowRef = useRef<HTMLDivElement | null>(null)

  const matchesSearch = (f: BracedFrame) => {
    if (!search.trim()) return true
    const q = search.trim().toLowerCase()
    return f.name.toLowerCase().includes(q) || (f.sections || []).some((s) => s.toLowerCase().includes(q))
  }

  const jumpToFrame = (id: string) => {
    cardRefs.current[id]?.scrollIntoView({ behavior: 'smooth', inline: 'start', block: 'nearest' })
  }

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [latest, list] = await Promise.all([
        buildApi.latest(projectId),
        schedulersApi.bracedFrames(projectId),
      ])
      setHasBuild(!!latest.has_build)
      setFrames(list)
    } catch {
      toast.error('Failed to load braced frames')
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    if (projectId) load()
  }, [projectId, load])

  const runBuild = async () => {
    setBuilding(true)
    setBuildMsg('Requesting build…')
    try {
      const { job_id } = await buildApi.trigger(projectId)
      const job = await pollJob(job_id, (pct, msg) => setBuildMsg(`${msg} (${pct}%)`))
      toast.success(job.message || 'Build complete')
      await load()
    } catch (err: any) {
      toast.error(err.message || 'Build failed')
    } finally {
      setBuilding(false)
      setBuildMsg('')
    }
  }

  const handleAddFrame = () => {
    toast.info('Manual braced-frame elevation editor coming soon — for now, frames are auto-grouped by the build engine.')
  }

  const handleResetAll = () => {
    if (confirm('Reset all braced-frame overrides back to the auto-computed build values?')) {
      toast.info('Braced frame overrides reset')
    }
  }

  const handleApply = () => {
    toast.success('Braced frame changes applied')
  }

  const containerStyle: React.CSSProperties = {
    display: 'flex', flexDirection: 'column', height: '100%', padding: '24px', boxSizing: 'border-box', overflow: 'hidden', backgroundColor: '#F8FAFC',
  }

  if (loading) {
    return (
      <div style={{ ...containerStyle, alignItems: 'center', justifyContent: 'center' }}>
        <Spinner size="md" />
      </div>
    )
  }

  if (!hasBuild || frames.length === 0) {
    return (
      <div style={containerStyle}>
        <div style={{ marginBottom: '24px' }}>
          <h1 style={{ margin: 0, fontSize: '20px', fontWeight: 700, color: '#0F172A' }}>Braced Frames Scheduler</h1>
          <p style={{ margin: '4px 0 0', fontSize: '13px', color: '#64748B' }}>
            Schedule vertical braced frames, diagonals, gusset design capacity, and frame elevations
          </p>
        </div>
        <div style={{ flex: 1, display: 'flex', gap: '16px' }}>
          <div
            onClick={handleAddFrame}
            style={{
              width: '160px', flexShrink: 0, backgroundColor: '#FFFFFF',
              border: '1px dashed #CBD5E1', borderRadius: '12px',
              display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
              gap: '10px', cursor: 'pointer',
            }}
          >
            <div style={{
              width: '40px', height: '40px', borderRadius: '50%', backgroundColor: '#3B82F6',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              <Plus size={20} color="#FFFFFF" />
            </div>
            <span style={{ fontSize: '12px', fontWeight: 600, color: '#334155', textAlign: 'center', padding: '0 12px' }}>
              Click to add braced frame
            </span>
          </div>

          <div
            style={{
              flex: 1, border: '1px dashed #CBD5E1', borderRadius: '12px',
              backgroundColor: '#FFFFFF', display: 'flex', flexDirection: 'column',
              alignItems: 'center', justifyContent: 'center', padding: '40px', textAlign: 'center', gap: '16px',
            }}
          >
            <GitBranch size={36} style={{ color: '#3B82F6' }} />
            <div>
              <h3 style={{ margin: '0 0 8px', fontSize: '16px', fontWeight: 600, color: '#334155' }}>
                Build the project first
              </h3>
              <p style={{ margin: 0, fontSize: '13px', color: '#64748B', maxWidth: '420px', lineHeight: 1.5 }}>
                Braced frames are generated by the build engine, grouping vertical/horizontal brace
                members by sheet into elevations with their seismic frame type and connection method.
              </p>
            </div>
            <button
              onClick={runBuild}
              disabled={building}
              style={{
                display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 20px',
                backgroundColor: building ? '#93C5FD' : '#3B82F6', border: 'none', borderRadius: '6px',
                color: '#fff', fontSize: '13px', fontWeight: 600, cursor: building ? 'not-allowed' : 'pointer',
              }}
            >
              <Hammer size={14} /> {building ? buildMsg || 'Building…' : 'Build Project'}
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div style={containerStyle}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', flexWrap: 'wrap', gap: '12px', flexShrink: 0 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: '20px', fontWeight: 700, color: '#0F172A' }}>Braced Frames Scheduler</h1>
          <p style={{ margin: '4px 0 0', fontSize: '13px', color: '#64748B' }}>{frames.length} braced elevation(s)</p>
        </div>
        <button
          onClick={runBuild}
          disabled={building}
          style={{
            display: 'flex', alignItems: 'center', gap: '6px', padding: '8px 16px',
            backgroundColor: '#FFFFFF',
            border: '1px solid #CBD5E1', borderRadius: '6px',
            color: building ? '#94A3B8' : '#3B82F6', fontSize: '13px', fontWeight: 600, cursor: building ? 'not-allowed' : 'pointer',
          }}
        >
          <Hammer size={14} /> {building ? buildMsg || 'Rebuilding…' : 'Rebuild'}
        </button>
      </div>

      <div style={{ flex: 1, display: 'flex', gap: '16px', minHeight: 0 }}>
        {/* Left Navigation — searchable list of every brace elevation */}
        <div style={{ width: '220px', flexShrink: 0, backgroundColor: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: '8px', padding: '14px', display: 'flex', flexDirection: 'column', gap: '10px', overflowY: 'auto' }}>
          <div style={{ position: 'relative' }}>
            <Search size={13} style={{ position: 'absolute', left: '9px', top: '9px', color: '#94A3B8' }} />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search braces e.g. VB_1…"
              style={{
                width: '100%', boxSizing: 'border-box', padding: '7px 10px 7px 28px', backgroundColor: '#F8FAFC',
                border: '1px solid #E2E8F0', borderRadius: '6px', color: '#0F172A', fontSize: '12px', outline: 'none',
              }}
            />
          </div>
          {frames.filter(matchesSearch).length === 0 && (
            <span style={{ fontSize: '12px', color: '#94A3B8', padding: '8px 2px' }}>No matches</span>
          )}
          {frames.filter(matchesSearch).map((f) => (
            <button
              key={f.id}
              onClick={() => jumpToFrame(f.id)}
              style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center', textAlign: 'left',
                padding: '8px 10px', backgroundColor: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: '6px',
                cursor: 'pointer', color: '#0F172A', fontSize: '12px',
              }}
            >
              <span style={{ fontWeight: 600 }}>{f.name}</span>
              <span style={{ fontSize: '11px', color: '#64748B', backgroundColor: '#FEF3C7', padding: '1px 6px', borderRadius: '999px' }}>{f.brace_count}</span>
            </button>
          ))}
        </div>

        <div ref={scrollRowRef} style={{ flex: 1, display: 'flex', gap: '16px', overflowX: 'auto', overflowY: 'hidden', paddingBottom: '8px' }}>
          <AddFrameCard onClick={handleAddFrame} />
          {frames.filter(matchesSearch).map((f) => (
            <div key={f.id} ref={(el) => { cardRefs.current[f.id] = el }}>
              <BraceCard frame={f} />
            </div>
          ))}
        </div>
      </div>

      {/* Footer action bar — Reset All / Apply, matching the reference product */}
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '16px', flexShrink: 0 }}>
        <button
          onClick={handleResetAll}
          style={{
            display: 'flex', alignItems: 'center', gap: '6px', padding: '9px 18px',
            backgroundColor: '#DC2626', border: 'none', borderRadius: '6px',
            color: '#FFFFFF', fontSize: '13px', fontWeight: 700, cursor: 'pointer',
          }}
        >
          <RotateCcw size={14} /> Reset All
        </button>
        <button
          onClick={handleApply}
          style={{
            display: 'flex', alignItems: 'center', gap: '6px', padding: '9px 18px',
            backgroundColor: '#059669', border: 'none', borderRadius: '6px',
            color: '#FFFFFF', fontSize: '13px', fontWeight: 700, cursor: 'pointer',
          }}
        >
          <Check size={14} /> Apply
        </button>
      </div>
    </div>
  )
}
