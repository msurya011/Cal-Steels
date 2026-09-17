import { create } from 'zustand'

export type ToolType = 'select' | 'hand' | 'ruler' | 'marker' | 'column' | 'beam' | 'brace' | 'joist' | 'hbrace' | 'crop' | 'text' | 'rectangle' | 'line' | 'polyline'

export interface Point {
  x: number
  y: number
}

export interface CropRect {
  x0: number
  y0: number
  x1: number
  y1: number
}

export interface RulerLine {
  x1: number
  y1: number
  x2: number
  y2: number
}

export interface TextMarker {
  id: string
  x: number
  y: number
  text: string
}

// Rectangle / Line / Polyline markup shapes -- SteelGenie's Annotate flyout.
export interface ShapeMarker {
  id: string
  kind: 'rectangle' | 'line' | 'polyline'
  points: Point[]
}

// A popped undo/redo entry carries enough of the removed item to restore it
// on redo -- storing just the type (as the old undoStack did) loses the
// data needed to put it back.
type HistoryEntry =
  | { type: 'marker'; data: Point }
  | { type: 'ruler'; data: RulerLine }
  | { type: 'text'; data: TextMarker }

// SteelGenie-style itemized activity log ("Resize B_184", "Move B_9", "Add
// text"...) shown in the History panel -- distinct from undoStack/redoStack
// above, which only exist to make Ctrl+Z work for annotation markup. This
// log is purely informational (no revert-to-this-point yet), covering
// member edits too so every action taken on a sheet is visible in one place.
export type HistoryLogKind = 'move' | 'resize' | 'add' | 'edit' | 'delete' | 'text' | 'marker' | 'ruler' | 'shape'
export interface HistoryLogEntry {
  id: string
  ts: number
  kind: HistoryLogKind
  label: string
}

export interface LayerPreset {
  id: string
  name: string
  classVisibility: Record<string, boolean>
  classOpacity: Record<string, number>
  classColors: Record<string, string>
  aids: {
    markers: boolean
    rulers: boolean
    labels: boolean
    confidenceHalo: boolean
    detectionRegion: boolean
    grid: boolean
    piecemarks: boolean
    lengths: boolean
    reactions: boolean
    columnProjections: boolean
    lengthFilter: boolean
    gridDimensions: boolean
  }
  colorMode: 'kind' | 'status' | 'sequence' | 'weight' | 'labor_code' | 'paint'
}

export interface LayersState {
  classVisibility: Record<string, boolean>
  classOpacity: Record<string, number>
  classColors: Record<string, string>
  planVisible: boolean
  aids: {
    markers: boolean
    rulers: boolean
    labels: boolean
    confidenceHalo: boolean
    detectionRegion: boolean
    grid: boolean
    piecemarks: boolean
    lengths: boolean
    reactions: boolean
    columnProjections: boolean
    lengthFilter: boolean
    gridDimensions: boolean
  }
  colorMode: 'kind' | 'status' | 'sequence' | 'weight' | 'labor_code' | 'paint'
  activePresetId: string | null
  hiddenLegendKeys: Set<string>
}

export const DEFAULT_PRESETS: LayerPreset[] = [
  {
    id: 'preset-all',
    name: 'All',
    classVisibility: { beam: true, column: true, vbrace: true, hbrace: true, joist: true, unlabelled: true },
    classOpacity: { beam: 1, column: 1, vbrace: 1, hbrace: 1, joist: 1, unlabelled: 1 },
    classColors: { column: '#38BDF8', beam: '#8B5CF6', vbrace: '#D97706', hbrace: '#0E7490', joist: '#10B981', unlabelled: '#64748B' },
    aids: {
      markers: true,
      rulers: true,
      labels: true,
      confidenceHalo: true,
      detectionRegion: true,
      grid: true,
      piecemarks: true,
      lengths: true,
      reactions: false,
      columnProjections: true,
      lengthFilter: false,
      gridDimensions: true,
    },
    colorMode: 'kind'
  },
  {
    id: 'preset-steel',
    name: 'Steel only',
    classVisibility: { beam: true, column: true, vbrace: true, hbrace: true, joist: true, unlabelled: true },
    classOpacity: { beam: 1, column: 1, vbrace: 1, hbrace: 1, joist: 1, unlabelled: 1 },
    classColors: { column: '#38BDF8', beam: '#8B5CF6', vbrace: '#D97706', hbrace: '#0E7490', joist: '#10B981', unlabelled: '#64748B' },
    aids: {
      markers: false,
      rulers: false,
      labels: false,
      confidenceHalo: false,
      detectionRegion: false,
      grid: false,
      piecemarks: false,
      lengths: false,
      reactions: false,
      columnProjections: false,
      lengthFilter: false,
      gridDimensions: false,
    },
    colorMode: 'kind'
  },
  {
    id: 'preset-qa',
    name: 'QA pass',
    classVisibility: { beam: true, column: true, vbrace: true, hbrace: true, joist: true, unlabelled: true },
    classOpacity: { beam: 1, column: 1, vbrace: 1, hbrace: 1, joist: 1, unlabelled: 1 },
    classColors: { column: '#38BDF8', beam: '#8B5CF6', vbrace: '#D97706', hbrace: '#0E7490', joist: '#10B981', unlabelled: '#64748B' },
    aids: {
      markers: true,
      rulers: true,
      labels: true,
      confidenceHalo: true,
      detectionRegion: false,
      grid: true,
      piecemarks: true,
      lengths: true,
      reactions: false,
      columnProjections: true,
      lengthFilter: false,
      gridDimensions: true,
    },
    colorMode: 'status'
  },
  {
    id: 'preset-braces',
    name: 'Braces check',
    classVisibility: { beam: false, column: false, vbrace: true, hbrace: true, joist: false, unlabelled: false },
    classOpacity: { beam: 1, column: 1, vbrace: 1, hbrace: 1, joist: 1, unlabelled: 1 },
    classColors: { column: '#38BDF8', beam: '#8B5CF6', vbrace: '#D97706', hbrace: '#0E7490', joist: '#10B981', unlabelled: '#64748B' },
    aids: {
      markers: true,
      rulers: true,
      labels: true,
      confidenceHalo: false,
      detectionRegion: false,
      grid: true,
      piecemarks: true,
      lengths: true,
      reactions: false,
      columnProjections: true,
      lengthFilter: false,
      gridDimensions: true,
    },
    colorMode: 'kind'
  }
]

