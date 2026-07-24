import React, { useState } from 'react'
import { useWorkspaceStore, ToolType } from '../../../lib/stores/workspaceStore'
import { Pointer, Hand, Ruler, MapPin, Undo2, ZoomIn, ZoomOut, Maximize2 } from 'lucide-react'

const SCALE_OPTIONS = [
  { label: '1/32" = 1\'-0"',  ratio: 384 },
  { label: '3/64" = 1\'-0"',  ratio: 256 },
  { label: '1/16" = 1\'-0"',  ratio: 192 },
  { label: '3/32" = 1\'-0"',  ratio: 128 },
  { label: '1/8" = 1\'-0"',   ratio: 96  },
  { label: '3/16" = 1\'-0"',  ratio: 64  },
  { label: '1/4" = 1\'-0"',   ratio: 48  },
  { label: '3/8" = 1\'-0"',   ratio: 32  },
  { label: '1/2" = 1\'-0"',   ratio: 24  },
  { label: '3/4" = 1\'-0"',   ratio: 16  },
  { label: '1" = 1\'-0"',     ratio: 12  },
  { label: '1-1/2" = 1\'-0"', ratio: 8   },
  { label: '3" = 1\'-0"',     ratio: 4   },
  { label: '1" = 10\'-0"',    ratio: 120 },
  { label: '1" = 20\'-0"',    ratio: 240 },
  { label: '1" = 30\'-0"',    ratio: 360 },
  { label: '1" = 40\'-0"',    ratio: 480 },
  { label: '1" = 50\'-0"',    ratio: 600 },
  { label: '1" = 60\'-0"',    ratio: 720 },
  { label: '1" = 100\'-0"',   ratio: 1200 },
]

interface CanvasToolbarProps {
  onScaleChange: (label: string, ratio: number) => void
  onRunAnalyse: (detectUnlabeled: boolean, elevation: number) => Promise<void>
  isAnalysing: boolean
}

export function CanvasToolbar({ onScaleChange, onRunAnalyse, isAnalysing }: CanvasToolbarProps) {
  const {
    activeTool,
    setTool,
    zoomLevel,
    setZoom,
    popUndo,
    undoStack,
    selectedScale,
    selectedRatio,
  } = useWorkspaceStore()

  const [scaleOpen, setScaleOpen] = useState(false)

  // Keyboard shortcuts: C column, B beam, V brace, M measure, Esc select
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      const map: Record<string, ToolType> = { c: 'column', b: 'beam', v: 'brace', m: 'ruler' }
      const k = e.key.toLowerCase()
      if (map[k]) setTool(map[k])
      if (e.key === 'Escape') setTool('select')
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [setTool])
  const handleZoom = (direction: 'in' | 'out' | 'reset') => {
    if (direction === 'reset') {
      setZoom(1.0)
    } else if (direction === 'in') {
      setZoom(Math.min(zoomLevel + 0.25, 4.0))
    } else {
      setZoom(Math.max(zoomLevel - 0.25, 0.5))
    }
  }

  return (
    <div
      style={{
        height: '48px',
        backgroundColor: '#132E4F',
        borderBottom: '1px solid rgba(59, 130, 246, 0.1)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 16px',
        userSelect: 'none',
        flexShrink: 0,
        gap: '12px',
      }}
    >
      {/* Drawing tools moved to the floating VerticalToolStrip on the canvas */}
      <div />

      {/* Scaling Picker dropdown */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', position: 'relative' }}>
        <span style={{ fontSize: '11px', color: '#64748B', fontWeight: 600, textTransform: 'uppercase' }}>Scale</span>
        <button
          onClick={() => setScaleOpen(!scaleOpen)}
          style={{
            backgroundColor: '#1B3A60',
            border: '1px solid rgba(59, 130, 246, 0.15)',
            borderRadius: '6px',
            padding: '5px 12px',
            color: '#F1F5F9',
            fontSize: '12px',
            fontWeight: 600,
            cursor: 'pointer',
            minWidth: '120px',
            textAlign: 'left',
          }}
        >
          {selectedScale || 'Select Scale'}
        </button>

        {scaleOpen && (
          <div
            style={{
              position: 'absolute',
              top: '36px',
              left: '42px',
              width: '180px',
              maxHeight: '260px',
              overflowY: 'auto',
              backgroundColor: '#1B3A60',
              border: '1px solid rgba(59, 130, 246, 0.25)',
              borderRadius: '8px',
              boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
              zIndex: 100,
              padding: '4px',
            }}
          >
            {SCALE_OPTIONS.map((opt) => (
              <div
                key={opt.label}
                onClick={() => {
                  onScaleChange(opt.label, opt.ratio)
                  setScaleOpen(false)
                }}
                style={{
                  padding: '6px 10px',
                  color: '#94A3B8',
                  fontSize: '12px',
                  fontWeight: 500,
                  cursor: 'pointer',
                  borderRadius: '4px',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.backgroundColor = 'rgba(59,130,246,0.12)'
                  e.currentTarget.style.color = '#FFFFFF'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = 'transparent'
                  e.currentTarget.style.color = '#94A3B8'
                }}
              >
                {opt.label}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Zoom controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
        <button
          onClick={() => handleZoom('out')}
          title="Zoom out"
          style={{ background: 'transparent', border: 'none', borderRadius: '6px', padding: '6px 10px', color: '#94A3B8', cursor: 'pointer' }}
        >
          <ZoomOut size={14} />
        </button>
        <span style={{ fontSize: '11px', fontWeight: 700, color: '#F1F5F9', minWidth: '32px', textAlign: 'center' }}>
          {Math.round(zoomLevel * 100)}%
        </span>
        <button
          onClick={() => handleZoom('in')}
          title="Zoom in"
          style={{ background: 'transparent', border: 'none', borderRadius: '6px', padding: '6px 10px', color: '#94A3B8', cursor: 'pointer' }}
        >
          <ZoomIn size={14} />
        </button>
        <button
          onClick={() => handleZoom('reset')}
          title="Reset zoom"
          style={{ background: 'transparent', border: 'none', borderRadius: '6px', padding: '6px 10px', color: '#94A3B8', cursor: 'pointer' }}
        >
          <Maximize2 size={14} />
        </button>
      </div>
    </div>
  )
}
