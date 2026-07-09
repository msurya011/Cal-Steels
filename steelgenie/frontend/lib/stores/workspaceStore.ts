import { create } from 'zustand'

export type ToolType = 'select' | 'hand' | 'ruler' | 'marker' | 'column' | 'beam' | 'brace'

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
  undoStack: ('marker' | 'ruler')[]
  selectedMemberId: string | null
  activeTab: 'Plans' | 'BOM'
  currentPageId: string | null
  currentPageIndex: number
  selectedRatio: number | null
  selectedScale: string | null
  wrapperSize: { w: number; h: number }
  imageNaturalWidth: number | null
  imageAspect: number

  // New Member Segregation state
  selection: Set<string>
  hiddenKinds: Set<string>
  hiddenIds: Set<string>
  isolation: { kind?: string; ids?: Set<string> } | null
  colorMode: 'kind' | 'status' | 'confidence'
  searchQuery: string
  zoomTarget: { id: string; nonce: number } | null

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
  pushUndo: (type: 'marker' | 'ruler') => void
  popUndo: () => void
  selectMember: (id: string | null) => void
  setActiveTab: (tab: 'Plans' | 'BOM') => void
  setCurrentPage: (id: string | null, idx: number) => void
  setScale: (label: string | null, ratio: number | null) => void
  setWrapperSize: (w: number, h: number) => void
  setImageNaturalWidth: (w: number | null) => void
  setImageAspect: (a: number) => void
  resetTakeoffState: () => void

  // New Member Segregation mutations
  setSelection: (ids: Set<string>) => void
  toggleSelection: (id: string) => void
  clearSelection: () => void
  toggleKindVisibility: (kind: string, visible?: boolean) => void
  toggleMemberVisibility: (id: string, visible?: boolean) => void
  showAllMembers: () => void
  setIsolation: (isolation: { kind?: string; ids?: Set<string> } | null) => void
  setColorMode: (mode: 'kind' | 'status' | 'confidence') => void
  setSearchQuery: (q: string) => void
  setZoomTarget: (id: string | null) => void
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
  selectedMemberId: null,
  activeTab: 'Plans',
  currentPageId: null,
  currentPageIndex: 0,
  selectedRatio: null,
  selectedScale: null,
  wrapperSize: { w: 1, h: 1 },
  imageNaturalWidth: null,
  imageAspect: 0.75,

  // New state defaults
  selection: new Set<string>(),
  hiddenKinds: new Set<string>(),
  hiddenIds: new Set<string>(),
  isolation: null,
  colorMode: 'kind',
  searchQuery: '',
  zoomTarget: null,

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
  pushUndo: (type) => set((state) => ({ undoStack: [...state.undoStack, type] })),
  popUndo: () =>
    set((state) => {
      const nextStack = [...state.undoStack]
      const last = nextStack.pop()
      if (!last) return {}

      if (last === 'marker') {
        const nextMarkers = [...state.markerDots]
        nextMarkers.pop()
        return { undoStack: nextStack, markerDots: nextMarkers }
      } else {
        const nextLines = [...state.rulerLines]
        nextLines.pop()
        return { undoStack: nextStack, rulerLines: nextLines }
      }
    }),
  selectMember: (id) => set({ selectedMemberId: id, selection: id ? new Set([id]) : new Set() }),
  setActiveTab: (tab) => set({ activeTab: tab }),
  setCurrentPage: (id, idx) => set({ currentPageId: id, currentPageIndex: idx }),
  setScale: (label, ratio) => set({ selectedScale: label, selectedRatio: ratio }),
  setWrapperSize: (w, h) => set({ wrapperSize: { w, h } }),
  setImageNaturalWidth: (w) => set({ imageNaturalWidth: w }),
  setImageAspect: (a) => set({ imageAspect: a }),
  resetTakeoffState: () =>
    set({
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
      selectedMemberId: null,
      selection: new Set(),
      hiddenKinds: new Set(),
      hiddenIds: new Set(),
      isolation: null,
      zoomTarget: null,
    }),

  // New mutations
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
  toggleKindVisibility: (kind, visible) =>
    set((state) => {
      const next = new Set(state.hiddenKinds)
      const shouldHide = visible !== undefined ? !visible : !next.has(kind)
      if (shouldHide) {
        next.add(kind)
      } else {
        next.delete(kind)
      }
      return { hiddenKinds: next }
    }),
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
  showAllMembers: () => set({ hiddenKinds: new Set(), hiddenIds: new Set() }),
  setIsolation: (iso) => set({ isolation: iso }),
  setColorMode: (mode) => set({ colorMode: mode }),
  setSearchQuery: (q) => set({ searchQuery: q }),
  setZoomTarget: (id) =>
    set((state) => ({
      zoomTarget: id ? { id, nonce: (state.zoomTarget?.nonce ?? 0) + 1 } : null,
    })),
}))
