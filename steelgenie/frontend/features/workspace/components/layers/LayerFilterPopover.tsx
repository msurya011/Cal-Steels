'use client'

import React from 'react'
import { Eye, EyeOff } from 'lucide-react'
import { useWorkspaceStore } from '../../../../lib/stores/workspaceStore'

interface LayerFilterPopoverProps {
  members: any[]
  onClose: () => void
  projectId?: string
}

// Switch Toggle component
function ToggleSwitch({ checked, onChange }: { checked: boolean; onChange: () => void }) {
  return (
    <button
      onClick={onChange}
      style={{
        width: '34px',
        height: '18px',
        borderRadius: '9px',
        backgroundColor: checked ? '#10B981' : '#475569',
        position: 'relative',
        border: 'none',
        cursor: 'pointer',
        transition: 'background-color 0.2s',
        padding: 0,
        outline: 'none',
      }}
    >
      <span
        style={{
          width: '14px',
          height: '14px',
          borderRadius: '50%',
          backgroundColor: '#FFFFFF',
          position: 'absolute',
          top: '2px',
          left: checked ? '18px' : '2px',
          transition: 'left 0.2s ease',
        }}
      />
    </button>
  )
}

// Label-checkbox stack
function CenteredCheckbox({ label, checked, onChange }: { label: string; checked: boolean; onChange: () => void }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '6px', flex: 1 }}>
      <span style={{ fontSize: '10px', color: '#94A3B8', fontWeight: 700 }}>{label}</span>
      <input
        type="checkbox"
        checked={checked}
        onChange={onChange}
        style={{
          width: '14px',
          height: '14px',
          cursor: 'pointer',
          accentColor: '#10B981',
          outline: 'none',
        }}
      />
    </div>
  )
}

export function LayerFilterPopover({ members, onClose, projectId }: LayerFilterPopoverProps) {
  const store = useWorkspaceStore()
  const {
    layers,
    toggleLayerVisibility,
    togglePlanVisibility,
    toggleAid,
  } = store

  // Count helper
  const getCount = (key: string) => {
    if (key === 'unlabelled') {
      return members.filter((m) => !m.kind || m.kind === 'unlabelled').length
    }
    if (key === 'vbrace') {
      return members.filter((m) => m.kind === 'vbrace' || m.kind === 'brace').length
    }
    return members.filter((m) => m.kind === key).length
  }

  // Row switch renderer
  const renderRow = (label: string, checked: boolean, onChange: () => void) => (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: '5px 0',
      }}
    >
      <span style={{ fontSize: '12px', fontWeight: 600, color: '#E2E8F0' }}>{label}</span>
      <ToggleSwitch checked={checked} onChange={onChange} />
    </div>
  )

  const masterLabelsActive = layers.aids.labels !== false

  return (
    <div
      style={{
        position: 'absolute',
        left: '40px', // Anchor to vertical tool strip
        top: '46px',
        width: '240px',
        backgroundColor: '#102030',
        border: '1px solid rgba(255, 255, 255, 0.08)',
        borderRadius: '10px',
        boxShadow: '0 8px 32px rgba(0, 0, 0, 0.4)',
        zIndex: 100,
        display: 'flex',
        flexDirection: 'column',
        boxSizing: 'border-box',
        color: '#F1F5F9',
        fontFamily: 'Inter, system-ui, sans-serif',
        padding: '16px',
        gap: '12px',
      }}
    >
      {/* Header */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
          paddingBottom: '10px',
        }}
      >
        <span style={{ fontSize: '13px', fontWeight: 700, color: '#FFFFFF' }}>
          Layer Filter
        </span>
        <button
          onClick={() => toggleAid('labels')}
          style={{
            background: 'none',
            border: 'none',
            color: masterLabelsActive ? '#10B981' : '#64748B',
            cursor: 'pointer',
            padding: 0,
            display: 'flex',
          }}
          title={masterLabelsActive ? 'Hide all labels' : 'Show labels'}
        >
          {masterLabelsActive ? <Eye size={15} /> : <EyeOff size={15} />}
        </button>
      </div>

      {/* Row Switches */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
        {renderRow('Plan', layers.planVisible !== false, togglePlanVisibility)}
        {renderRow('Grids', layers.aids.grid !== false, () => toggleAid('grid'))}
        {renderRow(`Beams`, layers.classVisibility.beam !== false, () => toggleLayerVisibility('beam'))}
        {renderRow(`Undefined Beams`, layers.classVisibility.unlabelled !== false, () => toggleLayerVisibility('unlabelled'))}
        {renderRow(`Columns`, layers.classVisibility.column !== false, () => toggleLayerVisibility('column'))}
      </div>

      {/* Section: Labels */}
      <div style={{ borderTop: '1px solid rgba(255, 255, 255, 0.08)', paddingTop: '10px' }}>
        <span style={{ fontSize: '11px', fontWeight: 700, color: '#64748B', textTransform: 'uppercase', display: 'block', marginBottom: '8px' }}>
          Labels
        </span>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px' }}>
          <CenteredCheckbox
            label="Piecemarks"
            checked={layers.aids.piecemarks !== false}
            onChange={() => toggleAid('piecemarks')}
          />
          <CenteredCheckbox
            label="Lengths"
            checked={layers.aids.lengths !== false}
            onChange={() => toggleAid('lengths')}
          />
          <CenteredCheckbox
            label="Reactions"
            checked={layers.aids.reactions === true}
            onChange={() => toggleAid('reactions')}
          />
        </div>
      </div>

      {/* Section: Editor */}
      <div style={{ borderTop: '1px solid rgba(255, 255, 255, 0.08)', paddingTop: '10px' }}>
        <span style={{ fontSize: '11px', fontWeight: 700, color: '#64748B', textTransform: 'uppercase', display: 'block', marginBottom: '8px' }}>
          Editor
        </span>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', marginBottom: '10px' }}>
          <CenteredCheckbox
            label="Grids"
            checked={layers.aids.grid !== false}
            onChange={() => toggleAid('grid')}
          />
          <CenteredCheckbox
            label="Column Projections"
            checked={layers.aids.columnProjections !== false}
            onChange={() => toggleAid('columnProjections')}
          />
        </div>
        {renderRow('Length Filter', layers.aids.lengthFilter === true, () => toggleAid('lengthFilter'))}
      </div>
    </div>
  )
}