const getInitialLayers = (): LayersState => {
  if (typeof window !== 'undefined') {
    const saved = localStorage.getItem('calsteel-layers')
    if (saved) {
      try {
        const parsed = JSON.parse(saved)
        parsed.hiddenLegendKeys = new Set(parsed.hiddenLegendKeys || [])
        if (parsed.aids.piecemarks === undefined) parsed.aids.piecemarks = true
        if (parsed.aids.lengths === undefined) parsed.aids.lengths = true
        if (parsed.aids.reactions === undefined) parsed.aids.reactions = false
        if (parsed.aids.columnProjections === undefined) parsed.aids.columnProjections = true
        if (parsed.aids.lengthFilter === undefined) parsed.aids.lengthFilter = false
        if (parsed.aids.gridDimensions === undefined) parsed.aids.gridDimensions = true
        if (parsed.classColors) {
          if (parsed.classColors.beam === '#BE185D') parsed.classColors.beam = '#8B5CF6'
          if (parsed.classColors.joist === '#7C3AED' || parsed.classColors.joist === '#06B6D4') parsed.classColors.joist = '#10B981'
        }
        return parsed
      } catch {
        // ignore
      }
    }
  }
  return {
    classVisibility: { beam: true, column: true, vbrace: true, hbrace: true, joist: true, unlabelled: true },
    classOpacity: { beam: 1.0, column: 1.0, vbrace: 1.0, hbrace: 1.0, joist: 1.0, unlabelled: 1.0 },
    classColors: { column: '#38BDF8', beam: '#8B5CF6', vbrace: '#D97706', hbrace: '#0E7490', joist: '#10B981', unlabelled: '#64748B' },
    planVisible: true,
    aids: {
      markers: true,
      rulers: true,
      labels: true,
      confidenceHalo: false,
      detectionRegion: false,
      grid: false,
      piecemarks: true,
      lengths: true,
      reactions: false,
      columnProjections: true,
      lengthFilter: false,
      gridDimensions: true,
    },
    colorMode: 'kind',
    activePresetId: null,
    hiddenLegendKeys: new Set<string>()
  }
}

const getInitialPresets = (): LayerPreset[] => {
  if (typeof window !== 'undefined') {
    const saved = localStorage.getItem('calsteel-presets')
    if (saved) {
      try {
        const parsed = JSON.parse(saved)
        // ensure default aids are populated
        const validated = parsed.map((p: any) => ({
          ...p,
          aids: {
            markers: true,
            rulers: true,
            labels: true,
            confidenceHalo: false,
            detectionRegion: false,
            grid: false,
            piecemarks: true,
            lengths: true,
            reactions: false,
            columnProjections: true,
            lengthFilter: false,
            ...p.aids
          }
        }))
        return [...DEFAULT_PRESETS, ...validated]
      } catch {
        // ignore
      }
    }
  }
  return DEFAULT_PRESETS
}

