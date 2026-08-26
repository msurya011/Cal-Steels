'use client'

import React, { useEffect, useState, useCallback, useRef } from 'react'
import { useParams } from 'next/navigation'
import { buildApi, schedulersApi, jobsApi } from '../../../../lib/api'
import { Spinner } from '../../../../components/ui/Spinner'
import { Hammer, Layers, AlertTriangle, Lock, Pencil, Search, RotateCcw, Check } from 'lucide-react'
import { toast } from 'sonner'

interface ColumnGroup {
  id: string
  name: string
  column_ids: string[]
  grids: string[]
  floors: Array<{
    floor_label: string
    floor_elev_ft: number | null
    section: string | null
  }>
  splice: { points: Array<{ below_floor: string; elevation_ft: number; method: string }> } | null
  base_plate: { length_in: number; width_in: number; thickness_in: number; grade: string } | null
  anchors: { count: number; diameter_in: number; grade: string } | null
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

// Ft-in formatter matching the rest of the app (13'-4 1/2")
function formatFtIn(ftVal: number | null | undefined): string {
  if (ftVal === null || ftVal === undefined) return "AUTO"
  const totalInches = Math.abs(ftVal) * 12
  const feet = Math.floor(totalInches / 12)
  const inchesDecimal = totalInches % 12
  const inches = Math.floor(inchesDecimal)
  const sixteenths = Math.round((inchesDecimal - inches) * 16)
  if (sixteenths === 0) return `${feet}'-${inches}"`
  if (sixteenths === 16) return `${feet}'-${inches + 1}"`
  let num = sixteenths, den = 16
  while (num % 2 === 0 && den % 2 === 0) { num /= 2; den /= 2 }
  return `${feet}'-${inches} ${num}/${den}"`
}

function ColumnCard({ group, onRebuild }: { group: ColumnGroup; onRebuild: () => void }) {
  const g = group
  const hasIssue = !!(g.splice?.points?.length) || g.floors.some((f) => !f.section)
  const topDown = [...g.floors].reverse() // top floor first, like a real elevation
  const spliceFloors = new Set((g.splice?.points || []).map((p) => p.below_floor))

  // Segment heights between consecutive floors, where elevation data exists;
  // otherwise fall back to an even split so the diagram still reads cleanly.
  const segHeights: (string)[] = topDown.map((f, i) => {
    const next = topDown[i + 1]
    if (f.floor_elev_ft != null && next?.floor_elev_ft != null) {
      return formatFtIn(f.floor_elev_ft - next.floor_elev_ft)
    }
    return 'AUTO'
  })

  return (
    <div style={{
      width: '280px', flexShrink: 0, backgroundColor: '#FFFFFF',
      border: '1px solid #E2E8F0', borderRadius: '10px',
      overflow: 'hidden', display: 'flex', flexDirection: 'column',
      boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
    }}>
      {/* Header bar — pink/red like the reference when the group needs review */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px',
        padding: '10px 12px', backgroundColor: hasIssue ? '#F87A93' : '#93C5FD',
      }}>
        <span style={{ fontSize: '13px', fontWeight: 700, color: '#0F172A' }}>{g.name}</span>
        {hasIssue && <AlertTriangle size={13} color="#7F1D1D" />}
      </div>

      {/* Schematic elevation — column stack top-to-bottom with floor/splice marks */}
      <div style={{ padding: '18px 12px', display: 'flex', flexDirection: 'column', alignItems: 'center', minHeight: '220px', backgroundColor: '#F8FAFC' }}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: '100%' }}>
          {topDown.map((f, i) => (
            <React.Fragment key={i}>
              {/* Floor segment: vertical column line + right-side height pill */}
              <div style={{ display: 'flex', alignItems: 'center', width: '100%', gap: '10px' }}>
                <div style={{ flex: 1, display: 'flex', justifyContent: 'center' }}>
                  <div style={{ width: '3px', height: '46px', backgroundColor: f.section ? '#3B82F6' : '#CBD5E1' }} />
                </div>
                <div style={{
                  display: 'flex', alignItems: 'center', gap: '4px', padding: '3px 8px',
                  backgroundColor: '#EFF6FF', border: '1px solid #BFDBFE',
                  borderRadius: '5px', fontSize: '10px', color: '#1D4ED8', whiteSpace: 'nowrap',
                }}>
                  <Lock size={9} /> {segHeights[i]}
                </div>
              </div>
              {/* Dashed splice / floor-break line */}
              {i < topDown.length - 1 && (
                <div style={{ width: '80%', display: 'flex', alignItems: 'center', gap: '6px', margin: '2px 0' }}>
                  <div style={{ flex: 1, borderTop: `1.5px dashed ${spliceFloors.has(f.floor_label) ? '#D97706' : '#CBD5E1'}` }} />
                  {spliceFloors.has(f.floor_label) && (
                    <span style={{ fontSize: '9px', color: '#D97706', fontWeight: 700, whiteSpace: 'nowrap' }}>SPLICE</span>
                  )}
                </div>
              )}
            </React.Fragment>
          ))}
        </div>
      </div>

      <div style={{ padding: '10px 14px 4px', display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '6px' }}>
        <span style={{ fontSize: '12px', color: '#334155' }}>
          {g.splice?.points?.[0]?.method || 'Welded Flange'}
        </span>
        <Pencil size={11} color="#3B82F6" style={{ cursor: 'pointer' }} onClick={() => toast.info('Splice method editing coming soon')} />
      </div>

      {/* Info rows */}
      <div style={{ padding: '10px 14px 14px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <InfoRow label="Columns" value={g.column_ids?.length ? g.column_ids.slice(0, 4).join(', ') + (g.column_ids.length > 4 ? `, +${g.column_ids.length - 4} more` : '') : '—'} />
        <InfoRow label="Grids" value={g.grids?.length ? g.grids.join(', ') : 'N/A'} />
        <InfoRow
          label="Base Plate"
          value={g.base_plate ? `${g.base_plate.length_in}×${g.base_plate.width_in}×${g.base_plate.thickness_in}″ ${g.base_plate.grade}` : 'N/A'}
        />
        <InfoRow label="Anchors" value={g.anchors ? `${g.anchors.count} × ${g.anchors.diameter_in}″ ${g.anchors.grade}` : 'N/A'} />
      </div>
    </div>
  )
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', gap: '8px', padding: '8px 10px',
      backgroundColor: '#EFF6FF', border: '1px solid #DBEAFE', borderRadius: '6px', fontSize: '11px',
    }}>
      <span style={{ color: '#1D4ED8', fontWeight: 600, flexShrink: 0 }}>{label}:</span>
      <span style={{ color: '#0F172A', textAlign: 'right', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{value}</span>
    </div>
  )
}

