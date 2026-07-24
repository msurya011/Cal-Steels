'use client'

import React, { useState, useEffect } from 'react'
import { useWorkspaceStore, ToolType } from '../../../lib/stores/workspaceStore'
import {
  Pointer, Hand, Ruler, MapPin, Undo2, Redo2, Columns,
  Filter, Palette, Crop, Maximize, Minimize, Home, Image as ImageIcon, Type, List, Trash2,
  Component, PenLine, Map, History as HistoryIcon, Move, Scaling, Plus, Pencil, X as XIcon,
} from 'lucide-react'
import { LayerFilterPopover } from './layers/LayerFilterPopover'
import { toast } from 'sonner'

// Matches SteelGenie's "Color By" dropdown exactly (verified live against
// the reference app: Member Type, Status, Sequence, Weight, Labor Code,
// Paint -- in this order, no more, no less).
const COLOR_MODES: { id: 'kind' | 'status' | 'sequence' | 'weight' | 'labor_code' | 'paint'; label: string }[] = [
  { id: 'kind', label: 'Member Type' },
  { id: 'status', label: 'Status' },
  { id: 'sequence', label: 'Sequence' },
  { id: 'weight', label: 'Weight' },
  { id: 'labor_code', label: 'Labor Code' },
  { id: 'paint', label: 'Paint' },
]