interface WorkspaceState {
  activeTool: ToolType
  zoomLevel: number
  isPanning: boolean
  cropMode: boolean
  cropDrag: CropRect | null
  cropRect: CropRect | null
  rulerStart: Point | null
  rulerEnd: Point | null
  rulerDragging: boolean
  markerDots: Point[]
  rulerLines: RulerLine[]
  undoStack: ('marker' | 'ruler' | 'text')[]
  redoStack: HistoryEntry[]
  historyLog: HistoryLogEntry[]
  pushHistoryLog: (kind: HistoryLogKind, label: string) => void
  clearHistoryLog: () => void
  // Pages with a member edited since their last Extract/Build -- flagged
  // "Requesting Build" in the sheet rail until the user re-runs extraction,
  // matching SteelGenie's behavior of never silently letting a built sheet's
  // BOM/3D data drift out of sync with a manual edit.
  dirtyPageIds: Set<string>
  markPageDirty: (pageId: string) => void
  clearPageDirty: (pageId: string) => void
  textMarkers: TextMarker[]
  shapeMarkers: ShapeMarker[]
  addShapeMarker: (kind: ShapeMarker['kind'], points: Point[]) => void
  removeShapeMarker: (id: string) => void
  resetViewSignal: number
  selectedMemberId: string | null
  
  // Drag State for Interactive Editing
  draggingMemberId: string | null
  dragEndpoint: 'start' | 'end' | null
  dragOffset: Point | null
  setDraggingMember: (id: string | null, endpoint: 'start' | 'end' | null, offset: Point | null) => void

  activeTab: 'Plans' | 'BOM'
  currentPageId: string | null
  currentPageIndex: number
  selectedRatio: number | null
  selectedScale: string | null
  wrapperSize: { w: number; h: number }
  imageNaturalWidth: number | null
  imageAspect: number

  // Member Segregation state
  selection: Set<string>
  hiddenIds: Set<string>
  isolation: { kind?: string; ids?: Set<string> } | null
  searchQuery: string
  zoomTarget: { id: string; nonce: number } | null

  // Layer Redesign slice
  layers: LayersState
  presets: LayerPreset[]

  // 3D split view — single source of truth shared between the project
  // layout (top-right "3D" toggle, persistent across every sub-route) and
  // the Plans page (which needs to hide its own right-side panels while
  // it's open, and to trigger a rebuild when a page's T.O.S. changes).
  show3d: boolean
  modelRefreshSignal: number
  // Which page's members most recently changed (edit/create/delete), if any
  // -- lets the 3D viewer force-refresh just that page's geometry instead of
  // silently no-op'ing (addPageMembers skips pages it already loaded unless
  // told force=true, which is correct for "don't re-add a page that hasn't
  // changed" but wrong for "this exact page's member WAS just edited").
  lastEditedPageId: string | null
  setShow3d: (show: boolean) => void
  toggleShow3d: () => void
  bumpModelRefresh: (pageId?: string) => void

  setTool: (tool: ToolType) => void
  setZoom: (zoom: number) => void
  setIsPanning: (panning: boolean) => void
  setCropMode: (mode: boolean) => void
  setCropDrag: (drag: CropRect | null) => void
  setCropRect: (rect: CropRect | null) => void
  setRulerStart: (pt: Point | null) => void
  setRulerEnd: (pt: Point | null) => void
  setRulerDragging: (dragging: boolean) => void
  addMarkerDot: (pt: Point) => void
  addRulerLine: (line: RulerLine) => void
  addTextMarker: (pt: Point, text: string) => void
  removeTextMarker: (id: string) => void
  removeMarkerDot: (index: number) => void
  removeRulerLine: (index: number) => void
  pushUndo: (type: 'marker' | 'ruler') => void
  popUndo: () => void
  redo: () => void
  triggerResetView: () => void
  selectMember: (id: string | null) => void
  setActiveTab: (tab: 'Plans' | 'BOM') => void
  setCurrentPage: (id: string | null, idx: number) => void
  setScale: (label: string | null, ratio: number | null) => void
  setWrapperSize: (w: number, h: number) => void
  setImageNaturalWidth: (w: number | null) => void
  setImageAspect: (a: number) => void
  pageGridDimensions: Record<string, any[]>
  gridDimensions: any[]
  setGridDimensions: (pageIdOrDims: any, maybeDims?: any[]) => void
  // Work Point (WP) marker -- the plan's implied origin grid intersection.
  // Mirrors the gridDimensions/pageGridDimensions pattern exactly: one entry
  // per page so switching pages doesn't show the previous page's WP for a
  // frame, plus the "currently active" convenience field the overlay reads.
  pageWorkPoint: Record<string, any | null>
  workPoint: any | null
  setWorkPoint: (pageIdOrWp: any, maybeWp?: any | null) => void
  resetTakeoffState: () => void

  // Member Segregation mutations
  setSelection: (ids: Set<string>) => void
  toggleSelection: (id: string) => void
  clearSelection: () => void
  toggleMemberVisibility: (id: string, visible?: boolean) => void
  showAllMembers: () => void
  setIsolation: (isolation: { kind?: string; ids?: Set<string> } | null) => void
  setSearchQuery: (q: string) => void
  setZoomTarget: (id: string | null) => void