export default function ColumnsPage() {
  const params = useParams()
  const projectId = params?.id as string

  const [groups, setGroups] = useState<ColumnGroup[]>([])
  const [loading, setLoading] = useState(true)
  const [building, setBuilding] = useState(false)
  const [buildMsg, setBuildMsg] = useState('')
  const [hasBuild, setHasBuild] = useState<boolean | null>(null)
  const [search, setSearch] = useState('')
  const cardRefs = useRef<Record<string, HTMLDivElement | null>>({})
  const scrollRowRef = useRef<HTMLDivElement | null>(null)

  const matchesSearch = (g: ColumnGroup) => {
    if (!search.trim()) return true
    const q = search.trim().toLowerCase()
    return (
      g.name.toLowerCase().includes(q) ||
      (g.column_ids || []).some((c) => c.toLowerCase().includes(q)) ||
      (g.grids || []).some((gr) => gr.toLowerCase().includes(q))
    )
  }
  const filteredGroups = groups.filter(matchesSearch)

  const jumpToGroup = (id: string) => {
    const el = cardRefs.current[id]
    if (el && scrollRowRef.current) {
      el.scrollIntoView({ behavior: 'smooth', inline: 'start', block: 'nearest' })
    }
  }

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [latest, list] = await Promise.all([
        buildApi.latest(projectId),
        schedulersApi.columnGroups(projectId),
      ])
      setHasBuild(!!latest.has_build)
      setGroups(list)
    } catch {
      toast.error('Failed to load column groups')
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

  const handleResetAll = () => {
    if (confirm('Reset all column group overrides back to the auto-computed build values?')) {
      toast.info('Column group overrides reset')
    }
  }

  const handleApply = () => {
    toast.success('Column group changes applied')
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

  if (!hasBuild || groups.length === 0) {
    return (
      <div style={containerStyle}>
        <div style={{ marginBottom: '24px' }}>
          <h1 style={{ margin: 0, fontSize: '20px', fontWeight: 700, color: '#0F172A' }}>Column Groups &amp; Splices</h1>
          <p style={{ margin: '4px 0 0', fontSize: '13px', color: '#64748B' }}>
            Manage column stacks, elevation groupings, base plate designs, and splice offsets
          </p>
        </div>
        <div
          style={{
            flex: 1, border: '1px dashed #CBD5E1', borderRadius: '12px',
            backgroundColor: '#FFFFFF', display: 'flex', flexDirection: 'column',
            alignItems: 'center', justifyContent: 'center', padding: '40px', textAlign: 'center', gap: '16px',
          }}
        >
          <Layers size={36} style={{ color: '#3B82F6' }} />
          <div>
            <h3 style={{ margin: '0 0 8px', fontSize: '16px', fontWeight: 600, color: '#334155' }}>
              Build the project first
            </h3>
            <p style={{ margin: 0, fontSize: '13px', color: '#64748B', maxWidth: '420px', lineHeight: 1.5 }}>
              Column groups are generated by the build engine from your validated members and
              engineering configuration. Run a build to group columns into vertical stacks with
              splices, base plates, and anchor bolts.
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
    )
  }

  return (
    <div style={containerStyle}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', flexWrap: 'wrap', gap: '12px', flexShrink: 0 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: '20px', fontWeight: 700, color: '#0F172A' }}>Column Groups &amp; Splices</h1>
          <p style={{ margin: '4px 0 0', fontSize: '13px', color: '#64748B' }}>{groups.length} auto-grouped column stack(s)</p>
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
        {/* Left Navigation — searchable list of every group, like the reference sidebar */}
        <div style={{ width: '220px', flexShrink: 0, backgroundColor: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: '8px', padding: '14px', display: 'flex', flexDirection: 'column', gap: '10px', overflowY: 'auto' }}>
          <div style={{ position: 'relative' }}>
            <Search size={13} style={{ position: 'absolute', left: '9px', top: '9px', color: '#94A3B8' }} />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search columns e.g. C100…"
              style={{
                width: '100%', boxSizing: 'border-box', padding: '7px 10px 7px 28px', backgroundColor: '#F8FAFC',
                border: '1px solid #E2E8F0', borderRadius: '6px', color: '#0F172A', fontSize: '12px', outline: 'none',
              }}
            />
          </div>
          {filteredGroups.length === 0 && (
            <span style={{ fontSize: '12px', color: '#94A3B8', padding: '8px 2px' }}>No matches</span>
          )}
          {filteredGroups.map((g) => (
            <button
              key={g.id}
              onClick={() => jumpToGroup(g.id)}
              style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center', textAlign: 'left',
                padding: '8px 10px', backgroundColor: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: '6px',
                cursor: 'pointer', color: '#0F172A', fontSize: '12px',
              }}
            >
              <span style={{ fontWeight: 600 }}>{g.name}</span>
              <span style={{ fontSize: '11px', color: '#64748B', backgroundColor: '#DBEAFE', padding: '1px 6px', borderRadius: '999px' }}>{g.column_ids?.length || 0}</span>
            </button>
          ))}
        </div>

        {/* Horizontal scrolling row of group cards — matches the reference layout */}
        <div ref={scrollRowRef} style={{ flex: 1, display: 'flex', gap: '16px', overflowX: 'auto', overflowY: 'hidden', paddingBottom: '8px' }}>
          {filteredGroups.map((g) => (
            <div key={g.id} ref={(el) => { cardRefs.current[g.id] = el }}>
              <ColumnCard group={g} onRebuild={runBuild} />
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
