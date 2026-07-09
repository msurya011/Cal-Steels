import React, { useState, useEffect } from 'react'
import { Eye, EyeOff, Search, Save, Settings, Trash2, Check } from 'lucide-react'
import { useWorkspaceStore } from '../../../../lib/stores/workspaceStore'

interface LayerFilterPopoverProps {
  members: any[]
  onClose: () => void
  projectId?: string
}

// Color picker choices (colorblind safe & premium aesthetics)
const PALETTE = [
  '#EC4899', // Pink
  '#3B82F6', // Blue
  '#F59E0B', // Orange
  '#06B6D4', // Teal
  '#8B5CF6', // Violet
  '#10B981', // Green
  '#64748B', // Grey
  '#EF4444', // Red
]

export function LayerFilterPopover({ members, onClose, projectId }: LayerFilterPopoverProps) {
  const store = useWorkspaceStore()
  const {
    layers,
    presets,
    toggleLayerVisibility,
    setLayerOpacity,
    setLayerColor,
    toggleAid,
    setColorMode,
    applyPreset,
    savePreset,
    deletePreset,
    setIsolation,
  } = store

  const [search, setSearch] = useState('')
  const [activePicker, setActivePicker] = useState<string | null>(null)
  const [showSavePreset, setShowSavePreset] = useState(false)
  const [newPresetName, setNewPresetName] = useState('')

  // Member class classifications with label and store key
  const CLASSES = [
    { label: 'Beams', key: 'beam' },
    { label: 'Columns', key: 'column' },
    { label: 'Vert. Braces', key: 'vbrace' },
    { label: 'Horiz. Braces', key: 'hbrace' },
    { label: 'Joists', key: 'joist' },
    { label: 'Unlabelled', key: 'unlabelled' },
  ]

  // Counts grouping
  const getCount = (key: string) => {
    if (key === 'unlabelled') {
      return members.filter((m) => !m.kind || m.kind === 'unlabelled').length
    }
    if (key === 'vbrace') {
      return members.filter((m) => m.kind === 'vbrace' || m.kind === 'brace').length
    }
    return members.filter((m) => m.kind === key).length
  }

  // Handle Alt+click to solo (isolate)
  const handleEyeClick = (e: React.MouseEvent, key: string) => {
    if (e.altKey) {
      e.preventDefault()
      setIsolation({ kind: key })
    } else {
      toggleLayerVisibility(key)
    }
  }

  // Preset CRUD operations
  const handleApplyPreset = (presetId: string) => {
    applyPreset(presetId)
  }

  const handleSavePresetSubmit = () => {
    if (newPresetName.trim()) {
      savePreset(newPresetName.trim())
      setNewPresetName('')
      setShowSavePreset(false)
    }
  }

  const handleShowAll = () => {
    CLASSES.forEach((c) => {
      if (!layers.classVisibility[c.key]) {
        toggleLayerVisibility(c.key)
      }
    })
  }

  const handleHideAll = () => {
    CLASSES.forEach((c) => {
      if (layers.classVisibility[c.key]) {
        toggleLayerVisibility(c.key)
      }
    })
  }

  const handleInvert = () => {
    CLASSES.forEach((c) => {
      toggleLayerVisibility(c.key)
    })
  }

  // Generate top sections legend (up to 8 entries)
  const getSectionLegend = () => {
    const counts: Record<string, number> = {}
    members.forEach((m) => {
      if (m.section) {
        counts[m.section] = (counts[m.section] || 0) + 1
      }
    })
    return Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 8)
      .map(([section]) => section)
  }

  const activePreset = presets.find((p) => p.id === layers.activePresetId)

  // Filter CLASSES by search string
  const filteredClasses = CLASSES.filter((c) =>
    c.label.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div
      style={{
        position: 'absolute',
        left: '52px', // anchor to vertical tool strip
        top: '60px',
        width: '300px',
        backgroundColor: '#1E293B',
        border: '1px solid rgba(59, 130, 246, 0.2)',
        borderRadius: '8px',
        boxShadow: '0 8px 32px rgba(0, 0, 0, 0.4), 0 0 1px rgba(255, 255, 255, 0.1)',
        zIndex: 100,
        display: 'flex',
        flexDirection: 'column',
        boxSizing: 'border-box',
        color: '#F1F5F9',
        fontFamily: 'Inter, system-ui, sans-serif',
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: '12px 14px',
          borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          backgroundColor: '#0F172A',
          borderTopLeftRadius: '7px',
          borderTopRightRadius: '7px',
        }}
      >
        <span style={{ fontSize: '12px', fontWeight: 800, letterSpacing: '0.6px', color: '#94A3B8' }}>
          LAYER FILTER
        </span>
        <button
          onClick={onClose}
          style={{
            background: 'none',
            border: 'none',
            color: '#64748B',
            cursor: 'pointer',
            fontSize: '15px',
            lineHeight: 1,
            padding: '2px',
          }}
        >
          &times;
        </button>
      </div>

      {/* Preset select & Search filter */}
      <div
        style={{
          padding: '12px 14px',
          display: 'flex',
          flexDirection: 'column',
          gap: '8px',
          borderBottom: '1px solid rgba(255, 255, 255, 0.04)',
        }}
      >
        {/* Preset Selector */}
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <span style={{ fontSize: '11px', color: '#94A3B8', fontWeight: 600 }}>Preset:</span>
          <select
            value={layers.activePresetId || ''}
            onChange={(e) => handleApplyPreset(e.target.value)}
            style={{
              flex: 1,
              backgroundColor: '#0F172A',
              border: '1px solid rgba(59, 130, 246, 0.15)',
              borderRadius: '5px',
              color: '#F1F5F9',
              fontSize: '11px',
              padding: '4px 8px',
              outline: 'none',
              cursor: 'pointer',
            }}
          >
            <option value="" disabled>
              Select preset...
            </option>
            {presets.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>

          {layers.activePresetId && !['preset-all', 'preset-steel', 'preset-qa', 'preset-braces'].includes(layers.activePresetId) && (
            <button
              onClick={() => deletePreset(layers.activePresetId!)}
              style={{
                backgroundColor: 'transparent',
                border: 'none',
                color: '#EF4444',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
              title="Delete preset"
            >
              <Trash2 size={13} />
            </button>
          )}
        </div>

        {/* Search */}
        <div style={{ position: 'relative' }}>
          <Search
            size={13}
            style={{ position: 'absolute', left: '8px', top: '8px', color: '#64748B' }}
          />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter layers..."
            style={{
              width: '100%',
              padding: '6px 8px 6px 26px',
              backgroundColor: '#0F172A',
              border: '1px solid rgba(255, 255, 255, 0.08)',
              borderRadius: '5px',
              color: '#F1F5F9',
              fontSize: '11px',
              outline: 'none',
              boxSizing: 'border-box',
            }}
          />
        </div>
      </div>

      {/* Content wrapper */}
      <div style={{ overflowY: 'auto', maxHeight: '350px', padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
        {/* MEMBER CLASSES */}
        <div>
          <div style={{ fontSize: '10px', fontWeight: 700, color: '#64748B', marginBottom: '8px', textTransform: 'uppercase' }}>
            Member Classes
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {filteredClasses.map((c) => {
              const count = getCount(c.key)
              const visible = layers.classVisibility[c.key] !== false
              const color = layers.classColors[c.key] || '#10B981'
              const opacity = layers.classOpacity[c.key] ?? 1.0

              return (
                <div
                  key={c.key}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '4px 6px',
                    borderRadius: '4px',
                    backgroundColor: count === 0 ? 'rgba(255,255,255,0.01)' : 'rgba(255,255,255,0.02)',
                    opacity: count === 0 ? 0.45 : 1,
                    position: 'relative',
                  }}
                  onMouseEnter={(e) => {
                    const slider = e.currentTarget.querySelector('.opacity-slider') as HTMLElement
                    if (slider) slider.style.display = 'block'
                  }}
                  onMouseLeave={(e) => {
                    const slider = e.currentTarget.querySelector('.opacity-slider') as HTMLElement
                    if (slider) slider.style.display = 'none'
                    setActivePicker(null)
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    {/* Swatch & Picker */}
                    <div style={{ position: 'relative' }}>
                      <button
                        onClick={() => setActivePicker(activePicker === c.key ? null : c.key)}
                        style={{
                          width: '10px',
                          height: '10px',
                          borderRadius: '50%',
                          backgroundColor: color,
                          border: 'none',
                          cursor: 'pointer',
                          padding: 0,
                        }}
                        title="Recolor category"
                      />
                      {activePicker === c.key && (
                        <div
                          style={{
                            position: 'absolute',
                            left: '14px',
                            top: '-8px',
                            zIndex: 110,
                            backgroundColor: '#0F172A',
                            border: '1px solid rgba(59, 130, 246, 0.3)',
                            borderRadius: '6px',
                            padding: '6px',
                            display: 'grid',
                            gridTemplateColumns: 'repeat(4, 1fr)',
                            gap: '4px',
                          }}
                        >
                          {PALETTE.map((hex) => (
                            <button
                              key={hex}
                              onClick={() => {
                                setLayerColor(c.key, hex)
                                setActivePicker(null)
                              }}
                              style={{
                                width: '12px',
                                height: '12px',
                                borderRadius: '50%',
                                backgroundColor: hex,
                                border: 'none',
                                cursor: 'pointer',
                                padding: 0,
                              }}
                            />
                          ))}
                        </div>
                      )}
                    </div>

                    {/* Eye toggle */}
                    <button
                      onClick={(e) => handleEyeClick(e, c.key)}
                      style={{
                        background: 'none',
                        border: 'none',
                        color: visible ? '#3B82F6' : '#64748B',
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        padding: 0,
                      }}
                      title="Alt+Click to Solo/Isolate"
                    >
                      {visible ? <Eye size={13} /> : <EyeOff size={13} />}
                    </button>

                    <span style={{ fontSize: '11px', fontWeight: 500 }}>
                      {c.label} ({count})
                    </span>
                  </div>

                  {/* Hover Opacity Slider */}
                  <div
                    className="opacity-slider"
                    style={{
                      display: 'none',
                      position: 'absolute',
                      right: '8px',
                      top: '50%',
                      transform: 'translateY(-50%)',
                      backgroundColor: '#1E293B',
                      padding: '2px 6px',
                      borderRadius: '4px',
                    }}
                  >
                    <input
                      type="range"
                      min="0.15"
                      max="1.0"
                      step="0.05"
                      value={opacity}
                      onChange={(e) => setLayerOpacity(c.key, parseFloat(e.target.value))}
                      style={{ width: '50px', height: '2px', cursor: 'pointer' }}
                    />
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        {/* ANNOTATIONS & AIDS */}
        <div>
          <div style={{ fontSize: '10px', fontWeight: 700, color: '#64748B', marginBottom: '8px', textTransform: 'uppercase' }}>
            Annotations & Aids
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
            {[
              { label: 'Manual markers', key: 'markers' },
              { label: 'Ruler lines', key: 'rulers' },
              { label: 'Member labels', key: 'labels' },
              { label: 'Grid lines', key: 'grid' },
              { label: 'Confidence halo', key: 'confidenceHalo' },
              { label: 'Detection region', key: 'detectionRegion' },
            ].map((aid) => {
              const active = layers.aids[aid.key as keyof typeof layers.aids] !== false
              return (
                <label
                  key={aid.key}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    cursor: 'pointer',
                    fontSize: '11px',
                    userSelect: 'none',
                  }}
                >
                  <input
                    type="checkbox"
                    checked={active}
                    onChange={() => toggleAid(aid.key)}
                    style={{ cursor: 'pointer' }}
                  />
                  <span style={{ color: active ? '#F1F5F9' : '#64748B' }}>{aid.label}</span>
                </label>
              )
            })}
          </div>
        </div>

        {/* COLOR BY */}
        <div style={{ borderTop: '1px solid rgba(255, 255, 255, 0.05)', paddingTop: '10px' }}>
          <div style={{ fontSize: '10px', fontWeight: 700, color: '#64748B', marginBottom: '6px', textTransform: 'uppercase' }}>
            Color By
          </div>
          <div
            style={{
              display: 'flex',
              backgroundColor: '#0F172A',
              padding: '2px',
              borderRadius: '6px',
              marginBottom: '8px',
            }}
          >
            {(['kind', 'status', 'confidence', 'section'] as const).map((mode) => (
              <button
                key={mode}
                onClick={() => setColorMode(mode)}
                style={{
                  flex: 1,
                  backgroundColor: layers.colorMode === mode ? '#3B82F6' : 'transparent',
                  color: layers.colorMode === mode ? '#FFFFFF' : '#94A3B8',
                  border: 'none',
                  borderRadius: '4px',
                  fontSize: '9px',
                  fontWeight: 700,
                  padding: '4px 0',
                  cursor: 'pointer',
                  textTransform: 'capitalize',
                }}
              >
                {mode}
              </button>
            ))}
          </div>

          {/* Dynamic Legend Preview (top 8 sections or key statuses) */}
          <div
            style={{
              fontSize: '10px',
              color: '#64748B',
              backgroundColor: '#0F172A',
              padding: '6px 8px',
              borderRadius: '6px',
              display: 'flex',
              flexWrap: 'wrap',
              gap: '6px',
            }}
          >
            <span style={{ fontWeight: 600 }}>Legend:</span>
            {layers.colorMode === 'kind' && (
              <>
                <span style={{ display: 'flex', alignItems: 'center', gap: '3px' }}>
                  <span style={{ width: '8px', height: '4px', backgroundColor: layers.classColors.beam }} /> Beam
                </span>
                <span style={{ display: 'flex', alignItems: 'center', gap: '3px' }}>
                  <span style={{ width: '8px', height: '4px', backgroundColor: layers.classColors.column }} /> Column
                </span>
                <span style={{ display: 'flex', alignItems: 'center', gap: '3px' }}>
                  <span style={{ width: '8px', height: '4px', backgroundColor: layers.classColors.vbrace }} /> Brace
                </span>
              </>
            )}
            {layers.colorMode === 'status' && (
              <>
                <span style={{ display: 'flex', alignItems: 'center', gap: '3px' }}>
                  <span style={{ width: '8px', height: '4px', backgroundColor: '#10B981' }} /> Verified
                </span>
                <span style={{ display: 'flex', alignItems: 'center', gap: '3px' }}>
                  <span style={{ width: '8px', height: '4px', backgroundColor: '#EF4444' }} /> Rejected
                </span>
                <span style={{ display: 'flex', alignItems: 'center', gap: '3px' }}>
                  <span style={{ width: '8px', height: '4px', backgroundColor: '#F59E0B' }} /> Needs Review
                </span>
              </>
            )}
            {layers.colorMode === 'confidence' && (
              <>
                <span style={{ display: 'flex', alignItems: 'center', gap: '3px' }}>
                  <span style={{ width: '8px', height: '4px', backgroundColor: '#10B981' }} /> &gt;90%
                </span>
                <span style={{ display: 'flex', alignItems: 'center', gap: '3px' }}>
                  <span style={{ width: '8px', height: '4px', backgroundColor: '#3B82F6' }} /> &gt;70%
                </span>
                <span style={{ display: 'flex', alignItems: 'center', gap: '3px' }}>
                  <span style={{ width: '8px', height: '4px', backgroundColor: '#F59E0B' }} /> &gt;50%
                </span>
              </>
            )}
            {layers.colorMode === 'section' &&
              getSectionLegend().map((sec) => {
                // Generate color using store logic hash
                let hash = 0
                for (let i = 0; i < sec.length; i++) {
                  hash = sec.charCodeAt(i) + ((hash << 5) - hash)
                }
                const colors = ['#3B82F6', '#EF4444', '#10B981', '#F59E0B', '#8B5CF6', '#EC4899', '#06B6D4', '#14B8A6']
                const c = colors[Math.abs(hash) % colors.length]
                return (
                  <span key={sec} style={{ display: 'flex', alignItems: 'center', gap: '3px' }}>
                    <span style={{ width: '8px', height: '4px', backgroundColor: c }} /> {sec}
                  </span>
                )
              })}
          </div>
        </div>
      </div>

      {/* Save presets overlay modal */}
      {showSavePreset && (
        <div
          style={{
            padding: '12px',
            backgroundColor: '#0F172A',
            borderTop: '1px solid rgba(59, 130, 246, 0.2)',
            display: 'flex',
            flexDirection: 'column',
            gap: '8px',
          }}
        >
          <div style={{ fontSize: '11px', color: '#94A3B8', fontWeight: 600 }}>Save Layer Preset</div>
          <div style={{ display: 'flex', gap: '6px' }}>
            <input
              value={newPresetName}
              onChange={(e) => setNewPresetName(e.target.value)}
              placeholder="e.g. My Custom View"
              style={{
                flex: 1,
                padding: '4px 8px',
                backgroundColor: '#1E293B',
                border: '1px solid rgba(255,255,255,0.1)',
                borderRadius: '4px',
                color: '#F1F5F9',
                fontSize: '11px',
                outline: 'none',
              }}
            />
            <button
              onClick={handleSavePresetSubmit}
              style={{
                padding: '4px 10px',
                backgroundColor: '#3B82F6',
                border: 'none',
                borderRadius: '4px',
                color: '#FFFFFF',
                fontSize: '11px',
                cursor: 'pointer',
                fontWeight: 600,
              }}
            >
              Save
            </button>
            <button
              onClick={() => setShowSavePreset(false)}
              style={{
                padding: '4px 6px',
                backgroundColor: 'transparent',
                border: 'none',
                color: '#64748B',
                fontSize: '11px',
                cursor: 'pointer',
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Footer Actions */}
      <div
        style={{
          padding: '10px 14px',
          borderTop: '1px solid rgba(255, 255, 255, 0.08)',
          backgroundColor: '#0F172A',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          borderBottomLeftRadius: '7px',
          borderBottomRightRadius: '7px',
        }}
      >
        <div style={{ display: 'flex', gap: '8px' }}>
          <button
            onClick={handleShowAll}
            style={{
              background: 'none',
              border: 'none',
              color: '#3B82F6',
              fontSize: '10px',
              fontWeight: 700,
              cursor: 'pointer',
              padding: 0,
            }}
          >
            Show All
          </button>
          <button
            onClick={handleHideAll}
            style={{
              background: 'none',
              border: 'none',
              color: '#64748B',
              fontSize: '10px',
              fontWeight: 700,
              cursor: 'pointer',
              padding: 0,
            }}
          >
            Hide All
          </button>
          <button
            onClick={handleInvert}
            style={{
              background: 'none',
              border: 'none',
              color: '#F59E0B',
              fontSize: '10px',
              fontWeight: 700,
              cursor: 'pointer',
              padding: 0,
            }}
          >
            Invert
          </button>
        </div>

        <button
          onClick={() => setShowSavePreset(true)}
          style={{
            backgroundColor: '#1E293B',
            border: '1px solid rgba(59, 130, 246, 0.2)',
            borderRadius: '4px',
            color: '#FFFFFF',
            fontSize: '10px',
            padding: '3px 8px',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '4px',
          }}
        >
          <Save size={10} />
          Save...
        </button>
      </div>
    </div>
  )
}
