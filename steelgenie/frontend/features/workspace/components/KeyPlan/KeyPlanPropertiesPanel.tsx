'use client'

import React, { useState } from 'react'
import { X, Eye, Lock } from 'lucide-react'
import { toast } from 'sonner'
import { floorsApi } from '../../../../lib/api'
import { KeyPlanFloor, colorForPageIdx } from './KeyPlanTypes'

interface KeyPlanPropertiesPanelProps {
  projectId: string
  floors: KeyPlanFloor[]
  activeFloorId: string | null
  onSelectFloor: (floorId: string) => void
  manualPageIds: Set<string>
  onToggleManual: (pageId: string) => void
  hiddenPageIds: Set<string>
  onToggleHidden: (pageId: string) => void
  onApplied: () => void
  onClose: () => void
}

/**
 * Right-dock panel for the Key Plan tool -- matches SteelGenie's Key Plan
 * Properties panel: alignment toggle, Levels (floors) list, Sections
 * (pages of the active floor) list with per-page Auto/Manual, Apply.
 */
export function KeyPlanPropertiesPanel({
  projectId,
  floors,
  activeFloorId,
  onSelectFloor,
  manualPageIds,
  onToggleManual,
  hiddenPageIds,
  onToggleHidden,
  onApplied,
  onClose,
}: KeyPlanPropertiesPanelProps) {
  const [alignmentEnabled, setAlignmentEnabled] = useState(true)
  const [applying, setApplying] = useState(false)
  const [showBackgroundPlan, setShowBackgroundPlan] = useState(false)
  const [showGrids, setShowGrids] = useState(true)
  const [showColumnProjections, setShowColumnProjections] = useState(true)
  const [colorize, setColorize] = useState(true)

  const activeFloor = floors.find((f) => f.id === activeFloorId) || null

  const handleApply = async () => {
    setApplying(true)
    try {
      await floorsApi.registerAll(projectId, true)
      toast.success('Key Plan alignment applied')
      onApplied()
    } catch (err: any) {
      toast.error(err.message || 'Failed to apply Key Plan alignment')
    } finally {
      setApplying(false)
    }
  }

  return (
    <div style={{ width: '300px', height: '100%', backgroundColor: '#0B1220', borderLeft: '1px solid rgba(255,255,255,0.08)', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 14px', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
        <span style={{ fontSize: '13px', fontWeight: 700, color: '#FFFFFF' }}>Properties</span>
        <X size={15} style={{ cursor: 'pointer', color: '#64748B' }} onClick={onClose} />
      </div>

      <div style={{ padding: '12px 14px' }}>
        <div
          style={{
            width: '100%', textAlign: 'center', padding: '8px', borderRadius: '8px',
            backgroundColor: '#3B82F6', color: '#FFFFFF', fontSize: '12px', fontWeight: 700,
          }}
        >
          Key Plan
        </div>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '0 14px 14px' }}>
        {/* Use Key Plan alignment toggle */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 0' }}>
          <span style={{ fontSize: '12px', fontWeight: 600, color: '#E2E8F0' }}>Use Key Plan alignment</span>
          <button
            onClick={() => setAlignmentEnabled((v) => !v)}
            style={{
              width: '34px', height: '18px', borderRadius: '10px', border: 'none', cursor: 'pointer',
              backgroundColor: alignmentEnabled ? '#3B82F6' : '#334155', position: 'relative', transition: 'background-color 0.15s',
            }}
          >
            <span style={{
              position: 'absolute', top: '2px', left: alignmentEnabled ? '18px' : '2px',
              width: '14px', height: '14px', borderRadius: '50%', backgroundColor: '#FFFFFF', transition: 'left 0.15s',
            }} />
          </button>
        </div>
        <p style={{ fontSize: '11px', color: '#64748B', lineHeight: 1.5, margin: '0 0 14px' }}>
          Drag on the canvas, or switch a section to Manual to edit its offset. Auto sections use engine
          -solved grid placement; Manual sections persist whatever alignment you drag them to.
        </p>

        {/* Display options */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginBottom: '16px' }}>
          {[
            { label: 'Background Plan', v: showBackgroundPlan, set: setShowBackgroundPlan },
            { label: 'Grids', v: showGrids, set: setShowGrids },
            { label: 'Column Projections', v: showColumnProjections, set: setShowColumnProjections },
            { label: 'Colorize', v: colorize, set: setColorize },
          ].map((opt) => (
            <label key={opt.label} style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: '#CBD5E1', cursor: 'pointer' }}>
              <input type="checkbox" checked={opt.v} onChange={() => opt.set((x: boolean) => !x)} />
              {opt.label}
            </label>
          ))}
        </div>

        {/* Levels (floors) */}
        <div style={{ marginBottom: '16px' }}>
          <div style={{ fontSize: '11px', fontWeight: 700, color: '#64748B', letterSpacing: '0.06em', marginBottom: '8px' }}>
            LEVELS ({floors.length})
          </div>
          {floors.length === 0 && (
            <span style={{ fontSize: '11px', color: '#475569' }}>No floors clustered yet.</span>
          )}
          {floors.map((f) => (
            <div key={f.id} style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '5px 0' }}>
              <input
                type="radio"
                checked={f.id === activeFloorId}
                onChange={() => onSelectFloor(f.id)}
                style={{ cursor: 'pointer' }}
              />
              <span
                onClick={() => onSelectFloor(f.id)}
                style={{ flex: 1, fontSize: '12px', color: f.id === activeFloorId ? '#FFFFFF' : '#94A3B8', cursor: 'pointer' }}
              >
                {f.name}{typeof f.elevation_ft === 'number' ? ` (${f.elevation_ft.toFixed(0)}'-0")` : ''}
              </span>
              <span style={{ fontSize: '10px', color: '#475569' }}>{f.pages.length}</span>
              <Eye size={13} style={{ color: '#475569' }} />
            </div>
          ))}
        </div>

        {/* Sections (pages of the active floor) */}
        <div style={{ marginBottom: '16px' }}>
          <div style={{ fontSize: '11px', fontWeight: 700, color: '#64748B', letterSpacing: '0.06em', marginBottom: '8px' }}>
            SECTIONS ({activeFloor?.pages.length || 0})
          </div>
          {!activeFloor?.pages.length && (
            <span style={{ fontSize: '11px', color: '#475569' }}>Select a level above.</span>
          )}
          {activeFloor?.pages.map((p, i) => {
            const isManual = manualPageIds.has(p.page_id)
            const isHidden = hiddenPageIds.has(p.page_id)
            return (
              <div key={p.page_id} style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '5px 0' }}>
                <span style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: colorForPageIdx(i), flexShrink: 0 }} />
                <span
                  style={{ flex: 1, fontSize: '12px', color: isHidden ? '#475569' : '#E2E8F0', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                  title={p.title || undefined}
                >
                  {p.sheet_no ? `Page ${p.sheet_no}` : p.title || `Page ${p.idx ?? ''}`}
                </span>
                {p.registration?.method === 'manual' && <Lock size={11} style={{ color: '#64748B' }} />}
                <Eye
                  size={13}
                  style={{ color: isHidden ? '#334155' : '#94A3B8', cursor: 'pointer' }}
                  onClick={() => onToggleHidden(p.page_id)}
                />
                <button
                  onClick={() => onToggleManual(p.page_id)}
                  style={{
                    fontSize: '9px', fontWeight: 700, padding: '3px 7px', borderRadius: '5px', border: 'none', cursor: 'pointer',
                    backgroundColor: isManual ? '#F59E0B' : '#1E293B', color: isManual ? '#0B1220' : '#94A3B8',
                  }}
                >
                  {isManual ? 'MANUAL' : 'AUTO'}
                </button>
              </div>
            )
          })}
        </div>
      </div>

      <div style={{ padding: '14px', borderTop: '1px solid rgba(255,255,255,0.06)' }}>
        <button
          onClick={handleApply}
          disabled={applying}
          style={{
            width: '100%', padding: '10px', borderRadius: '8px', border: 'none', cursor: applying ? 'default' : 'pointer',
            backgroundColor: '#16A34A', color: '#FFFFFF', fontSize: '13px', fontWeight: 700, opacity: applying ? 0.6 : 1,
          }}
        >
          {applying ? 'Applying…' : 'Apply'}
        </button>
      </div>
    </div>
  )
}