// Small anchored popover for the color/palette button -- picks colorMode,
// mirroring SteelGenie's palette tool (was previously only reachable via
// the hidden Shift+L shortcut).
function ColorModePopover({ onClose, members }: { onClose: () => void; members: any[] }) {
  const {
    layers,
    setColorMode,
    toggleLayerVisibility,
    toggleLegendKey,
    toggleAid,
  } = useWorkspaceStore()

  const currentMode = layers.colorMode

  const hashColorFor = (key: string): string => {
    let hash = 0
    for (let i = 0; i < key.length; i++) {
      hash = key.charCodeAt(i) + ((hash << 5) - hash)
    }
    const colors = ['#3B82F6', '#EF4444', '#10B981', '#F59E0B', '#8B5CF6', '#EC4899', '#06B6D4', '#14B8A6']
    return colors[Math.abs(hash) % colors.length]
  }

  // Build the list of legend items based on the active color mode
  let legendItems: { label: string; color: string; active: boolean; onClick: () => void }[] = []

  if (currentMode === 'kind') {
    legendItems = [
      {
        label: 'Columns',
        color: layers.classColors.column || '#38BDF8',
        active: layers.classVisibility.column !== false,
        onClick: () => toggleLayerVisibility('column')
      },
      {
        label: 'Beams',
        color: layers.classColors.beam || '#BE185D',
        active: layers.classVisibility.beam !== false,
        onClick: () => toggleLayerVisibility('beam')
      },
      {
        label: 'Beams (Undefined)',
        color: layers.classColors.unlabelled || '#EF4444',
        active: layers.classVisibility.unlabelled !== false,
        onClick: () => toggleLayerVisibility('unlabelled')
      },
      {
        label: 'Joists',
        color: layers.classColors.joist || '#7C3AED',
        active: layers.classVisibility.joist !== false,
        onClick: () => toggleLayerVisibility('joist')
      },
      {
        label: 'Moment Connection',
        color: '#10B981',
        active: !layers.hiddenLegendKeys.has('moment'),
        onClick: () => toggleLegendKey('moment')
      },
      {
        label: 'Grids',
        color: '#6B7280',
        active: layers.aids.grid !== false,
        onClick: () => toggleAid('grid')
      },
      {
        label: 'Horizontal Braces',
        color: layers.classColors.hbrace || '#0E7490',
        active: layers.classVisibility.hbrace !== false,
        onClick: () => toggleLayerVisibility('hbrace')
      }
    ]
  } else if (currentMode === 'status') {
    legendItems = [
      {
        label: 'Verified',
        color: '#10B981',
        active: !layers.hiddenLegendKeys.has('verified'),
        onClick: () => toggleLegendKey('verified')
      },
      {
        label: 'Need Review',
        color: '#F59E0B',
        active: !layers.hiddenLegendKeys.has('need_review'),
        onClick: () => toggleLegendKey('need_review')
      },
      {
        label: 'Rejected',
        color: '#EF4444',
        active: !layers.hiddenLegendKeys.has('rejected'),
        onClick: () => toggleLegendKey('rejected')
      },
      {
        label: 'Excluded / Draft',
        color: '#64748B',
        active: !layers.hiddenLegendKeys.has('excluded'),
        onClick: () => toggleLegendKey('excluded')
      }
    ]
  } else if (currentMode === 'sequence') {
    const seqs = Array.from(new Set(members.map(m => (m.sequence !== null && m.sequence !== undefined ? String(m.sequence) : 'Unsequenced'))))
    seqs.sort((a, b) => (a === 'Unsequenced' ? 1 : b === 'Unsequenced' ? -1 : Number(a) - Number(b)))
    legendItems = seqs.map(seq => ({
      label: seq === 'Unsequenced' ? 'Unsequenced' : `Sequence ${seq}`,
      color: seq === 'Unsequenced' ? '#64748B' : hashColorFor(seq),
      active: !layers.hiddenLegendKeys.has(seq),
      onClick: () => toggleLegendKey(seq),
    }))
  } else if (currentMode === 'weight') {
    legendItems = [
      { label: '< 100 lb', color: '#10B981', active: !layers.hiddenLegendKeys.has('< 100 lb'), onClick: () => toggleLegendKey('< 100 lb') },
      { label: '100–300 lb', color: '#3B82F6', active: !layers.hiddenLegendKeys.has('100–300 lb'), onClick: () => toggleLegendKey('100–300 lb') },
      { label: '300–600 lb', color: '#F59E0B', active: !layers.hiddenLegendKeys.has('300–600 lb'), onClick: () => toggleLegendKey('300–600 lb') },
      { label: '> 600 lb', color: '#EF4444', active: !layers.hiddenLegendKeys.has('> 600 lb'), onClick: () => toggleLegendKey('> 600 lb') },
      { label: 'Unbuilt (no weight yet)', color: '#64748B', active: !layers.hiddenLegendKeys.has('Unbuilt'), onClick: () => toggleLegendKey('Unbuilt') },
    ]
  } else if (currentMode === 'labor_code') {
    const codes = Array.from(new Set(members.map(m => m.labor_code || 'Unassigned')))
    legendItems = codes.map(code => ({
      label: code,
      color: code === 'Unassigned' ? '#64748B' : hashColorFor(code),
      active: !layers.hiddenLegendKeys.has(code),
      onClick: () => toggleLegendKey(code),
    }))
  } else if (currentMode === 'paint') {
    const paints = Array.from(new Set(members.map(m => m.paint || 'Unpainted')))
    legendItems = paints.map(p => ({
      label: p,
      color: p === 'Unpainted' ? '#94A3B8' : hashColorFor(p),
      active: !layers.hiddenLegendKeys.has(p),
      onClick: () => toggleLegendKey(p),
    }))
  }

  return (
    <div
      style={{
        position: 'absolute',
        left: '40px',
        top: '0px',
        width: '210px',
        backgroundColor: '#FFFFFF',
        border: '1px solid rgba(0, 0, 0, 0.08)',
        borderRadius: '12px',
        boxShadow: '0 10px 25px -5px rgba(0,0,0,0.1), 0 8px 10px -6px rgba(0,0,0,0.1)',
        zIndex: 100,
        padding: '16px',
        display: 'flex',
        flexDirection: 'column',
        fontFamily: 'Inter, sans-serif'
      }}
    >
      <h3 style={{ margin: '0 0 8px 0', fontSize: '10px', fontWeight: 800, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
        COLOR BY
      </h3>

      <select
        value={currentMode}
        onChange={(e) => setColorMode(e.target.value as any)}
        style={{
          width: '100%',
          height: '36px',
          borderRadius: '6px',
          border: '1px solid #CBD5E1',
          padding: '0 8px',
          fontSize: '13px',
          fontWeight: 600,
          color: '#334155',
          backgroundColor: '#FFFFFF',
          outline: 'none',
          cursor: 'pointer',
          marginBottom: '16px'
        }}
      >
        {COLOR_MODES.map((m) => (
          <option key={m.id} value={m.id}>{m.label}</option>
        ))}
      </select>

      <div style={{ height: '1px', backgroundColor: '#F1F5F9', margin: '0 0 12px 0' }} />

      <h3 style={{ margin: '0 0 10px 0', fontSize: '10px', fontWeight: 800, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
        LEGEND
      </h3>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '180px', overflowY: 'auto', paddingRight: '4px' }}>
        {legendItems.map((item, idx) => (
          <button
            key={`${item.label}-${idx}`}
            onClick={item.onClick}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '10px',
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              padding: '2px 0',
              textAlign: 'left',
              width: '100%',
              opacity: item.active ? 1 : 0.4,
              transition: 'opacity 0.2s',
              outline: 'none'
            }}
          >
            <div style={{
              width: '12px',
              height: '12px',
              borderRadius: '4px',
              backgroundColor: item.color,
              flexShrink: 0
            }} />
            <span style={{
              fontSize: '12px',
              fontWeight: 500,
              color: '#475569',
              textDecoration: item.active ? 'none' : 'line-through',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap'
            }}>
              {item.label}
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}

// Lists every marker/text-markup/ruler placed on the sheet, with jump/delete
// -- SteelGenie's "list" tool.
function AnnotationListPopover({ onClose }: { onClose: () => void }) {
  const { markerDots, removeMarkerDot, rulerLines, removeRulerLine, textMarkers, removeTextMarker, shapeMarkers, removeShapeMarker } = useWorkspaceStore()
  const total = markerDots.length + rulerLines.length + textMarkers.length + shapeMarkers.length
  const SHAPE_ICON: Record<string, string> = { rectangle: '▭', line: '📏', polyline: '〰️' }

  return (
    <div
      style={{
        position: 'absolute', left: '40px', top: '0px', width: '220px', maxHeight: '280px', overflowY: 'auto',
        backgroundColor: '#102030', border: '1px solid rgba(255,255,255,0.08)',
        borderRadius: '10px', boxShadow: '0 8px 32px rgba(0,0,0,0.4)', zIndex: 100,
        padding: '12px', display: 'flex', flexDirection: 'column', gap: '8px',
      }}
    >
      <span style={{ fontSize: '13px', fontWeight: 700, color: '#FFFFFF' }}>Annotations ({total})</span>
      {total === 0 && <span style={{ fontSize: '11px', color: '#64748B' }}>Nothing placed on this sheet yet.</span>}
      {textMarkers.map((tm) => (
        <div key={tm.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '12px', color: '#E2E8F0' }}>
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>📝 {tm.text}</span>
          <Trash2 size={12} style={{ cursor: 'pointer', color: '#EF4444', flexShrink: 0, marginLeft: '6px' }} onClick={() => removeTextMarker(tm.id)} />
        </div>
      ))}
      {markerDots.map((m, i) => (
        <div key={`mk-${i}`} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '12px', color: '#E2E8F0' }}>
          <span>📍 Marker {i + 1}</span>
          <Trash2 size={12} style={{ cursor: 'pointer', color: '#EF4444' }} onClick={() => removeMarkerDot(i)} />
        </div>
      ))}
      {rulerLines.map((r, i) => (
        <div key={`rl-${i}`} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '12px', color: '#E2E8F0' }}>
          <span>📏 Ruler {i + 1}</span>
          <Trash2 size={12} style={{ cursor: 'pointer', color: '#EF4444' }} onClick={() => removeRulerLine(i)} />
        </div>
      ))}
      {shapeMarkers.map((sm) => (
        <div key={sm.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '12px', color: '#E2E8F0' }}>
          <span>{SHAPE_ICON[sm.kind] || '✏️'} {sm.kind[0].toUpperCase() + sm.kind.slice(1)}</span>
          <Trash2 size={12} style={{ cursor: 'pointer', color: '#EF4444' }} onClick={() => removeShapeMarker(sm.id)} />
        </div>
      ))}
    </div>
  )
}

