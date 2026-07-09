'use client'

import React, { useState, useEffect } from 'react'
import { useWorkspaceStore, ToolType } from '../../../lib/stores/workspaceStore'
import { Pointer, Hand, Ruler, MapPin, Undo2, Layers, Columns } from 'lucide-react'
import { LayerFilterPopover } from './layers/LayerFilterPopover'
import { toast } from 'sonner'

interface VerticalToolStripProps {
  members: any[]
  projectId?: string
  sidebarOpen: boolean
  onToggleSidebar: () => void
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
}: VerticalToolStripProps) {
  const {
    activeTool,
    setTool,
    popUndo,
    undoStack,
    layers,
    toggleLayerVisibility,
    setColorMode,
  } = useWorkspaceStore()

  const [showLayers, setShowLayers] = useState(false)

  const tools: { id: ToolType; label: string; icon: React.ReactNode }[] = [
    { id: 'select', label: 'Select (Esc)', icon: <Pointer size={15} /> },
    { id: 'hand', label: 'Pan view', icon: <Hand size={15} /> },
    { id: 'ruler', label: 'Measure / calibrate scale (M)', icon: <Ruler size={15} /> },
    { id: 'marker', label: 'Add marker', icon: <MapPin size={15} /> },
    { id: 'column', label: 'Draw column — click (C)', icon: <b style={{ fontSize: 13 }}>C</b> },
    { id: 'beam', label: 'Draw beam — drag span (B)', icon: <b style={{ fontSize: 13 }}>B</b> },
    { id: 'brace', label: 'Draw brace — drag diagonal (V)', icon: <b style={{ fontSize: 13 }}>V</b> },
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

      // L: Toggle layers popover
      if (e.key === 'l' && !e.shiftKey) {
        e.preventDefault()
        setShowLayers((prev) => !prev)
        toast.info('Layer Filter panel toggled')
      }

      // N: Toggle navigation sidebar
      if (e.key === 'n' && !e.shiftKey) {
        e.preventDefault()
        onToggleSidebar()
        toast.info(`Navigation panel ${!sidebarOpen ? 'opened' : 'closed'}`)
      }

      // Shift+L: Cycle Color By mode
      if (e.key.toLowerCase() === 'l' && e.shiftKey) {
        e.preventDefault()
        const modes: ('kind' | 'status' | 'confidence' | 'section')[] = ['kind', 'status', 'confidence', 'section']
        const currentIdx = modes.indexOf(layers.colorMode)
        const nextIdx = (currentIdx + 1) % modes.length
        setColorMode(modes[nextIdx])
        toast.info(`Color Mode changed to: ${modes[nextIdx]}`)
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
  }, [layers.colorMode, setColorMode, toggleLayerVisibility, sidebarOpen, onToggleSidebar])

  const btn = (active: boolean): React.CSSProperties => ({
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: '34px',
    height: '34px',
    border: 'none',
    borderRadius: '8px',
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
        gap: '2px',
        padding: '6px',
        backgroundColor: '#FFFFFF',
        borderRadius: '12px',
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
        <Columns size={15} />
      </button>

      <div style={{ height: '1px', backgroundColor: 'rgba(0,0,0,0.1)', margin: '4px 2px' }} />

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

      <div style={{ height: '1px', backgroundColor: 'rgba(0,0,0,0.1)', margin: '4px 2px' }} />

      {/* Undo tool */}
      <button
        title="Undo annotation"
        onClick={popUndo}
        disabled={undoStack.length === 0}
        style={{
          ...btn(false),
          color: undoStack.length > 0 ? '#33445C' : '#B8C2CE',
          cursor: undoStack.length > 0 ? 'pointer' : 'not-allowed',
        }}
      >
        <Undo2 size={15} />
      </button>

      {/* Layers Panel Button */}
      <button
        title="Layer Filter (L)"
        onClick={() => setShowLayers(!showLayers)}
        style={{
          ...btn(showLayers),
          color: showLayers ? '#FFFFFF' : '#33445C',
          cursor: 'pointer',
        }}
      >
        <Layers size={15} />
      </button>

      {/* Layer Filter Popover anchor */}
      {showLayers && (
        <LayerFilterPopover
          members={members}
          onClose={() => setShowLayers(false)}
          projectId={projectId}
        />
      )}
    </div>
  )
}