  // Layer slice mutations
  toggleLayerVisibility: (kind: string) => void
  togglePlanVisibility: () => void
  setLayerOpacity: (kind: string, opacity: number) => void
  setLayerColor: (kind: string, hexColor: string) => void
  toggleAid: (aidName: string) => void
  setColorMode: (mode: 'kind' | 'status' | 'sequence' | 'weight' | 'labor_code' | 'paint') => void
  applyPreset: (presetId: string) => void
  savePreset: (name: string) => void
  deletePreset: (id: string) => void
  setPresetsFromServer: (serverPresets: LayerPreset[]) => void
  toggleLegendKey: (key: string) => void
}

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  activeTool: 'select',
  zoomLevel: 1.0,
  isPanning: false,
  cropMode: false,
  cropDrag: null,
  cropRect: null,
  rulerStart: null,
  rulerEnd: null,
  rulerDragging: false,
  markerDots: [],
  rulerLines: [],
  undoStack: [],
  redoStack: [],
  textMarkers: [],
  shapeMarkers: [],
  addShapeMarker: (kind, points) =>
    set((state) => ({
      shapeMarkers: [...state.shapeMarkers, { id: `shape-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, kind, points }],
    })),
  removeShapeMarker: (id) => set((state) => ({ shapeMarkers: state.shapeMarkers.filter((s) => s.id !== id) })),
  historyLog: [],
  pushHistoryLog: (kind, label) =>
    set((state) => ({
      historyLog: [
        ...state.historyLog,
        { id: `hist-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, ts: Date.now(), kind, label },
      ],
    })),
  clearHistoryLog: () => set({ historyLog: [] }),
  dirtyPageIds: new Set(),
  markPageDirty: (pageId) => set((state) => ({ dirtyPageIds: new Set(state.dirtyPageIds).add(pageId) })),
  clearPageDirty: (pageId) =>
    set((state) => {
      const next = new Set(state.dirtyPageIds)
      next.delete(pageId)
      return { dirtyPageIds: next }
    }),
  resetViewSignal: 0,
  selectedMemberId: null,
  draggingMemberId: null,
  dragEndpoint: null,
  dragOffset: null,
  activeTab: 'Plans',
  currentPageId: null,
  currentPageIndex: 0,
  selectedRatio: null,
  selectedScale: null,
  wrapperSize: { w: 1, h: 1 },
  imageNaturalWidth: null,
  imageAspect: 0.75,

  // State defaults
  selection: new Set<string>(),
  hiddenIds: new Set<string>(),
  isolation: null,
  searchQuery: '',
  zoomTarget: null,

  layers: getInitialLayers(),
  presets: getInitialPresets(),

  // Always starts closed — the 3D pane must never appear until the user
  // explicitly clicks the "3D" button in this session. Previously this read
  // a persisted localStorage flag, which meant a brand-new/empty project
  // could open with the 3D split-pane already showing (rendering a bare
  // spinner on a black background since there was no model yet).
  show3d: false,
  modelRefreshSignal: 0,
  lastEditedPageId: null,
  setShow3d: (show) => set({ show3d: show }),
  toggleShow3d: () => set((state) => ({ show3d: !state.show3d })),
  bumpModelRefresh: (pageId) => set((state) => ({ modelRefreshSignal: state.modelRefreshSignal + 1, lastEditedPageId: pageId ?? state.lastEditedPageId })),

  setDraggingMember: (id, endpoint, offset) => set({ draggingMemberId: id, dragEndpoint: endpoint, dragOffset: offset }),

  setTool: (tool) => set({ activeTool: tool }),
  setZoom: (zoom) => set({ zoomLevel: zoom }),
  setIsPanning: (panning) => set({ isPanning: panning }),
  setCropMode: (mode) => set({ cropMode: mode }),
  setCropDrag: (drag) => set({ cropDrag: drag }),
  setCropRect: (rect) => set({ cropRect: rect }),
  setRulerStart: (pt) => set({ rulerStart: pt }),
  setRulerEnd: (pt) => set({ rulerEnd: pt }),
  setRulerDragging: (dragging) => set({ rulerDragging: dragging }),
  addMarkerDot: (pt) => set((state) => ({ markerDots: [...state.markerDots, pt] })),
  addRulerLine: (line) => set((state) => ({ rulerLines: [...state.rulerLines, line] })),
  addTextMarker: (pt, text) =>
    set((state) => {
      const marker: TextMarker = { id: `txt-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, x: pt.x, y: pt.y, text }
      return { textMarkers: [...state.textMarkers, marker], undoStack: [...state.undoStack, 'text'] }
    }),
  removeTextMarker: (id) => set((state) => ({ textMarkers: state.textMarkers.filter((m) => m.id !== id) })),
  removeMarkerDot: (index) => set((state) => ({ markerDots: state.markerDots.filter((_, i) => i !== index) })),
  removeRulerLine: (index) => set((state) => ({ rulerLines: state.rulerLines.filter((_, i) => i !== index) })),
  pushUndo: (type) => set((state) => ({ undoStack: [...state.undoStack, type], redoStack: [] })),
  popUndo: () =>
    set((state) => {
      const nextStack = [...state.undoStack]
      const last = nextStack.pop()
      if (!last) return {}

      if (last === 'marker') {
        const nextMarkers = [...state.markerDots]
        const removed = nextMarkers.pop()
        const redoStack = removed ? [...state.redoStack, { type: 'marker' as const, data: removed }] : state.redoStack
        return { undoStack: nextStack, markerDots: nextMarkers, redoStack }
      } else if (last === 'text') {
        const nextMarkers = [...state.textMarkers]
        const removed = nextMarkers.pop()
        const redoStack = removed ? [...state.redoStack, { type: 'text' as const, data: removed }] : state.redoStack
        return { undoStack: nextStack, textMarkers: nextMarkers, redoStack }
      } else {
        const nextLines = [...state.rulerLines]
        const removed = nextLines.pop()
        const redoStack = removed ? [...state.redoStack, { type: 'ruler' as const, data: removed }] : state.redoStack
        return { undoStack: nextStack, rulerLines: nextLines, redoStack }
      }
    }),
  redo: () =>
    set((state) => {
      const nextRedo = [...state.redoStack]
      const entry = nextRedo.pop()
      if (!entry) return {}
      if (entry.type === 'marker') {
        return { redoStack: nextRedo, markerDots: [...state.markerDots, entry.data], undoStack: [...state.undoStack, 'marker'] }
      } else if (entry.type === 'text') {
        return { redoStack: nextRedo, textMarkers: [...state.textMarkers, entry.data], undoStack: [...state.undoStack, 'text'] }
      } else {
        return { redoStack: nextRedo, rulerLines: [...state.rulerLines, entry.data], undoStack: [...state.undoStack, 'ruler'] }
      }
    }),
  triggerResetView: () => set((state) => ({ resetViewSignal: state.resetViewSignal + 1, zoomLevel: 1.0 })),
  selectMember: (id) => set({ selectedMemberId: id, selection: id ? new Set([id]) : new Set() }),
  setActiveTab: (tab) => set({ activeTab: tab }),
  setCurrentPage: (id, idx) =>
    set((s) => {
      if (s.currentPageId === id && s.currentPageIndex === idx) return s
      return {
        currentPageId: id,
        currentPageIndex: idx,
        gridDimensions: (id && s.pageGridDimensions && s.pageGridDimensions[id]) ? s.pageGridDimensions[id] : [],
        workPoint: (id && s.pageWorkPoint && s.pageWorkPoint[id] !== undefined) ? s.pageWorkPoint[id] : null,
      }
    }),
  setScale: (label, ratio) =>
    set((s) => {
      if (s.selectedScale === label && s.selectedRatio === ratio) return s
      return { selectedScale: label, selectedRatio: ratio }
    }),

  setWrapperSize: (w, h) => set({ wrapperSize: { w, h } }),
  setImageNaturalWidth: (w) => set({ imageNaturalWidth: w }),
  setImageAspect: (a) => set({ imageAspect: a }),
  pageGridDimensions: {},
  gridDimensions: [],
  setGridDimensions: (pageIdOrDims: any, maybeDims?: any[]) => {
    if (typeof pageIdOrDims === 'string') {
      const pageId = pageIdOrDims
      const dims = maybeDims || []
      set((s) => {
        const prev = s.pageGridDimensions?.[pageId]
        if (prev === dims) return s
        if (Array.isArray(prev) && Array.isArray(dims) && prev.length === 0 && dims.length === 0) return s
        return {
          pageGridDimensions: { ...s.pageGridDimensions, [pageId]: dims },
          gridDimensions: s.currentPageId === pageId ? dims : s.gridDimensions,
        }
      })
    } else {
      const dims = pageIdOrDims || []
      set((s) => {
        if (s.gridDimensions === dims) return s
        if (Array.isArray(s.gridDimensions) && Array.isArray(dims) && s.gridDimensions.length === 0 && dims.length === 0) return s
        return {
          gridDimensions: dims,
          pageGridDimensions: s.currentPageId
            ? { ...s.pageGridDimensions, [s.currentPageId]: dims }
            : s.pageGridDimensions,
        }
      })
    }
  },
  pageWorkPoint: {},
  workPoint: null,
  setWorkPoint: (pageIdOrWp: any, maybeWp?: any | null) => {
    if (typeof pageIdOrWp === 'string') {
      const pageId = pageIdOrWp
      const wp = maybeWp ?? null
      set((s) => {
        const prev = s.pageWorkPoint?.[pageId]
        if (prev === wp) return s
        return {
          pageWorkPoint: { ...s.pageWorkPoint, [pageId]: wp },
          workPoint: s.currentPageId === pageId ? wp : s.workPoint,
        }
      })
    } else {
      const wp = pageIdOrWp ?? null
      set((s) => {
        if (s.workPoint === wp) return s
        return {
          workPoint: wp,
          pageWorkPoint: s.currentPageId
            ? { ...s.pageWorkPoint, [s.currentPageId]: wp }
            : s.pageWorkPoint,
        }
      })
    }
  },
  resetTakeoffState: () =>
    set((state) => {
      const defaultLayers = {
        classVisibility: { beam: true, column: true, vbrace: true, hbrace: true, joist: true, unlabelled: true },
        classOpacity: { beam: 1.0, column: 1.0, vbrace: 1.0, hbrace: 1.0, joist: 1.0, unlabelled: 1.0 },
        classColors: { column: '#38BDF8', beam: '#BE185D', vbrace: '#D97706', hbrace: '#0E7490', joist: '#7C3AED', unlabelled: '#64748B' },
        planVisible: true,
        aids: {
          markers: true,
          rulers: true,
          labels: true,
          confidenceHalo: false,
          detectionRegion: false,
          grid: false,
          piecemarks: true,
          lengths: true,
          reactions: false,
          columnProjections: true,
          lengthFilter: false,
          gridDimensions: true,
        },
        colorMode: 'kind' as const,
        activePresetId: null,
        hiddenLegendKeys: new Set<string>()
      }
      localStorage.setItem('calsteel-layers', JSON.stringify({ ...defaultLayers, hiddenLegendKeys: [] }))
      return {
        activeTool: 'select',
        zoomLevel: 1.0,
        isPanning: false,
        cropMode: false,
        cropDrag: null,
        cropRect: null,
        rulerStart: null,
        rulerEnd: null,
        rulerDragging: false,
        markerDots: [],
        rulerLines: [],
        undoStack: [],
        redoStack: [],
        textMarkers: [],
        shapeMarkers: [],
        historyLog: [],
        dirtyPageIds: new Set(),
        selectedMemberId: null,
        selection: new Set(),
        hiddenIds: new Set(),
        isolation: null,
        zoomTarget: null,
        layers: defaultLayers
      }
    }),

  // Mutations
  setSelection: (ids) => set({ selection: ids }),
  toggleSelection: (id) =>
    set((state) => {
      const next = new Set(state.selection)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      const singleId = next.size === 1 ? Array.from(next)[0] : null
      return { selection: next, selectedMemberId: singleId }
    }),
  clearSelection: () => set({ selection: new Set(), selectedMemberId: null }),
  toggleMemberVisibility: (id, visible) =>
    set((state) => {
      const next = new Set(state.hiddenIds)
      const shouldHide = visible !== undefined ? !visible : !next.has(id)
      if (shouldHide) {
        next.add(id)
      } else {
        next.delete(id)
      }
      return { hiddenIds: next }
    }),
  showAllMembers: () =>
    set((state) => {
      const nextLayers = {
        ...state.layers,
        classVisibility: { beam: true, column: true, vbrace: true, hbrace: true, joist: true, unlabelled: true },
        hiddenLegendKeys: new Set<string>()
      }
      localStorage.setItem('calsteel-layers', JSON.stringify({ ...nextLayers, hiddenLegendKeys: [] }))
      return { hiddenIds: new Set(), layers: nextLayers }
    }),
  setIsolation: (iso) => set({ isolation: iso }),
  setSearchQuery: (q) => set({ searchQuery: q }),
  setZoomTarget: (id) =>
    set((state) => ({
      zoomTarget: id ? { id, nonce: (state.zoomTarget?.nonce ?? 0) + 1 } : null,
    })),

  // Layer slice mutations
  toggleLayerVisibility: (kind) =>
    set((state) => {
      const nextVis = { ...state.layers.classVisibility, [kind]: !state.layers.classVisibility[kind] }
      const nextLayers = { ...state.layers, classVisibility: nextVis, activePresetId: null }
      localStorage.setItem('calsteel-layers', JSON.stringify({ ...nextLayers, hiddenLegendKeys: Array.from(nextLayers.hiddenLegendKeys) }))
      return { layers: nextLayers }
    }),
  togglePlanVisibility: () =>
    set((state) => {
      const nextLayers = { ...state.layers, planVisible: !state.layers.planVisible }
      localStorage.setItem('calsteel-layers', JSON.stringify({ ...nextLayers, hiddenLegendKeys: Array.from(nextLayers.hiddenLegendKeys) }))
      return { layers: nextLayers }
    }),
  setLayerOpacity: (kind, opacity) =>
    set((state) => {
      const nextOp = { ...state.layers.classOpacity, [kind]: opacity }
      const nextLayers = { ...state.layers, classOpacity: nextOp, activePresetId: null }
      localStorage.setItem('calsteel-layers', JSON.stringify({ ...nextLayers, hiddenLegendKeys: Array.from(nextLayers.hiddenLegendKeys) }))
      return { layers: nextLayers }
    }),
  setLayerColor: (kind, hexColor) =>
    set((state) => {
      const nextColors = { ...state.layers.classColors, [kind]: hexColor }
      const nextLayers = { ...state.layers, classColors: nextColors }
      localStorage.setItem('calsteel-layers', JSON.stringify({ ...nextLayers, hiddenLegendKeys: Array.from(nextLayers.hiddenLegendKeys) }))
      return { layers: nextLayers }
    }),
  toggleAid: (aidName) =>
    set((state) => {
      const nextAids = { ...state.layers.aids, [aidName as keyof typeof state.layers.aids]: !state.layers.aids[aidName as keyof typeof state.layers.aids] }
      const nextLayers = { ...state.layers, aids: nextAids, activePresetId: null }
      localStorage.setItem('calsteel-layers', JSON.stringify({ ...nextLayers, hiddenLegendKeys: Array.from(nextLayers.hiddenLegendKeys) }))
      return { layers: nextLayers }
    }),
  setColorMode: (mode) =>
    set((state) => {
      const nextLayers = { ...state.layers, colorMode: mode, activePresetId: null }
      localStorage.setItem('calsteel-layers', JSON.stringify({ ...nextLayers, hiddenLegendKeys: Array.from(nextLayers.hiddenLegendKeys) }))
      return { layers: nextLayers }
    }),
  applyPreset: (presetId) =>
    set((state) => {
      const preset = state.presets.find((p) => p.id === presetId)
      if (!preset) return {}
      const nextLayers = {
        classVisibility: { ...preset.classVisibility },
        classOpacity: { ...preset.classOpacity },
        classColors: { ...preset.classColors },
        planVisible: true,
        aids: { ...preset.aids },
        colorMode: preset.colorMode,
        activePresetId: presetId,
        hiddenLegendKeys: new Set<string>()
      }
      localStorage.setItem('calsteel-layers', JSON.stringify({ ...nextLayers, hiddenLegendKeys: [] }))
      return { layers: nextLayers }
    }),
  savePreset: (name) =>
    set((state) => {
      const newPreset: LayerPreset = {
        id: 'preset-' + Date.now(),
        name,
        classVisibility: { ...state.layers.classVisibility },
        classOpacity: { ...state.layers.classOpacity },
        classColors: { ...state.layers.classColors },
        aids: { ...state.layers.aids },
        colorMode: state.layers.colorMode,
      }
      const userPresetsOnly = state.presets.filter((p) => !DEFAULT_PRESETS.find((d) => d.id === p.id))
      const nextUserPresets = [...userPresetsOnly, newPreset]
      localStorage.setItem('calsteel-presets', JSON.stringify(nextUserPresets))

      const nextPresets = [...state.presets, newPreset]
      return { presets: nextPresets, layers: { ...state.layers, activePresetId: newPreset.id } }
    }),
  deletePreset: (id) =>
    set((state) => {
      if (DEFAULT_PRESETS.find((d) => d.id === id)) return {}
      const nextPresets = state.presets.filter((p) => p.id !== id)
      const userPresetsOnly = nextPresets.filter((p) => !DEFAULT_PRESETS.find((d) => d.id === p.id))
      localStorage.setItem('calsteel-presets', JSON.stringify(userPresetsOnly))
      return {
        presets: nextPresets,
        layers: {
          ...state.layers,
          activePresetId: state.layers.activePresetId === id ? null : state.layers.activePresetId,
        },
      }
    }),
  setPresetsFromServer: (serverPresets) =>
    set((state) => {
      const userPresets = serverPresets.filter((sp) => !DEFAULT_PRESETS.find((d) => d.id === sp.id))
      return { presets: [...DEFAULT_PRESETS, ...userPresets] }
    }),
  toggleLegendKey: (key) =>
    set((state) => {
      const next = new Set(state.layers.hiddenLegendKeys)
      if (next.has(key)) {
        next.delete(key)
      } else {
        next.add(key)
      }
      const nextLayers = { ...state.layers, hiddenLegendKeys: next }
      localStorage.setItem('calsteel-layers', JSON.stringify({ ...nextLayers, hiddenLegendKeys: Array.from(next) }))
      return { layers: nextLayers }
    }),
}))

export const getMemberRenderProps = (
  state: { layers: LayersState; hiddenIds: Set<string>; isolation: { kind?: string; ids?: Set<string> } | null },
  member: {
    id: string
    kind: string
    confidence?: number | null
    status?: string
    section?: string | null
    // Sourced from the matching bom_items row (joined by member_id) once a
    // build has run -- these are SteelGenie's actual "Color By" fields, not
    // ones we invented. Null/undefined until Build has produced a BOM.
    sequence?: number | string | null
    weight_lbs?: number | null
    labor_code?: string | null
    paint?: string | null
  }
) => {
  const { layers, hiddenIds, isolation } = state
  const sectionStr = (member.section || '').trim().toUpperCase()
  const isExplicitBeam = member.kind === 'beam' && /^(W\d|HSS|C\d|MC\d|L\d|PIPE|ISA)/.test(sectionStr)
  const isExplicitJoist = member.kind === 'joist' ||
    /\d{1,2}(?:K|LH|DLH|KSP|G|CJ|CS)/.test(sectionStr) ||
    sectionStr.includes('JOIST')

  let mKind = (member.kind || 'beam').toLowerCase()
  if (isExplicitJoist || (!isExplicitBeam && member.kind !== 'column' && member.kind !== 'footing')) {
    mKind = 'joist'
  } else if (isExplicitBeam) {
    mKind = 'beam'
  }

  const weightTier = (w: number | null | undefined): string => {
    if (w === null || w === undefined) return 'Unbuilt'
    if (w < 100) return '< 100 lb'
    if (w < 300) return '100–300 lb'
    if (w < 600) return '300–600 lb'
    return '> 600 lb'
  }

  // 1. Central Legend toggle checks
  if (layers.hiddenLegendKeys && layers.hiddenLegendKeys.size > 0) {
    if (layers.colorMode === 'status' && member.status && layers.hiddenLegendKeys.has(member.status)) {
      return { visible: false, color: '#64748B', opacity: 0 }
    }
    if (layers.colorMode === 'sequence') {
      const key = member.sequence !== null && member.sequence !== undefined ? String(member.sequence) : 'Unsequenced'
      if (layers.hiddenLegendKeys.has(key)) {
        return { visible: false, color: '#64748B', opacity: 0 }
      }
    }
    if (layers.colorMode === 'weight' && layers.hiddenLegendKeys.has(weightTier(member.weight_lbs))) {
      return { visible: false, color: '#64748B', opacity: 0 }
    }
    if (layers.colorMode === 'labor_code') {
      const key = member.labor_code || 'Unassigned'
      if (layers.hiddenLegendKeys.has(key)) {
        return { visible: false, color: '#64748B', opacity: 0 }
      }
    }
    if (layers.colorMode === 'paint') {
      const key = member.paint || 'Unpainted'
      if (layers.hiddenLegendKeys.has(key)) {
        return { visible: false, color: '#64748B', opacity: 0 }
      }
    }
  }

  // 2. Determine visibility
  let visible = true

  // Check if member is hidden by ID
  if (hiddenIds.has(member.id)) {
    visible = false
  }

  // Check if member class is visible
  let classKey = mKind
  if (mKind === 'brace') classKey = 'vbrace'
  if (mKind === 'vbrace') classKey = 'vbrace'
  if (mKind === 'hbrace') classKey = 'hbrace'

  if (layers.classVisibility[classKey] === false) {
    visible = false
  }

  // Handle isolation (solo category or IDs)
  if (isolation) {
    if (isolation.kind) {
      const isMatch =
        mKind === isolation.kind ||
        (isolation.kind === 'vbrace' && (mKind === 'vbrace' || mKind === 'hbrace' || mKind === 'brace'))
      if (!isMatch) {
        visible = false
      }
    } else if (isolation.ids && !isolation.ids.has(member.id)) {
      visible = false
    }
  }

  // 3. Determine color
  let color = layers.classColors[classKey] || '#10B981'

  // If isolation is active for a category and matches, it should be colored green
  if (isolation && isolation.kind) {
    const isMatch =
      mKind === isolation.kind ||
      (isolation.kind === 'vbrace' && (mKind === 'vbrace' || mKind === 'hbrace' || mKind === 'brace'))
    if (isMatch) {
      color = '#10B981' // Green
    }
  } else {
    // If not isolated, respect colorMode
    const hashColor = (key: string): string => {
      let hash = 0
      for (let i = 0; i < key.length; i++) {
        hash = key.charCodeAt(i) + ((hash << 5) - hash)
      }
      const colors = ['#3B82F6', '#EF4444', '#10B981', '#F59E0B', '#8B5CF6', '#EC4899', '#06B6D4', '#14B8A6']
      return colors[Math.abs(hash) % colors.length]
    }

    if (layers.colorMode === 'status') {
      if (member.status === 'verified') color = '#10B981'
      else if (member.status === 'rejected') color = '#EF4444'
      else if (member.status === 'need_review') color = '#F59E0B'
      else color = '#64748B'
    } else if (layers.colorMode === 'sequence') {
      const key = member.sequence !== null && member.sequence !== undefined ? String(member.sequence) : 'Unsequenced'
      color = key === 'Unsequenced' ? '#64748B' : hashColor(key)
    } else if (layers.colorMode === 'weight') {
      const tier = weightTier(member.weight_lbs)
      if (tier === '< 100 lb') color = '#10B981'
      else if (tier === '100–300 lb') color = '#3B82F6'
      else if (tier === '300–600 lb') color = '#F59E0B'
      else if (tier === '> 600 lb') color = '#EF4444'
      else color = '#64748B'
    } else if (layers.colorMode === 'labor_code') {
      const key = member.labor_code || 'Unassigned'
      color = key === 'Unassigned' ? '#64748B' : hashColor(key)
    } else if (layers.colorMode === 'paint') {
      const key = member.paint || 'Unpainted'
      color = key === 'Unpainted' ? '#94A3B8' : hashColor(key)
    }
  }

  // 4. Determine opacity
  let opacity = layers.classOpacity[classKey] ?? 1.0
  if (isolation && !isolation.kind && isolation.ids && !isolation.ids.has(member.id)) {
    // Dimmed state for specific selection isolation
    opacity = 0.15
    visible = true
  }

  return { visible, color, opacity }
}