// Itemized activity log ("Resize B_184", "Move B_9", "Add text"...) --
// SteelGenie's HISTORY panel. Informational only for now (no click-to-
// revert-to-this-point yet); every member move/resize/add/edit/delete and
// every annotation placed on the sheet gets its own row here, newest last.
const HISTORY_KIND_ICON: Record<string, React.ReactNode> = {
  move: <Move size={12} />,
  resize: <Scaling size={12} />,
  add: <Plus size={12} />,
  edit: <Pencil size={12} />,
  delete: <Trash2 size={12} />,
  text: <Type size={12} />,
  marker: <MapPin size={12} />,
  ruler: <Ruler size={12} />,
  shape: <PenLine size={12} />,
}

function HistoryPanel({ onClose }: { onClose: () => void }) {
  const { historyLog, clearHistoryLog } = useWorkspaceStore()
  const ordered = [...historyLog].reverse()

  return (
    <div
      style={{
        position: 'absolute', left: '40px', bottom: '0px', width: '230px', maxHeight: '320px', overflowY: 'auto',
        backgroundColor: '#102030', border: '1px solid rgba(255,255,255,0.08)',
        borderRadius: '10px', boxShadow: '0 8px 32px rgba(0,0,0,0.4)', zIndex: 100,
        padding: '10px', display: 'flex', flexDirection: 'column', gap: '4px',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 2px 6px' }}>
        <span style={{ fontSize: '11px', fontWeight: 700, color: '#94A3B8', letterSpacing: '0.06em' }}>HISTORY</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <Trash2
            size={13}
            style={{ cursor: 'pointer', color: '#64748B' }}
            onClick={() => clearHistoryLog()}
          />
          <XIcon size={13} style={{ cursor: 'pointer', color: '#64748B' }} onClick={onClose} />
        </div>
      </div>
      {ordered.length === 0 && (
        <span style={{ fontSize: '11px', color: '#475569', padding: '4px 2px' }}>No activity on this sheet yet.</span>
      )}
      {ordered.map((h) => (
        <div
          key={h.id}
          style={{
            display: 'flex', alignItems: 'center', gap: '8px', padding: '6px 6px',
            borderRadius: '6px', fontSize: '12px', color: '#E2E8F0',
          }}
        >
          <span style={{ color: '#60A5FA', flexShrink: 0 }}>{HISTORY_KIND_ICON[h.kind] || <Pencil size={12} />}</span>
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{h.label}</span>
        </div>
      ))}
    </div>
  )
}

// "Structural Members" flyout -- matches SteelGenie's single "I" icon that
// opens Column / Beam / Joist / Horizontal Brace draw tools, instead of
// three always-visible flat buttons with no Joist/Horizontal Brace option.
const STRUCTURAL_MEMBER_TOOLS: { id: ToolType; label: string; shortcut: string }[] = [
  { id: 'column', label: 'Column', shortcut: 'C' },
  { id: 'beam', label: 'Beam', shortcut: 'B' },
  { id: 'joist', label: 'Joist', shortcut: 'J' },
  { id: 'brace', label: 'Vertical Brace', shortcut: 'V' },
  { id: 'hbrace', label: 'Horizontal Brace', shortcut: 'H' },
]

function StructuralMembersPopover({
  activeTool,
  onPick,
}: {
  activeTool: ToolType
  onPick: (t: ToolType) => void
}) {
  return (
    <div
      style={{
        position: 'absolute', left: '40px', top: '0px', width: '190px',
        backgroundColor: '#102030', border: '1px solid rgba(255,255,255,0.08)',
        borderRadius: '10px', boxShadow: '0 8px 32px rgba(0,0,0,0.4)', zIndex: 100,
        padding: '8px', display: 'flex', flexDirection: 'column', gap: '2px',
      }}
    >
      <span style={{ fontSize: '10px', fontWeight: 700, color: '#64748B', letterSpacing: '0.06em', padding: '2px 8px 6px' }}>
        STRUCTURAL MEMBERS
      </span>
      {STRUCTURAL_MEMBER_TOOLS.map((t) => (
        <button
          key={t.id}
          onClick={() => onPick(t.id)}
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '7px 10px', borderRadius: '6px', border: 'none', textAlign: 'left',
            backgroundColor: activeTool === t.id ? '#3B82F6' : 'transparent',
            color: activeTool === t.id ? '#FFFFFF' : '#CBD5E1',
            fontSize: '12px', fontWeight: 600, cursor: 'pointer',
          }}
        >
          <span>{t.label}</span>
          <span style={{ fontSize: '10px', opacity: 0.6 }}>{t.shortcut}</span>
        </button>
      ))}
    </div>
  )
}

