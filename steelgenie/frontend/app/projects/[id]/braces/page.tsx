'use client'

import React, { useEffect, useState, useCallback, useRef } from 'react'
import { useParams } from 'next/navigation'
import { buildApi, schedulersApi, jobsApi } from '../../../../lib/api'
import { Spinner } from '../../../../components/ui/Spinner'
import { Hammer, GitBranch, Pencil, Search } from 'lucide-react'
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
  for (;;) {
    const job = await jobsApi.get(jobId)
    onProgress(job.progress ?? 0, job.message ?? '')
    if (job.status === 'done') return job
    if (job.status === 'failed') throw new Error(job.error || 'Build failed')
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
      <line x1={0} y1={8} x2={W} y2={8} stroke="#334155" strokeWidth={2} />
      <line x1={0} y1={H - 8} x2={W} y2={H - 8} stroke="#334155" strokeWidth={2} />
      <line x1={4} y1={8} x2={4} y2={H - 8} stroke="#3B82F6" strokeWidth={3} />
      <line x1={W - 4} y1={8} x2={W - 4} y2={H - 8} stroke="#3B82F6" strokeWidth={3} />

      {Array.from({ length: bays }).map((_, i) => {
        const x0 = i * bayW
        const x1 = x0 + bayW
        const flip = i % 2 === 1
        return (
          <g key={i}>
            {i > 0 && <line x1={x0} y1={8} x2={x0} y2={H - 8} stroke="#1E293B" strokeWidth={1.5} />}
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
      width: '280px', flexShrink: 0, backgroundColor: '#111827',
      border: '1px solid rgba(59,130,246,0.08)', borderRadius: '10px',
      overflow: 'hidden', display: 'flex', flexDirection: 'column',
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: '10px 12px', backgroundColor: 'rgba(217, 119, 6, 0.85)',
      }}>
        <span style={{ fontSize: '13px', fontWeight: 700, color: '#FFFFFF' }}>{f.name}</span>
      </div>

      <div style={{ padding: '16px 18px', backgroundColor: '#0B1220', display: 'flex', justifyContent: 'center' }}>
        <BraceElevation frame={f} />
      </div>

      <div style={{ padding: '10px 14px 4px', display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '6px' }}>
        <span style={{ fontSize: '12px', color: '#94A3B8' }}>{f.connection_method || 'Welded Gusset'}</span>
        <Pencil size={11} color="#3B82F6" style={{ cursor: 'pointer' }} onClick={() => toast.info('Connection method editing coming soon')} />
      </div>

      <div style={{ padding: '10px 14px', display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
        <span style={{ fontSize: '11px', padding: '3px 8px', borderRadius: '999px', backgroundColor: 'rgba(217,119,6,0.14)', color: '#F59E0B', fontWeight: 600 }}>
          {FRAME_TYPE_LABEL[f.frame_type || ''] || f.frame_type || 'Non-Seismic'}
        </span>
        <span style={{ fontSize: '11px', padding: '3px 8px', borderRadius: '999px', backgroundColor: 'rgba(255,255,255,0.05)', color: '#94A3B8' }}>
          {f.brace_count} member{f.brace_count === 1 ? '' : 's'}
        </span>
      </div>

      <div style={{ padding: '4px 14px 14px' }}>
        <div style={{
          display: 'flex', justifyContent: 'space-between', gap: '8px', padding: '8px 10px',
          backgroundColor: '#1E293B', borderRadius: '6px', fontSize: '11px',
        }}>
          <span style={{ color: '#64748B', fontWeight: 600, flexShrink: 0 }}>Sections:</span>
          <span style={{ color: '#F1F5F9', textAlign: 'right', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {f.sections?.join(', ') || '—'}
          </span>
        </div>
      </div>
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

  const containerStyle: React.CSSProperties = {
    display: 'flex', flexDirection: 'column', height: '100%', padding: '24px', boxSizing: 'border-box', overflow: 'hidden',
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
          <h1 style={{ margin: 0, fontSize: '20px', fontWeight: 700, color: '#F1F5F9' }}>Braced Frames Scheduler</h1>
          <p style={{ margin: '4px 0 0', fontSize: '13px', color: '#64748B' }}>
            Schedule vertical braced frames, diagonals, gusset design capacity, and frame elevations
          </p>
        </div>
        <div
          style={{
            flex: 1, border: '1px dashed rgba(59, 130, 246, 0.15)', borderRadius: '12px',
            backgroundColor: 'rgba(30, 41, 59, 0.15)', display: 'flex', flexDirection: 'column',
            alignItems: 'center', justifyContent: 'center', padding: '40px', textAlign: 'center', gap: '16px',
          }}
        >
          <GitBranch size={36} style={{ color: '#3B82F6' }} />
          <div>
            <h3 style={{ margin: '0 0 8px', fontSize: '16px', fontWeight: 600, color: '#94A3B8' }}>
              Build the project first
            </h3>
            <p style={{ margin: 0, fontSize: '13px', color: '#475569', maxWidth: '420px', lineHeight: 1.5 }}>
              Braced frames are generated by the build engine, grouping vertical/horizontal brace
              members by sheet into elevations with their seismic frame type and connection method.
            </p>
          </div>
          <button
            onClick={runBuild}
            disabled={building}
            style={{
              display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 20px',
              backgroundColor: building ? 'rgba(59,130,246,0.2)' : '#3B82F6', border: 'none', borderRadius: '6px',
              color: '#fff', fontSize: '13px', fontWeight: 600, cursor: building ? 'not-allowed' : 'pointer',
            }}
          >
            <Hammer size={14} /> {building ? buildMsg || 'Building…' : 'Build Project'}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div style={containerStyle}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', flexWrap: 'wrap', gap: '12px', flexShrink: 0 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: '20px', fontWeight: 700, color: '#F1F5F9' }}>Braced Frames Scheduler</h1>
          <p style={{ margin: '4px 0 0', fontSize: '13px', color: '#64748B' }}>{frames.length} braced elevation(s)</p>
        </div>
        <button
          onClick={runBuild}
          disabled={building}
          style={{
            display: 'flex', alignItems: 'center', gap: '6px', padding: '8px 16px',
            backgroundColor: building ? 'rgba(59,130,246,0.15)' : 'rgba(59,130,246,0.1)',
            border: '1px solid rgba(59,130,246,0.25)', borderRadius: '6px',
            color: building ? '#475569' : '#60A5FA', fontSize: '13px', fontWeight: 600, cursor: building ? 'not-allowed' : 'pointer',
          }}
        >
          <Hammer size={14} /> {building ? buildMsg || 'Rebuilding…' : 'Rebuild'}
        </button>
      </div>

      <div style={{ flex: 1, display: 'flex', gap: '16px', minHeight: 0 }}>
        {/* Left Navigation — searchable list of every brace elevation */}
        <div style={{ width: '220px', flexShrink: 0, backgroundColor: '#111827', border: '1px solid rgba(59,130,246,0.08)', borderRadius: '8px', padding: '14px', display: 'flex', flexDirection: 'column', gap: '10px', overflowY: 'auto' }}>
          <div style={{ position: 'relative' }}>
            <Search size={13} style={{ position: 'absolute', left: '9px', top: '9px', color: '#475569' }} />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by section…"
              style={{
                width: '100%', boxSizing: 'border-box', padding: '7px 10px 7px 28px', backgroundColor: '#1F2937',
                border: '1px solid rgba(59, 130, 246, 0.15)', borderRadius: '6px', color: '#F1F5F9', fontSize: '12px', outline: 'none',
              }}
            />
          </div>
          {frames.filter(matchesSearch).length === 0 && (
            <span style={{ fontSize: '12px', color: '#475569', padding: '8px 2px' }}>No matches</span>
          )}
          {frames.filter(matchesSearch).map((f) => (
            <button
              key={f.id}
              onClick={() => jumpToFrame(f.id)}
              style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center', textAlign: 'left',
                padding: '8px 10px', backgroundColor: '#1E293B', border: 'none', borderRadius: '6px',
                cursor: 'pointer', color: '#F1F5F9', fontSize: '12px',
              }}
            >
              <span style={{ fontWeight: 600 }}>{f.name}</span>
              <span style={{ fontSize: '11px', color: '#64748B' }}>{f.brace_count}</span>
            </button>
          ))}
        </div>

        <div ref={scrollRowRef} style={{ flex: 1, display: 'flex', gap: '16px', overflowX: 'auto', overflowY: 'hidden', paddingBottom: '8px' }}>
          {frames.filter(matchesSearch).map((f) => (
            <div key={f.id} ref={(el) => { cardRefs.current[f.id] = el }}>
              <BraceCard frame={f} />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
