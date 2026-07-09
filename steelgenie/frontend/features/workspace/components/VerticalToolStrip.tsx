'use client'

import React from 'react'
import { useWorkspaceStore, ToolType } from '../../../lib/stores/workspaceStore'
import { Pointer, Hand, Ruler, MapPin, Undo2 } from 'lucide-react'

/**
 * SteelGenie-style floating vertical tool strip, docked on the left edge
 * of the drawing canvas.
 */
export function VerticalToolStrip() {
  const { activeTool, setTool, popUndo, undoStack } = useWorkspaceStore()

  const tools: { id: ToolType; label: string; icon: React.ReactNode }[] = [
    { id: 'select', label: 'Select (Esc)', icon: <Pointer size={15} /> },
    { id: 'hand', label: 'Pan view', icon: <Hand size={15} /> },
    { id: 'ruler', label: 'Measure / calibrate scale (M)', icon: <Ruler size={15} /> },
    { id: 'marker', label: 'Add marker', icon: <MapPin size={15} /> },
    { id: 'column', label: 'Draw column — click (C)', icon: <b style={{ fontSize: 13 }}>C</b> },
    { id: 'beam', label: 'Draw beam — drag span (B)', icon: <b style={{ fontSize: 13 }}>B</b> },
    { id: 'brace', label: 'Draw brace — drag diagonal (V)', icon: <b style={{ fontSize: 13 }}>V</b> },
  ]

  const btn = (active: boolean): React.CSSProperties => ({
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: '34px',
    height: '34px',
    border: 'none',
    borderRadius: '8px',
    backgroundColor: active ? '#3B82F6' : 'transparent',
    color: active ? '#FFFFFF' : '#B9C7D8',
    cursor: 'pointer',
    transition: 'all 0.15s',
  })

  return (
    <div
      style={{
        position: 'absolute',
        top: '16px',
        left: '12px',
        zIndex: 30,
        display: 'flex',
        flexDirection: 'column',
        gap: '2px',
        padding: '6px',
        backgroundColor: '#FFFFFF',
        borderRadius: '12px',
        boxShadow: '0 4px 18px rgba(0,0,0,0.35)',
      }}
    >
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
    </div>
  )
}