// "Annotate" flyout -- SteelGenie groups Text / Rectangle / Line / Polyline
// markup tools together under one icon.
const ANNOTATE_TOOLS: { id: ToolType; label: string; shortcut: string }[] = [
  { id: 'text', label: 'Text', shortcut: 'T' },
  { id: 'rectangle', label: 'Rectangle', shortcut: 'R' },
  { id: 'line', label: 'Line', shortcut: 'L' },
  { id: 'polyline', label: 'Polyline', shortcut: 'P' },
]

function AnnotatePopover({
  activeTool,
  onPick,
}: {
  activeTool: ToolType
  onPick: (t: ToolType) => void
}) {
  return (
    <div
      style={{
        position: 'absolute', left: '40px', top: '0px', width: '170px',
        backgroundColor: '#102030', border: '1px solid rgba(255,255,255,0.08)',
        borderRadius: '10px', boxShadow: '0 8px 32px rgba(0,0,0,0.4)', zIndex: 100,
        padding: '8px', display: 'flex', flexDirection: 'column', gap: '2px',
      }}
    >
      <span style={{ fontSize: '10px', fontWeight: 700, color: '#64748B', letterSpacing: '0.06em', padding: '2px 8px 6px' }}>
        ANNOTATE
      </span>
      {ANNOTATE_TOOLS.map((t) => (
        <button
          key={t.id}
          onClick={() => onPick(t.id)}
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '7px 10px', borderRadius: '6px', border: 'none', textAlign: 'left',
            backgroundColor: activeTool === t.id ? '#3B82F6' : 'transparent',
            color: activeTool === t.id ? '#FFFFFF' : '#CBD5E1',
            fontSize: '12px', fontWeight: 600, cursor: 'pointer',
          }}
        >
          <span>{t.label}</span>
          <span style={{ fontSize: '10px', opacity: 0.6 }}>{t.shortcut}</span>
        </button>
      ))}
    </div>
  )
}

interface VerticalToolStripProps {
  members: any[]
  projectId?: string
  sidebarOpen: boolean
  onToggleSidebar: () => void
  showKeyPlan?: boolean
  onToggleKeyPlan?: () => void
}

/**
 * SteelGenie-style floating vertical tool strip, docked on the left edge
 * of the drawing canvas.
 */
export function VerticalToolStrip({
  members,
  projectId,
  sidebarOpen,
  onToggleSidebar,
  showKeyPlan,
  onToggleKeyPlan,
}: VerticalToolStripProps) {
  const {
    activeTool,
    setTool,
    popUndo,
    undoStack,
    redo,
    redoStack,
    layers,
    toggleLayerVisibility,
    togglePlanVisibility,
    setColorMode,
    triggerResetView,
  } = useWorkspaceStore()

  const [showLayers, setShowLayers] = useState(false)
  const [showPalette, setShowPalette] = useState(false)
  const [showList, setShowList] = useState(false)
  const [showStructural, setShowStructural] = useState(false)
  const [showAnnotate, setShowAnnotate] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const historyLog = useWorkspaceStore((s) => s.historyLog)

  useEffect(() => {
    const onFsChange = () => setIsFullscreen(!!document.fullscreenElement)
    document.addEventListener('fullscreenchange', onFsChange)
    return () => document.removeEventListener('fullscreenchange', onFsChange)
  }, [])

  const handleFullscreen = () => {
    const el = document.getElementById('plan-viewport-root')
    if (!el) return
    if (document.fullscreenElement) {
      document.exitFullscreen()
    } else {
      el.requestFullscreen().catch(() => toast.error('Fullscreen not available in this browser'))
    }
  }

  const closeAllPopovers = () => {
    setShowLayers(false)
    setShowPalette(false)
    setShowList(false)
    setShowStructural(false)
    setShowAnnotate(false)
    setShowHistory(false)
  }

  const STRUCTURAL_TOOL_IDS: ToolType[] = ['column', 'beam', 'joist', 'brace', 'hbrace']
  const ANNOTATE_TOOL_IDS: ToolType[] = ['text', 'rectangle', 'line', 'polyline']
  const isStructuralActive = STRUCTURAL_TOOL_IDS.includes(activeTool)
  const isAnnotateActive = ANNOTATE_TOOL_IDS.includes(activeTool)

  const tools: { id: ToolType; label: string; icon: React.ReactNode }[] = [
    { id: 'select', label: 'Select (Esc)', icon: <Pointer size={13} /> },
    { id: 'hand', label: 'Pan view', icon: <Hand size={13} /> },
    { id: 'ruler', label: 'Measure / calibrate scale (M)', icon: <Ruler size={13} /> },
    { id: 'crop', label: 'Crop / zoom to region', icon: <Crop size={13} /> },
    { id: 'marker', label: 'Pin / location marker', icon: <MapPin size={13} /> },
  ]

  // Roving shortcuts
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      const activeEl = document.activeElement
      if (
        activeEl &&
        (activeEl.tagName === 'INPUT' ||
          activeEl.tagName === 'TEXTAREA' ||
          activeEl.tagName === 'SELECT' ||
          activeEl.getAttribute('contenteditable') === 'true')
      ) {
        return
      }

      const key = e.key.toLowerCase()

      // F: Toggle layers popover (Filter)
      if (key === 'f') {
        e.preventDefault()
        setShowLayers((prev) => !prev)
        toast.info('Layer Filter panel toggled')
      }

      // N: Toggle navigation sidebar
      if (key === 'n' && !e.shiftKey) {
        e.preventDefault()
        onToggleSidebar()
        toast.info(`Navigation panel ${!sidebarOpen ? 'opened' : 'closed'}`)
      }

      // Shift+L: Cycle Color By mode
      if (e.key.toLowerCase() === 'l' && e.shiftKey) {
        e.preventDefault()
        const modes = COLOR_MODES.map((m) => m.id)
        const currentIdx = modes.indexOf(layers.colorMode)
        const nextIdx = (currentIdx + 1) % modes.length
        setColorMode(modes[nextIdx])
        toast.info(`Color Mode changed to: ${COLOR_MODES[nextIdx].label}`)
      }

      // Tool selection shortcuts
      if (e.key === 'Escape') {
        e.preventDefault()
        setTool('select')
        toast.info('Select mode active')
      }
      if (key === 'c') {
        e.preventDefault()
        setTool('column')
        toast.info('Column tool selected')
      }
      if (key === 'b') {
        e.preventDefault()
        setTool('beam')
        toast.info('Beam tool selected')
      }
      if (key === 'j') {
        e.preventDefault()
        setTool('joist')
        toast.info('Joist tool selected')
      }
      if (key === 'v') {
        e.preventDefault()
        setTool('brace')
        toast.info('Vertical Brace tool selected')
      }
      if (key === 'h' && !e.ctrlKey && !e.metaKey) {
        e.preventDefault()
        setTool('hbrace')
        toast.info('Horizontal Brace tool selected')
      }
      if (key === 't') {
        e.preventDefault()
        setTool('text')
        toast.info('Text tool selected')
      }
      if (key === 'm') {
        e.preventDefault()
        setTool('ruler')
        toast.info('Ruler tool selected')
      }
      if (key === 'r' && !e.ctrlKey && !e.metaKey) {
        e.preventDefault()
        setTool('rectangle')
        toast.info('Rectangle tool selected')
      }
      if (key === 'l' && !e.shiftKey) {
        e.preventDefault()
        setTool('line')
        toast.info('Line tool selected')
      }
      if (key === 'p') {
        e.preventDefault()
        setTool('polyline')
        toast.info('Polyline tool selected')
      }

      // 1-5: Quick toggles for categories
      if (['1', '2', '3', '4', '5'].includes(e.key)) {
        e.preventDefault()
        const indexMap = ['beam', 'column', 'vbrace', 'hbrace', 'joist']
        const targetKind = indexMap[parseInt(e.key) - 1]
        toggleLayerVisibility(targetKind)
        const visible = useWorkspaceStore.getState().layers.classVisibility[targetKind] !== false
        toast.info(`${targetKind} layer ${visible ? 'shown' : 'hidden'}`)
      }
    }

    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [layers.colorMode, setColorMode, toggleLayerVisibility, sidebarOpen, onToggleSidebar, setTool])

  const getStructuralIcon = () => {
    if (activeTool === 'column') {
      return (
        <svg width="13" height="13" viewBox="0 0 100 100" fill="currentColor">
          <path d="M 15 15 H 85 V 35 H 60 V 65 H 85 V 85 H 15 V 65 H 40 V 35 H 15 Z" />
        </svg>
      )
    }
    if (activeTool === 'beam') {
      return (
        <svg width="13" height="13" viewBox="0 0 100 100" fill="currentColor">
          <rect x="10" y="35" width="80" height="30" rx="4" />
        </svg>
      )
    }
    if (activeTool === 'joist') {
      return (
        <svg width="13" height="13" viewBox="0 0 100 100" stroke="currentColor" strokeWidth="12" fill="none">
          <line x1="10" y1="20" x2="90" y2="20" />
          <line x1="10" y1="80" x2="90" y2="80" />
          <polyline points="15,20 35,80 55,20 75,80 85,20" />
        </svg>
      )
    }
    if (activeTool === 'brace') {
      return (
        <svg width="13" height="13" viewBox="0 0 100 100" stroke="currentColor" strokeWidth="14" fill="none">
          <line x1="15" y1="15" x2="85" y2="85" />
          <line x1="15" y1="85" x2="85" y2="15" strokeDasharray="10,8" />
        </svg>
      )
    }
    if (activeTool === 'hbrace') {
      return (
        <svg width="13" height="13" viewBox="0 0 100 100" stroke="currentColor" strokeWidth="14" fill="none">
          <polyline points="15,30 50,70 85,30" />
        </svg>
      )
    }
    return <Component size={13} />
  }

  const getAnnotateIcon = () => {
    if (activeTool === 'text') return <Type size={13} />
    if (activeTool === 'rectangle') {
      return (
        <svg width="13" height="13" viewBox="0 0 100 100" stroke="currentColor" strokeWidth="14" fill="none">
          <rect x="15" y="15" width="70" height="70" rx="8" />
        </svg>
      )
    }
    if (activeTool === 'line') {
      return (
        <svg width="13" height="13" viewBox="0 0 100 100" stroke="currentColor" strokeWidth="14" fill="none">
          <line x1="15" y1="85" x2="85" y2="15" />
        </svg>
      )
    }
    if (activeTool === 'polyline') {
      return (
        <svg width="13" height="13" viewBox="0 0 100 100" stroke="currentColor" strokeWidth="12" fill="none">
          <polyline points="15,80 40,30 65,70 85,20" />
        </svg>
      )
    }
    return <PenLine size={13} />
  }

  const btn = (active: boolean): React.CSSProperties => ({
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: '27px',
    height: '27px',
    border: 'none',
    borderRadius: '6px',
    backgroundColor: active ? '#3B82F6' : 'transparent',
    color: active ? '#FFFFFF' : '#33445C',
    cursor: 'pointer',
    transition: 'all 0.15s',
  })

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '0px',
        padding: '4px',
        backgroundColor: '#FFFFFF',
        borderRadius: '10px',
        boxShadow: '0 4px 18px rgba(0,0,0,0.35)',
      }}
    >
      {/* Sidebar toggle button (Navigation panel) */}
      <button
        title="Toggle Navigation panel (N)"
        onClick={onToggleSidebar}
        style={{
          ...btn(sidebarOpen),
          color: sidebarOpen ? '#FFFFFF' : '#33445C',
          cursor: 'pointer',
        }}
      >
        <Columns size={13} />
      </button>

      <div style={{ height: '1px', backgroundColor: 'rgba(0,0,0,0.1)', margin: '3px 4px' }} />

      {tools.map((t) => (
        <button
          key={t.id}
          title={t.label}
          onClick={() => setTool(t.id)}
          style={{
            ...btn(activeTool === t.id),
            color: activeTool === t.id ? '#FFFFFF' : '#33445C',
          }}
        >
          {t.icon}
        </button>
      ))}

      {/* Structural Members -- Column / Beam / Joist / Horizontal Brace draw tools,
          grouped behind one icon like SteelGenie instead of always-visible flat buttons. */}
      <div style={{ position: 'relative' }}>
        <button
          title="Structural members (draw)"
          onClick={() => { const next = !showStructural; closeAllPopovers(); setShowStructural(next) }}
          style={{ ...btn(isStructuralActive || showStructural), color: (isStructuralActive || showStructural) ? '#FFFFFF' : '#33445C' }}
        >
          {getStructuralIcon()}
        </button>
        {showStructural && (
          <StructuralMembersPopover
            activeTool={activeTool}
            onPick={(t) => { setTool(t); setShowStructural(false) }}
          />
        )}
      </div>

      {/* Annotate -- Text / Rectangle / Line / Polyline markup tools. */}
      <div style={{ position: 'relative' }}>
        <button
          title="Annotate (draw)"
          onClick={() => { const next = !showAnnotate; closeAllPopovers(); setShowAnnotate(next) }}
          style={{ ...btn(isAnnotateActive || showAnnotate), color: (isAnnotateActive || showAnnotate) ? '#FFFFFF' : '#33445C' }}
        >
          {getAnnotateIcon()}
        </button>
        {showAnnotate && (
          <AnnotatePopover
            activeTool={activeTool}
            onPick={(t) => { setTool(t); setShowAnnotate(false) }}
          />
        )}
      </div>

      <div style={{ height: '1px', backgroundColor: 'rgba(0,0,0,0.1)', margin: '3px 4px' }} />

      {/* Filter -- member kind / status filtering (also folds in the plan +
          grid + label visibility toggles that used to live under "Layers") */}
      <button
        title="Filter (F)"
        onClick={() => { const next = !showLayers; closeAllPopovers(); setShowLayers(next) }}
        style={{ ...btn(showLayers), color: showLayers ? '#FFFFFF' : '#33445C', position: 'relative' }}
      >
        <Filter size={13} />
      </button>
      {showLayers && (
        <LayerFilterPopover members={members} onClose={() => setShowLayers(false)} projectId={projectId} />
      )}

      {/* Color / palette -- pick what drives member coloring */}
      <div style={{ position: 'relative' }}>
        <button
          title="Color by..."
          onClick={() => { const next = !showPalette; closeAllPopovers(); setShowPalette(next) }}
          style={{ ...btn(showPalette), color: showPalette ? '#FFFFFF' : '#33445C' }}
        >
          <Palette size={13} />
        </button>
        {showPalette && <ColorModePopover onClose={() => setShowPalette(false)} members={members} />}
      </div>

      {/* Fullscreen */}
      <button
        title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
        onClick={handleFullscreen}
        style={{ ...btn(isFullscreen), color: isFullscreen ? '#FFFFFF' : '#33445C' }}
      >
        {isFullscreen ? <Minimize size={13} /> : <Maximize size={13} />}
      </button>

      {/* Layers -- raster image on/off (one-click, matches SteelGenie's
          dedicated image toggle rather than burying it in a popover) */}
      <button
        title={layers.planVisible === false ? 'Show plan image' : 'Hide plan image'}
        onClick={togglePlanVisibility}
        style={{ ...btn(false), color: layers.planVisible === false ? '#94A3B8' : '#33445C' }}
      >
        {layers.planVisible === false ? <ImageIcon size={13} opacity={0.4} /> : <ImageIcon size={13} />}
      </button>

      {/* Home -- reset pan/zoom to fit */}
      <button title="Reset view" onClick={triggerResetView} style={btn(false)}>
        <Home size={13} />
      </button>

      {/* Key Plan -- overlays every page of the current floor, color-coded
          per page, in one shared feet-based coordinate space. */}
      {onToggleKeyPlan && (
        <button
          title="Key Plan"
          onClick={onToggleKeyPlan}
          style={{ ...btn(!!showKeyPlan), color: showKeyPlan ? '#FFFFFF' : '#33445C' }}
        >
          <Map size={13} />
        </button>
      )}

      {/* List -- every marker / text markup / ruler placed on this sheet */}
      <div style={{ position: 'relative' }}>
        <button
          title="Annotation list"
          onClick={() => { const next = !showList; closeAllPopovers(); setShowList(next) }}
          style={{ ...btn(showList), color: showList ? '#FFFFFF' : '#33445C' }}
        >
          <List size={13} />
        </button>
        {showList && <AnnotationListPopover onClose={() => setShowList(false)} />}
      </div>

      <div style={{ height: '1px', backgroundColor: 'rgba(0,0,0,0.1)', margin: '3px 4px' }} />

      {/* Activity log -- every member move/resize/add/edit/delete plus every
          annotation placed on this sheet, itemized ("Resize B_184", "Move
          B_9"...), matching SteelGenie's History panel. */}
      <div style={{ position: 'relative' }}>
        <button
          title="History"
          onClick={() => { const next = !showHistory; closeAllPopovers(); setShowHistory(next) }}
          style={{ ...btn(showHistory), color: showHistory ? '#FFFFFF' : '#33445C', position: 'relative' }}
        >
          <HistoryIcon size={13} />
          {historyLog.length > 0 && (
            <span
              style={{
                position: 'absolute', top: '-4px', right: '-4px', minWidth: '14px', height: '14px',
                borderRadius: '7px', backgroundColor: '#3B82F6', color: '#FFFFFF', fontSize: '9px',
                fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '0 3px',
              }}
            >
              {historyLog.length > 99 ? '99+' : historyLog.length}
            </span>
          )}
        </button>
        {showHistory && <HistoryPanel onClose={() => setShowHistory(false)} />}
      </div>

      {/* History: Undo / Redo */}
      <button
        title="Undo"
        onClick={popUndo}
        disabled={undoStack.length === 0}
        style={{
          ...btn(false),
          color: undoStack.length > 0 ? '#33445C' : '#B8C2CE',
          cursor: undoStack.length > 0 ? 'pointer' : 'not-allowed',
        }}
      >
        <Undo2 size={13} />
      </button>
      <button
        title="Redo"
        onClick={redo}
        disabled={redoStack.length === 0}
        style={{
          ...btn(false),
          color: redoStack.length > 0 ? '#33445C' : '#B8C2CE',
          cursor: redoStack.length > 0 ? 'pointer' : 'not-allowed',
        }}
      >
        <Redo2 size={13} />
      </button>
    </div>
  )
}
